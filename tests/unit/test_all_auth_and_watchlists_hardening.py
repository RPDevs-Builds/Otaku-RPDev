import unittest
from unittest.mock import patch, MagicMock
import os
import json

try:
    import conftest
except ImportError:
    import tests.conftest as conftest

from resources.lib.ui import control
from resources.lib.windows.wlf_auth import WatchlistFlavorAuth
from resources.lib.WatchlistFlavor.AniList import AniListWLF
from resources.lib.WatchlistFlavor.MyAnimeList import MyAnimeListWLF
from resources.lib.WatchlistFlavor.Kitsu import KitsuWLF
from resources.lib.WatchlistFlavor import WatchlistFlavor
from resources.lib.debrid.real_debrid import RealDebrid
from resources.lib.debrid.premiumize import Premiumize
from resources.lib.debrid.all_debrid import AllDebrid
from resources.lib.debrid.debrid_link import DebridLink
from resources.lib.debrid.torbox import TorBox
from resources.lib.debrid.easydebrid import EasyDebrid
from resources.lib.debrid.easynews import Easynews


class TestAllAuthAndWatchlistsHardening(unittest.TestCase):

    def setUp(self):
        # Reset settings
        control.setSetting('anilist.username', '')
        control.setSetting('anilist.token', '')
        control.setSetting('anilist.userid', '')
        control.setBool('anilist.enabled', False)

        control.setSetting('mal.authvar', '')
        control.setSetting('mal.token', '')
        control.setSetting('mal.refresh', '')
        control.setBool('mal.enabled', False)

        control.setSetting('kitsu.authvar', '')
        control.setSetting('kitsu.password', '')
        control.setSetting('kitsu.token', '')
        control.setSetting('kitsu.refresh', '')
        control.setBool('kitsu.enabled', False)

        control.setBool('realdebrid.enabled', False)
        control.setBool('premiumize.enabled', False)
        control.setBool('alldebrid.enabled', False)
        control.setBool('debridlink.enabled', False)
        control.setBool('torbox.enabled', False)
        control.setBool('easydebrid.enabled', False)
        control.setBool('easynews.enabled', False)

    # =========================================================================
    # 1. WatchlistFlavorAuth Window Tests
    # =========================================================================
    def test_wlf_auth_qr_code_graceful_fallback(self):
        """Verify onInit does not crash when pyqrcode raises Exception."""
        win = WatchlistFlavorAuth('wlf_auth_anilist.xml', control.ADDON_PATH, flavor='anilist')
        with patch('pyqrcode.create', side_effect=RuntimeError("QR creation failure")):
            win.onInit()
            # Window initialized without crashing, qr_code property cleared
            self.assertEqual(win.getProperty('qr_code'), '')

    def test_wlf_auth_set_settings_validation(self):
        """Verify set_settings rejects empty credentials and accepts valid ones."""
        win = WatchlistFlavorAuth('wlf_auth_anilist.xml', control.ADDON_PATH, flavor='anilist')
        
        # Test empty anilist inputs
        win.getControl = MagicMock()
        win.getControl.side_effect = lambda cid: MagicMock(getText=lambda: "")
        win.close = MagicMock()
        win.set_settings()
        self.assertFalse(win.authorized)
        win.close.assert_not_called()

        # Test valid anilist inputs
        win.getControl.side_effect = lambda cid: MagicMock(getText=lambda: "my_user" if cid == 1000 else "my_token")
        win.set_settings()
        self.assertTrue(win.authorized)
        win.close.assert_called_once()
        self.assertEqual(control.getSetting('anilist.username'), 'my_user')
        self.assertEqual(control.getSetting('anilist.token'), 'my_token')

    # =========================================================================
    # 2. AniList Login Hardening Tests
    # =========================================================================
    def test_anilist_login_empty_credentials(self):
        wlf = AniListWLF('', '', '', '', '', '', 0, 0)
        self.assertIsNone(wlf.login())

    def test_anilist_login_api_failure(self):
        wlf = AniListWLF('', 'test_user', '', '', 'test_token', '', 0, 0)
        with patch('resources.lib.ui.client.post', return_value=None):
            self.assertIsNone(wlf.login())

    def test_anilist_login_success(self):
        wlf = AniListWLF('', 'test_user', '', '', 'test_token', '', 0, 0)
        mock_resp = MagicMock(ok=True)
        mock_resp.json.return_value = {'data': {'User': {'id': 123456}}}
        with patch('resources.lib.ui.client.post', return_value=mock_resp):
            res = wlf.login()
            self.assertEqual(res, {'userid': '123456'})

    # =========================================================================
    # 3. MyAnimeList Login & Refresh Tests
    # =========================================================================
    def test_mal_login_empty_authvar(self):
        wlf = MyAnimeListWLF('', '', '', '', '', '', 0, 0)
        self.assertIsNone(wlf.login())

    def test_mal_login_query_formats(self):
        # 1. Full URL
        wlf1 = MyAnimeListWLF('https://myanimelist.net/v1/oauth2/authorize?code=code123&state=state456', '', '', '', '', '', 0, 0)
        # 2. Raw query string
        wlf2 = MyAnimeListWLF('code=code123&state=state456', '', '', '', '', '', 0, 0)
        # 3. Raw code directly
        wlf3 = MyAnimeListWLF('code123', '', '', '', '', '', 0, 0)

        mock_token_resp = MagicMock(ok=True)
        mock_token_resp.json.return_value = {
            'access_token': 'mal_access',
            'refresh_token': 'mal_refresh',
            'expires_in': 3600
        }
        mock_user_resp = MagicMock(ok=True)
        mock_user_resp.json.return_value = {'name': 'MAL_Tester'}

        with patch('resources.lib.ui.client.post', return_value=mock_token_resp), \
             patch('resources.lib.ui.client.get', return_value=mock_user_resp):
            for wlf in [wlf1, wlf2, wlf3]:
                res = wlf.login()
                self.assertIsNotNone(res)
                self.assertEqual(res['token'], 'mal_access')
                self.assertEqual(res['username'], 'MAL_Tester')

    def test_mal_login_network_failure(self):
        wlf = MyAnimeListWLF('code=code123', '', '', '', '', '', 0, 0)
        with patch('resources.lib.ui.client.post', return_value=None):
            self.assertIsNone(wlf.login())

    def test_mal_refresh_token(self):
        control.setSetting('mal.refresh', 'old_refresh')
        mock_resp = MagicMock(ok=True)
        mock_resp.json.return_value = {
            'access_token': 'new_token',
            'refresh_token': 'new_refresh',
            'expires_in': 7200
        }
        with patch('resources.lib.ui.client.post', return_value=mock_resp):
            MyAnimeListWLF.refresh_token()
            self.assertEqual(control.getSetting('mal.token'), 'new_token')
            self.assertEqual(control.getSetting('mal.refresh'), 'new_refresh')

    # =========================================================================
    # 4. Kitsu Login & Refresh Tests
    # =========================================================================
    def test_kitsu_login_empty_credentials(self):
        wlf = KitsuWLF('', '', '', '', '', '', 0, 0)
        self.assertIsNone(wlf.login())

    def test_kitsu_login_missing_user_data_fallback(self):
        """Verify empty data array in user endpoint doesn't raise IndexError."""
        wlf = KitsuWLF('kitsu_user', '', 'kitsu_pass', '', '', '', 0, 0)
        mock_token_resp = MagicMock(ok=True)
        mock_token_resp.json.return_value = {
            'access_token': 'kitsu_tok',
            'refresh_token': 'kitsu_ref',
            'expires_in': 86400
        }
        mock_user_resp = MagicMock(ok=True)
        mock_user_resp.json.return_value = {'data': []}

        with patch('resources.lib.ui.client.post', return_value=mock_token_resp), \
             patch('resources.lib.ui.client.get', return_value=mock_user_resp):
            res = wlf.login()
            self.assertIsNotNone(res)
            self.assertEqual(res['username'], 'kitsu_user')
            self.assertEqual(res['token'], 'kitsu_tok')

    def test_kitsu_refresh_token(self):
        control.setSetting('kitsu.refresh', 'old_kitsu_refresh')
        mock_resp = MagicMock(ok=True)
        mock_resp.json.return_value = {
            'access_token': 'refreshed_kitsu_tok',
            'refresh_token': 'new_kitsu_ref',
            'expires_in': 86400
        }
        with patch('resources.lib.ui.client.post', return_value=mock_resp):
            KitsuWLF('', '', '', '', '', '', 0, 0).refresh_token()
            self.assertEqual(control.getSetting('kitsu.token'), 'refreshed_kitsu_tok')

    # =========================================================================
    # 5. WatchlistFlavor Request Delegation Tests
    # =========================================================================
    def test_watchlist_flavor_login_request_flow(self):
        with patch.object(AniListWLF, 'login', return_value={'userid': '999', 'username': 'test'}):
            WatchlistFlavor.login_request('anilist')
            self.assertTrue(control.getBool('anilist.enabled'))
            self.assertEqual(control.getSetting('anilist.userid'), '999')

        # Test user cancelled (returns False)
        with patch.object(AniListWLF, 'login', return_value=False), \
             patch('resources.lib.ui.control.ok_dialog') as mock_dlg:
            res = WatchlistFlavor.login_request('anilist')
            self.assertIsNone(res)
            mock_dlg.assert_not_called()

    # =========================================================================
    # 6. Real-Debrid Auth & Polling Tests
    # =========================================================================
    def test_real_debrid_auth_cancellation_and_qr_fallback(self):
        rd = RealDebrid()
        mock_code_resp = MagicMock(ok=True)
        mock_code_resp.json.return_value = {
            'device_code': 'dev123',
            'user_code': 'user123',
            'interval': 1,
            'expires_in': 10
        }
        with patch('resources.lib.ui.client.get', return_value=mock_code_resp), \
             patch('pyqrcode.create', side_effect=Exception("QR error")), \
             patch('resources.lib.windows.progress_dialog.Progress_dialog.iscanceled', side_effect=[False, True]), \
             patch('resources.lib.windows.progress_dialog.Progress_dialog.close') as mock_close:
            rd.auth()
            mock_close.assert_called()
            self.assertFalse(control.getBool('realdebrid.enabled'))

    def test_real_debrid_auth_success(self):
        rd = RealDebrid()
        mock_code_resp = MagicMock(ok=True)
        mock_code_resp.json.return_value = {
            'device_code': 'dev123',
            'user_code': 'user123',
            'interval': 1,
            'expires_in': 10
        }
        with patch('resources.lib.ui.client.get', return_value=mock_code_resp), \
             patch.object(rd, 'auth_loop', return_value=True), \
             patch.object(rd, 'token_request'), \
             patch.object(rd, 'status'):
            rd.auth()
            self.assertTrue(control.getBool('realdebrid.enabled'))

    # =========================================================================
    # 7. Premiumize Auth Tests
    # =========================================================================
    def test_premiumize_auth_success(self):
        prem = Premiumize()
        mock_code_resp = MagicMock(ok=True)
        mock_code_resp.json.return_value = {
            'device_code': 'pdev123',
            'user_code': 'puser123',
            'interval': 1,
            'expires_in': 10
        }
        with patch('resources.lib.ui.client.post', return_value=mock_code_resp), \
             patch.object(prem, 'auth_loop', return_value=True), \
             patch.object(prem, 'status'):
            prem.auth()
            self.assertTrue(control.getBool('premiumize.enabled'))

    # =========================================================================
    # 8. AllDebrid Auth Tests
    # =========================================================================
    def test_alldebrid_auth_cancellation_and_qr_fallback(self):
        ad = AllDebrid()
        mock_code_resp = MagicMock(ok=True)
        mock_code_resp.json.return_value = {
            'data': {
                'pin': '1234',
                'check': 'chk123',
                'user_url': 'https://alldebrid.com/pin',
                'base_url': 'https://alldebrid.com/pin',
                'expires_in': 10,
                'check_step': 1
            }
        }
        with patch('resources.lib.ui.client.get', return_value=mock_code_resp), \
             patch('pyqrcode.create', side_effect=Exception("QR error")), \
             patch('resources.lib.windows.progress_dialog.Progress_dialog.iscanceled', return_value=True), \
             patch('resources.lib.windows.progress_dialog.Progress_dialog.close') as mock_close:
            ad.auth()
            mock_close.assert_called()
            self.assertFalse(control.getBool('alldebrid.enabled'))

    def test_alldebrid_auth_success(self):
        ad = AllDebrid()
        mock_code_resp = MagicMock(ok=True)
        mock_code_resp.json.return_value = {
            'data': {
                'pin': '1234',
                'check': 'chk123',
                'user_url': 'https://alldebrid.com/pin',
                'expires_in': 10,
                'check_step': 1
            }
        }
        with patch('resources.lib.ui.client.get', return_value=mock_code_resp), \
             patch.object(ad, 'auth_loop', return_value=True), \
             patch.object(ad, 'status'):
            ad.auth()
            self.assertTrue(control.getBool('alldebrid.enabled'))

    # =========================================================================
    # 9. Debrid-Link Auth Tests
    # =========================================================================
    def test_debridlink_auth_success_and_dialog_close(self):
        dl = DebridLink()
        mock_code_resp = MagicMock(ok=True)
        mock_code_resp.json.return_value = {
            'device_code': 'dldev',
            'user_code': 'dlusr',
            'interval': 1,
            'expires_in': 10,
            'verification_url': 'https://debrid-link.com/device'
        }
        with patch('resources.lib.ui.client.post', return_value=mock_code_resp), \
             patch.object(dl, 'auth_loop', return_value=True), \
             patch.object(dl, 'status'), \
             patch('resources.lib.windows.progress_dialog.Progress_dialog.close') as mock_close:
            dl.auth()
            mock_close.assert_called()
            self.assertTrue(control.getBool('debridlink.enabled'))

    # =========================================================================
    # 10. TorBox Auth Tests
    # =========================================================================
    def test_torbox_auth_success(self):
        tb = TorBox()
        mock_code_resp = MagicMock(ok=True)
        mock_code_resp.json.return_value = {
            'data': {
                'device_code': 'tbdev',
                'code': 'tbusr',
                'interval': 1,
                'expires_at': '2030-01-01T00:00:00Z'
            }
        }
        with patch('resources.lib.ui.client.get', return_value=mock_code_resp), \
             patch.object(tb, 'auth_loop', return_value=True), \
             patch.object(tb, 'status'):
            tb.auth()
            self.assertTrue(control.getBool('torbox.enabled'))

    # =========================================================================
    # 11. EasyDebrid Auth Tests
    # =========================================================================
    def test_easydebrid_auth_cancel_and_success(self):
        ed = EasyDebrid()
        # Test cancel input dialog
        with patch('resources.lib.ui.control.input_dialog', return_value=""):
            ed.auth()
            self.assertFalse(control.getBool('easydebrid.enabled'))

        # Test valid input
        with patch('resources.lib.ui.control.input_dialog', return_value="valid_ed_key"), \
             patch.object(ed, 'status', return_value=True):
            ed.auth()
            self.assertEqual(control.getSetting('easydebrid.token'), 'valid_ed_key')
            self.assertTrue(control.getBool('easydebrid.enabled'))

    # =========================================================================
    # 12. Easynews Auth Tests
    # =========================================================================
    def test_easynews_auth_success(self):
        en = Easynews()
        control.setSetting('easynews.user', 'test_user')
        control.setSetting('easynews.password', 'test_pass')
        with patch.object(en, 'verify_login', return_value=True):
            en.auth()
            self.assertTrue(control.getBool('easynews.enabled'))


if __name__ == '__main__':
    unittest.main()
