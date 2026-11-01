"""
Unit tests for Otaku Provider Color Palette & Branding (colors.py)
"""

import unittest
import tests.conftest  # noqa: F401
from resources.lib.ui import colors


class TestColors(unittest.TestCase):

    def test_provider_color_mappings(self):
        """Standard providers map to distinctive branding hex colors."""
        self.assertEqual(colors.get_provider_color('Premiumize'), 'FF4700B4')
        self.assertEqual(colors.get_provider_color('premiumize'), 'FF4700B4')
        self.assertEqual(colors.get_provider_color('Real-Debrid'), 'FF0080FF')
        self.assertEqual(colors.get_provider_color('realdebrid'), 'FF0080FF')
        self.assertEqual(colors.get_provider_color('TorBox'), 'FFFF8000')
        self.assertEqual(colors.get_provider_color('AllDebrid'), 'FF00CC66')
        self.assertEqual(colors.get_provider_color('Debrid-Link'), 'FFFF0055')
        self.assertEqual(colors.get_provider_color('HiAnime'), 'FF00E5FF')
        self.assertEqual(colors.get_provider_color('AniKoto'), 'FFFF4081')

    def test_fallback_color(self):
        """Unknown or empty providers receive safe fallback grey."""
        self.assertEqual(colors.get_provider_color('UnknownProvider'), 'FFB0BEC5')
        self.assertEqual(colors.get_provider_color(''), 'FFB0BEC5')
        self.assertEqual(colors.get_provider_color(None), 'FFB0BEC5')

    def test_colorize_label(self):
        """colorize_label wraps text in Kodi COLOR tags with matching provider hex."""
        tagged = colors.colorize_label('Premiumize', 'Premiumize')
        self.assertEqual(tagged, '[COLOR FF4700B4]Premiumize[/COLOR]')

        fallback = colors.colorize_label('Unknown', 'random_service')
        self.assertEqual(fallback, '[COLOR FFB0BEC5]Unknown[/COLOR]')


if __name__ == '__main__':
    unittest.main()
