"""
Unit tests for v6.4.2 fixes (Review #24 + C-39..C-48 + Wave 3a polish).
"""

import json
import os
import sys
import time
import types
import unittest
from unittest.mock import MagicMock, patch

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_TEST_DIR, '..', '..'))
_ADDON_ROOT = os.path.join(_REPO_ROOT, 'plugin.video.otaku.rpdev')
_CTX_ROOT = os.path.join(_REPO_ROOT, 'context.otaku.rpdev')
for _p in (_REPO_ROOT, _ADDON_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import tests.conftest  # noqa: E402, F401
from resources.lib.ui import client, control, database_sync, domains, player  # noqa: E402
from resources.lib.routes import playback  # noqa: E402


class TestV642Hardening(unittest.TestCase):

    def setUp(self):
        control.playerWindow.clearProperty('otaku.preResolved_url')
        control.playerWindow.clearProperty('otaku.preResolved_malId')
        control.playerWindow.clearProperty('otaku.preResolved_episode')
        control.playerWindow.clearProperty('otaku.preResolved_data')
        control.playerWindow.clearProperty('otaku.active_source_is_dub')

    def test_c45_preresolved_handoff_skips_probe_within_30m_and_reprobes_after_30m(self):
        pr_data = {
            'url': 'https://cdn.example/master.m3u8',
            'headers': {},
            'source': {'provider': 'hianime', 'type': 'direct', 'info': ['megaplay DUB'], 'lang': 3},
            'sub': [],
            'resolved_at': time.time() - 360,  # 6 minutes old (normal 70%->PlayNext gap)
        }
        control.playerWindow.setProperty('otaku.preResolved_url', pr_data['url'])
        control.playerWindow.setProperty('otaku.preResolved_malId', '51711')
        control.playerWindow.setProperty('otaku.preResolved_episode', '2')
        control.playerWindow.setProperty('otaku.preResolved_data', json.dumps(pr_data))

        with patch('resources.lib.windows.resolver.Resolver.prefetch_play_link') as mock_probe, \
             patch('resources.lib.ui.player.WatchlistPlayer.handle_player'), \
             patch('resources.lib.ui.control.getBool', side_effect=lambda k, default=False: True if k == 'smartplay.preresolve' else default), \
             patch('resources.lib.ui.control.HANDLE', 1), \
             patch('resources.lib.ui.control.exit_code'), \
             patch('xbmcplugin.setResolvedUrl'):
            hit = playback._try_preresolved_handoff('51711', '2', {}, None)
        self.assertTrue(hit)
        mock_probe.assert_not_called()
        self.assertEqual(control.playerWindow.getProperty('otaku.active_source_is_dub'), 'true')

        # Now simulate >30 min stale pre-resolved URL that fails re-probe -> falls back cleanly
        pr_data['resolved_at'] = time.time() - 2400
        control.playerWindow.setProperty('otaku.preResolved_url', pr_data['url'])
        control.playerWindow.setProperty('otaku.preResolved_malId', '51711')
        control.playerWindow.setProperty('otaku.preResolved_episode', '5')
        control.playerWindow.setProperty('otaku.preResolved_data', json.dumps(pr_data))
        with patch('resources.lib.ui.control.getBool', side_effect=lambda k, default=False: True if k == 'smartplay.preresolve' else default), \
             patch('resources.lib.windows.resolver.Resolver.prefetch_play_link', return_value=None) as mock_probe2:
            hit2 = playback._try_preresolved_handoff('51711', '5', {}, None)
        self.assertFalse(hit2)
        mock_probe2.assert_called_once()

    def test_c45_player_onplaybackerror_triggers_startup_failover(self):
        p = player.WatchlistPlayer()
        p.mal_id = 51711
        p.episode = 5
        p.total_time = 0
        p.current_time = 0
        p._user_stopped_or_errored = False
        p._failover_triggered = False
        with patch.object(p, '_attempt_midstream_failover', return_value=True) as mock_failover:
            p.onPlayBackError()
        mock_failover.assert_called_once_with('startup_error')

    def test_c48_single_track_und_audio_uses_dub_hint(self):
        p = player.WatchlistPlayer()
        p.preferred_audio = 1
        p.preferred_subtitle_setting = 1
        p.preferred_subtitle_keyword = 4
        p.preferred_subtitle_type = 0
        p._series_audio_override = False
        p._series_sub_override = False
        p._series_sub_mode_override = False
        control.playerWindow.setProperty('otaku.active_source_is_dub', 'true')

        with patch.object(control, 'getBool', side_effect=lambda k, default=False: {
            'general.kodi_language': False,
            'general.subtitles.keyword': True,
            'general.subtitles.type': False,
            'general.dubsubtitles': False,
            'subtitles.enabled': True,
            'subtitles.auto_search': True,
            'subtitles.prefer_forced': False,
        }.get(k, default)), \
             patch.object(p, '_query_player_streams', return_value=([{'index': 0, 'language': 'und', 'name': ''}], [{'index': 0, 'language': 'eng', 'name': 'English'}])), \
             patch.object(p, 'setAudioStream'), \
             patch.object(p, 'setSubtitleStream'), \
             patch.object(p, 'showSubtitles') as mock_show, \
             patch.object(p, '_trigger_auto_subtitle_download') as mock_dl:
            p.setup_audio_and_subtitles()
        mock_dl.assert_not_called()
        mock_show.assert_called_once_with(False)

    def test_c47_database_sync_merges_new_hianime_embed_servers(self):
        stored = ['vidstreaming', 'megacloud']
        with patch.object(database_sync.control, 'getStringList', return_value=list(stored)), \
             patch.object(database_sync.control, 'setStringList') as mock_set, \
             patch.object(database_sync.control, 'getBool', return_value=False), \
             patch.object(database_sync.SyncDatabase, '_create_all_tables'), \
             patch.object(database_sync.SyncDatabase, 'refresh_activites'), \
             patch.object(database_sync.SyncDatabase, '_migrate_database'):
            sd = database_sync.SyncDatabase.__new__(database_sync.SyncDatabase)
            sd.activites = {'otaku_version': '1.0.14'}
            sd.last_meta_update = database_sync.SyncDatabase.SCHEMA_VERSION
            sd.check_database_version()
        embed_calls = [c[0][1] for c in mock_set.call_args_list if c[0][0] == 'embed.config']
        self.assertTrue(embed_calls)
        merged = embed_calls[-1]
        for srv in ('ryu', 'volt', 'ayame'):
            self.assertIn(srv, merged)
        self.assertIn('vidstreaming', merged)

    def test_c43_client_jpost_preserves_json_content_type_on_cf_retry(self):
        seen_requests = []

        class _FakeResp:
            status = 200
            code = 200
            headers = {}
            def info(self):
                return self.headers
            def read(self):
                return b'{"ok":true}'
            def close(self):
                pass

        import urllib.error
        import io
        cf_err = urllib.error.HTTPError(
            'https://example.test/api',
            403,
            'Forbidden',
            {'Server': 'cloudflare', 'cf-mitigated': 'challenge'},
            io.BytesIO(b'Just a moment...'),
        )

        def _fake_open(req, timeout=None):
            seen_requests.append((req.data, dict(req.header_items())))
            if len(seen_requests) == 1:
                raise cf_err
            return _FakeResp()

        fake_opener = MagicMock()
        fake_opener.open.side_effect = _fake_open

        with patch('urllib.request.build_opener', return_value=fake_opener), \
             patch.object(client.control, 'getBool', side_effect=lambda k, default=False: True if k == 'fs_enable' else default), \
             patch.object(client.cfcookie, 'get', return_value=('cf_clearance=abc', 'TestUA/1.0')):
            res = client.request('https://example.test/api', post={'hello': 'world'}, jpost=True, use_session=False)

        self.assertEqual(res, b'{"ok":true}')
        self.assertEqual(len(seen_requests), 2)
        retry_body, retry_headers = seen_requests[1]
        self.assertEqual(retry_body, b'{"hello": "world"}')
        lower_hdrs = {k.lower(): v for k, v in retry_headers.items()}
        self.assertEqual(lower_hdrs.get('content-type'), 'application/json')

    def test_c41_process_context_and_context_addon_scripts(self):
        with patch.object(control.settings, 'getBool', return_value=True):
            control.process_context()
        self.assertEqual(control.homeWindow.getProperty('context.otaku.rpdev.markedasunwatched'), 'true')
        self.assertEqual(control.homeWindow.getProperty('context.otaku.rpdev.seriesprofile'), 'true')

        import importlib.util
        ctx_path = os.path.join(_CTX_ROOT, 'default.py')
        spec = importlib.util.spec_from_file_location('ctx_default_test', ctx_path)
        ctx_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ctx_mod)

        fake_item = MagicMock()
        fake_item.getPath.return_value = 'plugin://plugin.video.otaku.rpdev/play/51711/6?auto_resume=1'
        vinfo = MagicMock()
        vinfo.getTitle.return_value = 'Ep 6'
        vinfo.getMediaType.return_value = 'episode'
        vinfo.getTVShowTitle.return_value = ''
        vinfo.getPlot.return_value = ''
        vinfo.getYear.return_value = 0
        vinfo.getPremieredAsW3C.return_value = ''
        vinfo.getSeason.return_value = 1
        vinfo.getEpisode.return_value = 6
        vinfo.getFirstAiredAsW3C.return_value = ''
        vinfo.getRating.return_value = 0
        vinfo.getResumeTime.return_value = 0
        vinfo.getUniqueIDs.return_value = {'mal_id': '51711'}
        fake_item.getVideoInfoTag.return_value = vinfo
        fake_item.getArt.return_value = ''
        fake_item.getProperty.return_value = ''

        executed = []
        with patch.object(sys, 'argv', ['default.py', 'rescrape']), \
             patch.object(sys, 'listitem', fake_item, create=True), \
             patch.object(ctx_mod.xbmc, 'executebuiltin', side_effect=executed.append):
            ctx_mod.main()
        self.assertEqual(len(executed), 1)
        self.assertIn('auto_resume=1', executed[0])
        self.assertIn('rescrape=true', executed[0])

        # Logout slices first path segment only
        fake_item.getPath.return_value = 'plugin://plugin.video.otaku.rpdev/watchlist/anilist/CURRENT'
        executed.clear()
        with patch.object(sys, 'argv', ['default.py', 'logout']), \
             patch.object(sys, 'listitem', fake_item, create=True), \
             patch.object(ctx_mod.xbmc, 'executebuiltin', side_effect=executed.append):
            ctx_mod.main()
        self.assertEqual(executed, ['RunPlugin(plugin://plugin.video.otaku.rpdev/watchlist_logout/anilist)'])

    def test_c42_search_filter_non_folder_and_scene_jump_guide(self):
        from resources.lib.routes import search as search_routes
        from resources.lib.routes import tools as tools_routes
        from resources.lib import Main
        drawn = []
        with patch.object(search_routes.database, 'browse_mappings_by_year_season', return_value=([{'mal_id': 1, 'mal_title': 'Test'}], False)), \
             patch.object(search_routes.utils, 'allocate_offline_mapping_items', return_value=[]), \
             patch.object(search_routes.control, 'draw_items', side_effect=lambda items, *a: drawn.extend(items)):
            search_routes.BROWSE_YEAR_SEASON('2025/WINTER', {})
        self.assertTrue(drawn)
        self.assertFalse(drawn[0]['isfolder'])

        tool_urls = [u for _, u, _, _ in Main.get_menu_items('tools')]
        for expected in ('source_filter', 'browse_year_season', 'watchlist_drift_auditor', 'watchlist_telemetry', 'scene_jump_guide', 'backup_settings'):
            self.assertIn(expected, tool_urls)

        with patch('xbmc.Player.isPlayingVideo', return_value=False), \
             patch.object(tools_routes.control, 'textviewer_dialog') as mock_tv, \
             patch.object(tools_routes.control, 'exit_code'):
            tools_routes.SCENE_JUMP_GUIDE('', {})
        mock_tv.assert_called_once()

    def test_wave3a_opensubtitles_401_clears_token_and_animekai_rejects_mismatch(self):
        from resources.lib.subtitles.services import opensubtitles
        from resources.lib.subtitles.models import VideoMeta
        opensubtitles._token_cache = {'token': 'stale-jwt', 'expires_at': time.time() + 3600}
        resp_401 = MagicMock(status_code=401)
        with patch('resources.lib.ui.client.get', return_value=resp_401):
            res = opensubtitles.OpenSubtitlesService.search(VideoMeta(title='Test'), {})
        self.assertEqual(res, [])
        self.assertEqual(opensubtitles._token_cache, {})

        from resources.lib.pages import animekai
        ak = animekai.Sources()
        html_body = '<a class="aitem" href="/watch/completely-wrong-show"><h6 class="title" data-jp="Wrong">Completely Wrong Show</h6></a>'
        fake_json = json.dumps({'result': {'html': html_body}})
        with patch.object(ak, '_get_request', return_value=fake_json):
            slug = ak._search_anime('The Iceblade Sorcerer Shall Rule the World', {}, mal_id=51711)
        self.assertIsNone(slug)

    def test_resolve_trakt_season_episode_handles_multi_season_and_split_cour_tvdb_rules(self):
        from resources.lib.ui import player
        rules = [
            {'season': 1, 'range_start': 1, 'range_end': 8, 'ep_start': 1},
            {'season': 2, 'range_start': 1, 'range_end': 22, 'ep_start': 9},
            {'season': 3, 'range_start': 13, 'range_end': 24, 'ep_start': 31},
        ]
        with patch.object(player.database, 'get_mappings', return_value={'thetvdb_season': 'a'}), \
             patch.object(player.database, 'get_tvdb_rules', return_value=rules):
            self.assertEqual(player.resolve_trakt_season_episode(21, episode=5), (1, 5))
            self.assertEqual(player.resolve_trakt_season_episode(21, episode=10), (2, 2))
            self.assertEqual(player.resolve_trakt_season_episode(21, episode=31), (3, 13))


if __name__ == '__main__':
    unittest.main()
