"""
test_gogoanime.py - Unit Tests for GogoAnime Scraper Engine
===========================================================
Tests multi-server candidate retention without premature break,
server list parsing, and sub/dub metadata mapping.
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
from unittest.mock import patch

from resources.lib.pages.gogoanime import Sources as GogoSources
from resources.lib.ui import control


class TestGogoAnimeScraper(unittest.TestCase):
    def setUp(self):
        control.clearSettingsCache()
        self.scraper = GogoSources()

    def tearDown(self):
        control.cleanup()

    @patch('resources.lib.ui.database.get')
    def test_process_gogo_collects_all_servers_no_early_break(self, mock_db_get):
        """Verify that all matching servers are retained and premature break is eliminated."""
        sample_html = '''
        <div class="anime_muti_link">
            <ul>
                <li class="vidcdn"><a data-video="//vidstreaming.io/embed/ep1">Vidstreaming</a></li>
                <li class="streamwish"><a data-video="https://streamwish.to/e/ep1">Streamwish</a></li>
                <li class="mp4upload"><a data-video="//www.mp4upload.com/embed-ep1.html">Mp4upload</a></li>
            </ul>
        </div>
        '''
        mock_db_get.return_value = sample_html

        with patch.object(self.scraper, 'embeds', return_value=['vidcdn', 'streamwish', 'mp4upload']):
            sources = self.scraper._process_gogo('attack-on-titan', 1234, 1)

        # Must have collected all 3 servers rather than breaking after the first one
        self.assertEqual(len(sources), 3)
        self.assertEqual(sources[0]['info'], ['VIDCDN SUB'])
        self.assertEqual(sources[0]['hash'], 'https://vidstreaming.io/embed/ep1')
        self.assertEqual(sources[1]['info'], ['STREAMWISH SUB'])
        self.assertEqual(sources[1]['hash'], 'https://streamwish.to/e/ep1')
        self.assertEqual(sources[2]['info'], ['MP4UPLOAD SUB'])
        self.assertEqual(sources[2]['hash'], 'https://www.mp4upload.com/embed-ep1.html')

    @patch('resources.lib.ui.database.get')
    def test_process_gogo_filters_unsupported_servers(self, mock_db_get):
        """Verify unsupported servers are skipped while enabled ones are collected."""
        sample_html = '''
        <div class="anime_muti_link">
            <ul>
                <li class="unknown_host"><a data-video="https://unknown.com/embed">Unknown</a></li>
                <li class="vidcdn"><a data-video="https://vidcdn.com/embed">Vidcdn</a></li>
            </ul>
        </div>
        '''
        mock_db_get.return_value = sample_html

        with patch.object(self.scraper, 'embeds', return_value=['vidcdn']):
            sources = self.scraper._process_gogo('one-piece', 21, 1000)

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]['info'], ['VIDCDN SUB'])

    @patch('resources.lib.ui.database.get')
    def test_process_gogo_sub_vs_dub_language_tagging(self, mock_db_get):
        """Verify dub returns lang=3 and sub returns lang=2."""
        sample_html = '''
        <div class="anime_muti_link">
            <ul>
                <li class="vidcdn"><a data-video="https://vidcdn.com/embed">Vidcdn</a></li>
            </ul>
        </div>
        '''
        mock_db_get.return_value = sample_html

        with patch.object(self.scraper, 'embeds', return_value=['vidcdn']):
            sub_sources = self.scraper._process_gogo('naruto', 20, 1)
            dub_sources = self.scraper._process_gogo('naruto-dub', 20, 1)

        self.assertEqual(sub_sources[0]['lang'], 2)
        self.assertEqual(dub_sources[0]['lang'], 3)
        self.assertEqual(sub_sources[0]['info'], ['VIDCDN SUB'])
        self.assertEqual(dub_sources[0]['info'], ['VIDCDN DUB'])


if __name__ == '__main__':
    unittest.main()
