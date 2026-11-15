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
from unittest.mock import patch, MagicMock

from resources.lib import pages
from resources.lib.debrid import debrid_cache
from resources.lib.pages import animepahe, watchnixtoons2
from resources.lib.ui import control, database


class TestSourceTypeFilter(unittest.TestCase):
    def setUp(self):
        control.clearSettingsCache()

    def tearDown(self):
        control.clearSettingsCache()

    def test_settings_priority_over_window_property(self):
        """Authoritative Kodi settings.getInt must take precedence over stale homeWindow property."""
        # Simulate stale startup window property holding 0 (Both)
        control.homeWindow.setProperty(f'{control.ADDON_ID}_general.source', '0')
        # Simulate Kodi settings.xml having 2 (Dub)
        control.settings.setInt('general.source', 2)
        control.clearSettingsCache()

        # control.getInt must return 2 (Dub), not 0 (Both)
        self.assertEqual(control.getInt('general.source'), 2)

    def test_sort_sources_dub_filters_megaplay_ryu_animix_sub(self):
        """When general.source == 2 (Dub), all SUB embed sources must be strictly filtered out."""
        control.settings.setInt('general.source', 2)
        control.clearSettingsCache()

        # Set min/max resolution to pass through
        control.settings.setInt('general.minResolution', 0)
        control.settings.setInt('general.maxResolution', 10)
        control.settings.setInt('general.fileFilter', 0)

        sample_sources = [
            {'quality': 2, 'type': 'direct', 'provider': 'anikoto', 'info': ['MEGAPLAY SUB'], 'lang': 2, 'hash': 'h1', 'release_title': 'Show - Ep 1'},
            {'quality': 2, 'type': 'direct', 'provider': 'hianime', 'info': ['RYU SUB'], 'lang': 2, 'hash': 'h2', 'release_title': 'Show - Ep 1'},
            {'quality': 2, 'type': 'direct', 'provider': 'animix', 'info': ['bunny SUB'], 'lang': 2, 'hash': 'h3', 'release_title': 'Show Ep1'},
            {'quality': 2, 'type': 'direct', 'provider': 'anikoto', 'info': ['MEGAPLAY DUB'], 'lang': 3, 'hash': 'h4', 'release_title': 'Show - Ep 1'},
            {'quality': 3, 'type': 'torrent', 'provider': 'nyaa', 'info': ['1080p', 'Dual Audio'], 'lang': 1, 'hash': 'h5', 'release_title': '[SubsPlease] Show - 01 (Dual Audio)'},
        ]

        filtered = pages.Sources.sortSources(
            torrent_list=[sample_sources[4]],
            hoster_list=[],
            embed_list=sample_sources[0:4],
            cloud_files=[],
            local_files=[],
            media_type='episode',
            duration=1400
        )

        hashes = [s['hash'] for s in filtered]
        self.assertNotIn('h1', hashes, "MEGAPLAY SUB must be filtered out when general.source == 2 (Dub)")
        self.assertNotIn('h2', hashes, "RYU SUB must be filtered out when general.source == 2 (Dub)")
        self.assertNotIn('h3', hashes, "bunny SUB must be filtered out when general.source == 2 (Dub)")
        self.assertIn('h4', hashes, "MEGAPLAY DUB must be preserved when general.source == 2 (Dub)")
        self.assertIn('h5', hashes, "Dual Audio torrent must be preserved when general.source == 2 (Dub)")

    def test_sort_sources_sub_filters_dub(self):
        """When general.source == 1 (Sub), all pure DUB sources must be strictly filtered out."""
        control.settings.setInt('general.source', 1)
        control.clearSettingsCache()

        control.settings.setInt('general.minResolution', 0)
        control.settings.setInt('general.maxResolution', 10)
        control.settings.setInt('general.fileFilter', 0)

        sample_sources = [
            {'quality': 2, 'type': 'direct', 'provider': 'anikoto', 'info': ['MEGAPLAY SUB'], 'lang': 2, 'hash': 'h1', 'release_title': 'Show - Ep 1'},
            {'quality': 2, 'type': 'direct', 'provider': 'anikoto', 'info': ['MEGAPLAY DUB'], 'lang': 3, 'hash': 'h4', 'release_title': 'Show - Ep 1'},
            {'quality': 3, 'type': 'torrent', 'provider': 'nyaa', 'info': ['1080p', 'Dual Audio'], 'lang': 1, 'hash': 'h5', 'release_title': '[SubsPlease] Show - 01 (Dual Audio)'},
        ]

        filtered = pages.Sources.sortSources(
            torrent_list=[sample_sources[2]],
            hoster_list=[],
            embed_list=sample_sources[0:2],
            cloud_files=[],
            local_files=[],
            media_type='episode',
            duration=1400
        )

        hashes = [s['hash'] for s in filtered]
        self.assertIn('h1', hashes, "MEGAPLAY SUB must be preserved when general.source == 1 (Sub)")
        self.assertNotIn('h4', hashes, "MEGAPLAY DUB must be filtered out when general.source == 1 (Sub)")
        self.assertIn('h5', hashes, "Dual Audio torrent must be preserved when general.source == 1 (Sub)")

    def test_debrid_cache_prune_expired_hashes_ensures_table(self):
        """prune_expired_hashes must ensure the table exists and execute without error."""
        try:
            debrid_cache.prune_expired_hashes()
        except Exception as e:
            self.fail(f"prune_expired_hashes failed with unexpected exception: {e}")

    def test_animepahe_build_source_respects_source_type(self):
        """AnimePahe _build_source must return None when audio mismatches general.source."""
        control.settings.setInt('general.source', 2)  # Dub
        control.clearSettingsCache()

        ap = animepahe.Sources()
        sub_item = {'data-src': 'https://kwik.cx/e/123', 'data-resolution': '1080', 'data-audio': 'jpn'}
        dub_item = {'data-src': 'https://kwik.cx/e/456', 'data-resolution': '1080', 'data-audio': 'eng'}

        self.assertIsNone(ap._build_source(sub_item, 'Test Title', 1, ['kwik.cx']))
        dub_src = ap._build_source(dub_item, 'Test Title', 1, ['kwik.cx'])
        self.assertIsNotNone(dub_src)
        self.assertEqual(dub_src['lang'], 3)

    def test_filter_sources_by_audio_preserves_dual_and_multi_with_multisub(self):
        """Dual-Audio (lang=1) and Multi-Audio (lang=0) carrying MULTI-SUB must be kept for Dub & Sub."""
        import conftest
        from resources.lib.ui import source_utils
        from resources.lib.pages import Sources

        sample = [
            {'release_title': '[ToonsHub] Show - S01E01', 'type': 'torrent', 'provider': 'nyaa', 'quality': 2, 'size': '500 MB', 'byte_size': 500000000, 'seeders': 10, 'lang': 1, 'info': ['HEVC', 'DUAL-AUDIO', 'MULTI-SUB']},
            {'release_title': '[Ironclad] Show - S01E01', 'type': 'torrent', 'provider': 'nekobt', 'quality': 2, 'size': '600 MB', 'byte_size': 600000000, 'seeders': 12, 'lang': 0, 'info': ['MULTI-AUDIO', 'MULTI-SUB']},
            {'release_title': '[EMBER] Show - S01E01', 'type': 'torrent', 'provider': 'nyaa', 'quality': 2, 'size': '250 MB', 'byte_size': 250000000, 'seeders': 20, 'lang': 2, 'info': ['HEVC', 'SUB']},
            {'release_title': '[Yameii] Show - S01E01 [English Dub]', 'type': 'torrent', 'provider': 'nyaa', 'quality': 2, 'size': '450 MB', 'byte_size': 450000000, 'seeders': 15, 'lang': 3, 'info': ['AVC', 'DUB']},
        ]

        dub_only = source_utils.filter_sources_by_audio(sample, 2)
        self.assertEqual(
            [s['release_title'] for s in dub_only],
            ['[ToonsHub] Show - S01E01', '[Ironclad] Show - S01E01', '[Yameii] Show - S01E01 [English Dub]'],
        )

        sub_only = source_utils.filter_sources_by_audio(sample, 1)
        self.assertEqual(
            [s['release_title'] for s in sub_only],
            ['[ToonsHub] Show - S01E01', '[Ironclad] Show - S01E01', '[EMBER] Show - S01E01'],
        )

        both = source_utils.filter_sources_by_audio(sample, 0)
        self.assertEqual(len(both), 4)

        saved_store = dict(conftest._settings_store)
        saved_props = dict(conftest._window_props)
        try:
            # End-to-end sortSources with general.source=2 preserves ToonsHub & Ironclad MULTI-SUB torrents
            control.setInt('general.source', 2)
            control.setBool('show.uncached', True)
            control.setInt('general.minResolution', 0)
            control.setInt('general.maxResolution', 4)
            control.setInt('general.fileFilter', 0)
            control.setBool('general.release_title_filter.enabled', False)
            control.setStringList('general.filters', [])
            control.clearSettingsCache()

            sorted_dub = Sources.sortSources(
                torrent_list=[dict(s) for s in sample],
                hoster_list=[],
                embed_list=[],
                cloud_files=[],
                local_files=[],
                media_type='show',
                duration=24,
                show_title='Show',
            )
            sorted_titles = [s['release_title'] for s in sorted_dub]
            self.assertIn('[ToonsHub] Show - S01E01', sorted_titles)
            self.assertIn('[Ironclad] Show - S01E01', sorted_titles)
            self.assertIn('[Yameii] Show - S01E01 [English Dub]', sorted_titles)
            self.assertNotIn('[EMBER] Show - S01E01', sorted_titles)
        finally:
            conftest._settings_store.clear()
            conftest._settings_store.update(saved_store)
            conftest._window_props.clear()
            conftest._window_props.update(saved_props)
            control.clearSettingsCache()


if __name__ == '__main__':
    unittest.main()
