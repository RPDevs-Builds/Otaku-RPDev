import datetime
import os
import unittest
from unittest import mock

from resources.lib.ui import control, database


class TestEndpointsInit(unittest.TestCase):
    def test_dub_is_upcoming(self):
        from resources.lib.endpoints import _dub_is_upcoming

        future_dt = (datetime.datetime.now() + datetime.timedelta(days=2)).strftime('%Y-%m-%d %H:%M')
        past_dt = (datetime.datetime.now() - datetime.timedelta(days=2)).strftime('%Y-%m-%d %H:%M')

        self.assertTrue(_dub_is_upcoming(future_dt))
        self.assertFalse(_dub_is_upcoming(past_dt))
        # Unparseable treated as True
        self.assertTrue(_dub_is_upcoming("invalid-date"))
        self.assertTrue(_dub_is_upcoming(None))

    def test_get_second_label(self):
        from resources.lib.endpoints import get_second_label

        info = {'episode': 1, 'season': 1}
        future_dt = (datetime.datetime.now() + datetime.timedelta(days=1)).strftime('%Y-%m-%d %H:%M')
        dub_data = [{'season': 1, 'episode': 1, 'release_time': future_dt}]

        with mock.patch.object(control, 'getBool', side_effect=lambda k, **kw: False):
            # Normal dub match
            lbl = get_second_label(info, dub_data)
            self.assertEqual(lbl, f"Dub {future_dt}")

            # Dub episode mismatch
            no_match_dub = [{'season': 1, 'episode': 2, 'release_time': future_dt}]
            self.assertIsNone(get_second_label(info, no_match_dub))

            # Malformed dub data entries handled gracefully
            bad_dub = [{'season': 'abc', 'episode': None}]
            self.assertIsNone(get_second_label(info, bad_dub))

            # Missing episode in info
            self.assertIsNone(get_second_label({}, dub_data))

        # Filler enabled with filler string present
        with mock.patch.object(control, 'getBool', side_effect=lambda k, **kw: k == 'jz.filler'):
            lbl_filler = get_second_label(info, dub_data, filler="Filler")
            self.assertEqual(lbl_filler, "Filler")


class TestEndpointsAnimeSkip(unittest.TestCase):
    def test_get_episode_ids(self):
        from resources.lib.endpoints import anime_skip

        mock_resp = mock.MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            'data': {
                'findShowsByExternalId': [
                    {'episodes': [{'id': 'ep101', 'number': 1}, {'id': 'ep102', 'number': '2'}, {'id': 'bad', 'number': 'invalid'}]}
                ]
            }
        }

        with mock.patch('resources.lib.ui.client.post', return_value=mock_resp):
            ids = anime_skip.get_episode_ids('12345', 1)
            self.assertEqual(ids, ['ep101'])

            ids_ep2 = anime_skip.get_episode_ids('12345', 2)
            self.assertEqual(ids_ep2, ['ep102'])

        with mock.patch('resources.lib.ui.client.post', return_value=None):
            self.assertEqual(anime_skip.get_episode_ids('12345', 1), [])

    def test_get_time_stamps(self):
        from resources.lib.endpoints import anime_skip

        mock_resp = mock.MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            'data': {
                'findTimestampsByEpisodeId': [
                    {'at': 120.0, 'type': {'name': 'Intro'}},
                    {'at': 210.0, 'type': {'name': 'Canon'}}
                ]
            }
        }

        with mock.patch('resources.lib.ui.client.post', return_value=mock_resp):
            res = anime_skip.get_time_stamps(['ep101'])
            self.assertEqual(len(res), 2)

        with mock.patch('resources.lib.ui.client.post', return_value=None):
            self.assertEqual(anime_skip.get_time_stamps(['ep101']), [])

    def test_convert_time_stamps(self):
        from resources.lib.endpoints import anime_skip

        self.assertIsNone(anime_skip.convert_time_stamps(None, True, True))

        stamps = [
            {'at': 60, 'type': {'name': 'Intro'}},
            {'at': 150, 'type': {'name': 'Canon'}},
            {'at': 1200, 'type': {'name': 'Credits'}},
            {'at': 1290, 'type': {'name': 'Preview'}},
            {'at': None, 'type': {}}
        ]

        res = anime_skip.convert_time_stamps(stamps, intro=True, outro=True)
        self.assertEqual(res['intro'], {'start': 60, 'end': 150})
        self.assertEqual(res['outro'], {'start': 1200, 'end': 1290})

        # Intro only
        res_intro = anime_skip.convert_time_stamps(stamps, intro=True, outro=False)
        self.assertIn('intro', res_intro)
        self.assertNotIn('outro', res_intro)


class TestEndpointsAniSkip(unittest.TestCase):
    def test_fetch_and_get_skip_times(self):
        from resources.lib.endpoints import aniskip

        mock_resp = mock.MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {'found': True, 'results': [{'skipType': 'op', 'interval': {'startTime': 10, 'endTime': 100}}]}

        with mock.patch('resources.lib.ui.client.get', return_value=mock_resp):
            data = aniskip._fetch_skip_times(1234, 1, 'op')
            self.assertEqual(data['found'], True)

        with mock.patch('resources.lib.ui.client.get', return_value=None):
            self.assertIsNone(aniskip._fetch_skip_times(1234, 1, 'op'))

        with mock.patch('resources.lib.ui.database.get', return_value={'cached': True}) as mock_db_get:
            cached = aniskip.get_skip_times(1234, 1, 'op')
            self.assertEqual(cached, {'cached': True})
            mock_db_get.assert_called_once()


class TestEndpointsMDBList(unittest.TestCase):
    def test_mdblist_api(self):
        from resources.lib.endpoints.mdblist import MDBListAPI, get_ratings_for_mal_ids, get_rating_for_mal_id

        # Case 1: no api key
        with mock.patch('resources.lib.ui.database.get_info', return_value=None):
            api_nokey = MDBListAPI()
            self.assertIsNone(api_nokey.api_key)
            self.assertEqual(api_nokey.get_ratings_batch([123]), {})

        # Case 2: with api key
        with mock.patch('resources.lib.ui.database.get_info', return_value={'api_key': 'testkey'}):
            api = MDBListAPI()
            self.assertEqual(api.api_key, 'testkey')

            # Empty input
            self.assertEqual(api.get_ratings_batch([]), {})
            self.assertEqual(api.get_ratings_batch([0, None]), {})

            mock_resp = mock.MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = [
                {
                    'ids': {'mal': 12345},
                    'score_average': 85,
                    'ratings': [
                        {'source': 'myanimelist', 'value': 8.5},
                        {'source': 'imdb', 'value': 8.2},
                        {'source': 'trakt', 'value': 80.0},
                        {'source': 'themoviedb', 'value': 86.0},
                        {'source': 'unknown', 'value': None}
                    ]
                }
            ]

            with mock.patch('resources.lib.ui.client.post', return_value=mock_resp):
                ratings = api.get_ratings_batch([12345])
                self.assertIn(12345, ratings)
                self.assertEqual(ratings[12345]['mal'], 8.5)
                self.assertEqual(ratings[12345]['imdb'], 8.2)
                self.assertEqual(ratings[12345]['trakt'], 8.0)
                self.assertEqual(ratings[12345]['tmdb'], 8.6)
                self.assertEqual(ratings[12345]['score_average'], 85)

                single = api.get_single_rating(12345)
                self.assertEqual(single['mal'], 8.5)

            # Single rating invalid id
            self.assertIsNone(api.get_single_rating(0))

            # Helper functions
            with mock.patch.object(MDBListAPI, 'get_ratings_batch', return_value={1: {'mal': 7.0}}):
                self.assertEqual(get_ratings_for_mal_ids([1]), {1: {'mal': 7.0}})
            with mock.patch.object(MDBListAPI, 'get_single_rating', return_value={'mal': 7.0}):
                self.assertEqual(get_rating_for_mal_id(1), {'mal': 7.0})


class TestEndpointsTeamup(unittest.TestCase):
    def test_match_episode(self):
        from resources.lib.endpoints.teamup import match_episode

        ep, season = match_episode("Show Title #12")
        self.assertEqual(ep, (12,))
        self.assertEqual(season, 0)

        ep_multi, season = match_episode("Show Title #1-3 Season 2")
        self.assertEqual(ep_multi, (1, 3))
        self.assertEqual(season, 2)

        ep_none, season_none = match_episode("Show Title Without Number")
        self.assertIsNone(ep_none)
        self.assertIsNone(season_none)

    def test_get_dub_data(self):
        from resources.lib.endpoints.teamup import get_dub_data

        self.assertIsNone(get_dub_data(en_title=None))

        mock_resp = mock.MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            'events': [
                {
                    'title': 'Test Show Season 1 #1',
                    'end_dt': '2026-11-20T12:00:00+00:00',
                    'notes': 'MAL: 12345\n<strong>episode:</strong> 1'
                },
                {
                    'title': 'Test Show #2-3',
                    'end_dt': '2026-11-21T12:00:00+00:00',
                    'notes': 'MAL: 12345'
                },
                {
                    'title': 'Different Show #1',
                    'end_dt': '2026-11-22T12:00:00+00:00',
                    'notes': 'MAL: 99999'
                }
            ]
        }

        with mock.patch('resources.lib.ui.client.get', return_value=mock_resp):
            dubs = get_dub_data(mal_id=12345, en_title="Test: Show!")
            self.assertIsNotNone(dubs)
            # Should have matched ep 1, and ep 2-3
            episodes = [d['episode'] for d in dubs]
            self.assertIn(1, episodes)
            self.assertIn('2', episodes)
            self.assertIn('3', episodes)


class TestEndpointsAnimeSchedule(unittest.TestCase):
    def test_get_route(self):
        from resources.lib.endpoints.animeschedule import get_route

        mock_resp = mock.MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            'anime': [{'route': 'test-anime-route'}]
        }

        with mock.patch('resources.lib.ui.client.get', return_value=mock_resp):
            self.assertEqual(get_route(1234), 'test-anime-route')

        with mock.patch('resources.lib.ui.client.get', return_value=None):
            self.assertEqual(get_route(1234), '')

    def test_add_to_list(self):
        from resources.lib.endpoints.animeschedule import add_to_list

        dub_list = []
        add_to_list(dub_list, 1, "2026-11-20T14:30:00+00:00")
        self.assertEqual(len(dub_list), 1)
        self.assertEqual(dub_list[0]['episode'], 1)
        self.assertEqual(dub_list[0]['season'], 0)

        # Invalid date handled without crash
        add_to_list(dub_list, 2, "not-a-date")
        self.assertEqual(len(dub_list), 1)

    def test_get_dub_time(self):
        from resources.lib.endpoints.animeschedule import get_dub_time

        # No show in db
        with mock.patch('resources.lib.ui.database.get_show', return_value=None):
            self.assertEqual(get_dub_time(1234), [])

        # Show with existing route
        fake_show = {'anime_schedule_route': 'my-route', 'kodi_meta': '{}'}
        html = """
        <div class="release-time-wrapper">
            Dub:
            <span>Episodes 1-2</span>
            <time datetime="2026-11-20T12:00:00Z"></time>
        </div>
        """
        mock_resp = mock.MagicMock()
        mock_resp.text = html

        with mock.patch('resources.lib.ui.database.get_show', return_value=fake_show), \
             mock.patch('resources.lib.ui.client.get', return_value=mock_resp):
            dubs = get_dub_time(1234)
            self.assertEqual(len(dubs), 2)
            self.assertEqual(dubs[0]['episode'], 1)
            self.assertEqual(dubs[1]['episode'], 2)


class TestEndpointsMal(unittest.TestCase):
    def test_mal_methods(self):
        from resources.lib.endpoints.mal import Mal

        mal = Mal()

        mock_resp = mock.MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            'data': [{'title': 'Anime A'}],
            'pagination': {'has_next_page': False}
        }

        with mock.patch('resources.lib.ui.client.get', return_value=mock_resp):
            res = mal.get_base_res("http://example.com/api")
            self.assertEqual(res, mock_resp.json.return_value)

            cal_res = mal.get_airing_calendar_res('monday', page=1)
            self.assertEqual(cal_res['data'][0]['title'], 'Anime A')

        with mock.patch.object(Mal, 'get_airing_calendar_res', return_value=mock_resp.json.return_value), \
             mock.patch.object(Mal, 'set_cached_data') as mock_set:
            mal.update_calendar(page=1)
            mock_set.assert_called()

        with mock.patch('os.path.exists', return_value=False):
            self.assertIsNone(mal.get_cached_data())

        with mock.patch('resources.lib.ui.control.atomic_write_json') as mock_write:
            mal.set_cached_data({'test': 1})
            mock_write.assert_called_once()


class TestEndpointsMalSync(unittest.TestCase):
    def test_malsync_functions(self):
        from resources.lib.endpoints import malsync

        sample_data = {
            'title': 'Main Title',
            'Sites': {
                'Gogoanime': {'slug1': {'url': 'https://gogo/anime-1', 'title': 'Gogo Title'}},
                'animepahe': {'slug2': {'url': 'https://pahe/anime-2', 'title': 'Pahe Title'}}
            }
        }

        mock_resp = mock.MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = sample_data

        with mock.patch('resources.lib.ui.client.get', return_value=mock_resp):
            fetched = malsync.fetch_mal_anime(123)
            self.assertEqual(fetched['title'], 'Main Title')

        # get_slugs
        slugs_gogo = malsync.get_slugs(123, site='Gogoanime', mal_data=sample_data)
        self.assertEqual(slugs_gogo, ['https://gogo/anime-1'])
        self.assertEqual(malsync.get_slugs(123, site='Unknown', mal_data=sample_data), [])

        # get_title
        self.assertEqual(malsync.get_title(123, site='Gogoanime', mal_data=sample_data), 'Gogo Title')
        self.assertIsNone(malsync.get_title(123, site='NonExistent', mal_data=sample_data))

        # get_label_title
        self.assertEqual(malsync.get_label_title(123, site='animepahe', mal_data=sample_data), 'Pahe Title')
        self.assertEqual(malsync.get_label_title(123, site='Zoro', mal_data=sample_data), 'Main Title')


class TestEndpointsSimkl(unittest.TestCase):
    def test_simkl_methods(self):
        from resources.lib.endpoints.simkl import Simkl

        simkl = Simkl()
        with mock.patch('resources.lib.ui.control.atomic_write_json') as mock_write:
            simkl.set_cached_data([{'simkl': True}])
            mock_write.assert_called_once()

        with mock.patch('os.path.exists', return_value=False):
            self.assertIsNone(simkl.get_cached_data())

        entry = {
            'ids': {'mal': '1234'},
            'date': '2024-01-01T00:00:00+00:00',
            'episode': {'episode': 12}
        }
        mock_resp = mock.MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = [entry]

        with mock.patch('resources.lib.ui.client.get', return_value=mock_resp), \
             mock.patch.object(simkl, 'get_cached_data', return_value=None), \
             mock.patch.object(simkl, 'set_cached_data'):
            ep_num = simkl.get_calendar_data(1234)
            self.assertEqual(ep_num, 12)
            found_entry = simkl.fetch_and_find_simkl_entry(1234)
            self.assertEqual(found_entry, entry)

        with mock.patch('resources.lib.ui.client.get', return_value=mock_resp), \
             mock.patch.object(simkl, 'set_cached_data') as mock_set:
            simkl.update_calendar()
            mock_set.assert_called_once_with([entry])


class TestEndpointsTMDB(unittest.TestCase):
    def test_tmdb_functions(self):
        from resources.lib.endpoints import tmdb

        # searchByTitle
        mock_search_resp = mock.MagicMock()
        mock_search_resp.ok = True
        mock_search_resp.json.return_value = {'results': [{'id': 999}]}
        with mock.patch('resources.lib.ui.client.get', return_value=mock_search_resp):
            self.assertEqual(tmdb.searchByTitle('Test Movie', 'movies'), 999)
        self.assertIsNone(tmdb.searchByTitle('', 'movies'))

        # get_episode_titles
        mock_trans_resp = mock.MagicMock()
        mock_trans_resp.ok = True
        mock_trans_resp.json.return_value = {
            'translations': [
                {'iso_639_1': 'en', 'data': {'name': 'Episode English'}},
                {'iso_639_1': 'ja', 'data': {'name': 'Episode Japanese'}}
            ]
        }
        with mock.patch('resources.lib.ui.client.get', return_value=mock_trans_resp):
            titles = tmdb.get_episode_titles(999, 1, 1)
            self.assertEqual(titles, ['Episode English'])

        # getArt
        mock_art_resp = mock.MagicMock()
        mock_art_resp.ok = True
        mock_art_resp.json.return_value = {
            'backdrops': [{'file_path': '/bd.jpg', 'iso_639_1': 'en'}],
            'posters': [{'file_path': '/post.jpg'}],
            'logos': [{'file_path': '/logo.png'}]
        }
        with mock.patch('resources.lib.ui.client.get', return_value=mock_art_resp):
            art = tmdb.getArt({'themoviedb_id': 999}, 'movies')
            self.assertIn('fanart', art)
            self.assertIn('poster', art)
            self.assertIn('clearlogo', art)
            self.assertIn('thumb', art)


class TestEndpointsTVDB(unittest.TestCase):
    def test_tvdb_functions(self):
        from resources.lib.endpoints import tvdb

        # _fetch_tvdb_token
        mock_login_resp = mock.MagicMock()
        mock_login_resp.ok = True
        mock_login_resp.json.return_value = {'data': {'token': 'secret-token'}}
        with mock.patch('resources.lib.ui.client.post', return_value=mock_login_resp):
            tok = tvdb._fetch_tvdb_token('testkey')
            self.assertEqual(tok, 'secret-token')

        # get_auth_token with cached token
        with mock.patch.object(tvdb, 'api_key', 'somekey'), \
             mock.patch('resources.lib.ui.database.get', return_value='db-token'):
            tvdb._cached_token = None
            tvdb._token_expiry = 0
            token = tvdb.get_auth_token()
            self.assertEqual(token, 'db-token')
            # Second call uses memory cache
            self.assertEqual(tvdb.get_auth_token(), 'db-token')

        # searchByTitle
        mock_search = mock.MagicMock()
        mock_search.ok = True
        mock_search.json.return_value = {'data': [{'tvdb_id': 1234}]}
        with mock.patch.object(tvdb, 'get_auth_token', return_value='token123'), \
             mock.patch.object(tvdb, 'api_key', 'somekey'), \
             mock.patch('resources.lib.ui.client.get', return_value=mock_search):
            res_id = tvdb.searchByTitle('Test Anime', 'shows')
            self.assertEqual(res_id, 1234)

        # getArt
        mock_art_resp = mock.MagicMock()
        mock_art_resp.ok = True
        mock_art_resp.json.return_value = {
            'data': {
                'artworks': [
                    {'type': 3, 'image': 'https://art/fanart.jpg', 'language': 'eng'},
                    {'type': 2, 'image': '/poster.jpg', 'language': 'eng'},
                    {'type': 22, 'image': '/clearart.png', 'language': 'eng'},
                    {'type': 23, 'image': '/logo.png', 'language': 'eng'}
                ]
            }
        }
        with mock.patch.object(tvdb, 'get_auth_token', return_value='token123'), \
             mock.patch('resources.lib.ui.client.get', return_value=mock_art_resp):
            art = tvdb.getArt({'thetvdb_id': 1234}, 'shows')
            self.assertIn('fanart', art)
            self.assertIn('poster', art)
            self.assertIn('clearart', art)
            self.assertIn('clearlogo', art)


class TestEndpointsAnimeFiller(unittest.TestCase):
    def test_anime_filler(self):
        from resources.lib.endpoints import anime_filler

        html = """
        <table class="EpisodeList">
            <tbody>
                <tr><td>1</td><td><span>Manga Canon</span></td></tr>
                <tr><td>2</td><td><span>Filler</span></td></tr>
            </tbody>
        </table>
        """
        mock_resp = mock.MagicMock()
        mock_resp.text = html

        with mock.patch('resources.lib.ui.client.get', return_value=mock_resp):
            res = anime_filler._fetch_filler_data('Naruto')
            self.assertEqual(res, ['Manga Canon', 'Filler'])

        self.assertEqual(anime_filler.get_data(''), [])
        with mock.patch('resources.lib.ui.database.get', return_value=['Filler']):
            self.assertEqual(anime_filler.get_data('Naruto'), ['Filler'])


class TestEndpointsFanart(unittest.TestCase):
    def test_fanart_getArt(self):
        from resources.lib.endpoints import fanart

        mock_resp = mock.MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            'showbackground': [{'url': 'http://fanart/bg.jpg', 'lang': 'en'}],
            'tvthumb': [{'url': 'http://fanart/thumb.jpg', 'lang': 'en'}],
            'clearart': [{'url': 'http://fanart/clear.png', 'lang': 'en'}],
            'clearlogo': [{'url': 'http://fanart/logo.png', 'lang': 'en', 'id': '1'}]
        }

        with mock.patch('resources.lib.ui.client.get', return_value=mock_resp):
            art = fanart.getArt({'thetvdb_id': 123}, 'shows')
            self.assertIn('fanart', art)
            self.assertIn('thumb', art)
            self.assertIn('clearart', art)
            self.assertIn('clearlogo', art)

            # Movie type
            mock_movie_resp = mock.MagicMock()
            mock_movie_resp.ok = True
            mock_movie_resp.json.return_value = {
                'moviebackground': [{'url': 'http://fanart/mbg.jpg', 'lang': 'en'}],
                'moviethumb': [{'url': 'http://fanart/mthumb.jpg', 'lang': 'en'}]
            }
            with mock.patch('resources.lib.ui.client.get', return_value=mock_movie_resp):
                mart = fanart.getArt({'themoviedb_id': 456}, 'movies')
                self.assertIn('fanart', mart)
                self.assertIn('thumb', mart)


class TestEndpointsAnilist(unittest.TestCase):
    def test_anilist_methods(self):
        from resources.lib.endpoints.anilist import Anilist, get_anilist_ratings_for_mal_ids

        anilist = Anilist()

        # get_anilist_by_mal_ids
        self.assertEqual(anilist.get_anilist_by_mal_ids([]), [])
        self.assertEqual(anilist.get_anilist_by_mal_ids(['bad', None]), [])

        mock_page_resp = mock.MagicMock()
        mock_page_resp.ok = True
        mock_page_resp.json.return_value = {
            'data': {
                'Media': {'bannerImage': 'http://banner.jpg'},
                'Page': {
                    'pageInfo': {'hasNextPage': False, 'total': 1},
                    'media': [
                        {
                            'id': 100,
                            'idMal': 1234,
                            'title': {'romaji': 'Show Romaji', 'english': 'Show English'},
                            'coverImage': {'extraLarge': 'http://cover.jpg'},
                            'bannerImage': 'http://banner.jpg',
                            'averageScore': 82,
                            'description': 'Show synopsis',
                            'episodes': 12,
                            'status': 'FINISHED',
                            'genres': ['Action'],
                            'duration': 24,
                            'countryOfOrigin': 'JP',
                            'format': 'TV',
                            'startDate': {'year': 2024, 'month': 1, 'day': 1},
                            'characters': {'edges': []}
                        }
                    ]
                }
            }
        }

        with mock.patch('resources.lib.ui.client.request', return_value=mock_page_resp), \
             mock.patch('resources.lib.ui.client.post', return_value=mock_page_resp):
            res = anilist.get_anilist_by_mal_ids([1234])
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0]['idMal'], 1234)

            # ratings
            ratings = anilist.get_anilist_ratings_batch([1234])
            self.assertIn(1234, ratings)
            self.assertEqual(ratings[1234], {'anilist_score': 82})

            # banners
            banners = anilist.get_banners_batch([1234])
            self.assertEqual(banners.get(1234), 'http://banner.jpg')

            # single banner
            b = anilist.get_banner(1234)
            self.assertEqual(b, 'http://banner.jpg')

            # synopsis
            synopsis = anilist.get_synopsis_by_mal_ids([1234])
            self.assertEqual(synopsis.get(1234), 'Show synopsis')

            # enrichment
            enrichment = anilist.get_enrichment_for_mal_ids([1234])
            self.assertEqual(len(enrichment), 1)
            self.assertEqual(enrichment[0]['idMal'], 1234)

            # convenience function
            ratings_convenience = get_anilist_ratings_for_mal_ids([1234])
            self.assertIn(1234, ratings_convenience)


class TestIndexersInit(unittest.TestCase):
    def test_pick_art_str(self):
        from resources.lib.indexers import _pick_art_str

        self.assertEqual(_pick_art_str('http://art.jpg'), 'http://art.jpg')
        self.assertEqual(_pick_art_str(['', 'http://art2.jpg']), 'http://art2.jpg')
        self.assertEqual(_pick_art_str(('http://art3.jpg',)), 'http://art3.jpg')
        self.assertEqual(_pick_art_str('   '), '')
        self.assertEqual(_pick_art_str([]), '')
        self.assertEqual(_pick_art_str(None), '')

    def test_apply_spoiler_shield(self):
        from resources.lib.indexers import _apply_spoiler_shield

        parsed = {
            'image': {
                'fanart': 'http://fanart.jpg',
                'poster': 'http://poster.jpg',
                'thumb': 'http://thumb.jpg'
            }
        }

        with mock.patch.object(control, 'getInt', return_value=0):
            _apply_spoiler_shield(parsed)
            self.assertEqual(parsed['image']['thumb'], 'http://fanart.jpg')

        with mock.patch.object(control, 'getInt', return_value=1):
            _apply_spoiler_shield(parsed)
            self.assertEqual(parsed['image']['thumb'], 'http://poster.jpg')

    def test_should_hide_unaired_episode(self):
        from resources.lib.indexers import should_hide_unaired_episode

        future_date = (datetime.date.today() + datetime.timedelta(days=10)).isoformat()
        past_date = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()

        # Disabled setting -> always returns False
        with mock.patch.object(control, 'getBool', return_value=False):
            self.assertFalse(should_hide_unaired_episode(future_date))

        # Enabled setting
        with mock.patch.object(control, 'getBool', return_value=True):
            self.assertTrue(should_hide_unaired_episode(future_date))
            self.assertFalse(should_hide_unaired_episode(past_date))
            self.assertFalse(should_hide_unaired_episode(''))
            self.assertFalse(should_hide_unaired_episode('bad-date'))

    def test_get_diff(self):
        from resources.lib.indexers import get_diff

        five_days_ago = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
        ep = {'last_updated': five_days_ago}
        update_time, diff = get_diff(ep)
        self.assertEqual(diff, 5)

    def test_parse_and_process_episodes(self):
        from resources.lib.indexers import parse_episodes, process_episodes

        kodi_meta = database.dumps({
            'name': 'Episode 1',
            'info': {'episode': 1, 'season': 1, 'aired': '2020-01-01', 'title': 'Pilot'}
        })
        res = {'kodi_meta': kodi_meta, 'number': 1, 'filler': ''}

        with mock.patch.object(control, 'getBool', side_effect=lambda k, **kw: False):
            parsed = parse_episodes(res, eps_watched=1)
            self.assertEqual(parsed['info']['playcount'], 1)

            results = process_episodes([res], eps_watched=1)
            self.assertEqual(len(results), 1)

    def test_process_dub(self):
        from resources.lib.indexers import process_dub

        # Teamup branch (api == 0)
        with mock.patch('resources.lib.ui.database.get_show_data', return_value=None), \
             mock.patch.object(control, 'getInt', return_value=0), \
             mock.patch('resources.lib.endpoints.teamup.get_dub_data', return_value=[{'episode': 1}]), \
             mock.patch('resources.lib.ui.database.update_show_data'):
            dubs = process_dub(1234, 'Test Show')
            self.assertEqual(dubs, [{'episode': 1}])

        # AnimeSchedule branch (api == 1)
        with mock.patch('resources.lib.ui.database.get_show_data', return_value=None), \
             mock.patch.object(control, 'getInt', return_value=1), \
             mock.patch('resources.lib.endpoints.animeschedule.get_dub_time', return_value=[{'episode': 2}]), \
             mock.patch('resources.lib.ui.database.update_show_data'):
            dubs2 = process_dub(1234, 'Test Show')
            self.assertEqual(dubs2, [{'episode': 2}])

        # Cached branch
        today_iso = datetime.date.today().isoformat()
        cached_show = {'last_updated': today_iso, 'data': database.dumps({'dub_data': [{'episode': 3}]})}
        with mock.patch('resources.lib.ui.database.get_show_data', return_value=cached_show):
            dubs3 = process_dub(1234, 'Test Show')
            self.assertEqual(dubs3, [{'episode': 3}])

    def test_update_database(self):
        from resources.lib.indexers import update_database

        with mock.patch('resources.lib.ui.database.update_episode') as mock_update, \
             mock.patch.object(control, 'getBool', side_effect=lambda k, **kw: False):
            parsed = update_database(
                mal_id=123,
                update_time='2026-11-14',
                res={},
                url='123/1',
                image='http://art.jpg',
                info={'episode': 1, 'season': 1},
                season=1,
                episode=1,
                episodes=[],
                title='Episode 1',
                fanart='http://fanart.jpg',
                poster='http://poster.jpg',
                clearart='',
                clearlogo='',
                dub_data=None,
                filler=''
            )
            mock_update.assert_called_once()
            self.assertEqual(parsed['info']['episode'], 1)


class TestIndexersAPIs(unittest.TestCase):
    def tearDown(self):
        database.close_thread_connections()

    def test_anizip_api(self):
        from resources.lib.indexers.anizip import ANIZIPAPI

        api = ANIZIPAPI()
        mock_resp = mock.MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            'episodes': {
                '1': {'episode': '1', 'title': {'en': 'Pilot'}, 'overview': 'Intro', 'rating': '8.5', 'airDate': '2024-01-01', 'seasonNumber': 1}
            }
        }

        with mock.patch('resources.lib.ui.client.get', return_value=mock_resp):
            info = api.get_anime_info(123)
            self.assertIn('episodes', info)

        show_meta = {'kodi_meta': database.dumps({'status': 'Airing', 'ename': 'Show', 'title_userPreferred': 'Show'}), 'unique_ids': {}}
        with mock.patch('resources.lib.ui.database.get_show', return_value=show_meta), \
             mock.patch('resources.lib.ui.database.get_unique_ids', return_value={}), \
             mock.patch('resources.lib.indexers.update_database', return_value={'info': {'episode': 1}}):
            parsed = api.parse_episode_view(
                res={'episode': '1', 'title': {'en': 'Pilot'}, 'overview': 'Intro', 'rating': '8.5', 'airDate': '2024-01-01'},
                mal_id=123,
                season=1,
                poster='http://poster.jpg',
                fanart='http://fanart.jpg',
                clearart='',
                clearlogo='',
                eps_watched=0,
                update_time='2024-01-01',
                tvshowtitle='Show',
                dub_data=None,
                filler_data=None
            )
            self.assertEqual(parsed['info']['episode'], 1)

    def test_anidb_api(self):
        from resources.lib.indexers.anidb import ANIDBAPI

        api = ANIDBAPI()
        with mock.patch('resources.lib.ui.database.get_mappings', return_value={'anidb_id': '456'}):
            self.assertEqual(api.get_anidb_id(123), '456')

        xml_data = "<anime><episode id='101'><epno>1</epno><title xml:lang='en'>Pilot</title></episode></anime>"
        mock_resp = mock.MagicMock()
        mock_resp.text = xml_data
        with mock.patch('resources.lib.ui.database.get_mappings', return_value={'anidb_id': '456'}), \
             mock.patch('resources.lib.ui.client.get', return_value=mock_resp), \
             mock.patch.object(control, 'getInt', return_value=0), \
             mock.patch.object(control, 'setInt'):
            meta = api.get_episode_meta(123)
            self.assertEqual(len(meta['episodes']), 1)

    def test_kitsu_api(self):
        from resources.lib.indexers.kitsu import KitsuAPI

        api = KitsuAPI()
        with mock.patch('resources.lib.ui.database.get_mappings', return_value={'kitsu_id': '789'}):
            self.assertEqual(api.get_kitsu_id(123), '789')

        mock_resp = mock.MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            'data': [{'id': '1', 'attributes': {'number': 1, 'canonicalTitle': 'Episode 1'}}],
            'links': {}
        }
        with mock.patch('resources.lib.ui.client.get', return_value=mock_resp):
            ep_meta = api.get_episode_meta('789')
            self.assertEqual(len(ep_meta), 1)

    def test_jikan_api(self):
        from resources.lib.indexers.jikanmoe import JikanAPI

        api = JikanAPI()
        info_resp = mock.MagicMock()
        info_resp.json.return_value = {
            'data': {'synopsis': 'Great anime synopsis', 'title': 'Pilot'}
        }
        ep_resp = mock.MagicMock()
        ep_resp.json.return_value = {
            'data': [{'mal_id': 1, 'title': 'Pilot'}],
            'pagination': {'has_next_page': False}
        }
        with mock.patch('resources.lib.ui.client.get', side_effect=[info_resp, info_resp, ep_resp]):
            info = api.get_anime_info(123)
            self.assertIsNotNone(info)
            synopsis = api.get_anime_synopsis(123)
            self.assertEqual(synopsis, 'Great anime synopsis')
            ep_meta = api.get_episode_meta(123)
            self.assertEqual(len(ep_meta), 1)

    def test_simkl_api(self):
        from resources.lib.indexers.simkl import SIMKLAPI

        api = SIMKLAPI()
        mock_search_resp = mock.MagicMock()
        mock_search_resp.json.return_value = [{'ids': {'simkl': '333'}}]
        mock_ep_resp = mock.MagicMock()
        mock_ep_resp.json.return_value = [{'title': 'Episode 1', 'episode': 1}]

        with mock.patch('resources.lib.ui.client.get', side_effect=[mock_search_resp, mock_ep_resp]), \
             mock.patch('resources.lib.ui.database.get_show', return_value={'simkl_id': '333', 'mal_id': 123}):
            simkl_id = api.get_id('mal', 123)
            self.assertEqual(simkl_id, '333')
            meta = api.get_episode_meta(123)
            self.assertEqual(len(meta), 1)

    def test_otaku_api_and_next_up(self):
        from resources.lib.indexers.otaku import OtakuAPI
        from resources.lib.indexers.otaku_next_up import Otaku_Next_Up_API

        otaku = OtakuAPI()
        self.assertIsNotNone(otaku.baseUrl)

        next_up = Otaku_Next_Up_API()
        self.assertIsInstance(next_up, OtakuAPI)

        # Meta extraction helpers
        with mock.patch('resources.lib.ui.database.get_mappings', return_value={'kitsu_id': '1', 'anidb_id': '2'}), \
             mock.patch('resources.lib.ui.database.get_show', return_value={'simkl_id': '3'}):
            self.assertEqual(otaku.get_kitsu_id(123), '1')
            self.assertEqual(otaku.get_anidb_id(123), '2')
            self.assertEqual(otaku.get_simkl_id(123), '3')

        with mock.patch('resources.lib.indexers.anizip.ANIZIPAPI.get_anime_info', return_value={'episodes': {}}):
            self.assertEqual(otaku.get_anizip_episode_meta(123), [])


if __name__ == '__main__':
    unittest.main()
