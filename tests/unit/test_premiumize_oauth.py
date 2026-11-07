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


class TestPremiumizeOAuth(unittest.TestCase):
    def setUp(self):
        # Clear mock settings before each test
        from resources.lib.ui import control
        control.setSetting('premiumize.token', '')
        control.setSetting('premiumize.username', '')
        control.setSetting('premiumize.auth.status', '')

    @patch('resources.lib.ui.control.lang', side_effect=lambda x: f"String_{x} {{}}" if x in (30081, 30082) else f"String_{x}")
    @patch('resources.lib.ui.control.copy2clip', return_value=True)
    @patch('resources.lib.windows.progress_dialog.Progress_dialog')
    @patch('resources.lib.ui.client.post')
    def test_premiumize_auth_device_code_flow_populates_window(self, mock_post, mock_dialog_cls, mock_clip, mock_lang):
        from resources.lib.debrid.premiumize import Premiumize

        # Mock Step 1 device code response
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'verification_uri': 'https://www.premiumize.me/device',
            'user_code': 'abcd-1234',
            'device_code': 'dev_code_xyz',
            'expires_in': 60,
            'interval': 5
        }
        mock_post.return_value = mock_resp

        mock_dialog_inst = MagicMock()
        mock_dialog_inst.iscanceled.return_value = True  # Cancel after first loop to exit
        mock_dialog_cls.return_value = mock_dialog_inst

        pm = Premiumize()
        pm.auth()

        # Verify Progress_dialog was initialized and shown
        mock_dialog_cls.assert_called_once()
        call_kwargs = mock_dialog_cls.call_args[1]
        self.assertIn('config', call_kwargs)
        config = call_kwargs['config']
        self.assertIn('https://www.premiumize.me/device', config['text'])
        self.assertIn('abcd-1234', config['text'])
        mock_dialog_inst.show.assert_called_once()

    @patch('resources.lib.windows.progress_dialog.Progress_dialog')
    @patch('resources.lib.ui.client.post')
    def test_premiumize_auth_pyqrcode_import_error_graceful_fallback(self, mock_post, mock_dialog_cls):
        """Verify window populates even if pyqrcode is not available or fails."""
        from resources.lib.debrid.premiumize import Premiumize

        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'verification_uri': 'https://www.premiumize.me/device',
            'user_code': 'abcd-1234',
            'device_code': 'dev_code_xyz',
            'expires_in': 60,
            'interval': 5
        }
        mock_post.return_value = mock_resp

        mock_dialog_inst = MagicMock()
        mock_dialog_inst.iscanceled.return_value = True
        mock_dialog_cls.return_value = mock_dialog_inst

        with patch.dict('sys.modules', {'pyqrcode': None}):
            pm = Premiumize()
            pm.auth()

        # Dialog must still be instantiated and shown
        mock_dialog_cls.assert_called_once()
        mock_dialog_inst.show.assert_called_once()
        config = mock_dialog_cls.call_args[1]['config']
        self.assertEqual(config['qr_code'], '')

    @patch('resources.lib.ui.control.ok_dialog')
    @patch('resources.lib.ui.client.post')
    def test_premiumize_auth_network_failure_dialog(self, mock_post, mock_ok_dialog):
        from resources.lib.debrid.premiumize import Premiumize

        mock_post.return_value = None
        pm = Premiumize()
        pm.auth()
        mock_ok_dialog.assert_called_once()

    @patch('resources.lib.ui.client.post')
    def test_premiumize_auth_loop_400_authorization_pending(self, mock_post):
        from resources.lib.debrid.premiumize import Premiumize

        pm = Premiumize()
        pm.dialog = MagicMock()
        pm.dialog.iscanceled.return_value = False
        pm.OauthTimeout = 300
        pm.OauthTimeStep = 5

        # HTTP 400 with authorization_pending (bool(r) == False in client.Response)
        mock_400 = MagicMock()
        mock_400.ok = False
        mock_400.status_code = 400
        mock_400.__bool__.return_value = False
        mock_400.json.return_value = {'error': 'authorization_pending', 'error_description': 'pending'}
        mock_post.return_value = mock_400

        result = pm.auth_loop('dev_code_xyz')
        self.assertFalse(result)
        self.assertEqual(pm.OauthTimeout, 300)

    @patch('resources.lib.ui.control.monitor.waitForAbort')
    @patch('resources.lib.ui.client.post')
    def test_premiumize_auth_loop_400_slow_down(self, mock_post, mock_wait):
        from resources.lib.debrid.premiumize import Premiumize

        pm = Premiumize()
        pm.dialog = MagicMock()
        pm.dialog.iscanceled.return_value = False
        pm.OauthTimeout = 300
        pm.OauthTimeStep = 5

        mock_400 = MagicMock()
        mock_400.ok = False
        mock_400.status_code = 400
        mock_400.__bool__.return_value = False
        mock_400.json.return_value = {'error': 'slow_down', 'error_description': 'slow down'}
        mock_post.return_value = mock_400

        result = pm.auth_loop('dev_code_xyz')
        self.assertFalse(result)
        self.assertEqual(pm.OauthTimeStep, 10)  # incremented by 5
        mock_wait.assert_called_with(5)

    @patch('resources.lib.ui.client.post')
    def test_premiumize_auth_loop_400_access_denied(self, mock_post):
        from resources.lib.debrid.premiumize import Premiumize

        pm = Premiumize()
        pm.dialog = MagicMock()
        pm.dialog.iscanceled.return_value = False
        pm.OauthTimeout = 300

        mock_400 = MagicMock()
        mock_400.ok = False
        mock_400.status_code = 400
        mock_400.__bool__.return_value = False
        mock_400.json.return_value = {'error': 'access_denied'}
        mock_post.return_value = mock_400

        result = pm.auth_loop('dev_code_xyz')
        self.assertFalse(result)
        self.assertEqual(pm.OauthTimeout, 0)

    @patch('resources.lib.ui.control.setSetting')
    @patch('resources.lib.ui.client.post')
    def test_premiumize_auth_loop_success_sets_token(self, mock_post, mock_set_setting):
        from resources.lib.debrid.premiumize import Premiumize

        pm = Premiumize()
        pm.dialog = MagicMock()
        pm.dialog.iscanceled.return_value = False

        mock_200 = MagicMock()
        mock_200.ok = True
        mock_200.status_code = 200
        mock_200.json.return_value = {
            'access_token': 'pm_token_secret_123',
            'token_type': 'Bearer',
            'expires_in': 3600,
            'scope': 'full'
        }
        mock_post.return_value = mock_200

        result = pm.auth_loop('dev_code_xyz')
        self.assertTrue(result)
        self.assertEqual(pm.token, 'pm_token_secret_123')
        mock_set_setting.assert_called_with('premiumize.token', 'pm_token_secret_123')

    @patch('resources.lib.ui.control.setSetting')
    @patch('resources.lib.ui.control.ok_dialog')
    @patch('resources.lib.ui.client.get')
    def test_premiumize_status_null_premium_until(self, mock_get, mock_ok_dialog, mock_set_setting):
        from resources.lib.debrid.premiumize import Premiumize

        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'customer_id': '123456',
            'premium_until': None
        }
        mock_get.return_value = mock_resp

        pm = Premiumize()
        pm.status()

        mock_set_setting.assert_any_call('premiumize.username', '123456')
        mock_set_setting.assert_any_call('premiumize.auth.status', 'Expired')


if __name__ == '__main__':
    unittest.main()