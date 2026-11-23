# -*- coding: utf-8 -*-
"""Hermetic unit & E2E tests for Otaku-RPDev v6.4.0 features (NF-11, NF-12, NF-14)."""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_TEST_DIR, '..', '..'))
_TESTS_DIR = os.path.join(_REPO_ROOT, 'tests')
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import conftest  # noqa: F401
from tests.e2e_v630.e2e_helpers import E2EHermeticEnv, invoke_plugin_route
from tests.kodi_profile import KodiProfile


class TestV640Features(unittest.TestCase):
    """Comprehensive verification for NF-11 Failover, NF-12 Series Profile XML, and NF-14 Scene Markers."""

    # ── NF-11: Mid-Stream CURL-56 / Stall Debrid Failover ──────────────────

    def test_nf11_failover_context_and_candidate_ordering(self):
        with E2EHermeticEnv('22'):
            from resources.lib.ui import database, domains
            from resources.lib.windows import resolver

            sources = [
                {
                    'provider': 'Nyaa',
                    'type': 'torrent',
                    'debrid_provider': 'Premiumize',
                    'hash': 'abc123def456',
                    'release_title': 'Show Ep 01 [1080p]',
                    'quality': 3,
                    'info': ['1080p'],
                },
                {
                    'provider': 'HiAnime',
                    'type': 'direct',
                    'hash': 'https://broken-cdn.example.net/stream.m3u8',
                    'release_title': 'Mirror 1',
                    'quality': 2,
                    'info': [],
                },
                {
                    'provider': 'AnimePahe',
                    'type': 'direct',
                    'hash': 'https://healthy-cdn.example.net/stream.mp4',
                    'release_title': 'Mirror 2',
                    'quality': 2,
                    'info': [],
                },
            ]
            ok = database.save_playback_failover_context(
                52991,
                1,
                {
                    'sources': sources,
                    'candidate_index': 0,
                    'active_url': 'https://s1.energycdn.com/dl/file.mkv',
                    'active_host': 's1.energycdn.com',
                    'debrid_provider': 'Premiumize',
                    'media_type': 'episode',
                },
            )
            self.assertTrue(ok)
            ctx = database.get_playback_failover_context(52991, 1)
            self.assertIsNotNone(ctx)
            self.assertEqual(ctx['debrid_provider'], 'Premiumize')
            self.assertEqual(len(ctx['sources']), 3)

            domains.adaptive_circuit_breaker.reset()
            domains.adaptive_circuit_breaker.record_failure('broken-cdn.example.net', category='debrid', status_code=429)
            ordered = resolver.build_midstream_failover_candidates(
                ctx,
                failing_host='broken-cdn.example.net',
                enabled_providers=['Premiumize', 'Real-Debrid', 'TorBox'],
                circuit_breaker=domains.adaptive_circuit_breaker,
            )
            # First candidates must switch Debrid provider on identical torrent hash, then healthy direct mirror
            self.assertEqual(ordered[0]['debrid_provider'], 'Real-Debrid')
            self.assertEqual(ordered[0]['hash'], 'abc123def456')
            self.assertEqual(ordered[1]['debrid_provider'], 'TorBox')
            self.assertEqual(ordered[2]['provider'], 'AnimePahe')

    def test_nf11_premature_eof_failover_and_diagnostics_report(self):
        with E2EHermeticEnv('22'):
            from resources.lib.ui import control, database, domains, player
            from resources.lib.routes import playback, tools

            control.setBool('smartplay.stream_failover', True)
            control.playerWindow.clearProperty('otaku.failover_attempts_52991_3')
            domains.adaptive_circuit_breaker.reset()

            sources = [
                {
                    'provider': 'Nyaa',
                    'type': 'torrent',
                    'debrid_provider': 'Premiumize',
                    'hash': 'hash999',
                    'release_title': 'Frieren Ep 03',
                    'quality': 3,
                    'info': ['1080p'],
                },
            ]
            database.save_playback_failover_context(
                52991,
                3,
                {
                    'sources': sources,
                    'candidate_index': 0,
                    'active_url': 'https://s2.energycdn.com/frieren03.mkv',
                    'active_host': 's2.energycdn.com',
                    'debrid_provider': 'Premiumize',
                    'media_type': 'episode',
                },
            )

            wp = player.WatchlistPlayer()
            wp.mal_id = 52991
            wp.episode = 3
            wp.media_type = 'episode'
            wp.total_time = 1440
            wp.current_time = 650

            backup_res = {
                'source': {'provider': 'Nyaa', 'type': 'torrent', 'debrid_provider': 'Real-Debrid', 'hash': 'hash999'},
                'linkinfo': {'url': 'https://rd-cdn.example.com/stream.mkv', 'headers': {'Content-Type': 'video/x-matroska'}},
                'url': 'https://rd-cdn.example.com/stream.mkv',
                'headers': {'Content-Type': 'video/x-matroska'},
                'sub': [],
            }
            exec_cmds = []
            with patch('resources.lib.windows.resolver.resolve_failover_candidate', return_value=backup_res), \
                 patch('resources.lib.ui.control.execute', side_effect=lambda cmd: exec_cmds.append(cmd)):
                wp.onPlayBackEnded()

            self.assertTrue(wp._failover_triggered)
            self.assertEqual(control.playerWindow.getProperty('otaku.preResolved_url'), 'https://rd-cdn.example.com/stream.mkv')
            self.assertTrue(any('play/52991/3?resume=647&auto_resume=1' in c for c in exec_cmds))

            # Diagnostics report includes tripped Debrid CDN / host section
            snap = domains.adaptive_circuit_breaker.get_snapshot()
            self.assertIn('s2.energycdn.com', snap)
            self.assertEqual(snap['s2.energycdn.com']['category'], 'debrid')
            report = tools.generate_diagnostics_report()
            self.assertIn('[6] Mid-Stream Failover & Debrid CDN Health', report)
            self.assertIn('s2.energycdn.com', report)

            # Manual bookmark prompt is bypassed cleanly when auto_resume=1 is passed
            with patch('resources.lib.ui.control.context_menu', side_effect=AssertionError('Must not prompt on auto_resume')), \
                 patch('resources.lib.MetaBrowser.get_sources', return_value=[]):
                playback.PLAY('52991/3', {'resume': '647', 'auto_resume': '1', 'tvshowtitle': 'Frieren'})

            # User-initiated stop must NEVER trigger failover
            wp2 = player.WatchlistPlayer()
            wp2.mal_id = 52991
            wp2.episode = 3
            wp2.total_time = 1440
            wp2.current_time = 400
            with patch('resources.lib.windows.resolver.resolve_failover_candidate') as mock_rf:
                wp2.onPlayBackStopped()
                mock_rf.assert_not_called()

    # ── NF-12: WindowXML SeriesProfileDialog Editor ───────────────────────

    def test_nf12_series_profile_windowxml_editor_and_persistence(self):
        with E2EHermeticEnv('22', strict_skin_controls=True):
            from resources.lib.ui import control, database
            from resources.lib.windows.series_profile import SeriesProfileDialog, open_series_profile_dialog

            self.assertTrue(KodiProfile.is_strict_skin_controls())
            dlg = SeriesProfileDialog('series_profile.xml', control.ADDON_PATH, mal_id=52991)
            dlg.onInit()
            self.assertEqual(dlg.list_control.size(), 8)

            # In-place stepping on Episode Offset (idx 5) and Intro Offset (idx 6) updates badge without resetting list
            list_ref = dlg.list_control
            dlg.list_control.selectItem(5)
            dlg.onClick(3003)  # +1 episode offset
            self.assertEqual(dlg.values['episode_offset'], 1)
            self.assertEqual(dlg.list_control, list_ref)
            self.assertEqual(dlg.list_control.getListItem(5).getProperty('value_badge'), '+1 ep')

            dlg.list_control.selectItem(6)
            dlg.onClick(3002)  # -1s intro offset
            self.assertEqual(dlg.values['intro_offset_s'], -1)
            self.assertIn('OP Example', dlg.getProperty('skip_preview'))

            # Save profile via Save button (3005)
            dlg.onClick(3005)
            self.assertTrue(dlg._win_closed)
            saved = database.get_series_override(52991)
            self.assertIsNotNone(saved)
            self.assertEqual(saved['episode_offset'], 1)
            self.assertEqual(saved['intro_offset_s'], -1)

            # Reset via button 3004 stages defaults in UI; Cancel keeps existing DB row, Save deletes DB row
            dlg.reset_defaults()
            self.assertEqual(dlg.values['episode_offset'], 0)
            self.assertIsNotNone(database.get_series_override(52991))
            dlg.onClick(3006)  # Cancel leaves DB override intact
            self.assertIsNotNone(database.get_series_override(52991))

            dlg_save_reset = SeriesProfileDialog('series_profile.xml', control.ADDON_PATH, mal_id=52991)
            dlg_save_reset.onInit()
            dlg_save_reset.reset_defaults()
            dlg_save_reset.onClick(3005)  # Save commits staged reset -> deletes DB override
            self.assertIsNone(database.get_series_override(52991))
            self.assertEqual(dlg_save_reset.values['episode_offset'], 0)

            # Non-parameterized route opens SeriesProfileDialog cleanly under try...finally
            with patch('resources.lib.windows.series_profile.SeriesProfileDialog.doModal', return_value=None) as mock_dm:
                invoke_plugin_route('series_profile/52991')
                mock_dm.assert_called_once()
            open_series_profile_dialog(52991)

    # ── NF-14: Kodi 22 Native Scene-Marker & Chapter Stepping ─────────────

    def test_nf14_scene_markers_merge_skip_and_routes(self):
        with E2EHermeticEnv('22'):
            from resources.lib.ui import control, player
            from resources.lib.windows.skip_intro import SkipIntro

            control.setBool('smartplay.scene_markers', True)
            chapters = [
                {'title': 'Prologue', 'start': 0.0, 'end': 45.0},
                {'title': 'Recap', 'start': 45.0, 'end': 88.0},
                {'title': 'Opening', 'start': 92.0, 'end': 182.0},
                {'title': 'Part A', 'start': 182.0, 'end': 720.0},
                {'title': 'Ending', 'start': 1295.0, 'end': 1385.0},
                {'title': 'Preview', 'start': 1385.0, 'end': 1420.0},
            ]
            markers = player.build_scene_markers(
                chapters,
                aniskip_start=90,
                aniskip_end=180,
                aniskip_source='aniskip',
                outro_start=1296,
                outro_end=1386,
                outro_source='introdb',
                total_time=1420,
            )
            self.assertEqual(len(markers), 6)
            op_marker = next(m for m in markers if m['kind'] == 'intro')
            self.assertEqual(op_marker['source'], 'chapter+aniskip')
            self.assertEqual(op_marker['start'], 90.0)
            self.assertEqual(op_marker['end'], 180.0)
            self.assertEqual(player.format_scene_marker_label(op_marker), '[01:30] Opening (CHAPTER+ANISKIP)')

            nxt = player.find_next_scene_marker(markers, 50.0)
            self.assertEqual(nxt['kind'], 'intro')
            prv = player.find_prev_scene_marker(markers, 92.0)
            self.assertEqual(prv['kind'], 'recap')
            restart = player.find_prev_scene_marker(markers, 100.0)
            self.assertEqual(restart['kind'], 'intro')

            # Contiguous Recap (45-88s) -> Opening (90-180s) resolves full jump end=180s
            wp = player.WatchlistPlayer()
            wp.ffprobe_chapters = chapters
            wp.skipintro_aniskip = True
            wp.skipintro_start = 90
            wp.skipintro_end = 180
            wp._skipintro_source = 'aniskip'
            wp.skipoutro_aniskip = True
            wp.skipoutro_start = 1296
            wp.skipoutro_end = 1386
            wp._skipoutro_source = 'introdb'
            wp.current_time = 50
            wp.total_time = 1420
            published = wp._publish_scene_markers()
            self.assertEqual(len(published), 6)
            self.assertEqual(wp._contiguous_skip_end(88), 180)
            self.assertIsNotNone(json.loads(control.playerWindow.getProperty('otaku.scene_markers')))

            # SkipIntro dialog respects next_marker_end on button 3001
            with KodiProfile('22', strict_skin_controls=True):
                si = SkipIntro(
                    'skip_intro_default.xml',
                    control.ADDON_PATH,
                    actionArgs={'item_type': 'skip_intro', 'skipintro_aniskip': True, 'skipintro_end': 88, 'next_marker_end': 180},
                )
                mock_si_player = MagicMock()
                si.player = mock_si_player
                si.onClick(3001)
                mock_si_player.seekTime.assert_called_once_with(180)
                self.assertIsNone(si.player)

            # Route step_scene_marker/next & scene_markers picker seek cleanly
            mock_player = MagicMock()
            mock_player.isPlaying.return_value = True
            mock_player.getTime.return_value = 50.0
            with patch('resources.lib.ui.player.xbmc.Player', return_value=mock_player):
                invoke_plugin_route('step_scene_marker/next')
                mock_player.seekTime.assert_called_with(90.0)
                mock_player.reset_mock()
                mock_player.isPlaying.return_value = True
                with patch('resources.lib.ui.control.select_dialog', return_value=4):
                    invoke_plugin_route('scene_markers')
                    mock_player.seekTime.assert_called_with(1296.0)


if __name__ == '__main__':
    unittest.main()
