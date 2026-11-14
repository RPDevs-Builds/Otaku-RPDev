# -*- coding: utf-8 -*-
"""
test_multipage_adversarial.py - Adversarial & Concurrency Stress Test Suite
===========================================================================
Empirical challenger stress-tests for multipage_jobs SQLite queue in database.py:
1. Concurrency and race conditions (rapid concurrent workers, atomic dequeue, no double-pickup).
2. Idempotency and duplicate prevention (rapid enqueue repetition, concurrent enqueue, target expansion).
3. State machine transitions (full lifecycle, error retry exhaustion, boundary handling).
4. Self-healing stale job recovery (prune_stale_multipage_jobs cutoff boundaries, retention).
5. SQL Injection & Type Safety (table-drop attacks, null bytes, unicode, bad IDs).
"""

import concurrent.futures
import json
import os
import sys
import time
import unittest

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


class TestMultipageAdversarialHarness(unittest.TestCase):
    """Adversarial stress harness for database multipage_jobs queue."""

    def setUp(self):
        self.test_db = f"{conftest.TEST_PROFILE_DIR}/multipage_jobs_adversarial_{time.time()}_{os.getpid()}.db"
        control.cacheFile = self.test_db
        database._tables_ready.discard(f"{self.test_db}:multipage_jobs")
        database._tables_ready.discard(f"{self.test_db}:multipage_jobs_ix_status")
        database._tables_ready.discard(f"{self.test_db}:multipage_jobs_ix_updated")
        database.close_thread_connections(self.test_db)
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    def tearDown(self):
        database.close_thread_connections(self.test_db)
        for ext in ('', '-wal', '-shm'):
            p = self.test_db + ext
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass

    # ═══════════════════════════════════════════════════════════════════════════
    #  1. Concurrency and Race Conditions
    # ═══════════════════════════════════════════════════════════════════════════

    def test_concurrent_dequeue_exclusive_single_consumption(self):
        """Verify 20 concurrent worker threads competing for 10 pending jobs dequeue each job exactly once."""
        num_jobs = 10
        num_workers = 20

        # Enqueue 10 distinct jobs
        created_ids = set()
        for i in range(num_jobs):
            jid = database.enqueue_multipage_job(
                provider='test_prov',
                browser_method=f'method_{i}',
                url_path=f'path_{i}',
                request_params={'page': 2, 'idx': i},
                target_page=5,
                priority=i
            )
            self.assertIsNotNone(jid)
            created_ids.add(str(jid))

        dequeued_jobs = []
        errors = []

        def worker_task(worker_id):
            try:
                # Close any stale thread connection to ensure separate thread-local connections
                database.close_thread_connections(control.cacheFile)
                job = database.dequeue_multipage_job(provider='test_prov')
                return job
            except Exception as e:
                errors.append(f"Worker {worker_id} crashed: {e}")
                return None
            finally:
                database.close_thread_connections(control.cacheFile)

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(worker_task, w) for w in range(num_workers)]
            for f in concurrent.futures.as_completed(futures):
                res = f.result()
                if res is not None:
                    dequeued_jobs.append(res)

        self.assertEqual(errors, [], f"Worker thread exceptions occurred: {errors}")

        dequeued_ids = [str(j['id']) for j in dequeued_jobs]
        unique_dequeued_ids = set(dequeued_ids)

        # Assert zero duplicate dequeues: exactly one worker claimed each dequeued job
        self.assertEqual(len(dequeued_ids), len(unique_dequeued_ids), "Duplicate job dequeue detected! Race condition violated exclusivity.")

        # Every dequeued job must belong to created_ids
        for jid in unique_dequeued_ids:
            self.assertIn(jid, created_ids)

        # Verify database state: all dequeued jobs must have status='running'
        with database.SQL(self.test_db) as cur:
            cur.execute("SELECT id, status FROM multipage_jobs")
            rows = cur.fetchall()
            status_map = {str(r['id']): r['status'] for r in rows}

        for j in dequeued_jobs:
            self.assertEqual(status_map[str(j['id'])], 'running')
            self.assertEqual(j['status'], 'running')

        # Any un-dequeued jobs must remain 'pending'
        remaining_pending = [jid for jid in created_ids if jid not in unique_dequeued_ids]
        for jid in remaining_pending:
            self.assertEqual(status_map[jid], 'pending')

    def test_concurrent_dequeue_empty_queue_safety(self):
        """Simultaneous dequeue on empty queue by 20 workers returns None safely."""
        database._init_multipage_jobs_table()
        num_workers = 20
        results = []

        def worker_task():
            database.close_thread_connections(control.cacheFile)
            try:
                return database.dequeue_multipage_job()
            finally:
                database.close_thread_connections(control.cacheFile)

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(worker_task) for _ in range(num_workers)]
            for f in concurrent.futures.as_completed(futures):
                results.append(f.result())

        self.assertTrue(all(r is None for r in results))

    # ═══════════════════════════════════════════════════════════════════════════
    #  2. Idempotency and Duplicate Prevention
    # ═══════════════════════════════════════════════════════════════════════════

    def test_rapid_sequential_enqueue_50_times(self):
        """Enqueue the exact same job 50 times in rapid succession."""
        job_ids = []
        for i in range(50):
            jid = database.enqueue_multipage_job(
                provider='anilist',
                browser_method='get_airing',
                url_path='airing',
                request_params={'filter': 'spring', 'year': 2026},
                target_page=20
            )
            self.assertIsNotNone(jid, f"Enqueue returned None on iteration {i}")
            job_ids.append(jid)

        # All 50 calls must return the identical job_id
        first_id = job_ids[0]
        self.assertTrue(all(jid == first_id for jid in job_ids), f"Job IDs varied: {set(job_ids)}")

        # Verify only 1 row exists in the database
        with database.SQL(self.test_db) as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM multipage_jobs")
            row = cur.fetchone()
            self.assertEqual(row['cnt'], 1, "Duplicate rows created in multipage_jobs!")

    def test_concurrent_enqueue_50_threads(self):
        """Simulate 50 concurrent threads enqueuing the exact same job simultaneously."""
        num_threads = 50
        results = []
        errors = []

        def enqueue_task(thread_id):
            database.close_thread_connections(control.cacheFile)
            try:
                jid = database.enqueue_multipage_job(
                    provider='anilist',
                    browser_method='get_popular',
                    url_path='popular',
                    request_params={'genre': 'Action'},
                    target_page=10
                )
                return jid
            except Exception as e:
                errors.append(f"Thread {thread_id} crashed: {e}")
                return None
            finally:
                database.close_thread_connections(control.cacheFile)

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(enqueue_task, t) for t in range(num_threads)]
            for f in concurrent.futures.as_completed(futures):
                results.append(f.result())

        self.assertEqual(errors, [], f"Thread crashed during concurrent enqueue: {errors}")

        # In database, exactly 1 row must exist
        with database.SQL(self.test_db) as cur:
            cur.execute("SELECT id, job_key FROM multipage_jobs")
            rows = cur.fetchall()
            self.assertEqual(len(rows), 1, f"Expected exactly 1 row, found {len(rows)}")
            canonical_id = str(rows[0]['id'])

        # Check return values: any non-None returns must match canonical_id
        valid_ids = [r for r in results if r is not None]
        self.assertGreater(len(valid_ids), 0, "No thread successfully returned a job ID")
        for jid in valid_ids:
            self.assertEqual(jid, canonical_id)

    def test_target_page_expansion_idempotency(self):
        """Re-enqueueing with larger target_page expands target; smaller does not regress."""
        jid1 = database.enqueue_multipage_job('mal', 'top', 'top', {'type': 'anime'}, target_page=5)
        # Expand target to 15
        jid2 = database.enqueue_multipage_job('mal', 'top', 'top', {'type': 'anime'}, target_page=15)
        self.assertEqual(jid1, jid2)

        with database.SQL(self.test_db) as cur:
            cur.execute("SELECT target_page FROM multipage_jobs WHERE id=?", (int(jid1),))
            self.assertEqual(cur.fetchone()['target_page'], 15)

        # Attempt to shrink target to 10 - must NOT regress
        jid3 = database.enqueue_multipage_job('mal', 'top', 'top', {'type': 'anime'}, target_page=10)
        self.assertEqual(jid1, jid3)

        with database.SQL(self.test_db) as cur:
            cur.execute("SELECT target_page FROM multipage_jobs WHERE id=?", (int(jid1),))
            self.assertEqual(cur.fetchone()['target_page'], 15)

    def test_re_enqueue_completed_and_failed_jobs(self):
        """Re-enqueuing completed job with higher target_page or failed job resets status to pending."""
        jid = database.enqueue_multipage_job('anilist', 'm', 'u', {}, target_page=5)
        job = database.dequeue_multipage_job()
        database.mark_multipage_job_done(job['id'])

        # Completed job with higher target_page resets to pending
        jid_new = database.enqueue_multipage_job('anilist', 'm', 'u', {}, target_page=10)
        self.assertEqual(jid, jid_new)
        re_job = database.dequeue_multipage_job()
        self.assertIsNotNone(re_job)
        self.assertEqual(re_job['target_page'], 10)

        # Fail job up to exhaustion
        database.mark_multipage_job_failed(re_job['id'], error="Test Failure", max_retries=1)
        with database.SQL(self.test_db) as cur:
            cur.execute("SELECT status, error_count, last_error FROM multipage_jobs WHERE id=?", (re_job['id'],))
            row = cur.fetchone()
            self.assertEqual(row['status'], 'failed')
            self.assertEqual(row['error_count'], 1)
            self.assertEqual(row['last_error'], 'Test Failure')

        # Re-enqueuing failed job resets error_count, last_error, and status to pending
        jid_retry = database.enqueue_multipage_job('anilist', 'm', 'u', {}, target_page=10)
        self.assertEqual(jid, jid_retry)
        with database.SQL(self.test_db) as cur:
            cur.execute("SELECT status, error_count, last_error FROM multipage_jobs WHERE id=?", (jid_retry,))
            row = cur.fetchone()
            self.assertEqual(row['status'], 'pending')
            self.assertEqual(row['error_count'], 0)
            self.assertIsNone(row['last_error'])

    # ═══════════════════════════════════════════════════════════════════════════
    #  3. State Machine Transitions
    # ═══════════════════════════════════════════════════════════════════════════

    def test_full_lifecycle_pending_running_progress_completed(self):
        """Verify full lifecycle from pending -> running -> progress updates -> completed."""
        t0 = int(time.time())
        jid = database.enqueue_multipage_job('simkl', 'anime_genres', 'genres', {'genre': 'action'}, target_page=8)

        # Verify initial pending state
        with database.SQL(self.test_db) as cur:
            cur.execute("SELECT * FROM multipage_jobs WHERE id=?", (int(jid),))
            j0 = cur.fetchone()
            self.assertEqual(j0['status'], 'pending')
            self.assertEqual(j0['current_page'], 2)
            self.assertEqual(j0['target_page'], 8)
            self.assertEqual(j0['error_count'], 0)

        # Transition to running
        job = database.dequeue_multipage_job('simkl')
        self.assertIsNotNone(job)
        self.assertEqual(job['status'], 'running')
        self.assertGreaterEqual(job['updated_at'], t0)

        # Step through progress updates
        for page in (3, 4, 5, 6, 7, 8):
            ok = database.update_multipage_job_progress(job['id'], current_page=page)
            self.assertTrue(ok)
            with database.SQL(self.test_db) as cur:
                cur.execute("SELECT current_page FROM multipage_jobs WHERE id=?", (job['id'],))
                self.assertEqual(cur.fetchone()['current_page'], page)

        # Transition to completed
        ok_done = database.mark_multipage_job_done(job['id'])
        self.assertTrue(ok_done)

        with database.SQL(self.test_db) as cur:
            cur.execute("SELECT status, current_page FROM multipage_jobs WHERE id=?", (job['id'],))
            final_job = cur.fetchone()
            self.assertEqual(final_job['status'], 'completed')
            self.assertEqual(final_job['current_page'], 8)

        # Dequeue must return None now
        self.assertIsNone(database.dequeue_multipage_job('simkl'))

    def test_failure_retry_progression_and_exhaustion(self):
        """Verify error_count increments monotonically, retries up to max_retries, and transitions to failed."""
        jid = database.enqueue_multipage_job('kitsu', 'trending', 'trending', {})
        max_retries = 4

        for attempt in range(1, max_retries):
            job = database.dequeue_multipage_job('kitsu')
            self.assertIsNotNone(job, f"Failed to dequeue on retry attempt {attempt}")
            self.assertEqual(job['status'], 'running')

            err_msg = f"HTTP 504 Gateway Timeout (Attempt {attempt})"
            ok = database.mark_multipage_job_failed(job['id'], error=err_msg, max_retries=max_retries)
            self.assertTrue(ok)

            with database.SQL(self.test_db) as cur:
                cur.execute("SELECT status, error_count, last_error FROM multipage_jobs WHERE id=?", (job['id'],))
                row = cur.fetchone()
                self.assertEqual(row['status'], 'pending', f"Job should be pending on attempt {attempt}")
                self.assertEqual(row['error_count'], attempt)
                self.assertEqual(row['last_error'], err_msg)

        # Final failure reaching max_retries
        job = database.dequeue_multipage_job('kitsu')
        self.assertIsNotNone(job)
        fatal_msg = f"HTTP 404 Fatal Final Error"
        ok = database.mark_multipage_job_failed(job['id'], error=fatal_msg, max_retries=max_retries)
        self.assertTrue(ok)

        with database.SQL(self.test_db) as cur:
            cur.execute("SELECT status, error_count, last_error FROM multipage_jobs WHERE id=?", (job['id'],))
            row = cur.fetchone()
            self.assertEqual(row['status'], 'failed')
            self.assertEqual(row['error_count'], max_retries)
            self.assertEqual(row['last_error'], fatal_msg)

        # Queue is exhausted: dequeue returns None
        self.assertIsNone(database.dequeue_multipage_job('kitsu'))

    def test_nonexistent_job_operations_fail_gracefully(self):
        """Operations on non-existent job ID return False/None without crashing."""
        self.assertFalse(database.update_multipage_job_progress(999999, 5))
        self.assertFalse(database.mark_multipage_job_done(999999))
        self.assertFalse(database.mark_multipage_job_failed(999999, "Fake Error"))

    # ═══════════════════════════════════════════════════════════════════════════
    #  4. Self-Healing Stale Job Recovery
    # ═══════════════════════════════════════════════════════════════════════════

    def test_prune_stale_multipage_jobs_comprehensive_matrix(self):
        """Verify boundary precision for prune_stale_multipage_jobs:
        - Stale running jobs (>300s) -> reset to pending
        - Active running jobs (<=300s) -> untouched
        - Ancient completed/failed (>86400s) -> purged
        - Recent completed/failed (<=86400s) -> preserved
        - Pending jobs (>86400s) -> preserved (never pruned)
        """
        now = int(time.time())
        database._init_multipage_jobs_table()

        records = [
            # key, status, updated_at, expect_status_after, expect_exists_after
            ('stale_running_301', 'running', now - 301, 'pending', True),
            ('active_running_299', 'running', now - 299, 'running', True),
            ('active_running_now', 'running', now, 'running', True),
            ('ancient_completed_86401', 'completed', now - 86401, None, False),
            ('recent_completed_86399', 'completed', now - 86399, 'completed', True),
            ('ancient_failed_90000', 'failed', now - 90000, None, False),
            ('recent_failed_1000', 'failed', now - 1000, 'failed', True),
            ('ancient_pending_100000', 'pending', now - 100000, 'pending', True),
        ]

        with database.SQL(self.test_db) as cur:
            for key, status, updated, _, _ in records:
                cur.execute(
                    "INSERT INTO multipage_jobs (job_key, provider, status, updated_at, created_at) VALUES (?, 'p', ?, ?, ?)",
                    (key, status, updated, updated)
                )
            cur.connection.commit()

        # Run prune with standard defaults: 86400s max age, 300s running timeout
        affected = database.prune_stale_multipage_jobs(max_age_seconds=86400, running_timeout=300)

        # Expected affected: 1 reset (stale_running_301) + 2 deleted (ancient_completed_86401, ancient_failed_90000) = 3
        self.assertEqual(affected, 3, f"Expected 3 affected rows, got {affected}")

        with database.SQL(self.test_db) as cur:
            cur.execute("SELECT job_key, status FROM multipage_jobs")
            db_map = {r['job_key']: r['status'] for r in cur.fetchall()}

        for key, _, _, exp_status, exp_exists in records:
            if exp_exists:
                self.assertIn(key, db_map, f"Expected {key} to exist in DB")
                self.assertEqual(db_map[key], exp_status, f"Job {key} status mismatch: expected {exp_status}, got {db_map[key]}")
            else:
                self.assertNotIn(key, db_map, f"Expected {key} to be deleted from DB")

    # ═══════════════════════════════════════════════════════════════════════════
    #  5. SQL Injection & Type Safety
    # ═══════════════════════════════════════════════════════════════════════════

    def test_sql_injection_payloads_in_all_fields(self):
        """Verify strict parameterized query safety against SQL injection payloads across all entrypoints."""
        injection_payloads = [
            "'; DROP TABLE multipage_jobs; --",
            "1' OR '1'='1",
            "admin'--",
            "\" OR \"\"=\"",
            "'; DELETE FROM multipage_jobs WHERE 1=1; --",
            "Robert'); DROP TABLE Students;--",
            "UNION SELECT null, username, password FROM users--",
            "' OR SLEEP(5) --",
            "'; VACUUM; --",
        ]

        for idx, payload in enumerate(injection_payloads):
            # Test enqueue_multipage_job with injection in every string field
            jid = database.enqueue_multipage_job(
                provider=payload,
                browser_method=payload,
                url_path=payload,
                request_params={'filter': payload, 'nested': [payload, 123]},
                target_page=5,
                priority=1
            )
            self.assertIsNotNone(jid, f"Failed to enqueue with injection payload: {payload}")

            # Verify table still exists and structure is intact
            with database.SQL(self.test_db) as cur:
                cur.execute("SELECT count(*) as cnt FROM multipage_jobs")
                count = cur.fetchone()['cnt']
                self.assertGreater(count, 0)

            # Test dequeue with injection payload as provider
            job = database.dequeue_multipage_job(provider=payload)
            self.assertIsNotNone(job, f"Failed to dequeue with injection provider: {payload}")
            self.assertEqual(job['provider'], payload)

            # Test update progress with malicious current_page
            ok_prog = database.update_multipage_job_progress(job['id'], current_page=3)
            self.assertTrue(ok_prog)

            # Test mark failed with malicious error payload
            ok_fail = database.mark_multipage_job_failed(job['id'], error=payload)
            self.assertTrue(ok_fail)

            with database.SQL(self.test_db) as cur:
                cur.execute("SELECT last_error FROM multipage_jobs WHERE id=?", (job['id'],))
                self.assertEqual(cur.fetchone()['last_error'], payload)

            # Test mark done
            ok_done = database.mark_multipage_job_done(job['id'])
            self.assertTrue(ok_done)

        # Confirm multipage_jobs table was NOT dropped or emptied
        with database.SQL(self.test_db) as cur:
            cur.execute("SELECT count(*) as cnt FROM multipage_jobs WHERE status='completed'")
            completed_count = cur.fetchone()['cnt']
            self.assertEqual(completed_count, len(injection_payloads))

    def test_sql_injection_in_job_id_arguments(self):
        """Verify malicious string inputs passed to integer job_id parameters are safely rejected."""
        malicious_ids = [
            "1; DROP TABLE multipage_jobs; --",
            "1 OR 1=1",
            "' OR '1'='1",
            "1 UNION SELECT 1, 2, 3",
            "NaN",
            "None",
            "",
            "   ",
        ]

        for bad_id in malicious_ids:
            # All must return False gracefully without raising unhandled exceptions or corrupting tables
            self.assertFalse(database.update_multipage_job_progress(bad_id, 2))
            self.assertFalse(database.mark_multipage_job_done(bad_id))
            self.assertFalse(database.mark_multipage_job_failed(bad_id, "error"))

        # Verify table multipage_jobs still exists
        with database.SQL(self.test_db) as cur:
            cur.execute("SELECT count(*) as cnt FROM multipage_jobs")
            self.assertIsNotNone(cur.fetchone())

    def test_null_bytes_and_extreme_inputs(self):
        """Verify handling of null bytes, unicode emojis, and 100KB large payloads in params."""
        large_str = "A" * 100000  # 100KB parameter string
        unicode_str = "アニメ 🚀 特急 💥 \u2603 \U0001F600"
        null_byte_str = "safe_prefix\x00malicious_suffix"

        jid = database.enqueue_multipage_job(
            provider="anilist_" + unicode_str,
            browser_method="browse_" + null_byte_str,
            url_path="/path/" + unicode_str,
            request_params={'large': large_str, 'null': null_byte_str, 'unicode': unicode_str},
            target_page=20
        )
        self.assertIsNotNone(jid)

        job = database.dequeue_multipage_job(provider="anilist_" + unicode_str)
        self.assertIsNotNone(job)
        self.assertEqual(job['provider'], "anilist_" + unicode_str)
        self.assertEqual(job['browser_method'], "browse_" + null_byte_str)
        self.assertIn(large_str, job['params'])


if __name__ == '__main__':
    unittest.main()
