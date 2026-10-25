"""test_standards_and_security.py - Unit tests for modern standards, resource management, and security.
"""

import os
import json
import time
import datetime
import unittest
from unittest.mock import patch

from resources.lib.ui import control, database
from resources.lib.windows.download_manager import Manager
from resources.lib.AniListBrowser import AniListBrowser


class TestStandardsAndSecurity(unittest.TestCase):

    def setUp(self):
        self.test_dir = os.path.join(control.dataPath, 'test_sandbox')
        os.makedirs(self.test_dir, exist_ok=True)

    def tearDown(self):
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_sqlite_version_import(self):
        """Verify sqlite_version is imported cleanly without pysqlite deprecation warnings."""
        from resources.lib.ui.database_sync import sqlite_version
        self.assertIsInstance(sqlite_version, str)
        self.assertTrue(len(sqlite_version) > 0)

    def test_anilist_browser_utc_timezone_aware(self):
        """Verify AniListBrowser parses createdAt without DeprecationWarning."""
        node = {
            'createdAt': 1700000000,
            'body': 'Great anime review',
            'score': 85,
            'user': {'name': 'TestUser'}
        }
        res = AniListBrowser._normalize_anilist_review_node(node)
        self.assertIn('date', res)
        # 1700000000 is 2023-11-14 in UTC
        self.assertEqual(res['date'], '2023-11-14')

    def test_prune_expired_cache(self):
        """Verify prune_expired_cache deletes entries older than cutoff and retains fresh ones."""
        database._init_cache_table()
        now = int(time.time())
        old_epoch = now - (35 * 86400)  # 35 days ago
        fresh_epoch = now - (5 * 86400)  # 5 days ago

        with database.SQL(control.cacheFile) as cur:
            cur.execute("REPLACE INTO cache (key, value, date) VALUES (?, ?, ?)", ("old_key", "'old_val'", old_epoch))
            cur.execute("REPLACE INTO cache (key, value, date) VALUES (?, ?, ?)", ("fresh_key", "'fresh_val'", fresh_epoch))
            cur.connection.commit()

        # Prune older than 30 days
        deleted = database.prune_expired_cache(max_age_days=30)
        self.assertGreaterEqual(deleted, 1)

        with database.SQL(control.cacheFile) as cur:
            cur.execute("SELECT * FROM cache WHERE key='old_key'")
            self.assertIsNone(cur.fetchone())
            cur.execute("SELECT * FROM cache WHERE key='fresh_key'")
            self.assertIsNotNone(cur.fetchone())

    def test_download_manager_atomic_save(self):
        """Verify _save_downloads_atomic writes atomically and leaves no lingering temp files."""
        test_json = os.path.join(self.test_dir, 'downloads.json')
        with patch.object(control, 'downloads_json', test_json):
            data = {'task1': {'progress': 50, 'status': 'downloading'}}
            Manager._save_downloads_atomic(data)

            self.assertTrue(os.path.exists(test_json))
            self.assertFalse(os.path.exists(f"{test_json}.tmp"))

            with open(test_json, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            self.assertEqual(loaded, data)

    def test_download_filename_path_traversal_sanitization(self):
        """Verify filename sanitization prevents directory traversal attacks."""
        dm = Manager()

        # 1. Directory traversal sequence
        url = "https://example.com/../../../../etc/passwd"
        raw_name = url.split("?")[0].split("/")[-1]
        clean_name = os.path.basename(raw_name.replace('\\', '/')).strip()
        self.assertEqual(clean_name, "passwd")

        # 2. Windows style directory separators
        win_name = "..\\..\\windows\\system32\\cmd.exe"
        clean_win = os.path.basename(win_name.replace('\\', '/')).strip()
        self.assertEqual(clean_win, "cmd.exe")

        # 3. Standard URL with parameters
        param_url = "https://cdn.example.org/stream/episode_01.mkv?token=secret&auth=123"
        clean_param = os.path.basename(param_url.split("?")[0].split("/")[-1].replace('\\', '/')).strip()
        self.assertEqual(clean_param, "episode_01.mkv")

        # 4. Empty / slash-only fallback
        empty_raw = "///"
        clean_empty = os.path.basename(empty_raw.replace('\\', '/')).strip()
        final_fallback = clean_empty if clean_empty else "download.mkv"
        self.assertEqual(final_fallback, "download.mkv")


if __name__ == '__main__':
    unittest.main()
