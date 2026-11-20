"""
Unit tests for v6.2.9 Deep Concerns Audit Remediations:
- C-01 / C-13: domains.join_url for translate.goog alt URLs, Window(10000)-persisted mirror &
               ScraperCircuitBreaker cooldowns, and AnimePahe cooldown check before MALSync lookup
- C-03 / C-09: Resolver marks failing embed/direct stream host in persistent cooldown and
               stably deprioritizes sibling candidates sharing that host
- C-06: control.end_directory(handle=0) properly terminates handle 0
- C-07: WatchlistPlayer never passes raw http(s):// stream URLs to Files.SetFileDetails on EOF/stop;
        hook_mimetype normalizes case & parameters and matches application/x-mpegurl
- C-10 / C-11: embed_extractor.get_sub logs total failure at warning + strips malformed '<}' VTT tags;
               player.score_subtitle_stream prefers external subtitle tracks on ties
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(
    os.path.join(_TEST_DIR, '..' if os.path.basename(_TEST_DIR) in ('unit', 'integration', 'lint') else '.')
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
_TESTS_DIR = os.path.join(_REPO_ROOT, 'tests')
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import conftest  # noqa: F401
from resources.lib import pages
from resources.lib.pages import animepahe
from resources.lib.ui import control, domains, embed_extractor, player
from resources.lib.windows import resolver


class TestConcernsDeepAuditV629(unittest.TestCase):

    def setUp(self):
        domains.clear_mirror_failures()
        pages.circuit_breaker.reset()

    def tearDown(self):
        domains.clear_mirror_failures()
        pages.circuit_breaker.reset()

    def test_domains_join_url_preserves_translate_goog_query_params(self):
        """C-01: domains.join_url appends path before query string for translate.goog alt URLs."""
        alt_base = 'https://animepahe-pw.translate.goog/?_x_tr_sl=auto&_x_tr_tl=en&_x_tr_hl=en&_x_tr_pto=wapp'
        api_url = domains.join_url(alt_base, 'api')
        self.assertTrue(api_url.startswith('https://animepahe-pw.translate.goog/api?'))
        self.assertIn('_x_tr_pto=wapp', api_url)
        self.assertNotIn('wapp/api', api_url)

        tosho_alt = 'https://animetosho-org.translate.goog/?_x_tr_sl=es&_x_tr_tl=en&_x_tr_hl=en'
        search_url = domains.join_url(tosho_alt, 'search')
        self.assertTrue(search_url.startswith('https://animetosho-org.translate.goog/search?'))
        self.assertNotIn('en/search', search_url)

        normal_url = domains.join_url('https://animepahe.pw/', 'play/slug123/ep456')
        self.assertEqual(normal_url, 'https://animepahe.pw/play/slug123/ep456')

    def test_mirror_cooldown_and_circuit_breaker_persist_across_invocations(self):
        """C-01 / C-13: Cooldowns persist in Window(10000) even when in-memory dicts reset."""
        domains.mark_mirror_failure('https://animepahe.pw/', cooldown=600)
        self.assertFalse(domains.is_mirror_healthy('https://animepahe.pw/'))

        # Simulate fresh Kodi plugin invocation (in-memory dict wiped)
        domains._FAILED_MIRRORS.clear()
        self.assertFalse(domains.is_mirror_healthy('https://animepahe.pw/'))

        # Circuit breaker also persists across fresh instances
        cb1 = pages.ScraperCircuitBreaker(failure_threshold=2, cooldown_seconds=300)
        cb1.record_failure('animepahe')
        cb1.record_failure('animepahe')
        self.assertTrue(cb1.is_tripped('animepahe'))

        cb2 = pages.ScraperCircuitBreaker(failure_threshold=2, cooldown_seconds=300)
        self.assertTrue(cb2.is_tripped('animepahe'))

    def test_animepahe_skips_malsync_when_host_in_cooldown(self):
        """C-01: AnimePahe checks is_mirror_healthy BEFORE _resolve_session_from_malsync."""
        scraper = animepahe.Sources()
        domains.mark_mirror_failure('https://animepahe.pw/', cooldown=600)

        with patch('resources.lib.ui.domains.get_domain', return_value='https://animepahe.pw/'), \
             patch.object(scraper, '_resolve_session_from_malsync') as mock_malsync, \
             patch('resources.lib.endpoints.malsync.get_title', return_value='Blood Lad'):
            res = scraper.get_sources(11633, 8)

        self.assertEqual(res, [])
        mock_malsync.assert_not_called()

    def test_resolver_deprioritizes_unhealthy_stream_hosts(self):
        """C-03 / C-09: Candidates on a cooled-down proxy host move behind healthy-host candidates."""
        domains.mark_mirror_failure('https://megacloud.animanga.fun/', cooldown=300)
        sources = [
            {'provider': 'hianime', 'type': 'direct', 'hash': 'https://megacloud.animanga.fun/proxy?url=1'},
            {'provider': 'hianime', 'type': 'direct', 'hash': 'https://megacloud.animanga.fun/proxy?url=2'},
            {'provider': 'hianime', 'type': 'direct', 'hash': 'https://upcloud.animanga.fun/proxy?url=3'},
            {'provider': 'anikoto', 'type': 'direct', 'hash': 'https://fetch.nexabloom.top/master.m3u8'},
        ]
        ordered = resolver._deprioritize_unhealthy_hosts(sources)
        self.assertEqual(ordered[0]['hash'], 'https://upcloud.animanga.fun/proxy?url=3')
        self.assertEqual(ordered[1]['hash'], 'https://fetch.nexabloom.top/master.m3u8')
        self.assertIn('megacloud.animanga.fun', ordered[2]['hash'])
        self.assertIn('megacloud.animanga.fun', ordered[3]['hash'])

    def test_player_resume_target_never_passes_http_url_to_setfiledetails(self):
        """C-07: onPlayBackEnded / onPlayBackStopped never pass raw http(s):// URLs to Files.SetFileDetails."""
        wp = player.WatchlistPlayer()
        wp.mal_id = 11737
        wp.episode = 1
        wp.path = ''
        wp.total_time = 5200

        with patch.object(wp, 'getPlayingFile', return_value='https://fetch.nexabloom.top/anime/abc/master.m3u8'), \
             patch('resources.lib.ui.control.jsonrpc') as mock_rpc, \
             patch('resources.lib.ui.control.clean_memory'), \
             patch('resources.lib.ui.control.closeAllDialogs'):
            wp.onPlayBackEnded()

        mock_rpc.assert_called_once()
        file_arg = mock_rpc.call_args[0][0]['params']['file']
        self.assertFalse(file_arg.startswith('http'))
        self.assertEqual(file_arg, f'plugin://{control.ADDON_ID}/play/11737/1')

        # If mal_id is absent, skip Files.SetFileDetails entirely rather than calling Stat on https://
        wp2 = player.WatchlistPlayer()
        wp2.mal_id = ''
        wp2.episode = 0
        wp2.path = ''
        wp2.total_time = 5200
        with patch.object(wp2, 'getPlayingFile', return_value='https://fetch.nexabloom.top/anime/abc/master.m3u8'), \
             patch('resources.lib.ui.control.jsonrpc') as mock_rpc2, \
             patch('resources.lib.ui.control.clean_memory'), \
             patch('resources.lib.ui.control.closeAllDialogs'):
            wp2.onPlayBackEnded()
        mock_rpc2.assert_not_called()

    def test_hook_mimetype_normalizes_case_and_parameters(self):
        """C-07: hook_mimetype matches parameterized & lowercase HLS MIME types."""
        item = MagicMock()
        item.getPath.return_value = 'https://cdn.example.com/master.m3u8|Referer=https://hianime.at/'
        mock_helper = MagicMock()
        mock_helper.check_inputstream.return_value = True
        mock_helper.inputstream_addon = 'inputstream.adaptive'

        with patch('resources.lib.ui.control.getBool', return_value=True), \
             patch('inputstreamhelper.Helper', return_value=mock_helper):
            resolver.hook_mimetype.trigger('Application/VND.Apple.MPEGURL; charset=utf-8', item)
            item.setContentLookup.assert_called_with(False)

            item2 = MagicMock()
            item2.getPath.return_value = 'https://cdn.example.com/alt.m3u8'
            resolver.hook_mimetype.trigger('application/x-mpegurl', item2)
            item2.setContentLookup.assert_called_with(False)

    def test_get_sub_sanitizes_malformed_vtt_tag_and_logs_warning_on_failure(self):
        """C-10: get_sub strips malformed '<}' VTT tags and logs total failure at warning."""
        bad_vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n<}if we can get along!</i>\n"
        mock_resp = MagicMock(text=bad_vtt)
        written = {}

        def _capture_write(path, content):
            written['path'] = path
            written['content'] = content

        with patch('resources.lib.ui.client.get', return_value=mock_resp), \
             patch('resources.lib.ui.control.atomic_write_text', side_effect=_capture_write):
            entry = embed_extractor.get_sub('https://cdn.test/eng.vtt', 'eng', sub_index=0)

        self.assertIsNotNone(entry)
        self.assertNotIn('<}', written['content'])
        self.assertIn('if we can get along!', written['content'])

        with patch('resources.lib.ui.client.get', return_value=None), \
             patch('resources.lib.ui.control.log') as mock_log:
            res = embed_extractor.get_sub('https://cdn.test/missing.vtt', 'eng', sub_index=0)
        self.assertIsNone(res)
        self.assertTrue(
            any(call.kwargs.get('level') == 'warning' or (len(call.args) > 1 and call.args[1] == 'warning') for call in mock_log.call_args_list)
        )

    def test_score_subtitle_stream_prefers_external_track_on_tie(self):
        """C-11: External downloaded .vtt/.srt subtitle beats in-manifest HLS track of same language."""
        manifest_sub = {'index': 0, 'language': 'eng', 'name': 'English', 'isdefault': False, 'isforced': False}
        external_sub = {'index': 1, 'language': 'eng', 'name': 'TemporarySubs.0.eng.vtt (External)', 'isdefault': False, 'isforced': False}
        chosen = player.select_subtitle_stream([manifest_sub, external_sub], target_mode='dialog', preferred_lang='eng')
        self.assertEqual(chosen, 1)

    def test_end_directory_handles_handle_zero(self):
        """C-06: control.end_directory(handle=0) invokes xbmcplugin.endOfDirectory."""
        control._directory_ended = False
        with patch('resources.lib.ui.control.xbmcplugin.endOfDirectory') as mock_end:
            control.end_directory(handle=0, succeeded=True, cacheToDisc=False)
        mock_end.assert_called_once_with(0, succeeded=True, cacheToDisc=False)

    def test_playback_ended_and_stopped_handle_none_total_time(self):
        """Live Kodi 22 fix: onPlayBackEnded/Stopped never raise TypeError when total_time is None."""
        wp = player.WatchlistPlayer.__new__(player.WatchlistPlayer)
        wp.total_time = None
        wp.current_time = None
        wp._playback_stopped = False
        wp._playback_ended = False
        wp._user_stopped_or_errored = False
        wp.item_path = 'plugin://plugin.video.otaku.rpdev/play/11633/8'
        with patch.object(wp, '_resolve_resume_target_file', return_value='plugin://plugin.video.otaku.rpdev/play/11633/8'), \
             patch('resources.lib.ui.control.closeAllDialogs'), \
             patch('resources.lib.ui.control.clean_memory'), \
             patch('resources.lib.ui.control.jsonrpc') as mock_rpc:
            wp.onPlayBackEnded()
            wp.onPlayBackStopped()
        mock_rpc.assert_not_called()

    def test_build_playlist_sorts_unsorted_episodes_numerically(self):
        """Live Kodi 22 fix: build_playlist sorts episodes numerically and queues only > current_ep."""
        wp = player.WatchlistPlayer.__new__(player.WatchlistPlayer)
        wp.episode = 8
        wp.mal_id = '11633'
        wp.episodes = [
            {'number': 10, 'url': 'play/11633/10', 'info': {'title': 'Ep 10'}, 'image': {}},
            {'number': 7, 'url': 'play/11633/7', 'info': {'title': 'Ep 7'}, 'image': {}},
            {'number': 5, 'url': 'play/11633/5', 'info': {'title': 'Ep 5'}, 'image': {}},
            {'number': 9, 'url': 'play/11633/9', 'info': {'title': 'Ep 9'}, 'image': {}},
            {'number': 8, 'url': 'play/11633/8', 'info': {'title': 'Ep 8'}, 'image': {}},
        ]
        queued_urls = []
        with patch('resources.lib.ui.control.getBool', return_value=True), \
             patch('resources.lib.indexers.process_episodes', side_effect=lambda eps, _: eps), \
             patch('resources.lib.ui.control.bulk_dir_list', side_effect=lambda eps, _: [(f"plugin://plugin.video.otaku.rpdev/{e['url']}", MagicMock()) for e in eps]), \
             patch('resources.lib.ui.player.playList.add', side_effect=lambda url, listitem: queued_urls.append(url)):
            wp.build_playlist()
        self.assertEqual(
            queued_urls,
            ['plugin://plugin.video.otaku.rpdev/play/11633/9', 'plugin://plugin.video.otaku.rpdev/play/11633/10'],
        )

    def test_checkpoint_databases_skips_readonly_mapping_db(self):
        """Live Kodi 22 fix: checkpoint_databases never opens read-only mappings.db for WAL checkpoint."""
        from resources.lib.ui import database
        opened_dbs = []

        def _fake_sql(db_path, *args, **kwargs):
            opened_dbs.append(db_path)
            cm = MagicMock()
            cm.__enter__.return_value = MagicMock()
            return cm

        with patch.object(database, 'SQL', side_effect=_fake_sql), \
             patch('os.path.exists', return_value=True):
            database.checkpoint_databases()
        self.assertNotIn(control.mappingDB, opened_dbs)
        self.assertIn(control.cacheFile, opened_dbs)

    def test_playback_route_uses_getbool_for_preresolve(self):
        """Live Kodi 22 fix: smartplay.preresolve is evaluated via control.getBool during playback route."""
        from resources.lib.routes import playback
        control.playerWindow.setProperty('otaku.preResolved_url', 'https://cdn.test/ep2.mkv')
        control.playerWindow.setProperty('otaku.preResolved_malId', '58516')
        control.playerWindow.setProperty('otaku.preResolved_episode', '2')
        try:
            with patch.object(control, 'getBool', side_effect=lambda k, default=False: False if k == 'smartplay.preresolve' else default) as mock_gb, \
                 patch.object(playback, 'database') as mock_db, \
                 patch('resources.lib.MetaBrowser.get_sources', return_value=[]):
                mock_db.get_episode.return_value = None
                playback.PLAY('58516/2', {})
                queried_keys = [c.args[0] for c in mock_gb.call_args_list if c.args]
                self.assertIn('smartplay.preresolve', queried_keys)
        finally:
            control.playerWindow.clearProperty('otaku.preResolved_url')
            control.playerWindow.clearProperty('otaku.preResolved_malId')
            control.playerWindow.clearProperty('otaku.preResolved_episode')


if __name__ == '__main__':
    unittest.main()
