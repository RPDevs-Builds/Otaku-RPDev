"""
test_embed_precaching_and_continuity_v5523.py
Unit tests for v5.5.23:
1. Episode sources pre-caching in database.py & MetaBrowser.py fast-path
2. Anikoto scraping fallback when database.get_show is None
3. Embed continuity in resolver.reorder_sources and pages.sortSources
4. Embed last_played_source key persistence in resolver.py
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

import unittest
from unittest.mock import MagicMock, patch

from resources.lib.ui import database, control
from resources.lib import MetaBrowser
from resources.lib.pages import anikoto, Sources as PagesSources
from resources.lib.windows.resolver import Resolver


class TestEmbedPrecachingAndContinuity(unittest.TestCase):

    def setUp(self):
        database._bump_mem_generation()
        database.clear_episode_sources()
        database.clear_season_pack()
        control.setSetting('last_played_source', 'None')
        control.setSetting('last_watched_series', '0')
        control.setBool('general.smartplay', True)
        control.setBool('smartplay.prefer_same_embed', True)

    def tearDown(self):
        database.clear_episode_sources()
        database.clear_season_pack()

    def test_database_episode_sources_caching(self):
        """Verify set_episode_sources, get_episode_sources, and clear_episode_sources."""
        mal_id = 99999
        ep = 2
        mock_sources = [
            {'provider': 'anikoto', 'type': 'direct', 'quality': 3, 'info': ['megaplay SUB'], 'lang': 2},
            {'provider': 'animepahe', 'type': 'direct', 'quality': 2, 'info': ['pahe SUB'], 'lang': 2}
        ]

        # Initially None
        self.assertIsNone(database.get_episode_sources(mal_id, ep))

        # Cache sources
        database.set_episode_sources(mal_id, ep, mock_sources)
        cached = database.get_episode_sources(mal_id, ep)
        self.assertIsNotNone(cached)
        self.assertEqual(len(cached), 2)
        self.assertEqual(cached[0]['provider'], 'anikoto')

        # Invalidate specific episode
        database.clear_episode_sources(mal_id, ep)
        self.assertIsNone(database.get_episode_sources(mal_id, ep))

    def test_metabrowser_fast_path_pre_scraped_sources(self):
        """Verify MetaBrowser.get_sources uses pre-scraped sources without re-scraping."""
        mal_id = 59228
        ep = 2
        mock_sources = [
            {'provider': 'anikoto', 'type': 'direct', 'quality': 3, 'info': ['megaplay SUB'], 'lang': 2}
        ]

        # Seed pre-scraped sources in DB
        database.set_episode_sources(mal_id, ep, mock_sources)

        # Mock database.get_show to return dummy show
        with patch.object(database, 'get_show', return_value={'kodi_meta': database.dumps({'query': 'Black Butler', 'episodes': 12, 'status': 'airing', 'duration': 1400})}):
            with patch('resources.lib.pages.getSourcesHelper') as mock_helper:
                sources = MetaBrowser.get_sources(mal_id, ep, 'show', rescrape=False, source_select=False, silent=False)
                self.assertEqual(sources, mock_sources)
                mock_helper.assert_not_called()

                # Rescrape=True must bypass pre-cache and invoke getSourcesHelper
                mock_helper.return_value = [{'provider': 'fresh', 'quality': 3}]
                fresh = MetaBrowser.get_sources(mal_id, ep, 'show', rescrape=True, source_select=False, silent=False)
                mock_helper.assert_called_once()
                self.assertEqual(fresh[0]['provider'], 'fresh')

    def test_anikoto_get_sources_fallback_when_show_is_none(self):
        """Verify anikoto.get_sources does not abort if database.get_show returns None."""
        scraper = anikoto.Sources()
        mal_id = 59228
        ep = 1

        mock_megaplay_result = {
            'sources': [{'file': 'https://fetch.example.com/master.m3u8'}],
            'tracks': [{'kind': 'captions', 'file': 'https://fetch.example.com/sub.vtt', 'label': 'English'}],
            'intro': {'end': 85},
            'outro': {'end': 1300}
        }

        with patch.object(database, 'get_show', return_value=None):
            with patch.object(database, 'get_show_meta', return_value={'name': 'Black Butler: Emerald Witch Arc'}):
                with patch('resources.lib.pages.anikoto.extract_megaplay_sources', return_value=mock_megaplay_result):
                    with patch.object(scraper, '_get_request', return_value='#EXT-X-STREAM-INF:BANDWIDTH=8000000,RESOLUTION=1920x1080\nhttps://fetch.example.com/1080p.m3u8'):
                        sources = scraper.get_sources(mal_id, ep)
                        self.assertIsNotNone(sources)
                        self.assertGreater(len(sources), 0)
                        self.assertEqual(sources[0]['provider'], 'anikoto')
                        self.assertIn('Black Butler: Emerald Witch Arc', sources[0]['release_title'])

    def test_resolver_reorder_sources_prefers_last_played_embed(self):
        """Verify resolver.reorder_sources prioritizes the embed provider matching last_played_source."""
        resolver = Resolver('resolver.xml', control.ADDON_PATH, actionArgs={'mal_id': 59228, 'episode': 2})

        # Save last played profile for anikoto (DUB, lang=3)
        last_played = {
            'provider': 'anikoto',
            'type': 'direct',
            'lang': 3,
            'quality': 3,
            'info': ['megaplay DUB'],
            'release_title': 'Kuroshitsuji: Midori no Majo-hen - Ep 1'
        }
        database.save_last_played_source(59228, last_played)
        control.setSetting('last_played_source', 'anikoto megaplay DUB')

        candidate_sources = [
            {'provider': 'hianime', 'type': 'direct', 'quality': 3, 'info': ['server SUB'], 'lang': 2, 'release_title': 'Ep 2'},
            {'provider': 'animepahe', 'type': 'direct', 'quality': 3, 'info': ['pahe SUB'], 'lang': 2, 'release_title': 'Ep 2'},
            {'provider': 'anikoto', 'type': 'direct', 'quality': 3, 'info': ['megaplay DUB'], 'lang': 3, 'release_title': 'Ep 2'}
        ]

        reordered = resolver.reorder_sources(list(candidate_sources))
        self.assertEqual(reordered[0]['provider'], 'anikoto')
        self.assertEqual(reordered[0]['lang'], 3)

    def test_pages_sort_sources_prefers_same_embed(self):
        """Verify pages.sortSources prioritizes preferred embed provider at index 0."""
        mal_id = 59228
        last_played = {
            'provider': 'anikoto',
            'type': 'direct',
            'lang': 2,
            'quality': 3,
            'info': ['megaplay SUB'],
            'release_title': 'Kuroshitsuji: Midori no Majo-hen - Ep 1'
        }
        database.save_last_played_source(mal_id, last_played)

        embed_sources = [
            {'provider': 'animepahe', 'type': 'direct', 'quality': 3, 'info': ['pahe SUB'], 'lang': 2, 'release_title': 'AnimePahe Ep 2'},
            {'provider': 'anikoto', 'type': 'direct', 'quality': 3, 'info': ['megaplay SUB'], 'lang': 2, 'release_title': 'Anikoto Ep 2'}
        ]

        sorted_sources = PagesSources.sortSources(
            torrent_list=[],
            hoster_list=[],
            embed_list=embed_sources,
            cloud_files=[],
            local_files=[],
            media_type='show',
            duration=1400,
            mal_id=mal_id
        )

        self.assertTrue(len(sorted_sources) >= 2)
        self.assertEqual(sorted_sources[0]['provider'], 'anikoto')

    def test_smartplay_continuity_reuses_resolver_for_known_series(self):
        """Verify playback.py routes to _show_resolver when series has last played source profile."""
        from resources.lib.routes import playback
        mal_id = '59228'
        ep = '2'

        # Seed last played source profile
        last_played = {
            'provider': 'anikoto',
            'type': 'direct',
            'lang': 2,
            'quality': 3,
            'release_title': 'Kuroshitsuji: Midori no Majo-hen - Ep 1'
        }
        database.save_last_played_source(int(mal_id), last_played)
        database.save_last_played_source(mal_id, last_played)

        # Settings: smartplay=True, last_watched_series='0' (default uninitialized), last_played_source='anikoto megaplay SUB'
        control.setBool('general.smartplay', True)
        control.setSetting('last_watched_series', '0')
        control.setSetting('last_played_source', 'anikoto megaplay SUB')

        mock_sources = [
            {'provider': 'animepahe', 'type': 'direct', 'quality': 3, 'info': ['pahe SUB'], 'lang': 2, 'release_title': 'AnimePahe Ep 2'},
            {'provider': 'anikoto', 'type': 'direct', 'quality': 3, 'info': ['megaplay SUB'], 'lang': 2, 'release_title': 'Anikoto Ep 2'}
        ]

        with patch('resources.lib.MetaBrowser.get_sources', return_value=mock_sources):
            with patch('resources.lib.routes.playback._show_resolver') as mock_resolver:
                with patch('resources.lib.routes.playback._show_source_select') as mock_select:
                    with patch('resources.lib.ui.database.get_episode', return_value={'kodi_meta': database.dumps({'info': {'mediatype': 'episode'}})}):
                        playback.PLAY(f'{mal_id}/{ep}', {})
                        mock_resolver.assert_called_once()
                        mock_select.assert_not_called()


if __name__ == '__main__':
    unittest.main()