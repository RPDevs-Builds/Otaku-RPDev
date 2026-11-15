# -*- coding: utf-8 -*-
"""
test_introdb.py - Unit tests for IntroDB skip times endpoint and player integration
===================================================================================
Tests API fetching, local ID mapping, caching, data normalization, and fallback logic.
"""

import unittest
from unittest import mock

import conftest  # Kodi mock harness  # noqa: F401
from resources.lib.endpoints import introdb
from resources.lib.ui import client, control, database


class TestIntroDBEndpoint(unittest.TestCase):

    def test_resolve_imdb_and_season_from_mappings(self):
        with mock.patch.object(database, 'get_mappings', return_value={
            'imdb_id': 'tt5057932',
            'thetvdb_season': 2,
            'anime_media_type': 'tv'
        }):
            imdb_id, season, is_movie = introdb.resolve_imdb_and_season(12345, episode=1)
            self.assertEqual(imdb_id, 'tt5057932')
            self.assertEqual(season, 2)
            self.assertFalse(is_movie)

    def test_resolve_imdb_and_season_show_meta_fallback(self):
        with mock.patch.object(database, 'get_mappings', return_value={}), \
             mock.patch.object(database, 'get_show_meta', return_value={
                 'meta_ids': '{"imdb_id": "tt9999999"}'
             }):
            imdb_id, season, is_movie = introdb.resolve_imdb_and_season(12345, episode=1)
            self.assertEqual(imdb_id, 'tt9999999')
            self.assertEqual(season, 1)
            self.assertFalse(is_movie)

    def test_resolve_imdb_and_season_anizip_fallback(self):
        mock_resp = mock.MagicMock(ok=True)
        with mock.patch.object(database, 'get_mappings', return_value={}), \
             mock.patch.object(database, 'get_show_meta', return_value=None), \
             mock.patch.object(client, 'get', return_value=mock_resp), \
             mock.patch.object(control, 'safe_json', return_value={'mappings': {'imdb_id': 'tt7777777', 'type': 'Movie'}}):
            imdb_id, season, is_movie = introdb.resolve_imdb_and_season(12345, episode=1)
            self.assertEqual(imdb_id, 'tt7777777')
            self.assertEqual(season, 1)
            self.assertTrue(is_movie)

    def test_resolve_imdb_and_season_normalizations(self):
        for raw_s, expected_s in [('0', 1), (0, 1), ('a', 1), (None, 1), ('3', 3), (3, 3), (-5, 1)]:
            with mock.patch.object(database, 'get_mappings', return_value={
                'imdb_id': 'tt1234567',
                'thetvdb_season': raw_s,
                'anime_media_type': 'tv'
            }):
                _, season, _ = introdb.resolve_imdb_and_season(100, episode=1)
                self.assertEqual(season, expected_s)

    def test_resolve_empty_mal_id(self):
        imdb_id, season, is_movie = introdb.resolve_imdb_and_season(None)
        self.assertIsNone(imdb_id)
        self.assertEqual(season, 1)
        self.assertFalse(is_movie)

    def test_fetch_segments_tv_success(self):
        mock_resp = mock.MagicMock(ok=True)
        payload = {
            'imdb_id': 'tt1234567',
            'season': 1,
            'episode': 1,
            'intro': {'start_sec': 10.0, 'end_sec': 100.0, 'confidence': 0.95},
            'outro': {'start_sec': 1300.0, 'end_sec': 1390.0, 'confidence': 0.90},
            'recap': None,
            'post_credits': None
        }
        with mock.patch.object(client, 'get', return_value=mock_resp) as mock_get, \
             mock.patch.object(control, 'safe_json', return_value=payload):
            res = introdb._fetch_segments('tt1234567', season=1, episode=1, is_movie=False)
            self.assertEqual(res, payload)
            self.assertIn('season=1&episode=1', mock_get.call_args[0][0])

    def test_fetch_segments_movie_success(self):
        mock_resp = mock.MagicMock(ok=True)
        payload = {
            'imdb_id': 'tt1234567',
            'intro': None,
            'outro': {'start_sec': 5400.0, 'end_sec': 5700.0}
        }
        with mock.patch.object(client, 'get', return_value=mock_resp) as mock_get, \
             mock.patch.object(control, 'safe_json', return_value=payload):
            res = introdb._fetch_segments('tt1234567', season=1, episode=1, is_movie=True)
            self.assertEqual(res, payload)
            self.assertIn('is_movie=true', mock_get.call_args[0][0])

    def test_fetch_segments_not_found(self):
        mock_resp = mock.MagicMock(ok=False)
        with mock.patch.object(client, 'get', return_value=mock_resp):
            res = introdb._fetch_segments('tt0000000', 1, 1, False)
            self.assertIsNone(res)

    def test_fetch_segments_empty_json(self):
        mock_resp = mock.MagicMock(ok=True)
        with mock.patch.object(client, 'get', return_value=mock_resp), \
             mock.patch.object(control, 'safe_json', return_value={}):
            res = introdb._fetch_segments('tt0000000', 1, 1, False)
            self.assertIsNone(res)

    def test_fetch_segments_missing_imdb(self):
        res = introdb._fetch_segments(None, 1, 1, False)
        self.assertIsNone(res)

    def test_get_skip_times_op(self):
        sample_segments = {
            'intro': {'start_sec': 15.5, 'end_sec': 105.5},
            'outro': {'start_sec': 1350.0, 'end_sec': 1440.0}
        }
        with mock.patch.object(introdb, 'resolve_imdb_and_season', return_value=('tt123', 1, False)), \
             mock.patch.object(introdb, 'get_segments', return_value=sample_segments):
            res = introdb.get_skip_times(12345, episode=1, skip_type='op')
            self.assertIsNotNone(res)
            self.assertEqual(res['results'][0]['skipType'], 'op')
            self.assertEqual(res['results'][0]['interval']['startTime'], 15.5)
            self.assertEqual(res['results'][0]['interval']['endTime'], 105.5)

    def test_get_skip_times_ed(self):
        sample_segments = {
            'intro': None,
            'outro': {'start_sec': 1350.0, 'end_sec': 1440.0}
        }
        with mock.patch.object(introdb, 'resolve_imdb_and_season', return_value=('tt123', 1, False)), \
             mock.patch.object(introdb, 'get_segments', return_value=sample_segments):
            res = introdb.get_skip_times(12345, episode=1, skip_type='ed')
            self.assertIsNotNone(res)
            self.assertEqual(res['results'][0]['skipType'], 'ed')
            self.assertEqual(res['results'][0]['interval']['startTime'], 1350.0)
            self.assertEqual(res['results'][0]['interval']['endTime'], 1440.0)

    def test_get_skip_times_missing_segment(self):
        sample_segments = {'intro': None, 'outro': None}
        with mock.patch.object(introdb, 'resolve_imdb_and_season', return_value=('tt123', 1, False)), \
             mock.patch.object(introdb, 'get_segments', return_value=sample_segments):
            res = introdb.get_skip_times(12345, episode=1, skip_type='op')
            self.assertIsNone(res)

    def test_get_extra_segments(self):
        sample_segments = {
            'intro': None,
            'outro': None,
            'recap': {'start_sec': 0.0, 'end_sec': 45.0},
            'post_credits': {'start_sec': 1420.0, 'end_sec': 1460.0}
        }
        with mock.patch.object(introdb, 'resolve_imdb_and_season', return_value=('tt123', 1, False)), \
             mock.patch.object(introdb, 'get_segments', return_value=sample_segments):
            extras = introdb.get_extra_segments(12345, episode=1)
            self.assertEqual(extras['recap']['startTime'], 0.0)
            self.assertEqual(extras['recap']['endTime'], 45.0)
            self.assertEqual(extras['post_credits']['startTime'], 1420.0)
            self.assertEqual(extras['post_credits']['endTime'], 1460.0)


class TestPlayerIntroDBIntegration(unittest.TestCase):

    def _create_mock_player(self):
        from resources.lib.ui.player import WatchlistPlayer
        with mock.patch.object(control, 'getInt', return_value=0), \
             mock.patch.object(control, 'getBool', return_value=True):
            p = WatchlistPlayer()
            p.mal_id = 9999
            p.episode = 1
            p.skipintro_aniskip_enable = True
            p.skipoutro_aniskip_enable = True
            p.skipintro_introdb_enable = True
            p.skipoutro_introdb_enable = True
            p.skipintro_offset = -2
            p.skipoutro_offset = -2
            return p

    def test_process_introdb_applies_intro_and_outro(self):
        p = self._create_mock_player()
        p.skipintro_aniskip = False
        p.skipoutro_aniskip = False

        sample_op = {'results': [{'skipType': 'op', 'interval': {'startTime': 20.0, 'endTime': 110.0}}]}
        sample_ed = {'results': [{'skipType': 'ed', 'interval': {'startTime': 1300.0, 'endTime': 1390.0}}]}

        with mock.patch.object(introdb, 'get_skip_times', side_effect=lambda mid, ep, stype: sample_op if stype == 'op' else sample_ed), \
             mock.patch.object(introdb, 'get_extra_segments', return_value={}):
            p.process_introdb()

            self.assertTrue(p.skipintro_aniskip)
            self.assertFalse(p.skipintro_from_chapters)
            self.assertEqual(p.skipintro_start, 18)  # 20 - 2
            self.assertEqual(p.skipintro_end, 108)  # 110 - 2

            self.assertTrue(p.skipoutro_aniskip)
            self.assertFalse(p.skipoutro_from_chapters)
            self.assertEqual(p.skipoutro_start, 1298)  # 1300 - 2
            self.assertEqual(p.skipoutro_end, 1388)  # 1390 - 2

    def test_process_introdb_preserves_aniskip_intro(self):
        p = self._create_mock_player()
        p.skipintro_aniskip = True  # AniSkip already found intro!
        p.skipintro_from_chapters = False
        p.skipintro_start = 50
        p.skipintro_end = 140

        p.skipoutro_aniskip = False  # AniSkip had no outro
        sample_ed = {'results': [{'skipType': 'ed', 'interval': {'startTime': 1300.0, 'endTime': 1390.0}}]}

        with mock.patch.object(introdb, 'get_skip_times', side_effect=lambda mid, ep, stype: sample_ed if stype == 'ed' else None) as mock_get_skip, \
             mock.patch.object(introdb, 'get_extra_segments', return_value={}):
            p.process_introdb()

            # Intro remains untouched from AniSkip
            self.assertEqual(p.skipintro_start, 50)
            self.assertEqual(p.skipintro_end, 140)

            # Outro filled from IntroDB
            self.assertTrue(p.skipoutro_aniskip)
            self.assertEqual(p.skipoutro_start, 1298)
            # Verify get_skip_times was NEVER called for 'op'
            self.assertNotIn(mock.call(9999, 1, 'op'), mock_get_skip.call_args_list)

    def test_process_introdb_overrides_chapters(self):
        p = self._create_mock_player()
        p.skipintro_aniskip = True
        p.skipintro_from_chapters = True  # Found by chapter extraction, but IntroDB takes precedence
        p.skipintro_start = 10
        p.skipintro_end = 100

        sample_op = {'results': [{'skipType': 'op', 'interval': {'startTime': 30.0, 'endTime': 120.0}}]}

        with mock.patch.object(introdb, 'get_skip_times', side_effect=lambda mid, ep, stype: sample_op if stype == 'op' else None), \
             mock.patch.object(introdb, 'get_extra_segments', return_value={}):
            p.process_introdb()

            self.assertTrue(p.skipintro_aniskip)
            self.assertFalse(p.skipintro_from_chapters)  # Overridden by IntroDB
            self.assertEqual(p.skipintro_start, 28)  # 30 - 2
            self.assertEqual(p.skipintro_end, 118)  # 120 - 2

    def test_process_introdb_disabled_by_settings(self):
        p = self._create_mock_player()
        p.skipintro_introdb_enable = False
        p.skipoutro_introdb_enable = False
        p.skipintro_aniskip = False
        p.skipoutro_aniskip = False

        with mock.patch.object(introdb, 'get_skip_times') as mock_get_skip:
            p.process_introdb()
            mock_get_skip.assert_not_called()
            self.assertFalse(p.skipintro_aniskip)
            self.assertFalse(p.skipoutro_aniskip)


if __name__ == '__main__':
    unittest.main()
