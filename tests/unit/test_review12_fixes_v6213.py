import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'plugin.video.otaku.rpdev'))

from resources.lib.pages import animetosho, nyaa
from resources.lib.ui import control, embed_extractor


class TestReview12And13FixesV6213(unittest.TestCase):
    """Regression tests for ONN Review #12 & #13 findings (C-24, C-25, C-11, C-26)."""

    def test_c24_animetosho_alt_failure_falls_back_to_direct_and_sticky_switches(self):
        """C-24: When animetosho-net.translate.goog fails (403/no #content), AnimeTosho falls back to animetosho.net and switches active host."""
        valid_html = (
            '<div id="content"><div class="home_list_entry">'
            '<div class="link"><a href="/view/1">[Judas] Wistoria - S02E06 [1080p][Dual-Audio]</a></div>'
            '<a href="magnet:?xt=urn:btih:' + ('a' * 40) + '">Magnet</a>'
            '<div class="size">500 MiB</div>'
            '<span title="Seeders: 42">42</span>'
            '</div></div>'
        )
        called_urls = []

        def _fake_get(url, params=None, **kw):
            called_urls.append(url)
            if 'translate.goog' in url:
                return MagicMock(status_code=403, text='<html><body>Blocked</body></html>')
            return MagicMock(status_code=200, text=valid_html)

        with patch('resources.lib.ui.domains.get_domain', return_value='https://animetosho-net.translate.goog/?_x_tr_sl=es&_x_tr_tl=en&_x_tr_hl=en'):
            scraper = animetosho.Sources()

        with patch('resources.lib.ui.client.get', side_effect=_fake_get):
            content_div = scraper._fetch_search_content({'q': 'Wistoria', 'qx': 1})
            self.assertIsNotNone(content_div)
            self.assertEqual(scraper._active_base_url, 'https://animetosho.net/')
            # Subsequent call goes straight to animetosho.net without hitting translate.goog again
            content_div2 = scraper._fetch_search_content({'aids': 18889})
            self.assertIsNotNone(content_div2)

        self.assertEqual(len(called_urls), 3)
        self.assertIn('translate.goog', called_urls[0])
        self.assertIn('animetosho.net', called_urls[1])
        self.assertIn('animetosho.net', called_urls[2])

    def test_c24_c25_animetosho_removes_duplicate_fallback_task_and_batches_debrid(self):
        """C-24/C-25: AnimeTosho drops duplicate params3, includes show_pack in parallel pool, and runs one batched Debrid check."""
        captured_tasks = []

        def _fake_parallel(items, fn):
            if items and isinstance(items[0], dict) and 'params' in items[0]:
                captured_tasks.extend(items)
                return [[{'name': '[Judas] Wistoria - S02E06', 'hash': 'b' * 40, 'downloads': 10, 'seeders': 5, 'size': '500 MB', 'magnet': 'magnet:?xt=urn:btih:' + 'b' * 40, '_is_show_pack': bool(t.get('is_show_pack'))}] for t in items]
            return [fn(x) for x in items]

        with patch('resources.lib.ui.domains.get_domain', return_value='https://animetosho.net/'):
            scraper = animetosho.Sources()

        with patch('resources.lib.ui.database.get_show_meta', return_value=None), \
             patch('resources.lib.ui.database.get_mappings', return_value={'anidb_id': 18889}), \
             patch('resources.lib.ui.utils.parallel_process', side_effect=_fake_parallel), \
             patch('resources.lib.pages.animetosho.Debrid') as mock_debrid, \
             patch.object(control, 'getBool', return_value=False):
            mock_debrid.return_value.torrentCacheCheck.side_effect = lambda fl, **kw: (fl, [])
            res = scraper.get_sources(
                '(Tsue to Tsurugi no Wistoria Season 2)|(Wistoria: Wand and Sword Season 2)',
                59983, 6, 'RELEASING', 'tv', season=2,
            )

        task_names = [t['name'] for t in captured_tasks]
        self.assertNotIn('fallback', task_names)
        self.assertIn('primary', task_names)
        self.assertIn('anidb_id', task_names)
        self.assertIn('show_pack', task_names)
        # Single batched Debrid check with deduplicated hash
        mock_debrid.return_value.torrentCacheCheck.assert_called_once()
        checked_batch = mock_debrid.return_value.torrentCacheCheck.call_args.args[0]
        self.assertEqual(len(checked_batch), 1)
        self.assertEqual(len(res['cached']), 1)

    def test_c24_nyaa_primary_failure_falls_back_to_alt_host(self):
        """C-24: When nyaa.si fails/blocks, Nyaa falls back to nyaa-si.translate.goog and sticky-switches."""
        called_urls = []

        def _fake_get(url, params=None, **kw):
            called_urls.append(url)
            if 'translate.goog' not in url:
                return MagicMock(status_code=503, text='<html>CF block</html>')
            return MagicMock(status_code=200, text='<div class="table-responsive"><table></table></div>')

        with patch('resources.lib.ui.domains.get_domain', return_value='https://nyaa.si/'):
            scraper = nyaa.Sources()

        with patch('resources.lib.ui.client.get', side_effect=_fake_get):
            html = scraper._fetch_html({'q': 'Wistoria'})
            self.assertIsNotNone(html)
            self.assertIn('translate.goog', scraper._active_base_url)

        self.assertEqual(len(called_urls), 2)
        self.assertIn('nyaa.si', called_urls[0])
        self.assertIn('nyaa-si.translate.goog', called_urls[1])

    def test_c11_get_sub_falls_back_to_origin_on_http200_json_or_cueless_vtt(self):
        """C-11: Proxy returning HTTP 200 JSON error or cue-less WEBVTT triggers origin fallback and normalizes leading whitespace."""
        valid_vtt = '   \n\ufeff  WEBVTT\n\n00:01.020 --> 00:07.020\nEPISODE 1: AMBITION\n'
        written = {}

        def _capture_write(path, content):
            written['path'] = path
            written['content'] = content
            return True

        def _fake_get(url, headers=None, **kw):
            if 'megacloud.animanga.fun' in url:
                return MagicMock(text='{"error": "token expired"}')
            return MagicMock(text=valid_vtt)

        with patch('resources.lib.ui.client.get', side_effect=_fake_get), \
             patch('resources.lib.ui.control.atomic_write_text', side_effect=_capture_write):
            entry = embed_extractor.get_sub(
                'https://megacloud.animanga.fun/fetch?url=https%3A%2F%2Forigin.test%2Feng-2.vtt',
                'eng',
                source_url='https://origin.test/eng-2.vtt',
                sub_index=0,
                sub_tag='58516_1_999',
            )

        self.assertIsNotNone(entry)
        self.assertEqual(entry['path'], 'special://temp/TemporarySubs.58516_1_999.0.eng.vtt')
        # Leading spaces stripped so WEBVTT starts at byte 0 (Kodi DVDFactorySubtitle.cpp requirement)
        self.assertTrue(written['content'].startswith('WEBVTT'))

    def test_c11_get_sub_rejects_cueless_vtt_invalid_srt_and_failed_write(self):
        """C-11: Rejects cue-less WEBVTT stubs, non-cue SRT garbage, and atomic_write_text=False; auto-promotes hour-less VTT."""
        # Cue-less VTT stub rejected
        with patch('resources.lib.ui.client.get', return_value=MagicMock(text='WEBVTT\n\n')):
            self.assertIsNone(embed_extractor.get_sub('https://cdn.test/stub.vtt', 'eng'))

        # Plain-text error on extensionless URL (defaults to .srt) rejected
        with patch('resources.lib.ui.client.get', return_value=MagicMock(text='403 Forbidden - Access Denied')):
            self.assertIsNone(embed_extractor.get_sub('https://cdn.test/subtitle/12345', 'eng'))

        # Hour-less VTT cues on extensionless URL auto-promoted to .vtt with WEBVTT header
        written = {}

        def _capture_write(path, content):
            written['path'] = path
            written['content'] = content
            return True

        with patch('resources.lib.ui.client.get', return_value=MagicMock(text='00:01.020 --> 00:07.020\nHello\n')), \
             patch('resources.lib.ui.control.atomic_write_text', side_effect=_capture_write):
            entry = embed_extractor.get_sub('https://cdn.test/subtitle/12345', 'eng')
        self.assertIsNotNone(entry)
        self.assertTrue(entry['path'].endswith('.0.eng.vtt'))
        self.assertTrue(written['content'].startswith('WEBVTT\n\n'))

        # Write failure returns None instead of passing broken path to Kodi
        with patch('resources.lib.ui.client.get', return_value=MagicMock(text='WEBVTT\n\n00:01.000 --> 00:03.000\nHi\n')), \
             patch('resources.lib.ui.control.atomic_write_text', return_value=False):
            self.assertIsNone(embed_extractor.get_sub('https://cdn.test/ok.vtt', 'eng'))


if __name__ == '__main__':
    unittest.main()
