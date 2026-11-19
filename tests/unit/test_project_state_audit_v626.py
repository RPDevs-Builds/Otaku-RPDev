"""
Unit tests for v6.2.6 Comprehensive Project State & Log Audit Remediations:
- C-16: Zero-Wait pre-resolved handoff preservation across onPlayBackEnded & callable scrobbler
- C-03 / C-09: Resolver 30s timeout abort, Monitor fast-fail OnStop & episode source cache clearing
- C-07: _HLS_HOOK / _DASH_HOOK setContentLookup(False) & setMimeType on Kodi 21/22
- C-08: BaseWindow / anichart_window / SourceSelect setProperty None & list coercion
- C-02: Dynamic-list & grouplist skin XML <defaultcontrol> cleanup
- C-05: service.version_check prunes settings AFTER control.setSetting
- C-10: embed_extractor.get_sub proxy-to-origin fallback
"""

# Standardized Otaku Test Bootstrap
import os
import sys

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_TEST_DIR, '..' if os.path.basename(_TEST_DIR) in ('unit', 'integration', 'lint') else '.'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
_TESTS_DIR = os.path.join(_REPO_ROOT, 'tests')
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import conftest  # Centralized Kodi mock harness  # noqa: F401
from tests.kodi_profile import KodiProfile, MockListItem21, MockListItem22

import json
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch

from resources.lib.ui import control, database, embed_extractor
from resources.lib.windows import anichart_window, base_window, resolver, source_select


class _TrackableListItem21(MockListItem21):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.content_lookup = True
        self.mime_type = None

    def setContentLookup(self, enabled):
        self.content_lookup = bool(enabled)

    def setMimeType(self, mime):
        self.mime_type = mime


class _TrackableListItem22(MockListItem22):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.content_lookup = True
        self.mime_type = None

    def setContentLookup(self, enabled):
        self.content_lookup = bool(enabled)

    def setMimeType(self, mime):
        self.mime_type = mime


class TestProjectStateAuditV626(unittest.TestCase):

    def tearDown(self):
        for prop in (
            'otaku.preResolved_url',
            'otaku.preResolved_malId',
            'otaku.preResolved_episode',
            'otaku.preResolved_data',
        ):
            control.playerWindow.clearProperty(prop)
        control.playList.clear()

    def test_zero_wait_preresolved_preserved_on_playback_ended_and_cleared_on_stopped(self):
        """Pre-resolved stream properties survive natural EOF transition in playlist, but clear on manual stop/error."""
        from resources.lib.ui.player import WatchlistPlayer

        def _seed_props():
            control.playerWindow.setProperty('otaku.preResolved_url', 'https://cdn.example.com/ep2.m3u8')
            control.playerWindow.setProperty('otaku.preResolved_malId', '11633')
            control.playerWindow.setProperty('otaku.preResolved_episode', '2')
            control.playerWindow.setProperty('otaku.preResolved_data', '{"url": "https://cdn.example.com/ep2.m3u8"}')

        # 1. Natural EOF with multi-item playlist -> preserve properties across keepAlive exit
        _seed_props()
        control.playList.clear()
        control.playList.add('plugin://plugin.video.otaku.rpdev/play/11633/1')
        control.playList.add('plugin://plugin.video.otaku.rpdev/play/11633/2')

        wp = WatchlistPlayer()
        wp.mal_id = 11633
        wp.episode = 1
        wp.path = 'plugin://plugin.video.otaku.rpdev/play/11633/1'
        wp.total_time = 1400
        wp._skip_processed = True
        wp.media_type = 'movie'

        with patch.object(wp, 'isPlaying', side_effect=[False]), \
             patch.object(wp, 'onWatchedPercent'), \
             patch('resources.lib.ui.control.jsonrpc'), \
             patch('resources.lib.ui.control.clean_memory'), \
             patch('resources.lib.ui.control.closeAllDialogs'), \
             patch('resources.lib.ui.database.get_show', return_value=None):
            wp.onPlayBackEnded()
            self.assertTrue(wp._playback_ended)
            wp.keepAlive()

        self.assertEqual(control.playerWindow.getProperty('otaku.preResolved_url'), 'https://cdn.example.com/ep2.m3u8')
        self.assertEqual(control.playerWindow.getProperty('otaku.preResolved_episode'), '2')

        # 2. Manual user stop -> immediately clears properties
        _seed_props()
        wp2 = WatchlistPlayer()
        with patch('resources.lib.ui.control.jsonrpc'), \
             patch('resources.lib.ui.control.clean_memory'), \
             patch('resources.lib.ui.control.closeAllDialogs'):
            wp2.onPlayBackStopped()
        self.assertEqual(control.playerWindow.getProperty('otaku.preResolved_url'), '')
        self.assertEqual(control.playerWindow.getProperty('otaku.preResolved_episode'), '')

        # 3. Playback error -> immediately clears properties
        _seed_props()
        wp3 = WatchlistPlayer()
        with patch('resources.lib.ui.control.clean_memory'), \
             patch('resources.lib.ui.control.closeAllDialogs'):
            wp3.onPlayBackError()
        self.assertEqual(control.playerWindow.getProperty('otaku.preResolved_url'), '')

    def test_zero_wait_playback_passes_callable_watchlist_update_episode(self):
        """Zero-Wait PLAY route passes watchlist_update_episode callable (not int) to handle_player."""
        from resources.lib.WatchlistIntegration import watchlist_update_episode
        from resources.lib.routes import playback

        mock_data = {
            'url': 'https://cdn.example.com/hls/ep2/master.m3u8',
            'headers': {'Content-Type': 'application/vnd.apple.mpegurl'},
            'source': {'type': 'embed', 'provider': 'hianime'},
        }
        control.playerWindow.setProperty('otaku.preResolved_url', mock_data['url'])
        control.playerWindow.setProperty('otaku.preResolved_malId', '481')
        control.playerWindow.setProperty('otaku.preResolved_episode', '2')
        control.playerWindow.setProperty('otaku.preResolved_data', json.dumps(mock_data))
        control.setBool('smartplay.preresolve', True)

        with patch('xbmcplugin.setResolvedUrl'), \
             patch('resources.lib.ui.embed_extractor.del_subs'), \
             patch('resources.lib.ui.player.WatchlistPlayer') as mock_wp_cls:
            mock_wp = MagicMock()
            mock_wp_cls.return_value = mock_wp

            playback.PLAY('481/2', {})

            mock_wp.handle_player.assert_called_once()
            args = mock_wp.handle_player.call_args[0]
            self.assertEqual(args[0], '481')
            self.assertIs(args[1], watchlist_update_episode)
            self.assertTrue(callable(args[1]))
            self.assertEqual(args[2], 2)

    def test_resolver_monitor_fast_fail_onstop_and_cache_invalidation(self):
        """Monitor catches <2s OnStop failures when idle or post-OnPlay, and Resolver clears cached episode sources."""
        # Case A: Player was idle at start -> <2s OnStop immediately sets playbackerror
        with patch('resources.lib.windows.resolver.xbmc.Player') as mock_player_cls:
            mock_player_cls.return_value.isPlaying.return_value = False
            mon = resolver.Monitor()
            mon.onNotification('Player', 'Player.OnStop', '{}')
            self.assertTrue(mon.playbackerror)

        # Case B: Player was already playing previous item -> initial <2s OnStop ignored until OnPlay
        with patch('resources.lib.windows.resolver.xbmc.Player') as mock_player_cls:
            mock_player_cls.return_value.isPlaying.return_value = True
            mon2 = resolver.Monitor()
            mon2.onNotification('Player', 'Player.OnStop', '{}')
            self.assertFalse(mon2.playbackerror)
            mon2.onNotification('Player', 'Player.OnPlay', '{}')
            mon2.onNotification('Player', 'Player.OnStop', '{}')
            self.assertTrue(mon2.playbackerror)

        # Case C: 30s timeout sets abort=True & clears pre-scraped episode sources
        res = resolver.Resolver('resolver.xml', conftest.ADDON_ROOT, actionArgs={'mal_id': 49114, 'episode': 11}, source_select=False)
        res.sources = [{'provider': 'hianime', 'type': 'direct', 'hash': 'https://megacloud.animanga.fun/x.m3u8'}]
        res.return_data = {
            'linkinfo': {'url': 'https://megacloud.animanga.fun/master.m3u8', 'headers': {}},
            'source': res.sources[0],
            'candidate_index': 0,
        }
        res.params = {}

        with patch('resources.lib.windows.resolver.Monitor') as mock_mon_cls, \
             patch('resources.lib.windows.resolver.database.clear_episode_sources') as mock_clear, \
             patch('resources.lib.windows.resolver.xbmcplugin.setResolvedUrl'), \
             patch('resources.lib.ui.embed_extractor.del_subs'), \
             patch.object(res, 'close'):
            mock_mon = MagicMock()
            mock_mon.waitForAbort.return_value = False
            mock_mon.playbackerror = False
            mock_mon.abortRequested.return_value = False
            mock_mon.playing = False
            mock_mon_cls.return_value = mock_mon

            res._handle_playback()
            self.assertTrue(res.abort)
            mock_clear.assert_called_once_with(49114, 11)

    def test_hls_and_dash_hooks_disable_content_lookup_on_kodi_21_and_22(self):
        """Both _HLS_HOOK and _DASH_HOOK invoke setContentLookup(False) and setMimeType on Kodi 21 and 22."""
        control.setBool('inputstreamadaptive.enabled', True)

        for profile_ver, item_cls in (('21', _TrackableListItem21), ('22', _TrackableListItem22)):
            with KodiProfile(profile_ver):
                hls_item = item_cls(path='https://fetch.nexabloom.top/master.m3u8|Referer=https://hianime.at/')
                resolver._HLS_HOOK(hls_item)
                self.assertFalse(hls_item.content_lookup, f"HLS setContentLookup(False) missed on Kodi {profile_ver}")
                self.assertEqual(hls_item.mime_type, 'application/vnd.apple.mpegurl')
                self.assertEqual(hls_item.getPath(), 'https://fetch.nexabloom.top/master.m3u8')

                dash_item = item_cls(path='https://cdn.example.com/manifest.mpd|Referer=https://example.com/')
                resolver._DASH_HOOK(dash_item)
                self.assertFalse(dash_item.content_lookup, f"DASH setContentLookup(False) missed on Kodi {profile_ver}")
                self.assertEqual(dash_item.mime_type, 'application/dash+xml')
                self.assertEqual(dash_item.getPath(), 'https://cdn.example.com/manifest.mpd')

    def test_base_window_and_source_select_setproperty_none_and_list_coercion(self):
        """BaseWindow, anichart_window, and SourceSelect coerce None/list properties and preserve movie titles."""
        # BaseWindow direct setProperty contract
        bw = base_window.BaseWindow.__new__(base_window.BaseWindow)
        bw.item_information = {
            'format': 'MOVIE',
            'name': 'Blue Exorcist: The Movie',
            'title_userPreferred': None,
            'plot': None,
            'poster': ['https://example.com/poster.jpg'],
            'fanart': 'https://example.com/fanart.jpg',
            'clearlogo': 'https://example.com/logo.png',
            'rating': None,
        }
        with patch('xbmcgui.WindowXMLDialog.setProperty') as mock_super_set:
            bw._set_window_properties()
            props = {call[0][0]: call[0][1] for call in mock_super_set.call_args_list}
            self.assertEqual(props['item.art.poster'], 'https://example.com/poster.jpg')
            self.assertEqual(props['item.info.plot'], '')
            self.assertEqual(props['item.info.rating'], '')
            self.assertEqual(props['item.info.title'], 'Blue Exorcist: The Movie')

            # Oversized (>64KB) property is skipped
            mock_super_set.reset_mock()
            bw.setProperty('huge', 'x' * 70000)
            mock_super_set.assert_not_called()

        # anichart_window BaseWindow setProperty contract
        aw = anichart_window.BaseWindow.__new__(anichart_window.BaseWindow)
        with patch('xbmcgui.WindowXMLDialog.setProperty') as mock_ani_set:
            aw.setProperty('k', None)
            mock_ani_set.assert_called_with('k', '')
            aw.setProperty('lst', ['https://a.jpg', 'https://b.jpg'])
            mock_ani_set.assert_called_with('lst', 'https://a.jpg')

        # SourceSelect movie path with rating=None and list poster
        meta_json = json.dumps({'plot': None, 'rating': None, 'poster': ['https://example.com/movie.jpg'], 'start_date': '2012-12-28'})
        with patch('resources.lib.windows.source_select.database.get_show', return_value={'kodi_meta': meta_json}), \
             patch('resources.lib.windows.source_select.database.get_show_meta', return_value=None):
            ss = source_select.SourceSelect('source_select.xml', conftest.ADDON_ROOT, actionArgs={'mal_id': 11737})
            self.assertEqual(ss.getProperty('item.info.plot'), '')
            self.assertEqual(ss.getProperty('item.info.rating'), '')
            self.assertEqual(ss.getProperty('item.art.thumb'), 'https://example.com/movie.jpg')
            self.assertEqual(ss.getProperty('item.info.year'), '2012')

    def test_dynamic_list_skins_omit_premature_defaultcontrol(self):
        """Dynamic list dialogs must omit <defaultcontrol>1000</defaultcontrol>; wlf_auth_mal group 2000 targets 1002."""
        skin_dir = os.path.join(conftest.ADDON_ROOT, 'resources', 'skins', 'Default', '1080i')
        for xml_name in ('anichart.xml', 'clear_cache.xml', 'download_manager.xml', 'menu_order.xml', 'settings_backup.xml'):
            root = ET.parse(os.path.join(skin_dir, xml_name)).getroot()
            self.assertIsNone(root.find('defaultcontrol'), f"{xml_name} should omit top-level <defaultcontrol>")

        wlf_root = ET.parse(os.path.join(skin_dir, 'wlf_auth_mal.xml')).getroot()
        grp_2000 = wlf_root.find(".//control[@id='2000']")
        self.assertIsNotNone(grp_2000)
        dc = grp_2000.find('defaultcontrol')
        self.assertIsNotNone(dc)
        self.assertEqual(dc.text.strip(), '1002')

    def test_version_check_prunes_settings_after_setsetting(self):
        """service.version_check invokes clean_settings AFTER control.setSetting('otaku.version', ...)."""
        import service
        call_order = []
        control.setSetting('otaku.version', '6.2.4')

        orig_set_setting = control.setSetting

        def _track_set(k, v):
            if k == 'otaku.version':
                call_order.append(('setSetting', k, v))
            return orig_set_setting(k, v)

        def _track_clean(**kwargs):
            call_order.append(('clean_settings', kwargs.get('silent')))
            return (0, [])

        with patch('resources.lib.ui.control.setSetting', side_effect=_track_set), \
             patch('resources.lib.ui.clean_settings.clean_settings', side_effect=_track_clean), \
             patch.object(service, 'toggle_reuselanguageinvoker'):
            service.version_check()

        self.assertEqual(
            call_order,
            [('setSetting', 'otaku.version', control.ADDON_VERSION), ('clean_settings', True)],
        )

    def test_embed_extractor_get_sub_falls_back_from_proxy_to_source_url(self):
        """get_sub falls back to source_url or decoded ?url= param when proxy fetch fails (C-10)."""
        mock_vtt = MagicMock()
        mock_vtt.text = 'WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nHello'

        proxy_url = 'https://megacloud.animanga.fun/fetch?url=https%3A%2F%2Forigin.example.com%2Fsubs%2Feng-2.vtt'

        def _fake_get(url, headers=None, verify=True):
            if 'megacloud.animanga.fun/fetch' in url:
                return None
            if url == 'https://origin.example.com/subs/eng-2.vtt':
                return mock_vtt
            return None

        with patch('resources.lib.ui.client.get', side_effect=_fake_get), \
             patch('resources.lib.ui.control.atomic_write_text', return_value=True) as mock_write:
            res = embed_extractor.get_sub(proxy_url, 'eng', sub_index=2, display_name='English')
            self.assertIsNotNone(res)
            self.assertEqual(res['lang'], 'eng')
            mock_write.assert_called_once()


if __name__ == '__main__':
    unittest.main()
