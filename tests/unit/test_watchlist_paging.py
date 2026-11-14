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

import xbmc
import xbmcgui
from resources.lib.ui import control
from resources.lib.ui.BrowserBase import BrowserBase
from resources.lib.WatchlistFlavor.Simkl import SimklWLF
from resources.lib.WatchlistFlavor.AniList import AniListWLF
from resources.lib.WatchlistFlavor.MyAnimeList import MyAnimeListWLF
from resources.lib.WatchlistFlavor.Kitsu import KitsuWLF


class TestWatchlistPaging(unittest.TestCase):

    def setUp(self):
        control.clearSettingsCache()

    def tearDown(self):
        control.clearSettingsCache()

    # 1. is_addon_visible tests
    @patch('xbmcgui.getCurrentWindowId', return_value=10025)
    def test_is_addon_visible_myvideonav(self, mock_win):
        self.assertTrue(control.is_addon_visible())

    @patch('xbmcgui.getCurrentWindowId', return_value=10000)
    @patch('xbmc.getInfoLabel', side_effect=lambda prop: 'plugin.video.otaku.rpdev' if prop == 'Container.PluginName' else '')
    def test_is_addon_visible_plugin_name(self, mock_info, mock_win):
        self.assertTrue(control.is_addon_visible())

    @patch('xbmcgui.getCurrentWindowId', return_value=10000)
    @patch('xbmc.getInfoLabel', side_effect=lambda prop: 'plugin://plugin.video.otaku.rpdev/watchlist_status_type/simkl/completed' if prop == 'Container.FolderPath' else '')
    def test_is_addon_visible_folder_path(self, mock_info, mock_win):
        self.assertTrue(control.is_addon_visible())

    @patch('xbmcgui.getCurrentWindowId', return_value=10000)
    @patch('xbmc.getInfoLabel', return_value='')
    def test_is_addon_visible_home_widget_false(self, mock_info, mock_win):
        self.assertFalse(control.is_addon_visible())

    # 2. handle_paging tests across flavors
    @patch('resources.lib.ui.control.is_addon_visible', return_value=False)
    @patch('resources.lib.ui.control.getBool', side_effect=lambda k: True if k == 'widget.hide.nextpage' else False)
    def test_handle_paging_page1_hidden_on_widget(self, mock_bool, mock_vis):
        # On page 1 on a widget with hide.nextpage=True, Next Page is suppressed
        res_simkl = SimklWLF.handle_paging(True, 'watchlist_status_type_pages/simkl/completed/50', 1)
        self.assertEqual(res_simkl, [])

        res_ani = AniListWLF.handle_paging(True, 'watchlist_status_type_pages/anilist/COMPLETED/50', 1)
        self.assertEqual(res_ani, [])

        res_mal = MyAnimeListWLF.handle_paging(50, 'watchlist_status_type_pages/mal/completed', 1)
        self.assertEqual(res_mal, [])

        res_kitsu = KitsuWLF.handle_paging(50, 'watchlist_status_type_pages/kitsu/completed', 1)
        self.assertEqual(res_kitsu, [])

        res_browser = BrowserBase.handle_paging(True, 'watchlist_status_type_pages/browser/50', 1)
        self.assertEqual(res_browser, [])

    @patch('resources.lib.ui.control.is_addon_visible', return_value=True)
    @patch('resources.lib.ui.control.getBool', side_effect=lambda k: True if k == 'widget.hide.nextpage' else False)
    def test_handle_paging_page1_shown_in_addon(self, mock_bool, mock_vis):
        # On page 1 inside the addon, Next Page is always shown
        res_simkl = SimklWLF.handle_paging(True, 'watchlist_status_type_pages/simkl/completed/50', 1)
        self.assertEqual(len(res_simkl), 1)
        self.assertIn('page=2', res_simkl[0].get('url', ''))

        res_ani = AniListWLF.handle_paging(True, 'watchlist_status_type_pages/anilist/COMPLETED/50', 1)
        self.assertEqual(len(res_ani), 1)
        self.assertIn('page=2', res_ani[0].get('url', ''))

        res_mal = MyAnimeListWLF.handle_paging(50, 'watchlist_status_type_pages/mal/completed', 1)
        self.assertEqual(len(res_mal), 1)
        self.assertIn('page=2', res_mal[0].get('url', ''))

        res_kitsu = KitsuWLF.handle_paging(50, 'watchlist_status_type_pages/kitsu/completed', 1)
        self.assertEqual(len(res_kitsu), 1)
        self.assertIn('page=2', res_kitsu[0].get('url', ''))

    @patch('resources.lib.ui.control.is_addon_visible', return_value=False)
    @patch('resources.lib.ui.control.getBool', side_effect=lambda k: True if k == 'widget.hide.nextpage' else False)
    def test_handle_paging_page2_never_hidden(self, mock_bool, mock_vis):
        # On page 2+, Next Page is NEVER suppressed even if widget.hide.nextpage=True
        res_simkl = SimklWLF.handle_paging(True, 'watchlist_status_type_pages/simkl/completed/100', 2)
        self.assertEqual(len(res_simkl), 1)
        self.assertIn('page=3', res_simkl[0].get('url', ''))

        res_ani = AniListWLF.handle_paging(True, 'watchlist_status_type_pages/anilist/COMPLETED/100', 2)
        self.assertEqual(len(res_ani), 1)
        self.assertIn('page=3', res_ani[0].get('url', ''))

        res_mal = MyAnimeListWLF.handle_paging(100, 'watchlist_status_type_pages/mal/completed', 2)
        self.assertEqual(len(res_mal), 1)
        self.assertIn('page=3', res_mal[0].get('url', ''))

        res_kitsu = KitsuWLF.handle_paging(100, 'watchlist_status_type_pages/kitsu/completed', 2)
        self.assertEqual(len(res_kitsu), 1)
        self.assertIn('page=3', res_kitsu[0].get('url', ''))

        res_browser = BrowserBase.handle_paging(True, 'watchlist_status_type_pages/browser/100?page=%d', 2)
        self.assertEqual(len(res_browser), 1)
        self.assertIn('page=3', res_browser[0].get('url', ''))

    # 3. Cache refresh only on offset == 0
    @patch('resources.lib.WatchlistFlavor.Simkl.SimklWLF._should_refresh_cache')
    @patch('resources.lib.ui.database.is_watchlist_cache_valid', return_value=True)
    @patch('resources.lib.ui.database.get_watchlist_cache_count', return_value=100)
    @patch('resources.lib.ui.database.get_watchlist_cache', return_value=[])
    def test_simkl_cache_refresh_offset_guard(self, mock_cache, mock_count, mock_valid, mock_refresh):
        simkl = SimklWLF()

        # Page 1 (offset=0): should check refresh
        simkl.get_watchlist_status('completed', False, 0, 1)
        self.assertEqual(mock_refresh.call_count, 1)

        # Page 2 (offset=50): should NOT check refresh
        simkl.get_watchlist_status('completed', False, '50', 2)
        self.assertEqual(mock_refresh.call_count, 1)

        # Page 3 (offset=100): should NOT check refresh
        simkl.get_watchlist_status('completed', False, 100, 3)
        self.assertEqual(mock_refresh.call_count, 1)

    @patch('resources.lib.WatchlistFlavor.AniList.AniListWLF._should_refresh_cache')
    @patch('resources.lib.ui.database.is_watchlist_cache_valid', return_value=True)
    @patch('resources.lib.ui.database.get_watchlist_cache_count', return_value=100)
    @patch('resources.lib.ui.database.get_watchlist_cache', return_value=[])
    def test_anilist_cache_refresh_offset_guard(self, mock_cache, mock_count, mock_valid, mock_refresh):
        ani = AniListWLF()

        # Page 1 (offset=0): should check refresh
        ani.process_status_view('query', {}, False, 'COMPLETED', 0, 1)
        self.assertEqual(mock_refresh.call_count, 1)

        # Page 2 (offset=50): should NOT check refresh
        ani.process_status_view('query', {}, False, 'COMPLETED', '50', 2)
        self.assertEqual(mock_refresh.call_count, 1)

    @patch('resources.lib.WatchlistFlavor.MyAnimeList.MyAnimeListWLF._should_refresh_cache')
    @patch('resources.lib.ui.database.is_watchlist_cache_valid', return_value=True)
    @patch('resources.lib.ui.database.get_watchlist_cache_count', return_value=100)
    @patch('resources.lib.ui.database.get_watchlist_cache', return_value=[])
    def test_mal_cache_refresh_offset_guard(self, mock_cache, mock_count, mock_valid, mock_refresh):
        mal = MyAnimeListWLF()

        # Page 1 (offset=0): should check refresh
        mal.get_watchlist_status('completed', False, 0, 1)
        self.assertEqual(mock_refresh.call_count, 1)

        # Page 2 (offset=50): should NOT check refresh
        mal.get_watchlist_status('completed', False, 50, 2)
        self.assertEqual(mock_refresh.call_count, 1)

    @patch('resources.lib.WatchlistFlavor.Kitsu.KitsuWLF._should_refresh_cache')
    @patch('resources.lib.ui.database.is_watchlist_cache_valid', return_value=True)
    @patch('resources.lib.ui.database.get_watchlist_cache_count', return_value=100)
    @patch('resources.lib.ui.database.get_watchlist_cache', return_value=[])
    def test_kitsu_cache_refresh_offset_guard(self, mock_cache, mock_count, mock_valid, mock_refresh):
        kitsu = KitsuWLF()

        # Page 1 (offset=0): should check refresh
        kitsu.get_watchlist_status('completed', False, 0, 1)
        self.assertEqual(mock_refresh.call_count, 1)

        # Page 2 (offset=50): should NOT check refresh
        kitsu.get_watchlist_status('completed', False, 50, 2)
        self.assertEqual(mock_refresh.call_count, 1)

    # 4. AniList chunking tests
    @patch('resources.lib.WatchlistFlavor.AniList.AniListWLF._should_refresh_cache')
    @patch('resources.lib.ui.database.is_watchlist_cache_valid', return_value=False)
    @patch('resources.lib.ui.database.save_watchlist_cache')
    @patch('resources.lib.ui.database.get_watchlist_cache', return_value=[])
    @patch('resources.lib.WatchlistFlavor.AniList.client.post')
    def test_anilist_chunking_pagination(self, mock_post, mock_get_cache, mock_save, mock_valid, mock_refresh):
        ani = AniListWLF()

        # Mock two chunks from AniList GraphQL
        mock_response_1 = MagicMock()
        mock_response_1.json.return_value = {
            'data': {
                'MediaListCollection': {
                    'hasNextChunk': True,
                    'lists': [{
                        'entries': [{'id': 1, 'media': {'id': 101, 'title': {'romaji': 'Show 1'}}}]
                    }]
                }
            }
        }
        mock_response_2 = MagicMock()
        mock_response_2.json.return_value = {
            'data': {
                'MediaListCollection': {
                    'hasNextChunk': False,
                    'lists': [{
                        'entries': [{'id': 2, 'media': {'id': 102, 'title': {'romaji': 'Show 2'}}}]
                    }]
                }
            }
        }
        mock_post.side_effect = [mock_response_1, mock_response_2]

        ani.process_status_view('query', {'userName': 'testuser'}, False, 'COMPLETED', 0, 1, cache_only=True)

        self.assertEqual(mock_post.call_count, 2)
        mock_save.assert_called_once()
        saved_entries = mock_save.call_args[0][2]
        self.assertEqual(len(saved_entries), 2)
        self.assertEqual(saved_entries[0]['id'], 1)
        self.assertEqual(saved_entries[1]['id'], 2)

    # 5. schedule_next_page_prefetch is safe no-op
    def test_schedule_next_page_prefetch_is_safe_noop(self):
        called = []
        control.schedule_next_page_prefetch([{}], lambda: called.append(1))
        self.assertEqual(called, [])

    # 6. Simkl Currently Watching page 2+ resilience when optional fields are omitted
    @patch('resources.lib.WatchlistFlavor.Simkl.get_meta.collect_meta')
    @patch('resources.lib.ui.database.get_show_meta', return_value=None)
    @patch('resources.lib.ui.database.get_show', return_value=None)
    @patch('resources.lib.ui.database.get_unique_ids', return_value={})
    @patch('resources.lib.ui.database.is_watchlist_cache_valid', return_value=True)
    @patch('resources.lib.ui.database.get_watchlist_cache_count', return_value=3)
    @patch('resources.lib.ui.database.get_watchlist_cache')
    def test_simkl_watching_page2_resilient_to_missing_fields(
        self, mock_cache, mock_count, mock_valid, mock_uids, mock_show, mock_meta, mock_collect
    ):
        from resources.lib.ui import database
        control.setBool('interface.watchlist.paging', True)
        control.setInt('interface.perpage.watchlist', 2)
        # Item on page 2 missing poster, year, user_rating, added_to_watchlist_at, last_watched_at, user_rated_at
        sparse_item = {
            'show': {'ids': {'mal': 999, 'anilist': 888}, 'title': 'Sparse Simkl Show'},
            'watched_episodes_count': 0,
            'total_episodes_count': 12,
        }
        mock_cache.return_value = [{'data': database.dumps(sparse_item)}]

        simkl = SimklWLF()
        with patch('resources.lib.endpoints.anilist.Anilist.get_enrichment_for_mal_ids', return_value=[]):
            res = simkl.get_watchlist_status('watching', False, '2', 2)

        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['info']['episodes'], 12)
        self.assertIn('Sparse Simkl Show', res[0]['name'])


if __name__ == '__main__':
    unittest.main()
