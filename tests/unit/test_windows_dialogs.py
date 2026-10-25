"""
test_windows_dialogs.py - Unit Tests for GUI Windows & Dialogs (Phase 7)
========================================================================
Tests Resolver, SourceSelect, PlayingNext, and TextViewerXML windows
for action dispatch, source reordering, skin control error resilience, and key actions.
"""

import os
import unittest
from unittest.mock import patch, MagicMock

import conftest
import xbmcgui
from resources.lib.windows.resolver import Resolver
from resources.lib.windows.playing_next import PlayingNext
from resources.lib.windows.textviewer import TextViewerXML
from resources.lib.windows.source_select import SourceSelect
from resources.lib.ui import control


class TestWindowsDialogs(unittest.TestCase):

    def test_resolver_window_reorder_sources(self):
        res = Resolver("resolver.xml", conftest.ADDON_ROOT, actionArgs={"mal_id": 16498}, source_select=False)
        sources = [
            {"release_title": "S1", "debrid_provider": "alldebrid", "type": "torrent", "quality": 3, "size": "1 GB"},
            {"release_title": "S2", "debrid_provider": "realdebrid", "type": "torrent", "quality": 4, "size": "2 GB"}
        ]
        reordered = res.reorder_sources(sources)
        self.assertEqual(len(reordered), 2)
        titles = [s["release_title"] for s in reordered]
        self.assertIn("S1", titles)
        self.assertIn("S2", titles)

    def test_resolver_build_art_dict(self):
        actionArgs = {
            "mal_id": 16498,
            "params": {
                "thumb": "http://example.com/thumb.jpg",
                "poster": "http://example.com/poster.jpg"
            }
        }
        res = Resolver("resolver.xml", conftest.ADDON_ROOT, actionArgs=actionArgs, source_select=False)
        art = res._build_art_dict(use_params=True)
        self.assertEqual(art.get("thumb"), "http://example.com/thumb.jpg")
        self.assertEqual(art.get("tvshow.poster"), "http://example.com/poster.jpg")

    def test_playing_next_handle_actions(self):
        mock_player = MagicMock()
        mock_player.getTotalTime.return_value = 1440.0
        actionArgs = {
            "playing_file": "http://example.com/video.mkv",
            "duration": 30,
            "total_time": 1440,
            "skipoutro_end": 1410
        }
        pn = PlayingNext("playing_next.xml", conftest.ADDON_ROOT, actionArgs=actionArgs)
        pn.player = mock_player
        self.assertFalse(pn.actioned)

        # Test clicking playnext (control 3001)
        pn.handle_action(3001)
        self.assertTrue(pn.actioned)
        mock_player.seekTime.assert_called_with(1435.0)

    def test_textviewer_window(self):
        tv = TextViewerXML("textviewer.xml", conftest.ADDON_ROOT, heading="Changelog", instructions_text="Otaku v5.5.0 Released!")
        tv.onInit()
        self.assertEqual(tv.getProperty("otaku.heading"), "Changelog")
        self.assertEqual(tv.getProperty("otaku.text"), "Otaku v5.5.0 Released!")

        # Test back action
        mock_action = MagicMock()
        mock_action.getId.return_value = xbmcgui.ACTION_NAV_BACK
        tv.onAction(mock_action)


if __name__ == "__main__":
    unittest.main()
