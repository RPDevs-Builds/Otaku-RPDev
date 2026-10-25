"""
Unit tests for Log Token Sanitization (P2) and Memory Management & Concurrency Bounding (P3).
"""

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import tests.conftest  # noqa: F401
from resources.lib.ui import control
from resources.lib.pages import Sources


class TestSecurityAndMemory(unittest.TestCase):

    def setUp(self):
        tests.conftest.mock_xbmc.log.reset_mock()

    def test_log_sanitization_bearer(self):
        """Verify Bearer tokens are redacted in log messages."""
        msg = "Sending request with Authorization: Bearer abc123456789_xyz-token"
        sanitized = control.sanitize_log(msg)
        self.assertNotIn("abc123456789_xyz-token", sanitized)
        self.assertIn("Authorization: Bearer [REDACTED]", sanitized)

    def test_log_sanitization_url_params(self):
        """Verify API keys and tokens in URL query strings are redacted."""
        url1 = "https://api.real-debrid.com/rest/1.0/user?auth_token=SECRET_RD_TOKEN_999&limit=10"
        sanitized1 = control.sanitize_log(url1)
        self.assertNotIn("SECRET_RD_TOKEN_999", sanitized1)
        self.assertIn("auth_token=[REDACTED]", sanitized1)
        self.assertIn("&limit=10", sanitized1)

        url2 = "https://api.example.com/data?api_key=KEY_123456&other=value"
        sanitized2 = control.sanitize_log(url2)
        self.assertNotIn("KEY_123456", sanitized2)
        self.assertIn("api_key=[REDACTED]", sanitized2)

    def test_log_sanitization_json_fields(self):
        """Verify sensitive JSON and dictionary keys are redacted."""
        json_msg = '{"access_token": "ACCESS_SECRET_777", "refresh_token": "REFRESH_SECRET_888", "expires_in": 3600}'
        sanitized = control.sanitize_log(json_msg)
        self.assertNotIn("ACCESS_SECRET_777", sanitized)
        self.assertNotIn("REFRESH_SECRET_888", sanitized)
        self.assertIn('"access_token": "[REDACTED]"', sanitized)
        self.assertIn('"refresh_token": "[REDACTED]"', sanitized)
        self.assertIn('"expires_in": 3600', sanitized)

    def test_log_sanitization_basic_auth(self):
        """Verify Basic Auth credentials in URLs are redacted."""
        url = "https://myuser:superpassword123@myhost.com/dav/files"
        sanitized = control.sanitize_log(url)
        self.assertNotIn("superpassword123", sanitized)
        self.assertIn("https://myuser:[REDACTED]@myhost.com/dav/files", sanitized)

    def test_log_sanitization_active_setting_tokens(self):
        """Verify tokens configured in user settings are redacted even without standard prefix."""
        with patch.object(control, 'getSetting', side_effect=lambda k: 'CUSTOM_USER_RD_TOKEN_XYZ' if k == 'realdebrid.token' else ''):
            msg = "Processing user hash against CUSTOM_USER_RD_TOKEN_XYZ in cache"
            sanitized = control.sanitize_log(msg)
            self.assertNotIn("CUSTOM_USER_RD_TOKEN_XYZ", sanitized)
            self.assertIn("[REDACTED]", sanitized)

    def test_control_log_integration(self):
        """Verify control.log() calls xbmc.log with sanitized output."""
        control.log("Querying https://api.simkl.com/sync?client_secret=SIMKL_SECRET_XYZ", level="info")
        tests.conftest.mock_xbmc.log.assert_called_once()
        logged_str = tests.conftest.mock_xbmc.log.call_args[0][0]
        self.assertNotIn("SIMKL_SECRET_XYZ", logged_str)
        self.assertIn("client_secret=[REDACTED]", logged_str)

    def test_clean_memory_execution_and_artwork_cache(self):
        """Verify clean_memory() executes without errors and bounds _artwork_cache."""
        for i in range(250):
            control._artwork_cache[f'item_{i}'] = f'thumb_{i}.jpg'
        self.assertEqual(len(control._artwork_cache), 250)

        control.clean_memory()
        self.assertEqual(len(control._artwork_cache), 0)

    def test_detect_max_threads_bounds(self):
        """Verify _detect_max_threads() returns a valid bound between 2 and 8."""
        threads = control._detect_max_threads()
        self.assertIsInstance(threads, int)
        self.assertGreaterEqual(threads, 2)
        self.assertLessEqual(threads, 8)
        self.assertEqual(control.max_threads, threads)

    def test_scraper_concurrency_semaphore(self):
        """Verify Sources._scrape_semaphore limits concurrent execution."""
        self.assertTrue(hasattr(Sources, '_scrape_semaphore'))
        self.assertEqual(Sources._scrape_semaphore._value, control.max_threads)

        active_workers = 0
        max_seen_active = 0
        lock = threading.Lock()

        def dummy_worker():
            nonlocal active_workers, max_seen_active
            with lock:
                active_workers += 1
                if active_workers > max_seen_active:
                    max_seen_active = active_workers
            time.sleep(0.02)
            with lock:
                active_workers -= 1

        threads = []
        for _ in range(16):
            t = Sources._start_worker(dummy_worker)
            threads.append(t)

        for t in threads:
            t.join()

        self.assertLessEqual(max_seen_active, control.max_threads)
        self.assertEqual(active_workers, 0)


if __name__ == '__main__':
    unittest.main()
