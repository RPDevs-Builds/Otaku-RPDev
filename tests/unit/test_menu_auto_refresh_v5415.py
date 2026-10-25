import unittest
from unittest.mock import patch, MagicMock

import tests.conftest  # noqa: F401
from resources.lib.ui import control
import service
from resources.lib import Main


class TestMenuAutoRefreshV5415(unittest.TestCase):

    def setUp(self):
        control.clearSettingsCache()
        control.clearGlobalProp('otaku.menu.needs_refresh')

    def tearDown(self):
        control.clearSettingsCache()
        control.clearGlobalProp('otaku.menu.needs_refresh')

    # 1. Menu Settings Snapshot
    def test_get_menu_settings_snapshot_contains_all_menu_keys(self):
        snapshot = service._get_menu_settings_snapshot()
        self.assertIsInstance(snapshot, dict)
        self.assertIn('menu.mainmenu.config', snapshot)
        self.assertIn('menu.submenu.config', snapshot)
        self.assertIn('menu.genres.config', snapshot)
        self.assertIn('movie.mainmenu.config', snapshot)
        self.assertIn('tv_show.mainmenu.config', snapshot)

    # 2. onSettingsChanged: Ignored for non-menu settings
    @patch('service._get_menu_settings_snapshot')
    @patch('resources.lib.ui.control.refresh')
    @patch('resources.lib.ui.control.is_addon_visible', return_value=True)
    def test_on_settings_changed_ignores_non_menu_settings(self, mock_visible, mock_refresh, mock_snapshot):
        # Initial snapshot
        initial_snap = {'menu.mainmenu.config': ['last_watched', 'tools']}
        mock_snapshot.return_value = initial_snap

        monitor = service.Monitor()
        mock_refresh.reset_mock()

        # Simulate a setting change event where menu settings did NOT change
        # (e.g. subtitle, debrid token, or player option changed)
        mock_snapshot.return_value = initial_snap
        monitor.onSettingsChanged()

        # Must NOT trigger container refresh
        mock_refresh.assert_not_called()
        self.assertNotEqual(control.getGlobalProp('otaku.menu.needs_refresh'), 'true')

    # 3. onSettingsChanged: Triggers refresh ONLY when menu settings change
    @patch('service._get_menu_settings_snapshot')
    @patch('resources.lib.ui.control.refresh')
    @patch('resources.lib.ui.control.is_addon_visible', return_value=True)
    @patch('resources.lib.ui.control.clearSettingsCache')
    def test_on_settings_changed_refreshes_on_menu_setting_change(self, mock_clear_cache, mock_visible, mock_refresh, mock_snapshot):
        # Initial snapshot
        mock_snapshot.return_value = {'menu.mainmenu.config': ['last_watched', 'tools']}
        monitor = service.Monitor()
        mock_refresh.reset_mock()

        # Simulate user changing main menu items (e.g. adding next_up)
        mock_snapshot.return_value = {'menu.mainmenu.config': ['last_watched', 'next_up', 'tools']}
        monitor.onSettingsChanged()

        # Must trigger container refresh and set refresh flag
        mock_refresh.assert_called_once()
        self.assertEqual(control.getGlobalProp('otaku.menu.needs_refresh'), 'true')
        mock_clear_cache.assert_called()

    # 4. cacheToDisc=False on Category Main Menus and Submenus
    @patch('resources.lib.ui.control.draw_items')
    @patch('resources.lib.Main._collect_category_menu_items', return_value=[])
    @patch('resources.lib.Main._finalize_menu_list_items', return_value=[])
    def test_draw_category_main_menu_disables_cache_to_disc(self, mock_finalize, mock_collect, mock_draw):
        Main._draw_category_main_menu('main', 'menu.mainmenu.config', '', 'test log')
        mock_draw.assert_called_once()
        _, kwargs = mock_draw.call_args
        self.assertIn('cacheToDisc', kwargs)
        self.assertFalse(kwargs['cacheToDisc'])

    @patch('resources.lib.ui.control.draw_items')
    @patch('resources.lib.Main.get_menu_items', return_value=[])
    def test_draw_filtered_submenu_disables_cache_to_disc(self, mock_get_items, mock_draw):
        Main._draw_filtered_submenu('trending', 'menu.submenu.config')
        mock_draw.assert_called_once()
        _, kwargs = mock_draw.call_args
        self.assertIn('cacheToDisc', kwargs)
        self.assertFalse(kwargs['cacheToDisc'])

    # 5. _maybe_refresh_main_menu clears cache
    @patch('resources.lib.ui.control.clearSettingsCache')
    def test_maybe_refresh_main_menu_clears_cache_when_flag_present(self, mock_clear_cache):
        control.setGlobalProp('otaku.menu.needs_refresh', 'true')
        Main._maybe_refresh_main_menu('Testing menu refresh')
        self.assertFalse(control.getGlobalProp('otaku.menu.needs_refresh'))
        mock_clear_cache.assert_called_once()


if __name__ == '__main__':
    unittest.main()
