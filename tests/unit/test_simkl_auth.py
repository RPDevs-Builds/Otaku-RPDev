"""
test_simkl_auth.py - Unit Tests for Simkl Watchlist Authentication and Client ID Fallbacks
========================================================================================
Validates Simkl OAuth PIN authorization, QR code generation resilience,
cancellation handling, username extraction, settings persistence, and built-in API fallbacks.
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

from resources.lib.ui import database, control
from resources.lib.WatchlistFlavor import WatchlistFlavor
from resources.lib.WatchlistFlavor.Simkl import SimklWLF
from resources.lib.indexers.simkl import SIMKLAPI


class TestSimklAuth(unittest.TestCase):

    def setUp(self):
        control.setSetting('simkl.token', '')
        control.setSetting('simkl.username', '')
        control.setBool('simkl.enabled', False)

    def test_simkl_client_id_property_and_fallback(self):
        simkl = SimklWLF()
        self.assertTrue(bool(simkl.client_id))
        self.assertEqual(simkl.client_id, '59dfdc579d244e1edf6f89874d521d37a69a95a1abd349910cb056a1872ba2c8')

        # Test indexers SIMKLAPI fallback
        api = SIMKLAPI()
        self.assertEqual(api.ClientID, '59dfdc579d244e1edf6f89874d521d37a69a95a1abd349910cb056a1872ba2c8')

    def test_database_get_info_builtin_fallback(self):
        with patch('os.path.exists', return_value=False):
            info = database.get_info('Simkl')
            self.assertEqual(info.get('client_id'), '59dfdc579d244e1edf6f89874d521d37a69a95a1abd349910cb056a1872ba2c8')
            self.assertEqual(info.get('api_name'), 'Simkl')

    def test_simkl_headers(self):
        simkl = SimklWLF(token='simkl_test_access_token')
        headers = simkl._SimklWLF__headers()
        self.assertEqual(headers.get('Content-Type'), 'application/json')
        self.assertEqual(headers.get('Authorization'), 'Bearer simkl_test_access_token')
        self.assertEqual(headers.get('simkl-api-key'), '59dfdc579d244e1edf6f89874d521d37a69a95a1abd349910cb056a1872ba2c8')

    @patch('resources.lib.WatchlistFlavor.Simkl.client.post')
    @patch('resources.lib.WatchlistFlavor.Simkl.client.get')
    @patch('resources.lib.windows.progress_dialog.Progress_dialog')
    @patch('resources.lib.ui.control.copy2clip')
    @patch('resources.lib.ui.control.sleep')
    def test_simkl_login_success(self, mock_sleep, mock_copy, mock_dialog_cls, mock_get, mock_post):
        mock_dialog = MagicMock()
        mock_dialog.iscanceled.return_value = False
        mock_dialog_cls.return_value = mock_dialog

        # 1st GET: /oauth/pin
        resp_pin = MagicMock()
        resp_pin.json.return_value = {
            'result': 'OK',
            'user_code': 'SIM12',
            'device_code': 'dev_code_abc',
            'verification_url': 'https://simkl.com/pin',
            'interval': 1,
            'expires_in': 10
        }
        resp_pin.__bool__.return_value = True

        # 2nd GET: /oauth/pin/SIM12 (polling)
        resp_poll = MagicMock()
        resp_poll.json.return_value = {
            'result': 'OK',
            'access_token': 'simkl_oauth_secret_token_123'
        }
        resp_poll.__bool__.return_value = True

        mock_get.side_effect = [resp_pin, resp_poll]

        # POST: /users/settings
        resp_settings = MagicMock()
        resp_settings.json.return_value = {
            'user': {'name': 'SimklAnimeFan'}
        }
        resp_settings.__bool__.return_value = True
        mock_post.return_value = resp_settings

        simkl = SimklWLF()
        res = simkl.login()

        self.assertIsNotNone(res)
        self.assertEqual(res.get('token'), 'simkl_oauth_secret_token_123')
        self.assertEqual(res.get('username'), 'SimklAnimeFan')
        mock_copy.assert_called_once_with('SIM12')
        mock_dialog.show.assert_called_once()
        mock_dialog.close.assert_called()

    @patch('resources.lib.WatchlistFlavor.Simkl.client.get')
    @patch('resources.lib.ui.control.notify')
    def test_simkl_login_pin_connection_failure(self, mock_notify, mock_get):
        # When /oauth/pin fails
        mock_get.return_value = None

        simkl = SimklWLF()
        res = simkl.login()

        self.assertIsNone(res)
        mock_notify.assert_called_once()

    @patch('resources.lib.WatchlistFlavor.Simkl.client.post')
    @patch('resources.lib.WatchlistFlavor.Simkl.client.get')
    @patch('resources.lib.windows.progress_dialog.Progress_dialog')
    @patch('resources.lib.ui.control.sleep')
    def test_simkl_login_qr_code_graceful_fallback(self, mock_sleep, mock_dialog_cls, mock_get, mock_post):
        mock_dialog = MagicMock()
        mock_dialog.iscanceled.return_value = False
        mock_dialog_cls.return_value = mock_dialog

        resp_pin = MagicMock()
        resp_pin.json.return_value = {
            'result': 'OK',
            'user_code': 'QRFAIL',
            'interval': 1,
            'expires_in': 5
        }
        resp_pin.__bool__.return_value = True

        resp_poll = MagicMock()
        resp_poll.json.return_value = {
            'result': 'OK',
            'access_token': 'simkl_token_no_qr'
        }
        resp_poll.__bool__.return_value = True
        mock_get.side_effect = [resp_pin, resp_poll]

        mock_post.return_value = None

        with patch('pyqrcode.create', side_effect=Exception('Missing libpng')):
            simkl = SimklWLF()
            res = simkl.login()

            self.assertIsNotNone(res)
            self.assertEqual(res.get('token'), 'simkl_token_no_qr')

    @patch('resources.lib.WatchlistFlavor.Simkl.client.get')
    @patch('resources.lib.windows.progress_dialog.Progress_dialog')
    @patch('resources.lib.ui.control.sleep')
    def test_simkl_login_dialog_canceled(self, mock_sleep, mock_dialog_cls, mock_get):
        mock_dialog = MagicMock()
        mock_dialog.iscanceled.return_value = True
        mock_dialog_cls.return_value = mock_dialog

        resp_pin = MagicMock()
        resp_pin.json.return_value = {
            'result': 'OK',
            'user_code': 'CANCEL1',
            'interval': 1,
            'expires_in': 10
        }
        resp_pin.__bool__.return_value = True
        mock_get.return_value = resp_pin

        simkl = SimklWLF()
        res = simkl.login()

        self.assertIsNone(res)
        mock_dialog.close.assert_called()

    @patch('resources.lib.WatchlistFlavor.Simkl.SimklWLF.login')
    @patch('resources.lib.ui.control.ok_dialog')
    def test_watchlist_flavor_login_and_logout_request(self, mock_ok_dialog, mock_simkl_login):
        # 1. Successful login
        mock_simkl_login.return_value = {
            'token': 'tok_xyz_123',
            'username': 'OtakuSimklUser'
        }
        WatchlistFlavor.login_request('simkl')

        self.assertEqual(control.getSetting('simkl.token'), 'tok_xyz_123')
        self.assertEqual(control.getSetting('simkl.username'), 'OtakuSimklUser')
        self.assertTrue(control.getBool('simkl.enabled'))
        self.assertTrue(control.getBool('watchlist.update.enabled'))
        mock_ok_dialog.assert_called_with('Login', 'Success')

        # 2. Logout
        WatchlistFlavor.logout_request('simkl')
        self.assertEqual(control.getSetting('simkl.token'), '')
        self.assertEqual(control.getSetting('simkl.username'), '')
        self.assertFalse(control.getBool('simkl.enabled'))

        # 3. Canceled login (returns None)
        mock_simkl_login.return_value = None
        mock_ok_dialog.reset_mock()
        res = WatchlistFlavor.login_request('simkl')
        self.assertIsNone(res)
        mock_ok_dialog.assert_not_called()


if __name__ == '__main__':
    unittest.main()