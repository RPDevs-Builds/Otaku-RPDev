"""
test_debrid_and_playback_m1c.py - Unit Tests for Worker M1C Remediations
========================================================================
Tests proactive OAuth token refresh (300s buffer), 429 jittered backoff,
Easynews float timeouts, demuxer chapter decoupling from ffprobe,
and clean code mutable default argument elimination.
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
import time
from unittest.mock import patch, MagicMock

from resources.lib.ui import control
from resources.lib.debrid.real_debrid import RealDebrid
from resources.lib.debrid.debrid_link import DebridLink
from resources.lib.debrid.torbox import TorBox
from resources.lib.debrid.all_debrid import AllDebrid
from resources.lib.debrid.premiumize import Premiumize
from resources.lib.debrid.easynews import Easynews
from resources.lib.ui.player import WatchlistPlayer
from resources.lib.AnimeSchedule import AnimeScheduleCalendar
from resources.lib.ui.BrowserBase import BrowserBase
from resources.lib.ui import embed_extractor


class TestDebridAndPlaybackM1C(unittest.TestCase):
    def setUp(self):
        control.clearSettingsCache()

    def tearDown(self):
        control.cleanup()

    # ── 1. Proactive OAuth Token Refresh (300s Buffer) ──────────────────────────

    def test_realdebrid_proactive_token_refresh(self):
        """Verify RealDebrid refreshes token proactively when within 300s of expiration."""
        rd = RealDebrid()
        rd.token = 'existing_token'
        rd.refresh = 'refresh_token_xyz'

        now = time.time()
        # Case A: Expiring in 200 seconds (< 300s buffer) -> Must refresh
        control.setInt('realdebrid.expiry', int(now + 200))
        with patch.object(rd, 'refreshToken') as mock_refresh:
            headers = rd.headers()
            mock_refresh.assert_called_once()
            self.assertEqual(headers, {'Authorization': 'Bearer existing_token'})

        # Case B: Expiring in 600 seconds (> 300s buffer) -> Should NOT refresh
        control.setInt('realdebrid.expiry', int(now + 600))
        with patch.object(rd, 'refreshToken') as mock_refresh:
            headers = rd.headers()
            mock_refresh.assert_not_called()
            self.assertEqual(headers, {'Authorization': 'Bearer existing_token'})

    def test_debridlink_proactive_token_refresh(self):
        """Verify DebridLink refreshes token proactively when within 300s of expiration."""
        dl = DebridLink()
        dl.token = 'dl_token_123'
        dl.refresh = 'dl_refresh_xyz'

        now = time.time()
        # Case A: Expiring in 150 seconds (< 300s buffer) -> Must refresh
        control.setInt('debridlink.expiry', int(now + 150))
        with patch.object(dl, 'refreshToken') as mock_refresh:
            headers = dl.headers()
            mock_refresh.assert_called_once()
            self.assertIn('Authorization', headers)

        # Case B: Expiring in 800 seconds (> 300s buffer) -> Should NOT refresh
        control.setInt('debridlink.expiry', int(now + 800))
        with patch.object(dl, 'refreshToken') as mock_refresh:
            headers = dl.headers()
            mock_refresh.assert_not_called()

    # ── 2. Debrid 429 Jittered Backoff & Non-blocking Aborts ───────────────────

    def test_debrid_429_jittered_backoff_and_waitforabort(self):
        """Verify 429 response triggers non-blocking waitForAbort with jitter across clients."""
        clients = [
            (RealDebrid(), 'get', 'https://api.real-debrid.com/rest/1.0/torrents'),
            (TorBox(), 'get', 'https://api.torbox.app/v1/api/torrents/checkcached'),
            (AllDebrid(), 'get', 'https://api.alldebrid.com/v4.1/test'),
            (DebridLink(), 'post', 'https://debrid-link.fr/api/v2/test'),
            (Premiumize(), 'get', 'https://www.premiumize.me/api/test'),
        ]

        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {'Retry-After': '1'}

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.ok = True

        for client_inst, method, test_url in clients:
            with patch(f'resources.lib.ui.client.{method}', side_effect=[resp_429, resp_200]) as mock_http, \
                 patch('resources.lib.ui.control.monitor.waitForAbort', return_value=False) as mock_wait:
                r = client_inst._request_with_backoff(method, test_url)
                self.assertEqual(mock_http.call_count, 2)
                mock_wait.assert_called_once()
                wait_arg = mock_wait.call_args[0][0]
                # Base is 1.0; jitter is [0.1, 0.4] -> must be in [1.1, 1.45]
                self.assertGreaterEqual(wait_arg, 1.1)
                self.assertLessEqual(wait_arg, 1.45)
                self.assertEqual(r.status_code, 200)

    # ── 3. Easynews Float Timeout Precision ───────────────────────────────────

    @patch('resources.lib.ui.client.get')
    def test_easynews_float_timeouts(self, mock_get):
        """Verify Easynews casts timeouts to float to prevent sub-second integer truncation."""
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {'data': []}
        mock_get.return_value = mock_resp

        en = Easynews()
        en.username = 'testuser'
        en.password = 'testpass'

        en.search('Attack on Titan')
        self.assertTrue(mock_get.called)
        timeout_arg = mock_get.call_args[1].get('timeout')
        self.assertIsInstance(timeout_arg, float)

    # ── 4. Demuxer Chapter Resolution Flow Decoupled from ffprobe ─────────────

    @patch('resources.lib.ui.control.getBool')
    @patch('resources.lib.ui.control.jsonrpc')
    def test_demuxer_chapters_decoupled_from_ffprobe_setting(self, mock_jsonrpc, mock_getBool):
        """Verify native Kodi 22 Player.GetChapters queries execute even if ffprobe binary is disabled."""
        # ffprobe binary disabled!
        mock_getBool.side_effect = lambda setting, default=False: {
            'ffprobe.chapters.enable': False,
            'general.aniskip': True,
        }.get(setting, default)

        mock_jsonrpc.return_value = {
            'result': {
                'chapters': [
                    {'name': 'Cold Open', 'time': 0.0},
                    {'name': 'Opening', 'time': 60.0},
                    {'name': 'Main Part', 'time': 150.0},
                    {'name': 'Ending', 'time': 1300.0},
                ]
            }
        }

        player = WatchlistPlayer()
        player.total_time = 1400
        player.ffprobe_chapters = []
        player.skipintro_aniskip_enable = True
        player.skipintro_aniskip = False
        player.skipintro_offset = 0
        player.skipoutro_aniskip_enable = True
        player.skipoutro_aniskip = False
        player.skipoutro_offset = 0

        # Run demuxer chapter processing
        player.process_ffprobe_chapter_skips()

        # Chapters must be populated directly via JSON-RPC regardless of ffprobe.chapters.enable
        self.assertTrue(player.skipintro_aniskip)
        self.assertEqual(player.skipintro_start, 60)
        self.assertEqual(player.skipintro_end, 150)
        self.assertTrue(player.skipoutro_aniskip)
        self.assertEqual(player.skipoutro_start, 1300)

    # ── 5. Clean Code Modernization: Mutable Default Elimination ──────────────

    def test_animeschedule_mutable_defaults(self):
        """Verify AnimeSchedule calendar uses safe default and does not mutate shared state."""
        calendar = AnimeScheduleCalendar()
        with patch.object(calendar, '_load_cache', return_value=[{'title': 'Anime A'}]):
            res1 = calendar.get_calendar_data(days=7)
            self.assertIsNotNone(res1)
            # Default types parameter must be safely handled
            res2 = calendar.get_calendar_data(days=7, types=None)
            self.assertIsNotNone(res2)

    def test_browserbase_mutable_defaults(self):
        """Verify BrowserBase _post_request does not reuse a shared mutable dict."""
        browser = BrowserBase()
        with patch.object(browser, '_send_request', return_value='response') as mock_send:
            browser._post_request('https://example.com/api')
            # Called with default empty dict
            self.assertEqual(mock_send.call_args[0][1], {})

    def test_embed_extractor_mutable_defaults(self):
        """Verify embed_extractor __register_extractor does not leak shared list."""
        # Check __register_extractor signature has datas=None default
        import inspect
        fn = getattr(embed_extractor, '__register_extractor')
        sig = inspect.signature(fn)
        self.assertIsNone(sig.parameters['datas'].default)


if __name__ == '__main__':
    unittest.main()
