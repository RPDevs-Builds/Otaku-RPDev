"""
test_animeskip.py - Unit tests for Anime-Skip skip times endpoint and player integration
"""

import unittest
from unittest import mock

from resources.lib.endpoints import anime_skip
from resources.lib.ui import control
from resources.lib.ui.player import WatchlistPlayer


class TestAnimeSkipEndpoint(unittest.TestCase):
    def test_resolve_anilist_id_mappings_db(self):
        with mock.patch('resources.lib.ui.database.get_mappings', return_value={'anilist_id': 249}):
            anilist_id = anime_skip.resolve_anilist_id(249)
            self.assertEqual(anilist_id, 249)

    def test_resolve_anilist_id_show_meta(self):
        with mock.patch('resources.lib.ui.database.get_mappings', return_value={}), \
             mock.patch('resources.lib.ui.database.get_show_meta', return_value={'meta_ids': '{"anilist_id": 16498}'}):
            anilist_id = anime_skip.resolve_anilist_id(16498)
            self.assertEqual(anilist_id, 16498)

    def test_resolve_anilist_id_fallback(self):
        with mock.patch('resources.lib.ui.database.get_mappings', return_value={}), \
             mock.patch('resources.lib.ui.database.get_show_meta', return_value={}), \
             mock.patch('resources.lib.ui.client.get', return_value=None):
            anilist_id = anime_skip.resolve_anilist_id(9999)
            self.assertEqual(anilist_id, 9999)

    def test_resolve_anilist_id_none(self):
        self.assertIsNone(anime_skip.resolve_anilist_id(None))

    def test_fetch_skip_times_success(self):
        mock_resp = mock.MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            'data': {
                'findShowsByExternalId': [{
                    'episodes': [{
                        'number': '1',
                        'timestamps': [
                            {'at': 0, 'typeId': '9edc0037-fa4e-47a7-a29a-d9c43368daa8'},
                            {'at': 90.0, 'typeId': '14550023-2589-46f0-bfb4-152976506b4c'},
                            {'at': 180.0, 'typeId': '9edc0037-fa4e-47a7-a29a-d9c43368daa8'},
                            {'at': 1300.0, 'typeId': '2a730a51-a601-439b-bc1f-7b94a640ffb9'},
                            {'at': 1390.0, 'typeId': 'c7b1eddb-defa-4bc6-a598-f143081cfe4b'}
                        ]
                    }]
                }]
            }
        }
        with mock.patch('resources.lib.ui.client.post', return_value=mock_resp):
            res = anime_skip._fetch_skip_times(12345, episode=1, client_id='test_key')
            self.assertIn('op', res)
            self.assertIn('ed', res)
            self.assertEqual(res['op'], {'startTime': 90.0, 'endTime': 180.0})
            self.assertEqual(res['ed'], {'startTime': 1300.0, 'endTime': 1390.0})

    def test_fetch_skip_times_empty_on_network_fail(self):
        with mock.patch('resources.lib.ui.client.post', return_value=None):
            res = anime_skip._fetch_skip_times(12345, 1)
            self.assertEqual(res, {})


class TestPlayerAnimeSkipIntegration(unittest.TestCase):
    def _create_mock_player(self):
        with mock.patch.object(control, 'getInt', return_value=0), \
             mock.patch.object(control, 'getBool', return_value=True), \
             mock.patch.object(control, 'getSetting', return_value='test_key'):
            p = WatchlistPlayer()
            p.mal_id = 9999
            p.episode = 1
            p.skipintro_aniskip_enable = True
            p.skipoutro_aniskip_enable = True
            p.animeskip_enable = True
            p.animeskip_apikey = 'test_key'
            p.skipintro_animeskip_enable = True
            p.skipoutro_animeskip_enable = True
            p.skipintro_offset = -2
            p.skipoutro_offset = -2
            return p

    def test_process_animeskip_applies_intro_and_outro(self):
        p = self._create_mock_player()
        p.skipintro_aniskip = False
        p.skipoutro_aniskip = False

        sample_op = {'results': [{'skipType': 'op', 'interval': {'startTime': 100.0, 'endTime': 190.0}}]}
        sample_ed = {'results': [{'skipType': 'ed', 'interval': {'startTime': 1310.0, 'endTime': 1400.0}}]}

        with mock.patch.object(anime_skip, 'get_skip_times', side_effect=lambda mid, ep, stype, client_id: sample_op if stype == 'op' else sample_ed):
            p.process_animeskip()

            self.assertTrue(p.skipintro_aniskip)
            self.assertFalse(p.skipintro_from_chapters)
            self.assertEqual(p.skipintro_start, 98)  # 100 - 2
            self.assertEqual(p.skipintro_end, 188)  # 190 - 2

            self.assertTrue(p.skipoutro_aniskip)
            self.assertFalse(p.skipoutro_from_chapters)
            self.assertEqual(p.skipoutro_start, 1308)  # 1310 - 2
            self.assertEqual(p.skipoutro_end, 1398)  # 1400 - 2

    def test_process_animeskip_preserves_aniskip_intro(self):
        p = self._create_mock_player()
        p.skipintro_aniskip = True  # AniSkip already found intro!
        p.skipintro_from_chapters = False
        p.skipintro_start = 50
        p.skipintro_end = 140

        p.skipoutro_aniskip = False  # AniSkip had no outro
        sample_ed = {'results': [{'skipType': 'ed', 'interval': {'startTime': 1300.0, 'endTime': 1390.0}}]}

        with mock.patch.object(anime_skip, 'get_skip_times', side_effect=lambda mid, ep, stype, client_id: sample_ed if stype == 'ed' else None) as mock_get_skip:
            p.process_animeskip()

            # Intro remains untouched from AniSkip
            self.assertEqual(p.skipintro_start, 50)
            self.assertEqual(p.skipintro_end, 140)

            # Outro filled from Anime-Skip
            self.assertTrue(p.skipoutro_aniskip)
            self.assertEqual(p.skipoutro_start, 1298)
            # Verify get_skip_times was NEVER called for 'op'
            self.assertNotIn(mock.call(9999, 1, 'op', client_id='test_key'), mock_get_skip.call_args_list)

    def test_process_animeskip_disabled_by_master_setting(self):
        p = self._create_mock_player()
        p.animeskip_enable = False
        p.skipintro_aniskip = False
        p.skipoutro_aniskip = False

        with mock.patch.object(anime_skip, 'get_skip_times') as mock_get_skip:
            p.process_animeskip()
            mock_get_skip.assert_not_called()
            self.assertFalse(p.skipintro_aniskip)

    def test_process_animeskip_disabled_without_apikey(self):
        p = self._create_mock_player()
        p.animeskip_apikey = ''
        p.skipintro_aniskip = False
        p.skipoutro_aniskip = False

        with mock.patch.object(anime_skip, 'get_skip_times') as mock_get_skip:
            p.process_animeskip()
            mock_get_skip.assert_not_called()
            self.assertFalse(p.skipintro_aniskip)


if __name__ == '__main__':
    unittest.main()
