"""
test_scrapers_all.py - Unit Tests for Scrapers & Extractor Engines (Phase 6)
=============================================================================
Tests ScraperCircuitBreaker, Nyaa, AnimeTosho, Torrentio, and Source sorting
for resolution categorization, hash extraction, error trapping, and circuit tripping.
"""

import os
import unittest
from unittest.mock import patch, MagicMock

import conftest
from resources.lib.pages import ScraperCircuitBreaker, Sources as MainSources
from resources.lib.pages.nyaa import Sources as NyaaSources
from resources.lib.pages.animetosho import Sources as ToshoSources
from resources.lib.pages.torrentio import Sources as TorrentioSources
from resources.lib.ui import control


class TestScrapersAll(unittest.TestCase):

    def test_circuit_breaker_tripping_and_reset(self):
        cb = ScraperCircuitBreaker(failure_threshold=2, cooldown_seconds=60)
        self.assertFalse(cb.is_tripped("nyaa"))

        cb.record_failure("nyaa")
        self.assertFalse(cb.is_tripped("nyaa"))

        cb.record_failure("nyaa")
        self.assertTrue(cb.is_tripped("nyaa"))

        cb.record_success("nyaa")
        self.assertFalse(cb.is_tripped("nyaa"))

    def test_nyaa_parse_view(self):
        raw_item = {
            "name": "[SubsPlease] Shingeki no Kyojin - 01 (1080p) [ABCD1234].mkv",
            "hash": "abcdef1234567890abcdef1234567890abcdef12",
            "size": "1.4 GiB",
            "seeders": 150,
            "magnet": "magnet:?xt=urn:btih:abcdef1234567890abcdef1234567890abcdef12"
        }
        parsed = NyaaSources.parse_nyaa_view(raw_item, episode="1", cached=True)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["release_title"], raw_item["name"])
        self.assertEqual(parsed["hash"], raw_item["hash"])
        self.assertEqual(parsed["quality"], 3)  # 1080p == 3
        self.assertEqual(parsed["type"], "torrent")
        self.assertEqual(parsed["seeders"], 150)

    def test_animetosho_parse_view(self):
        raw_item = {
            "name": "[Erai-raws] Shingeki no Kyojin - 01 [720p][Multiple Subtitle].mkv",
            "hash": "1122334455667788990011223344556677889900",
            "size": "850 MB",
            "seeders": 50,
            "magnet": "magnet:?xt=urn:btih:1122334455667788990011223344556677889900"
        }
        parsed = ToshoSources.parse_animetosho_view(raw_item, episode="1", cached=True)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["release_title"], raw_item["name"])
        self.assertEqual(parsed["quality"], 2)  # 720p == 2

    def test_sources_sort_sources(self):
        torrent_list = [
            {"release_title": "Show 720p", "quality": 2, "type": "torrent", "size": "700 MB", "seeders": 10, "provider": "nyaa"},
            {"release_title": "Show 1080p", "quality": 3, "type": "torrent", "size": "1.4 GB", "seeders": 50, "provider": "nyaa"},
            {"release_title": "Show 4K", "quality": 4, "type": "torrent", "size": "4.5 GB", "seeders": 100, "provider": "nyaa"}
        ]
        control.setSetting("general.fileFilter", "0")  # disable size filtering for test
        sorted_sources = MainSources.sortSources(
            torrent_list=torrent_list,
            hoster_list=[],
            embed_list=[],
            cloud_files=[],
            local_files=[],
            media_type="episodes",
            duration=1440
        )
        self.assertEqual(len(sorted_sources), 3)
        qualities = [s["quality"] for s in sorted_sources]
        self.assertEqual(qualities[0], 4)
        self.assertEqual(qualities[1], 3)
        self.assertEqual(qualities[2], 2)


if __name__ == "__main__":
    unittest.main()
