"""
test_routes_and_indexers.py - Unit Tests for Routes & Indexers (Phase 8)
========================================================================
Tests search routes, watch history routes, episode metadata indexing,
unaired episode countdown badges, and spoiler shielding.
"""

import os
import unittest
import json
import pickle
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

import conftest
from resources.lib.routes import search, history
from resources.lib import indexers
from resources.lib.ui import control, database


class TestRoutesAndIndexers(unittest.TestCase):

    def test_search_config(self):
        types_list, dialog_dict, media_type_map, history_map = search.get_search_config()
        self.assertIn("search_anime/", types_list)
        self.assertIn("search_anime/", dialog_dict)
        self.assertEqual(dialog_dict["search_anime/"], "anime")

    def test_search_history_route(self):
        with patch("resources.lib.ui.database.getSearchHistory", return_value=["Naruto", "One Piece"]):
            with patch("resources.lib.ui.control.draw_items") as mock_draw:
                search.SEARCH_HISTORY({}, {"filter": "anime"})
                self.assertTrue(mock_draw.called)
                items = mock_draw.call_args[0][0]
                self.assertGreaterEqual(len(items), 2)
                item_names = [i["name"] for i in items]
                self.assertIn("Naruto", item_names)

    def test_indexers_should_hide_unaired_episode(self):
        control.setSetting('interface.aired_episodes', 'true')
        future_date = (date.today() + timedelta(days=10)).isoformat()
        past_date = (date.today() - timedelta(days=10)).isoformat()

        self.assertTrue(indexers.should_hide_unaired_episode(future_date))
        self.assertFalse(indexers.should_hide_unaired_episode(past_date))
        self.assertFalse(indexers.should_hide_unaired_episode(None))

    def test_indexers_parse_episodes(self):
        meta_dict = {
            "name": "Episode 1",
            "url": "play/1",
            "info": {
                "title": "To You, in 2000 Years",
                "aired": (date.today() + timedelta(days=1)).isoformat(),
                "episode": 1
            },
            "image": {"poster": "poster.jpg", "fanart": "fanart.jpg"}
        }
        res_row = {
            "number": 1,
            "kodi_meta": database.dumps(meta_dict),
            "filler": "Canon"
        }

        control.setSetting('interface.aired.show_countdown', 'true')
        parsed = indexers.parse_episodes(res_row, eps_watched=0)
        self.assertIn("(Airs Tomorrow)", parsed["name"])
        self.assertTrue(parsed["info"].get("unaired"))


if __name__ == "__main__":
    unittest.main()
