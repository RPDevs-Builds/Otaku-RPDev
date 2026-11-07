"""
test_milestone2_adversarial_hardening.py - Milestone 2 Adversarial Hardening Tests
===================================================================================
Comprehensive tests for Milestone 2 adversarial coverage hardening refinements:
1. EasyDebrid non-blocking waitForAbort backoff and float Retry-After parsing.
2. Immediate return None across all 6 debrid clients on abort signal.
3. routes/playback.py watchlist sync aborted during Kodi shutdown across all 3 routes.
4. Main.py VIEW_REVIEW safe JSON decoding from SQLite cache with control.loads_json.
5. watchnixtoons2.py _embed_api_origin protocol-relative URL scheme self-containment.
"""

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

from resources.lib.ui import control, database
from resources.lib.debrid.real_debrid import RealDebrid
from resources.lib.debrid.torbox import TorBox
from resources.lib.debrid.all_debrid import AllDebrid
from resources.lib.debrid.debrid_link import DebridLink
from resources.lib.debrid.premiumize import Premiumize
from resources.lib.debrid.easydebrid import EasyDebrid
from resources.lib.pages.watchnixtoons2 import Sources as WNT2Sources
from resources.lib import Main


class TestMilestone2AdversarialHardening(unittest.TestCase):
    def setUp(self):
        control.clearSettingsCache()

    def tearDown(self):
        control.cleanup()

    # ── 1. EasyDebrid Non-Blocking Backoff & Float Headers ─────────────────────

    def test_easydebrid_waitforabort_and_float_headers(self):
        """Verify EasyDebrid parses float Retry-After, calls waitForAbort, and avoids time.sleep."""
        ed = EasyDebrid()
        resp_429 = MagicMock(status_code=429, headers={'Retry-After': '2.5'})
        resp_200 = MagicMock(status_code=200, ok=True)

        with patch('resources.lib.ui.client.get', side_effect=[resp_429, resp_200]) as mock_get, \
             patch('time.sleep') as mock_sleep, \
             patch('resources.lib.ui.control.monitor.waitForAbort', return_value=False) as mock_wait:
            res = ed._request_with_backoff('get', 'https://easydebrid.com/api/v1/user/details')
            self.assertEqual(res, resp_200)
            self.assertEqual(mock_get.call_count, 2)
            self.assertFalse(mock_sleep.called, "time.sleep must not be called")
            self.assertTrue(mock_wait.called, "waitForAbort must be called")
            wait_arg = mock_wait.call_args[0][0]
            # Base 2.5 + jitter [0.1, 0.4] -> in range [2.6, 2.95]
            self.assertGreaterEqual(wait_arg, 2.6)
            self.assertLessEqual(wait_arg, 2.95)

    # ── 2. Debrid Clients Immediate Abort Return None ─────────────────────────

    def test_all_debrid_clients_return_none_on_abort(self):
        """Verify all 6 debrid clients return None immediately and abort retries when waitForAbort returns True."""
        clients = [
            (RealDebrid(), 'get', 'https://api.real-debrid.com/rest/1.0/torrents'),
            (TorBox(), 'get', 'https://api.torbox.app/v1/api/torrents/checkcached'),
            (AllDebrid(), 'get', 'https://api.alldebrid.com/v4.1/test'),
            (DebridLink(), 'post', 'https://debrid-link.fr/api/v2/test'),
            (Premiumize(), 'get', 'https://www.premiumize.me/api/test'),
            (EasyDebrid(), 'get', 'https://easydebrid.com/api/v1/user/details'),
        ]

        resp_429 = MagicMock(status_code=429, headers={'Retry-After': '1'})

        for client_inst, method, test_url in clients:
            with patch(f'resources.lib.ui.client.{method}', return_value=resp_429) as mock_http, \
                 patch('resources.lib.ui.control.monitor.waitForAbort', return_value=True) as mock_wait:
                res = client_inst._request_with_backoff(method, test_url)
                self.assertIsNone(res, f"{client_inst.__class__.__name__} failed to return None on abort")
                self.assertEqual(mock_http.call_count, 1, f"{client_inst.__class__.__name__} reissued HTTP call despite abort")
                mock_wait.assert_called_once()

    def test_all_debrid_clients_retry_when_not_aborted(self):
        """Verify all 6 debrid clients proceed to retry when waitForAbort returns False."""
        clients = [
            (RealDebrid(), 'get', 'https://api.real-debrid.com/rest/1.0/torrents'),
            (TorBox(), 'get', 'https://api.torbox.app/v1/api/torrents/checkcached'),
            (AllDebrid(), 'get', 'https://api.alldebrid.com/v4.1/test'),
            (DebridLink(), 'post', 'https://debrid-link.fr/api/v2/test'),
            (Premiumize(), 'get', 'https://www.premiumize.me/api/test'),
            (EasyDebrid(), 'get', 'https://easydebrid.com/api/v1/user/details'),
        ]

        resp_429 = MagicMock(status_code=429, headers={'Retry-After': '1'})
        resp_200 = MagicMock(status_code=200, ok=True)

        for client_inst, method, test_url in clients:
            with patch(f'resources.lib.ui.client.{method}', side_effect=[resp_429, resp_200]) as mock_http, \
                 patch('resources.lib.ui.control.monitor.waitForAbort', return_value=False) as mock_wait:
                res = client_inst._request_with_backoff(method, test_url)
                self.assertEqual(res, resp_200, f"{client_inst.__class__.__name__} did not return retry response")
                self.assertEqual(mock_http.call_count, 2, f"{client_inst.__class__.__name__} did not retry HTTP call")
                mock_wait.assert_called_once()

    # ── 3. routes/playback.py Watchlist Sync Abort Checks ─────────────────────

    def test_routes_playback_watchlist_sync_respects_abort(self):
        """Verify MARKED_AS_WATCHED, MARKED_AS_UNWATCHED, MARK_PREVIOUS_WATCHED guard sync_watchlist with abort."""
        from resources.lib.routes.playback import MARKED_AS_WATCHED, MARKED_AS_UNWATCHED, MARK_PREVIOUS_WATCHED

        route_actions = [
            (MARKED_AS_WATCHED, '12345/1/'),
            (MARKED_AS_UNWATCHED, '12345/2/'),
            (MARK_PREVIOUS_WATCHED, '12345/3/'),
        ]

        # Case A: When abort is requested, sync_watchlist is bypassed across all routes
        for func, payload in route_actions:
            with patch('resources.lib.ui.control.monitor.waitForAbort', return_value=True) as mock_abort, \
                 patch('service.sync_watchlist') as mock_sync, \
                 patch('resources.lib.WatchlistIntegration.watchlist_update_episode', return_value=True), \
                 patch('resources.lib.ui.database.get_show', return_value=None), \
                 patch('resources.lib.ui.database.get_episode', return_value=None), \
                 patch('resources.lib.ui.database.get_episode_list', return_value=[]), \
                 patch('resources.lib.routes.playback.save_to_watch_history'), \
                 patch('resources.lib.ui.control.yesno_dialog', return_value=True):
                func(payload, {})
                mock_sync.assert_not_called()
                mock_abort.assert_called_with(3)

        # Case B: When abort is NOT requested, sync_watchlist executes across all routes
        for func, payload in route_actions:
            with patch('resources.lib.ui.control.monitor.waitForAbort', return_value=False) as mock_abort, \
                 patch('service.sync_watchlist') as mock_sync, \
                 patch('resources.lib.WatchlistIntegration.watchlist_update_episode', return_value=True), \
                 patch('resources.lib.ui.database.get_show', return_value=None), \
                 patch('resources.lib.ui.database.get_episode', return_value=None), \
                 patch('resources.lib.ui.database.get_episode_list', return_value=[]), \
                 patch('resources.lib.routes.playback.save_to_watch_history'), \
                 patch('resources.lib.ui.control.yesno_dialog', return_value=True):
                func(payload, {})
                mock_sync.assert_called_once_with(True)
                mock_abort.assert_called_with(3)

    # ── 4. Main.py VIEW_REVIEW Corrupted SQLite Cache Guard ───────────────────

    @patch('resources.lib.ui.control.notify')
    def test_main_view_review_corrupted_cache_handles_gracefully(self, mock_notify):
        """Verify VIEW_REVIEW gracefully handles corrupted/invalid JSON in SQLite cache via control.loads_json."""
        # Insert corrupted JSON string in cache
        database.cache_insert('otaku_reviews_99999', '{"corrupted json: [')
        control.setGlobalProp('otaku.reviews.mal_id', '99999')
        control.setGlobalProp('otaku.reviews.page', '1')

        with patch('resources.lib.ui.control.textviewer_dialog') as mock_dialog:
            # Must not raise json.decoder.JSONDecodeError!
            Main.VIEW_REVIEW('99999/0/', {})
            mock_dialog.assert_not_called()
            mock_notify.assert_called_once()
            self.assertEqual(mock_notify.call_args[0][0], control.ADDON_NAME)

    # ── 5. WatchNixtoons2 Protocol-Relative Origin Dynamization ───────────────

    def test_watchnixtoons2_protocol_relative_scheme_fallback(self):
        """Verify _embed_api_origin correctly handles protocol-relative URLs (//netloc)."""
        scraper = WNT2Sources()
        self.assertEqual(
            scraper._embed_api_origin('//mirror.wcostream.tv/embed/player.php'),
            'https://mirror.wcostream.tv/'
        )
        self.assertEqual(
            scraper._embed_api_origin('http://cdn.wcostream.com/inc/embed/'),
            'http://cdn.wcostream.com/'
        )
        self.assertEqual(
            scraper._embed_api_origin('https://embed.wcostream.com/inc/embed/'),
            'https://embed.wcostream.com/'
        )
        self.assertEqual(
            scraper._embed_api_origin('invalid-url-string'),
            'https://embed.wcostream.com/'
        )


if __name__ == '__main__':
    unittest.main()
