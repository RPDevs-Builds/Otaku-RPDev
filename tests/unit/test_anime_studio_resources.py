"""
test_anime_studio_resources.py - Unit Tests for Anime Studio Icon Integration
=============================================================================
Verifies resolution of anime studio icons from resource packages
(resource.images.animestudio.coloured & resource.images.animestudio.white),
ListItem properties, settings selection, and resolver art propagation.
"""

import unittest
from unittest.mock import MagicMock, patch

import conftest
from resources.lib.ui import control
from resources.lib.windows.resolver import Resolver


class TestAnimeStudioResources(unittest.TestCase):

    def setUp(self):
        control._artwork_cache.clear()

    def test_set_videotags_studio_property_list(self):
        li = conftest.MockListItem()
        info = {'studio': ['Bones', 'A-1 Pictures']}
        control.set_videotags(li, info)
        self.assertEqual(li.getVideoInfoTag().getStudios(), ['Bones'])
        self.assertEqual(li.getProperty('Studio'), 'Bones')
        self.assertEqual(li.getProperty('Studios'), 'Bones / A-1 Pictures')

    def test_set_videotags_studio_property_str(self):
        li = conftest.MockListItem()
        info = {'studio': 'MAPPA / Wit Studio'}
        control.set_videotags(li, info)
        self.assertEqual(li.getVideoInfoTag().getStudios(), ['MAPPA'])
        self.assertEqual(li.getProperty('Studio'), 'MAPPA')
        self.assertEqual(li.getProperty('Studios'), 'MAPPA / Wit Studio')

    def test_xbmc_add_dir_studio_art_coloured(self):
        art = {'poster': 'https://example.com/poster.jpg'}
        info = {'studio': ['CloverWorks']}
        bulk_prefs = {
            'artwork_fanart_enabled': False,
            'fanart_select_enabled': False,
            'artwork_clearlogo_enabled': False,
            'artwork_studios_style': 'coloured',
        }
        u, liz, isfolder = control.xbmc_add_dir(
            'Test Show', 'test/url', art, info, [], True, True, False, bulk_prefs
        )
        expected_art = 'resource://resource.images.animestudio.coloured/CloverWorks.png'
        self.assertEqual(liz.getArt('studio'), expected_art)
        self.assertEqual(liz.getArt('tvshow.studio'), expected_art)
        self.assertEqual(liz.getProperty('Studio'), 'CloverWorks')
        self.assertEqual(liz.getProperty('StudioIcon'), expected_art)
        self.assertEqual(liz.getProperty('StudioLogo'), expected_art)
        self.assertEqual(liz.getProperty('Studio.Icon'), expected_art)
        self.assertEqual(liz.getProperty('Studio.Logo'), expected_art)

    def test_xbmc_add_dir_studio_art_white(self):
        art = {'poster': 'https://example.com/poster.jpg'}
        info = {'studio': 'Science SARU'}
        bulk_prefs = {
            'artwork_fanart_enabled': False,
            'fanart_select_enabled': False,
            'artwork_clearlogo_enabled': False,
            'artwork_studios_style': 'white',
        }
        u, liz, isfolder = control.xbmc_add_dir(
            'Test Show', 'test/url', art, info, [], True, True, False, bulk_prefs
        )
        expected_art = 'resource://resource.images.animestudio.white/Science SARU.png'
        self.assertEqual(liz.getArt('studio'), expected_art)
        self.assertEqual(liz.getArt('tvshow.studio'), expected_art)
        self.assertEqual(liz.getProperty('Studio'), 'Science SARU')
        self.assertEqual(liz.getProperty('StudioIcon'), expected_art)
        self.assertEqual(liz.getProperty('StudioLogo'), expected_art)
        self.assertEqual(liz.getProperty('Studio.Icon'), expected_art)
        self.assertEqual(liz.getProperty('Studio.Logo'), expected_art)

    def test_xbmc_add_dir_studio_art_none(self):
        art = {'poster': 'https://example.com/poster.jpg'}
        info = {'studio': ['ufotable']}
        bulk_prefs = {
            'artwork_fanart_enabled': False,
            'fanart_select_enabled': False,
            'artwork_clearlogo_enabled': False,
            'artwork_studios_style': 'none',
        }
        u, liz, isfolder = control.xbmc_add_dir(
            'Test Show', 'test/url', art, info, [], True, True, False, bulk_prefs
        )
        self.assertEqual(liz.getArt('studio'), '')
        self.assertEqual(liz.getArt('tvshow.studio'), '')
        self.assertEqual(liz.getProperty('StudioIcon'), '')
        self.assertEqual(liz.getProperty('StudioLogo'), '')
        self.assertEqual(liz.getProperty('Studio'), 'ufotable')

    def test_resolver_build_art_dict_propagates_studio(self):
        resolver = Resolver.__new__(Resolver)
        resolver.image = {
            'poster': 'https://example.com/poster.jpg',
            'studio': 'resource://resource.images.animestudio.coloured/Bones.png',
            'tvshow.studio': 'resource://resource.images.animestudio.coloured/Bones.png',
        }
        resolver.params = {}

        art_dict = resolver._build_art_dict(use_params=False)
        self.assertEqual(art_dict['studio'], 'resource://resource.images.animestudio.coloured/Bones.png')
        self.assertEqual(art_dict['tvshow.studio'], 'resource://resource.images.animestudio.coloured/Bones.png')

        resolver.params = {
            'studio': 'resource://resource.images.animestudio.white/Bones.png',
            'tvshow.studio': 'resource://resource.images.animestudio.white/Bones.png',
        }
        param_art_dict = resolver._build_art_dict(use_params=True)
        self.assertEqual(param_art_dict['studio'], 'resource://resource.images.animestudio.white/Bones.png')
        self.assertEqual(param_art_dict['tvshow.studio'], 'resource://resource.images.animestudio.white/Bones.png')


if __name__ == '__main__':
    unittest.main()
