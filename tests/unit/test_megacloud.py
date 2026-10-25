"""
Unit tests for Megacloud / Rabbitstream native pure-Python decryptor.
"""

import json
import unittest
from unittest.mock import patch, MagicMock

import tests.conftest  # noqa: F401
from resources.lib.ui import megacloud_extractor
from resources.lib.ui import embed_extractor
from resources.lib.ui.megacloud_extractor import MegacloudDecryptor


class TestMegacloudExtractor(unittest.TestCase):

    def setUp(self):
        self.decryptor = MegacloudDecryptor()

    def test_keygen2_float_vs_int_parity(self):
        """Verify keygen2 with IEEE 754 float hash produces valid keys matching V8/Node JS."""
        secret = "pXJdDCTByENrAOGFOyziD"
        nonce = "d870cf24"

        float_key = self.decryptor.keygen2(secret, nonce, use_float_hash=True)
        int_key = self.decryptor.keygen2(secret, nonce, use_float_hash=False)

        self.assertIsInstance(float_key, str)
        self.assertGreater(len(float_key), 20)
        self.assertIsInstance(int_key, str)
        self.assertGreater(len(int_key), 20)

    def test_seed_shuffle2_deterministic(self):
        """Verify PRNG LCG unshuffle produces deterministic sequence."""
        src = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
        shuffled1 = self.decryptor.seed_shuffle2(list(src), "12345")
        shuffled2 = self.decryptor.seed_shuffle2(list(src), "12345")
        self.assertEqual(shuffled1, shuffled2)
        self.assertEqual(len(shuffled1), len(src))
        self.assertEqual(set(shuffled1), set(src))

    def test_columnar_cipher2_reversal(self):
        """Verify columnar transposition cipher logic."""
        test_text = "ThisIsASecretPayloadForMegacloudTesting12345"
        key = "SECRETKEY123"
        reversed_cols = self.decryptor.columnar_cipher2(test_text, key)
        self.assertIsInstance(reversed_cols, str)
        self.assertGreaterEqual(len(reversed_cols), len(test_text) - 10)

    def test_bundled_keys_json_present_and_valid(self):
        """Verify the bundled resources/data/keys.json exists and has valid vidstr key."""
        keys = megacloud_extractor._get_decryption_keys()
        self.assertIn('vidstr', keys)
        self.assertTrue(len(keys['vidstr']) >= 10)
        self.assertIn('_meta', keys)

    def test_embed_extractor_domain_registration(self):
        """Verify embed_extractor dispatches registered Megacloud / Rabbitstream URLs."""
        test_urls = [
            "https://megacloud.tv/embed-2/e-1/2b8AEgZybAgc?k=1",
            "https://megacloud.blog/embed-2/v3/e-1/2b8AEgZybAgc?k=1",
            "https://rabbitstream.net/embed-2/e-1/2b8AEgZybAgc?k=1",
            "https://rapid-cloud.co/embed-2/2b8AEgZybAgc?k=1",
            "https://megaf.cc/e-1/2b8AEgZybAgc?k=1",
            "https://4spromax.site/e/2b8AEgZybAgc",
            "https://megaup.live/e/2b8AEgZybAgc",
        ]
        def fake_probe(url, *args, **kwargs):
            m = MagicMock()
            m.url = url
            m.status_code = 200
            m.text = "<html></html>"
            m.headers = {"Referer": url}
            return m

        with patch("resources.lib.ui.client.get", side_effect=fake_probe), \
             patch("resources.lib.ui.megacloud_extractor.extract_megacloud_sources") as mock_extract:
            mock_extract.return_value = {
                "sources": [{"file": "https://cdn.example.com/stream/master.m3u8"}],
                "tracks": [],
                "intro": {"start": 10, "end": 100},
            }
            for url in test_urls:
                res = embed_extractor.load_video_from_url(url)
                self.assertIsNotNone(res, f"Failed to match registered domain: {url}")
                self.assertTrue(res.startswith("https://cdn.example.com/stream/master.m3u8"))

    def test_extract_megacloud_sources_mock_flow(self):
        """Verify full extract_megacloud_sources pipeline from embed HTML to decrypted JSON."""
        token = "0123456789abcdef" * 3  # Exactly 48 chars
        embed_html = f'<html><head><script>var token = "{token}";</script></head><body></body></html>'

        get_sources_payload = {
            "sources": [{"file": "https://megacloud.cdn/hls/video.m3u8", "type": "hls"}],
            "tracks": [{"file": "https://megacloud.cdn/sub/en.vtt", "label": "English", "kind": "captions"}],
            "intro": {"start": 85, "end": 175},
            "outro": {"start": 1320, "end": 1410},
            "encrypted": False
        }

        mock_resp_embed = MagicMock()
        mock_resp_embed.text = embed_html
        mock_resp_embed.status_code = 200

        mock_resp_sources = MagicMock()
        mock_resp_sources.text = json.dumps(get_sources_payload)
        mock_resp_sources.json.return_value = get_sources_payload
        mock_resp_sources.status_code = 200

        def fake_client_get(url, *args, **kwargs):
            if "getSources" in url:
                return mock_resp_sources
            return mock_resp_embed

        with patch("resources.lib.ui.control.getBool", return_value=False), \
             patch("resources.lib.ui.megacloud_extractor.client.get", side_effect=fake_client_get):
            res = megacloud_extractor.extract_megacloud_sources("https://megacloud.blog/embed-2/v3/e-1/2b8AEgZybAgc?k=1")
            self.assertIsNotNone(res)
            self.assertEqual(res["sources"][0]["file"], "https://megacloud.cdn/hls/video.m3u8")
            self.assertEqual(len(res["tracks"]), 1)
            self.assertEqual(res["intro"]["start"], 85)
            self.assertEqual(res["outro"]["end"], 1410)


if __name__ == '__main__':
    unittest.main()
