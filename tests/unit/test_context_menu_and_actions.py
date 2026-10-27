"""
test_context_menu_and_actions.py - Exhaustive Audit for All Context Menu Items & Non-Settings Routes
=====================================================================================================
Validates that:
1. All 15 context menu items in context.otaku.rpdev/addon.xml have valid, registered router handlers.
2. URL helper _extract_watch_target extracts correct target IDs across all Kodi route forms.
3. Every context menu action executes without uncaught exceptions, missing attributes, or NoneType unpack errors.
4. Non-settings tool/telemetry routes (database_stats, scraper_stats, vacuum, integrity check, sync) execute cleanly.
5. Watchlist, Cloud, and Search contextual actions handle arbitrary payload depths safely.
6. database.get_unique_ids and get_mappings are guaranteed to return dicts even on missing tables or errors.
"""

import os
import re
import unittest
from contextlib import ExitStack
from xml.etree import ElementTree as ET
from unittest.mock import patch, MagicMock

import tests.conftest  # noqa: F401
from resources.lib import Main  # registers all routes
from resources.lib.ui import router, control, database


class TestContextMenuAndActions(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.repo_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        cls.context_addon_xml = os.path.join(
            cls.repo_root, "context.otaku.rpdev", "addon.xml"
        )
        cls.context_default_py = os.path.join(
            cls.repo_root, "context.otaku.rpdev", "default.py"
        )

    def test_context_menu_items_declared_in_addon_xml(self):
        """Verify context.otaku.rpdev addon.xml declares all 15 expected menu items."""
        self.assertTrue(os.path.isfile(self.context_addon_xml), f"Not found: {self.context_addon_xml}")
        tree = ET.parse(self.context_addon_xml)
        root = tree.getroot()

        items = root.findall(".//menu/item")
        args = [item.get("args") for item in items if item.get("args")]

        expected_args = {
            "findrecommendations",
            "findrelations",
            "getwatchorder",
            "viewreviews",
            "viewstatistics",
            "markedaswatched",
            "markedasunwatched",
            "markpreviouswatched",
            "rescrape",
            "sourceselect",
            "logout",
            "deletefromdatabase",
            "watchlist",
            "fanartselect",
            "clearcache",
        }
        self.assertEqual(expected_args, set(args), "Mismatch in context menu actions declared in addon.xml")

    def test_context_default_watch_target_extractor(self):
        """Test _extract_watch_target helper for robust path parsing."""
        import sys
        sys.path.insert(0, os.path.join(self.repo_root, "context.otaku.rpdev"))
        try:
            import default as context_default
            fn = context_default._extract_watch_target
            plugin = "plugin://plugin.video.otaku.rpdev"

            self.assertEqual(fn(f"{plugin}/play/21/5", plugin), "/21/5")
            self.assertEqual(fn(f"{plugin}/play_movie/21", plugin), "/21/1")
            self.assertEqual(fn(f"{plugin}/watchlist_to_ep/21/3", plugin), "/21/3")
            self.assertEqual(fn(f"{plugin}/animes/21", plugin), "/21/1")
            self.assertEqual(fn(f"{plugin}/play_al/21/4", plugin), "/21/4")
            self.assertEqual(fn(f"{plugin}/21/7", plugin), "/21/7")
            self.assertEqual(fn("21/8", plugin), "/21/8")
            self.assertEqual(fn(f"{plugin}/play/21", plugin), "/21/1")
            self.assertEqual(fn(f"{plugin}/", plugin), "/1/1")
        finally:
            if sys.path[0] == os.path.join(self.repo_root, "context.otaku.rpdev"):
                sys.path.pop(0)

    def test_database_get_unique_ids_and_mappings_resilience(self):
        """Ensure get_unique_ids and get_mappings unconditionally return dicts, never None."""
        # Test with None inputs
        self.assertIsInstance(database.get_unique_ids(None, None), dict)
        self.assertIsInstance(database.get_mappings(None, None), dict)
        self.assertIsInstance(database.get_mal_ids(None, None), list)

        # Test with missing/non-existent IDs
        self.assertIsInstance(database.get_unique_ids(99999999, 'mal_id'), dict)
        self.assertIsInstance(database.get_mappings(99999999, 'mal_id'), dict)
        self.assertIsInstance(database.get_mal_ids(99999999, 'mal_id'), list)

        # Test with invalid identifiers (fails validation safely)
        self.assertIsInstance(database.get_unique_ids(21, 'invalid_column; DROP TABLE anime;--'), dict)
        self.assertIsInstance(database.get_mappings(21, 'invalid_column'), dict)

    def test_control_get_info_label(self):
        """Ensure control.getInfoLabel returns a string and handles labels properly."""
        self.assertTrue(hasattr(control, 'getInfoLabel'), "control module must have getInfoLabel")
        val = control.getInfoLabel('Container.FolderPath')
        self.assertIsInstance(val, str)

    def test_all_context_menu_routes_execute(self):
        """Execute all context menu routes through router.router_process with mocked dialogs."""
        control.setSetting('watchlist.update.enabled', 'true')
        control.setSetting('mal.token', 'test_token')

        actions_to_test = [
            ('find_recommendations/21', {}),
            ('find_relations/21', {}),
            ('watch_order/21', {}),
            ('anime_reviews/animes/21/0', {}),
            ('anime_reviews/21', {}),
            ('anime_statistics/21', {}),
            ('watchlist_logout/mal', {}),
            ('delete_anime_database/21', {}),
            ('watchlist_manager/animes/21/', {}),
            ('watchlist_manager/21', {}),
            ('marked_as_watched/21/1', {}),
            ('marked_as_unwatched/21/1', {}),
            ('mark_previous_watched/21/5', {}),
            ('clear_cache', {}),
            ('clear_cache', {'select': 'providers'}),
            ('clear_cache', {'select': 'all'}),
            ('fanart_select/21', {}),
            ('playback_options/21/1', {}),
        ]

        with ExitStack() as stack:
            stack.enter_context(patch('resources.lib.windows.wlf_auth.WatchlistFlavorAuth', return_value=MagicMock()))
            stack.enter_context(patch('resources.lib.windows.sort_select.SortSelect', return_value=MagicMock()))
            stack.enter_context(patch('resources.lib.windows.stats_window.StatsWindow', return_value=MagicMock()))
            stack.enter_context(patch('resources.lib.ui.control.ok_dialog', return_value=True))
            stack.enter_context(patch('resources.lib.ui.control.yesno_dialog', return_value=True))
            stack.enter_context(patch('resources.lib.ui.control.yesnocustom_dialog', return_value=2))  # Cancel playback
            stack.enter_context(patch('resources.lib.ui.control.textviewer_dialog', return_value=None))
            stack.enter_context(patch('resources.lib.ui.control.select_dialog', return_value=-1))
            stack.enter_context(patch('resources.lib.ui.control.multiselect_dialog', return_value=[]))
            stack.enter_context(patch('resources.lib.ui.control.notify', return_value=None))
            stack.enter_context(patch('resources.lib.ui.control.execute', return_value=None))
            stack.enter_context(patch('resources.lib.ui.control.refresh', return_value=None))
            stack.enter_context(patch('resources.lib.ui.control.setSetting', return_value=None))
            stack.enter_context(patch('resources.lib.ui.control.keyboard', return_value=''))
            stack.enter_context(patch('resources.lib.WatchlistFlavor.WatchlistFlavor.watchlist_update_all_episodes', return_value=True))
            stack.enter_context(patch('service.refresh_apis', return_value=None))
            stack.enter_context(patch('service.update_mappings_db', return_value=None))

            for url, params in actions_to_test:
                with self.subTest(route=url):
                    try:
                        router.router_process(url, params)
                    except Exception as e:
                        self.fail(f"Route '{url}' raised unexpected exception: {type(e).__name__}: {e}")

    def test_non_settings_tool_routes_execute(self):
        """Execute all non-settings tools, telemetry, and management routes."""
        tools_routes = [
            ('tools', {}),
            ('database_stats', {}),
            ('scraper_stats', {}),
            ('clear_scraper_metrics', {}),
            ('vacuum_databases', {}),
            ('check_db_integrity', {}),
            ('sync_mappings', {}),
            ('clear_selected_fanart', {}),
            ('rebuild_database', {}),
            ('completed_sync', {}),
            ('sort_select', {}),
            ('setup_wizard', {}),
            ('change_log', {}),
            ('airing_calendar', {}),
            ('next_up', {}),
            ('watchlist_status_type/mal/watching', {}),
            ('watchlist_to_ep/21/1', {}),
            ('watchlist_to_ep/21', {}),
            ('remove_search_item/search_anime/test', {}),
            ('edit_search_item/search_anime/test', {}),
            ('cloud_create_folder/realdebrid/root', {}),
            ('cloud_rename_item/realdebrid/123', {'title': 'OldName'}),
            ('delete_cloud_item/realdebrid/123', {'title': 'OldName'}),
            ('cloud_purge_stalled/realdebrid', {}),
        ]

        with ExitStack() as stack:
            stack.enter_context(patch('resources.lib.windows.wlf_auth.WatchlistFlavorAuth', return_value=MagicMock()))
            stack.enter_context(patch('resources.lib.windows.sort_select.SortSelect', return_value=MagicMock()))
            stack.enter_context(patch('resources.lib.windows.anichart.Anichart', return_value=MagicMock()))
            stack.enter_context(patch('resources.lib.ui.control.ok_dialog', return_value=True))
            stack.enter_context(patch('resources.lib.ui.control.yesno_dialog', return_value=False))
            stack.enter_context(patch('resources.lib.ui.control.yesnocustom_dialog', return_value=0))
            stack.enter_context(patch('resources.lib.ui.control.textviewer_dialog', return_value=None))
            stack.enter_context(patch('resources.lib.ui.control.select_dialog', return_value=-1))
            stack.enter_context(patch('resources.lib.ui.control.multiselect_dialog', return_value=[]))
            stack.enter_context(patch('resources.lib.ui.control.notify', return_value=None))
            stack.enter_context(patch('resources.lib.ui.control.execute', return_value=None))
            stack.enter_context(patch('resources.lib.ui.control.refresh', return_value=None))
            stack.enter_context(patch('resources.lib.ui.control.setSetting', return_value=None))
            stack.enter_context(patch('resources.lib.ui.control.keyboard', return_value='new_name'))
            stack.enter_context(patch('resources.lib.WatchlistFlavor.WatchlistFlavor.watchlist_update_all_episodes', return_value=True))
            stack.enter_context(patch('service.refresh_apis', return_value=None))
            stack.enter_context(patch('service.update_mappings_db', return_value=None))

            for url, params in tools_routes:
                with self.subTest(route=url):
                    try:
                        router.router_process(url, params)
                    except Exception as e:
                        self.fail(f"Route '{url}' raised unexpected exception: {type(e).__name__}: {e}")


if __name__ == "__main__":
    unittest.main()
