"""Unit tests for WS-8 telemetry markers (control.log_metric), audit_onn_logs.py rollups & WS-7 asset audit."""
# -*- coding: utf-8 -*-

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from resources.lib.ui import control
from scripts import audit_onn_logs, optimize_addon_assets


class TestTelemetryAndLogAuditor(unittest.TestCase):
    """Exercise control.log_metric sanitization, OTAKU_METRIC parsing, rollup metrics, and --metrics-out."""

    def test_control_log_metric_sanitizes_newlines_and_whitespace(self):
        logged = []
        with patch('resources.lib.ui.control.log', side_effect=lambda msg, level='info': logged.append((msg, level))):
            control.log_metric(
                'scrape summary\nbad',
                level='info',
                provider='nyaa si',
                elapsed_ms=1234,
                cached_torrents=0,
                ok=True,
                bad_val='line1\nline2\r\nline3',
            )
        self.assertEqual(len(logged), 1)
        msg, lvl = logged[0]
        self.assertEqual(lvl, 'info')
        self.assertNotIn('\n', msg)
        self.assertNotIn('\r', msg)
        self.assertTrue(msg.startswith('OTAKU_METRIC event=scrape_summary_bad'))
        parsed = audit_onn_logs.parse_otaku_metric_line(msg)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['event'], 'scrape_summary_bad')
        self.assertEqual(parsed['elapsed_ms'], 1234)
        self.assertEqual(parsed['cached_torrents'], 0)
        self.assertIs(parsed['ok'], True)

    def test_analyze_log_text_and_metrics_out_rollup(self):
        sample_log = "\n".join([
            "2026-11-26 10:00:00 T:1 info <general>: plugin.video.otaku.rpdev v6.0.7 started",
            "2026-11-26 10:00:01 T:1 info <general>: OTAKU RPDEV (1): OTAKU_METRIC event=scrape_summary cached_torrents=0 elapsed_ms=4200 embed_grace_s=4",
            "2026-11-26 10:00:02 T:1 info <general>: OTAKU RPDEV (1): OTAKU_METRIC event=scrape_summary cached_torrents=3 elapsed_ms=1800 embed_grace_s=0",
            "2026-11-26 10:00:03 T:1 info <general>: OTAKU RPDEV (1): OTAKU_METRIC event=zero_wait_hit attempts=1 mal_id=52991 provider=nyaa",
            "2026-11-26 10:00:04 T:1 warning <general>: OTAKU RPDEV (1): OTAKU_METRIC event=zero_wait_miss mal_id=100 pruned=2",
            "2026-11-26 10:00:05 T:1 info <general>: OTAKU RPDEV (1): OTAKU_METRIC event=failover attempt=1 provider=animetosho reason=curl56 success=true",
            "2026-11-26 10:00:06 T:1 warning <general>: OTAKU RPDEV (1): OTAKU_METRIC event=memory_guard action=throttle_gc_trim rss_mb=920",
            "2026-11-26 10:00:07 T:1 info <general>: OTAKU RPDEV (1): OTAKU_METRIC event=memory_guard action=hysteresis_cleared rss_mb=680",
            "2026-11-26 10:00:08 T:1 warning <general>: OTAKU RPDEV (1): OTAKU_METRIC event=dns_gate state=tripped hosts=2 ttl_s=15",
            "2026-11-26 10:00:09 T:1 info <general>: OTAKU RPDEV (1): OTAKU_METRIC event=dns_gate state=cleared reason=ttl_expired",
            "2026-11-26 10:00:10 T:1 info <general>: OTAKU RPDEV (1): OTAKU_METRIC event=debrid_quota_prune provider=realdebrid pruned_count=3",
            "2026-11-26 10:00:11 T:1 info <general>: OTAKU RPDEV (1): OTAKU_METRIC event=lazy_cache_probe hits=2 probed=3 provider=realdebrid",
            "2026-11-26 10:00:12 T:1 info <general>: OTAKU RPDEV (1): OTAKU_METRIC event=sub_calibrate mal_id=52991 offset_ms=-5000",
        ]) + "\n"

        report = audit_onn_logs.analyze_log_text(sample_log, requested_offset=0)
        mr = report['metrics_rollup']
        self.assertEqual(mr['total_metric_events'], 12)
        self.assertEqual(mr['scrape_summary']['count'], 2)
        self.assertEqual(mr['scrape_summary']['avg_elapsed_ms'], 3000.0)
        self.assertEqual(mr['scrape_summary']['zero_cached_scrapes'], 1)
        self.assertEqual(mr['scrape_summary']['embed_grace_triggers'], 1)
        self.assertEqual(mr['zero_wait'], {'hits': 1, 'misses': 1, 'hit_rate_pct': 50.0})
        self.assertEqual(mr['failover'], {'success': 1, 'failed': 0})
        self.assertEqual(mr['memory_guard'], {'triggers': 1, 'recoveries': 1})
        self.assertEqual(mr['dns_gate'], {'tripped': 1, 'cleared': 1})
        self.assertEqual(mr['debrid_quota_prune']['total_pruned'], 3)
        self.assertEqual(mr['lazy_cache_probe']['total_hits'], 2)
        self.assertEqual(mr['sub_calibrate']['events'], 1)

        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, 'onn.log')
            metrics_jsonl = os.path.join(tmpdir, 'metrics.jsonl')
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(sample_log)
            rc = audit_onn_logs.main(['--input', log_file, '--offset', '0', '--metrics-out', metrics_jsonl])
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.isfile(metrics_jsonl))
            with open(metrics_jsonl, 'r', encoding='utf-8') as mf:
                rows = [json.loads(ln) for ln in mf if ln.strip()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['metrics_rollup']['total_metric_events'], 12)

    def test_ws7_asset_audit_scans_both_addons_cleanly(self):
        scan = optimize_addon_assets.scan_image_assets()
        self.assertGreaterEqual(scan['total_png_files'], 1400)
        self.assertIn(os.path.join('context.otaku.rpdev', 'resources', 'images'), scan['by_root'])
        self.assertIn(os.path.join('plugin.video.otaku.rpdev', 'resources', 'images'), scan['by_root'])
        self.assertEqual(len(scan['icon_themes']), 8)
        opt_res = optimize_addon_assets.optimize_png_files(scan['_full_paths'][:2], apply=False)
        self.assertEqual(opt_res['mode'], 'audit_only')
        self.assertEqual(opt_res['optimized_files'], 0)


if __name__ == '__main__':
    unittest.main()
