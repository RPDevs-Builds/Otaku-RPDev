"""
Unit tests for scripts/audit_onn_logs.py (read-only ONN log auditor).
"""

import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_TEST_DIR, '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts import audit_onn_logs  # noqa: E402


class _FakeHTTPResponse:
    def __init__(self, body_bytes, seek_offset=None):
        self._buf = io.BytesIO(body_bytes)
        self.headers = {}
        if seek_offset is not None:
            self.headers['X-Seek-Offset'] = str(seek_offset)

    def read(self):
        return self._buf.read()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self._buf.close()
        return False


class TestAuditOnnLogs(unittest.TestCase):

    def test_read_concerns_offset_parses_real_concerns_md(self):
        concerns_path = os.path.join(_REPO_ROOT, 'docs', 'CONCERNS.md')
        offset = audit_onn_logs.read_concerns_offset(concerns_path)
        with open(concerns_path, 'r', encoding='utf-8') as f:
            text = f.read()
        match = audit_onn_logs.CURSOR_RE.search(text) or audit_onn_logs.CURSOR_FALLBACK_RE.search(text)
        self.assertIsNotNone(match)
        expected_offset = int(match.group(1))
        self.assertGreaterEqual(offset, 0)
        self.assertEqual(offset, expected_offset)

        with tempfile.TemporaryDirectory() as tmpdir:
            sample = os.path.join(tmpdir, 'CONCERNS_SAMPLE.md')
            with open(sample, 'w', encoding='utf-8') as f:
                f.write('| **Next review offset** | **433385** |\n')
            self.assertEqual(audit_onn_logs.read_concerns_offset(sample), 433385)

    def test_offline_fixture_classification_and_noise_filtering(self):
        fixture_path = os.path.join(_REPO_ROOT, 'tests', 'fixtures', 'onn_kodi_log_sample.txt')
        concerns_path = os.path.join(_REPO_ROOT, 'docs', 'CONCERNS.md')
        expected_offset = audit_onn_logs.read_concerns_offset(concerns_path)

        with tempfile.TemporaryDirectory() as tmpdir:
            out_json = os.path.join(tmpdir, 'audit_report.json')
            rc = audit_onn_logs.main([
                '--concerns', concerns_path,
                '--input', fixture_path,
                '--json', out_json,
            ])
            self.assertEqual(rc, 0)
            with open(out_json, 'r', encoding='utf-8') as f:
                report = json.load(f)

        self.assertEqual(report['status'], 'ok')
        self.assertEqual(report['requested_offset'], expected_offset)
        self.assertEqual(report['addon_versions'].get('plugin.video.otaku.rpdev'), '6.2.19')
        self.assertEqual(report['counts']['otaku_errors'], 1)
        self.assertEqual(report['counts']['otaku_warnings'], 1)
        self.assertEqual(report['counts']['non_otaku_noise_filtered'], 3)
        self.assertEqual(report['counts']['zero_wait'], 3)
        self.assertEqual(report['counts']['subtitles'], 3)
        self.assertEqual(report['counts']['clean_settings'], 1)
        self.assertEqual(report['counts']['concerns']['C-06'], 1)
        self.assertEqual(report['counts']['concerns']['C-11'], 1)
        self.assertEqual(report['counts']['concerns']['C-14'], 1)
        self.assertEqual(report['counts']['concerns']['C-34'], 1)
        self.assertEqual(report['counts']['concerns']['C-35'], 1)

    def test_mocked_http_get_uses_get_method_timeout_and_detects_rotation(self):
        captured = {}
        rotated_log = b"Starting Kodi (22.0-RC2)\n2026-11-21 06:00:00 T:1 info <general>: OTAKU RPDEV (1): clean_settings ok\n"

        def _fake_urlopen(req, timeout=None):
            captured['url'] = req.full_url
            captured['method'] = req.get_method()
            captured['timeout'] = timeout
            return _FakeHTTPResponse(rotated_log, seek_offset=0)

        with patch('scripts.audit_onn_logs.urllib.request.urlopen', side_effect=_fake_urlopen):
            raw, seek = audit_onn_logs.fetch_log_from_url('http://10.13.0.16:8081/tail', offset=433385, timeout=7.5)

        self.assertEqual(captured['method'], 'GET')
        self.assertEqual(captured['url'], 'http://10.13.0.16:8081/tail?offset=433385')
        self.assertEqual(captured['timeout'], 7.5)
        self.assertEqual(seek, 0)

        report = audit_onn_logs.analyze_log_text(
            raw.decode('utf-8'),
            requested_offset=433385,
            x_seek_offset=seek,
            raw_bytes_len=len(raw),
        )
        self.assertTrue(report['rotated'])
        self.assertEqual(report['next_offset'], len(rotated_log))
        self.assertEqual(report['counts']['clean_settings'], 1)

    def test_json_stdout_and_unreachable_url_handling(self):
        buf = io.StringIO()
        fixture_path = os.path.join(_REPO_ROOT, 'tests', 'fixtures', 'onn_kodi_log_sample.txt')
        with patch('sys.stdout', buf):
            rc = audit_onn_logs.main(['--offset', '0', '--input', fixture_path, '--json'])
        self.assertEqual(rc, 0)
        parsed = json.loads(buf.getvalue())
        self.assertEqual(parsed['status'], 'ok')
        self.assertEqual(parsed['requested_offset'], 0)

        err_buf = io.StringIO()
        with patch('scripts.audit_onn_logs.urllib.request.urlopen', side_effect=OSError('Connection refused')), \
             patch('sys.stdout', err_buf):
            rc_err = audit_onn_logs.main(['--offset', '100', '--url', 'http://10.13.0.16:8081/tail', '--json'])
        self.assertEqual(rc_err, 1)
        err_json = json.loads(err_buf.getvalue())
        self.assertEqual(err_json['status'], 'error')
        self.assertIn('Connection refused', err_json['error'])

    def test_corrupted_and_missing_concerns_emit_json_error_and_stderr(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_concerns = os.path.join(tmpdir, 'bad_concerns.md')
            missing_concerns = os.path.join(tmpdir, 'nonexistent_concerns.md')
            sample_log = os.path.join(tmpdir, 'sample.log')
            with open(bad_concerns, 'w', encoding='utf-8') as f:
                f.write('# Corrupted concerns file without cursor\n')
            with open(sample_log, 'w', encoding='utf-8') as f:
                f.write('line1\n')

            for concerns_arg, mode_args in (
                (bad_concerns, ['--input', sample_log]),
                (bad_concerns, ['--url', 'http://127.0.0.1:9999/tail']),
                (missing_concerns, ['--input', sample_log]),
                (missing_concerns, ['--url', 'http://127.0.0.1:9999/tail']),
            ):
                out_buf = io.StringIO()
                with patch('sys.stdout', out_buf):
                    rc = audit_onn_logs.main(['--concerns', concerns_arg, *mode_args, '--json'])
                self.assertEqual(rc, 1)
                payload = json.loads(out_buf.getvalue())
                self.assertEqual(payload['status'], 'error')
                self.assertEqual(payload['requested_offset'], 0)
                self.assertTrue(payload['error'])

            stderr_buf = io.StringIO()
            with patch('sys.stderr', stderr_buf):
                rc_txt = audit_onn_logs.main(['--concerns', missing_concerns, '--input', sample_log])
            self.assertEqual(rc_txt, 1)
            self.assertIn('ERROR:', stderr_buf.getvalue())

    def test_negative_offset_rejected_in_cli_and_library_calls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sample_log = os.path.join(tmpdir, 'sample.log')
            with open(sample_log, 'w', encoding='utf-8') as f:
                f.write('line1\n')

            out_buf = io.StringIO()
            with patch('sys.stdout', out_buf):
                rc = audit_onn_logs.main(['--input', sample_log, '--offset', '-5', '--json'])
            self.assertEqual(rc, 1)
            payload = json.loads(out_buf.getvalue())
            self.assertEqual(payload['status'], 'error')
            self.assertEqual(payload['requested_offset'], -5)
            self.assertIn('Offset must be >= 0', payload['error'])

            stderr_buf = io.StringIO()
            with patch('sys.stderr', stderr_buf):
                rc_txt = audit_onn_logs.main(['--url', 'http://127.0.0.1:9999/tail', '--offset', '-5'])
            self.assertEqual(rc_txt, 1)
            self.assertIn('ERROR:', stderr_buf.getvalue())
            self.assertIn('Offset must be >= 0', stderr_buf.getvalue())

            with self.assertRaises(ValueError):
                audit_onn_logs.fetch_log_from_file(sample_log, offset=-5)
            with self.assertRaises(ValueError):
                audit_onn_logs.fetch_log_from_url('http://127.0.0.1:8081/tail', offset=-1)
            with self.assertRaises(ValueError):
                audit_onn_logs.analyze_log_text('line1\n', requested_offset=-1)

    def test_metrics_out_appends_longitudinal_jsonl_record(self):
        fixture_path = os.path.join(_REPO_ROOT, 'tests', 'fixtures', 'onn_kodi_log_sample.txt')
        concerns_path = os.path.join(_REPO_ROOT, 'docs', 'CONCERNS.md')

        with tempfile.TemporaryDirectory() as tmpdir:
            metrics_path = os.path.join(tmpdir, 'telemetry', 'onn_metrics.jsonl')
            rc1 = audit_onn_logs.main(['--concerns', concerns_path, '--input', fixture_path, '--metrics-out', metrics_path])
            rc2 = audit_onn_logs.main(['--concerns', concerns_path, '--input', fixture_path, '--metrics-out', metrics_path])
            self.assertEqual(rc1, 0)
            self.assertEqual(rc2, 0)

            with open(metrics_path, 'r', encoding='utf-8') as f:
                lines = [ln.strip() for ln in f if ln.strip()]
            self.assertEqual(len(lines), 2)
            rec = json.loads(lines[0])
            self.assertIn('timestamp_utc', rec)
            self.assertEqual(rec['addon_versions'].get('plugin.video.otaku.rpdev'), '6.2.19')
            self.assertEqual(rec['counts']['zero_wait'], 3)
            self.assertEqual(rec['counts']['concerns']['C-14'], 1)

    def test_rotation_eof_x_seek_offset_and_bom_banner_not_double_counted(self):
        rotated_bom_log = (
            "\ufeff2026-11-21 20:25:51.609 T:8128 info <general>: "
            "-----------------------------------------------------------------------\n"
            "2026-11-21 20:25:51.609 T:8128 info <general>: Starting Kodi (22.0-RC2)\n"
            "2026-11-21 20:26:07.357 T:8155 info <general>: OTAKU RPDEV (0): clean_settings ok\n"
        )
        raw_bytes = rotated_bom_log.encode('utf-8')
        # ONN /tail server sets X-Seek-Offset to EOF length (== len(raw_bytes)) when rotated
        report = audit_onn_logs.analyze_log_text(
            rotated_bom_log,
            requested_offset=309579,
            x_seek_offset=len(raw_bytes),
            raw_bytes_len=len(raw_bytes),
        )
        self.assertTrue(report['rotated'])
        self.assertEqual(report['next_offset'], len(raw_bytes))

        # Even if rotated file already grew larger than the prior cursor, line-2 banner still flags rotation
        report_grown = audit_onn_logs.analyze_log_text(
            rotated_bom_log,
            requested_offset=50,
            x_seek_offset=len(raw_bytes),
            raw_bytes_len=len(raw_bytes),
        )
        self.assertTrue(report_grown['rotated'])
        self.assertEqual(report_grown['next_offset'], len(raw_bytes))

    def test_multiline_python_traceback_attributed_by_addon_path(self):
        log_text = (
            "2026-11-21 21:40:00.163 T:8163 error <general>: EXCEPTION Thrown (PythonToCppException) : "
            "-->Python callback/script returned the following error<--\n"
            "                                            Traceback (most recent call last):\n"
            "                                              File \"/storage/addons/service.upnext/resources/lib/player.py\", line 82\n"
            "                                            AttributeError: read-only UpNextPlayer.stop_count\n"
            "                                            -->End of Python script error report<--\n"
            "2026-11-21 21:40:01.000 T:8164 error <general>: EXCEPTION Thrown (PythonToCppException) : "
            "-->Python callback/script returned the following error<--\n"
            "                                            Traceback (most recent call last):\n"
            "                                              File \"/storage/addons/script.random.thirdparty/default.py\", line 12\n"
            "                                            RuntimeError: boom\n"
            "                                            -->End of Python script error report<--\n"
            "2026-11-21 21:41:00.000 T:9000 error <general>: EXCEPTION Thrown (PythonToCppException) : "
            "-->Python callback/script returned the following error<--\n"
            "                                            Traceback (most recent call last):\n"
            "                                              File \"/storage/addons/plugin.video.otaku.rpdev/resources/lib/Main.py\", line 99\n"
            "                                            ValueError: otaku bug\n"
            "                                            -->End of Python script error report<--\n"
        )
        report = audit_onn_logs.analyze_log_text(log_text, requested_offset=0)
        self.assertEqual(report['counts']['otaku_errors'], 2)
        self.assertEqual(report['counts']['non_otaku_noise_filtered'], 4)
        self.assertEqual(len(report['samples']['otaku_errors']), 2)

    def test_session_start_header_mismatch_resets_cursor_when_rotated_log_exceeds_old_offset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            concerns_file = os.path.join(tmpdir, 'CONCERNS.md')
            with open(concerns_file, 'w', encoding='utf-8') as f:
                f.write(
                    "| Field | Value |\n|---|---|\n"
                    "| Log session started | 2026-11-21 20:25:51 (previous session) |\n"
                    "| **Next review offset** | **100** |\n"
                )
            rotated_log_path = os.path.join(tmpdir, 'kodi.log')
            rotated_content = (
                "2026-11-23 09:25:27.498 T:23836 info <general>: -----------------------------------------------------------------------\n"
                "2026-11-23 09:25:27.499 T:23836 info <general>: Starting Kodi (21.3)\n"
                "2026-11-23 09:25:33.000 T:23850 info <general>: OTAKU RPDEV (0): clean_settings: Settings file clean\n"
                "2026-11-23 12:37:46.000 T:24000 info <general>: OTAKU RPDEV (1): Playback: Zero-Wait Pre-Resolved Stream Hit for 51711 Ep 2!\n"
            )
            with open(rotated_log_path, 'w', encoding='utf-8') as f:
                f.write(rotated_content)

            out_json = os.path.join(tmpdir, 'report.json')
            rc = audit_onn_logs.main(['--concerns', concerns_file, '--input', rotated_log_path, '--json', out_json])
            self.assertEqual(rc, 0)
            with open(out_json, 'r', encoding='utf-8') as f:
                report = json.load(f)
            self.assertTrue(report['rotated'])
            self.assertEqual(report['counts']['clean_settings'], 1)
            self.assertEqual(report['counts']['zero_wait'], 1)
            self.assertEqual(report['next_offset'], len(rotated_content.encode('utf-8')))


if __name__ == '__main__':
    unittest.main()
