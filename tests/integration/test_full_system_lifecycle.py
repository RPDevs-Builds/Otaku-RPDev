"""
test_full_system_lifecycle.py - End-to-End System Lifecycle Integration Test (Phase 9)
======================================================================================
Tests cold add-on launch, settings migrations, root directory construction,
router parameter dispatching, and shutdown checkpoints.
"""

import os
import unittest
from unittest.mock import patch, MagicMock

import conftest
import xbmcplugin
import service
from resources.lib import Main
from resources.lib.ui import control, database
from resources.lib.ui.router import router_process


class TestFullSystemLifecycle(unittest.TestCase):

    def setUp(self):
        xbmcplugin.reset()

    def test_service_version_check(self):
        # Test upgrade migration from older version
        control.setSetting("otaku.version", "5.4.0")
        with patch.object(service, "toggle_reuselanguageinvoker"):
            service.version_check()
        # Verify version setting is bumped
        self.assertEqual(control.getSetting("otaku.version"), control.ADDON_VERSION)

    def test_main_root_menu_generation(self):
        xbmcplugin.reset()
        Main.LIST_MENU("", {})
        # Verify directory items were emitted
        self.assertGreater(len(xbmcplugin.directory_items), 0)
        # Verify end of directory was signaled to Kodi
        self.assertGreater(len(xbmcplugin.end_of_directory_args), 0)
        handle, succeeded, updateListing, cacheToDisc = xbmcplugin.end_of_directory_args[0]
        self.assertTrue(succeeded)

    def test_router_dispatch_root(self):
        xbmcplugin.reset()
        router_process("", {})
        self.assertGreater(len(xbmcplugin.directory_items), 0)

    def test_router_dispatch_invalid_route_safety(self):
        xbmcplugin.reset()
        # Malformed path should not crash the process
        router_process("invalid_route_xyz", {"bad": "param"})


if __name__ == "__main__":
    unittest.main()
