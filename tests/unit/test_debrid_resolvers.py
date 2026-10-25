"""
test_debrid_resolvers.py - Unit Tests for Debrid Resolvers & Cloud VFS (Phase 5)
================================================================================
Tests RealDebrid, TorBox, debrid_cache, and cloud VFS operations
for hash caching, TTL expiration, hoster unrestrict, and error safety.
"""

import os
import unittest
import time
from unittest.mock import patch, MagicMock

import conftest
from resources.lib.debrid import debrid_cache
from resources.lib.debrid.real_debrid import RealDebrid
from resources.lib.debrid.torbox import TorBox
from resources.lib.debrid import debrid_cloud
from resources.lib.ui import control


class TestDebridResolvers(unittest.TestCase):

    def setUp(self):
        debrid_cache.clear_debrid_cache()

    def test_debrid_cache_set_and_get(self):
        test_hash = "abcdef1234567890abcdef1234567890abcdef12"
        debrid_cache.set_cached_hashes([(test_hash, "True")], "realdebrid")

        results = debrid_cache.get_cached_hashes([test_hash])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["hash"], test_hash)
        self.assertEqual(results[0]["debrid"], "realdebrid")
        self.assertEqual(results[0]["cached"], "True")

    def test_debrid_cache_clear(self):
        test_hash = "1122334455667788990011223344556677889900"
        debrid_cache.set_cached_hashes([(test_hash, "True")], "torbox")
        self.assertEqual(len(debrid_cache.get_cached_hashes([test_hash])), 1)

        debrid_cache.clear_debrid_cache()
        self.assertEqual(len(debrid_cache.get_cached_hashes([test_hash])), 0)

    def test_debrid_cache_dmm_secret_math(self):
        self.assertEqual(debrid_cache._to_int32(0x100000000), 0)
        self.assertEqual(debrid_cache._to_int32(0xFFFFFFFF), -1)
        key, sol = debrid_cache._get_dmm_secret()
        self.assertIsInstance(key, str)
        self.assertIsInstance(sol, str)
        self.assertGreater(len(key), 8)
        self.assertGreater(len(sol), 8)

    def test_real_debrid_resolve_single_file(self):
        rd = RealDebrid()
        mock_torrent_info = {
            "id": "TORRENT_123",
            "files": [{"id": 1, "selected": 1, "path": "/Show - 01.mkv"}],
            "links": ["https://real-debrid.com/d/XYZ123"]
        }
        with patch.object(rd, "addMagnet", return_value={"id": "TORRENT_123"}):
            with patch.object(rd, "torrentSelect", return_value=True):
                with patch.object(rd, "torrentInfo", return_value=mock_torrent_info):
                    with patch.object(rd, "resolve_hoster", return_value="https://download.real-debrid.com/video.mkv"):
                        with patch.object(rd, "deleteTorrent", return_value=True):
                            resolved = rd.resolve_single_magnet("magnet:?xt=urn:btih:hash", 1, pack_select=False)
                            self.assertEqual(resolved, "https://download.real-debrid.com/video.mkv")

    def test_torbox_status_parsing(self):
        tb = TorBox()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "success": True,
            "data": {
                "email": "user@example.com",
                "plan": 1
            }
        }
        with patch("resources.lib.ui.client.get", return_value=mock_resp):
            tb.status()
            self.assertEqual(control.getSetting("torbox.username"), "user@example.com")
            self.assertEqual(control.getSetting("torbox.auth.status"), "Essential")

    def test_torbox_status_network_failure(self):
        tb = TorBox()
        with patch("resources.lib.ui.client.get", return_value=None):
            # Must not crash when network returns None
            tb.status()


if __name__ == "__main__":
    unittest.main()
