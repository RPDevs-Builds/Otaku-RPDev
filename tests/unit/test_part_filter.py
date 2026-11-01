# -*- coding: utf-8 -*-
"""
test_part_filter.py - Unit Tests for Multi-Part Anime and Chinese Hardsub Filter
"""

import unittest
from unittest.mock import patch, MagicMock
from resources.lib.ui import part_filter


class TestPartFilter(unittest.TestCase):

    def test_chinese_hardsub_dropped_when_chinese_not_requested(self):
        sources = [
            {'name': '[SubsPlease] Shingeki no Kyojin - 01 [1080p].mkv', 'type': 'torrent'},
            {'name': '[B-Global] Shingeki no Kyojin - 01 [CHS] [1080p].mp4', 'type': 'torrent'},
            {'name': '[ANi] Shingeki no Kyojin - 01 [CHT] [1080p].mkv', 'type': 'torrent'},
            {'name': '[Erai-raws] Shingeki no Kyojin - 01 [1080p].mkv', 'type': 'torrent'},
        ]
        with patch.object(part_filter, '_user_wants_chinese', return_value=False):
            with patch.object(part_filter, '_get_mappings_info', return_value=None):
                result = part_filter.filter_sources(sources, mal_id=16498, episode=1)
                names = [s['name'] for s in result]
                self.assertIn('[SubsPlease] Shingeki no Kyojin - 01 [1080p].mkv', names)
                self.assertIn('[Erai-raws] Shingeki no Kyojin - 01 [1080p].mkv', names)
                self.assertNotIn('[B-Global] Shingeki no Kyojin - 01 [CHS] [1080p].mp4', names)
                self.assertNotIn('[ANi] Shingeki no Kyojin - 01 [CHT] [1080p].mkv', names)
                self.assertEqual(len(result), 2)

    def test_chinese_hardsub_kept_when_user_wants_chinese(self):
        sources = [
            {'name': '[B-Global] Shingeki no Kyojin - 01 [CHS] [1080p].mp4', 'type': 'torrent'},
            {'name': '[SubsPlease] Shingeki no Kyojin - 01 [1080p].mkv', 'type': 'torrent'},
        ]
        with patch.object(part_filter, '_user_wants_chinese', return_value=True):
            with patch.object(part_filter, '_get_mappings_info', return_value=None):
                result = part_filter.filter_sources(sources, mal_id=16498, episode=1)
                self.assertEqual(len(result), 2)

    def test_multi_part_franchise_filter_drops_wrong_part(self):
        # User is watching Part 2 Episode 1
        sources = [
            {'name': '[SubsPlease] Bleach - Thousand-Year Blood War Part 2 - 01 (1080p).mkv', 'type': 'torrent'},
            {'name': '[SubsPlease] Bleach - Thousand-Year Blood War Part 1 - 01 (1080p).mkv', 'type': 'torrent'},
            {'name': '[Erai-raws] Bleach - Thousand-Year Blood War Cour 2 - 01 [1080p].mkv', 'type': 'torrent'},
            {'name': '[Erai-raws] Bleach - Thousand-Year Blood War Cour 1 - 01 [1080p].mkv', 'type': 'torrent'},
        ]
        mapping_mock = {
            'thetvdb_season': 1,
            'thetvdb_part': 2,
            'anime_media_episodes': '1 - 13',
            'global_media_episodes': '14 - 26',
            'mal_title': 'Bleach: Sennen Kessen-hen - Ketsubetsu-tan'
        }
        with patch.object(part_filter, '_user_wants_chinese', return_value=False):
            with patch.object(part_filter, '_get_mappings_info', return_value=mapping_mock):
                result = part_filter.filter_sources(sources, mal_id=53998, episode=1)
                names = [s['name'] for s in result]
                self.assertIn('[SubsPlease] Bleach - Thousand-Year Blood War Part 2 - 01 (1080p).mkv', names)
                self.assertIn('[Erai-raws] Bleach - Thousand-Year Blood War Cour 2 - 01 [1080p].mkv', names)
                self.assertNotIn('[SubsPlease] Bleach - Thousand-Year Blood War Part 1 - 01 (1080p).mkv', names)
                self.assertNotIn('[Erai-raws] Bleach - Thousand-Year Blood War Cour 1 - 01 [1080p].mkv', names)
                self.assertEqual(len(result), 2)

    def test_multi_part_batch_range_filtering(self):
        # Part 2 episode 1 (global_ep = 17, ep_num = 1)
        sources = [
            {'name': '[SubsPlease] Shingeki no Kyojin (01-16) (1080p) [Batch]', 'type': 'torrent'},
            {'name': '[SubsPlease] Shingeki no Kyojin (17-28) (1080p) [Batch]', 'type': 'torrent'},
            {'name': '[SubsPlease] Shingeki no Kyojin (01-28) (1080p) [Batch]', 'type': 'torrent'},
        ]
        mapping_mock = {
            'thetvdb_season': 4,
            'thetvdb_part': 2,
            'anime_media_episodes': '1 - 12',
            'global_media_episodes': '17 - 28',
            'mal_title': 'Shingeki no Kyojin: The Final Season Part 2'
        }
        with patch.object(part_filter, '_user_wants_chinese', return_value=False):
            with patch.object(part_filter, '_get_mappings_info', return_value=mapping_mock):
                result = part_filter.filter_sources(sources, mal_id=48583, episode=1)
                names = [s['name'] for s in result]
                # Batch 01-16 does not cover episode 17, so it should be dropped!
                self.assertNotIn('[SubsPlease] Shingeki no Kyojin (01-16) (1080p) [Batch]', names)
                self.assertIn('[SubsPlease] Shingeki no Kyojin (17-28) (1080p) [Batch]', names)
                self.assertIn('[SubsPlease] Shingeki no Kyojin (01-28) (1080p) [Batch]', names)
                self.assertEqual(len(result), 2)

    def test_empty_or_none_sources_handled_gracefully(self):
        self.assertEqual(part_filter.filter_sources([]), [])
        self.assertEqual(part_filter.filter_sources(None), [])


if __name__ == '__main__':
    unittest.main()
