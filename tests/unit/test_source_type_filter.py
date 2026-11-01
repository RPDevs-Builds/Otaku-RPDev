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


if __name__ == '__main__':
    unittest.main()
