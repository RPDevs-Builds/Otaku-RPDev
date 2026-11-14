"""
Unit tests for multi-dimensional sorting architecture across Otaku-RPDev:
- Kodi native sort methods registered in control.draw_items()
- SQLite view v_watchlist_items extraction across AniList, MAL, Simkl, and Kitsu
- Pre-pagination SQL sorting by name, score, date, episodes remaining, and progress
- WatchlistFlavorBase sort and order mapping
- Self-healing view reconstruction on missing view error
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

import json
import unittest

from resources.lib.WatchlistFlavor.WatchlistFlavorBase import WatchlistFlavorBase
from resources.lib.ui import control, database, utils
from resources.lib.ui.database_sync import SyncDatabase


class TestWatchlistSorting(unittest.TestCase):

    def setUp(self):
        conftest.mock_xbmcplugin.reset()

    def test_kodi_native_sort_methods_registration(self):
        """control.draw_items registers comprehensive native sort methods for tvshows, videos, and episodes."""
        dummy_items = [utils.allocate_item('Anime A', 'plugin://test/1', True, False, [], '', {'title': 'Anime A'})]

        # 1. TV Shows (and movies, videos, seasons)
        conftest.mock_xbmcplugin.reset()
        control.draw_items(dummy_items, 'tvshows')
        methods = [sm[1] for sm in conftest.mock_xbmcplugin.sort_methods]
        self.assertIn(conftest.mock_xbmcplugin.SORT_METHOD_UNSORTED, methods)
        self.assertNotIn(conftest.mock_xbmcplugin.SORT_METHOD_NONE, methods)
        self.assertIn(conftest.mock_xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE, methods)
        self.assertIn(conftest.mock_xbmcplugin.SORT_METHOD_DATE, methods)
        self.assertIn(conftest.mock_xbmcplugin.SORT_METHOD_VIDEO_RATING, methods)
        self.assertIn(conftest.mock_xbmcplugin.SORT_METHOD_EPISODE, methods)
        self.assertIn(conftest.mock_xbmcplugin.SORT_METHOD_PLAYCOUNT, methods)

        # 2. Episodes
        conftest.mock_xbmcplugin.reset()
        control.draw_items(dummy_items, 'episodes')
        methods_ep = [sm[1] for sm in conftest.mock_xbmcplugin.sort_methods]
        self.assertIn(conftest.mock_xbmcplugin.SORT_METHOD_UNSORTED, methods_ep)
        self.assertNotIn(conftest.mock_xbmcplugin.SORT_METHOD_NONE, methods_ep)
        self.assertIn(conftest.mock_xbmcplugin.SORT_METHOD_EPISODE, methods_ep)
        self.assertIn(conftest.mock_xbmcplugin.SORT_METHOD_VIDEO_RATING, methods_ep)
        self.assertIn(conftest.mock_xbmcplugin.SORT_METHOD_DATE, methods_ep)
        self.assertIn(conftest.mock_xbmcplugin.SORT_METHOD_PLAYCOUNT, methods_ep)

        # 3. Addons / Tools menus keep single default sort method
        conftest.mock_xbmcplugin.reset()
        control.draw_items(dummy_items, 'addons')
        methods_addons = [sm[1] for sm in conftest.mock_xbmcplugin.sort_methods]
        self.assertEqual(len(methods_addons), 1)
        self.assertEqual(methods_addons[0], conftest.mock_xbmcplugin.SORT_METHOD_UNSORTED)

    def test_v_watchlist_items_view_and_cross_service_extraction(self):
        """v_watchlist_items view normalizes title, score, episodes, and dates across all 4 services."""
        sync_db = SyncDatabase()
        sync_db.build_watchlist_cache_table()
        database.clear_watchlist_cache()

        sample_anilist = {
            'media': {
                'title': {'english': 'Attack on Titan', 'romaji': 'Shingeki no Kyojin'},
                'averageScore': 88,
                'episodes': 25,
                'startDate': {'year': 2013, 'month': 4, 'day': 7}
            },
            'progress': 10,
            'updatedAt': 1680000000
        }
        sample_mal = {
            'node': {
                'id': 16498,
                'title': 'Shingeki no Kyojin',
                'alternative_titles': {'en': 'Attack on Titan'},
                'mean': 8.54,
                'num_episodes': 25,
                'start_date': '2013-04-07'
            },
            'list_status': {
                'num_episodes_watched': 15,
                'updated_at': '2023-01-01T00:00:00Z'
            }
        }
        sample_simkl = {
            'show': {
                'ids': {'mal': 16498},
                'title': 'Attack on Titan',
                'release_date': '2013-04-07',
                'ratings': {'simkl': {'rating': 8.7}}
            },
            'total_episodes_count': 25,
            'watched_episodes_count': 20,
            'last_watched_at': '2023-05-01T12:00:00Z'
        }
        sample_kitsu = {
            'mal_id': 16498,
            'anime': {
                'attributes': {
                    'canonicalTitle': 'Shingeki no Kyojin',
                    'titles': {'en': 'Attack on Titan', 'en_jp': 'Shingeki no Kyojin'},
                    'averageRating': '85.2',
                    'episodeCount': 25,
                    'startDate': '2013-04-07'
                }
            },
            'entry': {
                'attributes': {
                    'progress': 5,
                    'updatedAt': '2023-03-01T00:00:00Z'
                }
            }
        }

        database.save_watchlist_cache('anilist', 'watching', [sample_anilist])
        database.save_watchlist_cache('mal', 'watching', [sample_mal])
        database.save_watchlist_cache('simkl', 'watching', [sample_simkl])
        database.save_watchlist_cache('kitsu', 'watching', [sample_kitsu])

        with database.SQL(control.malSyncDB) as cur:
            rows = cur.execute('SELECT * FROM v_watchlist_items ORDER BY id').fetchall()

        self.assertEqual(len(rows), 4)

        # Verify AniList
        al = rows[0]
        self.assertEqual(al['service'], 'anilist')
        self.assertEqual(al['title_en'], 'Attack on Titan')
        self.assertEqual(al['title_romaji'], 'Shingeki no Kyojin')
        self.assertAlmostEqual(al['score'], 88.0)
        self.assertEqual(al['total_episodes'], 25)
        self.assertEqual(al['episodes_watched'], 10)
        self.assertEqual(al['episodes_remaining'], 15)
        self.assertEqual(al['release_date'], '2013-04-07')

        # Verify MAL
        mal = rows[1]
        self.assertEqual(mal['service'], 'mal')
        self.assertEqual(mal['title_en'], 'Attack on Titan')
        self.assertEqual(mal['title_romaji'], 'Shingeki no Kyojin')
        self.assertAlmostEqual(mal['score'], 85.4)
        self.assertEqual(mal['total_episodes'], 25)
        self.assertEqual(mal['episodes_watched'], 15)
        self.assertEqual(mal['episodes_remaining'], 10)
        self.assertEqual(mal['release_date'], '2013-04-07')

        # Verify Simkl
        simkl = rows[2]
        self.assertEqual(simkl['service'], 'simkl')
        self.assertEqual(simkl['title_en'], 'Attack on Titan')
        self.assertAlmostEqual(simkl['score'], 87.0)
        self.assertEqual(simkl['total_episodes'], 25)
        self.assertEqual(simkl['episodes_watched'], 20)
        self.assertEqual(simkl['episodes_remaining'], 5)
        self.assertEqual(simkl['release_date'], '2013-04-07')

        # Verify Kitsu
        kitsu = rows[3]
        self.assertEqual(kitsu['service'], 'kitsu')
        self.assertEqual(kitsu['title_en'], 'Attack on Titan')
        self.assertEqual(kitsu['title_romaji'], 'Shingeki no Kyojin')
        self.assertAlmostEqual(kitsu['score'], 85.2)
        self.assertEqual(kitsu['total_episodes'], 25)
        self.assertEqual(kitsu['episodes_watched'], 5)
        self.assertEqual(kitsu['episodes_remaining'], 20)
        self.assertEqual(kitsu['release_date'], '2013-04-07')

    def test_database_level_sorting_and_pagination(self):
        """get_watchlist_cache sorts by title, score, remaining, and handles limit/offset."""
        sync_db = SyncDatabase()
        sync_db.build_watchlist_cache_table()
        database.clear_watchlist_cache('anilist', 'watching')

        shows = [
            {'media': {'title': {'english': 'Bleach', 'romaji': 'Bleach'}, 'averageScore': 80, 'episodes': 366, 'startDate': {'year': 2004, 'month': 10, 'day': 5}}, 'progress': 300, 'updatedAt': 1680000001},
            {'media': {'title': {'english': 'Chainsaw Man', 'romaji': 'Chainsaw Man'}, 'averageScore': 87, 'episodes': 12, 'startDate': {'year': 2022, 'month': 10, 'day': 12}}, 'progress': 2, 'updatedAt': 1680000003},
            {'media': {'title': {'english': 'Death Note', 'romaji': 'Death Note'}, 'averageScore': 90, 'episodes': 37, 'startDate': {'year': 2006, 'month': 10, 'day': 4}}, 'progress': 35, 'updatedAt': 1680000002},
            {'media': {'title': {'english': 'Attack on Titan', 'romaji': 'Shingeki no Kyojin'}, 'averageScore': 92, 'episodes': 25, 'startDate': {'year': 2013, 'month': 4, 'day': 7}}, 'progress': 20, 'updatedAt': 1680000004},
        ]
        database.save_watchlist_cache('anilist', 'watching', shows)

        # 1. Sort by Title ASC
        items = database.get_watchlist_cache('anilist', 'watching', sort_by='title', order='asc')
        titles = [item['title_en'] for item in items]
        self.assertEqual(titles, ['Attack on Titan', 'Bleach', 'Chainsaw Man', 'Death Note'])

        # 2. Sort by Score DESC
        items = database.get_watchlist_cache('anilist', 'watching', sort_by='score', order='desc')
        scores = [item['score'] for item in items]
        self.assertEqual(scores, [92.0, 90.0, 87.0, 80.0])

        # 3. Sort by Episodes Remaining DESC (66 remaining Bleach, 10 remaining Chainsaw Man, 5 remaining AoT, 2 remaining Death Note)
        items = database.get_watchlist_cache('anilist', 'watching', sort_by='remaining', order='desc')
        remaining = [item['episodes_remaining'] for item in items]
        self.assertEqual(remaining, [66, 10, 5, 2])

        # 4. Sort by Episodes Remaining ASC (fewest remaining first)
        items = database.get_watchlist_cache('anilist', 'watching', sort_by='remaining', order='asc')
        remaining = [item['episodes_remaining'] for item in items]
        self.assertEqual(remaining, [2, 5, 10, 66])

        # 5. Pagination: limit 2, offset 0 then offset 2
        p1 = database.get_watchlist_cache('anilist', 'watching', limit=2, offset=0, sort_by='title', order='asc')
        self.assertEqual([x['title_en'] for x in p1], ['Attack on Titan', 'Bleach'])

        p2 = database.get_watchlist_cache('anilist', 'watching', limit=2, offset=2, sort_by='title', order='asc')
        self.assertEqual([x['title_en'] for x in p2], ['Chainsaw Man', 'Death Note'])

    def test_watchlist_flavor_base_sort_mapping(self):
        """WatchlistFlavorBase.get_sort_col_and_order maps settings to correct SQL col and direction."""
        # Title (0), Ascending (0) with english title
        wlf = WatchlistFlavorBase(sort=0, order=0)
        wlf.title_lang = 'english'
        col, direction = wlf.get_sort_col_and_order()
        self.assertEqual(col, 'title_en')
        self.assertEqual(direction, 'ASC')

        # Title (0), Ascending (0) with romaji title
        wlf = WatchlistFlavorBase(sort=0, order=0)
        wlf.title_lang = 'romaji'
        col, direction = wlf.get_sort_col_and_order()
        self.assertEqual(col, 'title_romaji')
        self.assertEqual(direction, 'ASC')

        # Title (0), Descending (1) with english title
        wlf = WatchlistFlavorBase(sort=0, order=1)
        wlf.title_lang = 'english'
        col, direction = wlf.get_sort_col_and_order()
        self.assertEqual(col, 'title_en')
        self.assertEqual(direction, 'DESC')

        # Score (1), Default (0) -> DESC (highest first)
        wlf = WatchlistFlavorBase(sort=1, order=0)
        col, direction = wlf.get_sort_col_and_order()
        self.assertEqual(col, 'score')
        self.assertEqual(direction, 'DESC')

        # Episodes Remaining (5), Default (0) -> DESC (most remaining first)
        wlf = WatchlistFlavorBase(sort=5, order=0)
        col, direction = wlf.get_sort_col_and_order()
        self.assertEqual(col, 'remaining')
        self.assertEqual(direction, 'DESC')

        # Episodes Remaining (5), Reversed (1) -> ASC (fewest remaining first)
        wlf = WatchlistFlavorBase(sort=5, order=1)
        col, direction = wlf.get_sort_col_and_order()
        self.assertEqual(col, 'remaining')
        self.assertEqual(direction, 'ASC')

        # Total Episodes (6), Default (0) -> DESC
        wlf = WatchlistFlavorBase(sort=6, order=0)
        col, direction = wlf.get_sort_col_and_order()
        self.assertEqual(col, 'episodes')
        self.assertEqual(direction, 'DESC')

    def test_database_self_healing_view_rebuild(self):
        """get_watchlist_cache automatically rebuilds v_watchlist_items view if missing."""
        sync_db = SyncDatabase()
        sync_db.build_watchlist_cache_table()

        sample = {'media': {'title': {'english': 'Self Healing Test'}, 'averageScore': 85, 'episodes': 12}, 'progress': 4}
        database.save_watchlist_cache('anilist', 'watching', [sample])

        # Manually drop the view to simulate an un-migrated or corrupted database state
        with database.SQL(control.malSyncDB) as cur:
            cur.execute('DROP VIEW IF EXISTS v_watchlist_items')
            cur.connection.commit()

        # Query should catch OperationalError, self-heal by rebuilding view, and return results cleanly
        items = database.get_watchlist_cache('anilist', 'watching', sort_by='title')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['title_en'], 'Self Healing Test')
        self.assertEqual(items[0]['episodes_remaining'], 8)

    def test_sort_label_masks_preserve_titles(self):
        """Ensure addSortMethod never uses %Y, %R, %E, or %P as labelMask (which overwrites titles)."""
        dummy_items = [utils.allocate_item('Anime Title', 'plugin://test/1', True, False, [], '', {'title': 'Anime Title'})]

        for ctype, expected_mask in (('tvshows', '%L'), ('episodes', '%H. %T'), ('addons', '%L')):
            conftest.mock_xbmcplugin.reset()
            control.draw_items(dummy_items, ctype)
            for sm_args in conftest.mock_xbmcplugin.sort_methods:
                label_mask = sm_args[2] if len(sm_args) > 2 else ''
                self.assertEqual(
                    label_mask, expected_mask,
                    f"Sort method {sm_args} for content_type={ctype!r} overwrote labelMask with {label_mask!r}"
                )

    def test_episode_counts_populated_for_sorting(self):
        """Ensure tvshow browse views and set_videotags pass total episodes to VideoInfoTag.setEpisode."""
        import xbmcgui
        from unittest.mock import patch
        from resources.lib.AniListBrowser import AniListBrowser
        from resources.lib.MalBrowser import MalBrowser

        # 1. control.set_videotags handles episodes, total_episodes_count, and setDateTime
        for key in ('episode', 'episodes', 'total_episodes', 'total_episodes_count'):
            li = xbmcgui.ListItem('Test Show')
            control.set_videotags(li, {'title': 'Test Show', key: 24, 'premiered': '2023-04-01'})
            self.assertEqual(li.getVideoInfoTag().getEpisode(), 24)
            self.assertEqual(li.getDateTime(), '2023-04-01T00:00:00')

        li_yr = xbmcgui.ListItem('Year Only')
        control.set_videotags(li_yr, {'title': 'Year Only', 'year': 2021})
        self.assertEqual(li_yr.getDateTime(), '2021-01-01T00:00:00')

        # 2. AniListBrowser.base_anilist_view includes episodes
        ab = AniListBrowser()
        sample_al = {
            'id': 1, 'idMal': 10, 'episodes': 24, 'averageScore': 88,
            'title': {'romaji': 'Test AL', 'english': 'Test AL'},
            'coverImage': {'extraLarge': 'img.jpg'}, 'genres': ['Action'],
            'startDate': {'year': 2023, 'month': 4, 'day': 1}, 'status': 'FINISHED',
            'characters': {'edges': []}, 'studios': {'edges': []},
        }
        with patch('resources.lib.ui.database.get_show_meta', return_value=None), \
             patch('resources.lib.ui.database.get_show', return_value=None):
            res_al = ab.base_anilist_view(sample_al)
        self.assertEqual(res_al['info'].get('episodes'), 24)

        # 3. MalBrowser.base_mal_view includes episodes
        mb = MalBrowser()
        sample_mal = {
            'mal_id': 20, 'title': 'Test MAL', 'title_english': 'Test MAL',
            'episodes': 12, 'score': 8.5, 'duration': '24 min per ep',
            'images': {'webp': {'large_image_url': 'img.jpg'}},
            'genres': [{'name': 'Action'}], 'aired': {'from': '2022-01-01T00:00:00+00:00'},
        }
        with patch('resources.lib.ui.database.get_show_meta', return_value=None), \
             patch('resources.lib.ui.database.get_show', return_value=None), \
             patch('resources.lib.ui.database.get_mappings', return_value={}):
            res_mal = mb.base_mal_view(sample_mal)
        self.assertEqual(res_mal['info'].get('episodes'), 12)

    def test_special_sort_pinning_next_page_and_filter(self):
        """Ensure Next Page rows pin to bottom and Filter rows pin to top via SpecialSort."""
        next_item = utils.allocate_item(
            'Next Page (2)', 'watchlist_status_type_pages/simkl/watching/50?page=2',
            True, False, [], 'next.png', {'plot': 'Next Page (2)'}, fanart='next.png'
        )
        filter_item = utils.allocate_item(
            '[Filter List by Text...]', 'multipage_filter?base_url=top_100%2F%25d',
            False, False, [], 'search.png', {'plot': 'Filter'}
        )
        clear_item = utils.allocate_item(
            '[COLOR deepskyblue][Clear Filter: test][/COLOR]', 'multipage_clear_filter?base_url=top_100%2F1',
            False, False, [], 'search.png', {'plot': 'Clear'}
        )
        show_item = utils.allocate_item(
            'Normal Show', 'animes/1/', True, False, [], 'poster.jpg', {'title': 'Normal Show'}
        )

        conftest.mock_xbmcplugin.reset()
        control.draw_items([filter_item, clear_item, show_item, next_item], 'tvshows')
        added = conftest.mock_xbmcplugin.directory_items
        self.assertEqual(len(added), 4)
        self.assertEqual(added[0][2].getProperty('SpecialSort'), 'top')
        self.assertEqual(added[1][2].getProperty('SpecialSort'), 'top')
        self.assertEqual(added[2][2].getProperty('SpecialSort'), '')
        self.assertEqual(added[3][2].getProperty('SpecialSort'), 'bottom')


if __name__ == '__main__':
    unittest.main()