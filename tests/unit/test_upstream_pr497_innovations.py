# -*- coding: utf-8 -*-
"""
test_upstream_pr497_innovations.py - Unit tests for PR #497 ISO 639-2 matching & Easynews colon sanitizing
"""

import unittest
from unittest.mock import patch, MagicMock
from resources.lib.ui.player import is_language_match
from resources.lib.debrid.easynews import Easynews


class TestPR497Innovations(unittest.TestCase):

    def test_easynews_colon_sanitization(self):
        en = Easynews()
        en.username = 'test_user'
        en.password = 'test_pass'

        with patch('resources.lib.debrid.easynews.client.get') as mock_get:
            mock_resp = MagicMock()
            mock_resp.ok = True
            mock_resp.json.return_value = {'data': []}
            mock_get.return_value = mock_resp

            en.search("Bleach: Thousand-Year Blood War")

            # Verify query sent to Solr API stripped the colon
            self.assertTrue(mock_get.called)
            call_kwargs = mock_get.call_args[1]
            params = call_kwargs['params']
            self.assertEqual(params['gps'], "Bleach  Thousand-Year Blood War")
            self.assertNotIn(":", params['gps'])

    def test_iso_639_2_language_matching_kodi_builtin(self):
        # Test matching via synonym dictionaries
        self.assertTrue(is_language_match('ja', 'Stereo', 'jpn'))
        self.assertTrue(is_language_match('ja-JP', 'Japanese', 'jpn'))
        self.assertTrue(is_language_match('en', 'Surround', 'eng'))
        self.assertTrue(is_language_match('en-US', 'English', 'eng'))

        # Test xbmc.convertLanguage normalization fallback
        import xbmc
        with patch.object(xbmc, 'convertLanguage', side_effect=lambda l, fmt: 'jpn' if l in ('ja', 'japanese') else 'eng'):
            self.assertTrue(is_language_match('ja', '', 'jpn'))
            self.assertTrue(is_language_match('japanese', '', 'jpn'))


if __name__ == '__main__':
    unittest.main()
