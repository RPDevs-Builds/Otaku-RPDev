"""
test_watchlist_flavors.py - Unit Tests for Watchlist Synchronization (Phase 4)
=============================================================================
Tests WatchlistFlavorBase, AniList, MyAnimeList, Kitsu, and Simkl flavors
for enrichment extraction, mapping lookups, status transitions, and error safety.
"""

import os
import unittest
from unittest.mock import patch, MagicMock

import conftest
from resources.lib.WatchlistFlavor.WatchlistFlavorBase import WatchlistFlavorBase
from resources.lib.WatchlistFlavor.AniList import AniListWLF
from resources.lib.WatchlistFlavor.MyAnimeList import MyAnimeListWLF
from resources.lib.WatchlistFlavor.Kitsu import KitsuWLF
from resources.lib.WatchlistFlavor.Simkl import SimklWLF


class TestWatchlistFlavors(unittest.TestCase):

    def test_watchlist_flavor_properties(self):
        kitsu = KitsuWLF()
        self.assertEqual(kitsu.title, "Kitsu")
        self.assertEqual(kitsu.flavor_name, "kitsu")

        simkl = SimklWLF()
        self.assertEqual(simkl.title, "Simkl")
        self.assertEqual(simkl.flavor_name, "simkl")

    def test_watchlist_base_extract_anilist_enrichment(self):
        base = WatchlistFlavorBase()
        media = {
            "id": 16498,
            "idMal": 16498,
            "title": {"romaji": "Shingeki no Kyojin", "english": "Attack on Titan"},
            "bannerImage": "http://example.com/banner.jpg",
            "coverImage": {"extraLarge": "http://example.com/cover.jpg"},
            "format": "TV",
            "episodes": 25,
            "duration": 24,
            "status": "FINISHED",
            "genres": ["Action", "Drama"],
            "averageScore": 85,
            "studios": {"edges": [{"isMain": True, "node": {"name": "WIT STUDIO"}}]}
        }
        enrichment = base._extract_anilist_enrichment(media)
        self.assertEqual(enrichment.get("average_score"), 8.5)
        self.assertEqual(enrichment.get("duration"), 1440)
        self.assertEqual(enrichment.get("studios"), ["WIT STUDIO"])
        self.assertEqual(enrichment.get("poster"), "http://example.com/cover.jpg")
        self.assertEqual(enrichment.get("anilist_id"), 16498)

    def test_watchlist_base_get_mapping_id(self):
        base = WatchlistFlavorBase()
        # Test fallback when DB returns None
        with patch("resources.lib.ui.database.get_show", return_value=None):
            with patch("resources.lib.ui.database.get_unique_ids", return_value=None):
                with patch.object(base, "get_flavor_id_vercel", return_value=7442):
                    mapping_id = base._get_mapping_id(16498, "kitsu_id")
                    self.assertEqual(mapping_id, 7442)

    def test_anilist_flavor_headers_and_sort(self):
        ani = AniListWLF()
        headers = ani._AniListWLF__headers()
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["Accept"], "application/json")

        statuses = ani.action_statuses()
        status_codes = [s[1] for s in statuses]
        self.assertIn("CURRENT", status_codes)
        self.assertIn("COMPLETED", status_codes)

        sort_val = ani._AniListWLF__get_sort()
        self.assertIsNotNone(sort_val)

    def test_mal_flavor_save_completed(self):
        mal = MyAnimeListWLF()
        mock_data = [
            {"node": {"id": 16498, "num_episodes": 25}},
            {"node": {"id": 20000, "num_episodes": None}},  # Unannounced/unknown episodes
            {"node": {"id": 30000}}                          # Missing num_episodes key
        ]
        with patch.object(mal, "get_user_anime_list", return_value=mock_data):
            completed = mal.save_completed()
            self.assertEqual(completed.get("16498"), 25)
            self.assertNotIn("20000", completed)
            self.assertNotIn("30000", completed)


    def test_simkl_update_num_episodes_single_and_up_to(self):
        simkl = SimklWLF()
        with patch("resources.lib.WatchlistFlavor.Simkl.client.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"not_found": {}}
            mock_post.return_value = mock_resp

            # Single episode
            simkl.update_num_episodes("12345", 5, up_to=False)
            self.assertTrue(mock_post.called)
            sent_data = mock_post.call_args[1]["json_data"]
            self.assertEqual(sent_data["shows"][0]["episodes"], [{"number": 5}])

            # Up to episode (bulk history sync)
            simkl.update_num_episodes("12345", 4, up_to=True)
            sent_bulk = mock_post.call_args[1]["json_data"]
            expected_eps = [{"number": 1}, {"number": 2}, {"number": 3}, {"number": 4}]
            self.assertEqual(sent_bulk["shows"][0]["episodes"], expected_eps)


if __name__ == "__main__":
    unittest.main()
