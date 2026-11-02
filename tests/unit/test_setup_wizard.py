# -*- coding: utf-8 -*-
"""
test_setup_wizard.py - Unit tests for Modernized Profile-Based Setup Wizard
"""

import unittest
from unittest.mock import patch, MagicMock
from resources.lib.routes import tools
from resources.lib.ui import control


class TestSetupWizard(unittest.TestCase):

    def test_apply_hardware_preset_high_end(self):
        tools.apply_hardware_preset(0)
        self.assertEqual(control.getInt('scraper.concurrency.workers'), 16)
        self.assertEqual(control.getInt('general.timeout'), 20)
        self.assertEqual(control.getInt('db.sqlite.cache_size_mb'), 32)
        self.assertEqual(control.getInt('db.sqlite.mmap_size_mb'), 64)
        self.assertTrue(control.getBool('general.kodi.cache'))
        self.assertTrue(control.getBool('smartplay.preresolve'))

    def test_apply_hardware_preset_balanced(self):
        tools.apply_hardware_preset(1)
        self.assertEqual(control.getInt('scraper.concurrency.workers'), 8)
        self.assertEqual(control.getInt('general.timeout'), 15)
        self.assertEqual(control.getInt('db.sqlite.cache_size_mb'), 16)
        self.assertEqual(control.getInt('db.sqlite.mmap_size_mb'), 32)
        self.assertTrue(control.getBool('general.kodi.cache'))
        self.assertTrue(control.getBool('smartplay.preresolve'))

    def test_apply_hardware_preset_low_ram(self):
        tools.apply_hardware_preset(2)
        self.assertEqual(control.getInt('scraper.concurrency.workers'), 4)
        self.assertEqual(control.getInt('general.timeout'), 12)
        self.assertEqual(control.getInt('db.sqlite.cache_size_mb'), 8)
        self.assertEqual(control.getInt('db.sqlite.mmap_size_mb'), 4)
        self.assertFalse(control.getBool('general.kodi.cache'))
        self.assertFalse(control.getBool('smartplay.preresolve'))
        self.assertTrue(control.getBool('clean.memory'))

    def test_apply_torrent_providers_recommended(self):
        tools.apply_torrent_providers_preset(0)
        self.assertTrue(control.getBool('provider.nyaa'))
        self.assertTrue(control.getBool('provider.animetosho'))
        self.assertTrue(control.getBool('provider.bitsearch'))
        self.assertTrue(control.getBool('provider.piratebay'))
        self.assertFalse(control.getBool('provider.torrentio'))
        self.assertFalse(control.getBool('provider.nekobt'))

    def test_apply_torrent_providers_all(self):
        tools.apply_torrent_providers_preset(1)
        self.assertTrue(control.getBool('provider.nyaa'))
        self.assertTrue(control.getBool('provider.animetosho'))
        self.assertTrue(control.getBool('provider.bitsearch'))
        self.assertTrue(control.getBool('provider.piratebay'))
        self.assertTrue(control.getBool('provider.torrentio'))
        self.assertTrue(control.getBool('provider.nekobt'))

    def test_apply_torrent_providers_none(self):
        tools.apply_torrent_providers_preset(2)
        self.assertFalse(control.getBool('provider.nyaa'))
        self.assertFalse(control.getBool('provider.animetosho'))
        self.assertFalse(control.getBool('provider.bitsearch'))
        self.assertFalse(control.getBool('provider.piratebay'))
        self.assertFalse(control.getBool('provider.torrentio'))
        self.assertFalse(control.getBool('provider.nekobt'))

    def test_apply_embed_providers_recommended(self):
        tools.apply_embed_providers_preset(0)
        self.assertTrue(control.getBool('provider.hianime'))
        self.assertTrue(control.getBool('provider.animepahe'))
        self.assertTrue(control.getBool('provider.anikoto'))
        self.assertTrue(control.getBool('provider.watchnixtoons2'))
        self.assertFalse(control.getBool('provider.animix'))

    def test_apply_embed_providers_all(self):
        tools.apply_embed_providers_preset(1)
        self.assertTrue(control.getBool('provider.hianime'))
        self.assertTrue(control.getBool('provider.animepahe'))
        self.assertTrue(control.getBool('provider.anikoto'))
        self.assertTrue(control.getBool('provider.watchnixtoons2'))
        self.assertTrue(control.getBool('provider.animix'))

    def test_apply_embed_providers_none(self):
        tools.apply_embed_providers_preset(2)
        self.assertFalse(control.getBool('provider.hianime'))
        self.assertFalse(control.getBool('provider.animepahe'))
        self.assertFalse(control.getBool('provider.anikoto'))
        self.assertFalse(control.getBool('provider.watchnixtoons2'))
        self.assertFalse(control.getBool('provider.animix'))

    def test_apply_playback_profile_sub(self):
        with patch('resources.lib.windows.sort_select.SortSelect.auto_action') as mock_sort:
            tools.apply_playback_profile(0)
            self.assertEqual(control.getInt('general.audio'), 0)
            self.assertEqual(control.getInt('general.subtitles'), 1)
            self.assertEqual(control.getInt('general.source'), 1)
            self.assertFalse(control.getBool('divflavors.showdub'))
            mock_sort.assert_called_with(0)

    def test_apply_playback_profile_dub(self):
        with patch('resources.lib.windows.sort_select.SortSelect.auto_action') as mock_sort:
            tools.apply_playback_profile(1)
            self.assertEqual(control.getInt('general.audio'), 1)
            self.assertEqual(control.getInt('general.subtitles'), 0)
            self.assertEqual(control.getInt('general.source'), 2)
            self.assertTrue(control.getBool('divflavors.showdub'))
            mock_sort.assert_called_with(1)


if __name__ == '__main__':
    unittest.main()
