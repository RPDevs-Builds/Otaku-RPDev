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
from unittest.mock import patch, MagicMock

from resources.lib.ui import control, router
from resources.lib.windows import menu_order
from resources.lib import Main


class TestMenuOrder(unittest.TestCase):

    def setUp(self):
        control.clearSettingsCache()
        control.clearGlobalProp('otaku.menu.needs_refresh')

    def tearDown(self):
        control.clearSettingsCache()
        control.clearGlobalProp('otaku.menu.needs_refresh')

    def test_default_menu_items_structure(self):
        """Verify DEFAULT_MENU_ITEMS contains 24 distinct items and valid metadata."""
        self.assertEqual(len(menu_order.DEFAULT_MENU_ITEMS), 24)
        self.assertEqual(len(menu_order.DEFAULT_ORDER), 24)
        self.assertEqual(len(set(menu_order.DEFAULT_ORDER)), 24)

        for item_id, string_id, default_en, icon in menu_order.DEFAULT_MENU_ITEMS:
            self.assertIn(item_id, menu_order.MENU_ITEM_METADATA)
            self.assertIsInstance(string_id, int)
            self.assertIsInstance(default_en, bool)
            self.assertTrue(icon.endswith('.png'))

    def test_get_item_label_unnumbered(self):
        """Test resolving clean unnumbered localized string for menu items."""
        with patch('resources.lib.ui.control.lang', side_effect=lambda x: f"Label_{x}"):
            lbl = menu_order.get_item_label('watchlist')
            self.assertEqual(lbl, "Label_30162")
            # Verify no numbers or indices prefixed
            self.assertFalse(lbl.startswith(('0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '[')))

            lbl_custom = menu_order.get_item_label('airing_calendar')
            self.assertEqual(lbl_custom, "Label_30001")

            lbl_fallback = menu_order.get_item_label('custom_addon_tool')
            self.assertEqual(lbl_fallback, "Custom Addon Tool")

    def test_load_menu_order_defaults(self):
        """Test default loading when no settings exist."""
        with patch('resources.lib.ui.control.getSetting', return_value=''), \
             patch('resources.lib.ui.control.getStringList', return_value=[]):
            ordered_ids, enabled_set = menu_order.load_menu_order()
            self.assertEqual(ordered_ids, menu_order.DEFAULT_ORDER)
            self.assertEqual(enabled_set, set(menu_order.DEFAULT_ENABLED))

    def test_load_menu_order_legacy_watchlist_inclusion(self):
        """Test backward compatibility: watchlist auto-added if order unset and config lacks watchlist."""
        with patch('resources.lib.ui.control.getSetting', return_value=''), \
             patch('resources.lib.ui.control.getStringList', return_value=['last_watched', 'trending']):
            ordered_ids, enabled_set = menu_order.load_menu_order()
            self.assertEqual(ordered_ids, menu_order.DEFAULT_ORDER)
            self.assertIn('watchlist', enabled_set)
            self.assertIn('last_watched', enabled_set)
            self.assertIn('trending', enabled_set)

    def test_load_menu_order_custom(self):
        """Test loading custom order with missing defaults appended."""
        custom_order_str = 'search,trending,tools'
        custom_config = ['search', 'tools']
        with patch('resources.lib.ui.control.getSetting', return_value=custom_order_str), \
             patch('resources.lib.ui.control.getStringList', return_value=custom_config):
            ordered_ids, enabled_set = menu_order.load_menu_order()
            self.assertEqual(ordered_ids[:3], ['search', 'trending', 'tools'])
            self.assertEqual(len(ordered_ids), 24)
            self.assertEqual(enabled_set, {'search', 'tools'})

    def test_save_menu_order(self):
        """Test saving updates settings, sets refresh flag, and triggers refresh."""
        ordered_ids = ['search', 'watchlist', 'trending', 'tools']
        enabled_set = {'search', 'tools'}

        with patch('resources.lib.ui.control.setSetting') as mock_set_setting, \
             patch('resources.lib.ui.control.setStringList') as mock_set_string_list, \
             patch('resources.lib.ui.control.setGlobalProp') as mock_set_prop, \
             patch('resources.lib.ui.control.clearSettingsCache') as mock_clear, \
             patch('resources.lib.ui.control.refresh') as mock_refresh:

            menu_order.save_menu_order(ordered_ids, enabled_set)

            mock_set_setting.assert_called_once_with('menu.mainmenu.order', 'search,watchlist,trending,tools')
            mock_set_string_list.assert_called_once_with('menu.mainmenu.config', ['search', 'tools'])
            mock_set_prop.assert_called_once_with('otaku.menu.needs_refresh', 'true')
            mock_clear.assert_called_once()
            mock_refresh.assert_called_once()

    def test_move_item(self):
        """Test move_item boundary and displacement logic."""
        items = ['A', 'B', 'C', 'D', 'E']

        # Move Up (C from index 2 to index 1)
        new_idx = menu_order.move_item(items, 2, 1)
        self.assertEqual(new_idx, 1)
        self.assertEqual(items, ['A', 'C', 'B', 'D', 'E'])

        # Move Down (C from index 1 to index 3)
        new_idx = menu_order.move_item(items, 1, 3)
        self.assertEqual(new_idx, 3)
        self.assertEqual(items, ['A', 'B', 'D', 'C', 'E'])

        # Move to Top (C to index 0)
        new_idx = menu_order.move_item(items, 3, 0)
        self.assertEqual(new_idx, 0)
        self.assertEqual(items, ['C', 'A', 'B', 'D', 'E'])

        # Move to Bottom (C to index 4)
        new_idx = menu_order.move_item(items, 0, 4)
        self.assertEqual(new_idx, 4)
        self.assertEqual(items, ['A', 'B', 'D', 'E', 'C'])

        # Out of bounds clamping
        new_idx = menu_order.move_item(items, 4, 100)
        self.assertEqual(new_idx, 4)
        new_idx = menu_order.move_item(items, 4, -10)
        self.assertEqual(new_idx, 0)
        self.assertEqual(items, ['C', 'A', 'B', 'D', 'E'])

    def test_collect_category_menu_items_respects_custom_order(self):
        """Test that _collect_category_menu_items strictly yields items in user-configured order."""
        custom_order = 'search,tools,trending,airing_calendar,watchlist'
        enabled_config = ['search', 'tools', 'watchlist']  # trending and calendar disabled

        mock_main_items = [
            ('Calendar', 'airing_calendar', 'cal.png', {}),
            ('Trending', 'trending', 'trend.png', {}),
            ('Search', 'search', 'search.png', {}),
            ('Tools', 'tools', 'tools.png', {}),
        ]
        mock_watchlist = [("My AniList", "watchlist/anilist", "al.png", {})]

        with patch('resources.lib.ui.control.getSetting', return_value=custom_order), \
             patch('resources.lib.ui.control.getStringList', return_value=enabled_config), \
             patch('resources.lib.Main.get_menu_items', return_value=mock_main_items), \
             patch('resources.lib.Main.add_watchlist', return_value=mock_watchlist):

            result = Main._collect_category_menu_items('main', 'menu.mainmenu.config', '')

            # Expected order: search, tools, watchlist
            result_keys = [itm[1] for itm in result]
            self.assertEqual(result_keys, ['search', 'tools', 'watchlist/anilist'])

    def test_collect_category_menu_items_legacy_fallback(self):
        """Test legacy fallback when menu.mainmenu.order is empty."""
        enabled_config = ['airing_calendar', 'trending']
        mock_main_items = [
            ('Calendar', 'airing_calendar', 'cal.png', {}),
            ('Trending', 'trending', 'trend.png', {}),
            ('Search', 'search', 'search.png', {}),
        ]
        mock_watchlist = [("My AniList", "watchlist/anilist", "al.png", {})]

        with patch('resources.lib.ui.control.getSetting', return_value=''), \
             patch('resources.lib.ui.control.getStringList', return_value=enabled_config), \
             patch('resources.lib.Main.get_menu_items', return_value=mock_main_items), \
             patch('resources.lib.Main.add_watchlist', return_value=mock_watchlist), \
             patch('resources.lib.Main.add_last_watched', return_value=[]), \
             patch('resources.lib.Main.add_watch_history', return_value=[]), \
             patch('resources.lib.Main.add_next_up', return_value=[]), \
             patch('resources.lib.Main.add_my_cloud', return_value=[]):

            result = Main._collect_category_menu_items('main', 'menu.mainmenu.config', '')
            # Watchlist prepended at top in legacy mode
            self.assertEqual(result[0][1], 'watchlist/anilist')
            self.assertEqual(result[1][1], 'airing_calendar')
            self.assertEqual(result[2][1], 'trending')

    def test_tools_menu_contains_menu_order(self):
        """Verify _tools_menu contains the menu_order action entry."""
        tools = Main._tools_menu()
        tool_paths = [t[1] for t in tools]
        self.assertIn('menu_order', tool_paths)

    def test_route_menu_order_registered(self):
        """Verify route @Route('menu_order') is registered and callable."""
        registered_paths = [r.path for r in router.ROUTES]
        self.assertIn('menu_order', registered_paths)
        route_obj = next(r for r in router.ROUTES if r.path == 'menu_order')
        self.assertTrue(callable(route_obj.func))

    def test_menu_order_dialog_actions_and_buttons(self):
        """Test MenuOrderDialog button handlers (Move Up, Down, Top, Bottom, Toggle, Reset, Save)."""
        dlg = menu_order.MenuOrderDialog("menu_order.xml", control.ADDON_PATH)
        dlg.onInit()

        # Initial state
        self.assertFalse(dlg.modified)
        first_item = dlg.ordered_ids[0]
        second_item = dlg.ordered_ids[1]

        # 1. Select index 1 and Move Up (Button 3001)
        dlg.list_control.selectItem(1)
        dlg.onClick(3001)
        self.assertTrue(dlg.modified)
        self.assertEqual(dlg.ordered_ids[0], second_item)
        self.assertEqual(dlg.ordered_ids[1], first_item)

        # 2. Select index 0 and Move Down (Button 3002)
        dlg.list_control.selectItem(0)
        dlg.onClick(3002)
        self.assertEqual(dlg.ordered_ids[0], first_item)
        self.assertEqual(dlg.ordered_ids[1], second_item)

        # 3. Select index 5 and Move to Top (Button 3003)
        target_item = dlg.ordered_ids[5]
        dlg.list_control.selectItem(5)
        dlg.onClick(3003)
        self.assertEqual(dlg.ordered_ids[0], target_item)

        # 4. Select index 0 and Move to Bottom (Button 3004)
        bottom_item = dlg.ordered_ids[0]
        dlg.list_control.selectItem(0)
        dlg.onClick(3004)
        self.assertEqual(dlg.ordered_ids[-1], bottom_item)

        # 5. Toggle Visibility (Button 3005)
        dlg.list_control.selectItem(0)
        curr_id = dlg.ordered_ids[0]
        was_enabled = curr_id in dlg.enabled_set
        dlg.onClick(3005)
        self.assertEqual(curr_id in dlg.enabled_set, not was_enabled)
        # Toggle back via list click (Control ID 1000)
        dlg.onClick(1000)
        self.assertEqual(curr_id in dlg.enabled_set, was_enabled)

        # 6. Reset to Defaults (Button 3006)
        with patch('resources.lib.ui.control.yesno_dialog', return_value=True):
            dlg.onClick(3006)
            self.assertEqual(dlg.ordered_ids, menu_order.DEFAULT_ORDER)
            self.assertEqual(dlg.enabled_set, set(menu_order.DEFAULT_ENABLED))

        # 7. Save & Apply (Button 3007)
        with patch('resources.lib.windows.menu_order.save_menu_order') as mock_save, \
             patch('resources.lib.ui.control.notify') as mock_notify:
            dlg.onClick(3007)
            mock_save.assert_called_once_with(dlg.ordered_ids, dlg.enabled_set)
            mock_notify.assert_called_once()
            self.assertTrue(dlg._win_closed)

    def test_toggle_visibility_in_place_no_reset(self):
        """Verify toggle_visibility mutates ListItem in-place and never calls reset()."""
        dlg = menu_order.MenuOrderDialog("menu_order.xml", control.ADDON_PATH)
        dlg.onInit()

        # Select index 3
        dlg.list_control.selectItem(3)
        target_id = dlg.ordered_ids[3]
        initial_order = list(dlg.ordered_ids)

        with patch.object(dlg.list_control, 'reset') as mock_reset:
            # 1. Toggle visibility on index 3
            dlg.toggle_visibility(3)
            # Must NOT call reset() on the list
            mock_reset.assert_not_called()

            # Item order must remain 100% identical
            self.assertEqual(dlg.ordered_ids, initial_order)

            # Property on ListItem must be updated in-place
            li = dlg.list_control.getListItem(3)
            self.assertIsNotNone(li)
            badge = li.getProperty('status_badge')
            is_en = target_id in dlg.enabled_set
            expected_badge = '[COLOR deepskyblue][✓][/COLOR]' if is_en else '[COLOR grey][  ][/COLOR]'
            self.assertEqual(badge, expected_badge)

    def test_clicking_list_item_only_toggles_and_never_moves(self):
        """Verify clicking on a list item (Control ID 1000) only toggles visibility and NEVER moves the item."""
        dlg = menu_order.MenuOrderDialog("menu_order.xml", control.ADDON_PATH)
        dlg.onInit()

        # Select an item that is NOT at the top (e.g., index 4)
        dlg.list_control.selectItem(4)
        item_at_4 = dlg.ordered_ids[4]
        initial_order = list(dlg.ordered_ids)
        was_enabled = item_at_4 in dlg.enabled_set

        # Click the list item directly (Control 1000)
        dlg.onClick(1000)

        # Order must remain completely unchanged
        self.assertEqual(dlg.ordered_ids, initial_order)
        self.assertEqual(dlg.ordered_ids[4], item_at_4)

        # Visibility must be cleanly flipped
        self.assertEqual(item_at_4 in dlg.enabled_set, not was_enabled)

        # Click again to toggle back
        dlg.onClick(1000)
        self.assertEqual(dlg.ordered_ids, initial_order)
        self.assertEqual(item_at_4 in dlg.enabled_set, was_enabled)

    def test_onaction_back_and_cancel_handling(self):
        """Verify onAction properly routes back actions (9, 10, 92, 110, 216) to cancel_and_close."""
        dlg = menu_order.MenuOrderDialog("menu_order.xml", control.ADDON_PATH)
        dlg.onInit()

        mock_action = MagicMock()
        with patch.object(dlg, 'cancel_and_close') as mock_cancel:
            for action_code in [9, 10, 92, 110, 216]:
                mock_action.getId.return_value = action_code
                dlg.onAction(mock_action)
            self.assertEqual(mock_cancel.call_count, 5)

        # Action 7 (Enter) is not intercepted by onAction, avoiding duplicate event dispatch
        with patch.object(dlg, 'onClick') as mock_click, \
             patch.object(dlg, 'toggle_visibility') as mock_toggle:
            mock_action.getId.return_value = 7
            dlg.onAction(mock_action)
            mock_click.assert_not_called()
            mock_toggle.assert_not_called()

    def test_open_menu_order_dialog_lifecycle(self):
        """Test open_menu_order_dialog instantiates MenuOrderDialog and executes doModal."""
        with patch.object(menu_order.MenuOrderDialog, 'doModal') as mock_modal:
            menu_order.open_menu_order_dialog()
            mock_modal.assert_called_once()


if __name__ == '__main__':
    unittest.main()
