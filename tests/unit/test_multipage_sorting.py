# -*- coding: utf-8 -*-
"""
test_multipage_sorting.py - Hermetic Unit Tests for Multipage Sorting & Filtering
================================================================================
Comprehensive offline test suite verifying:
- Multipage settings retrieval and defensive bounds clamping.
- Normalized sort key extraction (Date, Episode, Rating, Default).
- Case-insensitive token text filtering, BBCode stripping, action item preservation.
- Window merging, deduplication, intermediate Next Page stripping, and 1,000 item ceiling.
- Stable multi-dimensional sorting with missing/unrated bottom-placement in both directions.
- Safe list pagination slicing.
- Database peek() cache hits (RAM, SQLite) and non-blocking miss non-execution.
- Database multipage_jobs SQLite queue lifecycle (enqueue, dequeue, progress, done, failed, prune).
"""

import os
import sys
import time
import threading
import unittest
from unittest.mock import MagicMock, patch

# Standardized Otaku Test Bootstrap
_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_TEST_DIR, '..' if os.path.basename(_TEST_DIR) in ('unit', 'integration', 'lint') else '.'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
_TESTS_DIR = os.path.join(_REPO_ROOT, 'tests')
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import conftest  # Centralized Kodi mock harness  # noqa: F401

from resources.lib.ui import control, database, multipage
from service import MultipageWorker
import xbmc


class RealisticMonitor:
    """Monitor simulator utilizing threading.Event for realistic timeout and abort responsiveness."""

    def __init__(self):
        self._abort = threading.Event()

    def abortRequested(self):
        return self._abort.is_set()

    def requestAbort(self):
        self._abort.set()

    def waitForAbort(self, timeout=0):
        return self._abort.wait(float(timeout))


class TestMultipageSettings(unittest.TestCase):
    """Verifies reading and bounds clamping of multipage settings."""

    def test_default_settings(self):
        """Default settings match expected schema values."""
        with patch.object(control, 'getInt') as mock_int, patch.object(control, 'getBool') as mock_bool:
            mock_int.side_effect = lambda k: {
                'multipage.precache.pages': 20,
                'multipage.sort.by': 0,
                'multipage.sort.order': 0,
                'multipage.display.mode': 0,
            }.get(k, 0)
            mock_bool.side_effect = lambda k: {
                'multipage.show.filter.item': True,
            }.get(k, True)

            cfg = multipage.get_multipage_settings()
            self.assertEqual(cfg['precache_pages'], 20)
            self.assertEqual(cfg['sort_by'], 0)
            self.assertEqual(cfg['sort_order'], 0)
            self.assertEqual(cfg['display_mode'], 0)
            self.assertTrue(cfg['show_filter_item'])

    def test_settings_clamping_and_fallbacks(self):
        """Settings out of bounds clamp to safe defaults."""
        with patch.object(control, 'getInt') as mock_int, patch.object(control, 'getBool') as mock_bool:
            # Test below minimum
            mock_int.side_effect = lambda k: {
                'multipage.precache.pages': 0,
                'multipage.sort.by': 99,
                'multipage.sort.order': -1,
                'multipage.display.mode': 5,
            }.get(k, 0)
            mock_bool.side_effect = lambda k: None

            cfg = multipage.get_multipage_settings()
            self.assertEqual(cfg['precache_pages'], 20)
            self.assertEqual(cfg['sort_by'], 0)
            self.assertEqual(cfg['sort_order'], 0)
            self.assertEqual(cfg['display_mode'], 0)
            self.assertTrue(cfg['show_filter_item'])

            # Test above maximum
            mock_int.side_effect = lambda k: {
                'multipage.precache.pages': 50,
                'multipage.sort.by': 2,
                'multipage.sort.order': 1,
                'multipage.display.mode': 1,
            }.get(k, 0)
            mock_bool.side_effect = lambda k: False

            cfg2 = multipage.get_multipage_settings()
            self.assertEqual(cfg2['precache_pages'], 20)  # Clamped to 20
            self.assertEqual(cfg2['sort_by'], 2)
            self.assertEqual(cfg2['sort_order'], 1)
            self.assertEqual(cfg2['display_mode'], 1)
            self.assertFalse(cfg2['show_filter_item'])


class TestSortKeyExtraction(unittest.TestCase):
    """Verifies extraction and normalization of sort keys."""

    def test_sort_key_default(self):
        """Default sort mode (0) returns 0."""
        item = {'name': 'Anime A', 'info': {'rating': 8.5, 'premiered': '2023-01-01', 'episode': 12}}
        self.assertEqual(multipage.extract_sort_key(item, 0), 0)
        self.assertEqual(multipage.extract_sort_key({}, 0), 0)
        self.assertEqual(multipage.extract_sort_key(None, 0), 0)

    def test_sort_key_date(self):
        """Date mode (1) normalizes dates and handles missing/partial dates."""
        item_full = {'name': 'Anime A', 'info': {'premiered': '2023-04-12'}}
        self.assertEqual(multipage.extract_sort_key(item_full, 1), '2023-04-12')

        item_slash = {'name': 'Anime B', 'info': {'premiered': '2022/10/05'}}
        self.assertEqual(multipage.extract_sort_key(item_slash, 1), '2022-10-05')

        item_year = {'name': 'Anime C', 'info': {'year': 2021}}
        self.assertEqual(multipage.extract_sort_key(item_year, 1), '2021')

        item_aired = {'name': 'Anime D', 'info': {'aired': '2020-01'}}
        self.assertEqual(multipage.extract_sort_key(item_aired, 1), '2020-01')

        # Missing date
        self.assertEqual(multipage.extract_sort_key({'info': {}}, 1), '')
        self.assertEqual(multipage.extract_sort_key({'info': {'premiered': None}}, 1), '')
        self.assertEqual(multipage.extract_sort_key({'info': {'premiered': ''}}, 1), '')
        self.assertEqual(multipage.extract_sort_key(None, 1), '')

    def test_sort_key_episode(self):
        """Episode mode (2) extracts integer episode count."""
        item_int = {'name': 'Anime A', 'info': {'episode': 24}}
        self.assertEqual(multipage.extract_sort_key(item_int, 2), 24)

        item_str = {'name': 'Anime B', 'info': {'episodes': '12'}}
        self.assertEqual(multipage.extract_sort_key(item_str, 2), 12)

        item_text = {'name': 'Anime C', 'info': {'total_episodes': '26 eps'}}
        self.assertEqual(multipage.extract_sort_key(item_text, 2), 26)

        # Missing or invalid episodes
        self.assertEqual(multipage.extract_sort_key({'info': {'episode': 0}}, 2), 0)
        self.assertEqual(multipage.extract_sort_key({'info': {'episode': 'unknown'}}, 2), 0)
        self.assertEqual(multipage.extract_sort_key({'info': {}}, 2), 0)
        self.assertEqual(multipage.extract_sort_key(None, 2), 0)

    def test_sort_key_rating(self):
        """Rating mode (3) extracts float rating score."""
        item_float = {'name': 'Anime A', 'info': {'rating': 8.75}}
        self.assertEqual(multipage.extract_sort_key(item_float, 3), 8.75)

        item_int = {'name': 'Anime B', 'info': {'score': 9}}
        self.assertEqual(multipage.extract_sort_key(item_int, 3), 9.0)

        item_dict = {'name': 'Anime C', 'info': {'rating': {'score': 7.6}}}
        self.assertEqual(multipage.extract_sort_key(item_dict, 3), 7.6)

        item_str = {'name': 'Anime D', 'info': {'averageScore': '82.5'}}
        self.assertEqual(multipage.extract_sort_key(item_str, 3), 82.5)

        # Missing or invalid rating
        self.assertEqual(multipage.extract_sort_key({'info': {'rating': 0.0}}, 3), 0.0)
        self.assertEqual(multipage.extract_sort_key({'info': {'rating': 'N/A'}}, 3), 0.0)
        self.assertEqual(multipage.extract_sort_key({'info': {}}, 3), 0.0)
        self.assertEqual(multipage.extract_sort_key(None, 3), 0.0)


class TestTextFiltering(unittest.TestCase):
    """Verifies text filtering with tokenization, BBCode stripping, and action item preservation."""

    def setUp(self):
        self.action_filter = {'name': '[COLOR yellow][Filter List by Text...][/COLOR]', 'url': 'plugin://plugin.video.otaku.rpdev/multipage_filter'}
        self.action_clear = {'name': '[COLOR red][Clear Filter][/COLOR]', 'url': 'plugin://plugin.video.otaku.rpdev/multipage_filter?action=clear'}
        self.item_aot = {
            'name': '[B]Attack on Titan[/B]',
            'url': 'plugin://plugin.video.otaku.rpdev/anime/1',
            'info': {'title': 'Shingeki no Kyojin', 'plot': 'Humanity fights against giant titans.'}
        }
        self.item_hero = {
            'name': '[COLOR blue]My Hero Academia[/COLOR]',
            'url': 'plugin://plugin.video.otaku.rpdev/anime/2',
            'info': {'title': 'Boku no Hero Academia', 'plot': 'Izuku Midoriya dreams of becoming a superhero.'}
        }
        self.item_demon = {
            'name': 'Demon Slayer',
            'url': 'plugin://plugin.video.otaku.rpdev/anime/3',
            'info': {'title': 'Kimetsu no Yaiba', 'plot': 'Tanjiro battles demons to save his sister.'}
        }
        self.next_page = {
            'name': 'Next Page (2)',
            'url': 'plugin://plugin.video.otaku.rpdev/next',
            'image': {'icon': 'resource://resource.images.otaku/next.png'}
        }
        self.items = [self.action_filter, self.item_aot, self.item_hero, self.item_demon, self.next_page]

    def test_filter_empty_query(self):
        """Empty query returns all items unchanged."""
        self.assertEqual(multipage.filter_window_by_text(self.items, ''), self.items)
        self.assertEqual(multipage.filter_window_by_text(self.items, '   '), self.items)
        self.assertEqual(multipage.filter_window_by_text(self.items, None), self.items)
        self.assertEqual(multipage.filter_window_by_text([], 'hero'), [])

    def test_filter_token_matching_and_bbcode_stripping(self):
        """Tokens match across stripped name, title, and plot; preserves action item; drops Next Page."""
        # Single token match on name
        res = multipage.filter_window_by_text(self.items, 'titan')
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0], self.action_filter)
        self.assertEqual(res[1], self.item_aot)

        # Token match on plot
        res2 = multipage.filter_window_by_text(self.items, 'superhero')
        self.assertEqual(len(res2), 2)
        self.assertEqual(res2[0], self.action_filter)
        self.assertEqual(res2[1], self.item_hero)

        # Multi-token match across fields ("hero" in name, "midoriya" in plot)
        res3 = multipage.filter_window_by_text(self.items, 'hero midoriya')
        self.assertEqual(len(res3), 2)
        self.assertEqual(res3[0], self.action_filter)
        self.assertEqual(res3[1], self.item_hero)

        # Non-matching multi-token
        res4 = multipage.filter_window_by_text(self.items, 'hero titan')
        self.assertEqual(len(res4), 1)
        self.assertEqual(res4[0], self.action_filter)


class TestWindowMerging(unittest.TestCase):
    """Verifies list merging, deduplication, Next Page row stripping, and 1,000 item ceiling."""

    def test_merge_deduplication_and_next_page_stripping(self):
        """Merges two pages, strips intermediate Next Page, deduplicates by ID, keeps tail Next Page."""
        action = {'name': '[Filter List by Text...]', 'url': 'plugin://plugin.video.otaku.rpdev/multipage_filter'}
        p1_item1 = {'name': 'Anime 1', 'url': 'url1', 'info': {'UniqueIDs': {'mal_id': '101'}}}
        p1_item2 = {'name': 'Anime 2', 'url': 'url2', 'info': {'UniqueIDs': {'mal_id': '102'}}}
        p1_next = {'name': 'Next Page (2)', 'image': {'icon': 'next.png'}}

        p2_item1 = {'name': 'Anime 2 (dup)', 'url': 'url2', 'info': {'UniqueIDs': {'mal_id': '102'}}}
        p2_item3 = {'name': 'Anime 3', 'url': 'url3', 'info': {'UniqueIDs': {'mal_id': '103'}}}
        p2_next = {'name': 'Next Page (3)', 'image': {'icon': 'next.png'}}

        page1 = [action, p1_item1, p1_item2, p1_next]
        page2 = [p2_item1, p2_item3, p2_next]

        merged = multipage.merge_window(page1, page2, max_items=1000)
        self.assertEqual(len(merged), 5)
        self.assertEqual(merged[0], action)
        self.assertEqual(merged[1], p1_item1)
        self.assertEqual(merged[2], p1_item2)
        self.assertEqual(merged[3], p2_item3)
        self.assertEqual(merged[4], p2_next)

    def test_merge_1000_item_capping(self):
        """Merged window is strictly capped at max_items (1,000) and drops tail Next Page when full."""
        page1 = [{'name': f'Anime {i}', 'url': f'url_{i}'} for i in range(700)]
        page2 = [{'name': f'Anime {i}', 'url': f'url_{i}'} for i in range(700, 1200)]
        next_page = {'name': 'Next Page', 'image': {'icon': 'next.png'}}
        page2.append(next_page)

        merged = multipage.merge_window(page1, page2, max_items=1000)
        self.assertEqual(len(merged), 1000)
        self.assertNotIn(next_page, merged)


class TestWindowSorting(unittest.TestCase):
    """Verifies stable sorting, action/pagination preservation, and missing-value bottom-placement."""

    def setUp(self):
        self.header = {'name': '[Filter List by Text...]', 'url': 'filter_url'}
        self.footer = {'name': 'Next Page (2)', 'image': {'icon': 'next.png'}}

        self.item_high = {'name': 'Top Anime', 'info': {'rating': 9.2, 'premiered': '2024-01-01', 'episode': 24}}
        self.item_mid = {'name': 'Mid Anime', 'info': {'rating': 7.5, 'premiered': '2022-05-10', 'episode': 12}}
        self.item_low = {'name': 'Low Anime', 'info': {'rating': 6.0, 'premiered': '2020-03-15', 'episode': 6}}
        self.item_unrated1 = {'name': 'Unrated 1', 'info': {'rating': 0.0, 'premiered': '', 'episode': 0}}
        self.item_unrated2 = {'name': 'Unrated 2', 'info': {'rating': None, 'premiered': None, 'episode': None}}

        self.items = [self.header, self.item_mid, self.item_unrated1, self.item_high, self.item_unrated2, self.item_low, self.footer]

    def test_sort_default_mode(self):
        """Mode 0 preserves original order."""
        res = multipage.sort_window(self.items, 0, 0)
        self.assertEqual(res, self.items)

    def test_sort_rating_descending(self):
        """Descending rating: highest first, unrated at the very bottom, header and footer preserved."""
        res = multipage.sort_window(self.items, 3, 0)
        self.assertEqual(res[0], self.header)
        self.assertEqual(res[1], self.item_high)   # 9.2
        self.assertEqual(res[2], self.item_mid)    # 7.5
        self.assertEqual(res[3], self.item_low)    # 6.0
        self.assertEqual(res[4], self.item_unrated1)  # unrated at bottom
        self.assertEqual(res[5], self.item_unrated2)  # unrated at bottom
        self.assertEqual(res[6], self.footer)

    def test_sort_rating_ascending(self):
        """Ascending rating: lowest first, unrated STILL at the very bottom."""
        res = multipage.sort_window(self.items, 3, 1)
        self.assertEqual(res[0], self.header)
        self.assertEqual(res[1], self.item_low)    # 6.0
        self.assertEqual(res[2], self.item_mid)    # 7.5
        self.assertEqual(res[3], self.item_high)   # 9.2
        self.assertEqual(res[4], self.item_unrated1)  # unrated at bottom
        self.assertEqual(res[5], self.item_unrated2)  # unrated at bottom
        self.assertEqual(res[6], self.footer)

    def test_sort_date_descending_and_ascending(self):
        """Date mode sorts chronologically with missing dates at the bottom."""
        # Descending (newest first)
        res_desc = multipage.sort_window(self.items, 1, 0)
        self.assertEqual(res_desc[0], self.header)
        self.assertEqual(res_desc[1], self.item_high)  # 2024
        self.assertEqual(res_desc[2], self.item_mid)   # 2022
        self.assertEqual(res_desc[3], self.item_low)   # 2020
        self.assertEqual(res_desc[4], self.item_unrated1)
        self.assertEqual(res_desc[5], self.item_unrated2)
        self.assertEqual(res_desc[6], self.footer)

        # Ascending (oldest first)
        res_asc = multipage.sort_window(self.items, 1, 1)
        self.assertEqual(res_asc[0], self.header)
        self.assertEqual(res_asc[1], self.item_low)    # 2020
        self.assertEqual(res_asc[2], self.item_mid)    # 2022
        self.assertEqual(res_asc[3], self.item_high)   # 2024
        self.assertEqual(res_asc[4], self.item_unrated1)
        self.assertEqual(res_asc[5], self.item_unrated2)
        self.assertEqual(res_asc[6], self.footer)

    def test_sort_episode_descending_and_ascending(self):
        """Episode mode sorts by episode count with zero/missing at the bottom."""
        res_desc = multipage.sort_window(self.items, 2, 0)
        self.assertEqual(res_desc[1], self.item_high)  # 24
        self.assertEqual(res_desc[2], self.item_mid)   # 12
        self.assertEqual(res_desc[3], self.item_low)   # 6
        self.assertEqual(res_desc[4], self.item_unrated1)
        self.assertEqual(res_desc[5], self.item_unrated2)

        res_asc = multipage.sort_window(self.items, 2, 1)
        self.assertEqual(res_asc[1], self.item_low)    # 6
        self.assertEqual(res_asc[2], self.item_mid)    # 12
        self.assertEqual(res_asc[3], self.item_high)   # 24
        self.assertEqual(res_asc[4], self.item_unrated1)
        self.assertEqual(res_asc[5], self.item_unrated2)


class TestPageSlicing(unittest.TestCase):
    """Verifies safe pagination slicing."""

    def test_safe_slicing(self):
        items = list(range(50))
        # Page 1
        self.assertEqual(multipage.slice_page(items, page=1, per_page=20), list(range(0, 20)))
        # Page 2
        self.assertEqual(multipage.slice_page(items, page=2, per_page=20), list(range(20, 40)))
        # Page 3 (partial)
        self.assertEqual(multipage.slice_page(items, page=3, per_page=20), list(range(40, 50)))
        # Out of bounds page
        self.assertEqual(multipage.slice_page(items, page=4, per_page=20), [])
        # Defensive clamps
        self.assertEqual(multipage.slice_page(items, page=-1, per_page=20), list(range(0, 20)))
        self.assertEqual(multipage.slice_page(items, page=1, per_page=-5), list(range(0, 20)))
        self.assertEqual(multipage.slice_page([], page=1, per_page=20), [])


class TestDatabasePeek(unittest.TestCase):
    """Verifies database.peek() non-blocking checks and non-execution on miss."""

    def setUp(self):
        self.test_db = f"{conftest.TEST_PROFILE_DIR}/peek_test.db"
        control.cacheFile = self.test_db
        database._bump_mem_generation()

    def test_peek_ram_hit(self):
        """RAM cache hit returns deserialized value immediately without calling func."""
        key = "test_ram_key"
        val = {'data': 'ram_val'}
        database._mem_set(key, repr(val), 24)

        dummy_func = MagicMock()
        result = database.peek(key, 24)
        self.assertEqual(result, val)
        dummy_func.assert_not_called()

    def test_peek_sqlite_hit(self):
        """SQLite cache hit returns value without calling func."""
        key = "test_sql_key"
        val = {'data': 'sql_val'}
        now = int(time.time())

        database._init_cache_table()
        with database.SQL(self.test_db) as cur:
            cur.execute("INSERT OR REPLACE INTO cache (key, value, date) VALUES (?, ?, ?)", (key, repr(val), now))
            cur.connection.commit()

        dummy_func = MagicMock()
        result = database.peek(key, 24)
        self.assertEqual(result, val)
        dummy_func.assert_not_called()

    def test_peek_miss_does_not_execute_function(self):
        """Cache miss returns None without executing the provided callable."""
        dummy_func = MagicMock()
        result = database.peek(dummy_func, 24, "arg1", key="custom_suffix")
        self.assertIsNone(result)
        dummy_func.assert_not_called()

    def test_peek_expired_miss(self):
        """Expired SQLite entry returns None without calling function."""
        key = "test_expired_key"
        val = {'data': 'expired'}
        expired_time = int(time.time()) - (48 * 3600)  # 48 hours ago

        database._init_cache_table()
        with database.SQL(self.test_db) as cur:
            cur.execute("INSERT OR REPLACE INTO cache (key, value, date) VALUES (?, ?, ?)", (key, repr(val), expired_time))
            cur.connection.commit()

        dummy_func = MagicMock()
        result = database.peek(key, 24)
        self.assertIsNone(result)
        dummy_func.assert_not_called()


class TestDatabaseMultipageJobs(unittest.TestCase):
    """Verifies multipage_jobs table queue operations (enqueue, dequeue, progress, done, failed, prune)."""

    def setUp(self):
        self.test_db = f"{conftest.TEST_PROFILE_DIR}/multipage_jobs_test.db"
        control.cacheFile = self.test_db

    def test_enqueue_and_dequeue_lifecycle(self):
        """Enqueue atomic creation, priority ordering, and atomic dequeue transition to 'running'."""
        job_id = database.enqueue_multipage_job(
            provider='anilist',
            browser_method='get_airing',
            url_path='airing',
            request_params={'page': 2, 'sort': 'POPULARITY_DESC'},
            target_page=10,
            priority=5
        )
        self.assertIsNotNone(job_id)
        self.assertIsInstance(job_id, str)

        # Dequeue
        job = database.dequeue_multipage_job(provider='anilist')
        self.assertIsNotNone(job)
        self.assertEqual(str(job['id']), job_id)
        self.assertEqual(job['status'], 'running')
        self.assertEqual(job['provider'], 'anilist')
        self.assertEqual(job['target_page'], 10)

        # Queue is now empty for pending jobs
        empty_job = database.dequeue_multipage_job(provider='anilist')
        self.assertIsNone(empty_job)

    def test_enqueue_idempotent_deduplication(self):
        """Re-enqueueing existing pending/running job updates target_page and returns existing id."""
        job_id1 = database.enqueue_multipage_job('mal', 'get_top', 'top', {'mode': 'tv'}, target_page=5)
        job_id2 = database.enqueue_multipage_job('mal', 'get_top', 'top', {'mode': 'tv'}, target_page=15)
        self.assertEqual(job_id1, job_id2)

        job = database.dequeue_multipage_job('mal')
        self.assertEqual(job['target_page'], 15)

    def test_update_progress_and_mark_done(self):
        """Progress updates current_page and mark_done sets completed status."""
        job_id = database.enqueue_multipage_job('anilist', 'popular', 'popular', {}, target_page=10)
        job = database.dequeue_multipage_job()

        # Update progress
        ok = database.update_multipage_job_progress(job['id'], current_page=4)
        self.assertTrue(ok)

        # Mark done
        ok_done = database.mark_multipage_job_done(job['id'])
        self.assertTrue(ok_done)

        with database.SQL(self.test_db) as cur:
            cur.execute("SELECT current_page, status FROM multipage_jobs WHERE id=?", (job['id'],))
            row = cur.fetchone()
            self.assertEqual(row['current_page'], 4)
            self.assertEqual(row['status'], 'completed')

    def test_mark_failed_retry_and_exhaustion(self):
        """Marking failed increments error count; retries until max_retries then transitions to 'failed'."""
        job_id = database.enqueue_multipage_job('anilist', 'fail_test', 'fail', {})
        job = database.dequeue_multipage_job()

        # 1st failure -> resets to pending for retry
        database.mark_multipage_job_failed(job['id'], error="Timeout 1", max_retries=3)
        job_retry1 = database.dequeue_multipage_job()
        self.assertIsNotNone(job_retry1)
        self.assertEqual(job_retry1['error_count'], 1)

        # 2nd failure -> resets to pending
        database.mark_multipage_job_failed(job['id'], error="Timeout 2", max_retries=3)
        job_retry2 = database.dequeue_multipage_job()
        self.assertIsNotNone(job_retry2)
        self.assertEqual(job_retry2['error_count'], 2)

        # 3rd failure -> max_retries reached, transitions to 'failed'
        database.mark_multipage_job_failed(job['id'], error="Fatal Error", max_retries=3)
        job_dead = database.dequeue_multipage_job()
        self.assertIsNone(job_dead)

        with database.SQL(self.test_db) as cur:
            cur.execute("SELECT status, last_error FROM multipage_jobs WHERE id=?", (job['id'],))
            row = cur.fetchone()
            self.assertEqual(row['status'], 'failed')
            self.assertEqual(row['last_error'], 'Fatal Error')

    def test_prune_stale_jobs(self):
        """Stale running jobs are reset to pending; old completed/failed jobs are purged."""
        now = int(time.time())
        database._init_multipage_jobs_table()

        with database.SQL(self.test_db) as cur:
            # 1. Stale running job (updated 600 seconds ago)
            cur.execute(
                "INSERT INTO multipage_jobs (job_key, provider, status, updated_at, created_at) VALUES (?, ?, 'running', ?, ?)",
                ('stale_running', 'anilist', now - 600, now - 600)
            )
            # 2. Old completed job (updated 100,000 seconds ago)
            cur.execute(
                "INSERT INTO multipage_jobs (job_key, provider, status, updated_at, created_at) VALUES (?, ?, 'completed', ?, ?)",
                ('old_completed', 'mal', now - 100000, now - 100000)
            )
            # 3. Fresh completed job (updated 100 seconds ago)
            cur.execute(
                "INSERT INTO multipage_jobs (job_key, provider, status, updated_at, created_at) VALUES (?, ?, 'completed', ?, ?)",
                ('fresh_completed', 'mal', now - 100, now - 100)
            )
            cur.connection.commit()

        # Prune with 300s running timeout, 86400s max age
        affected = database.prune_stale_multipage_jobs(max_age_seconds=86400, running_timeout=300)
        self.assertEqual(affected, 2)  # 1 reset + 1 deleted

        # Stale running job should now be pending and dequeuable
        dequeued = database.dequeue_multipage_job(provider='anilist')
        self.assertIsNotNone(dequeued)
        self.assertEqual(dequeued['job_key'], 'stale_running')

        with database.SQL(self.test_db) as cur:
            cur.execute("SELECT job_key FROM multipage_jobs")
            keys = [r['job_key'] for r in cur.fetchall()]
            self.assertIn('stale_running', keys)
            self.assertIn('fresh_completed', keys)
            self.assertNotIn('old_completed', keys)


class TestMultipageWorkerLifecycle(unittest.TestCase):
    """Verifies MultipageWorker thread lifecycle, run loop, and responsive shutdown."""

    def setUp(self):
        self.test_db = f"{conftest.TEST_PROFILE_DIR}/worker_lifecycle_test.db"
        control.cacheFile = self.test_db
        database._init_multipage_jobs_table()

    def test_worker_thread_initialization_and_daemon(self):
        """Worker thread initializes as daemon with expected thread name."""
        monitor = conftest.MockMonitor()
        worker = MultipageWorker(monitor=monitor)
        self.assertEqual(worker.name, "Otaku-MultipageWorker")
        self.assertTrue(worker.daemon)
        self.assertIs(worker.monitor, monitor)

    def test_worker_run_and_shutdown_on_abort_requested(self):
        """Worker runs and shuts down cleanly and responsively when monitor.requestAbort() is called."""
        monitor = conftest.MockMonitor()
        worker = MultipageWorker(monitor=monitor)
        worker.start()
        self.assertTrue(worker.is_alive())

        monitor.requestAbort()
        worker.join(timeout=2.0)
        self.assertFalse(worker.is_alive())

    def test_worker_shutdown_on_stop_event(self):
        """Worker shuts down cleanly when stop() is called."""
        monitor = conftest.MockMonitor()
        worker = MultipageWorker(monitor=monitor)
        worker.start()
        self.assertTrue(worker.is_alive())

        worker.stop()
        worker.join(timeout=2.0)
        self.assertFalse(worker.is_alive())

    def test_worker_stop_responsiveness_while_idle(self):
        """worker.stop() while in idle loop unblocks and joins responsively (<0.2s)."""
        monitor = RealisticMonitor()
        worker = MultipageWorker(monitor=monitor)
        with patch.object(database, 'dequeue_multipage_job', return_value=None):
            worker.start()
            time.sleep(0.04)
            t_stop = time.time()
            worker.stop()
            worker.join(timeout=2.0)
            elapsed = time.time() - t_stop
            self.assertFalse(worker.is_alive())
            self.assertLess(elapsed, 0.2, f"worker.stop() idle exit took too long: {elapsed:.3f}s")

    def test_worker_stop_responsiveness_mid_pacing(self):
        """worker.stop() mid-pacing unblocks and exits responsively (<0.2s)."""
        monitor = RealisticMonitor()
        worker = MultipageWorker(monitor=monitor)
        mock_browser = MagicMock()

        job = {
            'id': 105,
            'job_id': 105,
            'provider': 'anilist',
            'browser_method': 'get_pages',
            'url_path': 'test_path',
            'request_params': '{}',
            'current_page': 2,
            'target_page': 5
        }

        with patch('resources.lib.AniListBrowser.AniListBrowser', return_value=mock_browser), \
             patch.object(database, 'update_multipage_job_progress'), \
             patch.object(database, 'mark_multipage_job_done'), \
             patch.object(worker, '_check_and_refresh_container'):
            t = threading.Thread(target=worker._process_job, args=(job,), daemon=True)
            t.start()
            time.sleep(0.04)  # Enters pacing wait
            t_stop = time.time()
            worker.stop()
            t.join(timeout=2.0)
            elapsed = time.time() - t_stop
            self.assertFalse(t.is_alive())
            self.assertLess(elapsed, 0.2, f"worker.stop() mid-pacing exit took too long: {elapsed:.3f}s")

    def test_worker_processes_job_and_updates_progress(self):
        """Worker dequeues pending job, invokes browser method, updates progress, and marks completed."""
        monitor = conftest.MockMonitor()
        worker = MultipageWorker(monitor=monitor)

        job_id = database.enqueue_multipage_job(
            provider='anilist',
            browser_method='get_test_pages',
            url_path='test_url',
            request_params={'format': 'TV'},
            target_page=4,
            current_page=2
        )
        self.assertIsNotNone(job_id)

        mock_browser = MagicMock()
        mock_fetch = MagicMock()
        mock_browser.get_test_pages = mock_fetch

        with patch('resources.lib.AniListBrowser.AniListBrowser', return_value=mock_browser):
            job = database.dequeue_multipage_job()
            self.assertIsNotNone(job)
            worker._process_job(job)

        # Verify pages 2, 3, 4 were fetched
        self.assertEqual(mock_fetch.call_count, 3)
        mock_fetch.assert_any_call(format='TV', page=2)
        mock_fetch.assert_any_call(format='TV', page=3)
        mock_fetch.assert_any_call(format='TV', page=4)

        # Verify DB status
        with database.SQL(self.test_db) as cur:
            cur.execute("SELECT status, current_page FROM multipage_jobs WHERE id=?", (int(job_id),))
            row = cur.fetchone()
            self.assertEqual(row['status'], 'completed')
            self.assertEqual(row['current_page'], 4)


class TestMultipageWorkerPacing(unittest.TestCase):
    """Verifies API rate pacing (>=1.0s AniList, >=1.1s Jikan/MAL) using mocked monitor."""

    def test_pacing_constants_and_accessor(self):
        """Pacing values meet or exceed requirements."""
        self.assertGreaterEqual(MultipageWorker.PACING_ANILIST, 1.0)
        self.assertGreaterEqual(MultipageWorker.PACING_MAL, 1.1)

        self.assertGreaterEqual(MultipageWorker.get_pacing('anilist'), 1.0)
        self.assertGreaterEqual(MultipageWorker.get_pacing('AniList'), 1.0)
        self.assertGreaterEqual(MultipageWorker.get_pacing('mal'), 1.1)
        self.assertGreaterEqual(MultipageWorker.get_pacing('jikan'), 1.1)
        self.assertGreaterEqual(MultipageWorker.get_pacing('MyAnimeList'), 1.1)

    def test_anilist_rate_pacing_invocation(self):
        """AniList pre-cache job invokes waitForAbort with pacing >= 1.0 between pages."""
        monitor = MagicMock()
        monitor.abortRequested.return_value = False
        monitor.waitForAbort.return_value = False

        worker = MultipageWorker(monitor=monitor)
        mock_browser = MagicMock()

        job = {
            'id': 1,
            'job_id': 1,
            'provider': 'anilist',
            'browser_method': 'test_method',
            'url_path': 'test_path',
            'request_params': '{}',
            'current_page': 2,
            'target_page': 3
        }

        with patch('resources.lib.AniListBrowser.AniListBrowser', return_value=mock_browser), \
             patch.object(database, 'update_multipage_job_progress'), \
             patch.object(database, 'mark_multipage_job_done'), \
             patch.object(worker, '_check_and_refresh_container'):
            worker._process_job(job)

        pacing_calls = [call[0][0] for call in monitor.waitForAbort.call_args_list]
        self.assertTrue(any(p >= 1.0 for p in pacing_calls), f"Expected pacing >= 1.0, got: {pacing_calls}")

    def test_jikan_mal_rate_pacing_invocation(self):
        """Jikan/MAL pre-cache job invokes waitForAbort with pacing >= 1.1 between pages."""
        monitor = MagicMock()
        monitor.abortRequested.return_value = False
        monitor.waitForAbort.return_value = False

        worker = MultipageWorker(monitor=monitor)
        mock_browser = MagicMock()

        job = {
            'id': 2,
            'job_id': 2,
            'provider': 'jikan',
            'browser_method': 'test_method',
            'url_path': 'test_path',
            'request_params': '{}',
            'current_page': 2,
            'target_page': 3
        }

        with patch('resources.lib.MalBrowser.MalBrowser', return_value=mock_browser), \
             patch.object(database, 'update_multipage_job_progress'), \
             patch.object(database, 'mark_multipage_job_done'), \
             patch.object(worker, '_check_and_refresh_container'):
            worker._process_job(job)

        pacing_calls = [call[0][0] for call in monitor.waitForAbort.call_args_list]
        self.assertTrue(any(p >= 1.1 for p in pacing_calls), f"Expected pacing >= 1.1, got: {pacing_calls}")


class TestMultipageWorkerPausing(unittest.TestCase):
    """Verifies worker pauses when media playback is active, display in standby, or screensaver active."""

    def setUp(self):
        self.worker = MultipageWorker()

    def test_should_pause_when_playback_active(self):
        """Worker pauses if xbmc.Player().isPlaying() returns True."""
        with patch('xbmc.Player.isPlaying', return_value=True), \
             patch.object(control, 'is_device_in_standby', return_value=False), \
             patch('xbmc.getCondVisibility', return_value=False):
            self.assertTrue(self.worker._should_pause())

    def test_should_pause_when_device_in_standby(self):
        """Worker pauses if control.is_device_in_standby() returns True."""
        with patch('xbmc.Player.isPlaying', return_value=False), \
             patch.object(control, 'is_device_in_standby', return_value=True), \
             patch('xbmc.getCondVisibility', return_value=False):
            self.assertTrue(self.worker._should_pause())

    def test_should_pause_when_screensaver_active(self):
        """Worker pauses if System.ScreenSaverActive is True."""
        with patch('xbmc.Player.isPlaying', return_value=False), \
             patch.object(control, 'is_device_in_standby', return_value=False), \
             patch('xbmc.getCondVisibility', side_effect=lambda cond: cond == 'System.ScreenSaverActive'):
            self.assertTrue(self.worker._should_pause())

    def test_should_not_pause_when_all_idle(self):
        """Worker does not pause when playback, standby, and screensaver are all inactive."""
        with patch('xbmc.Player.isPlaying', return_value=False), \
             patch.object(control, 'is_device_in_standby', return_value=False), \
             patch('xbmc.getCondVisibility', return_value=False):
            self.assertFalse(self.worker._should_pause())

    def test_run_loop_waits_when_paused(self):
        """Run loop calls waitForAbort(2.0) and avoids dequeuing jobs while paused."""
        monitor = MagicMock()
        monitor.abortRequested.side_effect = [False, False, True]
        monitor.waitForAbort.return_value = False

        worker = MultipageWorker(monitor=monitor)
        with patch.object(worker, '_should_pause', return_value=True), \
             patch.object(database, 'dequeue_multipage_job') as mock_dequeue:
            worker.run()
            mock_dequeue.assert_not_called()
            monitor.waitForAbort.assert_called_with(2.0)


class TestContainerRefreshGating(unittest.TestCase):
    """Verifies Container.Refresh triggered only when viewing page 1 in Mode 1, and idempotency prevents loops."""

    def setUp(self):
        self.worker = MultipageWorker()
        self.job = {
            'id': 42,
            'job_id': 42,
            'url_path': 'plugin://plugin.video.otaku.rpdev/airing'
        }
        control.homeWindow.setProperty('otaku_mp_refreshed_42', '')

    def test_refresh_triggered_on_page_1_mode_1(self):
        """Container.Refresh triggered when viewing page 1 in Mode 1 (All Pre-Cached Items)."""
        with patch.object(control, 'getInt', return_value=1), \
             patch('xbmc.getInfoLabel', return_value='plugin://plugin.video.otaku.rpdev/airing?page=1'), \
             patch.object(control, 'refresh') as mock_refresh:
            self.worker._check_and_refresh_container(self.job)
            mock_refresh.assert_called_once()
            self.assertEqual(control.homeWindow.getProperty('otaku_mp_refreshed_42'), '1')

    def test_idempotency_token_prevents_infinite_refresh_loop(self):
        """Second call with same job does not re-trigger Container.Refresh."""
        control.homeWindow.setProperty('otaku_mp_refreshed_42', '1')

        with patch.object(control, 'getInt', return_value=1), \
             patch('xbmc.getInfoLabel', return_value='plugin://plugin.video.otaku.rpdev/airing?page=1'), \
             patch.object(control, 'refresh') as mock_refresh:
            self.worker._check_and_refresh_container(self.job)
            mock_refresh.assert_not_called()

    def test_no_refresh_in_mode_0(self):
        """Mode 0 (Paged) does not trigger Container.Refresh."""
        with patch.object(control, 'getInt', return_value=0), \
             patch('xbmc.getInfoLabel', return_value='plugin://plugin.video.otaku.rpdev/airing?page=1'), \
             patch.object(control, 'refresh') as mock_refresh:
            self.worker._check_and_refresh_container(self.job)
            mock_refresh.assert_not_called()

    def test_no_refresh_when_viewing_page_2(self):
        """No refresh if user is currently viewing page 2."""
        with patch.object(control, 'getInt', return_value=1), \
             patch('xbmc.getInfoLabel', return_value='plugin://plugin.video.otaku.rpdev/airing?page=2'), \
             patch.object(control, 'refresh') as mock_refresh:
            self.worker._check_and_refresh_container(self.job)
            mock_refresh.assert_not_called()

    def test_no_refresh_when_viewing_different_url(self):
        """No refresh if user navigated to a different list."""
        with patch.object(control, 'getInt', return_value=1), \
             patch('xbmc.getInfoLabel', return_value='plugin://plugin.video.otaku.rpdev/popular?page=1'), \
             patch.object(control, 'refresh') as mock_refresh:
            self.worker._check_and_refresh_container(self.job)
            mock_refresh.assert_not_called()

    def test_folder_matching_variations(self):
        """_is_folder_match handles paths with or without query params and trailing slashes."""
        self.assertTrue(MultipageWorker._is_folder_match('plugin://plugin.video.otaku.rpdev/airing?page=1', 'plugin://plugin.video.otaku.rpdev/airing'))
        self.assertTrue(MultipageWorker._is_folder_match('plugin://plugin.video.otaku.rpdev/airing', 'plugin://plugin.video.otaku.rpdev/airing'))
        self.assertTrue(MultipageWorker._is_folder_match('airing', 'airing'))
        self.assertTrue(MultipageWorker._is_folder_match('plugin://plugin.video.otaku.rpdev/airing?page=1', 'airing'))
        self.assertFalse(MultipageWorker._is_folder_match('plugin://plugin.video.otaku.rpdev/popular?page=1', 'airing'))
        self.assertFalse(MultipageWorker._is_folder_match('', 'airing'))
        self.assertFalse(MultipageWorker._is_folder_match('airing', ''))

    def test_no_refresh_when_addon_not_visible(self):
        """No refresh if add-on window is in background or hidden (control.is_addon_visible() is False)."""
        with patch.object(control, 'getInt', return_value=1), \
             patch('xbmc.getInfoLabel', return_value='plugin://plugin.video.otaku.rpdev/airing?page=1'), \
             patch.object(control, 'is_addon_visible', return_value=False) as mock_visible, \
             patch.object(control, 'refresh') as mock_refresh:
            self.worker._check_and_refresh_container(self.job)
            self.assertTrue(mock_visible.called)
            mock_refresh.assert_not_called()
            self.assertEqual(control.homeWindow.getProperty('otaku_mp_refreshed_42'), '')

    def test_refresh_when_addon_visible(self):
        """Refresh triggers when add-on is visible (control.is_addon_visible() is True)."""
        with patch.object(control, 'getInt', return_value=1), \
             patch('xbmc.getInfoLabel', return_value='plugin://plugin.video.otaku.rpdev/airing?page=1'), \
             patch.object(control, 'is_addon_visible', return_value=True) as mock_visible, \
             patch.object(control, 'refresh') as mock_refresh:
            self.worker._check_and_refresh_container(self.job)
            self.assertTrue(mock_visible.called)
            mock_refresh.assert_called_once()
            self.assertEqual(control.homeWindow.getProperty('otaku_mp_refreshed_42'), '1')

    def test_folder_matching_disparate_query_parameters(self):
        """_is_folder_match distinguishes routes with conflicting query parameters on same path."""
        # Conflicting queries on same route
        self.assertFalse(MultipageWorker._is_folder_match(
            'plugin://plugin.video.otaku.rpdev/airing?season=fall&year=2025&page=1',
            'plugin://plugin.video.otaku.rpdev/airing?season=spring&year=2026'
        ))
        self.assertFalse(MultipageWorker._is_folder_match(
            'plugin://plugin.video.otaku.rpdev/airing?season=fall&page=1',
            'plugin://plugin.video.otaku.rpdev/airing?season=spring'
        ))
        # Matching queries on same route (with page stripped)
        self.assertTrue(MultipageWorker._is_folder_match(
            'plugin://plugin.video.otaku.rpdev/airing?season=fall&year=2025&page=1',
            'plugin://plugin.video.otaku.rpdev/airing?season=fall&year=2025'
        ))
        # Ephemeral in-list text filter should still match base pre-cache job
        self.assertTrue(MultipageWorker._is_folder_match(
            'plugin://plugin.video.otaku.rpdev/airing?page=1&filter_text=shingeki',
            'plugin://plugin.video.otaku.rpdev/airing'
        ))
        # Different base routes with same query must not match
        self.assertFalse(MultipageWorker._is_folder_match(
            'plugin://plugin.video.otaku.rpdev/popular?season=fall&page=1',
            'plugin://plugin.video.otaku.rpdev/airing?season=fall'
        ))


class TestMultipageInvariants(unittest.TestCase):
    """Verifies architectural invariants: 64KB window property ceiling and graceful error handling."""

    def test_payload_exceeding_64kb_bypasses_window_property(self):
        """Large payloads exceeding 64KB are rejected by control.homeWindow.setProperty, ensuring storage in SQLite cache.db."""
        key = "otaku_test_large_payload"
        large_val = "x" * 70000
        control.homeWindow.setProperty(key, '')
        control.homeWindow.setProperty(key, large_val)
        self.assertEqual(control.homeWindow.getProperty(key), '')

        # Also test global prop accessor
        control.setGlobalProp(key, large_val)
        self.assertEqual(control.homeWindow.getProperty(key), '')

    def test_worker_handles_job_failure_gracefully(self):
        """Worker handles exceptions during page fetching without crashing, marking job failed."""
        test_db = f"{conftest.TEST_PROFILE_DIR}/worker_failure_test.db"
        control.cacheFile = test_db
        database._init_multipage_jobs_table()

        job_id = database.enqueue_multipage_job(
            provider='anilist',
            browser_method='crashing_method',
            url_path='test_fail',
            request_params={},
            target_page=3,
            current_page=2
        )

        mock_browser = MagicMock()
        mock_browser.crashing_method.side_effect = RuntimeError("API Connection Timeout")

        worker = MultipageWorker(monitor=conftest.MockMonitor())
        with patch('resources.lib.AniListBrowser.AniListBrowser', return_value=mock_browser):
            job = database.dequeue_multipage_job()
            worker._process_job(job)

        with database.SQL(test_db) as cur:
            cur.execute("SELECT status, last_error FROM multipage_jobs WHERE id=?", (int(job_id),))
            row = cur.fetchone()
            self.assertIn(row['status'], ('pending', 'failed'))
            self.assertIn("API Connection Timeout", row['last_error'])


class TestBrowserMultipageIntegration(unittest.TestCase):
    """Verifies BrowserBase.process_multipage_view and Main multipage routes."""

    def setUp(self):
        conftest.mock_xbmcplugin.reset()

    def test_process_multipage_view_paged_mode_with_filter_item(self):
        """In Mode 0 (Paged), filter action item is prepended and handle_paging is appended."""
        from resources.lib.ui.BrowserBase import BrowserBase

        browser = BrowserBase()
        browser.perpage = 2
        items = [
            {'name': 'Show 1', 'url': 'show/1', 'info': {'title': 'Show 1', 'rating': 8.0}},
            {'name': 'Show 2', 'url': 'show/2', 'info': {'title': 'Show 2', 'rating': 7.5}},
        ]

        with patch.object(control, 'getInt') as mock_int, patch.object(control, 'getBool') as mock_bool:
            mock_int.side_effect = lambda k: {
                'multipage.precache.pages': 5,
                'multipage.sort.by': 0,
                'multipage.sort.order': 0,
                'multipage.display.mode': 0,
            }.get(k, 0)
            mock_bool.side_effect = lambda k: {
                'multipage.show.filter.item': True,
                'widget.hide.nextpage': False,
            }.get(k, True)

            result = browser.process_multipage_view(items, True, 'airing?page=%d', 1)

            # First item must be [Filter List by Text...]
            self.assertTrue(multipage.is_action_item(result[0]))
            self.assertTrue('[Filter' in result[0]['name'] or '30712' in result[0]['name'])

            # Last item must be Next Page (2)
            self.assertTrue(multipage.is_next_page_item(result[-1]))
            self.assertIn('Next Page (2)', result[-1]['name'])

            # Middle items are the content
            content = [x for x in result if not multipage.is_action_item(x) and not multipage.is_next_page_item(x)]
            self.assertEqual(len(content), 2)

    def test_process_multipage_view_paged_mode_with_active_filter(self):
        """Active filter_text filters window and shows [Clear Filter] action item."""
        from resources.lib.ui.BrowserBase import BrowserBase

        browser = BrowserBase()
        browser.perpage = 5
        items = [
            {'name': 'Attack on Titan', 'url': 'show/1', 'info': {'title': 'Attack on Titan', 'plot': 'Titans attack'}},
            {'name': 'Naruto', 'url': 'show/2', 'info': {'title': 'Naruto', 'plot': 'Ninja adventure'}},
            {'name': 'Titan Junior High', 'url': 'show/3', 'info': {'title': 'Titan Junior High', 'plot': 'School parody'}},
        ]

        with patch.object(control, 'getInt') as mock_int, patch.object(control, 'getBool') as mock_bool:
            mock_int.side_effect = lambda k: 0
            mock_bool.side_effect = lambda k: True

            result = browser.process_multipage_view(items, False, 'airing?page=%d', 1, filter_text='titan')

            # First item must be [Clear Filter: ...]
            self.assertTrue(multipage.is_action_item(result[0]))
            self.assertTrue('Clear Filter' in result[0]['name'] or '30713' in result[0]['name'])

            # Only items matching 'titan' remain
            content = [x for x in result if not multipage.is_action_item(x)]
            self.assertEqual(len(content), 2)
            titles = [x['name'] for x in content]
            self.assertIn('Attack on Titan', titles)
            self.assertIn('Titan Junior High', titles)
            self.assertNotIn('Naruto', titles)

    def test_process_multipage_view_all_items_mode(self):
        """In Mode 1 (All Pre-Cached Items), cached pages are merged and displayed without paging item."""
        from resources.lib.ui.BrowserBase import BrowserBase

        browser = BrowserBase()
        browser.perpage = 2
        page1 = [
            {'name': 'Show 1', 'url': 'show/1', 'info': {'title': 'Show 1', 'rating': 7.0}},
            {'name': 'Show 2', 'url': 'show/2', 'info': {'title': 'Show 2', 'rating': 8.0}},
        ]
        page2 = [
            {'name': 'Show 3', 'url': 'show/3', 'info': {'title': 'Show 3', 'rating': 9.0}},
            {'name': 'Show 4', 'url': 'show/4', 'info': {'title': 'Show 4', 'rating': 8.5}},
        ]

        def mock_peek(p):
            if p == 2:
                return page2
            return None

        with patch.object(control, 'getInt') as mock_int, patch.object(control, 'getBool') as mock_bool:
            mock_int.side_effect = lambda k: {
                'multipage.precache.pages': 5,
                'multipage.sort.by': 3,       # Rating
                'multipage.sort.order': 0,    # Descending
                'multipage.display.mode': 1,  # All Pre-Cached Items
            }.get(k, 0)
            mock_bool.side_effect = lambda k: {
                'multipage.show.filter.item': True,
            }.get(k, True)

            result = browser.process_multipage_view(page1, True, 'airing?page=%d', 1, peek_fn=mock_peek)

            # Action item at top
            self.assertTrue(multipage.is_action_item(result[0]))

            # Content has all 4 items sorted by rating descending (9.0, 8.5, 8.0, 7.0)
            content = [x for x in result if not multipage.is_action_item(x)]
            self.assertEqual(len(content), 4)
            self.assertEqual(content[0]['name'], 'Show 3')  # 9.0
            self.assertEqual(content[1]['name'], 'Show 4')  # 8.5
            self.assertEqual(content[2]['name'], 'Show 2')  # 8.0
            self.assertEqual(content[3]['name'], 'Show 1')  # 7.0

    def test_multipage_filter_and_clear_routes(self):
        """Main MULTIPAGE_FILTER and MULTIPAGE_CLEAR_FILTER routes update container."""
        from resources.lib import Main

        with patch.object(control, 'input_dialog', return_value='Hunter') as mock_input, \
             patch.object(control, 'execute') as mock_exec:
            Main.MULTIPAGE_FILTER('', {'base_url': 'plugin://plugin.video.otaku.rpdev/airing?page=2'})
            mock_exec.assert_called_once()
            called_cmd = mock_exec.call_args[0][0]
            self.assertIn('Container.Update', called_cmd)
            self.assertIn('filter_text=Hunter', called_cmd)
            self.assertIn('page=1', called_cmd)

        with patch.object(control, 'execute') as mock_exec:
            Main.MULTIPAGE_CLEAR_FILTER('', {'base_url': 'plugin://plugin.video.otaku.rpdev/airing?page=1&filter_text=Hunter'})
            mock_exec.assert_called_once()
            called_cmd = mock_exec.call_args[0][0]
            self.assertIn('Container.Update', called_cmd)
            self.assertNotIn('filter_text', called_cmd)


class TestVideoInfoTagSetters(unittest.TestCase):
    """Verifies typed setters for VideoInfoTag in control.py."""

    def test_set_videotags_scalar_and_dict_rating(self):
        """Rating setter parses scalar floats, strings, ints, and dictionaries."""
        mock_vinfo = MagicMock()
        mock_li = MagicMock()
        mock_li.getVideoInfoTag.return_value = mock_vinfo

        # 1. Scalar float
        control.set_videotags(mock_li, {'rating': 8.75})
        mock_vinfo.setRating.assert_called_with(8.75, 0)

        # 2. Numeric string
        control.set_videotags(mock_li, {'rating': '9.2'})
        mock_vinfo.setRating.assert_called_with(9.2, 0)

        # 3. Dict with score and votes
        control.set_videotags(mock_li, {'rating': {'score': 8.5, 'votes': 1500}})
        mock_vinfo.setRating.assert_called_with(8.5, 1500)

        # 4. info['score'] fallback
        control.set_videotags(mock_li, {'score': 7.8})
        mock_vinfo.setRating.assert_called_with(7.8, 0)

    def test_set_videotags_episode_count_fallbacks(self):
        """Episode setter recognizes 'episode', 'episodes', and 'total_episodes'."""
        mock_vinfo = MagicMock()
        mock_li = MagicMock()
        mock_li.getVideoInfoTag.return_value = mock_vinfo

        # From episode
        control.set_videotags(mock_li, {'episode': 12})
        mock_vinfo.setEpisode.assert_called_with(12)

        # From episodes
        control.set_videotags(mock_li, {'episodes': 24})
        mock_vinfo.setEpisode.assert_called_with(24)

        # From total_episodes
        control.set_videotags(mock_li, {'total_episodes': 100})
        mock_vinfo.setEpisode.assert_called_with(100)


if __name__ == '__main__':
    unittest.main()
