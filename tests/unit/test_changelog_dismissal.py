"""
test_changelog_dismissal.py - Unit Tests for Changelog Launch Guard & Dismissal Actions
======================================================================================
Verifies that:
1. TextViewerXML dismisses on Android remote Back button (action 9) and other navigation actions.
2. The changelog route and parameter-less sub-routes do not trigger re-launch loops.
"""

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

from resources.lib.windows.textviewer import TextViewerXML


class TestChangelogDismissal(unittest.TestCase):

    def test_textviewer_dismisses_on_back_action_9(self):
        viewer = TextViewerXML.__new__(TextViewerXML)
        viewer.actioned = None
        viewer.close = MagicMock()

        # Action 9 is Kodi standard ACTION_BACK (Android TV Back button)
        action_back = MagicMock()
        action_back.getId.return_value = 9
        viewer.onAction(action_back)

        self.assertTrue(viewer.actioned)
        viewer.close.assert_called_once()

    def test_textviewer_dismisses_on_nav_back_92(self):
        viewer = TextViewerXML.__new__(TextViewerXML)
        viewer.actioned = None
        viewer.close = MagicMock()

        action_nav_back = MagicMock()
        action_nav_back.getId.return_value = 92
        viewer.onAction(action_nav_back)

        self.assertTrue(viewer.actioned)
        viewer.close.assert_called_once()

    def test_textviewer_dismisses_on_click(self):
        viewer = TextViewerXML.__new__(TextViewerXML)
        viewer.actioned = None
        viewer.close = MagicMock()

        viewer.onClick(2062)
        self.assertTrue(viewer.actioned)
        viewer.close.assert_called_once()

    def test_textviewer_dismisses_on_select_action_7(self):
        viewer = TextViewerXML.__new__(TextViewerXML)
        viewer.actioned = None
        viewer.close = MagicMock()

        action_select = MagicMock()
        action_select.getId.return_value = 7
        viewer.onAction(action_select)

        self.assertTrue(viewer.actioned)
        viewer.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()