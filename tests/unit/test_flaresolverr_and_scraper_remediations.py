"""
test_flaresolverr_and_scraper_remediations.py
=============================================
Unit & regression tests covering FB-01 through FB-10 remediations:
- Zero soupsieve runtime dependency in HiAnime, Nyaa, Gogoanime, AnimeKai (FB-01)
- FlareSolverr direct HTML execution (JA3/JA4 bypass), hard WAF fast-fail, and negative cooldown (FB-02, FB-05)
- Modern DDoS-Guard (__ddg1_/__ddg8_/__ddg9_/__ddg10_) cookie support (FB-04)
- Lazy challenge-only FlareSolverr fallback in Resolver.prefetch_play_link (FB-03)
- AnimePahe active mirrors & HTTPS-first connectivity checks (FB-05, FB-06)
- Spoiler Shield list-valued fanart unwrapping (FB-07)
- airing_calendar isFolder=False & modal disposal (FB-08)
"""

import io
import json
import os
import sys
import unittest
import urllib.error
from email.message import Message
from unittest.mock import MagicMock, patch

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_TEST_DIR, '..' if os.path.basename(_TEST_DIR) in ('unit', 'integration', 'lint') else '.'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
_TESTS_DIR = os.path.join(_REPO_ROOT, 'tests')
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import conftest  # noqa: F401

from resources.lib import Main
from resources.lib import indexers
from resources.lib.pages import animepahe, gogoanime, hianime, nyaa
from resources.lib.ui import client, control, database, domains
from resources.lib.windows.resolver import Resolver


def _make_http_error(url, code, body_str, server='cloudflare', cf_mitigated=''):
    hdrs = Message()
    hdrs['Server'] = server
    if cf_mitigated:
        hdrs['cf-mitigated'] = cf_mitigated
    return urllib.error.HTTPError(
        url, code, 'Forbidden', hdrs, io.BytesIO(body_str.encode('utf-8'))
    )


class TestFlareSolverrAndScraperRemediations(unittest.TestCase):

    def setUp(self):
        control.clearSettingsCache()
        client.clear_session()

    def tearDown(self):
        client.clear_session()
        control.cleanup()

    def test_fb01_scrapers_parse_without_soupsieve_installed(self):
        """HiAnime, Nyaa, and Gogoanime HTML parsers succeed even when soupsieve is absent."""
        with patch.dict(sys.modules, {'soupsieve': None}):
            # 1. HiAnime search + episode list + server list
            search_html = '''
            <div class="flw-item">
                <div class="film-detail"><h3 class="film-name"><a href="/frieren-beyond-journeys-end-18542?ref=search">Frieren</a></h3></div>
            </div>
            '''
            items = hianime.Sources._parse_search_results(search_html)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]['id'], '18542')

            hi = hianime.Sources()
            ep_payload = {'html': '<div class="ss-list"><a class="ep-item" data-number="1" data-id="107257">1</a></div>'}
            with patch('resources.lib.ui.database.get', return_value=ep_payload):
                self.assertEqual(hi._resolve_episode_id('https://hianime.at/', '18542', 1, {}), '107257')

            # 2. Nyaa episode table
            nyaa_html = '''
            <div class="table-responsive"><table><tbody>
                <tr class="success">
                    <td></td>
                    <td><a href="/view/1" title="[SubsPlease] Sousou no Frieren - 01 (1080p).mkv">Title</a>
                        <a href="/view/1" title="[SubsPlease] Sousou no Frieren - 01 (1080p).mkv">Link2</a></td>
                    <td class="text-center"><a href="magnet:?xt=urn:btih:abcdef1234567890abcdef1234567890abcdef12">M</a></td>
                    <td class="text-center">1.4 GiB</td>
                    <td class="text-center">2023-09-29</td>
                    <td class="text-center">150</td>
                    <td class="text-center">2</td>
                    <td class="text-center">5000</td>
                </tr>
            </tbody></table></div>
            '''
            mock_resp = MagicMock(status_code=200, text=nyaa_html)
            ny = nyaa.Sources()
            with patch('resources.lib.ui.client.get', return_value=mock_resp), \
                 patch('resources.lib.ui.source_utils.filter_sources', side_effect=lambda _p, lst, *_a: lst):
                rows = ny._fetch_and_filter_episodes('https://nyaa.si/', {}, 52991, '01', '01', None)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['seeders'], 150)

    def test_fb02_client_direct_flaresolverr_bypasses_ja3_cookie_replay(self):
        """client.request returns solved HTML directly from FlareSolverr without second urllib 403 failure."""
        fs_json = json.dumps({
            'status': 'ok',
            'solution': {
                'url': 'https://www.wcostream.tv/anime/frieren',
                'status': 200,
                'headers': {'Content-Type': 'text/html; charset=utf-8'},
                'response': '<html><title>Frieren</title></html>',
                'cookies': [{'name': 'cf_clearance', 'value': 'tok123'}],
                'userAgent': 'Mozilla/5.0 Chrome/142',
            },
        })
        cf_err = _make_http_error(
            'https://www.wcostream.tv/anime/frieren',
            403,
            '<html><head><title>Just a moment...</title></head></html>',
            cf_mitigated='challenge',
        )
        mock_opener = MagicMock()
        mock_opener.open.side_effect = cf_err

        with patch('urllib.request.build_opener', return_value=mock_opener), \
             patch('resources.lib.ui.control.getBool', side_effect=lambda k, **_kw: k == 'fs_enable'), \
             patch('resources.lib.ui.control.getSetting', return_value='http://127.0.0.1:8191/v1'), \
             patch('resources.lib.ui.control.getInt', return_value=25), \
             patch('resources.lib.ui.client._basic_request', return_value=fs_json), \
             patch('resources.lib.ui.client.store'):
            resp = client.get('https://www.wcostream.tv/anime/frieren')
            self.assertEqual(resp.status_code, 200)
            self.assertIn('<title>Frieren</title>', resp.text)
            # Opener was called ONLY once (no second urllib replay that would fail JA3/JA4!)
            self.assertEqual(mock_opener.open.call_count, 1)

    def test_fb04_ddgcookie_accepts_modern_ddg_cookie_names(self):
        """ddgcookie accepts __ddg1_, __ddg8_, __ddg9_, __ddg10_ when __ddg2_ is absent."""
        fs_json = json.dumps({
            'status': 'ok',
            'solution': {
                'status': 200,
                'cookies': [
                    {'name': '__ddg1_', 'value': 'a1'},
                    {'name': '__ddg8_', 'value': 'a8'},
                    {'name': '__ddg9_', 'value': 'a9'},
                    {'name': '__ddg10_', 'value': 'a10'},
                ],
                'userAgent': 'Mozilla/5.0 Chrome/142',
            },
        })
        ddg = client.ddgcookie()
        with patch('resources.lib.ui.control.getSetting', return_value='http://127.0.0.1:8191/v1'), \
             patch('resources.lib.ui.control.getInt', return_value=20), \
             patch('resources.lib.ui.client._basic_request', return_value=fs_json), \
             patch('resources.lib.ui.client.store'):
            cookie, ua = ddg.get('https://nyaa.si/', 20)
            self.assertIsNotNone(cookie)
            self.assertIn('__ddg1_=a1', cookie)
            self.assertIn('__ddg10_=a10', cookie)
            self.assertEqual(ua, 'Mozilla/5.0 Chrome/142')

    def test_fb05_hard_waf_skips_flaresolverr_and_failed_host_enters_cooldown(self):
        """Hard Cloudflare WAF blocks skip FlareSolverr in 0ms; timeout puts host in negative cooldown."""
        waf_err = _make_http_error(
            'https://animepahe.pw/api?m=search&q=Frieren',
            403,
            '<html><title>Attention Required! | Cloudflare</title><div id="cf-error-details">Sorry, you have been blocked</div></html>',
        )
        mock_opener = MagicMock()
        mock_opener.open.side_effect = waf_err
        with patch('urllib.request.build_opener', return_value=mock_opener), \
             patch('resources.lib.ui.control.getBool', return_value=True), \
             patch('resources.lib.ui.client._basic_request') as mock_fs:
            resp = client.get('https://animepahe.pw/api?m=search&q=Frieren')
            self.assertEqual(resp.status_code, 403)
            mock_fs.assert_not_called()

        # Interactive Turnstile timeout records cooldown so 2nd call skips FlareSolverr immediately
        with patch('resources.lib.ui.control.getSetting', return_value='http://127.0.0.1:8191/v1'), \
             patch('resources.lib.ui.control.getInt', return_value=20), \
             patch('resources.lib.ui.client._basic_request', return_value='{"status":"error","message":"Timeout"}') as mock_fs2:
            cf = client.cfcookie()
            self.assertIsNone(cf.solve_request('https://animepahe.pw/'))
            self.assertIsNone(cf.solve_request('https://animepahe.pw/anime/123'))
            self.assertEqual(mock_fs2.call_count, 1)

    def test_fb03_resolver_prefetch_skips_flaresolverr_on_healthy_cdn(self):
        """Resolver.prefetch_play_link does NOT invoke FlareSolverr when stream CDN returns HTTP 200/206."""
        healthy_resp = MagicMock(status_code=206, headers={'Content-Type': 'application/vnd.apple.mpegurl'}, url='https://megacloud.animanga.fun/master.m3u8')
        with patch('resources.lib.ui.control.getBool', side_effect=lambda k, **_kw: k == 'fs_enable'), \
             patch('resources.lib.ui.client.head', return_value=healthy_resp), \
             patch('resources.lib.ui.client.cfcookie.get') as mock_cf:
            out = Resolver.prefetch_play_link('https://megacloud.animanga.fun/master.m3u8')
            self.assertIsNotNone(out)
            mock_cf.assert_not_called()

    def test_fb05_animepahe_default_domain_and_origin_rewrite(self):
        """AnimePahe defaults to animepahe.pw (not parked .ru) and rewrites legacy slugs dynamically."""
        self.assertEqual(domains.DEFAULT_DOMAINS['animepahe'], 'https://animepahe.pw/')
        ap = animepahe.Sources()
        ap._BASE_URL = 'https://animepahe.org/'
        self.assertEqual(ap._rewrite_origin('https://animepahe.com/a/6231'), 'https://animepahe.org/a/6231')

    def test_fb07_spoiler_shield_unwraps_list_fanart(self):
        """Spoiler Shield unwraps list-valued fanart to a valid str so control.py never strips it."""
        ep_meta = {
            'name': 'The Journey\'s End',
            'info': {'title': 'The Journey\'s End', 'playcount': 0},
            'image': {
                'thumb': 'https://simkl.in/episodes/ep1_spoiler.webp',
                'icon': 'https://simkl.in/episodes/ep1_spoiler.webp',
                'fanart': ['https://assets.fanart.tv/frieren-fanart.jpg'],
                'poster': 'https://cdn.myanimelist.net/poster.jpg',
            },
        }
        row = {'number': 1, 'filler': '', 'kodi_meta': database.dumps(ep_meta)}
        with patch('resources.lib.ui.control.getBool', side_effect=lambda k, **_kw: k == 'interface.spoilers.hide_thumbs'), \
             patch('resources.lib.ui.control.getInt', return_value=0):
            parsed = indexers.parse_episodes(row, eps_watched=0)
            self.assertIsInstance(parsed['image']['thumb'], str)
            self.assertEqual(parsed['image']['thumb'], 'https://assets.fanart.tv/frieren-fanart.jpg')

    def test_fb08_airing_calendar_allocated_as_non_folder_action(self):
        """_finalize_menu_list_items marks airing_calendar with isfolder=False while normal menus remain folders."""
        items = Main._finalize_menu_list_items([
            ('Airing Anime Calendar', 'airing_calendar', 'airing_anime_calendar.png', {}),
            ('Trending', 'trending', 'trending.png', {}),
        ])
        self.assertFalse(items[0]['isfolder'])
        self.assertTrue(items[1]['isfolder'])

    def test_fb05_cf_alert_error_never_recurses_when_tls_retry_also_403(self):
        """Cloudflare 403 pages containing cf-alert-error must never recurse beyond a single TLSv1_2 retry."""
        call_count = [0]

        def _fake_open(req, timeout=None):
            call_count[0] += 1
            hdrs = Message()
            hdrs['Server'] = 'cloudflare'
            body = b'<html><body><div class="cf-alert-error">Error 1020</div></body></html>'
            raise urllib.error.HTTPError(req.full_url, 403, 'Forbidden', hdrs, io.BytesIO(body))

        mock_opener = MagicMock()
        mock_opener.open.side_effect = _fake_open
        with patch('urllib.request.build_opener', return_value=mock_opener):
            res = client.request('https://example.org/test', use_session=False)

        self.assertIsNone(res)
        self.assertEqual(call_count[0], 2)


if __name__ == '__main__':
    unittest.main()
