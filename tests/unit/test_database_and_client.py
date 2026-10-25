"""
Unit tests for Database SQLite connection pooling, safe serialization, and Client session management.
"""

import pickle
import unittest
from unittest.mock import MagicMock, patch

import tests.conftest  # noqa: F401
from resources.lib.ui import database, client


class TestDatabaseAndClient(unittest.TestCase):

    def test_database_thread_local_connection_pooling(self):
        """Consecutive SQL() blocks on the same thread reuse the same Connection."""
        test_db = f"{tests.conftest.TEST_PROFILE_DIR}/pool_test.db"
        with database.SQL(test_db) as cur1:
            conn1 = cur1.connection
            cur1.execute("CREATE TABLE IF NOT EXISTS test_t (id INT PRIMARY KEY)")

        with database.SQL(test_db) as cur2:
            conn2 = cur2.connection

        self.assertIs(conn1, conn2, "Consecutive SQL contexts on same thread must reuse connection")

    def test_database_safe_serialization(self):
        """database.dumps writes UTF-8 bytes; database.loads reads JSON, legacy pickle, and None safely."""
        data = {'name': 'Naruto', 'eps': 220, 'tags': ['ninja', 'action']}
        serialized = database.dumps(data)
        self.assertIsInstance(serialized, (bytes, str))
        loaded = database.loads(serialized)
        self.assertEqual(loaded, data)

        # Legacy pickle roundtrip through _SafeUnpickler
        pickled = pickle.dumps(data, protocol=2)
        loaded_pickle = database.loads(pickled)
        self.assertEqual(loaded_pickle, data)

        # None / empty handling
        self.assertEqual(database.loads(None), {})
        self.assertEqual(database.loads(''), {})

    def test_safe_unpickler_blocks_rce(self):
        """_SafeUnpickler blocks arbitrary code execution payloads."""
        import os
        class RCEPayload:
            def __reduce__(self):
                return (os.system, ('echo VULN',))

        dangerous_pickle = pickle.dumps(RCEPayload())
        with self.assertRaises(Exception):
            database.loads(dangerous_pickle)

    def test_sql_table_identifier_whitelisting(self):
        """Dynamic table and column names reject SQL injection payloads."""
        # Whitelisted tables should pass validation
        self.assertTrue(database._validate_identifier('show'))
        self.assertTrue(database._validate_identifier('episode'))
        self.assertTrue(database._validate_identifier('watchlist'))

        # Injections must raise ValueError
        with self.assertRaises(ValueError):
            database._validate_identifier('show; DROP TABLE show;--')
        with self.assertRaises(ValueError):
            database._validate_identifier("episode' OR '1'='1")
        with self.assertRaises(ValueError):
            database._validate_identifier('mal_id, name FROM secrets;--')

    def test_client_session_opener_reuse(self):
        """client.request(use_session=True) reuses cached domain openers."""
        client.clear_session()
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.info.return_value = {'Content-Type': 'application/json'}
        mock_resp.headers = {'Content-Type': 'application/json'}
        mock_resp.code = 200
        mock_resp.url = 'https://api.example.com/v1/test'

        with patch('urllib.request.OpenerDirector.open', return_value=mock_resp):
            client.get('https://api.example.com/v1/test')
            opener1 = client._session_openers.get('https://api.example.com')
            self.assertIsNotNone(opener1)

            client.get('https://api.example.com/v1/test2')
            opener2 = client._session_openers.get('https://api.example.com')
            self.assertIs(opener1, opener2, "Domain opener must be reused across requests")


if __name__ == '__main__':
    unittest.main()
