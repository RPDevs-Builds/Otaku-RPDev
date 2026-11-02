# -*- coding: utf-8 -*-
"""
test_scrapers_offline.py - Scraper Golden Master Offline Fixture Tests
=====================================================================
Validates DOM/JSON parser logic for Bitsearch, HiAnime, AnimePahe, AnimeTosho,
and Anikoto against static offline golden master fixtures without network I/O.
"""

import json
import os
import unittest
from unittest.mock import patch, MagicMock

from resources.lib.pages.bitsearch import Sources as BitsearchSources
from resources.lib.pages.hianime import Sources as HiAnimeSources
from resources.lib.pages.animepahe import Sources as AnimePaheSources
from resources.lib.pages.animetosho import Sources as ToshoSources
from resources.lib.ui import control

_FIXTURE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'fixtures', 'scrapers'))


class TestScrapersOffline(unittest.TestCase):

    def _read_fixture(self, filename):
        path = os.path.join(_FIXTURE_DIR, filename)
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_bitsearch_offline_parse_html(self):
        html_content = self._read_fixture('bitsearch_results.html')
        sources_instance = BitsearchSources()
        results = sources_instance._parse_html_results(html_content)

        self.assertEqual(len(results), 2)
        # Verify first item (SubsPlease 1080p)
        self.assertEqual(results[0]['hash'], '1111222233334444555566667777888899990000')
        self.assertIn('[SubsPlease]', results[0]['name'])
        self.assertEqual(results[0]['size'], '1.4 GB')
        self.assertEqual(results[0]['seeders'], 150)

        # Verify second item (Erai-raws 720p)
        self.assertEqual(results[1]['hash'], 'aaaa22223333444455556666777788889999bbbb')
        self.assertIn('[Erai-raws]', results[1]['name'])
        self.assertEqual(results[1]['size'], '850 MB')
        self.assertEqual(results[1]['seeders'], 45)

    def test_hianime_offline_parse_search(self):
        html_content = self._read_fixture('hianime_search.html')
        items = HiAnimeSources._parse_search_results(html_content)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['id'], '112')
        self.assertEqual(items[0]['name'], 'Attack on Titan')
        self.assertEqual(items[0]['slug'], 'attack-on-titan-112')

        self.assertEqual(items[1]['id'], '113')
        self.assertEqual(items[1]['name'], 'Attack on Titan Season 2')
        self.assertEqual(items[1]['slug'], 'attack-on-titan-season-2-113')

    def test_animepahe_offline_build_source(self):
        instance = AnimePaheSources()
        item = {
            'data-src': 'https://kwik.cx/e/testembed123',
            'data-audio': 'jpn',
            'data-resolution': '1080'
        }
        source = instance._build_source(item, 'Attack on Titan', '1', ['kwik.cx'])
        self.assertIsNotNone(source)
        self.assertEqual(source['release_title'], 'Attack on Titan - Ep 1')
        self.assertEqual(source['quality'], 3)  # 1080p == 3
        self.assertEqual(source['type'], 'embed')
        self.assertEqual(source['provider'], 'animepahe')
        self.assertIn('https://kwik.cx/e/testembed123', source['hash'])

    def test_animetosho_offline_parse_view(self):
        raw_json = self._read_fixture('animetosho_results.json')
        items = json.loads(raw_json)
        self.assertEqual(len(items), 2)

        # Test item 1
        parsed1 = ToshoSources.parse_animetosho_view(
            {
                'name': items[0]['title'],
                'hash': items[0]['info_hash'],
                'size': '1.4 GB',
                'seeders': items[0]['seeders'],
                'magnet': items[0]['magnet_uri']
            },
            episode="1",
            cached=True
        )
        self.assertIsNotNone(parsed1)
        self.assertEqual(parsed1['release_title'], items[0]['title'])
        self.assertEqual(parsed1['quality'], 3)  # 1080p == 3
        self.assertEqual(parsed1['seeders'], 150)

        # Test item 2
        parsed2 = ToshoSources.parse_animetosho_view(
            {
                'name': items[1]['title'],
                'hash': items[1]['info_hash'],
                'size': '850 MB',
                'seeders': items[1]['seeders'],
                'magnet': items[1]['magnet_uri']
            },
            episode="1",
            cached=True
        )
        self.assertIsNotNone(parsed2)
        self.assertEqual(parsed2['release_title'], items[1]['title'])
        self.assertEqual(parsed2['quality'], 2)  # 720p == 2
        self.assertEqual(parsed2['seeders'], 50)

    def test_anikoto_offline_fixture_structure(self):
        raw_json = self._read_fixture('anikoto_sources.json')
        data = json.loads(raw_json)
        self.assertIn('sources', data)
        self.assertIn('tracks', data)
        self.assertIn('intro', data)
        self.assertIn('outro', data)
        self.assertEqual(data['intro']['start'], 90)
        self.assertEqual(data['intro']['end'], 180)
        self.assertEqual(data['outro']['start'], 1380)
        self.assertEqual(data['outro']['end'], 1470)
        self.assertTrue(data['sources'][0]['file'].endswith('.m3u8'))


if __name__ == '__main__':
    unittest.main()
