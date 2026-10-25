import unittest
from unittest.mock import patch, MagicMock
import re

import tests.conftest  # noqa: F401
from resources.lib.ui import source_utils, control, embed_extractor
from resources.lib.pages import circuit_breaker
from resources.lib.windows import base_window
from resources.lib.debrid.real_debrid import RealDebrid
from resources.lib.debrid.torbox import TorBox


class TestPerformanceAndCircuitBreaker(unittest.TestCase):

    def setUp(self):
        circuit_breaker.reset()
        base_window.clear_artwork_cache()

    def tearDown(self):
        circuit_breaker.reset()
        base_window.clear_artwork_cache()

    def test_circuit_breaker_tripping_and_cooldown(self):
        provider = 'test_scraper'
        self.assertFalse(circuit_breaker.is_tripped(provider))

        # Record 2 failures - not tripped yet
        circuit_breaker.record_failure(provider)
        circuit_breaker.record_failure(provider)
        self.assertFalse(circuit_breaker.is_tripped(provider))

        # 3rd failure trips the circuit
        circuit_breaker.record_failure(provider)
        self.assertTrue(circuit_breaker.is_tripped(provider))

        # Resetting restores the circuit
        circuit_breaker.reset(provider)
        self.assertFalse(circuit_breaker.is_tripped(provider))

        # Success clears any failure count
        circuit_breaker.record_failure(provider)
        circuit_breaker.record_success(provider)
        circuit_breaker.record_failure(provider)
        self.assertFalse(circuit_breaker.is_tripped(provider))

    def test_source_utils_module_level_regexes(self):
        self.assertIsInstance(source_utils._RE_FILTER_SEASON, re.Pattern)
        self.assertIsInstance(source_utils._RE_FILTER_EPISODE, re.Pattern)
        self.assertIsInstance(source_utils._RE_FILTER_EPISODE_RANGE, re.Pattern)
        self.assertIsInstance(source_utils._RE_FILTER_PART, re.Pattern)
        self.assertIsInstance(source_utils._RE_FILTER_TRAILING_NUMBER, re.Pattern)
        self.assertIsInstance(source_utils._RE_FILTER_ORDINAL_CHECK, re.Pattern)

    def test_base_window_artwork_cache_purged_by_clean_memory(self):
        base_window._artwork_cache['thumb_9999'] = 'https://image.tmdb.org/t/p/w500/test.jpg'
        base_window._artwork_cache['fanart_9999'] = 'https://image.tmdb.org/t/p/original/test.jpg'
        self.assertEqual(len(base_window._artwork_cache), 2)

        # clean_memory must purge base_window._artwork_cache
        control.clean_memory()
        self.assertEqual(len(base_window._artwork_cache), 0)

    def test_sub_ext_detection_ass_and_vtt(self):
        ass_content = "[Script Info]\nTitle: English Anime Subtitle\nScriptType: v4.00+\n[Events]\nFormat: Layer, Start, End"
        self.assertEqual(embed_extractor._detect_sub_ext("https://embed.co/sub.txt", ass_content), ".ass")
        self.assertEqual(embed_extractor._detect_sub_ext("https://embed.co/sub.ass", ""), ".ass")
        self.assertEqual(embed_extractor._detect_sub_ext("https://embed.co/sub.ssa", ""), ".ssa")

        vtt_content = "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nHello"
        self.assertEqual(embed_extractor._detect_sub_ext("https://embed.co/sub.txt", vtt_content), ".vtt")
        self.assertEqual(embed_extractor._detect_sub_ext("https://embed.co/sub.vtt", ""), ".vtt")

        srt_content = "1\n00:00:01,000 --> 00:00:04,000\nHello\n"
        self.assertEqual(embed_extractor._detect_sub_ext("https://embed.co/sub.srt", srt_content), ".srt")

    def test_real_debrid_429_backoff_retry(self):
        rd = RealDebrid()
        mock_429 = MagicMock(status_code=429, ok=False, headers={'Retry-After': '1'})
        mock_200 = MagicMock(status_code=200, ok=True, json=lambda: {'id': 'RD_TORRENT_123'})

        with patch('resources.lib.ui.client.post', side_effect=[mock_429, mock_200]), \
             patch('time.sleep') as mock_sleep:
            res = rd.addMagnet("magnet:?xt=urn:btih:ABCDEF123456")
            self.assertEqual(res, {'id': 'RD_TORRENT_123'})
            mock_sleep.assert_called_once_with(1)

    def test_torbox_429_backoff_retry(self):
        tb = TorBox()
        mock_429 = MagicMock(status_code=429, ok=False, headers={'Retry-After': '1'})
        mock_200 = MagicMock(status_code=200, ok=True, json=lambda: {'data': {'torrent_id': 'TB_999'}})

        with patch('resources.lib.ui.client.post', side_effect=[mock_429, mock_200]), \
             patch('time.sleep') as mock_sleep:
            res = tb.addMagnet("magnet:?xt=urn:btih:ABCDEF123456")
            self.assertEqual(res, {'torrent_id': 'TB_999'})
            mock_sleep.assert_called_once_with(1)


if __name__ == '__main__':
    unittest.main()
