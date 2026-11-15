"""Unit tests for Watchlist Unlimited Pre-Caching, Single Container Presentation,
and Catalogue Browse Pagination.
"""

import unittest
from unittest.mock import MagicMock, patch

from resources.lib.ui import control, database
from resources.lib.ui.BrowserBase import BrowserBase
from resources.lib.MalBrowser import MalBrowser
from resources.lib.AniListBrowser import AniListBrowser
import service


class TestWatchlistPreCachingAndPaging(unittest.TestCase):
    """Verifies pre-caching behavior, single container presentation, and catalogue fixes."""

    def test_prefetch_watchlist_runs_when_precache_all_enabled(self):
        """prefetch_watchlist() runs when watchlist.precache.all is True even if watchlist.update.enabled is False."""
        with patch.object(control, 'getBool') as mock_bool, \
             patch.object(control, 'enabled_watchlists', return_value=['simkl']) as mock_enabled, \
             patch('resources.lib.WatchlistFlavor.WatchlistFlavor.get_flavor_by_name') as mock_get_flavor, \
             patch('resources.lib.ui.database.is_watchlist_cache_valid', return_value=False), \
             patch('resources.lib.ui.database.get_all_watchlist_mal_ids', return_value=[]):

            mock_bool.side_effect = lambda k: {
                'watchlist.prefetch.enabled': False,
                'watchlist.precache.all': True,
                'watchlist.update.enabled': False,
            }.get(k, False)

            mock_flavor = MagicMock()
            mock_get_flavor.return_value = mock_flavor

            service.prefetch_watchlist()

            # Verify that all 5 statuses for Simkl were queried with cache_only=True
            expected_statuses = ['watching', 'completed', 'hold', 'dropped', 'plantowatch']
            called_statuses = [call[0][0] for call in mock_flavor.get_watchlist_status.call_args_list]
            self.assertEqual(called_statuses, expected_statuses)
            for call in mock_flavor.get_watchlist_status.call_args_list:
                self.assertTrue(call[1].get('cache_only') or (len(call[0]) > 4 and call[0][4]))

    def test_browser_base_handle_paging_clean_url(self):
        """handle_paging generates clean URL with page query parameter and no double question marks."""
        # Case 1: base_url has %d
        items = BrowserBase.handle_paging(True, 'airing_this_season?page=%d', 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['url'], 'airing_this_season?page=2')

        # Case 2: base_url already has page=1
        items2 = BrowserBase.handle_paging(True, 'all_time_popular?page=1', 2)
        self.assertEqual(len(items2), 1)
        self.assertEqual(items2[0]['url'], 'all_time_popular?page=3')

        # Case 3: base_url has extra query params
        items3 = BrowserBase.handle_paging(True, 'genre_action?genre=1&page=2', 3)
        self.assertEqual(len(items3), 1)
        self.assertIn('page=4', items3[0]['url'])
        self.assertIn('genre=1', items3[0]['url'])
        self.assertNotIn('??', items3[0]['url'])

    def test_browser_base_process_multipage_view_page_2_does_not_empty(self):
        """When page 2 items are passed from API, process_multipage_view does not slice to empty list."""
        browser = BrowserBase()
        browser.perpage = 20
        # Simulated 20 items from API for page 2
        page_2_items = [{'name': f'Anime {i}', 'url': f'show/{i}'} for i in range(21, 41)]

        result = browser.process_multipage_view(page_2_items, True, 'all_time_popular?page=2', page=2)

        # 20 items + 1 Next Page item
        self.assertEqual(len(result), 21)
        self.assertEqual(result[0]['name'], 'Anime 21')
        self.assertEqual(result[19]['name'], 'Anime 40')
        self.assertEqual(result[20]['name'], 'Next Page (3)')
        self.assertEqual(result[20]['url'], 'all_time_popular?page=3')

    def test_mal_browser_airing_season_signatures_accept_filter_text(self):
        """MalBrowser season methods accept filter_text keyword parameter."""
        browser = MalBrowser()
        with patch.object(browser, '_browse_season_airing', return_value=[]) as mock_browse:
            browser.get_airing_this_season(1, None, 'airing_this_season', filter_text='test')
            mock_browse.assert_called_with(1, None, 'airing_this_season', 'airing_this_season', 'this', filter_text='test')

            browser.get_airing_last_season(1, None, 'airing_last_season', filter_text='test')
            mock_browse.assert_called_with(1, None, 'airing_last_season', 'airing_last_season', 'last', filter_text='test')

            browser.get_airing_next_season(1, None, 'airing_next_season', filter_text='test')
            mock_browse.assert_called_with(1, None, 'airing_next_season', 'airing_next_season', 'next', filter_text='test')

    def test_anilist_browser_airing_season_signatures_accept_filter_text(self):
        """AniListBrowser season methods accept filter_text keyword parameter."""
        browser = AniListBrowser()
        with patch.object(browser, '_browse_season_airing', return_value=[]) as mock_browse:
            browser.get_airing_this_season(1, None, 'airing_this_season', filter_text='test')
            mock_browse.assert_called_with(1, None, 'airing_this_season', 'airing_this_season', 'this', 'POPULARITY_DESC', filter_text='test')

            browser.get_airing_last_season(1, None, 'airing_last_season', filter_text='test')
            mock_browse.assert_called_with(1, None, 'airing_last_season', 'airing_last_season', 'last', 'TRENDING_DESC', filter_text='test')

            browser.get_airing_next_season(1, None, 'airing_next_season', filter_text='test')
            mock_browse.assert_called_with(1, None, 'airing_next_season', 'airing_next_season', 'next', 'POPULARITY_DESC', filter_text='test')

    def test_mal_browser_get_season_year_fallback_on_invalid_year(self):
        """When self.year_type is invalid (e.g. 0), get_season_year falls back safely to current year."""
        browser = MalBrowser()
        browser.year_type = 0
        season, year, _, _, _, _, _, _, _, _, _, _, _, _ = browser.get_season_year('current')
        import datetime
        self.assertIsNotNone(season)
        self.assertEqual(year, datetime.datetime.today().year)


if __name__ == '__main__':
    unittest.main()
