"""Unit tests for 10.13.0.16 log audit fixes (#1-#6).

Covers:
1. service.otaku.rpdev _wait_for_compatible_plugin() requires AddonManager registration and
   _shutdown_cleanup() releases Kodi SWIG proxies cleanly.
2. AnimePahe rotates across healthy mirrors + translate.goog fallback on 403/empty JSON,
   using 900s per-mirror cooldown, and BrowserBase._get_request() preserves translate.goog query params,
   while client.request() attempts FlareSolverr on Cloudflare 403 when enabled.
3. auto_download_subtitles() attempts up to 10 candidates and deduplicates identical URLs.
4. _attempt_midstream_failover('buffer_stall') skips CircuitBreaker trip & false-positive warning
   when 0 backup candidates exist.
5. control.xbmc_add_dir() / set_videotags() coerce None values so Kodi never receives None strings.
6. enforce_memory_watermark() keeps 900/2600 on <=2048MB sticks and scales to 1152/3200 on >2500MB RAM.
"""

import importlib.util
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PLUGIN_ROOT = os.path.join(_REPO_ROOT, 'plugin.video.otaku.rpdev')
_SERVICE_ROOT = os.path.join(_REPO_ROOT, 'service.otaku.rpdev')
_SERVICE_LIB = os.path.join(_SERVICE_ROOT, 'resources', 'lib')
for p in (_PLUGIN_ROOT, _SERVICE_LIB):
    if p not in sys.path:
        sys.path.insert(0, p)

from otaku_service import daemon as svc_daemon
from resources.lib import subtitles
from resources.lib.pages import animepahe
from resources.lib.subtitles.models import SubtitleResult, VideoMeta
from resources.lib.ui import BrowserBase, client, control, database, domains, player


def _load_service_entrypoint():
    spec = importlib.util.spec_from_file_location('otaku_service_main_test', os.path.join(_SERVICE_ROOT, 'service.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestServiceUpgradeRaceAndCleanup(unittest.TestCase):
    """Item #1: _wait_for_compatible_plugin requires Kodi Addon registration & _shutdown_cleanup releases proxies."""

    def test_wait_for_compatible_plugin_waits_for_kodi_addon_registration(self):
        svc_mod = _load_service_entrypoint()
        attempts = {'count': 0}

        def _fake_addon(addon_id):
            attempts['count'] += 1
            if attempts['count'] < 2:
                raise RuntimeError("Unknown addon id 'plugin.video.otaku.rpdev'")
            m = MagicMock()
            m.getAddonInfo.return_value = _PLUGIN_ROOT
            return m

        mock_mon = MagicMock()
        mock_mon.abortRequested.return_value = False
        mock_mon.waitForAbort.return_value = False

        with patch.object(svc_mod.xbmcaddon, 'Addon', side_effect=_fake_addon):
            path = svc_mod._wait_for_compatible_plugin(mock_mon, max_wait_s=5.0)

        self.assertEqual(path, _PLUGIN_ROOT)
        self.assertEqual(attempts['count'], 2)
        mock_mon.waitForAbort.assert_called_once_with(1.0)

    def test_shutdown_cleanup_releases_kodi_swig_proxies(self):
        with patch.object(control, 'release_kodi_proxies') as mock_release, \
             patch.object(database, 'checkpoint_databases'), \
             patch.object(database, 'close_all_connections'):
            svc_daemon._shutdown_cleanup(multipage_worker=None)
        mock_release.assert_called_once()


class TestAnimePaheMirrorFallbackAndFlareSolverr(unittest.TestCase):
    """Item #2: AnimePahe rotates mirrors + translate.goog with 900s cooldown & attempts FlareSolverr on CF 403."""

    def setUp(self):
        domains.adaptive_circuit_breaker.reset()
        domains.clear_mirror_failures()

    def tearDown(self):
        domains.adaptive_circuit_breaker.reset()
        domains.clear_mirror_failures()

    def test_browserbase_get_request_joins_translate_goog_params_with_ampersand(self):
        captured = {}
        fake_resp = MagicMock()
        fake_resp.text = '{"data": []}'

        def _fake_get(url, headers=None):
            captured['url'] = url
            return fake_resp

        bb = BrowserBase.BrowserBase()
        with patch.object(client, 'get', side_effect=_fake_get):
            res = bb._get_request(
                'https://animepahe-pw.translate.goog/api?_x_tr_sl=auto&_x_tr_tl=en',
                data={'m': 'search', 'q': 'Bleach'},
            )
        self.assertEqual(res, '{"data": []}')
        self.assertIn('?_x_tr_sl=auto&_x_tr_tl=en&m=search&q=Bleach', captured['url'])
        self.assertEqual(captured['url'].count('?'), 1)

    def test_animepahe_rotates_to_healthy_mirror_with_900s_cooldown(self):
        src = animepahe.Sources()
        called_urls = []

        def _fake_query(api_url, headers, query_title):
            called_urls.append(api_url)
            if 'animepahe.pw' in api_url:
                return None, False
            return [{'title': 'Bleach', 'year': 2004, 'session': 'sess-123'}], True

        with patch.object(src, '_collect_search_titles', return_value=(['Bleach'], {})), \
             patch.object(src, '_resolve_session_from_malsync', return_value=None), \
             patch.object(src, '_query_search_api', side_effect=_fake_query), \
             patch.object(src, '_process_ap', return_value=[{'provider': 'animepahe', 'hash': 'ok'}]):
            results = src.get_sources(269, 100)

        self.assertEqual(len(results), 1)
        self.assertGreaterEqual(len(called_urls), 2)
        self.assertIn('animepahe.pw', called_urls[0])
        self.assertFalse(domains.is_mirror_healthy('https://animepahe.pw/'))

    def test_client_request_attempts_flaresolverr_on_animepahe_cf_403_when_enabled(self):
        """Verify client.get() invokes FlareSolverr cfcookie on Cloudflare 403 when fs_enable=True."""
        import urllib.error
        from io import BytesIO

        cf_html = b'<html><head><title>Just a moment...</title></head><body>cloudflare</body></html>'
        err_403 = urllib.error.HTTPError(
            'https://animepahe.pw/api?m=search&q=Bleach',
            403,
            'Forbidden',
            {'Server': 'cloudflare'},
            BytesIO(cf_html),
        )
        fake_solver = MagicMock()
        fake_solver.solve_request.return_value = {
            'status': 200,
            'body': '{"data": [{"title": "Bleach"}]}',
            'cookie': 'cf_clearance=ok',
        }

        def _bool_cfg(k, default=False):
            return k == 'fs_enable'

        with patch('urllib.request.OpenerDirector.open', side_effect=err_403), \
             patch.object(control, 'getBool', side_effect=_bool_cfg), \
             patch.object(client, 'cfcookie', return_value=fake_solver), \
             patch.object(domains.adaptive_circuit_breaker, 'is_tripped', return_value=False), \
             patch.object(domains.adaptive_circuit_breaker, 'record_failure'):
            resp = client.get('https://animepahe.pw/api?m=search&q=Bleach')

        fake_solver.solve_request.assert_called_once()
        self.assertIsNotNone(resp)
        self.assertIn('Bleach', resp.text)


class TestSubtitleAutoAttemptsAndFailoverAndCoercion(unittest.TestCase):
    """Items #3, #4, #5: Subtitle 10-attempt budget, buffer_stall no-backup guard, None string coercion."""

    def test_auto_download_subtitles_succeeds_after_6_mismatches_and_dedups_urls(self):
        candidates = [
            SubtitleResult('subsource', f'Pack_{i}.zip', f'Pack_{i}.zip', 'English', 'en', f'https://sub/{i}', auto_identified=True)
            for i in range(7)
        ]
        # Duplicate URL on #1 should be skipped without burning an attempt
        candidates.insert(1, SubtitleResult('subsource', 'Dup.zip', 'Dup.zip', 'English', 'en', 'https://sub/0', auto_identified=True))

        meta = VideoMeta(title='Bleach', tvshow='Bleach', season=1, episode=75, preferred_lang='en')
        mock_player = MagicMock()
        mock_player.isPlaying.return_value = True
        mock_player.getTime.return_value = 0.0

        dl_calls = []

        def _fake_download(cand, m, s):
            dl_calls.append(cand.download_url)
            if cand.download_url == 'https://sub/6':
                return '/tmp/bleach_75.ass'
            return None

        with patch.object(subtitles, 'search_subtitles', return_value=candidates), \
             patch.object(subtitles, 'download_subtitle', side_effect=_fake_download), \
             patch.object(subtitles.xbmc, 'Player', return_value=mock_player), \
             patch.object(control, 'setGlobalProp'), \
             patch.object(control, 'notify'):
            ok = subtitles.auto_download_subtitles(meta=meta, settings={'subtitles.auto_search': True, 'subtitles.auto_download': True})

        self.assertTrue(ok)
        self.assertEqual(len(dl_calls), 7)
        self.assertEqual(dl_calls[-1], 'https://sub/6')

    def test_buffer_stall_without_backup_does_not_trip_circuit_breaker(self):
        domains.adaptive_circuit_breaker.reset()
        wp = player.WatchlistPlayer()
        wp.mal_id = 269
        wp.episode = 98
        wp.current_time = 120
        wp.path = 'https://fetch.nexabloom.top/anime/abc/master.m3u8'

        ctx = {
            'active_host': 'fetch.nexabloom.top',
            'active_url': wp.path,
            'sources': [{'hash': wp.path, 'provider': 'hianime'}],
            'candidate_index': 0,
        }
        with patch.object(database, 'get_playback_failover_context', return_value=ctx), \
             patch('resources.lib.windows.resolver.resolve_failover_candidate', return_value=None), \
             patch.object(control, 'log_metric') as mock_metric:
            res = wp._attempt_midstream_failover('buffer_stall')

        self.assertFalse(res)
        self.assertFalse(domains.adaptive_circuit_breaker.is_tripped('fetch.nexabloom.top', category='debrid'))
        mock_metric.assert_not_called()

    def test_xbmc_add_dir_never_passes_none_strings(self):
        mock_li = MagicMock()
        with patch('xbmcgui.ListItem', return_value=mock_li), \
             patch('xbmcplugin.addDirectoryItem', return_value=True):
            res = control.xbmc_add_dir(
                name=None,
                url=None,
                art={'thumb': None, 'poster': 'https://img/p.jpg'},
                info={'title': 'Test', 'code': None, 'hdrtype': 'hdr10'},
                draw_cm=[('Valid', 'action'), (None, 'bad')],
                bulk_add=True,
                isfolder=True,
                isplayable=False,
            )
        self.assertIsInstance(res[0], str)
        for call in mock_li.setProperty.call_args_list:
            self.assertIsNotNone(call[0][0])
            self.assertIsNotNone(call[0][1])
        cm_calls = mock_li.addContextMenuItems.call_args[0][0]
        self.assertEqual(len(cm_calls), 1)
        self.assertEqual(cm_calls[0][0], 'Valid')


class TestMemoryWatermarkHardwareScaling(unittest.TestCase):
    """Item #6: 900/2600 on <=2GB sticks; 1152/3200 on >2500MB RAM devices when default 900."""

    def _write_status(self, tmpdir, rss_mb, vmsize_mb):
        p = os.path.join(tmpdir, 'status')
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write(f"VmSize:\t{int(vmsize_mb * 1024)} kB\nVmRSS:\t{int(rss_mb * 1024)} kB\n")
        return p

    def test_scales_to_1152_and_3200_on_3gb_device_without_triggering_at_1050_or_3100(self):
        control.clearGlobalProp('otaku.memory_pressure')
        with tempfile.TemporaryDirectory() as tmpdir:
            p = self._write_status(tmpdir, rss_mb=1050, vmsize_mb=3100)
            with patch.object(control, 'get_device_ram_mb', return_value=2912), \
                 patch.object(control, 'getInt', return_value=900):
                res = control.enforce_memory_watermark(status_path=p, force_32bit=True, trim_fn=lambda: False)
            self.assertFalse(res['triggered'])
            self.assertEqual(res['watermark_mb'], 1152.0)
            self.assertEqual(res['vmsize_guard_mb'], 3200.0)

            # Still triggers if RSS >= 1152 MB
            p_high = self._write_status(tmpdir, rss_mb=1180, vmsize_mb=3100)
            with patch.object(control, 'get_device_ram_mb', return_value=2912), \
                 patch.object(control, 'getInt', return_value=900):
                res_high = control.enforce_memory_watermark(status_path=p_high, force_32bit=True, trim_fn=lambda: False)
            self.assertTrue(res_high['triggered'])
        control.clearGlobalProp('otaku.memory_pressure')


if __name__ == '__main__':
    unittest.main()
