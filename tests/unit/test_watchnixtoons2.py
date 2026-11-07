"""
test_watchnixtoons2.py - Unit Tests for WatchNixtoons2 Scraper Engine
====================================================================
Tests dynamic embed API origin derivation, embed detection order,
ad-verify payload construction with dynamic netlocs, and responsive abort loops.
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

import unittest
from unittest.mock import patch, MagicMock

from resources.lib.pages.watchnixtoons2 import Sources as WNT2Sources
from resources.lib.ui import control


class TestWatchNixtoons2Scraper(unittest.TestCase):
    def setUp(self):
        control.clearSettingsCache()
        self.scraper = WNT2Sources()

    def tearDown(self):
        control.cleanup()

    def test_embed_api_origin_derivation(self):
        """Verify dynamic derivation of embed origins from various mirror schemes and netlocs."""
        self.assertEqual(
            self.scraper._embed_api_origin('https://embed.wcostream.com/inc/embed/index.php?pid=123'),
            'https://embed.wcostream.com/'
        )
        self.assertEqual(
            self.scraper._embed_api_origin('https://cdn2.wcostream.cc/embed/player.php'),
            'https://cdn2.wcostream.cc/'
        )
        self.assertEqual(
            self.scraper._embed_api_origin('http://mirror.wco.tv/inc/embed/index.php'),
            'http://mirror.wco.tv/'
        )
        self.assertEqual(
            self.scraper._embed_api_origin('//mirror.wco.tv/inc/embed/index.php'),
            'https://mirror.wco.tv/'
        )
        # Fallback for invalid or missing netloc
        self.assertEqual(
            self.scraper._embed_api_origin('not-a-valid-url'),
            'https://embed.wcostream.com/'
        )

    def test_find_embed_url_vjs_iframe(self):
        """Verify vjs_iframe pattern detection and is_vhs flag."""
        html = '''
        <div class="player-container">
            <iframe id="cizgi-vjs-1" class="vjs_iframe" rel="nofollow" src="https://embed.wcostream.com/inc/embed/index.php?pid=999"></iframe>
        </div>
        '''
        url, is_vhs = self.scraper._find_embed_url(html, 'https://www.wcostream.tv/watch-anime')
        self.assertEqual(url, 'https://embed.wcostream.com/inc/embed/index.php?pid=999')
        self.assertTrue(is_vhs)

    def test_find_embed_url_uploads(self):
        """Verify uploads iframe pattern detection."""
        html = '''
        <div class="video">
            <iframe id="cizgiuploads0" src="/inc/embed/uploads.php?id=abc123"></iframe>
        </div>
        '''
        url, is_vhs = self.scraper._find_embed_url(html, 'https://www.wcostream.tv/watch-anime')
        self.assertEqual(url, 'https://www.wcostream.tv/inc/embed/uploads.php?id=abc123')
        self.assertFalse(is_vhs)

    def test_api_source_candidates_uses_dynamic_origin(self):
        """Verify _api_source_candidates uses the dynamic embed origin rather than hardcoded domain."""
        player_html = '''
        <script>
            $.getJSON("/inc/embed/video-json.php?id=xyz789", function(data) {
                console.log(data);
            });
        </script>
        <div data-link="/inc/embed/getvidlink.php?v=123"></div>
        '''
        embed_url = 'https://custom-mirror.wcostream.net/inc/embed/index.php?pid=555'
        candidates = self.scraper._api_source_candidates(player_html, embed_url)

        self.assertTrue(any(c.startswith('https://custom-mirror.wcostream.net/') for c in candidates))
        for c in candidates:
            self.assertNotIn('https://embed.wcostream.com', c)

    @patch.object(WNT2Sources, '_make_request')
    @patch('resources.lib.ui.control.monitor.waitForAbort', return_value=False)
    def test_run_wco_ad_verify_uses_dynamic_origin(self, mock_wait, mock_make_request):
        """Verify _run_wco_ad_verify queries advertisement.js and ad-verify using dynamic origin."""
        mock_make_request.return_value = MagicMock(text='ok')
        embed_url = 'https://stream.wco-edge.org/inc/embed/index.php?pid=4321'

        res = self.scraper._prepare_embed_player_url(embed_url)

        self.assertIsNotNone(res)
        self.assertTrue(res.startswith('https://stream.wco-edge.org/inc/embed/video-js-old.php'))

        # Check call arguments to _make_request
        calls = mock_make_request.call_args_list
        self.assertGreaterEqual(len(calls), 2)
        # advertisement.js call
        self.assertIn('https://stream.wco-edge.org/assets/ads/advertisement.js', calls[0][0][0])
        # ad-verify call
        self.assertEqual('https://stream.wco-edge.org/ad-verify', calls[1][0][0])
        # Verify waitForAbort was called with 5 seconds
        mock_wait.assert_called_with(5)

    @patch.object(WNT2Sources, '_make_request')
    @patch('resources.lib.ui.control.monitor.waitForAbort', return_value=True)
    def test_run_wco_ad_verify_aborts_cleanly(self, mock_wait, mock_make_request):
        """Verify _run_wco_ad_verify returns None immediately when waitForAbort returns True."""
        mock_make_request.return_value = MagicMock(text='ok')
        embed_url = 'https://stream.wco-edge.org/inc/embed/index.php?pid=4321'

        res = self.scraper._prepare_embed_player_url(embed_url)
        self.assertIsNone(res)


if __name__ == '__main__':
    unittest.main()
