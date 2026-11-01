"""
test_domains.py — Unit tests for Dynamic Domain Auto-Resolver
=============================================================
Tests dynamic domain resolution, local caching, bundled fallback loading,
user proxy/alt settings overrides, domain refresh, and HiAnime mirror management.
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

import socket
import unittest
from unittest.mock import patch, MagicMock

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

    def test_get_hianime_mirrors(self):
        """get_hianime_mirrors returns normalized list with primary mirror first."""
        mirrors = domains.get_hianime_mirrors()
        self.assertIsInstance(mirrors, list)
        self.assertGreaterEqual(len(mirrors), 1)
        self.assertTrue(mirrors[0].startswith('https://hianime.'))
        for m in mirrors:
            self.assertTrue(m.endswith('/'))

    def test_fetch_domains_from_hianime_pw_mock(self):
        """fetch_domains_from_hianime_pw parses canonical link and mirrors from HTML."""
        mock_html = """
        <html>
        <head>
          <link rel="canonical" href="https://hianime.at/" />
        </head>
        <body>
          <a href="https://hianime.at/">Primary</a>
          <a href="https://hianime.ba/">Mirror BA</a>
          <a href="https://hianime.gy/">Mirror GY</a>
          <a href="https://hianime.pw/">Landing (Ignore)</a>
          <a href="https://hianimetv.bz/">Mirror BZ</a>
        </body>
        </html>
        """
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = mock_html

        with patch('resources.lib.ui.client.get', return_value=mock_resp):
            res = domains.fetch_domains_from_hianime_pw()
            self.assertIsNotNone(res)
            primary, mirrors = res
            self.assertEqual(primary, 'https://hianime.at/')
            self.assertIn('https://hianime.at/', mirrors)
            self.assertIn('https://hianime.ba/', mirrors)
            self.assertIn('https://hianime.gy/', mirrors)
            self.assertIn('https://hianimetv.bz/', mirrors)
            # Ensure landing page pw is filtered out
            self.assertFalse(any('hianime.pw' in m for m in mirrors))

    def test_refresh_hianime_domains_success(self):
        """refresh_hianime_domains successfully updates cache with fetched mirrors."""
        mock_mirrors = ('https://hianime.at/', ['https://hianime.at/', 'https://hianime.ba/'])
        with patch('resources.lib.ui.domains.fetch_domains_from_hianime_pw', return_value=mock_mirrors):
            with patch('resources.lib.ui.domains.save_profile_domains', return_value=True):
                success, mirrors = domains.refresh_hianime_domains(force=True)
                self.assertTrue(success)
                self.assertEqual(mirrors, ['https://hianime.at/', 'https://hianime.ba/'])

    def test_refresh_hianime_domains_failure(self):
        """refresh_hianime_domains returns (False, []) on network/parse failure."""
        with patch('resources.lib.ui.domains.fetch_domains_from_hianime_pw', return_value=None):
            success, mirrors = domains.refresh_hianime_domains(force=True)
            self.assertFalse(success)
            self.assertEqual(mirrors, [])

    def test_is_internet_available_socket_success(self):
        """is_internet_available returns True when socket connects."""
        mock_sock = MagicMock()
        with patch('socket.create_connection', return_value=mock_sock):
            self.assertTrue(domains.is_internet_available())
            mock_sock.close.assert_called()

    def test_is_internet_available_offline(self):
        """is_internet_available returns False when socket and HTTP fail."""
        with patch('socket.create_connection', side_effect=socket.error("Offline")):
            with patch('resources.lib.ui.client.get', side_effect=Exception("Unreachable")):
                self.assertFalse(domains.is_internet_available())

    def test_refresh_domains_network_mock(self):
        """refresh_domains successfully parses remote JSON and updates cache."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "hianime": "https://hianime.at/",
            "nyaa": "https://nyaa.si/",
            "_meta": {"source": "mock"}
        }

        with patch('resources.lib.ui.client.get', return_value=mock_resp):
            success = domains.refresh_domains()
            self.assertTrue(success)
            self.assertEqual(domains.get_domain('hianime'), 'https://hianime.at/')


if __name__ == '__main__':
    unittest.main()