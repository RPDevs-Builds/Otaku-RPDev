# -*- coding: utf-8 -*-
"""
suite_sp.py — Opaque-Box E2E Tests for SP-02 & SP-03 (v6.3.0)
==============================================================
SP-02: Zero-Wait C-34 resolve_silent() candidate pruning + C-35 wlf_auth disposal/idle guard
SP-03: Read-only ONN log auditor (scripts/audit_onn_logs.py) + leak/quality hygiene
"""

import ast
import json
import os
import py_compile
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from tests.e2e_v630 import e2e_helpers
from tests.e2e_v630.e2e_helpers import (
    E2EHermeticEnv,
    E2EMockServer,
    REPO_ROOT,
    assert_repo_clean_of_leaks,
    feature,
    invoke_plugin_route,
    run_cli_script,
    send_http_response,
    tier,
)
from tests.lint import test_suite_quality


def _make_direct_source(url, provider='MockDirect'):
    return {
        'type': 'direct',
        'provider': provider,
        'release_title': f'[{provider}] Frieren - 02 [1080p]',
        'hash': url,
        'quality': 3,
        'info': ['1080p', 'SUB'],
        'size': '350 MB',
        'subs': [],
    }


def _seed_show_for_play(mal_id='52991', episode='2'):
    from resources.lib.ui import database
    kodi_meta = {
        'name': 'Sousou no Frieren',
        'title_userPreferred': 'Sousou no Frieren',
        'episodes': 28,
        'mediatype': 'tvshow',
        'poster': '',
        'plot': 'Test plot',
    }
    database.update_show(mal_id, database.dumps(kodi_meta))
    database.update_show_meta(mal_id, {'mal_id': mal_id}, {'poster': '', 'fanart': '', 'thumb': ''})


class TestSP02ZeroWaitAndWlfAuth(unittest.TestCase):
    """SP-02: C-34 resolve_silent() pruning & C-35 wlf_auth disposal/idle guard."""

    @tier(1)
    @feature('SP-02')
    def test_sp02_t1_resolve_silent_prunes_dead_lead_and_resolves_healthy_second(self):
        with E2EHermeticEnv('22'), E2EMockServer() as srv:
            from resources.lib.ui import database, domains
            from resources.lib.windows.resolver import resolve_silent

            dead_url = f"http://localhost:{srv.port}/dead_404.mkv"
            good_url = f"http://127.0.0.1:{srv.port}/video.mkv"
            sources = [
                _make_direct_source(dead_url, provider='DeadHost'),
                _make_direct_source(good_url, provider='GoodHost'),
            ]
            database.set_episode_sources('52991', '2', list(sources))

            resolved = resolve_silent(sources, episode='2', mal_id='52991')
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved['url'], good_url)
            self.assertEqual(resolved['source']['provider'], 'GoodHost')

            # Dead lead candidate was pruned in-place and in persisted SQLite cache
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0]['provider'], 'GoodHost')
            persisted = database.get_episode_sources('52991', '2')
            self.assertEqual(len(persisted), 1)
            self.assertEqual(persisted[0]['provider'], 'GoodHost')
            self.assertFalse(domains.is_mirror_healthy(f"http://localhost:{srv.port}/"))

    @tier(1)
    @feature('SP-02')
    def test_sp02_t1_zero_wait_prescrape_and_play_route_consumes_pruned_second(self):
        with E2EHermeticEnv('22') as env, E2EMockServer() as srv:
            from resources.lib.ui import control, database, player
            from resources.lib import MetaBrowser

            _seed_show_for_play('52991', '2')
            control.setBool('general.smartplay', True)
            control.setBool('smartplay.prescrape', True)
            control.setBool('smartplay.preresolve', True)
            control.setInt('general.playstyle.episode', 0)

            dead_url = f"http://localhost:{srv.port}/dead_404.mkv"
            good_url = f"http://127.0.0.1:{srv.port}/video.mkv"
            candidates = [
                _make_direct_source(dead_url, provider='DeadLead'),
                _make_direct_source(good_url, provider='HealthyBackup'),
            ]

            wp = player.WatchlistPlayer()
            wp.mal_id = '52991'
            wp.episode = 1
            wp.episodes = [1, 2, 3]
            wp.media_type = 'tv'

            with patch.object(MetaBrowser, 'get_sources', return_value=list(candidates)):
                wp._trigger_background_prescrape()
                deadline = time.monotonic() + 3.0
                while time.monotonic() < deadline:
                    if control.playerWindow.getProperty('otaku.preResolved_url'):
                        break
                    time.sleep(0.02)

            self.assertEqual(control.playerWindow.getProperty('otaku.preResolved_url'), good_url)
            self.assertEqual(control.playerWindow.getProperty('otaku.preResolved_episode'), '2')

            with patch('resources.lib.windows.resolver.Resolver.doModal') as mock_res_modal, \
                 patch('resources.lib.ui.player.WatchlistPlayer.handle_player') as mock_handle_player:
                res = invoke_plugin_route('play/52991/2', handle=11)

            mock_res_modal.assert_not_called()
            mock_handle_player.assert_called_once()
            self.assertEqual(len(res['resolved_urls']), 1)
            self.assertTrue(res['resolved_urls'][0][1])
            self.assertEqual(res['resolved_urls'][0][2].getPath(), good_url)
            self.assertEqual(control.playerWindow.getProperty('otaku.preResolved_url'), '')
            self.assertIsInstance(env.root_dir, str)

    @tier(1)
    @feature('SP-02')
    def test_sp02_t1_resolve_silent_deprioritizes_cooldown_mirror(self):
        with E2EHermeticEnv('22'), E2EMockServer() as srv:
            from resources.lib.ui import domains
            from resources.lib.windows.resolver import resolve_silent

            cooldown_url = f"http://localhost:{srv.port}/video.mkv"
            healthy_url = f"http://127.0.0.1:{srv.port}/video.mkv"
            domains.mark_mirror_failure(f"http://localhost:{srv.port}/", cooldown=300)

            sources = [
                _make_direct_source(cooldown_url, provider='CooldownHost'),
                _make_direct_source(healthy_url, provider='FreshHost'),
            ]
            resolved = resolve_silent(sources, episode='1', mal_id='52991')
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved['url'], healthy_url)
            self.assertEqual(resolved['source']['provider'], 'FreshHost')

    @tier(1)
    @feature('SP-02')
    def test_sp02_t1_wlf_auth_idle_timeout_auto_closes_under_kodi22(self):
        with E2EHermeticEnv('22', strict_skin_controls=True):
            from resources.lib.windows.wlf_auth import WatchlistFlavorAuth
            dlg = WatchlistFlavorAuth('wlf_auth_mal.xml', e2e_helpers.ADDON_ROOT, flavor='mal', idle_timeout=0.05)
            closed_event = threading.Event()
            orig_close = dlg.close

            def _tracked_close():
                orig_close()
                closed_event.set()

            dlg.close = _tracked_close

            def _fake_domodal(self_win):
                self_win.onInit()
                closed_event.wait(timeout=1.5)

            with patch('xbmcgui.WindowXMLDialog.doModal', new=_fake_domodal):
                result = dlg.doModal()

            self.assertTrue(closed_event.is_set())
            self.assertFalse(result)
            self.assertIsNone(dlg._idle_thread)

    @tier(1)
    @feature('SP-02')
    def test_sp02_t1_watchlist_login_auth_dialog_disposes_and_calls_login(self):
        with E2EHermeticEnv('22', strict_skin_controls=True):
            from resources.lib.WatchlistFlavor import WatchlistFlavor
            from resources.lib.windows.base_window import BaseWindow

            def _approve_modal(self_win):
                self_win.authorized = True
                return True

            with patch('resources.lib.windows.wlf_auth.WatchlistFlavorAuth.doModal', new=_approve_modal), \
                 patch.object(WatchlistFlavor, 'login_request', return_value=True) as mock_login:
                res = invoke_plugin_route('watchlist_login/mal', params={'auth_dialog': 'true'}, handle=7)

            mock_login.assert_called_once_with('mal')
            self.assertEqual(len(list(BaseWindow._active_windows)), 0)
            self.assertTrue(any(args[0] == 7 for args in res['end_of_directory']))

    @tier(1)
    @feature('SP-02')
    def test_sp02_t1_wlf_auth_anilist_controls_persist_and_authorize(self):
        with E2EHermeticEnv('22', strict_skin_controls=True):
            from resources.lib.ui import control
            from resources.lib.windows.wlf_auth import WatchlistFlavorAuth

            dlg = WatchlistFlavorAuth('wlf_auth_anilist.xml', e2e_helpers.ADDON_ROOT, flavor='anilist', idle_timeout=5.0)
            dlg.getControl(1000).setText('e2e_anilist_user')
            dlg.getControl(1001).setText('anilist_tok_abcdef123456')

            def _click_authorize(self_win):
                self_win.onInit()
                self_win.onClick(1002)

            with patch('xbmcgui.WindowXMLDialog.doModal', new=_click_authorize):
                authorized = dlg.doModal()

            self.assertTrue(authorized)
            self.assertEqual(control.getSetting('anilist.username'), 'e2e_anilist_user')
            self.assertEqual(control.getSetting('anilist.token'), 'anilist_tok_abcdef123456')

    @tier(2)
    @feature('SP-02')
    def test_sp02_t2_resolve_silent_all_dead_clears_episode_sources(self):
        with E2EHermeticEnv('22'), E2EMockServer() as srv:
            from resources.lib.ui import control, database
            from resources.lib.windows.resolver import resolve_silent

            dead_sources = [
                _make_direct_source(f"http://127.0.0.1:{srv.port}/dead1.mkv", provider='Dead1'),
                _make_direct_source(f"http://127.0.0.1:{srv.port}/dead2.mkv", provider='Dead2'),
                _make_direct_source(f"http://127.0.0.1:{srv.port}/dead3.mkv", provider='Dead3'),
            ]
            database.set_episode_sources('52991', '5', list(dead_sources))
            control.playerWindow.clearProperty('otaku.preResolved_url')

            resolved = resolve_silent(dead_sources, episode='5', mal_id='52991')
            self.assertIsNone(resolved)
            self.assertEqual(dead_sources, [])
            self.assertIsNone(database.get_episode_sources('52991', '5'))
            self.assertEqual(control.playerWindow.getProperty('otaku.preResolved_url'), '')

    @tier(2)
    @feature('SP-02')
    def test_sp02_t2_resolve_silent_empty_and_malformed_candidates_safe(self):
        with E2EHermeticEnv('22'):
            from resources.lib.windows.resolver import resolve_silent

            self.assertIsNone(resolve_silent([], episode='1', mal_id=None))
            self.assertIsNone(resolve_silent(None, episode='1', mal_id='52991'))
            malformed = [None, {}, 'not_a_dict']
            self.assertIsNone(resolve_silent(malformed, episode='', mal_id=None))
            self.assertEqual(malformed, [])

    @tier(2)
    @feature('SP-02')
    def test_sp02_t2_get_auth_dialog_exception_still_closes_and_disposes(self):
        with E2EHermeticEnv('22', strict_skin_controls=True):
            from resources.lib import WatchlistIntegration
            from resources.lib.windows.base_window import BaseWindow

            close_calls = []

            def _boom(self_win):
                raise RuntimeError('simulated modal crash')

            def _track_close(self_win):
                close_calls.append(True)
                self_win._stop_idle_timer()

            with patch('resources.lib.windows.wlf_auth.WatchlistFlavorAuth.doModal', new=_boom), \
                 patch('resources.lib.windows.wlf_auth.WatchlistFlavorAuth.close', new=_track_close):
                with self.assertRaises(RuntimeError):
                    WatchlistIntegration.get_auth_dialog('mal')

            self.assertGreaterEqual(len(close_calls), 1)
            self.assertEqual(len(list(BaseWindow._active_windows)), 0)

    @tier(2)
    @feature('SP-02')
    def test_sp02_t2_wlf_auth_monitor_abort_exits_watchdog_under_1s(self):
        with E2EHermeticEnv('22', strict_skin_controls=True):
            from resources.lib.ui import control
            from resources.lib.windows.wlf_auth import WatchlistFlavorAuth

            dlg = WatchlistFlavorAuth('wlf_auth_mal.xml', e2e_helpers.ADDON_ROOT, flavor='mal', idle_timeout=30.0)
            closed_event = threading.Event()
            orig_close = dlg.close

            def _tracked_close():
                orig_close()
                closed_event.set()

            dlg.close = _tracked_close

            def _abort_domodal(self_win):
                control.monitor._get_monitor().requestAbort()
                closed_event.wait(timeout=1.5)

            t0 = time.monotonic()
            with patch('xbmcgui.WindowXMLDialog.doModal', new=_abort_domodal):
                res = dlg.doModal()
            elapsed = time.monotonic() - t0

            self.assertTrue(closed_event.is_set())
            self.assertLess(elapsed, 1.0)
            self.assertFalse(res)

    @tier(2)
    @feature('SP-02')
    def test_sp02_t2_wlf_auth_back_actions_and_cancel_close_without_saving(self):
        for ver in ('21', '22'):
            with E2EHermeticEnv(ver, strict_skin_controls=True):
                from resources.lib.ui import control
                from resources.lib.windows.wlf_auth import WatchlistFlavorAuth

                control.setSetting('mal.authvar', '')
                for action_id in (9, 10, 92, 216):
                    dlg = WatchlistFlavorAuth('wlf_auth_mal.xml', e2e_helpers.ADDON_ROOT, flavor='mal', idle_timeout=10.0)
                    closed = []
                    orig_close = dlg.close
                    dlg.close = lambda d=dlg, oc=orig_close, c=closed: (c.append(action_id), oc())
                    mock_action = type('Action', (), {'getId': lambda _s, aid=action_id: aid})()
                    dlg.onAction(mock_action)
                    self.assertEqual(closed, [action_id])
                    self.assertFalse(dlg.authorized)

                dlg_cancel = WatchlistFlavorAuth('wlf_auth_mal.xml', e2e_helpers.ADDON_ROOT, flavor='mal', idle_timeout=10.0)
                dlg_cancel.getControl(1000).setText('should_not_save')
                with patch('xbmcgui.WindowXMLDialog.doModal', new=lambda s: s.onClick(1003)):
                    auth = dlg_cancel.doModal()
                self.assertFalse(auth)
                self.assertEqual(control.getSetting('mal.authvar'), '')

    @tier(2)
    @feature('SP-02')
    def test_sp02_t2_wlf_auth_empty_fields_trigger_validation_ok_dialog(self):
        with E2EHermeticEnv('22', strict_skin_controls=True) as env:
            from resources.lib.ui import control
            from resources.lib.windows.wlf_auth import WatchlistFlavorAuth

            control.setSetting('anilist.username', '')
            control.setSetting('anilist.token', '')
            dlg = WatchlistFlavorAuth('wlf_auth_anilist.xml', e2e_helpers.ADDON_ROOT, flavor='anilist', idle_timeout=10.0)
            dlg.getControl(1000).setText('   ')
            dlg.getControl(1001).setText('')

            with patch('xbmcgui.WindowXMLDialog.doModal', new=lambda s: s.onClick(1002)):
                auth = dlg.doModal()

            self.assertFalse(auth)
            self.assertEqual(control.getSetting('anilist.username'), '')
            self.assertEqual(control.getSetting('anilist.token'), '')
            self.assertEqual(len(env.dialog_capture.ok_dialogs), 1)
            self.assertIn('empty', env.dialog_capture.ok_dialogs[0]['message'].lower())


class TestSP03AuditOnnLogsAndHygiene(unittest.TestCase):
    """SP-03: Strictly read-only ONN log auditor & test/VFS leak hygiene."""

    @tier(1)
    @feature('SP-03')
    def test_sp03_t1_audit_onn_logs_classifies_signals_and_writes_json(self):
        fixture_log = (
            "2026-11-21 10:00:01.100 T:100 info <general>: OTAKU RPDEV (1): plugin.video.otaku.rpdev 6.3.0 initialized\n"
            "2026-11-21 10:00:02.100 T:100 info <general>: OTAKU RPDEV (1): Zero-Wait Pre-Resolved Stream Hit for 52991 Ep 2\n"
            "2026-11-21 10:00:03.100 T:100 info <general>: Subtitle Service: action=search returned 3 result(s)\n"
            "2026-11-21 10:00:04.100 T:100 error <general>: OTAKU RPDEV (1): resolve_silent failed for candidate\n"
            "2026-11-21 10:00:05.100 T:100 error <general>: OpenStream - Unable to create subtitle parser\n"
            "2026-11-21 10:00:06.100 T:100 warning <general>: OTAKU RPDEV (1): WatchlistFlavorAuth idle timeout\n"
            "2026-11-21 10:00:07.100 T:100 error <general>: plugin.video.umbrella: ignored noise\n"
        )
        with tempfile.TemporaryDirectory(prefix='otaku_sp03_') as td:
            log_path = os.path.join(td, 'onn.log')
            json_out = os.path.join(td, 'audit.json')
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write(fixture_log)

            proc = run_cli_script(
                'scripts/audit_onn_logs.py',
                ['--input', log_path, '--offset', '0', '--json', json_out],
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with open(json_out, 'r', encoding='utf-8') as jf:
                report = json.load(jf)

            self.assertEqual(report['status'], 'ok')
            self.assertEqual(report['counts']['zero_wait'], 2)
            self.assertEqual(report['counts']['subtitles'], 2)
            self.assertEqual(report['counts']['otaku_errors'], 1)
            self.assertEqual(report['counts']['otaku_warnings'], 1)
            self.assertEqual(report['counts']['non_otaku_noise_filtered'], 1)
            self.assertEqual(report['counts']['concerns']['C-34'], 1)
            self.assertEqual(report['counts']['concerns']['C-14'], 1)
            self.assertEqual(report['counts']['concerns']['C-35'], 1)
            self.assertEqual(report['addon_versions'].get('plugin.video.otaku.rpdev'), '6.3.0')

    @tier(1)
    @feature('SP-03')
    def test_sp03_t1_audit_onn_logs_reads_concerns_cursor_and_http_get_only(self):
        concerns_content = "| **Next review offset** | **12345** |\n"
        captured_reqs = []

        with tempfile.TemporaryDirectory(prefix='otaku_sp03_srv_') as td:
            concerns_path = os.path.join(td, 'CONCERNS.md')
            with open(concerns_path, 'w', encoding='utf-8') as f:
                f.write(concerns_content)
            json_out = os.path.join(td, 'tail_audit.json')

            with E2EMockServer() as srv:
                def _tail(req_handler, method, path, parsed, headers, body):
                    captured_reqs.append((method, path, parsed.query))
                    payload = "2026-11-21 10:01:00 T:1 info <general>: OTAKU RPDEV (1): clean_settings ok\n"
                    send_http_response(
                        req_handler,
                        status=200,
                        body=payload,
                        extra_headers={'X-Seek-Offset': '12345'},
                        is_head=(method == 'HEAD'),
                    )
                    return True

                srv.add_route('/tail', _tail)
                proc = run_cli_script(
                    'scripts/audit_onn_logs.py',
                    ['--concerns', concerns_path, '--url', f"{srv.get_base_url()}/tail", '--json', json_out],
                )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(captured_reqs, [('GET', '/tail', 'offset=12345')])
            with open(concerns_path, 'r', encoding='utf-8') as cf:
                self.assertEqual(cf.read(), concerns_content)
            with open(json_out, 'r', encoding='utf-8') as jf:
                report = json.load(jf)
            self.assertEqual(report['requested_offset'], 12345)
            self.assertEqual(report['counts']['clean_settings'], 1)

    @tier(1)
    @feature('SP-03')
    def test_sp03_t1_audit_onn_logs_offset_flag_overrides_concerns_cursor(self):
        with tempfile.TemporaryDirectory(prefix='otaku_sp03_off_') as td:
            concerns_path = os.path.join(td, 'CONCERNS.md')
            with open(concerns_path, 'w', encoding='utf-8') as f:
                f.write("| **Next review offset** | **99999** |\n")
            seen_queries = []

            with E2EMockServer() as srv:
                def _tail(req_handler, method, path, parsed, headers, body):
                    seen_queries.append(parsed.query)
                    send_http_response(
                        req_handler,
                        status=200,
                        body="2026-11-21 10:02:00 T:1 info <general>: OTAKU RPDEV (1): ok\n",
                        extra_headers={'X-Seek-Offset': '512'},
                    )
                    return True

                srv.add_route('/tail', _tail)
                proc = run_cli_script(
                    'scripts/audit_onn_logs.py',
                    ['--concerns', concerns_path, '--offset', '512', '--url', f"{srv.get_base_url()}/tail", '--json', '-'],
                )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(seen_queries, ['offset=512'])
            report = json.loads(proc.stdout)
            self.assertEqual(report['requested_offset'], 512)
            self.assertFalse(report['rotated'])

    @tier(1)
    @feature('SP-03')
    def test_sp03_t1_subtitle_temp_ops_hermetic_with_zero_repo_leaks(self):
        assert_repo_clean_of_leaks()
        with E2EHermeticEnv('22') as env, E2EMockServer() as srv:
            from resources.lib.ui import control, embed_extractor
            from resources.lib.subtitles import download as sub_dl
            from resources.lib.subtitles.models import SubtitleResult, VideoMeta

            sub_url = f"{srv.get_base_url()}/sub.srt"
            entry = embed_extractor.get_sub(sub_url, 'eng', sub_tag='sp03_leak_check')
            self.assertIsNotNone(entry)
            expected_temp_files = [f for f in os.listdir(env.temp_dir) if f.startswith('TemporarySubs.sp03_leak_check')]
            self.assertEqual(len(expected_temp_files), 1)

            vfs_target = os.path.join(env.temp_dir, 'atomic_probe.txt')
            wrote = control.atomic_write_text(vfs_target, 'hello', vfs_path='special://temp/atomic_probe.txt')
            self.assertTrue(wrote)
            self.assertTrue(os.path.isfile(vfs_target))

            meta = VideoMeta(title='Frieren', season=1, episode=2, filename='Frieren_02.mkv')
            sub_res = SubtitleResult(
                service_name='opensubtitles',
                display_name='OpenSubtitles',
                name='Frieren.02.srt',
                lang='English',
                lang_code='eng',
                download_url=sub_url,
            )
            with open(os.path.join(REPO_ROOT, 'tests', 'fixtures', 'media', 'sample.srt'), 'rb') as sf:
                srt_bytes = sf.read()

            with patch('resources.lib.subtitles.services.opensubtitles.OpenSubtitlesService.download', return_value=srt_bytes):
                dl_path = sub_dl.download_and_prepare_subtitle(sub_res, meta, {'subtitles.use_chardet': False})
            self.assertIsNotNone(dl_path)
            self.assertTrue(dl_path.startswith(env.profile_dir))
            self.assertTrue(os.path.isfile(dl_path))

            embed_extractor.del_subs()
            leftover = [f for f in os.listdir(env.temp_dir) if f.startswith('TemporarySubs.')]
            self.assertEqual(leftover, [])
        assert_repo_clean_of_leaks()

    @tier(1)
    @feature('SP-03')
    def test_sp03_t1_e2e_suite_passes_quality_and_compileall_hygiene(self):
        e2e_dir = os.path.join(REPO_ROOT, 'tests', 'e2e_v630')
        target_files = [
            os.path.join(REPO_ROOT, 'scripts', 'e2e_v630_suite.py'),
            os.path.join(e2e_dir, 'e2e_helpers.py'),
        ]
        for fname in sorted(os.listdir(e2e_dir)):
            if fname.startswith('suite_') and fname.endswith('.py'):
                target_files.append(os.path.join(e2e_dir, fname))

        for path in target_files:
            py_compile.compile(path, doraise=True)

        # Enforce test_suite_quality.py rules on all E2E suite_*.py files
        suite_files = [p for p in target_files if os.path.basename(p).startswith('suite_')]
        self.assertGreaterEqual(len(suite_files), 2)
        for path in suite_files:
            with open(path, 'r', encoding='utf-8') as f:
                src = f.read()
            tree = ast.parse(src, filename=path)
            for fn in test_suite_quality._iter_test_functions(tree):
                asserts = test_suite_quality._collect_assertion_nodes(fn)
                self.assertGreaterEqual(len(asserts), 1, f"Zero assertions in {path}:{fn.name}")
                seg = ast.get_source_segment(src, fn) or ''
                self.assertFalse('module_from_spec' in seg and 'exec_module' not in seg)
                for sub in ast.walk(fn):
                    if isinstance(sub, ast.ExceptHandler):
                        is_pass = len(sub.body) == 1 and isinstance(sub.body[0], (ast.Pass, ast.Continue))
                        if is_pass:
                            self.assertNotIn(
                                getattr(sub.type, 'id', None) if sub.type else None,
                                (None, 'Exception', 'BaseException'),
                            )

    @tier(2)
    @feature('SP-03')
    def test_sp03_t2_audit_onn_logs_detects_log_rotation_and_resets_offset(self):
        with tempfile.TemporaryDirectory(prefix='otaku_sp03_rot_') as td:
            concerns_path = os.path.join(td, 'CONCERNS.md')
            with open(concerns_path, 'w', encoding='utf-8') as f:
                f.write("| **Next review offset** | **50000** |\n")

            with E2EMockServer() as srv:
                def _rotated_tail(req_handler, method, path, parsed, headers, body):
                    payload = "2026-11-21 10:05:00 T:1 info <general>: OTAKU RPDEV (1): restarted\n"
                    send_http_response(
                        req_handler,
                        status=200,
                        body=payload,
                        extra_headers={'X-Seek-Offset': '0'},
                    )
                    return True

                srv.add_route('/tail', _rotated_tail)
                proc = run_cli_script(
                    'scripts/audit_onn_logs.py',
                    ['--concerns', concerns_path, '--url', f"{srv.get_base_url()}/tail", '--json', '-'],
                )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = json.loads(proc.stdout)
            self.assertTrue(report['rotated'])
            self.assertEqual(report['x_seek_offset'], 0)
            self.assertEqual(report['next_offset'], report['bytes_read'])

    @tier(2)
    @feature('SP-03')
    def test_sp03_t2_audit_onn_logs_unreachable_loopback_exits_cleanly(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('127.0.0.1', 0))
        closed_port = sock.getsockname()[1]
        sock.close()

        with tempfile.TemporaryDirectory(prefix='otaku_sp03_down_') as td:
            concerns_path = os.path.join(td, 'CONCERNS.md')
            concerns_text = "| **Next review offset** | **777** |\n"
            with open(concerns_path, 'w', encoding='utf-8') as f:
                f.write(concerns_text)

            proc = run_cli_script(
                'scripts/audit_onn_logs.py',
                ['--concerns', concerns_path, '--url', f'http://127.0.0.1:{closed_port}/tail', '--timeout', '2', '--json', '-'],
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertNotIn('Traceback (most recent call last)', proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload['status'], 'error')
            with open(concerns_path, 'r', encoding='utf-8') as cf:
                self.assertEqual(cf.read(), concerns_text)

    @tier(2)
    @feature('SP-03')
    def test_sp03_t2_audit_onn_logs_invalid_utf8_bytes_handled_with_replacement(self):
        with tempfile.TemporaryDirectory(prefix='otaku_sp03_utf8_') as td:
            log_path = os.path.join(td, 'bad_utf8.log')
            with open(log_path, 'wb') as f:
                f.write(b"\xff\xfe2026-11-21 10:06:00 T:1 info <general>: OTAKU RPDEV (1): clean_settings \x80\x81\n")

            proc = run_cli_script(
                'scripts/audit_onn_logs.py',
                ['--input', log_path, '--offset', '0', '--json', '-'],
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = json.loads(proc.stdout)
            self.assertEqual(report['status'], 'ok')
            self.assertEqual(report['counts']['clean_settings'], 1)
            self.assertEqual(report['total_lines'], 1)

    @tier(2)
    @feature('SP-03')
    def test_sp03_t2_audit_onn_logs_malformed_concerns_cursor_fails_non_zero(self):
        with tempfile.TemporaryDirectory(prefix='otaku_sp03_badcur_') as td:
            concerns_path = os.path.join(td, 'CONCERNS.md')
            with open(concerns_path, 'w', encoding='utf-8') as f:
                f.write("# No review offset cursor here\n")

            proc = run_cli_script(
                'scripts/audit_onn_logs.py',
                ['--concerns', concerns_path, '--url', 'http://127.0.0.1:1/tail'],
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn('Next review offset', proc.stderr)

    @tier(2)
    @feature('SP-03')
    def test_sp03_t2_audit_onn_logs_empty_log_fixture_valid_zero_json(self):
        with tempfile.TemporaryDirectory(prefix='otaku_sp03_empty_') as td:
            log_path = os.path.join(td, 'empty.log')
            with open(log_path, 'wb') as f:
                f.write(b"")

            proc = run_cli_script(
                'scripts/audit_onn_logs.py',
                ['--input', log_path, '--offset', '0', '--json', '-'],
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = json.loads(proc.stdout)
            self.assertEqual(report['status'], 'ok')
            self.assertEqual(report['bytes_read'], 0)
            self.assertEqual(report['total_lines'], 0)
            self.assertEqual(report['counts']['otaku_errors'], 0)
            self.assertEqual(report['counts']['zero_wait'], 0)
