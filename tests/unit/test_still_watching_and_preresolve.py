"""
Unit tests for 'Still Watching?' Binge Safeguard and Zero-Wait Pre-Resolved Stream Handoff.
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

import json
import unittest
from unittest.mock import MagicMock, patch
from resources.lib.ui import control


class TestStillWatchingAndPreResolve(unittest.TestCase):

    def setUp(self):
        control.setBool('smartplay.preresolve', True)
        control.playerWindow.clearProperty('otaku.preResolved_url')
        control.playerWindow.clearProperty('otaku.preResolved_malId')
        control.playerWindow.clearProperty('otaku.preResolved_episode')
        control.playerWindow.clearProperty('otaku.preResolved_data')
        control.playerWindow.clearProperty('otaku.consecutive_autoplay')

    def tearDown(self):
        control.playerWindow.clearProperty('otaku.preResolved_url')
        control.playerWindow.clearProperty('otaku.preResolved_malId')
        control.playerWindow.clearProperty('otaku.preResolved_episode')
        control.playerWindow.clearProperty('otaku.preResolved_data')
        control.playerWindow.clearProperty('otaku.consecutive_autoplay')

    def test_still_watching_dialog_init_and_properties(self):
        """StillWatchingXML initializes properties and timeout correctly."""
        from resources.lib.windows.still_watching import StillWatchingXML
        dlg = StillWatchingXML('still_watching.xml', control.ADDON_PATH, actionArgs={'title': 'Frieren', 'timeout': 20})
        self.assertEqual(dlg.timeout, 20)
        self.assertEqual(dlg.title, 'Frieren')
        self.assertFalse(dlg.closed)
        self.assertFalse(dlg.keep_watching)

    def test_still_watching_click_handlers(self):
        """Clicking Keep Watching sets keep_watching=True; Stop Playback sets False."""
        from resources.lib.windows.still_watching import StillWatchingXML
        dlg = StillWatchingXML('still_watching.xml', control.ADDON_PATH, actionArgs={'title': 'Frieren'})

        # Test Keep Watching (3001)
        dlg.onClick(3001)
        self.assertTrue(dlg.keep_watching)
        self.assertTrue(dlg.closed)

        # Test Stop Playback (3002)
        dlg2 = StillWatchingXML('still_watching.xml', control.ADDON_PATH, actionArgs={'title': 'Frieren'})
        dlg2.onClick(3002)
        self.assertFalse(dlg2.keep_watching)
        self.assertTrue(dlg2.closed)

    def test_pre_resolved_stream_handoff_in_playback(self):
        """PLAY route immediately consumes matching pre-resolved stream without rescraping."""
        from resources.lib.routes import playback

        # Setup pre-resolved window properties for MalID 481, Ep 2
        mock_data = {
            'url': 'https://cdn.example.com/hls/ep2/master.m3u8',
            'headers': {'Content-Type': 'application/vnd.apple.mpegurl'},
            'sub': [{'url': 'https://cdn.example.com/subs/en.vtt', 'lang': 'English', 'name': 'English', 'index': 0}]
        }
        control.playerWindow.setProperty('otaku.preResolved_url', mock_data['url'])
        control.playerWindow.setProperty('otaku.preResolved_malId', '481')
        control.playerWindow.setProperty('otaku.preResolved_episode', '2')
        control.playerWindow.setProperty('otaku.preResolved_data', json.dumps(mock_data))

        with patch('xbmcplugin.setResolvedUrl') as mock_set_resolved, \
             patch('resources.lib.MetaBrowser.get_sources') as mock_get_sources, \
             patch('resources.lib.MetaBrowser.get_anime_init'):

            playback.PLAY('481/2', {})

            # setResolvedUrl must be called with the pre-resolved URL
            mock_set_resolved.assert_called_once()
            called_item = mock_set_resolved.call_args[0][2]
            self.assertEqual(called_item.getPath(), mock_data['url'])

            # MetaBrowser.get_sources must NOT be called (0 ms delay!)
            mock_get_sources.assert_not_called()

            # Window properties must be cleared
            self.assertEqual(control.playerWindow.getProperty('otaku.preResolved_url'), '')
            self.assertEqual(control.playerWindow.getProperty('otaku.preResolved_malId'), '')

    def test_pre_resolved_stream_handoff_mismatch_fallback(self):
        """PLAY falls back to standard scraping when episode/mal_id mismatch."""
        from resources.lib.routes import playback

        # Stale pre-resolved data for Ep 1 when user requests Ep 2
        control.playerWindow.setProperty('otaku.preResolved_url', 'https://cdn.example.com/ep1.m3u8')
        control.playerWindow.setProperty('otaku.preResolved_malId', '481')
        control.playerWindow.setProperty('otaku.preResolved_episode', '1')

        with patch('resources.lib.MetaBrowser.get_sources') as mock_get_sources, \
             patch('resources.lib.routes.playback._show_resolver'):

            mock_get_sources.return_value = []
            playback.PLAY('481/2', {})

            # Must fall back to standard scraper since episode did not match
            mock_get_sources.assert_called_once()

    def test_resolve_silent_extractor(self):
        """resolve_silent safely resolves candidates headlessly without dialogs."""
        from resources.lib.windows import resolver

        mock_sources = [
            {'type': 'direct', 'hash': 'https://stream.example.com/video.mp4', 'provider': 'test'},
            {'type': 'embed', 'hash': 'https://embed.example.com/v/1234', 'provider': 'test'}
        ]

        with patch('resources.lib.windows.resolver.Resolver.prefetch_play_link') as mock_prefetch:
            mock_prefetch.return_value = {
                'url': 'https://stream.example.com/video.mp4',
                'headers': {'Content-Type': 'video/mp4'}
            }
            res = resolver.resolve_silent(mock_sources, 1, 481)
            self.assertIsNotNone(res)
            self.assertEqual(res['url'], 'https://stream.example.com/video.mp4')
            self.assertEqual(res['source'], mock_sources[0])


if __name__ == '__main__':
    unittest.main()