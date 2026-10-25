# -*- coding: utf-8 -*-
import unittest
from unittest.mock import MagicMock, patch

from tests import conftest  # Ensure mock harness is active
from resources.lib.ui import control, database
from resources.lib.windows.clear_cache import ClearCacheDialog, show_clear_cache_dialog
from resources.lib.routes import tools


class TestClearCacheDialog(unittest.TestCase):

    def setUp(self):
        database._init_cache_table()

    def test_database_cache_clear_providers_selective(self):
        """Verify cache_clear_providers removes provider cache but preserves metadata cache."""
        with database.SQL(control.cacheFile) as cur:
            cur.execute("INSERT OR REPLACE INTO cache VALUES ('season_pack_1001', 'data1', 9999999999)")
            cur.execute("INSERT OR REPLACE INTO cache VALUES ('nyaa_torrent_search', 'data2', 9999999999)")
            cur.execute("INSERT OR REPLACE INTO cache VALUES ('animepahe_embed_sources', 'data3', 9999999999)")
            cur.execute("INSERT OR REPLACE INTO cache VALUES ('anilist_metadata_show', 'keep_me', 9999999999)")
            cur.connection.commit()

        database.cache_clear_providers()

        with database.SQL(control.cacheFile) as cur:
            cur.execute("SELECT key FROM cache")
            remaining = [row['key'] for row in cur.fetchall()]

        self.assertNotIn('season_pack_1001', remaining)
        self.assertNotIn('nyaa_torrent_search', remaining)
        self.assertNotIn('animepahe_embed_sources', remaining)
        self.assertIn('anilist_metadata_show', remaining)

    def test_database_cache_clear_metadata_selective(self):
        """Verify cache_clear_metadata removes external API metadata but preserves provider cache."""
        with database.SQL(control.cacheFile) as cur:
            cur.execute("INSERT OR REPLACE INTO cache VALUES ('anilist_query_top', 'meta1', 9999999999)")
            cur.execute("INSERT OR REPLACE INTO cache VALUES ('mal_season_spring', 'meta2', 9999999999)")
            cur.execute("INSERT OR REPLACE INTO cache VALUES ('nyaa_scraper_keep', 'keep_prov', 9999999999)")
            cur.connection.commit()

        database.cache_clear_metadata()

        with database.SQL(control.cacheFile) as cur:
            cur.execute("SELECT key FROM cache")
            remaining = [row['key'] for row in cur.fetchall()]

        self.assertNotIn('anilist_query_top', remaining)
        self.assertNotIn('mal_season_spring', remaining)
        self.assertIn('nyaa_scraper_keep', remaining)

    def test_dialog_init_and_default_provider_selection(self):
        """Verify ClearCacheDialog initializes with 2 items and defaults to Provider Cache."""
        dialog = ClearCacheDialog("clear_cache.xml", control.ADDON_PATH)
        dialog.onInit()

        self.assertEqual(dialog.list_control.size(), 2)
        self.assertEqual(dialog.list_control.getSelectedPosition(), 0)
        self.assertEqual(dialog.list_control.getListItem(0).getProperty('action'), 'providers')
        self.assertEqual(dialog.list_control.getListItem(1).getProperty('action'), 'all')
        self.assertIn('Provider Cache', dialog.getProperty('cache.option_title'))

    def test_dialog_click_cancel_button(self):
        """Verify clicking control 3001 sets selection to cancel."""
        dialog = ClearCacheDialog("clear_cache.xml", control.ADDON_PATH)
        dialog.onInit()
        dialog.onClick(3001)

        self.assertEqual(dialog.selected, 'cancel')

    def test_dialog_click_list_selection(self):
        """Verify clicking control 1000 retrieves active selected item."""
        dialog = ClearCacheDialog("clear_cache.xml", control.ADDON_PATH)
        dialog.onInit()
        dialog.list_control.selectItem(1)
        dialog.onClick(1000)

        self.assertEqual(dialog.selected, 'all')

    def test_dialog_on_action_escape_and_back(self):
        """Verify Back/Escape action triggers cancellation."""
        dialog = ClearCacheDialog("clear_cache.xml", control.ADDON_PATH)
        dialog.onInit()

        mock_action = MagicMock()
        mock_action.getId.return_value = 92  # ACTION_NAV_BACK
        dialog.onAction(mock_action)

        self.assertEqual(dialog.selected, 'cancel')

    def test_dialog_on_action_select_focused_cancel(self):
        """Verify pressing Select when Cancel button is focused triggers cancellation."""
        dialog = ClearCacheDialog("clear_cache.xml", control.ADDON_PATH)
        dialog.onInit()
        dialog.setFocusId(3001)

        mock_action = MagicMock()
        mock_action.getId.return_value = 7  # ACTION_SELECT_ITEM
        dialog.onAction(mock_action)

        self.assertEqual(dialog.selected, 'cancel')

    @patch('resources.lib.windows.clear_cache.ClearCacheDialog.doModal', side_effect=RuntimeError("Skin missing"))
    @patch('resources.lib.ui.control.select_dialog', return_value=0)
    def test_show_clear_cache_dialog_fallback_to_select_dialog(self, mock_select, mock_modal):
        """Verify fallback to standard Kodi select dialog on XML error."""
        result = show_clear_cache_dialog()
        self.assertEqual(result, 'providers')
        mock_select.assert_called_once()

    @patch('resources.lib.ui.database.cache_clear_providers')
    @patch('resources.lib.windows.clear_cache.show_clear_cache_dialog', return_value='providers')
    def test_route_clear_cache_providers_invoked(self, mock_dialog, mock_clear_prov):
        """Verify tools route executes cache_clear_providers when providers selected."""
        tools.CLEAR_CACHE("", {})
        mock_clear_prov.assert_called_once()

    @patch('resources.lib.ui.database.cache_clear')
    @patch('resources.lib.windows.clear_cache.show_clear_cache_dialog', return_value='all')
    def test_route_clear_cache_all_invoked(self, mock_dialog, mock_clear_all):
        """Verify tools route executes cache_clear when all selected."""
        tools.CLEAR_CACHE("", {})
        mock_clear_all.assert_called_once()

    @patch('resources.lib.ui.database.cache_clear')
    @patch('resources.lib.ui.database.cache_clear_providers')
    @patch('resources.lib.windows.clear_cache.show_clear_cache_dialog', return_value='cancel')
    def test_route_clear_cache_cancelled(self, mock_dialog, mock_clear_prov, mock_clear_all):
        """Verify tools route does nothing when cancelled."""
        tools.CLEAR_CACHE("", {})
        mock_clear_prov.assert_not_called()
        mock_clear_all.assert_not_called()


if __name__ == '__main__':
    unittest.main()
