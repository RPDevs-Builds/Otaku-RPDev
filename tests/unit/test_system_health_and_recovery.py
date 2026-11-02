# -*- coding: utf-8 -*-
"""
test_system_health_and_recovery.py - Tests for SQLite Auto-Recovery & Diagnostics Suite
"""

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from resources.lib.ui import database, control
from resources.lib.routes import tools


class TestSystemHealthAndRecovery(unittest.TestCase):

    def test_is_db_corruption_error(self):
        self.assertTrue(database._is_db_corruption_error(sqlite3.DatabaseError("file is not a database")))
        self.assertTrue(database._is_db_corruption_error(sqlite3.DatabaseError("database disk image is malformed")))
        self.assertTrue(database._is_db_corruption_error(sqlite3.OperationalError("disk image is malformed")))
        self.assertFalse(database._is_db_corruption_error(sqlite3.OperationalError("database is locked")))
        self.assertFalse(database._is_db_corruption_error(ValueError("random error")))

    def test_quarantine_and_recover_db(self):
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"NOT A REAL SQLITE DATABASE CONTENT")
            temp_db = tf.name

        try:
            self.assertTrue(os.path.exists(temp_db))
            database._quarantine_and_recover_db(temp_db)

            # Assert original file was moved/quarantined
            self.assertFalse(os.path.exists(temp_db))

            # Find quarantined file
            dirname = os.path.dirname(temp_db)
            basename = os.path.basename(temp_db)
            quarantined = [f for f in os.listdir(dirname) if f.startswith(basename + ".corrupt.")]
            self.assertTrue(len(quarantined) >= 1)

            # Cleanup quarantined file
            for qf in quarantined:
                try:
                    os.remove(os.path.join(dirname, qf))
                except OSError:
                    pass
        finally:
            if os.path.exists(temp_db):
                try:
                    os.remove(temp_db)
                except OSError:
                    pass

    def test_execute_write_with_retry_success(self):
        conn = sqlite3.connect(":memory:")
        cur = conn.cursor()
        cur.execute("CREATE TABLE test (val TEXT)")

        database.execute_write_with_retry(cur, "INSERT INTO test VALUES (?)", ("alpha",))
        cur.execute("SELECT * FROM test")
        rows = cur.fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "alpha")
        conn.close()

    def test_execute_write_with_retry_locked_backoff(self):
        mock_cur = MagicMock()
        # Fail twice with locked, then succeed
        mock_cur.execute.side_effect = [
            sqlite3.OperationalError("database is locked"),
            sqlite3.OperationalError("database is locked"),
            MagicMock()
        ]

        # Should succeed after retries
        result = database.execute_write_with_retry(mock_cur, "INSERT INTO test VALUES (1)", max_retries=3)
        self.assertEqual(mock_cur.execute.call_count, 3)

    def test_generate_diagnostics_report(self):
        report = tools.generate_diagnostics_report()
        self.assertIn("System Health & Diagnostics Report", report)
        self.assertIn("[1] System Environment", report)
        self.assertIn("[2] Debrid Cloud Providers", report)
        self.assertIn("[3] Watchlist Services", report)
        self.assertIn("[4] SQLite Databases & Storage", report)
        self.assertIn("[5] Scraper Circuit Breakers & Domains", report)

    def test_execute_system_repair(self):
        with patch('resources.lib.ui.control.progressDialog') as mock_prog, \
             patch('resources.lib.ui.control.notify') as mock_notify:
            mock_dlg = MagicMock()
            mock_prog.create = mock_dlg.create
            mock_prog.update = mock_dlg.update
            mock_prog.close = mock_dlg.close

            tools.execute_system_repair()
            mock_notify.assert_called()


if __name__ == '__main__':
    unittest.main()
