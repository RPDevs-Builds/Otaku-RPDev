"""
test_endpoints_all.py - Unit Tests for External Endpoints (Phase 3)
==================================================================
Tests AniList, Simkl, AniDB, AniSkip, Fanart, and AnimeFiller endpoints
for response decoding, rate limit handling, schema variations, and network faults.
"""

import os
import unittest
from unittest.mock import patch, MagicMock

import conftest
from resources.lib.endpoints import anilist, simkl, anidb, aniskip, fanart, anime_filler


class TestEndpointsAll(unittest.TestCase):

    def test_anilist_get_anilist_by_mal_ids(self):
        ani = anilist.Anilist()
        fixture_path = os.path.join(conftest.REPO_ROOT, "tests/fixtures/anilist/trending.json")
        with open(fixture_path, "r", encoding="utf-8") as f:
            import json
            fixture_dict = json.load(f)
            fixture_dict["data"]["Page"]["pageInfo"]["hasNextPage"] = False
            fixture_json = json.dumps(fixture_dict)

        with patch("resources.lib.ui.client.request", return_value=fixture_json):
            media = ani.get_anilist_by_mal_ids([16498])
            self.assertEqual(len(media), 1)
            self.assertEqual(media[0]["id"], 16498)
            self.assertEqual(media[0]["title"]["userPreferred"], "Attack on Titan")

    def test_anilist_malformed_response_handling(self):
        ani = anilist.Anilist()
        with patch("resources.lib.ui.client.request", return_value="<html>502 Bad Gateway</html>"):
            media = ani.get_anilist_by_mal_ids([16498])
            self.assertEqual(len(media), 0)

    def test_anilist_ratings_batch(self):
        ani = anilist.Anilist()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": {
                "Page": {
                    "media": [
                        {
                            "idMal": 16498,
                            "averageScore": 85,
                            "stats": {"scoreDistribution": [{"score": 100, "amount": 1000}]}
                        }
                    ]
                }
            }
        }
        with patch("resources.lib.ui.client.post", return_value=mock_resp):
            ratings = ani.get_anilist_ratings_batch([16498])
            self.assertIn(16498, ratings)
            self.assertEqual(ratings[16498]["anilist_score"], 85)

    def test_simkl_calendar_data(self):
        simkl_instance = simkl.Simkl()
        fixture_path = os.path.join(conftest.REPO_ROOT, "tests/fixtures/simkl/search.json")
        with open(fixture_path, "r", encoding="utf-8") as f:
            import json
            fixture_data = json.load(f)

        with patch.object(simkl_instance, "get_cached_data", return_value=None):
            mock_resp = MagicMock()
            mock_resp.json.return_value = [
                {
                    "ids": {"mal": "16498"},
                    "date": "2023-11-04T15:00:00Z",
                    "episode": {"episode": 28}
                }
            ]
            with patch("resources.lib.ui.client.get", return_value=mock_resp):
                entry = simkl_instance.fetch_and_find_simkl_entry(16498)
                self.assertIsNotNone(entry)
                self.assertEqual(entry["ids"]["mal"], "16498")

    def test_anidb_get_episode_meta(self):
        xml_content = """<?xml version="1.0" encoding="utf-8"?>
        <anime id="9541">
            <episodes>
                <episode id="147573">
                    <epno>1</epno>
                </episode>
                <episode id="147574">
                    <epno>2</epno>
                </episode>
            </episodes>
        </anime>
        """
        mock_resp = MagicMock()
        mock_resp.text = xml_content
        with patch("resources.lib.ui.client.get", return_value=mock_resp):
            meta = anidb.get_episode_meta(9541)
            self.assertIn("1", meta)
            self.assertEqual(meta["1"]["anidb_id"], "147573")
            self.assertIn("2", meta)

    def test_anidb_malformed_xml(self):
        mock_resp = MagicMock()
        mock_resp.text = "NOT XML CONTENT"
        with patch("resources.lib.ui.client.get", return_value=mock_resp):
            meta = anidb.get_episode_meta(9541)
            self.assertEqual(meta, {})

    def test_aniskip_fetch_skip_times(self):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "found": True,
            "results": [
                {
                    "interval": {"startTime": 90.0, "endTime": 180.0},
                    "skipType": "op"
                }
            ]
        }
        with patch("resources.lib.ui.client.get", return_value=mock_resp):
            data = aniskip._fetch_skip_times(16498, 1, "op")
            self.assertTrue(data["found"])
            self.assertEqual(len(data["results"]), 1)

    def test_fanart_get_art(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "showbackground": [{"url": "http://fanart.tv/bg1.jpg", "lang": "en"}],
            "tvthumb": [{"url": "http://fanart.tv/thumb1.jpg", "lang": "en"}],
            "clearlogo": [{"url": "http://fanart.tv/logo1.png", "lang": "en", "id": "100"}]
        }
        with patch("resources.lib.ui.client.get", return_value=mock_resp):
            art = fanart.getArt({"thetvdb_id": 267440}, "tvshows")
            self.assertIn("http://fanart.tv/bg1.jpg", art.get("fanart", []))
            self.assertIn("http://fanart.tv/logo1.png", art.get("clearlogo", []))

    def test_anime_filler_get_data(self):
        html = """
        <html>
        <body>
            <table class="EpisodeList">
                <tbody>
                    <tr><td>1</td><td><span>Manga Canon</span></td></tr>
                    <tr><td>2</td><td><span>Filler</span></td></tr>
                </tbody>
            </table>
        </body>
        </html>
        """
        mock_resp = MagicMock()
        mock_resp.text = html
        with patch("resources.lib.ui.client.get", return_value=mock_resp):
            fillers = anime_filler.get_data("Naruto")
            self.assertEqual(fillers, ["Manga Canon", "Filler"])


if __name__ == "__main__":
    unittest.main()
