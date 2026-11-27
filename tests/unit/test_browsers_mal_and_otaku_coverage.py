"""High-coverage unit tests for OtakuBrowser, MalBrowser, and AniListBrowser."""
# -*- coding: utf-8 -*-

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from resources.lib.AniListBrowser import AniListBrowser, _apply_mal_picture_to_anime
from resources.lib.MalBrowser import MalBrowser
from resources.lib.OtakuBrowser import OtakuBrowser
from resources.lib.ui import control, database


def _sample_mal_anime(mal_id=52991, episodes=28):
    return {
        'mal_id': mal_id,
        'title': 'Sousou no Frieren',
        'title_english': "Frieren: Beyond Journey's End",
        'synopsis': 'Elf mage journey.',
        'type': 'TV',
        'episodes': episodes,
        'status': 'Finished Airing',
        'rating': 'PG-13 - Teens 13 or older',
        'duration': '24 min per ep',
        'score': 9.3,
        'scored_by': 500000,
        'genres': [{'name': 'Adventure'}, {'name': 'Fantasy'}],
        'studios': [{'name': 'Madhouse'}],
        'aired': {'from': '2023-09-29T00:00:00+00:00'},
        'year': 2023,
        'trailer': {'youtube_id': 'ZEkwCGJ3o7M'},
        'images': {'webp': {'large_image_url': 'https://cdn.example/frieren.webp'}},
    }


def _sample_anilist_media(al_id=154587, mal_id=52991, episodes=28):
    return {
        'id': al_id,
        'idMal': mal_id,
        'title': {'romaji': 'Sousou no Frieren', 'english': "Frieren: Beyond Journey's End"},
        'coverImage': {'extraLarge': 'https://cdn.anilist/frieren.jpg'},
        'bannerImage': 'https://cdn.anilist/banner.jpg',
        'startDate': {'year': 2023, 'month': 9, 'day': 29},
        'description': '<i>Elf</i><br>journey\nstory.',
        'synonyms': ['Frieren'],
        'format': 'TV',
        'episodes': episodes,
        'status': 'FINISHED',
        'genres': ['Adventure', 'Fantasy'],
        'duration': 24,
        'countryOfOrigin': 'JP',
        'averageScore': 91,
        'stats': {'scoreDistribution': [{'score': 90, 'amount': 1200}]},
        'trailer': {'id': 'ZEkwCGJ3o7M', 'site': 'youtube'},
        'characters': {
            'edges': [{
                'node': {'name': {'userPreferred': 'Frieren'}},
                'voiceActors': [{'name': {'userPreferred': 'Atsumi Tanezaki'}, 'image': {'large': 'https://cdn/va.jpg'}}],
            }]
        },
        'studios': {'edges': [{'isMain': True, 'node': {'name': 'Madhouse'}}]},
    }


class TestOtakuBrowserCoverage(unittest.TestCase):
    """Exercise combined MAL+AniList enrichment, flattening, movie/series branching & update paths."""

    def test_otaku_browser_flatten_process_view_and_database_update(self):
        ob = OtakuBrowser()
        mal_item = _sample_mal_anime(mal_id=52991, episodes=28)
        al_item = _sample_anilist_media(al_id=154587, mal_id=52991, episodes=28)

        # _flatten_mal_data_items extracts top-level and nested 'entry' items
        flattened = ob._flatten_mal_data_items({'data': [{'entry': [mal_item]}, mal_item]})
        self.assertGreaterEqual(len(flattened), 1)

        with patch('resources.lib.OtakuBrowser.get_meta.collect_meta'), \
             patch('resources.lib.OtakuBrowser.database.get_show', return_value=None), \
             patch('resources.lib.OtakuBrowser.database.update_show') as mock_upd, \
             patch('resources.lib.OtakuBrowser.database.get_show_meta', return_value={'art': json.dumps({'banner': 'b.jpg', 'thumb': ['t.jpg'], 'clearart': ['ca.png'], 'clearlogo': ['cl.png'], 'fanart': 'fa.jpg'})}), \
             patch('resources.lib.OtakuBrowser.database.get_unique_ids', return_value={'tvdb_id': '42'}), \
             patch('resources.lib.OtakuBrowser.database.get_anilist_enrichment_batch', return_value={52991: al_item}), \
             patch.object(ob, 'open_completed', return_value={'52991': 1}), \
             patch.object(ob, '_merge_offline_metadata_into_kodi_meta', side_effect=lambda mid, km: km):
            res_dict = {'data': [mal_item], 'pagination': {'has_next_page': False}}
            views = ob.process_otaku_view(res_dict, 'plugin://test/', page=1)
            self.assertGreaterEqual(len(views), 1)
            self.assertEqual(views[0]['url'], 'animes/52991/')
            self.assertEqual(views[0]['info']['mediatype'], 'tvshow')
            mock_upd.assert_called()

            # Single-episode movie branch in base_otaku_view / base_mal_view
            movie_mal = _sample_mal_anime(mal_id=16498, episodes=1)
            movie_view = ob.base_mal_view(movie_mal, completed={})
            self.assertEqual(movie_view['url'], 'play_movie/16498/')
            self.assertEqual(movie_view['info']['mediatype'], 'movie')

            # Combined database_update_show fills missing fields from AniList
            ob.database_update_show(mal_res={'mal_id': 99999, 'title': 'Partial', 'images': {'webp': {}}}, anilist_res=al_item)
            self.assertGreaterEqual(mock_upd.call_count, 2)

    def test_otaku_browser_recommendations_relations_and_base_res(self):
        ob = OtakuBrowser()
        mal_item = _sample_mal_anime()
        ok_resp = MagicMock(ok=True, text='{}')
        ok_resp.json.return_value = {'data': {'mal_id': 52991}}
        with patch('resources.lib.OtakuBrowser.client.get', return_value=ok_resp), \
             patch('resources.lib.OtakuBrowser.client.post', return_value=MagicMock(ok=True, text='{"data":{"Page":{"ANIME":[]}}}', json=MagicMock(return_value={'data': {'Page': {'ANIME': []}}}))):
            self.assertEqual(ob.get_mal_base_res('https://api.jikan.moe/v4/anime/52991'), {'data': {'mal_id': 52991}})
            self.assertEqual(ob.get_anilist_base_res({'page': 1}), [])

        def _ob_db_get(fn, ttl, url, *args, **kwargs):
            if '/recommendations' in str(url):
                return {'data': [{'entry': mal_item, 'votes': 9}], 'pagination': {'has_next_page': False}}
            if '/relations' in str(url):
                rel_entry = dict(mal_item, type='anime')
                return {'data': [{'relation': 'Sequel', 'entry': [rel_entry]}], 'pagination': {'has_next_page': False}}
            return {'data': mal_item}

        with patch('resources.lib.OtakuBrowser.database.get', side_effect=_ob_db_get), \
             patch('resources.lib.OtakuBrowser.get_meta.collect_meta'), \
             patch('resources.lib.OtakuBrowser.database.get_show', return_value={'kodi_meta': '{}'}), \
             patch('resources.lib.OtakuBrowser.database.get_show_meta', return_value=None), \
             patch('resources.lib.OtakuBrowser.database.get_unique_ids', return_value={}), \
             patch('resources.lib.OtakuBrowser.database.get_anilist_enrichment_batch', return_value={}), \
             patch('resources.lib.OtakuBrowser.control.sleep'), \
             patch.object(ob, 'open_completed', return_value={}):
            recs = ob.get_recommendations(100, 1)
            self.assertEqual(len(recs), 1)
            rels = ob.get_relations(100)
            self.assertEqual(len(rels), 1)


class TestMalBrowserCoverage(unittest.TestCase):
    """Exercise MalBrowser genres, date window ranking, search, watch order, reviews, stats & peek."""

    def test_mal_browser_season_date_params_filters_and_genres_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gfile = os.path.join(tmpdir, 'genres.json')
            with open(gfile, 'w', encoding='utf-8') as f:
                json.dump({'selected_genres_mal': ['1', '10']}, f)
            with patch.object(control, 'genre_json', gfile):
                mb = MalBrowser()
                self.assertEqual(mb.load_genres_from_json(), '1, 10')

        mb = MalBrowser()
        mb.status = 'airing'
        mb.rating = 'pg13'
        mb.genre = '1, 10'
        mb.format_in_type = 'tv'
        params = {}
        mb._apply_season_format_params(params, '')
        mb._apply_anime_type_params(params, 'movie')
        mb._apply_content_filters(params)
        self.assertEqual(params['filter'], 'tv')
        self.assertEqual(params['type'], 'movie')
        self.assertEqual(params['status'], 'airing')
        self.assertEqual(params['genres'], '1, 10')

        sy = mb.get_season_year('next')
        self.assertEqual(len(sy), 14)
        self.assertIn(sy[0], ('winter', 'spring', 'summer', 'fall'))

    def test_mal_browser_browse_ranked_airing_genre_search_and_details(self):
        mb = MalBrowser()
        sample = _sample_mal_anime(mal_id=52991, episodes=28)
        page_res = {'data': [sample], 'pagination': {'has_next_page': True}}

        def _mb_db_get(fn, ttl, url, *args, **kwargs):
            if str(url).endswith('/anime/52991'):
                return {'data': sample}
            return page_res

        with patch('resources.lib.MalBrowser.database.get', side_effect=_mb_db_get), \
             patch('resources.lib.MalBrowser.database.peek', return_value=page_res), \
             patch('resources.lib.MalBrowser.get_meta.collect_meta'), \
             patch('resources.lib.MalBrowser.database.get_show', return_value={'kodi_meta': '{}'}), \
             patch('resources.lib.MalBrowser.database.get_show_meta', return_value=None), \
             patch('resources.lib.MalBrowser.database.get_unique_ids', return_value={}), \
             patch.object(mb, 'open_completed', return_value={}):
            # Cover ranked presets, season airing, genre preset, trending/popular/voted/favourites/top_100
            self.assertTrue(len(mb.get_trending_this_year(1, 'tv')) >= 1)
            self.assertTrue(len(mb.get_popular_this_season(1, 'tv')) >= 1)
            self.assertTrue(len(mb.get_voted_last_year(1, 'tv')) >= 1)
            self.assertTrue(len(mb.get_favourites_all_time(1, 'tv')) >= 1) if hasattr(mb, 'get_favourites_all_time') else self.assertTrue(len(mb.get_all_time_favourites(1, 'tv')) >= 1)
            self.assertTrue(len(mb.get_top_100(1, 'tv')) >= 1)
            self.assertTrue(len(mb.get_airing_this_season(1, 'tv')) >= 1)
            self.assertTrue(len(mb._browse_genre_preset(1, 'tv', 'mal', 'genre_action', '1')) >= 1)
            self.assertTrue(len(mb.get_search('Frieren', 1, 'tv')) >= 1)

            # Recommendations, relations, single-item process_res & watch_order chiaki HTML
            chiaki_html = '<table><tr data-id="52991"><td>Main</td></tr></table>'
            chiaki_resp = MagicMock(ok=True, text=chiaki_html)
            with patch('resources.lib.MalBrowser.client.get', return_value=chiaki_resp):
                wo = mb.get_watch_order(52991)
                self.assertEqual(len(wo), 1)

            single = mb.process_res(sample)
            self.assertIsNotNone(single)

        # Reviews & statistics payload
        def _rev_stats_db_get(fn, ttl, url, *args, **kwargs):
            if '/reviews' in str(url):
                return {'data': [{'user': {'username': 'u1'}, 'review': 'Great!', 'score': 9, 'tags': ['Recommended'], 'date': '2026-01-01'}], 'pagination': {'has_next_page': False}}
            return {'data': {'watching': 10, 'completed': 20, 'total': 30, 'scores': []}}

        with patch('resources.lib.MalBrowser.database.get', side_effect=_rev_stats_db_get):
            rev = mb.get_reviews_page(52991, 1, 'show', 0)
            self.assertEqual(len(rev['reviews']), 1)
            stats = mb.get_statistics_payload(52991)
            self.assertEqual(stats['completed'], 20)


class TestAniListBrowserCoverage(unittest.TestCase):
    """Exercise AniListBrowser filters, ranked/season presets, reviews/stats & process_res."""

    def test_anilist_apply_mal_picture_and_season_helpers(self):
        anime = {'id': 154587, 'coverImage': {'extraLarge': 'orig.jpg'}}
        with patch('resources.lib.AniListBrowser.control.getBool', return_value=True), \
             patch('resources.lib.AniListBrowser.database.get_mappings', return_value={'mal_picture': '12/345.jpg'}):
            _apply_mal_picture_to_anime(anime)
        self.assertEqual(anime['coverImage']['extraLarge'], 'https://cdn.myanimelist.net/images/anime/12/345l.jpg')

        ab = AniListBrowser()
        self.assertEqual(ab._coerce_anilist_media_format('TV'), ['TV'])
        self.assertEqual(ab._coerce_anilist_media_format(['MOVIE']), ['MOVIE'])
        variables = {}
        ab.format_in_type = 'TV'
        ab.countryOfOrigin_type = 'JP'
        ab.status = 'FINISHED'
        ab.genre = ('Fantasy',)
        ab.tag = ('Magic',)
        ab._apply_common_list_variables(variables, None)
        self.assertEqual(variables['format'], ['TV'])
        self.assertEqual(variables['includedGenres'], ('Fantasy',))

    def test_anilist_ranked_season_genre_stats_reviews_and_base_res(self):
        ab = AniListBrowser()
        al_item = _sample_anilist_media(al_id=154587, mal_id=52991, episodes=28)
        al_page = {'pageInfo': {'hasNextPage': False}, 'ANIME': [al_item]}

        with patch('resources.lib.AniListBrowser.database.get', return_value=al_page), \
             patch('resources.lib.AniListBrowser.database.peek', return_value=al_page), \
             patch('resources.lib.AniListBrowser.get_meta.collect_meta'), \
             patch('resources.lib.AniListBrowser.database.get_show', return_value={'kodi_meta': '{}'}), \
             patch('resources.lib.AniListBrowser.database.get_show_meta', return_value=None), \
             patch('resources.lib.AniListBrowser.database.get_unique_ids', return_value={}), \
             patch.object(ab, 'open_completed', return_value={}):
            self.assertTrue(len(ab.get_airing_last_season(1, 'TV')) >= 1)
            self.assertTrue(len(ab.get_trending_this_year(1, 'TV')) >= 1)
            self.assertTrue(len(ab.get_popular_last_year(1, 'TV')) >= 1)
            self.assertTrue(len(ab.get_voted_this_season(1, 'TV')) >= 1)
            self.assertTrue(len(ab.get_favourites_this_year(1, 'TV')) >= 1) if hasattr(ab, 'get_favourites_this_year') else self.assertTrue(len(ab.get_all_time_popular(1, 'TV')) >= 1)
            self.assertTrue(len(ab.get_top_100(1, 'TV')) >= 1)
            self.assertTrue(len(ab._browse_genre_preset(1, 'TV', 'an', 'genre_action', 'Action')) >= 1)
            with self.assertRaises(ValueError):
                ab._ranked_media_list(1, 'TV', 'an', 'bad', 'TRENDING_DESC', period_mode='invalid')

        # Stats mapping across 10-point and 100-point buckets + HTTP get_base_res & get_anilist_res_with_mal_id
        mapped = ab._map_anilist_stats_to_stats_window({
            'statusDistribution': [{'status': 'CURRENT', 'amount': 50}, {'status': 'COMPLETED', 'amount': 150}],
            'scoreDistribution': [{'score': 90, 'amount': 100}, {'score': 8, 'amount': 20}],
        })
        self.assertEqual(mapped['watching'], 50)
        self.assertEqual(mapped['completed'], 150)
        self.assertEqual(mapped['total'], 200)

        gql_resp = MagicMock(ok=True, text='{"data": {"Page": {"ANIME": []}, "Media": {"id": 154587, "idMal": 52991}}}')
        gql_resp.json.return_value = {'data': {'Page': {'ANIME': []}, 'Media': al_item}}
        with patch('resources.lib.AniListBrowser.client.post', return_value=gql_resp), \
             patch('resources.lib.AniListBrowser.database.update_show'), \
             patch('resources.lib.AniListBrowser.get_meta.collect_meta'), \
             patch('resources.lib.AniListBrowser.database.get_show', return_value={'mal_id': 52991}):
            self.assertEqual(ab.get_base_res({'page': 1}), {'ANIME': []})
            self.assertEqual(ab.get_anilist_res_with_mal_id(52991)['id'], 154587)
            self.assertIsNotNone(ab.process_res(al_item))


if __name__ == '__main__':
    unittest.main()
