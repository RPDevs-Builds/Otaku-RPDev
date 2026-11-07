# -*- coding: utf-8 -*-
"""
test_upstream_pr500_tmdb_helper.py - Unit tests for PR #500 TMDbHelper episode mapping matching
"""

import unittest
from unittest.mock import patch, MagicMock
from resources.lib.routes.playback import tmdb_mapping_match


class TestPR500TMDbHelper(unittest.TestCase):

    def test_tmdb_mapping_match_empty_inputs(self):
        self.assertIsNone(tmdb_mapping_match(None, [], 1, 1))
        self.assertIsNone(tmdb_mapping_match('123', [], None, 1))
        self.assertIsNone(tmdb_mapping_match('123', [], 1, None))

    def test_tmdb_mapping_match_season_match(self):
        id_sources = [('themoviedb_id', '1001')]
        mock_rows = [{
            'mal_id': '35847',
            'themoviedb_id': '1001',
            'thetvdb_season': '1',
            'global_media_episodes': '1-12',
            'anime_media_episodes': '1-12'
        }]

        with patch('resources.lib.ui.database.get_mal_ids', return_value=mock_rows):
            with patch('resources.lib.ui.client.get') as mock_client:
                mock_resp = MagicMock()
                mock_resp.text = '{"seasons": [{"season_number": 1, "episode_count": 12}]}'
                mock_resp.json.return_value = {"seasons": [{"season_number": 1, "episode_count": 12}]}
                mock_client.return_value = mock_resp
                match = tmdb_mapping_match('1001', id_sources, 1, 10)
                self.assertIsNotNone(match)
                self.assertEqual(match['mal_id'], '35847')
                self.assertEqual(match['episode_number'], 10)
                self.assertEqual(match['matched_title'], 'mappings.db')

    def test_tmdb_mapping_match_absolute_numbered(self):
        id_sources = [('themoviedb_id', '2002')]
        mock_rows = [{
            'mal_id': '21',
            'themoviedb_id': '2002',
            'thetvdb_season': 'a',
            'global_media_episodes': '1-1000',
            'anime_media_episodes': '1-1000'
        }]

        with patch('resources.lib.ui.database.get_mal_ids', return_value=mock_rows):
            with patch('resources.lib.ui.client.get') as mock_client:
                # Season 2 episode 5 where Season 1 had 50 episodes -> absolute 55
                mock_resp = MagicMock()
                mock_resp.text = '{"seasons": [{"season_number": 1, "episode_count": 50}, {"season_number": 2, "episode_count": 50}]}'
                mock_resp.json.return_value = {"seasons": [{"season_number": 1, "episode_count": 50}, {"season_number": 2, "episode_count": 50}]}
                mock_client.return_value = mock_resp
                match = tmdb_mapping_match('2002', id_sources, 2, 5)
                self.assertIsNotNone(match)
                self.assertEqual(match['mal_id'], '21')
                self.assertEqual(match['episode_number'], 55)


if __name__ == '__main__':
    unittest.main()
