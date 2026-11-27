"""High-coverage unit tests for WatchlistFlavor Kitsu."""
# -*- coding: utf-8 -*-

import unittest
from unittest.mock import MagicMock, patch

from resources.lib.WatchlistFlavor.Kitsu import KitsuWLF
from resources.lib.ui import control


def _mock_http(payload, ok=True):
    r = MagicMock()
    r.ok = ok
    r.status_code = 200 if ok else 400
    r.headers = {}
    r.json.return_value = payload
    return r


def _sample_kitsu_payload(kitsu_id='7442', mal_id='16498', progress=3, ep_count=25, subtype='TV'):
    return {
        'data': [{
            'id': '101',
            'type': 'libraryEntries',
            'attributes': {
                'status': 'current',
                'progress': progress,
                'ratingTwenty': 18,
                'progressedAt': '2026-11-20T12:00:00Z',
                'updatedAt': '2026-11-20T12:00:00Z',
                'startedAt': '2026-10-01T12:00:00Z',
            },
            'relationships': {
                'anime': {'data': {'id': kitsu_id, 'type': 'anime'}},
            },
        }],
        'included': [
            {
                'id': kitsu_id,
                'type': 'anime',
                'attributes': {
                    'canonicalTitle': 'Attack on Titan',
                    'titles': {'en': 'Attack on Titan', 'en_jp': 'Shingeki no Kyojin'},
                    'synopsis': 'Titans vs humanity.',
                    'episodeCount': ep_count,
                    'episodeLength': 24,
                    'averageRating': '85.2',
                    'ageRating': 'R',
                    'subtype': subtype,
                    'youtubeVideoId': 'MGRm4IzK1SQ',
                    'posterImage': {'large': 'https://media.kitsu.io/poster.jpg'},
                },
                'relationships': {
                    'mappings': {'data': [{'id': 'map_1', 'type': 'mappings'}]},
                },
            },
            {
                'id': 'map_1',
                'type': 'mappings',
                'attributes': {
                    'externalSite': 'myanimelist/anime',
                    'externalId': mal_id,
                },
            },
        ],
    }


def _sample_anilist_enrichment(mal_id='16498'):
    return {
        'id': 16498,
        'idMal': int(mal_id),
        'title': {'romaji': 'Shingeki no Kyojin', 'english': 'Attack on Titan'},
        'coverImage': {'extraLarge': 'https://cdn.anilist/aot.jpg'},
        'genres': ['Action', 'Drama'],
        'studios': {'edges': [{'isMain': True, 'node': {'name': 'WIT STUDIO'}}]},
        'status': 'FINISHED',
        'startDate': {'year': 2013, 'month': 4, 'day': 7},
        'averageScore': 86,
        'stats': {'scoreDistribution': [{'score': 90, 'amount': 500}]},
        'countryOfOrigin': 'JP',
    }


class TestKitsuWatchlistCoverage(unittest.TestCase):
    """Exercise all KitsuWLF list, Next Up, mapping, and mutation paths."""

    def setUp(self):
        control.setSetting('kitsu.token', 'kitsu_tok')
        control.setSetting('kitsu.userid', '999')
        self.kw = KitsuWLF()
        self.kw.user_id = '999'
        self.kw.token = 'kitsu_tok'
        self.kw.sort = 0
        self.kw.order = 0
        self.kw.mapping = []

    def test_kitsu_watchlist_menus_status_and_next_up_views(self):
        # Status menus & _get_mapping_id
        self.assertGreaterEqual(len(self.kw.watchlist()), 5)
        self.assertIsNone(self.kw.action_statuses()) if not callable(getattr(self.kw, 'action_statuses', None)) else self.assertGreaterEqual(len(self.kw.action_statuses()), 5)

        sample = _sample_kitsu_payload()
        cached_item = {
            'entry': sample['data'][0],
            'anime': sample['included'][0],
            'mal_id': '16498',
        }
        al_item = _sample_anilist_enrichment('16498')

        from resources.lib.ui import database as db_mod
        with patch.object(self.kw, '_should_refresh_cache'), \
             patch.object(db_mod, 'is_watchlist_cache_valid', side_effect=[False, True, True]), \
             patch.object(db_mod, 'save_watchlist_cache') as mock_save, \
             patch.object(db_mod, 'get_watchlist_cache_count', return_value=2), \
             patch.object(db_mod, 'get_watchlist_cache', return_value=[{'data': db_mod.dumps(cached_item)}]), \
             patch('resources.lib.WatchlistFlavor.Kitsu.client.get', return_value=_mock_http(sample)), \
             patch('resources.lib.WatchlistFlavor.Kitsu.get_meta.collect_meta'), \
             patch('resources.lib.WatchlistFlavor.Kitsu.database.get_show_meta', return_value={'art': '{}'}), \
             patch('resources.lib.WatchlistFlavor.Kitsu.database.get_unique_ids', return_value={}), \
             patch('resources.lib.endpoints.anilist.Anilist.get_enrichment_for_mal_ids', return_value=[al_item]), \
             patch('resources.lib.ui.control.getBool', side_effect=lambda k, default=False: True if 'paging' in k else False), \
             patch('resources.lib.ui.control.getInt', side_effect=lambda k, default=0: 1 if 'perpage.watchlist' in k else 0):
            # Watchlist list view + paging item
            items = self.kw.get_watchlist_status('current', next_up=False, offset=0, page=1)
            self.assertGreaterEqual(len(items), 1)
            self.assertTrue(mock_save.called)

        # Next Up view + paging + build_next_up_episode + movie branch in _base_watchlist_view
        with patch.object(self.kw, '_should_refresh_cache'), \
             patch.object(db_mod, 'is_watchlist_cache_valid', return_value=True), \
             patch.object(db_mod, 'get_watchlist_cache_count', return_value=3), \
             patch.object(db_mod, 'get_watchlist_cache', return_value=[{'data': db_mod.dumps(cached_item)}]), \
             patch('resources.lib.WatchlistFlavor.Kitsu.get_meta.collect_meta'), \
             patch('resources.lib.endpoints.anilist.Anilist.get_enrichment_for_mal_ids', return_value=[al_item]), \
             patch.object(self.kw, 'build_next_up_item', return_value={'name': 'AOT 01x04', 'url': 'play/16498/4'}), \
             patch('resources.lib.ui.control.getBool', side_effect=lambda k, default=False: True if 'paging' in k else False), \
             patch('resources.lib.ui.control.getInt', side_effect=lambda k, default=0: 1 if 'perpage.watchlist' in k else 0):
            nu_items = self.kw.get_watchlist_status('current', next_up=True, offset=0, page=1)
            self.assertGreaterEqual(len(nu_items), 1)
            self.assertEqual(self.kw.get_watchlist_status('current', next_up=False, offset=0, page=1, cache_only=True), [])

    def test_kitsu_mappings_completed_and_mutations(self):
        sample = _sample_kitsu_payload()
        # mapping_mal resolves first via in-memory self.mapping, second via SIMKLAPI fallback
        with patch('resources.lib.WatchlistFlavor.Kitsu.client.get', return_value=_mock_http(sample)):
            completed = self.kw.save_completed()
            self.assertEqual(completed, {'16498': 3})

        with patch('resources.lib.WatchlistFlavor.Kitsu.SIMKLAPI.get_mapping_ids_from_simkl', return_value={'mal_id': '52991'}), \
             patch('resources.lib.WatchlistFlavor.Kitsu.database.add_mapping_id') as mock_add_map:
            self.kw.mapping = []
            self.assertEqual(self.kw.mapping_mal('99999'), '52991')
            mock_add_map.assert_called_once_with('52991', 'kitsu_id', '99999')

        # get_watchlist_anime_entry + update_list_status / update_num_episodes / update_score / delete_anime (both create & update branches)
        with patch.object(self.kw, '_get_mapping_id', return_value='7442'), \
             patch('resources.lib.WatchlistFlavor.Kitsu.client.get', side_effect=[
                 _mock_http(sample),          # get_watchlist_anime_entry
                 _mock_http({'data': []}),    # update_list_status create branch
                 _mock_http({'data': [{'id': '101'}]}),  # update_list_status patch branch
                 _mock_http({'data': []}),    # update_num_episodes create branch
                 _mock_http({'data': [{'id': '101'}]}),  # update_num_episodes patch branch
                 _mock_http({'data': []}),    # update_score create branch
                 _mock_http({'data': [{'id': '101'}]}),  # update_score patch branch
                 _mock_http({'data': [{'id': '101'}]}),  # delete_anime existing branch
                 _mock_http({'data': []}),    # delete_anime missing branch
             ]), \
             patch('resources.lib.WatchlistFlavor.Kitsu.client.post', return_value=_mock_http({'data': {}})), \
             patch('resources.lib.WatchlistFlavor.Kitsu.client.patch', return_value=_mock_http({'data': {}})), \
             patch('resources.lib.WatchlistFlavor.Kitsu.client.delete', return_value=_mock_http({})), \
             patch('resources.lib.ui.database.clear_watchlist_cache'):
            entry = self.kw.get_watchlist_anime_entry(16498)
            self.assertEqual(entry['eps_watched'], 3)
            self.assertEqual(entry['total_episodes'], 25)

            self.assertTrue(self.kw.update_list_status(16498, 'completed'))
            self.assertTrue(self.kw.update_list_status(16498, 'current'))
            self.assertTrue(self.kw.update_num_episodes(16498, 4))
            self.assertTrue(self.kw.update_num_episodes(16498, 5))
            self.assertTrue(self.kw.update_score(16498, 0))
            self.assertTrue(self.kw.update_score(16498, 9))
            self.assertTrue(self.kw.delete_anime(16498))
            self.assertTrue(self.kw.delete_anime(16498))


if __name__ == '__main__':
    unittest.main()
