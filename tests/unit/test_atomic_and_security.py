import os
import tempfile
import unittest
import json
from unittest.mock import patch, MagicMock

import tests.conftest  # noqa: F401
from resources.lib.ui import control, client, database
from resources.lib.windows.resolver import Resolver


class TestAtomicAndSecurity(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_atomic_write_json_success(self):
        target = os.path.join(self.test_dir, "sub", "data.json")
        payload = {"title": "Frieren", "episodes": 28, "genres": ["Adventure", "Fantasy"]}
        success = control.atomic_write_json(target, payload)
        self.assertTrue(success)
        self.assertTrue(os.path.exists(target))
        with open(target, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
        self.assertEqual(loaded, payload)

    def test_atomic_write_text_and_bytes(self):
        txt_target = os.path.join(self.test_dir, "test.txt")
        bin_target = os.path.join(self.test_dir, "test.bin")
        self.assertTrue(control.atomic_write_text(txt_target, "Hello Otaku!"))
        self.assertTrue(control.atomic_write_bytes(bin_target, b"\x00\x01\x02\x03"))

        with open(txt_target, 'r', encoding='utf-8') as f:
            self.assertEqual(f.read(), "Hello Otaku!")
        with open(bin_target, 'rb') as f:
            self.assertEqual(f.read(), b"\x00\x01\x02\x03")

    def test_url_scheme_validation_accepts_http_https(self):
        self.assertEqual(client._validate_url_scheme("https://api.myanimelist.net/v2"), "https://api.myanimelist.net/v2")
        self.assertEqual(client._validate_url_scheme("http://localhost:8080/test"), "http://localhost:8080/test")
        self.assertEqual(client._validate_url_scheme("//example.com/asset.js"), "https://example.com/asset.js")

    def test_url_scheme_validation_rejects_ssrf_and_lfi(self):
        with self.assertRaises(ValueError):
            client._validate_url_scheme("file:///etc/passwd")
        with self.assertRaises(ValueError):
            client._validate_url_scheme("ftp://ftp.example.com")
        with self.assertRaises(ValueError):
            client._validate_url_scheme("gopher://evil.com")
        with self.assertRaises(ValueError):
            client._validate_url_scheme("")

    def test_client_store_and_retrieve_path_traversal_sanitization(self):
        with patch.object(control, 'dataPath', self.test_dir):
            malicious_fname = "../../../etc/passwd.txt"
            client.store("safe_content", malicious_fname)
            # The file must be saved under test_dir using basename, NOT outside
            expected_file = os.path.join(self.test_dir, "passwd.txt")
            self.assertTrue(os.path.exists(expected_file))
            self.assertEqual(client.retrieve(malicious_fname), "safe_content")

    def test_sqlite_checkpoint_truncate(self):
        db_file = os.path.join(self.test_dir, "test_cache.db")
        with database.SQL(db_file) as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS test (id INT, val TEXT)")
            cur.execute("INSERT INTO test VALUES (1, 'demo')")
            cur.connection.commit()

        # Run checkpoint_databases
        with patch.object(control, 'cacheFile', db_file), \
             patch.object(control, 'malSyncDB', None), \
             patch.object(control, 'searchHistoryDB', None), \
             patch.object(control, 'mappingDB', None):
            database.checkpoint_databases(truncate=True)

        with database.SQL(db_file) as cur:
            cur.execute("SELECT val FROM test WHERE id=1")
            row = cur.fetchone()
            self.assertEqual(row['val'], 'demo')

    def test_debrid_failover_chain(self):
        resolver = Resolver.__new__(Resolver)
        resolver.canceled = False
        resolver.pack_select = False
        resolver.episode = 1
        resolver.mal_id = 12345
        resolver.media_type = 'anime'
        resolver.source_select = False
        resolver.play = False
        resolver.source_select_close = None
        resolver.return_data = {}
        resolver.setProperty = MagicMock()
        resolver.close = MagicMock()
        resolver.resolvers = {
            'Real-Debrid': MagicMock(),
            'TorBox': MagicMock()
        }

        # Mock enabled debrids: both Real-Debrid and TorBox are enabled
        with patch.object(control, 'enabled_debrid', return_value={'realdebrid': True, 'torbox': True}):
            providers = resolver.get_enabled_debrid_providers()
            self.assertIn('Real-Debrid', providers)
            self.assertIn('TorBox', providers)

            def mock_resolve_source(api, source):
                if source.get('debrid_provider') == 'Real-Debrid':
                    return None
                elif source.get('debrid_provider') == 'TorBox':
                    return 'https://torbox.net/stream/sample.mkv'
                return None

            resolver.resolve_source = mock_resolve_source
            resolver.prefetch_play_link = lambda link: {'url': link, 'headers': {}}

            source = {
                'type': 'torrent',
                'provider': 'Nyaa',
                'debrid_provider': 'Real-Debrid',
                'hash': '4A7E00112233',
                'quality': 3,
                'info': ['1080p'],
                'release_title': 'Frieren 01'
            }

            with patch('resources.lib.ui.ffprobe_chapters.attach_to_linkinfo'):
                resolver.resolve([source])
                self.assertIsNotNone(resolver.return_data.get('linkinfo'))
                self.assertEqual(resolver.return_data['linkinfo']['url'], 'https://torbox.net/stream/sample.mkv')
                self.assertEqual(resolver.return_data['source']['debrid_provider'], 'TorBox')


if __name__ == '__main__':
    unittest.main()
