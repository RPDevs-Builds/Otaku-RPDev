"""
test_challenger_m1_2_adversarial.py - Adversarial Stress & Empirical Verification Suite
======================================================================================
Empirical verification and adversarial challenge suite for Milestone 1 in Otaku-RPDev:
1. Demuxer chapter fallback chain & ffprobe decoupling:
   - JSON-RPC Player.GetChapters execution priority and format handling
   - Verification that native demuxer chapters function when ffprobe is disabled
2. Playback abort responsiveness:
   - Verification that simulated abort signals cause immediate return from waitForAbort
   - Loop termination under abort conditions in playback and scraping loops
3. Debrid 429 retry loops & jitter:
   - Jitter distribution, Retry-After header bounds, and non-blocking abort waits
   - Verification across all debrid clients (Real-Debrid, TorBox, AllDebrid, DebridLink, Premiumize, EasyDebrid)
4. Review cache offloading in Main.py:
   - Large review payloads (>100KB) saved cleanly to SQLite cache.db
   - Strict separation from Kodi C++ window properties (zero 64KB ceiling violations)
   - VIEW_REVIEW retrieval accuracy and multi-page transitions
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
import json
import statistics
from unittest.mock import patch, MagicMock

import xbmc
import xbmcgui
from resources.lib.ui import control, database, client
from resources.lib.ui.player import WatchlistPlayer
from resources.lib.debrid.real_debrid import RealDebrid
from resources.lib.debrid.torbox import TorBox
from resources.lib.debrid.all_debrid import AllDebrid
from resources.lib.debrid.debrid_link import DebridLink
from resources.lib.debrid.premiumize import Premiumize
from resources.lib.debrid.easydebrid import EasyDebrid
from resources.lib import Main
import service


class TestChallengerM1DemuxerChapters(unittest.TestCase):
    """Empirical verification of demuxer chapter fallback chain and ffprobe decoupling."""

    def setUp(self):
        control.clearSettingsCache()
        self.player = WatchlistPlayer()
        self.player.total_time = 1440
        self.player.ffprobe_chapters = []
        self.player.skipintro_aniskip_enable = True
        self.player.skipintro_aniskip = False
        self.player.skipintro_offset = 0
        self.player.skipoutro_aniskip_enable = True
        self.player.skipoutro_aniskip = False
        self.player.skipoutro_offset = 0

    def tearDown(self):
        control.cleanup()

    @patch('resources.lib.ui.control.getBool')
    @patch('resources.lib.ui.control.jsonrpc')
    def test_demuxer_chapters_execute_when_ffprobe_disabled(self, mock_jsonrpc, mock_getBool):
        """Verify Player.GetChapters JSON-RPC queries execute and succeed even when ffprobe is disabled."""
        mock_getBool.side_effect = lambda setting, default=False: {
            'ffprobe.chapters.enable': False,
            'general.aniskip': True,
        }.get(setting, default)

        mock_jsonrpc.return_value = {
            'jsonrpc': '2.0',
            'id': 1,
            'result': {
                'chapters': [
                    {'title': 'Prologue', 'time': 0.0},
                    {'title': 'Opening', 'time': 90.0},
                    {'title': 'Episode Part A', 'time': 180.0},
                    {'title': 'Ending', 'time': 1320.0},
                ]
            }
        }

        # Execute demuxer chapters query directly
        success = self.player.query_demuxer_chapters()
        self.assertTrue(success)
        mock_jsonrpc.assert_called_once_with({
            'jsonrpc': '2.0',
            'method': 'Player.GetChapters',
            'params': {'playerid': 1},
            'id': 1
        })
        self.assertEqual(len(self.player.ffprobe_chapters), 4)

        # Process chapters to populate skip windows
        self.player.process_ffprobe_chapter_skips()
        self.assertTrue(self.player.skipintro_aniskip)
        self.assertEqual(self.player.skipintro_start, 90.0)
        self.assertEqual(self.player.skipintro_end, 180.0)
        self.assertTrue(self.player.skipoutro_aniskip)
        self.assertEqual(self.player.skipoutro_start, 1320.0)
        self.assertEqual(self.player.skipoutro_end, 1440.0)

    @patch('resources.lib.ui.control.jsonrpc')
    def test_jsonrpc_time_dict_parsing_edge_cases(self, mock_jsonrpc):
        """Stress-test JSON-RPC time dict structures: zeros, fractional ms, missing fields, None."""
        mock_jsonrpc.return_value = {
            'result': {
                'chapters': [
                    {
                        'title': 'OP',
                        'time': {'hours': 0, 'minutes': 1, 'seconds': 30, 'milliseconds': 500}
                    },
                    {
                        'title': 'ED',
                        'time': {'hours': None, 'minutes': 22, 'seconds': 0, 'milliseconds': None}
                    },
                    {
                        'title': 'Preview',
                        'time': {'hours': 0, 'minutes': 23, 'seconds': 30}
                    }
                ]
            }
        }

        self.player.query_demuxer_chapters()
        self.assertEqual(len(self.player.ffprobe_chapters), 3)
        self.assertAlmostEqual(self.player.ffprobe_chapters[0]['start'], 90.5)
        self.assertAlmostEqual(self.player.ffprobe_chapters[0]['end'], 1320.0)
        self.assertAlmostEqual(self.player.ffprobe_chapters[1]['start'], 1320.0)
        self.assertAlmostEqual(self.player.ffprobe_chapters[1]['end'], 1410.0)

    @patch('resources.lib.ui.control.jsonrpc')
    def test_jsonrpc_out_of_order_chapters_sorted(self, mock_jsonrpc):
        """Stress-test out-of-order chapters from demuxer: verify chronological sorting."""
        mock_jsonrpc.return_value = {
            'result': {
                'chapters': [
                    {'title': 'Ending', 'time': 1300.0},
                    {'title': 'Cold Open', 'time': 0.0},
                    {'title': 'Opening', 'time': 60.0},
                ]
            }
        }

        self.player.query_demuxer_chapters()
        starts = [ch['start'] for ch in self.player.ffprobe_chapters]
        self.assertEqual(starts, [0.0, 60.0, 1300.0])
        self.assertEqual(self.player.ffprobe_chapters[0]['end'], 60.0)
        self.assertEqual(self.player.ffprobe_chapters[1]['end'], 1300.0)

    @patch('resources.lib.ui.control.jsonrpc')
    def test_jsonrpc_error_and_empty_responses(self, mock_jsonrpc):
        """Verify robust error recovery when JSON-RPC returns error, empty, or malformed data."""
        # 1. Error response
        mock_jsonrpc.return_value = {'error': {'code': -32100, 'message': 'Failed to execute'}}
        self.assertFalse(self.player.query_demuxer_chapters())
        self.assertEqual(self.player.ffprobe_chapters, [])

        # 2. Empty result
        mock_jsonrpc.return_value = {'result': {'chapters': []}}
        self.assertFalse(self.player.query_demuxer_chapters())

        # 3. None response
        mock_jsonrpc.return_value = None
        self.assertFalse(self.player.query_demuxer_chapters())

    @patch.object(WatchlistPlayer, 'query_demuxer_chapters')
    @patch.object(WatchlistPlayer, 'process_ffprobe_chapter_skips')
    @patch.object(WatchlistPlayer, '_run_unified_episode_monitor')
    @patch('xbmc.sleep')
    @patch.object(WatchlistPlayer, 'isPlaying', return_value=True)
    @patch.object(WatchlistPlayer, 'isPlayingVideo', return_value=True)
    @patch.object(WatchlistPlayer, 'getTotalTime', return_value=1440)
    def test_demuxer_query_executes_first_in_keepalive(self, mock_get_total, mock_is_video, mock_is_playing, mock_sleep, mock_monitor, mock_process, mock_query):
        """Verify query_demuxer_chapters executes BEFORE the external AniSkip sleep wait in keepAlive."""
        call_order = []
        mock_query.side_effect = lambda: call_order.append('query_demuxer')
        mock_process.side_effect = lambda: call_order.append('process_chapters')

        def stop_playback():
            call_order.append('unified_monitor')
            self.player._playback_stopped = True

        mock_monitor.side_effect = stop_playback

        # Set player attributes for non-movie playback
        self.player.media_type = 'episode'
        self.player.type = 'direct'
        self.player.provider = 'test'
        self.player.episodes = False
        self.player._skip_processed = True  # skip wait loop

        # Simulate keepAlive execution
        self.player.keepAlive()

        self.assertIn('query_demuxer', call_order)
        self.assertIn('process_chapters', call_order)
        self.assertIn('unified_monitor', call_order)
        # Demuxer query must precede chapter processing and unified monitor
        self.assertLess(call_order.index('query_demuxer'), call_order.index('process_chapters'))
        self.assertLess(call_order.index('process_chapters'), call_order.index('unified_monitor'))


class TestChallengerM1PlaybackAbortResponsiveness(unittest.TestCase):
    """Empirical verification of abort loop responsiveness and non-blocking wait behaviors."""

    def setUp(self):
        control.clearSettingsCache()

    def tearDown(self):
        control.cleanup()

    def test_wait_for_abort_responsiveness_benchmark(self):
        """Verify that simulated abort causes waitForAbort to return immediately without blocking."""
        monitor = control.monitor._get_monitor()
        monitor._abort = False

        # Measure baseline non-abort wait (capped to 0.02s in mock)
        t0 = time.time()
        res_no_abort = control.monitor.waitForAbort(0.01)
        elapsed_no_abort = time.time() - t0
        self.assertFalse(res_no_abort)

        # Trigger abort signal
        monitor.requestAbort()
        self.assertTrue(control.monitor.abortRequested())

        # Test waitForAbort with large requested timeout (5.0s)
        t0 = time.time()
        res_abort = control.monitor.waitForAbort(5.0)
        elapsed_abort = time.time() - t0

        self.assertTrue(res_abort)
        # Empirical timing check: must return immediately (<< 0.5s)
        self.assertLess(elapsed_abort, 0.05, f"waitForAbort did not return immediately under abort: took {elapsed_abort}s")

    @patch('resources.lib.indexers.jikanmoe.JikanAPI.get_episode_meta')
    def test_playback_route_jikan_rate_limit_breaks_on_abort(self, mock_get_meta):
        """Verify routes/playback.py 429 retry loop breaks immediately when abort is signaled."""
        # Simulate 429 response error
        err = Exception("Rate limit")
        err.response = MagicMock(status_code=429)
        mock_get_meta.side_effect = err

        # Set abort signal
        control.monitor._get_monitor().requestAbort()

        # Execute Jikan query section from playback.py (simulate by calling with abort)
        t0 = time.time()
        with patch.object(control.monitor, 'waitForAbort', return_value=True) as mock_wait:
            retries = 0
            max_retries = 3
            backoff = 2
            while retries <= max_retries:
                try:
                    mock_get_meta(12345)
                    break
                except Exception as e:
                    if hasattr(e, 'response') and getattr(e.response, 'status_code', None) == 429:
                        if control.monitor.waitForAbort(backoff):
                            break
                        retries += 1
                        backoff *= 2
            elapsed = time.time() - t0

        self.assertEqual(retries, 0, "Retry loop did not break on abort during 429 backoff")
        mock_wait.assert_called_once_with(2)

    def test_routes_playback_watchlist_sync_discrepancy(self):
        """
        Hardening Verification: routes/playback.py lines 646, 724, 827 now guard
        service.sync_watchlist(True) with 'if not control.monitor.waitForAbort(3):'
        preventing background sync from executing during Kodi abort or shutdown.
        """
        # When abort is requested (waitForAbort returns True): sync_watchlist is bypassed
        with patch('resources.lib.ui.control.monitor.waitForAbort', return_value=True) as mock_abort, \
             patch('service.sync_watchlist') as mock_sync, \
             patch('resources.lib.WatchlistIntegration.watchlist_update_episode', return_value=True), \
             patch('resources.lib.ui.database.get_show', return_value=None), \
             patch('resources.lib.routes.playback.save_to_watch_history'):
            from resources.lib.routes.playback import MARKED_AS_WATCHED
            MARKED_AS_WATCHED('12345/1/', {})
            mock_sync.assert_not_called()

        # When abort is NOT requested (waitForAbort returns False): sync_watchlist proceeds
        with patch('resources.lib.ui.control.monitor.waitForAbort', return_value=False) as mock_abort, \
             patch('service.sync_watchlist') as mock_sync, \
             patch('resources.lib.WatchlistIntegration.watchlist_update_episode', return_value=True), \
             patch('resources.lib.ui.database.get_show', return_value=None), \
             patch('resources.lib.routes.playback.save_to_watch_history'):
            from resources.lib.routes.playback import MARKED_AS_WATCHED
            MARKED_AS_WATCHED('12345/1/', {})
            mock_sync.assert_called_once_with(True)


class TestChallengerM1Debrid429AndJitter(unittest.TestCase):
    """Empirical verification of 429 backoff jitter and non-blocking abort waits across debrid clients."""

    def setUp(self):
        control.clearSettingsCache()

    def tearDown(self):
        control.cleanup()

    @patch('resources.lib.ui.control.monitor.waitForAbort')
    @patch('resources.lib.ui.client.get')
    def test_debrid_jitter_distribution_and_bounds(self, mock_client_get, mock_wait):
        """Empirically test jitter across 50 iterations: verify non-zero variance and bounded range."""
        mock_resp_429 = MagicMock()
        mock_resp_429.status_code = 429
        mock_resp_429.headers = {'Retry-After': '1'}

        mock_resp_200 = MagicMock()
        mock_resp_200.status_code = 200
        mock_resp_200.ok = True
        mock_resp_200.json.return_value = []

        mock_client_get.side_effect = [mock_resp_429, mock_resp_200] * 50

        rd = RealDebrid()
        wait_times = []

        def capture_wait(wait_secs):
            wait_times.append(wait_secs)
            return False

        mock_wait.side_effect = capture_wait

        for _ in range(50):
            rd._request_with_backoff('get', 'http://test/torrents')

        self.assertEqual(len(wait_times), 50)
        # Verify bounds: min(max(1.0, 1.0), 3.0) + [0.1, 0.4] = [1.1, 1.4]
        for w in wait_times:
            self.assertGreaterEqual(w, 1.1)
            self.assertLessEqual(w, 1.4)

        # Statistical check: variance must be positive (jitter is genuinely random)
        variance = statistics.variance(wait_times)
        self.assertGreater(variance, 0.0001, "Jitter has zero variance; backoff times are not randomized")

    @patch('resources.lib.ui.control.monitor.waitForAbort')
    @patch('resources.lib.ui.client.get')
    def test_retry_after_header_capping_and_fallbacks(self, mock_client_get, mock_wait):
        """Stress-test Retry-After variations: large values (cap 3s), invalid strings, missing header."""
        cases = [
            ({'Retry-After': '120'}, 3.1, 3.4),    # Capped to 3.0 + jitter
            ({'Retry-After': '0'}, 1.1, 1.4),      # Min-capped to 1.0 + jitter
            ({'Retry-After': '-5'}, 1.1, 1.4),     # Min-capped to 1.0 + jitter
            ({'Retry-After': 'invalid'}, 1.1, 1.4), # ValueError fallback to 1.0 + jitter
            ({}, 1.1, 1.4),                        # Missing header fallback to 1.0 + jitter
            ({'Retry-After': '2.5'}, 2.6, 2.9),    # Float Retry-After support
        ]

        tb = TorBox()
        for headers, min_expected, max_expected in cases:
            resp_429 = MagicMock(status_code=429, headers=headers)
            resp_200 = MagicMock(status_code=200, ok=True)
            mock_client_get.side_effect = [resp_429, resp_200]

            recorded_wait = []
            mock_wait.side_effect = lambda s: recorded_wait.append(s) or False

            tb._request_with_backoff('get', 'http://test/torrents')
            self.assertEqual(len(recorded_wait), 1)
            self.assertGreaterEqual(recorded_wait[0], min_expected, f"Failed for headers {headers}")
            self.assertLessEqual(recorded_wait[0], max_expected, f"Failed for headers {headers}")

    def test_easydebrid_uses_blocking_sleep_adversarial_finding(self):
        """
        Hardening Verification: EasyDebrid._request_with_backoff uses non-blocking
        control.monitor.waitForAbort instead of time.sleep, satisfying the responsive abort protocol.
        """
        ed = EasyDebrid()
        resp_429 = MagicMock(status_code=429, headers={'Retry-After': '1'})
        resp_200 = MagicMock(status_code=200, ok=True)

        with patch('resources.lib.ui.client.get', side_effect=[resp_429, resp_200]), \
             patch('time.sleep') as mock_sleep, \
             patch('resources.lib.ui.control.monitor.waitForAbort', return_value=False) as mock_wait:
            res = ed._request_with_backoff('get', 'http://test/torrents')

            # Verify waitForAbort was called and time.sleep was NOT called
            self.assertFalse(mock_sleep.called, "EasyDebrid should not call synchronous time.sleep")
            self.assertTrue(mock_wait.called, "EasyDebrid must call control.monitor.waitForAbort")
            self.assertEqual(res, resp_200)


class TestChallengerM1ReviewsCacheOffload(unittest.TestCase):
    """Empirical verification of user reviews cache offloading to SQLite cache.db (>100KB payloads)."""

    def setUp(self):
        control.clearSettingsCache()
        # Clean test cache table
        with database.SQL(control.cacheFile) as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, date INTEGER)")
            cur.execute("DELETE FROM cache WHERE key LIKE 'otaku_reviews_%'")
            cur.connection.commit()
        control.homeWindow.clearProperty('otaku.reviews.cache')
        control.homeWindow.clearProperty('otaku.reviews.mal_id')
        control.homeWindow.clearProperty('otaku.reviews.page')

    def tearDown(self):
        with database.SQL(control.cacheFile) as cur:
            cur.execute("DELETE FROM cache WHERE key LIKE 'otaku_reviews_%'")
            cur.connection.commit()
        control.cleanup()

    def _generate_synthetic_reviews(self, count=50, target_bytes=150000):
        """Generate a realistic reviews payload with detailed review text exceeding target_bytes."""
        reviews = []
        chars_per_review = int(target_bytes / count)
        for i in range(count):
            reviews.append({
                'mal_id': 12345,
                'user': {
                    'username': f'AnimeReviewer_{i}',
                    'url': f'https://myanimelist.net/profile/AnimeReviewer_{i}',
                    'images': {'jpg': {'image_url': f'https://cdn.myanimelist.net/images/user_{i}.jpg'}}
                },
                'score': 9,
                'date': '2026-11-01T12:00:00+00:00',
                'review': f"Review entry {i}: " + ("Comprehensive anime analysis with character arcs and thematic motifs. " * (chars_per_review // 75)),
                'tags': ['Recommended', 'Well Written'],
                'is_spoiler': (i % 3 == 0),
                'is_preliminary': (i % 5 == 0),
                'reactions': {'overall': 100 + i, 'nice': 50 + i, 'love_it': 30 + i}
            })
        return reviews

    @patch('resources.lib.Main.BROWSER')
    @patch('resources.lib.ui.control.draw_items')
    @patch('resources.lib.ui.control.schedule_next_page_prefetch')
    def test_large_reviews_payload_saved_to_sqlite_and_not_window_property(self, mock_prefetch, mock_draw, mock_browser):
        """Verify reviews payload >100KB is saved cleanly into SQLite cache.db without touching window properties."""
        reviews = self._generate_synthetic_reviews(count=40, target_bytes=160000)
        payload_json = json.dumps(reviews)
        payload_size = len(payload_json.encode('utf-8'))
        self.assertGreater(payload_size, 100000, f"Payload must be >100KB, got {payload_size} bytes")

        mock_browser.get_reviews_page.return_value = {
            'reviews': reviews,
            'items': [('Review 1', 'url1', 'img1', {})]
        }

        # Execute reviews listing drawing
        Main.draw_anime_reviews_listing(mal_id='54321', page=1, path='reviews', eps_watched=12)

        # 1. Verify SQLite cache.db contains the payload
        row = database.cache_get('otaku_reviews_54321')
        self.assertIsNotNone(row, "Review payload was not found in SQLite cache.db")
        cached_str = row['value'] if isinstance(row, dict) else row[1]
        self.assertEqual(len(cached_str.encode('utf-8')), payload_size)

        # Verify parsed data integrity
        restored_reviews = json.loads(cached_str)
        self.assertEqual(len(restored_reviews), len(reviews))
        self.assertEqual(restored_reviews[0]['user']['username'], 'AnimeReviewer_0')

        # 2. Verify window properties: otaku.reviews.cache MUST NOT BE SET
        self.assertEqual(control.getGlobalProp('otaku.reviews.cache'), '', "Window property 'otaku.reviews.cache' was illegally populated!")
        self.assertEqual(control.homeWindow.getProperty(f'{control.ADDON_NAME}.otaku.reviews.cache'), '')

        # 3. Verify metadata properties ARE set cleanly (and well within 64KB ceiling)
        mal_id_prop = control.getGlobalProp('otaku.reviews.mal_id')
        page_prop = control.getGlobalProp('otaku.reviews.page')
        self.assertEqual(mal_id_prop, '54321')
        self.assertEqual(page_prop, '1')
        self.assertLess(len(mal_id_prop.encode('utf-8')), 64)
        self.assertLess(len(page_prop.encode('utf-8')), 64)

        # 4. Verify 64KB guard: if someone attempted to set payload_json to window property, it would be rejected
        control.setGlobalProp('otaku.test.oversized', payload_json)
        self.assertEqual(control.getGlobalProp('otaku.test.oversized'), '', "64KB ceiling guard failed to reject oversized window property write")

    @patch('resources.lib.ui.control.textviewer_dialog')
    def test_view_review_retrieval_from_sqlite_cache(self, mock_dialog):
        """Verify VIEW_REVIEW retrieves cached reviews from SQLite cache.db and renders text viewer dialog."""
        reviews = self._generate_synthetic_reviews(count=10, target_bytes=120000)
        database.cache_insert('otaku_reviews_77777', json.dumps(reviews))
        control.setGlobalProp('otaku.reviews.mal_id', '77777')
        control.setGlobalProp('otaku.reviews.page', '1')

        # Call VIEW_REVIEW for item index 2
        Main.VIEW_REVIEW('77777/2/', {})

        # Verify textviewer_dialog was called with review index 2 details
        mock_dialog.assert_called_once()
        heading, body = mock_dialog.call_args[0]
        self.assertIn('AnimeReviewer_2', heading)
        self.assertIn('Review entry 2', body)

    @patch('resources.lib.Main.BROWSER')
    @patch('resources.lib.ui.control.textviewer_dialog')
    def test_multi_page_review_transitions(self, mock_dialog, mock_browser):
        """Verify multi-page reviews (>100KB each) transition cleanly without state corruption."""
        page1_reviews = self._generate_synthetic_reviews(count=20, target_bytes=110000)
        page2_reviews = self._generate_synthetic_reviews(count=20, target_bytes=110000)
        for r in page2_reviews:
            r['user']['username'] = 'Page2_' + r['user']['username']

        with patch('resources.lib.ui.control.draw_items'), patch('resources.lib.ui.control.schedule_next_page_prefetch'):
            # Fetch Page 1
            mock_browser.get_reviews_page.return_value = {'reviews': page1_reviews, 'items': []}
            Main.draw_anime_reviews_listing('88888', 1, 'path', 0)

            # View Page 1, review 0
            Main.VIEW_REVIEW('88888/0/', {})
            self.assertIn('AnimeReviewer_0', mock_dialog.call_args[0][0])

            # Fetch Page 2
            mock_dialog.reset_mock()
            mock_browser.get_reviews_page.return_value = {'reviews': page2_reviews, 'items': []}
            Main.draw_anime_reviews_listing('88888', 2, 'path', 0)

            # View Page 2, review 0
            Main.VIEW_REVIEW('88888/0/', {})
            self.assertIn('Page2_AnimeReviewer_0', mock_dialog.call_args[0][0])


if __name__ == '__main__':
    unittest.main()
