# -*- coding: utf-8 -*-
"""
test_subsystem_hardening_v598.py - Unit Tests for Subsystem Maturity & Hardening (v5.9.8)
========================================================================================
Covers the 6 core pillars:
1. Scraper URL Normalization & Double Slash Elimination (animetosho, bitsearch, nekobt, piratebay)
2. Safe Selection Dictionary Keys & Cancel State Handling (source_utils.user_select & get_best_match)
3. High-Frequency Source Regex Precompilation in Franchise Filtering (part_filter._RE_BATCH_RANGE)
4. OAuth Progress Dialog Lifecycle Cleanup & Window Memory Leaks (debrid & simkl auth loops)
5. Managed Context File Descriptors in Metadata Endpoints (endpoints.mal.Mal)
6. Resilient Fallback JSON Parsing Across Watchlist Flavors (MAL, Kitsu, Simkl, AniList)
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_TEST_DIR, '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
_TESTS_DIR = os.path.join(_REPO_ROOT, 'tests')
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import conftest  # noqa: F401


class TestSubsystemHardeningV598(unittest.TestCase):

    # -------------------------------------------------------------------------
    # Pillar 1: Scraper URL Normalization & Double Slash Elimination
    # -------------------------------------------------------------------------

    def test_animetosho_url_rstrip(self):
        from resources.lib.pages.animetosho import Sources as AnimetoshoSources
        scraper = AnimetoshoSources()
        scraper._BASE_URL = 'https://animetosho.org/'
        with patch.object(scraper, 'process_animetosho_episodes', return_value=[]) as mock_ep:
            scraper.get_show_sources('Frieren', 52991, 1, 1, None)
            mock_ep.assert_called_once()
            called_url = mock_ep.call_args[0][0]
            self.assertEqual(called_url, 'https://animetosho.org/search')
            self.assertNotIn('//search', called_url)

    def test_bitsearch_url_rstrip(self):
        from resources.lib.pages.bitsearch import Sources as BitsearchSources
        scraper = BitsearchSources()
        scraper._BASE_URL = 'https://bitsearch.to/'
        with patch('resources.lib.pages.bitsearch.client.get', return_value=None) as mock_get:
            scraper._fetch_search_results('Bleach')
            mock_get.assert_called_once()
            called_url = mock_get.call_args[0][0]
            self.assertTrue(called_url.startswith('https://bitsearch.to/search?q='))
            self.assertNotIn('//search', called_url)

    def test_piratebay_url_rstrip(self):
        from resources.lib.pages.piratebay import Sources as PiratebaySources
        scraper = PiratebaySources()
        scraper._BASE_URL = 'https://apibay.org/'
        with patch('resources.lib.pages.piratebay.client.get', return_value=None) as mock_get:
            scraper._fetch_apibay_results('Naruto')
            mock_get.assert_called_once()
            called_url = mock_get.call_args[0][0]
            self.assertTrue(called_url.startswith('https://apibay.org/q.php?q='))
            self.assertNotIn('//q.php', called_url)

    def test_nekobt_url_rstrip(self):
        from resources.lib.pages.nekobt import Sources as NekoBTSources
        scraper = NekoBTSources()
        scraper._BASE_URL = 'https://nekobt.to/api/v1/'
        with patch('resources.lib.pages.nekobt.client.get', return_value=None) as mock_get:
            scraper._resolve_media_id(['One Piece'], 21)
            mock_get.assert_called_once()
            called_url = mock_get.call_args[0][0]
            self.assertTrue(called_url.startswith('https://nekobt.to/api/v1/media/search'))
            self.assertNotIn('//media', called_url)

    # -------------------------------------------------------------------------
    # Pillar 2: Safe Selection Dictionary Keys & Cancel State Handling
    # -------------------------------------------------------------------------

    def test_user_select_cancel_safe_dict_keys(self):
        from resources.lib.ui import source_utils
        with patch('resources.lib.ui.control.select_dialog', return_value=-1):
            res = source_utils.user_select([{'short_name': 'test.mkv', 'path': '/path/test.mkv'}], 'short_name')
            self.assertEqual(res, [{'short_name': '', 'path': ''}])
            # Verify accessing 'short_name' does not raise KeyError
            self.assertEqual(res[0]['short_name'], '')
            self.assertEqual(res[0]['path'], '')

    def test_get_best_match_cancel_sets_false_and_no_keyerror(self):
        from resources.lib.ui import source_utils, control
        files = [
            {'short_name': 'Ep 01.mkv', 'path': '/cloud/Ep 01.mkv'},
            {'short_name': 'Ep 02.mkv', 'path': '/cloud/Ep 02.mkv'}
        ]
        # Simulate user cancelling selection dialog
        with patch('resources.lib.ui.control.select_dialog', return_value=-1):
            match = source_utils.get_best_match('short_name', files, 1, pack_select=True)
            self.assertEqual(match, {'short_name': '', 'path': ''})
            # Verify accessing dict_key directly works without KeyError
            self.assertEqual(match['short_name'], '')
            self.assertEqual(match['path'], '')
            # Verify best_match flag was reset to False
            self.assertFalse(control.getBool('best_match'))

    # -------------------------------------------------------------------------
    # Pillar 3: High-Frequency Source Regex Precompilation in Franchise Filtering
    # -------------------------------------------------------------------------

    def test_part_filter_precompiled_regex(self):
        from resources.lib.ui import part_filter
        import re
        self.assertIsInstance(part_filter._RE_BATCH_RANGE, re.Pattern)
        self.assertEqual(part_filter._extract_batch_range('[01-12] title'), (1, 12))
        self.assertEqual(part_filter._extract_batch_range('(01~24) show'), (1, 24))
        self.assertEqual(part_filter._extract_batch_range('show 05–10 '), (5, 10))
        self.assertEqual(part_filter._extract_batch_range('standalone episode 05'), (None, None))

    # -------------------------------------------------------------------------
    # Pillar 4: OAuth Progress Dialog Lifecycle Cleanup & Window Memory Leaks
    # -------------------------------------------------------------------------

    def test_torbox_auth_dialog_lifecycle_cleanup(self):
        from resources.lib.debrid.torbox import TorBox
        tb = TorBox()
        mock_dlg = MagicMock()
        mock_dlg.iscanceled.return_value = True  # Cancel immediately

        device_resp = MagicMock()
        device_resp.ok = True
        device_resp.json.return_value = {
            'data': {
                'device_code': 'dev123',
                'code': 'USR1',
                'friendly_verification_url': 'https://torbox.app/oauth/device',
                'interval': 1,
                'expires_at': '2030-01-01T00:00:00Z'
            }
        }

        with patch('resources.lib.debrid.torbox.client.get', return_value=device_resp):
            with patch('resources.lib.windows.progress_dialog.Progress_dialog', return_value=mock_dlg):
                with patch('resources.lib.ui.control.sleep'):
                    tb.auth()
                    # Dialog must be closed and deleted
                    mock_dlg.close.assert_called()
                    self.assertIsNone(tb.dialog)

    def test_simkl_auth_dialog_lifecycle_cleanup(self):
        from resources.lib.WatchlistFlavor.Simkl import SimklWLF
        simkl = SimklWLF()
        mock_dlg = MagicMock()
        mock_dlg.iscanceled.return_value = True

        pin_resp = MagicMock()
        pin_resp.json.return_value = {
            'user_code': 'USR1',
            'interval': 1,
            'expires_in': 60,
            'verification_url': 'https://simkl.com/pin'
        }

        with patch('resources.lib.WatchlistFlavor.Simkl.client.get', return_value=pin_resp):
            with patch('resources.lib.windows.progress_dialog.Progress_dialog', return_value=mock_dlg):
                with patch('resources.lib.ui.control.sleep'):
                    result = simkl.login()
                    self.assertIsNone(result)
                    mock_dlg.close.assert_called()

    # -------------------------------------------------------------------------
    # Pillar 5: Managed Context File Descriptors in Metadata Endpoints
    # -------------------------------------------------------------------------

    def test_mal_get_cached_data_context_manager(self):
        import tempfile
        import json
        from resources.lib.endpoints.mal import Mal
        from resources.lib.ui import control

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as tmp:
            json.dump({'data': 'calendar_test'}, tmp)
            tmp_path = tmp.name

        try:
            with patch.object(control, 'mal_calendar_json', tmp_path):
                mal = Mal()
                data = mal.get_cached_data()
                self.assertEqual(data, {'data': 'calendar_test'})
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    # -------------------------------------------------------------------------
    # Pillar 6: Resilient Fallback JSON Parsing Across Watchlist Flavors
    # -------------------------------------------------------------------------

    def test_watchlist_flavors_absorb_html_maintenance(self):
        from resources.lib.WatchlistFlavor.MyAnimeList import MyAnimeListWLF
        from resources.lib.WatchlistFlavor.Kitsu import KitsuWLF
        from resources.lib.WatchlistFlavor.Simkl import SimklWLF
        from resources.lib.WatchlistFlavor.AniList import AniListWLF
        from resources.lib.ui.client import Response

        # Mock HTML challenge / captive portal returning 200 OK with HTML body
        html_resp_200 = Response(
            b"<html><head><title>Captcha Challenge</title></head><body>Please verify</body></html>",
            status_code=200
        )

        with patch('resources.lib.ui.client.get', return_value=html_resp_200):
            mal = MyAnimeListWLF()
            # MAL with empty stats produces default counters, does not crash with ValueError
            self.assertEqual(mal.get_last_activity_timestamp(), "0_0_0_0_0_0_0")

            kitsu = KitsuWLF()
            kitsu.user_id = '12345'
            self.assertIsNone(kitsu.get_last_activity_timestamp())

            simkl = SimklWLF()
            self.assertIsNone(simkl.get_last_activity_timestamp())

        with patch('resources.lib.ui.client.post', return_value=html_resp_200):
            anilist = AniListWLF()
            self.assertIsNone(anilist.get_last_activity_timestamp())


if __name__ == '__main__':
    unittest.main()
