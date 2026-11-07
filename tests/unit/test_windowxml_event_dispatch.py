# Standardized Otaku Test Bootstrap
import os
import sys

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_TEST_DIR, '..' if os.path.basename(_TEST_DIR) in ('unit', 'integration', 'lint') else '.'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
_TESTS_DIR = os.path.join(_REPO_ROOT, 'tests')
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import conftest  # Centralized Kodi mock harness  # noqa: F401

import unittest
from unittest.mock import MagicMock, patch

import xbmcgui
from resources.lib.ui import control
from resources.lib.windows.source_select import SourceSelect
from resources.lib.windows.download_manager import DownloadManager
from resources.lib.windows.playing_next import PlayingNext
from resources.lib.windows.skip_intro import SkipIntro
from resources.lib.windows.clear_cache import ClearCacheDialog
from resources.lib.windows.textviewer import TextViewerXML
from resources.lib.windows.still_watching import StillWatchingXML
from resources.lib.windows.wlf_auth import WatchlistFlavorAuth


class MockRemovableControlList:
    """Mock ControlList that supports removeItem(idx) to test in-place list mutation."""

    def __init__(self):
        self._items = []
        self._selected = 0
        self.reset_called = False

    def addItem(self, item):
        self._items.append(item)

    def removeItem(self, idx):
        if 0 <= idx < len(self._items):
            self._items.pop(idx)

    def reset(self):
        self.reset_called = True
        self._items.clear()
        self._selected = 0

    def size(self):
        return len(self._items)

    def getListItem(self, idx):
        return self._items[idx] if 0 <= idx < len(self._items) else None

    def getSelectedPosition(self):
        return self._selected if self._items else -1

    def selectItem(self, idx):
        self._selected = idx


class TestWindowXMLEventDispatch(unittest.TestCase):

    def test_source_select_single_event_dispatch_on_click(self):
        """Verify SourceSelect resolves item on onClick(1000) and ignores onAction(7)."""
        ss = SourceSelect.__new__(SourceSelect)
        ss.displayed_sources = [
            {'release_title': 'Episode 1 [1080p]', 'quality': 3, 'type': 'torrent', 'provider': 'Nyaa'}
        ]
        ss.position = 0
        ss.display_list = MagicMock()
        ss.display_list.getSelectedPosition.return_value = 0
        ss.resolve_item = MagicMock()
        ss.close = MagicMock()

        # Action 7 (Enter/Select) should NOT trigger resolve_item directly in onAction
        action_select = MagicMock()
        action_select.getId.return_value = 7
        ss.onAction(action_select)
        ss.resolve_item.assert_not_called()

        # Action 100 should also NOT trigger resolve_item in onAction
        action_100 = MagicMock()
        action_100.getId.return_value = 100
        ss.onAction(action_100)
        ss.resolve_item.assert_not_called()

        # Single event dispatch: onClick(1000) handles the selection cleanly
        ss.onClick(1000)
        ss.resolve_item.assert_called_once()

    def test_source_select_back_action_closes_safely(self):
        """Verify SourceSelect closes and clears playlist on back/cancel actions."""
        ss = SourceSelect.__new__(SourceSelect)
        ss.stream_link = "active_link"
        ss.close = MagicMock()

        action_back = MagicMock()
        action_back.getId.return_value = 92  # ACTION_NAV_BACK
        ss.onAction(action_back)

        self.assertFalse(ss.stream_link)
        ss.close.assert_called_once()

    def test_download_manager_in_place_mutation_with_remove_item(self):
        """Verify DownloadManager trims list via removeItem without calling reset()."""
        dm = DownloadManager.__new__(DownloadManager)
        dm.display_list = MockRemovableControlList()

        # Populate initial 3 items
        initial_downloads = [
            {'filename': 'Ep1.mkv', 'speed': '1 MB/s', 'progress': 50, 'eta': '00:05:00', 'filesize': '500 MB', 'downloaded': '250 MB', 'status': 'Downloading', 'hash': 'h1'},
            {'filename': 'Ep2.mkv', 'speed': '2 MB/s', 'progress': 30, 'eta': '00:10:00', 'filesize': '500 MB', 'downloaded': '150 MB', 'status': 'Downloading', 'hash': 'h2'},
            {'filename': 'Ep3.mkv', 'speed': '3 MB/s', 'progress': 10, 'eta': '00:15:00', 'filesize': '500 MB', 'downloaded': '50 MB', 'status': 'Downloading', 'hash': 'h3'},
        ]
        dm.downloads = initial_downloads
        dm.populate_menu_items()

        self.assertEqual(dm.display_list.size(), 3)
        self.assertFalse(dm.display_list.reset_called)

        # Shrink to 2 items (Ep3 finished/removed) and update Ep1 progress in-place
        dm.downloads = [
            {'filename': 'Ep1.mkv', 'speed': '1.5 MB/s', 'progress': 80, 'eta': '00:02:00', 'filesize': '500 MB', 'downloaded': '400 MB', 'status': 'Downloading', 'hash': 'h1'},
            {'filename': 'Ep2_renamed.mkv', 'speed': '2.5 MB/s', 'progress': 60, 'eta': '00:05:00', 'filesize': '500 MB', 'downloaded': '300 MB', 'status': 'Downloading', 'hash': 'h2'},
        ]
        dm.populate_menu_items()

        # Must have trimmed to 2 items WITHOUT calling destructive reset()
        self.assertEqual(dm.display_list.size(), 2)
        self.assertFalse(dm.display_list.reset_called)

        # Item 0 must have updated properties
        li0 = dm.display_list.getListItem(0)
        self.assertEqual(li0.getProperty('item.info.progress'), '80')
        self.assertEqual(li0.getProperty('item.info.speed'), '1.5 MB/s')

        # Item 1 must have updated label and properties in-place
        li1 = dm.display_list.getListItem(1)
        self.assertEqual(li1.getLabel(), 'Ep2_renamed.mkv')
        self.assertEqual(li1.getProperty('item.info.progress'), '60')

    def test_download_manager_action7_single_dispatch(self):
        """Verify DownloadManager ignores action 7 in onAction, preserving single event dispatch."""
        dm = DownloadManager.__new__(DownloadManager)
        dm.abort = False
        dm.close = MagicMock()

        action = MagicMock()
        action.getId.return_value = 7
        dm.onAction(action)

        self.assertFalse(dm.abort)
        dm.close.assert_not_called()

    def test_playing_next_action7_single_dispatch(self):
        """Verify PlayingNext ignores action 7/100 in onAction and delegates to onClick."""
        pn = PlayingNext.__new__(PlayingNext)
        pn.actioned = False
        pn.close = MagicMock()

        action = MagicMock()
        action.getId.return_value = 7
        pn.onAction(action)
        self.assertFalse(pn.actioned)
        pn.close.assert_not_called()

        action100 = MagicMock()
        action100.getId.return_value = 100
        pn.onAction(action100)
        self.assertFalse(pn.actioned)
        pn.close.assert_not_called()

    def test_skip_intro_action7_single_dispatch(self):
        """Verify SkipIntro ignores action 7/100 in onAction and delegates to onClick."""
        si = SkipIntro.__new__(SkipIntro)
        si.actioned = None
        si.close = MagicMock()

        action = MagicMock()
        action.getId.return_value = 7
        si.onAction(action)
        self.assertIsNone(si.actioned)
        si.close.assert_not_called()

    def test_wlf_auth_action7_single_dispatch(self):
        """Verify WatchlistFlavorAuth ignores action 7 in onAction."""
        wlf = WatchlistFlavorAuth.__new__(WatchlistFlavorAuth)
        wlf.authorized = False
        wlf.close = MagicMock()

        action = MagicMock()
        action.getId.return_value = 7
        wlf.onAction(action)
        self.assertFalse(wlf.authorized)
        wlf.close.assert_not_called()

    def test_still_watching_action7_single_dispatch(self):
        """Verify StillWatchingXML ignores action 7 in onAction and respects closing_actions."""
        sw = StillWatchingXML.__new__(StillWatchingXML)
        sw.closing_actions = (92, 10, 110, 9)
        sw.keep_watching = True
        sw.close = MagicMock()

        action = MagicMock()
        action.getId.return_value = 7
        sw.onAction(action)
        self.assertTrue(sw.keep_watching)
        sw.close.assert_not_called()


if __name__ == '__main__':
    unittest.main()
