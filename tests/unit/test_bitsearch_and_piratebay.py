"""
test_bitsearch_and_piratebay.py — Unit Tests for Bitsearch and PirateBay Scrapers
==================================================================================
Tests HTML parsing, JSON parsing, magnet/hash extraction, view construction,
caching flags, quality tags, and registration for the Bitsearch and ThePirateBay
torrent scrapers.
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
from unittest.mock import patch, MagicMock

from resources.lib.pages import _TORRENT_MODULES
from resources.lib.pages.bitsearch import Sources as BitsearchSources
from resources.lib.pages.piratebay import Sources as PiratebaySources
from resources.lib.ui import colors, domains, source_utils


class TestBitsearchScraper(unittest.TestCase):

    def setUp(self):
        self.bitsearch = BitsearchSources()

    def test_parse_bitsearch_view_cached(self):
        res = {
            'name': '[SubsPlease] Dandadan - 01 (1080p) [ABCD1234].mkv',
            'hash': 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678',
            'size': '1.35 GB',
            'byte_size': 1449551462,
            'seeders': 250,
            'magnet': 'magnet:?xt=urn:btih:a1b2c3d4e5f60718293a4b5c6d7e8f9012345678&dn=Dandadan'
        }
        parsed = BitsearchSources.parse_bitsearch_view(res, episode='1', cached=True)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['release_title'], res['name'])
        self.assertEqual(parsed['hash'], res['hash'])
        self.assertEqual(parsed['provider'], 'bitsearch')
        self.assertEqual(parsed['type'], 'torrent')
        self.assertEqual(parsed['quality'], 3)  # 1080p == 3
        self.assertEqual(parsed['seeders'], 250)
        self.assertTrue(parsed['cached'])
        self.assertNotIn('magnet', parsed)

    def test_parse_bitsearch_view_uncached(self):
        res = {
            'name': '[Erai-raws] Dandadan - 01 [720p].mkv',
            'hash': 'b1b2c3d4e5f60718293a4b5c6d7e8f9012345678',
            'size': '750 MB',
            'byte_size': 786432000,
            'seeders': 45,
            'magnet': 'magnet:?xt=urn:btih:b1b2c3d4e5f60718293a4b5c6d7e8f9012345678&dn=Dandadan'
        }
        parsed = BitsearchSources.parse_bitsearch_view(res, episode='1', cached=False)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['quality'], 2)  # 720p == 2
        self.assertFalse(parsed['cached'])
        self.assertIn('(uncached)', parsed['type'])
        self.assertEqual(parsed['magnet'], res['magnet'])

    def test_html_card_parsing(self):
        sample_html = """
        <html>
        <body>
            <div class="torrent-result-card mb-3 p-3">
                <h5 class="title"><a href="/torrent/12345">[Bitsearch.to] [SubsPlease] Solo Leveling - 01 (1080p) [FEDCBA98].mkv</a></h5>
                <div class="stats">
                    <span>1.4 GB</span>
                    <span>120 seeders</span>
                    <span>15 leechers</span>
                    <span>500 downloads</span>
                </div>
                <div class="links">
                    <a href="magnet:?xt=urn:btih:c1c2c3d4e5f60718293a4b5c6d7e8f9012345678&amp;dn=%5BBitsearch.to%5D%20%5BSubsPlease%5D%20Solo%20Leveling%20-%2001%20(1080p)%20%5BFEDCBA98%5D.mkv">Download</a>
                </div>
            </div>
        </body>
        </html>
        """
        results = self.bitsearch._parse_html_results(sample_html)
        self.assertEqual(len(results), 1)
        item = results[0]
        self.assertEqual(item['hash'], 'c1c2c3d4e5f60718293a4b5c6d7e8f9012345678')
        # Title should have [Bitsearch.to] prefix stripped
        self.assertIn('[SubsPlease] Solo Leveling', item['name'])
        self.assertNotIn('[Bitsearch.to]', item['name'])
        self.assertEqual(item['seeders'], 120)
        self.assertEqual(item['leechers'], 15)
        self.assertEqual(item['size'], '1.4 GB')
        self.assertGreater(item['byte_size'], 1000000000)

    def test_html_card_fallback_parsing(self):
        # Card without the expected class name but containing magnet link
        sample_html = """
        <div>
            <div>
                <h3>[Judas] Bleach TYBW - 01 [1080p][HEVC].mkv</h3>
                <span>650 MB</span> <span>80 seeders</span>
                <a href="magnet:?xt=urn:btih:d1d2c3d4e5f60718293a4b5c6d7e8f9012345678&amp;dn=Bleach">Magnet</a>
            </div>
        </div>
        """
        results = self.bitsearch._parse_html_results(sample_html)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['hash'], 'd1d2c3d4e5f60718293a4b5c6d7e8f9012345678')
        self.assertIn('[Judas] Bleach', results[0]['name'])


class TestPirateBayScraper(unittest.TestCase):

    def setUp(self):
        self.pb = PiratebaySources()

    def test_parse_piratebay_view_cached(self):
        res = {
            'name': 'One Piece - 1000 (1080p) [Dual-Audio] [English Dub]',
            'hash': 'e1e2c3d4e5f60718293a4b5c6d7e8f9012345678',
            'size': '1.20 GB',
            'byte_size': 1288490188,
            'seeders': 320,
            'magnet': 'magnet:?xt=urn:btih:e1e2c3d4e5f60718293a4b5c6d7e8f9012345678&dn=One+Piece'
        }
        parsed = PiratebaySources.parse_piratebay_view(res, episode='1000', cached=True)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['release_title'], res['name'])
        self.assertEqual(parsed['hash'], res['hash'])
        self.assertEqual(parsed['provider'], 'piratebay')
        self.assertEqual(parsed['type'], 'torrent')
        self.assertEqual(parsed['quality'], 3)  # 1080p == 3
        self.assertEqual(parsed['seeders'], 320)
        self.assertTrue(parsed['cached'])
        self.assertNotIn('magnet', parsed)

    def test_parse_piratebay_view_uncached(self):
        res = {
            'name': 'One Piece - 1000 (480p)',
            'hash': 'f1f2c3d4e5f60718293a4b5c6d7e8f9012345678',
            'size': '350.00 MB',
            'byte_size': 367001600,
            'seeders': 10,
            'magnet': 'magnet:?xt=urn:btih:f1f2c3d4e5f60718293a4b5c6d7e8f9012345678&dn=One+Piece'
        }
        parsed = PiratebaySources.parse_piratebay_view(res, episode='1000', cached=False)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['quality'], 1)  # 480p == 1
        self.assertFalse(parsed['cached'])
        self.assertIn('(uncached)', parsed['type'])
        self.assertEqual(parsed['magnet'], res['magnet'])

    def test_apibay_json_parsing(self):
        sample_json = [
            {
                "id": "123456",
                "name": "[Anime Time] Sousou no Frieren (Season 1) [1080p][HEVC 10bit x265][Dual-Audio]",
                "info_hash": "A1B2C3D4E5F60718293A4B5C6D7E8F9012345678",
                "leechers": "25",
                "seeders": "180",
                "num_files": "28",
                "size": "15000000000",
                "username": "AnimeTime",
                "added": "1700000000",
                "category": "205",
                "imdb": ""
            }
        ]
        results = self.pb._parse_apibay_results(sample_json)
        self.assertEqual(len(results), 1)
        item = results[0]
        # Should be lowercase hash
        self.assertEqual(item['hash'], 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678')
        self.assertEqual(item['seeders'], 180)
        self.assertEqual(item['leechers'], 25)
        self.assertEqual(item['byte_size'], 15000000000)
        self.assertIn('GB', item['size'])
        self.assertTrue(item['magnet'].startswith('magnet:?xt=urn:btih:a1b2c3d4e5f60718293a4b5c6d7e8f9012345678'))

    def test_apibay_empty_response(self):
        # Apibay returns id="0" when no results are found
        empty_response = [{"id": "0", "name": "No results returned", "info_hash": "0000000000000000000000000000000000000000"}]
        results = self.pb._parse_apibay_results(empty_response)
        self.assertEqual(results, [])

    def test_apibay_invalid_payload(self):
        self.assertEqual(self.pb._parse_apibay_results("not valid json"), [])
        self.assertEqual(self.pb._parse_apibay_results({}), [])


class TestProviderIntegrationRegistration(unittest.TestCase):

    def test_modules_registered_in_pages(self):
        self.assertIn('bitsearch', _TORRENT_MODULES)
        self.assertIn('piratebay', _TORRENT_MODULES)
        mod_bs, key_bs = _TORRENT_MODULES['bitsearch']
        self.assertEqual(key_bs, 'bitsearch')
        self.assertTrue(hasattr(mod_bs, 'Sources'))

        mod_pb, key_pb = _TORRENT_MODULES['piratebay']
        self.assertEqual(key_pb, 'piratebay')
        self.assertTrue(hasattr(mod_pb, 'Sources'))

    def test_colors_registered(self):
        self.assertIn('bitsearch', colors.PROVIDER_COLORS)
        self.assertIn('piratebay', colors.PROVIDER_COLORS)

    def test_domains_registered(self):
        self.assertEqual(domains.get_domain('bitsearch'), 'https://bitsearch.to')
        self.assertEqual(domains.get_domain('piratebay'), 'https://apibay.org')

    def test_source_utils_filter_sources(self):
        # Ensure filter_sources accepts bitsearch and piratebay torrents with valid hashes
        bs_sources = [
            {'name': 'Show - 01 [1080p].mkv', 'hash': 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678'},
            {'name': 'Show - 01 [1080p].mkv'},  # Missing hash
        ]
        pb_sources = [
            {'name': 'Show - 01 [1080p].mkv', 'hash': 'b1b2c3d4e5f60718293a4b5c6d7e8f9012345678'},
            {'name': 'Show - 01 [1080p].mkv'},  # Missing hash
        ]
        with patch('resources.lib.ui.database.get_mappings', return_value={}):
            bs_filtered = source_utils.filter_sources('bitsearch', bs_sources, '52991', episode='1')
            pb_filtered = source_utils.filter_sources('piratebay', pb_sources, '52991', episode='1')
        self.assertEqual(len(bs_filtered), 1)
        self.assertEqual(bs_filtered[0]['hash'], 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678')
        self.assertEqual(len(pb_filtered), 1)
        self.assertEqual(pb_filtered[0]['hash'], 'b1b2c3d4e5f60718293a4b5c6d7e8f9012345678')


if __name__ == '__main__':
    unittest.main()
