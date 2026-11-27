"""Comprehensive unit tests for Engineering Sprint WS-1 through WS-5 hardening.

Covers >= 2:1 negative/edge-to-happy assertions across:
- WS-1 (C-37): 32-bit ARM RSS/VmSize memory watermark guard & libc fallback
- WS-2: Shared 15s DNS/connectivity gate & circuit breaker non-escalation
- WS-3: Bounded p90 scrape latency tracker & conditional embed grace deadline
- WS-4 (NF-17): Debrid quota guard & opt-in Lazy Top-N probe (with selectFiles)
- WS-5: Chapter-aligned auto subtitle calibration, sub_offset_ms schema, SeriesProfile strict Kodi 22 XML & OSD path
"""
# -*- coding: utf-8 -*-

import datetime
import os
import socket
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from freezegun import freeze_time

from tests.kodi_profile import KodiProfile
from resources.lib.ui import client, control, database, database_sync, domains


class TestWS1MemoryWatermarkGuard(unittest.TestCase):
    """WS-1 (C-37): 32-bit ARM RSS/VmSize memory guard, native heap trim & hysteresis."""

    def setUp(self):
        control.clearGlobalProp('otaku.memory_pressure')
        control.clearGlobalProp('otaku.memory_concurrency_limit')
        control.setInt('general.memory_watermark_mb', 900)

    def tearDown(self):
        control.clearGlobalProp('otaku.memory_pressure')
        control.clearGlobalProp('otaku.memory_concurrency_limit')
        control.setInt('general.memory_watermark_mb', 900)

    def _write_proc_status(self, directory, rss_kb, vmsize_kb, vmpeak_kb=None):
        path = os.path.join(directory, 'status')
        vmpeak = vmpeak_kb if vmpeak_kb is not None else vmsize_kb
        content = (
            "Name:\tkodi.bin\n"
            f"VmPeak:\t{vmpeak:8d} kB\n"
            f"VmSize:\t{vmsize_kb:8d} kB\n"
            f"VmRSS:\t{rss_kb:8d} kB\n"
        )
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return path

    def test_ws1_happy_rss_trigger_and_hysteresis_recovery(self):
        """Happy path + hysteresis: >= 900 MB RSS trips throttle_gc_trim; < 85% clears pressure."""
        worker = MagicMock()
        with tempfile.TemporaryDirectory() as tmpdir:
            high_status = self._write_proc_status(tmpdir, rss_kb=920 * 1024, vmsize_kb=1500 * 1024)
            res = control.enforce_memory_watermark(
                context='unit_test',
                multipage_worker=worker,
                status_path=high_status,
                force_32bit=True,
                trim_fn=lambda: True,
            )
            self.assertTrue(res['triggered'])
            self.assertFalse(res['recovered'])
            self.assertEqual(res['action'], 'throttle_gc_trim')
            self.assertEqual(control.getGlobalProp('otaku.memory_pressure'), 'true')
            self.assertEqual(control.getGlobalProp('otaku.memory_concurrency_limit'), '1')
            worker.set_memory_pressure.assert_called_with(True, max_workers=1)

            # Edge: 800 MB is below 900 MB watermark, yet >= 765 MB (85% hysteresis) -> must remain throttled
            worker.reset_mock()
            mid_status = self._write_proc_status(tmpdir, rss_kb=800 * 1024, vmsize_kb=1500 * 1024)
            res_mid = control.enforce_memory_watermark(
                context='unit_test',
                multipage_worker=worker,
                status_path=mid_status,
                force_32bit=True,
            )
            self.assertFalse(res_mid['triggered'])
            self.assertFalse(res_mid['recovered'])
            self.assertEqual(control.getGlobalProp('otaku.memory_pressure'), 'true')

            # Recovery: 700 MB < 765 MB (85% of 900) and VmSize < 85% of 2600 -> clears pressure
            low_status = self._write_proc_status(tmpdir, rss_kb=700 * 1024, vmsize_kb=1400 * 1024)
            res_low = control.enforce_memory_watermark(
                context='unit_test',
                multipage_worker=worker,
                status_path=low_status,
                force_32bit=True,
            )
            self.assertTrue(res_low['recovered'])
            self.assertEqual(res_low['action'], 'hysteresis_cleared')
            self.assertEqual(control.getGlobalProp('otaku.memory_pressure'), '')
            worker.set_memory_pressure.assert_called_with(False, max_workers=None)

    def test_ws1_negative_vmsize_2600mb_guard_and_64bit_skip(self):
        """Negative/Edge: VmSize >= 2600 MB trips guard even at low RSS; 64-bit host returns no-op."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vmsize_high = self._write_proc_status(tmpdir, rss_kb=450 * 1024, vmsize_kb=2650 * 1024)
            res_32 = control.enforce_memory_watermark(
                status_path=vmsize_high,
                force_32bit=True,
                trim_fn=lambda: False,
            )
            self.assertTrue(res_32['triggered'])
            self.assertEqual(res_32['action'], 'throttle_gc_only')

            # Reset and verify 64-bit host is unaffected
            control.clearGlobalProp('otaku.memory_pressure')
            res_64 = control.enforce_memory_watermark(status_path=vmsize_high, force_32bit=False)
            self.assertFalse(res_64['triggered'])
            self.assertEqual(res_64['action'], 'none')
            self.assertEqual(control.getGlobalProp('otaku.memory_pressure'), '')

    def test_ws1_edge_missing_proc_status_and_bionic_mallopt_fallback(self):
        """Edge: Missing /proc/self/status is safe None; _trim_native_heap falls back from libc.so.6 to libc.so mallopt(-101, 0)."""
        self.assertIsNone(control.get_process_memory_mb(status_path='/nonexistent/proc/self/status'))
        res = control.enforce_memory_watermark(status_path='/nonexistent/proc/self/status', force_32bit=True)
        self.assertFalse(res['triggered'])
        self.assertEqual(res['action'], 'none')

        # Simulate libc.so.6 failing to load and Android Bionic libc.so (without malloc_trim) succeeding via mallopt(-101, 0)
        bionic_lib = MagicMock(spec=['mallopt'])
        bionic_lib.mallopt.return_value = 1

        def _fake_cdll(name):
            if name == 'libc.so.6':
                raise OSError("not glibc")
            if name == 'libc.so':
                return bionic_lib
            raise OSError("unknown lib")

        with patch('ctypes.CDLL', side_effect=_fake_cdll):
            trimmed = control._trim_native_heap()
        self.assertTrue(trimmed)
        bionic_lib.mallopt.assert_called_once_with(-101, 0)

        # When both CDLLs fail, returns False cleanly without raising
        with patch('ctypes.CDLL', side_effect=OSError("no libc")):
            self.assertFalse(control._trim_native_heap())

    def test_ws1_edge_service_multipage_throttle_and_tools_filecache_warning(self):
        """Edge: MultipageWorker throttles concurrency under memory pressure; tools.py warns on 32-bit filecache > 64 MB."""
        import service
        worker = service.MultipageWorker.__new__(service.MultipageWorker)
        worker._memory_throttled = False
        worker.max_concurrency = 2
        worker.set_memory_pressure(True, max_workers=1)
        self.assertTrue(worker._memory_throttled)
        self.assertEqual(worker.max_concurrency, 1)
        worker.set_memory_pressure(False, max_workers=2)
        self.assertFalse(worker._memory_throttled)
        self.assertEqual(worker.max_concurrency, 2)

        from resources.lib.routes import tools
        fake_mem = {'rss_mb': 500.0, 'vmsize_mb': 1200.0, 'vm_peak_mb': 1300.0}
        # RPC returns 128 MB filecache -> 32-bit recommendation must appear in returned diagnostics text
        rpc_resp = {'result': {'value': 134217728}}
        with patch('resources.lib.ui.control.jsonrpc', return_value=rpc_resp), \
             patch('resources.lib.ui.control.get_process_memory_mb', return_value=fake_mem), \
             patch('resources.lib.ui.control.is_32bit_process', return_value=True):
            report_text = tools.generate_diagnostics_report()
            self.assertIn('Kodi File Cache: 128 MB', report_text)
            self.assertIn('64 MB on 32-bit', report_text)


class TestWS2ConnectivityGate(unittest.TestCase):
    """WS-2: Shared 15s DNS/connectivity gate & circuit breaker non-escalation."""

    def setUp(self):
        client.clear_connectivity_gate()
        domains.adaptive_circuit_breaker.reset()

    def tearDown(self):
        client.clear_connectivity_gate()
        domains.adaptive_circuit_breaker.reset()

    def test_ws2_negative_single_dead_mirror_does_not_trip_gate(self):
        """Negative: 1 dead hostname failing with gaierror repeatedly must NOT trip global gate."""
        gai = socket.gaierror(-2, "Name or service not known")
        gate = client.ConnectivityGate()
        with freeze_time("2026-11-26 12:00:00"):
            tripped1 = gate.record_failure('dead-mirror-a.example', gai, verify_connectivity_fn=lambda: True)
            tripped2 = gate.record_failure('dead-mirror-a.example', gai, verify_connectivity_fn=lambda: True)
            self.assertFalse(tripped1)
            self.assertFalse(tripped2)
            self.assertFalse(gate.is_tripped())

    def test_ws2_happy_two_distinct_hostnames_trip_and_clamp_ttl_with_single_clear_log(self):
        """Happy + Edge: >= 2 distinct failing hostnames within 5s trips gate <= 15s; transition-only clear log."""
        gai = socket.gaierror(-3, "Temporary failure in name resolution")
        gate = client.ConnectivityGate()
        with freeze_time("2026-11-26 12:00:00") as frozen:
            self.assertFalse(gate.record_failure('nyaa.si', gai, verify_connectivity_fn=lambda: True))
            frozen.tick(delta=datetime.timedelta(seconds=2))
            self.assertTrue(gate.record_failure('animetosho.org', gai, verify_connectivity_fn=lambda: True))
            self.assertTrue(gate.is_tripped())

            # Clamp check: even if clock skew stored an extreme property, internal _gate_until is clamped <= now + 15s
            now = 1795694402.0
            gate._gate_until = 0.0
            control.homeWindow.setProperty('otaku.dns_gate_until', str(now + 9999.0))
            with patch('resources.lib.ui.client.time.time', return_value=now):
                self.assertTrue(gate.is_tripped())
                self.assertLessEqual(gate._gate_until, now + 15.0 + 0.01)

            # Clear transitions via record_success() emit state=cleared exactly once
            with patch('resources.lib.ui.control.log_metric') as mock_metric:
                gate.record_success()
                gate.record_success()
                self.assertEqual(mock_metric.call_count, 1)
                self.assertEqual(mock_metric.call_args[1].get('state'), 'cleared')

    def test_ws2_negative_client_request_failfast_and_circuit_breaker_non_escalation(self):
        """Negative: Tripped gate fail-fasts client.request() and circuit breaker skips cooldown on DNS drop."""
        gate = client._connectivity_gate
        gai = socket.gaierror(-3, "Temporary failure in name resolution")
        gate.record_failure('nyaa.si', gai, verify_connectivity_fn=lambda: True)
        gate.record_failure('animetosho.org', gai, verify_connectivity_fn=lambda: True)
        self.assertTrue(client.is_connectivity_gate_tripped())
        res = client.request('https://nyaa.si/?q=frieren')
        self.assertIsNone(res)
        self.assertTrue(getattr(client._tls_req_state, 'last_connectivity_drop', False))

        # Circuit breaker must NOT open cooldown for a connectivity drop or socket.gaierror
        cb = domains.adaptive_circuit_breaker
        gai = socket.gaierror(-3, "Temporary failure in name resolution")
        for _ in range(5):
            cb.record_failure('nyaa.si', is_connectivity_drop=True)
            cb.record_failure('nyaa.si', exc=gai)
        self.assertFalse(cb.is_tripped('nyaa.si'))

        # True provider error (after gate clears) still trips circuit breaker normally
        client.clear_connectivity_gate()
        for _ in range(cb.failure_threshold):
            cb.record_failure('nyaa.si', exc=RuntimeError("HTTP 500"))
        self.assertTrue(cb.is_tripped('nyaa.si'))


class TestWS3AdaptiveScrapeDeadlines(unittest.TestCase):
    """WS-3: Bounded <= 20 sample p90 latency tracker & conditional embed grace deadline."""

    def setUp(self):
        database.clear_scraper_metrics()

    def test_ws3_happy_and_edge_ring_buffer_p90_calculation(self):
        """Edge: Ring buffer caps at <= 20 samples per provider and computes true p90 after >= 3 samples."""
        # < 3 samples excluded by default min_samples=3
        database.record_provider_latency('hianime', 1.2)
        database.record_provider_latency('hianime', 1.8)
        self.assertNotIn('hianime', database.get_provider_p90_latencies(min_samples=3))

        # Push 25 samples: 15 fast (1.0s), then 10 slower (4.0s) -> only latest 20 kept (10x 1.0 + 10x 4.0 -> p90 = 4.0)
        database.clear_scraper_metrics()
        for _ in range(15):
            database.record_provider_latency('hianime', 1.0)
        for _ in range(10):
            database.record_provider_latency('hianime', 4.0)

        cached_row = database.cache_get(database._SCRAPER_LATENCY_CACHE_KEY)
        self.assertIsNotNone(cached_row)
        data = control.loads_json(cached_row['value'], default={})
        samples = data.get('hianime') or []
        self.assertLessEqual(len(samples), 20)
        self.assertEqual(len(samples), 20)
        p90_map = database.get_provider_p90_latencies(min_samples=3)
        self.assertAlmostEqual(p90_map['hianime'], 4.0, places=2)

    def test_ws3_edge_cold_start_and_cached_yield_embed_grace_behavior(self):
        """Edge: 0 cached yield triggers bounded +4s cold-start grace; >= 1 cached terminates cleanly without grace."""
        from resources.lib import pages

        args = {
            'query': 'Frieren',
            'mal_id': '52991',
            'episode': '1',
            'status': 'Finished Airing',
            'media_type': 'tv',
            'duration': '24',
            'rescrape': False,
            'source_select': False,
        }

        # Scenario A: 0 cached torrents + pending embed -> cold-start +4.0s grace applied cleanly
        with patch('resources.lib.pages.database.get_provider_p90_latencies', return_value={}), \
             patch('resources.lib.pages._TORRENT_MODULES', {}), \
             patch('resources.lib.pages._HOSTER_MODULES', {}), \
             patch('resources.lib.pages._EMBED_MODULES', [('hianime', MagicMock(), 'cache_k', 'hianime', False)]), \
             patch('resources.lib.pages.domains.adaptive_circuit_breaker.is_tripped', return_value=False), \
             patch('resources.lib.pages.control.getInt', side_effect=lambda k, default=0: 5 if k == 'general.timeout' else default), \
             patch('resources.lib.pages.control.getBool', side_effect=lambda k, default=False: k == 'provider.hianime'), \
             patch('resources.lib.pages.control.enabled_debrid', return_value={}), \
             patch('resources.lib.pages.control.enabled_cloud', return_value={}), \
             patch('resources.lib.pages.control.sleep'), \
             patch('resources.lib.pages.control.log_metric') as mock_metric:
            src = pages.Sources('get_sources.xml', control.ADDON_PATH, actionArgs=args)
            src._start_worker = lambda fn: MagicMock()
            perf_vals = iter([100.0, 105.5, 105.5, 110.0, 110.1])
            with patch('resources.lib.pages.time.perf_counter', side_effect=lambda: next(perf_vals, 115.0)):
                res = src.getSources(args)
            self.assertEqual(res, [])
            mock_metric.assert_called_once()
            self.assertEqual(mock_metric.call_args[0][0], 'scrape_summary')
            self.assertEqual(mock_metric.call_args[1]['embed_grace_s'], 4.0)

        # Scenario B: cached_yield >= 1 -> 0.0s grace even with pending embed
        with patch('resources.lib.pages.database.get_provider_p90_latencies', return_value={'hianime': 12.0}), \
             patch('resources.lib.pages._TORRENT_MODULES', {}), \
             patch('resources.lib.pages._HOSTER_MODULES', {}), \
             patch('resources.lib.pages._EMBED_MODULES', [('hianime', MagicMock(), 'cache_k', 'hianime', False)]), \
             patch('resources.lib.pages.domains.adaptive_circuit_breaker.is_tripped', return_value=False), \
             patch('resources.lib.pages.control.getInt', side_effect=lambda k, default=0: 5 if k == 'general.timeout' else default), \
             patch('resources.lib.pages.control.getBool', side_effect=lambda k, default=False: k == 'provider.hianime'), \
             patch('resources.lib.pages.control.enabled_debrid', return_value={}), \
             patch('resources.lib.pages.control.enabled_cloud', return_value={}), \
             patch('resources.lib.pages.control.sleep'), \
             patch('resources.lib.pages.control.log_metric') as mock_metric2:
            src2 = pages.Sources('get_sources.xml', control.ADDON_PATH, actionArgs=args)
            src2._start_worker = lambda fn: MagicMock()
            src2.torrentCacheSources = [{'hash': 'abc', 'type': 'torrent'}]
            perf_vals2 = iter([200.0, 206.0, 206.1])
            with patch('resources.lib.pages.time.perf_counter', side_effect=lambda: next(perf_vals2, 210.0)):
                src2.getSources(args)
            self.assertEqual(mock_metric2.call_args[1]['embed_grace_s'], 0.0)


class TestWS4DebridQuotaAndLazyProbe(unittest.TestCase):
    """WS-4 (NF-17): Debrid quota guard & opt-in Lazy Top-N probe across RD/PM/TB/AD."""

    def setUp(self):
        control.setBool('debrid.quota_guard', True)
        control.setBool('debrid.lazy_cache_probe', True)

    def tearDown(self):
        control.setBool('debrid.quota_guard', True)
        control.setBool('debrid.lazy_cache_probe', False)

    def test_ws4_happy_rd_lazy_probe_calls_selectfiles_before_downloaded_check(self):
        """Happy: RD probe_instant_cache calls addMagnet -> torrentSelect('all') -> torrentInfo -> checks downloaded."""
        from resources.lib.debrid.real_debrid import RealDebrid
        rd = RealDebrid()
        rd.autodelete = False
        call_seq = []

        def _add(m):
            call_seq.append('add')
            return {'id': 'rd_99'}

        def _sel(tid, files='all'):
            call_seq.append(('select', tid, files))
            return True

        def _info(tid):
            call_seq.append(('info', tid))
            return {'id': tid, 'status': 'downloaded'}

        with patch.object(rd, 'addMagnet', side_effect=_add), \
             patch.object(rd, 'torrentSelect', side_effect=_sel), \
             patch.object(rd, 'torrentInfo', side_effect=_info), \
             patch.object(rd, 'deleteTorrent') as mock_del:
            self.assertTrue(rd.probe_instant_cache('magnet:?xt=urn:btih:0123456789abcdef'))
            self.assertEqual(call_seq, ['add', ('select', 'rd_99', 'all'), ('info', 'rd_99')])
            mock_del.assert_not_called()

    def test_ws4_negative_rd_uncached_cleanup_and_saturation_warning_no_healthy_delete(self):
        """Negative: Uncached probe deletes temp torrent; saturated quota with 0 stalled logs warning & deletes 0 healthy."""
        from resources.lib.debrid.real_debrid import RealDebrid
        rd = RealDebrid()
        with patch.object(rd, 'addMagnet', return_value={'id': 'rd_uncached'}), \
             patch.object(rd, 'torrentSelect', return_value=True), \
             patch.object(rd, 'torrentInfo', return_value={'id': 'rd_uncached', 'status': 'downloading'}), \
             patch.object(rd, 'deleteTorrent', return_value=True) as mock_del:
            self.assertFalse(rd.probe_instant_cache('magnet:?xt=urn:btih:deadbeef'))
            mock_del.assert_called_once_with('rd_uncached')

        # Saturated 25 healthy completed items -> 0 deletions, 1 warning logged
        healthy_list = [{'id': f'ok_{i}', 'status': 'downloaded'} for i in range(25)]
        with patch.object(rd, 'list_torrents', return_value=healthy_list), \
             patch.object(rd, 'deleteTorrent') as mock_del_healthy, \
             patch('resources.lib.ui.control.log') as mock_log:
            cap = rd.ensure_cloud_capacity(max_active_slots=25)
            self.assertEqual(cap['pruned'], 0)
            self.assertTrue(cap['saturated'])
            mock_del_healthy.assert_not_called()
            mock_log.assert_called()
            self.assertIn('preserving healthy completed items', mock_log.call_args[0][0])

    def test_ws4_edge_lazy_probe_cap_only_tier3_positive_only_and_6s_timeout(self):
        """Edge: Lazy probe inspects <= 3 Tier-3 candidates (>=140 relevance), persists ONLY positive hits, stops at <= 6s."""
        from resources.lib.debrid import Debrid
        deb = Debrid()
        candidates = [
            {'hash': 'h_non_tier3', 'magnet': 'm0', 'seeders': 999, 'relevance': 80},
            {'hash': 'h1', 'magnet': 'm1', 'seeders': 50, 'relevance': 150},
            {'hash': 'h2', 'magnet': 'm2', 'seeders': 40, 'relevance': 140},
            {'hash': 'h3', 'magnet': 'm3', 'seeders': 30, 'relevance': 145},
            {'hash': 'h4', 'magnet': 'm4', 'seeders': 20, 'relevance': 160},
        ]
        probed_magnets = []

        def _fake_probe(magnet):
            probed_magnets.append(magnet)
            return magnet == 'm2'

        fake_client = MagicMock()
        fake_client.probe_instant_cache.side_effect = _fake_probe

        with patch('resources.lib.debrid.real_debrid.RealDebrid', return_value=fake_client), \
             patch('resources.lib.debrid.debrid_cache.set_cached_hashes') as mock_set_cache:
            hits = deb.lazy_probe_cached_torrents('realdebrid', candidates, max_candidates=3, max_total_s=6.0)
            self.assertEqual(hits, {'h2'})
            # Only top-3 by seeders among Tier-3 (>= 140) are probed; h_non_tier3 and h4 (lowest seeders) skipped
            self.assertEqual(probed_magnets, ['m1', 'm2', 'm3'])
            # Must persist ONLY positive hit ('h2', 'True'), never negative misses
            mock_set_cache.assert_called_once_with([('h2', 'True')], 'rd')

        # Timeout cap edge: clock jumps past 6.0s after 1st candidate -> stops early
        probed_timed = []
        fake_client2 = MagicMock()
        fake_client2.probe_instant_cache.side_effect = lambda m: (probed_timed.append(m) or False)
        clock = iter([1000.0, 1000.5, 1007.0, 1007.1])
        with patch('resources.lib.debrid.real_debrid.RealDebrid', return_value=fake_client2), \
             patch('resources.lib.debrid.time.monotonic', side_effect=lambda: next(clock, 1008.0)):
            hits2 = deb.lazy_probe_cached_torrents('realdebrid', candidates, max_candidates=3, max_total_s=6.0)
            self.assertEqual(hits2, set())
            self.assertEqual(probed_timed, ['m1'])

    def test_ws4_negative_pm_tb_ad_quota_guard_preserves_healthy_and_prunes_error(self):
        """Negative: PM/TB/AD prune errored transfers when saturated and preserve healthy items cleanly."""
        from resources.lib.debrid.premiumize import Premiumize
        from resources.lib.debrid.torbox import TorBox
        from resources.lib.debrid.all_debrid import AllDebrid

        pm = Premiumize()
        with patch.object(pm, 'transfer_list', return_value=[{'id': 'p1', 'status': 'error'}]), \
             patch.object(pm, 'get_storage_info', return_value={}), \
             patch.object(pm, 'delete_torrent', return_value=True) as pm_del:
            res_pm = pm.ensure_cloud_capacity(max_active_slots=1)
            self.assertEqual(res_pm['pruned'], 1)
            pm_del.assert_called_once_with('p1')

        tb = TorBox()
        with patch.object(tb, 'list_torrents', return_value=[{'id': 'tb1', 'download_state': 'error'}]), \
             patch.object(tb, 'delete_torrent', return_value=True) as tb_del:
            res_tb = tb.ensure_cloud_capacity(max_active_slots=1)
            self.assertEqual(res_tb['pruned'], 1)
            tb_del.assert_called_once_with('tb1')

        ad = AllDebrid()
        ad_resp = MagicMock(ok=True)
        ad_resp.json.return_value = {'data': {'magnets': [{'id': 'ad1', 'statusCode': 7}]}}
        with patch.object(ad, '_request_with_backoff', return_value=ad_resp), \
             patch.object(ad, 'delete_magnet', return_value=True) as ad_del:
            res_ad = ad.ensure_cloud_capacity(max_active_slots=1)
            self.assertEqual(res_ad['pruned'], 1)
            ad_del.assert_called_once_with('ad1')


class TestWS5SubtitleCalibrationAndProfile(unittest.TestCase):
    """WS-5: Multi-boundary chapter-aligned sub calibration, schema migration, OSD path & strict XML."""

    def test_ws5_happy_chapter_alignment_multi_boundary_and_shift_clamping(self):
        """Happy + Edge: Detects -5000ms shift on corroborated OP gap and clamps early cues at 00:00:00."""
        from resources.lib.subtitles.download import (
            detect_chapter_aligned_subtitle_offset_ms,
            shift_subtitle_timestamps,
        )
        # Video markers: OP at 90s..180s
        markers = [{'type': 'intro', 'start': 90.0, 'end': 180.0}]
        # Subs come from BD +5s shifted ahead of broadcast chapters -> dialogue ends at 95s, resumes at 185s
        srt = (
            "1\n00:00:03,000 --> 00:00:06,000\nOpening line\n\n"
            "2\n00:01:32,000 --> 00:01:35,000\nPre OP dialogue ends at 95s\n\n"
            "3\n00:03:05,000 --> 00:03:08,500\nPost OP dialogue resumes at 185s\n"
        )
        offset_ms = detect_chapter_aligned_subtitle_offset_ms(srt, '.srt', scene_markers=markers)
        self.assertEqual(offset_ms, -5000)

        shifted = shift_subtitle_timestamps(srt, '.srt', offset_ms)
        # Cue 1 starts at 3s -> shifted -5s must clamp at 00:00:00,000 instead of negative timestamp
        self.assertIn('00:00:00,000 --> 00:00:01,000', shifted)
        self.assertIn('00:03:00,000 --> 00:03:03,500', shifted)

    def test_ws5_negative_rejects_uncorroborated_post_op_title_card_and_out_of_bounds(self):
        """Negative: Single-boundary match (post-OP title card false positive) or <3s / >12s shift returns 0."""
        from resources.lib.subtitles.download import detect_chapter_aligned_subtitle_offset_ms

        markers = [{'type': 'intro', 'start': 90.0, 'end': 180.0}]
        # Pre-OP ends cleanly at 90s (NOT 95s), post-OP dialogue delayed by +5s title card to 185s -> must return 0
        title_card_srt = (
            "1\n00:01:26,000 --> 00:01:30,000\nCold open ends at exact 90s\n\n"
            "2\n00:03:05,000 --> 00:03:08,000\nDelayed by title card at 185s\n\n"
            "3\n00:03:10,000 --> 00:03:12,000\nNext line\n"
        )
        self.assertEqual(detect_chapter_aligned_subtitle_offset_ms(title_card_srt, '.srt', scene_markers=markers), 0)

        # Out-of-bounds shift (+20s > +-12s cap) must be rejected cleanly
        far_srt = (
            "1\n00:01:46,000 --> 00:01:50,000\nPre OP at 110s\n\n"
            "2\n00:03:20,000 --> 00:03:23,000\nPost OP at 200s\n\n"
            "3\n00:03:25,000 --> 00:03:28,000\nNext\n"
        )
        self.assertEqual(detect_chapter_aligned_subtitle_offset_ms(far_srt, '.srt', scene_markers=markers), 0)

        # Signs/OP styles in ASS must be ignored when scanning dialogue cues
        ass_signs = (
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            "Dialogue: 0,0:00:10.00,0:00:15.00,Signs,,0,0,0,,Title Sign\n"
            "Dialogue: 0,0:01:31.00,0:01:35.00,Default,,0,0,0,,Pre OP line\n"
            "Dialogue: 0,0:03:05.00,0:03:09.00,Default,,0,0,0,,Post OP line\n"
            "Dialogue: 0,0:03:12.00,0:03:15.00,Default,,0,0,0,,Third line\n"
        )
        self.assertEqual(detect_chapter_aligned_subtitle_offset_ms(ass_signs, '.ass', scene_markers=markers), -5000)

    def test_ws5_db_migration_persistence_osd_subtitle_service_and_strict_series_profile_xml(self):
        """DB Schema 1.0.16 migration + sub_offset_ms persistence + SeriesProfile 10-row Kodi 22 strict XML + OSD service."""
        database_sync.SyncDatabase()._ensure_column_migrations()
        with database.SQL(control.malSyncDB) as cur:
            cur.execute('PRAGMA table_info(series_overrides)')
            cols = {r['name'] if isinstance(r, dict) else r[1] for r in cur.fetchall()}
        self.assertIn('sub_offset_ms', cols)

        # Round-trip sub_offset_ms via set/get_series_override
        self.assertTrue(database.set_series_override(52991, sub_offset_ms=-2500))
        ov = database.get_series_override(52991)
        self.assertEqual(ov['sub_offset_ms'], -2500)
        database.delete_series_override(52991)

        # Strict KodiProfile('22') skin validation on 9-row SeriesProfileDialog (with new sub_offset_ms row)
        from resources.lib.windows.series_profile import SeriesProfileDialog, _FIELD_SPECS
        with KodiProfile('22', strict_skin_controls=True):
            dlg = SeriesProfileDialog(
                'series_profile.xml',
                control.ADDON_PATH,
                mal_id=52991,
            )
            self.assertEqual(len(_FIELD_SPECS), 9)
            self.assertEqual(_FIELD_SPECS[-1]['key'], 'sub_offset_ms')
            dlg.values['sub_offset_ms'] = 1500
            badge, is_ovr = dlg._format_value_badge(_FIELD_SPECS[-1])
            self.assertTrue(is_ovr)
            self.assertIn('+1500ms', badge)
            with patch('resources.lib.ui.control.select_dialog', return_value=4):
                dlg.edit_field(idx=8)
            self.assertEqual(dlg.values['sub_offset_ms'], 1750)
            dlg.close()
            del dlg

        # Verify service.subtitles.otaku.rpdev handle_request(action=download) picks up download_subtitle output cleanly
        import importlib.util
        import json
        import urllib.parse
        from resources.lib import subtitles as plugin_subtitles
        sub_svc_file = os.path.abspath(os.path.join(control.ADDON_PATH, '..', 'service.subtitles.otaku.rpdev', 'service.py'))
        spec = importlib.util.spec_from_file_location('otaku_sub_service_ws5_test', sub_svc_file)
        sub_svc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sub_svc)
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                out_srt = os.path.join(tmpdir, 'shifted.srt')
                with open(out_srt, 'w', encoding='utf-8') as f:
                    f.write("1\n00:00:05,000 --> 00:00:07,000\nAligned line\n")
                payload = urllib.parse.quote_plus(json.dumps({
                    'service_name': 'opensubtitles', 'display_name': 'OpenSubtitles',
                    'name': 'ep1.srt', 'lang': 'English', 'lang_code': 'en',
                }))
                with patch.object(plugin_subtitles, 'get_subtitles_settings', return_value={'subtitles.enabled': True, 'subtitles.auto_calibrate_chapters': False}), \
                     patch.object(plugin_subtitles, 'get_meta_from_player', return_value=MagicMock(mal_id=52991)), \
                     patch.object(plugin_subtitles, 'download_subtitle', return_value=out_srt) as mock_dl, \
                     patch.object(sub_svc, '_get_service_temp_dir', return_value=tmpdir), \
                     patch.object(sub_svc.xbmcplugin, 'addDirectoryItem') as mock_add_dir, \
                     patch.object(sub_svc.xbmcplugin, 'endOfDirectory'):
                    emitted = sub_svc.handle_request(7, f"?action=download&payload={payload}")
                    self.assertEqual(emitted, 1)
                    mock_add_dir.assert_called_once()
                    mock_dl.assert_called_once()
        finally:
            sys.modules.pop('otaku_sub_service_ws5_test', None)


if __name__ == '__main__':
    unittest.main()
