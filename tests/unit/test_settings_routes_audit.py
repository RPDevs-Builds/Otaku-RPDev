"""
test_settings_routes_audit.py - Exhaustive Audit for All Settings Routes
========================================================================
Validates that every single action button and route link declared in
resources/settings.xml has a corresponding, valid, and callable handler in
router.ROUTES, preventing runtime AttributeErrors or dead buttons.
"""

import os
import re
import unittest
from contextlib import ExitStack
from xml.etree import ElementTree as ET
from urllib.parse import urlparse, parse_qsl
from unittest.mock import patch, MagicMock

import tests.conftest  # noqa: F401
from resources.lib import Main  # registers all routes into router.ROUTES
from resources.lib.ui import router, control, database


class TestSettingsRoutesAudit(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        addon_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "plugin.video.otaku.rpdev")
        )
        cls.settings_xml_path = os.path.join(addon_dir, "resources", "settings.xml")

    def test_settings_xml_exists(self):
        self.assertTrue(os.path.isfile(self.settings_xml_path), f"settings.xml not found at {self.settings_xml_path}")

    def test_all_settings_action_routes_registered_and_executable(self):
        """
        Extract every plugin URL from settings.xml and verify it resolves to a registered handler.
        Then safely execute it to guarantee no AttributeError or syntax failure.
        """
        tree = ET.parse(self.settings_xml_path)
        root = tree.getroot()

        action_pattern = re.compile(r'plugin://plugin\.video\.otaku\.rpdev/([^"\'\)\s]+)')
        routes_found = set()

        for elem in root.iter():
            text = elem.text or ""
            for m in action_pattern.findall(text):
                routes_found.add(m)
            for attr_val in elem.attrib.values():
                for m in action_pattern.findall(attr_val):
                    routes_found.add(m)

        self.assertGreater(len(routes_found), 0, "No plugin routes found in settings.xml")

        mock_auth = MagicMock()
        mock_auth.auth.return_value = None
        mock_auth.refresh.return_value = None

        with ExitStack() as stack:
            stack.enter_context(patch("service.toggle_reuselanguageinvoker", return_value=None))
            stack.enter_context(patch("resources.lib.windows.wlf_auth.WatchlistFlavorAuth", return_value=MagicMock()))
            stack.enter_context(patch("resources.lib.ui.control.ok_dialog", return_value=True))
            stack.enter_context(patch("resources.lib.ui.control.yesno_dialog", return_value=False))
            stack.enter_context(patch("resources.lib.ui.control.yesnocustom_dialog", return_value=0))
            stack.enter_context(patch("resources.lib.ui.control.textviewer_dialog", return_value=None))
            stack.enter_context(patch("resources.lib.ui.control.select_dialog", return_value=-1))
            stack.enter_context(patch("resources.lib.ui.control.multiselect_dialog", return_value=[]))
            stack.enter_context(patch("resources.lib.ui.control.notify", return_value=None))
            stack.enter_context(patch("resources.lib.ui.control.execute", return_value=None))
            stack.enter_context(patch("resources.lib.ui.control.refresh", return_value=None))
            stack.enter_context(patch("resources.lib.ui.control.setSetting", return_value=None))
            stack.enter_context(patch("service.refresh_apis", return_value=None))
            stack.enter_context(patch("service.update_mappings_db", return_value=None))
            stack.enter_context(patch("resources.lib.debrid.real_debrid.RealDebrid", return_value=mock_auth))
            stack.enter_context(patch("resources.lib.debrid.premiumize.Premiumize", return_value=mock_auth))
            stack.enter_context(patch("resources.lib.debrid.all_debrid.AllDebrid", return_value=mock_auth))
            stack.enter_context(patch("resources.lib.debrid.debrid_link.DebridLink", return_value=mock_auth))
            stack.enter_context(patch("resources.lib.debrid.torbox.TorBox", return_value=mock_auth))
            stack.enter_context(patch("resources.lib.debrid.easydebrid.EasyDebrid", return_value=mock_auth))
            stack.enter_context(patch("resources.lib.debrid.easynews.Easynews", return_value=mock_auth))

            failed_routes = []
            unmatched_routes = []

            for raw_route in sorted(routes_found):
                parsed = urlparse(raw_route)
                path = parsed.path
                params = dict(parse_qsl(parsed.query)) if parsed.query else {}

                matched = any(
                    path == r.path or (r.wildcard and path.startswith(r.path))
                    for r in router.ROUTES
                )

                if not matched:
                    unmatched_routes.append(raw_route)
                    continue

                try:
                    router.router_process(path, params)
                except Exception as e:
                    failed_routes.append((raw_route, str(e)))

            self.assertEqual(
                unmatched_routes, [],
                f"Settings.xml routes missing handler in router: {unmatched_routes}"
            )
            self.assertEqual(
                failed_routes, [],
                f"Settings.xml routes threw unhandled exceptions: {failed_routes}"
            )


if __name__ == '__main__':
    unittest.main()
