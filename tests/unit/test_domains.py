"""
test_domains.py — Unit tests for Dynamic Domain Auto-Resolver
=============================================================
Tests dynamic domain resolution, local caching, bundled fallback loading,
user proxy/alt settings overrides, and domain refresh.
"""

import unittest
from unittest.mock import patch, MagicMock

import conftest  # Sets up xbmc, xbmcaddon mocks
from resources.lib.ui import control, domains


class TestDomains(unittest.TestCase):

    def test_default_domain_lookups(self):
        """Standard providers return non-empty URL strings ending with slash or path."""
        providers = ['hianime', 'gogoanime', 'animepahe', 'animekai', 'anikoto', 'nyaa', 'animetosho', 'nekobt', 'torrentio', 'watchnixtoons2']
        for p in providers:
            d = domains.get_domain(p)
            self.assertTrue(d.startswith('http'), f"Provider {p} returned invalid URL: {d}")

    def test_fallback_for_unknown_provider(self):
        """Unknown provider returns custom fallback or empty string."""
        d = domains.get_domain('nonexistent_provider', default='https://fallback.com/')
        self.assertEqual(d, 'https://fallback.com/')

    def test_nyaa_alt_setting_override(self):
        """When provider.nyaaalt is True, returns google translate proxy URL."""
        with patch.object(control, 'getBool', side_effect=lambda k: k == 'provider.nyaaalt'):
            d = domains.get_domain('nyaa')
            self.assertIn('translate.goog', d)

    def test_animetosho_alt_setting_override(self):
        """When provider.animetoshoalt is True, returns google translate proxy URL."""
        with patch.object(control, 'getBool', side_effect=lambda k: k == 'provider.animetoshoalt'):
            d = domains.get_domain('animetosho')
            self.assertIn('translate.goog', d)

    def test_get_all_domains(self):
        """get_all_domains returns dictionary containing core providers."""
        all_d = domains.get_all_domains()
        self.assertIsInstance(all_d, dict)
        self.assertIn('hianime', all_d)
        self.assertIn('nyaa', all_d)
        self.assertIn('animetosho', all_d)

    def test_refresh_domains_network_mock(self):
        """refresh_domains successfully parses remote JSON and updates cache."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "hianime": "https://hianime.to/",
            "nyaa": "https://nyaa.si/",
            "_meta": {"source": "mock"}
        }

        with patch('resources.lib.ui.client.get', return_value=mock_resp):
            success = domains.refresh_domains()
            self.assertTrue(success)
            self.assertEqual(domains.get_domain('hianime'), 'https://hianime.to/')


if __name__ == '__main__':
    unittest.main()
