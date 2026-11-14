# -*- coding: utf-8 -*-
"""
test_multipage_refresh_and_ceiling_adversarial.py - Milestone 2 Adversarial Stress Suite
========================================================================================
Empirical challenger stress-tests for Container.Refresh gating and 64KB window property ceiling:
1. Container.Refresh adversarial boundary matrix:
   - Full 96-cell Cartesian matrix testing mode (0 vs 1), page (1 vs 2 vs 5),
     Container.FolderPath (exact vs prefix_query vs mismatched vs empty),
     idempotency token (clean vs set), and visibility (visible vs hidden/background).
   - Verifies gating conditions, idempotency loop prevention, and checks whether
     window visibility is enforced.
2. Low-RAM 64KB window property ceiling invariant:
   - Massive datasets (100KB, 500KB, 2MB).
   - Verifies window property rejection across control.homeWindow.setProperty,
     control.setGlobalProp, and database._mem_set.
   - Verifies persistent storage, retrieval, and data fidelity in SQLite WAL cache.db.
"""

import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

# Standardized Otaku Test Bootstrap
_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_TEST_DIR, '..' if os.path.basename(_TEST_DIR) in ('unit', 'integration', 'lint') else '.'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
_TESTS_DIR = os.path.join(_REPO_ROOT, 'tests')
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import conftest  # Centralized Kodi mock harness  # noqa: F401

from resources.lib.ui import control, database
from service import MultipageWorker


class TestContainerRefreshAdversarialMatrix(unittest.TestCase):
    """Adversarial boundary matrix testing for MultipageWorker._check_and_refresh_container()."""

    def setUp(self):
        self.worker = MultipageWorker()
        self.job_id = 99
        self.job = {
            'id': self.job_id,
            'job_id': self.job_id,
            'url_path': 'plugin://plugin.video.otaku.rpdev/airing'
        }
        self.token_key = f"otaku_mp_refreshed_{self.job_id}"
        control.homeWindow.setProperty(self.token_key, '')

    def tearDown(self):
        control.homeWindow.setProperty(self.token_key, '')

    def _execute_refresh_case(self, mode, page, folder_type, token_state, is_visible):
        """Helper to run a single matrix cell and return whether control.refresh() was called."""
        if folder_type == 'exact':
            folder_path = 'plugin://plugin.video.otaku.rpdev/airing' if page == 1 else f'plugin://plugin.video.otaku.rpdev/airing?page={page}'
        elif folder_type == 'prefix_query':
            folder_path = f'plugin://plugin.video.otaku.rpdev/airing?page={page}&filter_text=foo'
        elif folder_type == 'mismatched':
            folder_path = f'plugin://plugin.video.otaku.rpdev/watchlist_anime?page={page}'
        elif folder_type == 'empty':
            folder_path = ''
        else:
            raise ValueError(f"Unknown folder_type: {folder_type}")

        token_val = '1' if token_state == 'set' else ''
        control.homeWindow.setProperty(self.token_key, token_val)

        with patch.object(control, 'getInt', return_value=mode), \
             patch('xbmc.getInfoLabel', return_value=folder_path), \
             patch.object(control, 'is_addon_visible', return_value=is_visible), \
             patch.object(control, 'refresh') as mock_refresh:
            self.worker._check_and_refresh_container(self.job)
            return mock_refresh.called

    def test_full_96_cell_boundary_matrix(self):
        """Executes full 96-cell Cartesian matrix testing all boundary permutations.
        Matrix dimensions:
        - multipage.display.mode: [0, 1] (2)
        - active_page: [1, 2, 5] (3)
        - folder_path: ['exact', 'prefix_query', 'mismatched', 'empty'] (4)
        - idempotency_token: ['clean', 'set'] (2)
        - visibility: [True, False] (2)
        Total = 2 * 3 * 4 * 2 * 2 = 96 permutations.
        """
        modes = [0, 1]
        pages = [1, 2, 5]
        folder_types = ['exact', 'prefix_query', 'mismatched', 'empty']
        tokens = ['clean', 'set']
        visibilities = [True, False]

        refresh_triggered_cases = []
        total_cases = 0

        for mode in modes:
            for page in pages:
                for ftype in folder_types:
                    for tok in tokens:
                        for vis in visibilities:
                            total_cases += 1
                            called = self._execute_refresh_case(mode, page, ftype, tok, vis)
                            if called:
                                refresh_triggered_cases.append({
                                    'mode': mode,
                                    'page': page,
                                    'folder': ftype,
                                    'token': tok,
                                    'visible': vis
                                })

        self.assertEqual(total_cases, 96, "Expected exactly 96 test permutations.")

        # Analyze triggered cases:
        # Every triggered case must have mode == 1, page == 1, matching folder, and clean token
        for c in refresh_triggered_cases:
            self.assertEqual(c['mode'], 1, f"Refresh triggered in invalid mode: {c}")
            self.assertEqual(c['page'], 1, f"Refresh triggered on invalid page: {c}")
            self.assertIn(c['folder'], ('exact', 'prefix_query'), f"Refresh triggered on mismatched folder: {c}")
            self.assertEqual(c['token'], 'clean', f"Refresh triggered when token was already set: {c}")

    def test_mode_0_strictly_blocks_refresh_across_all_subcases(self):
        """When multipage.display.mode == 0 (Paged mode), refresh is strictly blocked across all 48 permutations."""
        for page in [1, 2, 5]:
            for ftype in ['exact', 'prefix_query', 'mismatched', 'empty']:
                for tok in ['clean', 'set']:
                    for vis in [True, False]:
                        called = self._execute_refresh_case(0, page, ftype, tok, vis)
                        self.assertFalse(called, f"Mode 0 triggered refresh for: page={page}, folder={ftype}, token={tok}, vis={vis}")

    def test_pages_greater_than_1_strictly_block_refresh(self):
        """When user is on page 2 or page 5, refresh is strictly blocked regardless of mode or folder match."""
        for page in [2, 5]:
            for mode in [0, 1]:
                for ftype in ['exact', 'prefix_query', 'mismatched', 'empty']:
                    for tok in ['clean', 'set']:
                        for vis in [True, False]:
                            called = self._execute_refresh_case(mode, page, ftype, tok, vis)
                            self.assertFalse(called, f"Page {page} triggered refresh for: mode={mode}, folder={ftype}, token={tok}, vis={vis}")

    def test_mismatched_and_empty_folders_strictly_block_refresh(self):
        """When Container.FolderPath is empty or points to another route, refresh is never triggered."""
        for ftype in ['mismatched', 'empty']:
            for mode in [0, 1]:
                for page in [1, 2, 5]:
                    for tok in ['clean', 'set']:
                        for vis in [True, False]:
                            called = self._execute_refresh_case(mode, page, ftype, tok, vis)
                            self.assertFalse(called, f"Folder {ftype} triggered refresh for: mode={mode}, page={page}, token={tok}, vis={vis}")

    def test_idempotency_token_strictly_blocks_repeated_calls(self):
        """Once token 'otaku_mp_refreshed_{job_id}' is set to '1', repeated calls are strictly blocked."""
        # Clean state triggers refresh and sets token
        control.homeWindow.setProperty(self.token_key, '')
        with patch.object(control, 'getInt', return_value=1), \
             patch('xbmc.getInfoLabel', return_value='plugin://plugin.video.otaku.rpdev/airing?page=1'), \
             patch.object(control, 'is_addon_visible', return_value=True), \
             patch.object(control, 'refresh') as mock_refresh:
            self.worker._check_and_refresh_container(self.job)
            self.assertEqual(mock_refresh.call_count, 1)
            self.assertEqual(control.homeWindow.getProperty(self.token_key), '1')

            # Immediate second call with token now set
            self.worker._check_and_refresh_container(self.job)
            self.assertEqual(mock_refresh.call_count, 1, "Second call must NOT re-trigger control.refresh()")

            # 20 subsequent repeated calls are all blocked
            for _ in range(20):
                self.worker._check_and_refresh_container(self.job)
            self.assertEqual(mock_refresh.call_count, 1, "Idempotency token must block all subsequent calls")

    def test_missing_addon_visibility_gate_flaw(self):
        """EMPIRICAL FINDING: _check_and_refresh_container() fails to check control.is_addon_visible().
        When the add-on is in the background or hidden (is_addon_visible() == False),
        Container.Refresh is erroneously triggered, violating the requirement that
        refresh only occurs when the add-on is visible.
        """
        control.homeWindow.setProperty(self.token_key, '')
        with patch.object(control, 'getInt', return_value=1), \
             patch('xbmc.getInfoLabel', return_value='plugin://plugin.video.otaku.rpdev/airing?page=1'), \
             patch.object(control, 'is_addon_visible', return_value=False) as mock_visible, \
             patch.object(control, 'refresh') as mock_refresh:
            self.worker._check_and_refresh_container(self.job)

            # Assert that control.is_addon_visible was consulted and refresh was blocked:
            addon_visible_consulted = mock_visible.called
            refresh_called_while_hidden = mock_refresh.called

            self.assertTrue(addon_visible_consulted,
                            "control.is_addon_visible() must be queried in _check_and_refresh_container")
            self.assertFalse(refresh_called_while_hidden,
                             "control.refresh() must not be called when add-on is in the background or hidden")

    def test_conflicting_query_parameters_folder_match_overreach(self):
        """EMPIRICAL VERIFICATION: _is_folder_match() validates query params and rejects conflicting queries (e.g. season=fall vs season=spring).
        """
        user_viewing_fall = 'plugin://plugin.video.otaku.rpdev/airing?season=fall&year=2025&page=1'
        job_for_spring = 'plugin://plugin.video.otaku.rpdev/airing?season=spring&year=2026'

        matched = MultipageWorker._is_folder_match(user_viewing_fall, job_for_spring)
        self.assertFalse(matched, "Confirmed: _is_folder_match rejects conflicting query parameters")


class TestLowRam64KbCeilingInvariant(unittest.TestCase):
    """Adversarial stress harness for 64KB window property ceiling and SQLite WAL cache storage."""

    def setUp(self):
        self.test_db = f"{conftest.TEST_PROFILE_DIR}/test_cache_ceiling_adversarial_{time.time()}_{os.getpid()}.db"
        control.cacheFile = self.test_db
        database.close_thread_connections(self.test_db)
        for ext in ('', '-wal', '-shm'):
            p = self.test_db + ext
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        database._tables_ready.discard(f"{self.test_db}:cache")
        database._tables_ready.discard(f"{self.test_db}:cache_ix_key")
        database._tables_ready.discard(f"{self.test_db}:cache_ix_date")
        database._init_cache_table()

    def tearDown(self):
        database.close_thread_connections(self.test_db)
        for ext in ('', '-wal', '-shm'):
            p = self.test_db + ext
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass

    def test_window_property_64kb_rejection_massive_payloads(self):
        """Attempts to write 100KB, 500KB, and 2MB payloads to Kodi window properties are strictly rejected."""
        payload_sizes = [
            100 * 1024,        # 100 KB
            500 * 1024,        # 500 KB
            2 * 1024 * 1024    # 2 MB
        ]

        for size in payload_sizes:
            key = f"adversarial_test_payload_{size}"
            payload = "x" * size

            # 1. Direct window proxy setProperty
            control.homeWindow.setProperty(key, '')
            control.homeWindow.setProperty(key, payload)
            stored = control.homeWindow.getProperty(key)
            self.assertEqual(stored, '', f"Payload of size {size} bytes was NOT rejected by homeWindow.setProperty!")

            # 2. Global property helper setGlobalProp
            control.setGlobalProp(key, payload)
            stored_global = control.getGlobalProp(key)
            self.assertEqual(stored_global, '', f"Payload of size {size} bytes was NOT rejected by setGlobalProp!")

            # 3. Database internal RAM cache helper _mem_set
            database._mem_set(key, payload, hours=24)
            stored_mem = database._mem_get(key)
            self.assertIsNone(stored_mem, f"Payload of size {size} bytes was NOT rejected by database._mem_set!")

    def test_massive_multi_page_dataset_sqlite_wal_persistence_and_retrieval(self):
        """Constructs realistic multi-page anime datasets (100KB, 500KB, 2MB).
        Verifies:
        1. Window properties receive 0 bytes (zero RAM window cache pollution).
        2. Data is safely written into SQLite WAL cache.db.
        3. Data is retrieved from SQLite WAL cache.db with 100% item fidelity and equality.
        4. Non-blocking database.peek() also retrieves the cached dataset directly from SQLite.
        """
        target_sizes = [
            100 * 1024,        # 100 KB
            500 * 1024,        # 500 KB
            2 * 1024 * 1024    # 2 MB
        ]

        for target_bytes in target_sizes:
            # Construct synthetic anime items (~250 bytes per entry)
            num_items = target_bytes // 250
            dataset = [
                {
                    'id': i,
                    'title': f'Adversarial MultiPage Anime Title {i} [2026]',
                    'rating': round(7.0 + (i % 30) / 10.0, 2),
                    'episodes': 12 + (i % 24),
                    'year': 2020 + (i % 7),
                    'plot': f'Detailed plot synopsis for episode {i} testing SQLite WAL persistence under extreme payload sizes with special characters: <tag> & "quotes" and unicode: 呪術廻戦.',
                    'poster': f'https://image.example.com/anime/{i}.jpg'
                }
                for i in range(num_items)
            ]

            payload_str = repr(dataset)
            actual_size = len(payload_str.encode('utf-8'))
            self.assertGreaterEqual(actual_size, target_bytes, f"Constructed dataset {actual_size} < target {target_bytes}")

            fetch_count = [0]
            def fetch_multipage_dataset(page_size):
                fetch_count[0] += 1
                return dataset

            # Cache the massive dataset via database.get()
            cached_data = database.get(fetch_multipage_dataset, 24, target_bytes)
            self.assertEqual(fetch_count[0], 1, "fetch_multipage_dataset should have been invoked exactly once")
            self.assertEqual(len(cached_data), num_items)

            # Invariant 1: Window property RAM cache must NOT contain this payload
            hash_key = database._hash_function(fetch_multipage_dataset, (target_bytes,), {})
            full_window_key = database._get_mem_prefix() + hash_key
            window_prop_val = control.homeWindow.getProperty(full_window_key)
            self.assertEqual(window_prop_val, '', f"RAM window property must be empty for {target_bytes} payload")

            # Invariant 2: Subsequent database.get() must read directly from SQLite without invoking fetch function
            fetch_count[0] = 0
            retrieved_data = database.get(fetch_multipage_dataset, 24, target_bytes)
            self.assertEqual(fetch_count[0], 0, "Fetch function must NOT be called on SQLite cache hit")
            self.assertEqual(len(retrieved_data), num_items)
            self.assertEqual(retrieved_data, dataset, "Retrieved data from SQLite must match original dataset exactly")

            # Invariant 3: database.peek() must also retrieve the cached dataset from SQLite without network call
            peeked_data = database.peek(fetch_multipage_dataset, 24, target_bytes)
            self.assertIsNotNone(peeked_data, f"database.peek() failed to retrieve cached {target_bytes} dataset")
            self.assertEqual(len(peeked_data), num_items)
            self.assertEqual(peeked_data, dataset, "Data retrieved via database.peek() must match original exactly")

    def test_ast_literal_eval_parsing_robustness_on_2mb_dataset(self):
        """Verifies ast.literal_eval handles 2MB payload safely with sub-second parse latency."""
        num_items = (2 * 1024 * 1024) // 200 + 500
        dataset = [{'id': i, 'name': f'Anime #{i}', 'desc': 'p' * 150} for i in range(num_items)]
        raw_repr = repr(dataset)
        self.assertGreater(len(raw_repr), 2 * 1024 * 1024)

        t0 = time.perf_counter()
        import ast
        parsed = ast.literal_eval(raw_repr)
        elapsed = time.perf_counter() - t0

        self.assertEqual(len(parsed), num_items)
        self.assertLess(elapsed, 1.0, f"ast.literal_eval took too long: {elapsed:.3f}s")


if __name__ == '__main__':
    unittest.main()
