"""
Unit tests for multi-dimensional sorting architecture across Otaku-RPDev:
- Kodi native sort methods registered in control.draw_items()
- SQLite view v_watchlist_items extraction across AniList, MAL, Simkl, and Kitsu
- Pre-pagination SQL sorting by name, score, date, episodes remaining, and progress
- WatchlistFlavorBase sort and order mapping
- Self-healing view reconstruction on missing view error
"""

import json
import unittest

import tests.conftest
from resources.lib.WatchlistFlavor.WatchlistFlavorBase import WatchlistFlavorBase
from resources.lib.ui import control, database, utils
from resources.lib.ui.database_sync import SyncDatabase


class TestWatchlistSorting(unittest.TestCase):

    def setUp(self):
        tests.conftest.mock_xbmcplugin.reset()

    def test_kodi_native_sort_methods_registration(self):
        """control.draw_items registers comprehensive native sort methods for tvshows, videos, and episodes."""
        dummy_items = [utils.allocate_item('Anime A', 'plugin://test/1', True, False, [], '', {'title': 'Anime A'})]

        # 1. TV Shows (and movies, videos, seasons)
        tests.conftest.mock_xbmcplugin.reset()
        control.draw_items(dummy_items, 'tvshows')
        methods = [sm[1] for sm in tests.conftest.mock_xbmcplugin.sort_methods]
        self.assertIn(tests.conftest.mock_xbmcplugin.SORT_METHOD_NONE, methods)
        self.assertIn(tests.conftest.mock_xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE, methods)
        self.assertIn(tests.conftest.mock_xbmcplugin.SORT_METHOD_DATE, methods)
        self.assertIn(tests.conftest.mock_xbmcplugin.SORT_METHOD_VIDEO_RATING, methods)
        self.assertIn(tests.conftest.mock_xbmcplugin.SORT_METHOD_EPISODE, methods)
        self.assertIn(tests.conftest.mock_xbmcplugin.SORT_METHOD_PLAYCOUNT, methods)

        # 2. Episodes
        tests.conftest.mock_xbmcplugin.reset()
        control.draw_items(dummy_items, 'episodes')
        methods_ep = [sm[1] for sm in tests.conftest.mock_xbmcplugin.sort_methods]
        self.assertIn(tests.conftest.mock_xbmcplugin.SORT_METHOD_NONE, methods_ep)
        self.assertIn(tests.conftest.mock_xbmcplugin.SORT_METHOD_EPISODE, methods_ep)
        self.assertIn(tests.conftest.mock_xbmcplugin.SORT_METHOD_VIDEO_RATING, methods_ep)
        self.assertIn(tests.conftest.mock_xbmcplugin.SORT_METHOD_DATE, methods_ep)
        self.assertIn(tests.conftest.mock_xbmcplugin.SORT_METHOD_PLAYCOUNT, methods_ep)

        # 3. Addons / Tools menus keep single default sort method
        tests.conftest.mock_xbmcplugin.reset()
        control.draw_items(dummy_items, 'addons')
        methods_addons = [sm[1] for sm in tests.conftest.mock_xbmcplugin.sort_methods]
        self.assertEqual(len(methods_addons), 1)
        self.assertEqual(methods_addons[0], tests.conftest.mock_xbmcplugin.SORT_METHOD_NONE)

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


if __name__ == '__main__':
    unittest.main()
