# -*- coding: utf-8 -*-
"""
test_v630_wave3_features.py — Hermetic Unit & Integration Tests for NF-01..NF-08
=================================================================================
Covers:
  - NF-01: Multi-Tracker Watchlist Conflict Engine, Persistent 429 Scrobble Retry Queue & Telemetry Route
  - NF-02: Widget-Aware context.otaku.rpdev v1.0.46 Quick Actions (seriesprofile, manualsubtitles, widget mal_id)
  - NF-03: Filler & Recap Episode Badges, Binge Auto-Skip Filler, and Per-Series OP/ED Offset Calibration
  - NF-04: Unified Adaptive Provider Circuit Breaker (exponential cooldown tiers 300s -> 900s -> 3600s, half-open)
  - NF-05: Compressed (.xz/.gz) & Verified mappings.db Sync (SHA-256, PRAGMA quick_check, .bak rollback)
  - NF-06: Per-Series Playback & Scraper Override Profiles (CRUD, WatchlistPlayer, sortSources, series_profile route)
  - NF-07: Subtitle Intelligence v2 (top-3 fallback, SDH bracket/speaker tag stripping, subtitle circuit breaker)
  - NF-08: Cross-Watchlist Drift Auditor (compute_watchlist_drift, reconcile_watchlist_drift, route)
"""

import gzip
import hashlib
import lzma
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_TEST_DIR, '..' if os.path.basename(_TEST_DIR) in ('unit', 'integration', 'lint') else '.'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
_TESTS_DIR = os.path.join(_REPO_ROOT, 'tests')
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import conftest  # noqa: F401
from tests.e2e_v630.e2e_helpers import (
    E2EHermeticEnv,
    E2EMockServer,
    invoke_context_action,
    invoke_plugin_route,
    send_http_response,
)


class TestWave3FeaturesNF01ToNF08(unittest.TestCase):

    # ── NF-06: Per-Series Playback & Scraper Override Profiles ─────────────

    def test_nf06_series_override_crud_and_route(self):
        with E2EHermeticEnv('22'):
            from resources.lib.ui import database

            self.assertIsNone(database.get_series_override(52991))
            ok = database.set_series_override(
                52991,
                audio_lang='eng',
                sub_lang='eng',
                sub_mode='signs',
                preferred_provider='hianime',
                intro_offset_s=5,
                outro_offset_s=-3,
                skip_filler_mode='skip',
            )
            self.assertTrue(ok)
            ov = database.get_series_override(52991)
            self.assertIsNotNone(ov)
            self.assertEqual(ov['audio_lang'], 'eng')
            self.assertEqual(ov['sub_lang'], 'eng')
            self.assertEqual(ov['sub_mode'], 'signs')
            self.assertEqual(ov['preferred_provider'], 'hianime')
            self.assertEqual(ov['intro_offset_s'], 5)
            self.assertEqual(ov['outro_offset_s'], -3)
            self.assertEqual(ov['skip_filler_mode'], 'skip')

            all_ov = database.list_series_overrides()
            self.assertEqual(len(all_ov), 1)
            self.assertEqual(all_ov[0]['mal_id'], 52991)

            # Route update via query params
            invoke_plugin_route(
                'series_profile/52991',
                params={'audio_lang': 'jpn', 'preferred_provider': 'nyaa', 'intro_offset_s': '2'},
            )
            ov2 = database.get_series_override(52991)
            self.assertEqual(ov2['audio_lang'], 'jpn')
            self.assertEqual(ov2['preferred_provider'], 'nyaa')
            self.assertEqual(ov2['intro_offset_s'], 2)

            # Route reset via query param
            invoke_plugin_route('series_profile/52991', params={'reset': 'true'})
            self.assertIsNone(database.get_series_override(52991))

    def test_nf06_series_override_applied_in_player_and_sort_sources(self):
        with E2EHermeticEnv('22'):
            from resources.lib.ui import control, database, player
            from resources.lib.pages import Sources

            database.set_series_override(
                52991,
                audio_lang='eng',
                sub_lang='eng',
                sub_mode='signs',
                preferred_provider='hianime',
                intro_offset_s=4,
                outro_offset_s=-2,
                skip_filler_mode='skip',
            )

            # 1. WatchlistPlayer applies audio, sub_mode, and intro/outro offsets
            wp = player.WatchlistPlayer()
            with patch.object(wp, 'keepAlive', return_value=None), \
                 patch.object(wp, '_async_process_skip_times', return_value=None):
                wp.handle_player(52991, None, 1, 0, 'http://127.0.0.1/v.mkv', 'direct', 'nyaa', False)
            self.assertEqual(wp.preferred_audio, 1)
            self.assertEqual(wp.preferred_subtitle_setting, 1)
            self.assertEqual(wp.preferred_subtitle_keyword, 2)
            self.assertEqual(wp.skipintro_offset, 4)
            self.assertEqual(wp.skipoutro_offset, -2)

            # 2. sortSources prioritizes preferred_provider within equal relevance tier
            control.setInt('general.source', 0)
            src_win = Sources.__new__(Sources)
            t_list = []
            e_list = [
                {'release_title': 'Frieren - 01', 'provider': 'animepahe', 'type': 'embed', 'quality': 3, 'lang': 2, 'size': '500 MB', 'debrid_provider': '', 'info': []},
                {'release_title': 'Frieren - 01', 'provider': 'hianime', 'type': 'embed', 'quality': 3, 'lang': 2, 'size': '500 MB', 'debrid_provider': '', 'info': []},
            ]
            sorted_res = src_win.sortSources(t_list, [], e_list, [], [], 'show', 24, mal_id='52991', show_title='Frieren')
            self.assertEqual(sorted_res[0]['provider'], 'hianime')

    # ── NF-04: Unified Adaptive Provider Circuit Breaker ───────────────────

    def test_nf04_adaptive_circuit_breaker_exponential_tiers_and_half_open(self):
        with E2EHermeticEnv('22'):
            from resources.lib.ui.domains import AdaptiveCircuitBreaker

            cb = AdaptiveCircuitBreaker(failure_threshold=2, cooldown_seconds=300)
            cb.reset()

            # 2 failures -> Trip tier 1 (300s)
            cb.record_failure('nyaa', category='torrent')
            self.assertFalse(cb.is_tripped('nyaa'))
            cb.record_failure('nyaa', category='torrent')
            self.assertTrue(cb.is_tripped('nyaa'))
            snap1 = cb.get_snapshot()['nyaa']
            self.assertEqual(snap1['state'], 'OPEN')
            self.assertEqual(snap1['trips'], 1)
            self.assertEqual(snap1['category'], 'torrent')
            self.assertGreater(snap1['remaining_s'], 250)

            # Simulate cooldown expiry -> transitions to HALF_OPEN
            cb._cooldown_until['nyaa'] = 1.0
            self.assertFalse(cb.is_tripped('nyaa'))
            self.assertTrue(cb.is_half_open('nyaa'))

            # Single failure in HALF_OPEN -> immediately re-trips at tier 2 (900s)
            cb.record_failure('nyaa', category='torrent')
            self.assertTrue(cb.is_tripped('nyaa'))
            snap2 = cb.get_snapshot()['nyaa']
            self.assertEqual(snap2['trips'], 2)
            self.assertGreater(snap2['remaining_s'], 850)

            # Success clears all state
            cb.record_success('nyaa', category='torrent')
            self.assertFalse(cb.is_tripped('nyaa'))
            self.assertNotIn('nyaa', cb.get_snapshot())

    # ── NF-05: Compressed & Verified mappings.db Sync with .bak Rollback ──

    def test_nf05_compressed_xz_and_gz_mappings_sync_and_corrupt_rollback(self):
        with E2EHermeticEnv('22') as env, E2EMockServer() as srv:
            import service
            from resources.lib.ui import control, database

            # Build valid SQLite mappings DB in temp file
            with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tf:
                valid_db_path = tf.name
            try:
                with sqlite3.connect(valid_db_path) as c:
                    c.execute('CREATE TABLE anime (mal_id INTEGER PRIMARY KEY, kitsu_id INTEGER)')
                    c.execute('INSERT INTO anime VALUES (52991, 46789)')
                    c.commit()
                with open(valid_db_path, 'rb') as f:
                    valid_bytes = f.read()
            finally:
                if os.path.exists(valid_db_path):
                    os.remove(valid_db_path)

            xz_bytes = lzma.compress(valid_bytes)
            gz_bytes = gzip.compress(valid_bytes)
            valid_sha = hashlib.sha256(valid_bytes).hexdigest()

            def _map_handler(req_handler, method, path, parsed, headers, body):
                if path == '/mappings.db.xz':
                    send_http_response(
                        req_handler, 200, xz_bytes, 'application/x-xz',
                        extra_headers={'X-Checksum-Sha256': valid_sha, 'ETag': '"v1-xz"'},
                    )
                    return True
                if path == '/mappings.db.gz':
                    send_http_response(req_handler, 200, gz_bytes, 'application/gzip')
                    return True
                if path == '/corrupt.db':
                    send_http_response(req_handler, 200, b'SQLite format 3\x00CORRUPT_PAYLOAD_BYTES', 'application/octet-stream')
                    return True
                return False

            srv._custom_handler = _map_handler
            base = srv.get_base_url()

            # 1. Sync .xz with matching SHA-256
            ok_xz = service.update_mappings_db(url=f"{base}/mappings.db.xz")
            self.assertTrue(ok_xz)
            dest_db = os.path.join(control.dataPath, 'mappings.db')
            self.assertTrue(os.path.isfile(dest_db))
            ok_verify, reason = database.verify_sqlite_integrity(dest_db)
            self.assertTrue(ok_verify, reason)
            self.assertEqual(database.get_mappings(52991, 'mal_id').get('kitsu_id'), 46789)

            # 2. Sync .gz creates .bak of previous valid DB
            ok_gz = service.update_mappings_db(url=f"{base}/mappings.db.gz")
            self.assertTrue(ok_gz)
            self.assertTrue(os.path.isfile(f"{dest_db}.bak"))

            # 3. Corrupt payload rejected by PRAGMA quick_check; live mappings.db remains intact!
            ok_bad = service.update_mappings_db(url=f"{base}/corrupt.db")
            self.assertFalse(ok_bad)
            self.assertEqual(database.get_mappings(52991, 'mal_id').get('kitsu_id'), 46789)

            # 4. SHA-256 mismatch rejected
            ok_sha_fail = service.update_mappings_db(url=f"{base}/mappings.db.xz", expected_sha256='0' * 64)
            self.assertFalse(ok_sha_fail)

    # ── NF-01 & NF-08: Multi-Tracker Conflict Engine, 429 Queue & Drift Auditor ─

    def test_nf01_and_nf08_conflict_policies_retry_queue_and_drift_reconciliation(self):
        with E2EHermeticEnv('22'):
            from resources.lib.ui import control, database
            from resources.lib.WatchlistFlavor import WatchlistFlavor

            control.setBool('watchlist.update.enabled', True)
            control.setBool('anilist.enabled', True)
            control.setSetting('anilist.token', 'tok_al')
            control.setBool('mal.enabled', True)
            control.setSetting('mal.token', 'tok_mal')

            # Seed watchlist_cache with drift between AniList (ep 8) and MAL (ep 5)
            database.save_watchlist_cache('anilist', 'CURRENT', [
                {'media': {'idMal': 52991, 'title': {'english': 'Frieren'}, 'episodes': 28}, 'progress': 8, 'updatedAt': 1700000100},
            ])
            database.save_watchlist_cache('mal', 'watching', [
                {'node': {'id': 52991, 'title': 'Frieren', 'num_episodes': 28}, 'list_status': {'num_episodes_watched': 5, 'updated_at': '2026-11-21T10:00:00Z'}},
            ])

            # Test conflict policies via mocked flavor entries
            entry_al = {'eps_watched': 8, 'updated_at': '2026-11-20T00:00:00Z'}
            entry_mal = {'eps_watched': 5, 'updated_at': '2026-11-21T00:00:00Z'}
            with patch('resources.lib.WatchlistFlavor.AniList.AniListWLF.get_watchlist_anime_entry', return_value=entry_al), \
                 patch('resources.lib.WatchlistFlavor.MyAnimeList.MyAnimeListWLF.get_watchlist_anime_entry', return_value=entry_mal):
                control.setInt('watchlist.sync.conflict_policy', 0)  # highest_progress
                self.assertEqual(WatchlistFlavor.get_merged_watchlist_eps_watched(52991), 8)

                control.setInt('watchlist.sync.conflict_policy', 1)  # primary_wins (anilist first)
                self.assertEqual(WatchlistFlavor.get_merged_watchlist_eps_watched(52991), 8)

                control.setInt('watchlist.sync.conflict_policy', 2)  # latest_updated (mal is 2026-11-21)
                self.assertEqual(WatchlistFlavor.get_merged_watchlist_eps_watched(52991), 5)

            # Test NF-08 Drift detection and reconciliation
            control.setInt('watchlist.sync.conflict_policy', 0)
            drifts = WatchlistFlavor.compute_watchlist_drift()
            self.assertEqual(len(drifts), 1)
            self.assertEqual(drifts[0]['mal_id'], 52991)
            self.assertEqual(drifts[0]['target_episode'], 8)

            with patch.object(WatchlistFlavor, 'watchlist_update_episode_for_flavor', return_value=True) as mock_upd:
                reconciled = WatchlistFlavor.reconcile_watchlist_drift(drifts)
                self.assertEqual(reconciled, 1)
                mock_upd.assert_called_once_with('mal', 52991, 8)

            # Test NF-01 Persistent Scrobble Retry Queue
            database.enqueue_scrobble_retry('mal', 'update_episode', 52991, episode=9, error='HTTP 429', delay_seconds=0)
            queued = database.list_scrobble_retry_queue()
            self.assertEqual(len(queued), 1)
            self.assertEqual(queued[0]['service'], 'mal')

            with patch.object(WatchlistFlavor, 'watchlist_update_episode_for_flavor', return_value=True):
                drained = WatchlistFlavor.process_scrobble_retry_queue(limit=10)
                self.assertEqual(drained, 1)
            self.assertEqual(len(database.list_scrobble_retry_queue()), 0)

            # Test telemetry & drift routes
            res_tel = invoke_plugin_route('watchlist_telemetry')
            self.assertTrue(any('Multi-Tracker Watchlist Telemetry' in t['text'] for t in res_tel['textviewer_contents']))
            res_drift = invoke_plugin_route('watchlist_drift_auditor')
            self.assertTrue(any('Cross-Watchlist Drift Report' in t['text'] for t in res_drift['textviewer_contents']))

    # ── NF-02: Widget-Aware context.otaku.rpdev v1.0.46 Quick Actions ──────

    def test_nf02_widget_context_menu_resolution_and_new_actions(self):
        import xbmcgui
        with E2EHermeticEnv('22'):
            # Skin widget item without plugin:// path, carrying mal_id via ListItem property
            li = xbmcgui.ListItem('Frieren Widget', path='videodb://tvshows/titles/1/')
            li.setProperty('mal_id', '52991')
            li.getVideoInfoTag().setEpisode(7)

            self.assertEqual(
                invoke_context_action('seriesprofile', li),
                ['RunPlugin(plugin://plugin.video.otaku.rpdev/series_profile/52991)'],
            )
            self.assertEqual(
                invoke_context_action('manualsubtitles', li),
                ['RunPlugin(plugin://plugin.video.otaku.rpdev/search_subtitles)'],
            )
            self.assertEqual(
                invoke_context_action('markedaswatched', li),
                ['RunPlugin(plugin://plugin.video.otaku.rpdev/marked_as_watched/52991/7)'],
            )

    # ── NF-03: Filler & Recap Badges + Binge Auto-Skip Filler ──────────────

    def test_nf03_filler_and_recap_badges_and_binge_auto_skip(self):
        with E2EHermeticEnv('22'):
            from resources.lib import indexers
            from resources.lib.endpoints import anime_filler
            from resources.lib.ui import control, database, player, utils

            self.assertEqual(anime_filler.classify_filler_tag('Filler'), 'Filler')
            self.assertEqual(anime_filler.classify_filler_tag('Recap'), 'Recap')
            self.assertEqual(anime_filler.classify_filler_tag('Mostly Filler'), 'Filler')
            self.assertEqual(anime_filler.classify_filler_tag('Manga Canon'), '')

            control.setBool('interface.filler.badges', True)
            ep_filler = {
                'number': 5,
                'filler': 'Filler',
                'kodi_meta': database.dumps(utils.allocate_item('Ep 5', 'play/52991/5', False, True, [], '', {'title': 'Ep 5', 'episode': 5})),
            }
            ep_recap = {
                'number': 6,
                'filler': 'Recap',
                'kodi_meta': database.dumps(utils.allocate_item('Ep 6', 'play/52991/6', False, True, [], '', {'title': 'Ep 6', 'episode': 6})),
            }
            parsed_f = indexers.parse_episodes(ep_filler, 0)
            parsed_r = indexers.parse_episodes(ep_recap, 0)
            self.assertIn('[FILLER]', parsed_f['name'])
            self.assertIn('[RECAP]', parsed_r['name'])

            # Binge playlist filler auto-skip
            control.setBool('smartplay.skip_filler', True)
            control.playList.clear()
            wp = player.WatchlistPlayer()
            wp.mal_id = 52991
            wp.episode = 4
            wp.episodes = [
                ep_filler,
                {
                    'number': 6,
                    'filler': '',
                    'kodi_meta': database.dumps(utils.allocate_item('Ep 6 Canon', 'play/52991/6', False, True, [], '', {'title': 'Ep 6 Canon', 'episode': 6})),
                },
            ]
            with patch('resources.lib.AnimeSchedule.get_anime_schedule', return_value=None):
                wp.build_playlist()
            self.assertEqual(control.playList.size(), 1)
            item_entry = control.playList[0]
            item_url = item_entry[0] if isinstance(item_entry, tuple) else item_entry.getPath()
            self.assertIn('52991/6', item_url)

    # ── NF-07: Subtitle Intelligence v2 (SDH Stripping & Fallback) ─────────

    def test_nf07_sdh_tag_stripping_and_auto_download_fallback(self):
        with E2EHermeticEnv('22'), E2EMockServer() as srv:
            from resources.lib import subtitles
            from resources.lib.subtitles import download as sub_dl
            from resources.lib.subtitles.models import SubtitleResult, VideoMeta
            from resources.lib.ui import control

            raw_srt = (
                "1\n00:00:01,000 --> 00:00:03,000\n[dramatic music] FRIEREN: (sighs) Let us depart.\n\n"
                + "\n\n".join(f"{i}\n00:00:{i:02d},000 --> 00:00:{i:02d},500\nLine {i}" for i in range(2, 15))
            )
            cleaned = sub_dl.strip_sdh_hearing_impaired_tags(raw_srt)
            self.assertNotIn('[dramatic music]', cleaned)
            self.assertNotIn('(sighs)', cleaned)
            self.assertNotIn('FRIEREN:', cleaned)
            self.assertIn('Let us depart.', cleaned)

            # Multi-candidate fallback: candidate 1 returns HTML error, candidate 2 succeeds with SDH stripping
            control.setBool('subtitles.strip_sdh_tags', True)
            meta = VideoMeta(tvshow='Frieren', title='Frieren', season=1, episode=1, languages=['eng'], preferred_lang='eng')
            cand1 = SubtitleResult(service_name='opensubtitles', display_name='OpenSubtitles', name='Bad.01.srt', lang='English', lang_code='en', download_url=f'{srv.get_base_url()}/bad.srt', auto_identified=True)
            cand2 = SubtitleResult(service_name='subdl', display_name='SubDL', name='Good.01.srt', lang='English', lang_code='en', download_url=f'{srv.get_base_url()}/good.srt', auto_identified=True)

            mock_player_inst = MagicMock()
            mock_player_inst.isPlaying.return_value = True
            with patch('resources.lib.subtitles.search_subtitles', return_value=[cand1, cand2]), \
                 patch('resources.lib.subtitles.services.opensubtitles.OpenSubtitlesService.download', return_value=b'<html>502 Bad Gateway</html>'), \
                 patch('resources.lib.subtitles.services.subdl.SubDLService.download', return_value=raw_srt.encode('utf-8')), \
                 patch('xbmc.Player', return_value=mock_player_inst):
                ok = subtitles.auto_download_subtitles(meta=meta)

            self.assertTrue(ok)
            mock_player_inst.setSubtitles.assert_called_once()
            written_path = mock_player_inst.setSubtitles.call_args[0][0]
            with open(written_path, 'r', encoding='utf-8') as f:
                final_txt = f.read()
            self.assertNotIn('[dramatic music]', final_txt)
            self.assertIn('Let us depart.', final_txt)

    # ── Edge & Failure-Path Coverage Across NF-01..NF-08 ──────────────────

    def test_nf01_retry_after_header_backoff_and_max_attempts_pruning(self):
        with E2EHermeticEnv('22'):
            import time
            from resources.lib.ui import database
            from resources.lib.WatchlistFlavor import WatchlistFlavor

            t0 = int(time.time())
            ok = database.enqueue_scrobble_retry(
                'anilist', 'update_episode', 52991, episode=4, error='HTTP 429 Retry-After: 180', delay_seconds=60
            )
            self.assertTrue(ok)
            rows = database.list_scrobble_retry_queue()
            self.assertEqual(len(rows), 1)
            self.assertGreaterEqual(rows[0]['next_retry_at'], t0 + 180)
            self.assertEqual(rows[0]['attempts'], 1)

            # Force item due now and simulate failing replay -> attempts increments to 2
            with database.SQL(database.control.malSyncDB) as cur:
                cur.execute('UPDATE scrobble_retry_queue SET next_retry_at=0 WHERE mal_id=52991')
                cur.connection.commit()

            with patch.object(WatchlistFlavor, 'watchlist_update_episode_for_flavor', return_value=False):
                succeeded = WatchlistFlavor.process_scrobble_retry_queue(limit=10)
                self.assertEqual(succeeded, 0)
            rows2 = database.list_scrobble_retry_queue()
            self.assertEqual(len(rows2), 1)
            self.assertEqual(rows2[0]['attempts'], 2)

            # When attempts >= 5 and replay fails, entry is pruned from queue
            with database.SQL(database.control.malSyncDB) as cur:
                cur.execute('UPDATE scrobble_retry_queue SET attempts=5, next_retry_at=0 WHERE mal_id=52991')
                cur.connection.commit()
            with patch.object(WatchlistFlavor, 'watchlist_update_episode_for_flavor', return_value=False):
                WatchlistFlavor.process_scrobble_retry_queue(limit=10)
            self.assertEqual(len(database.list_scrobble_retry_queue()), 0)

    def test_nf02_widget_mal_id_fallback_from_infotag_uniqueid_and_missing_id_safety(self):
        import xbmcgui
        with E2EHermeticEnv('22'):
            # 1. InfoTagVideo uniqueID fallback
            li = xbmcgui.ListItem('Widget Item', path='videodb://movies/titles/9/')
            vtag = li.getVideoInfoTag()
            if hasattr(vtag, 'setUniqueIDs'):
                vtag.setUniqueIDs({'mal': '52991'})
            else:
                li.setProperty('mal_id', '52991')
            self.assertEqual(
                invoke_context_action('seriesprofile', li),
                ['RunPlugin(plugin://plugin.video.otaku.rpdev/series_profile/52991)'],
            )

            # 2. Missing mal_id returns empty command list without error
            li_empty = xbmcgui.ListItem('Unknown External Item', path='videodb://movies/titles/999/')
            self.assertEqual(invoke_context_action('seriesprofile', li_empty), [])

    def test_nf03_filler_auto_skip_preserves_playlist_when_all_remaining_are_filler(self):
        with E2EHermeticEnv('22'):
            from resources.lib.ui import control, database, player, utils

            control.setBool('smartplay.skip_filler', True)
            control.playList.clear()
            ep_filler_only = {
                'number': 5,
                'filler': 'Filler',
                'kodi_meta': database.dumps(utils.allocate_item('Ep 5', 'play/52991/5', False, True, [], '', {'title': 'Ep 5', 'episode': 5})),
            }
            wp = player.WatchlistPlayer()
            wp.mal_id = 52991
            wp.episode = 4
            wp.episodes = [ep_filler_only]
            with patch('resources.lib.AnimeSchedule.get_anime_schedule', return_value=None):
                wp.build_playlist()
            # Fallback keeps playlist intact when filtering would leave 0 items
            self.assertEqual(control.playList.size(), 1)

            # Per-series skip_filler_mode='keep' overrides global smartplay.skip_filler=True
            control.playList.clear()
            wp.series_override = {'skip_filler_mode': 'keep'}
            wp.episodes = [
                ep_filler_only,
                {
                    'number': 6,
                    'filler': '',
                    'kodi_meta': database.dumps(utils.allocate_item('Ep 6', 'play/52991/6', False, True, [], '', {'title': 'Ep 6', 'episode': 6})),
                },
            ]
            with patch('resources.lib.AnimeSchedule.get_anime_schedule', return_value=None):
                wp.build_playlist()
            self.assertEqual(control.playList.size(), 2)

    def test_nf04_circuit_breaker_tier3_cap_and_window_property_persistence(self):
        with E2EHermeticEnv('22'):
            from resources.lib.ui.domains import AdaptiveCircuitBreaker

            cb = AdaptiveCircuitBreaker(failure_threshold=1, cooldown_seconds=300)
            cb.reset()
            cb.record_failure('animetosho', category='torrent')  # Trip 1 -> 300s
            cb._cooldown_until['animetosho'] = 1.0
            self.assertTrue(cb.is_half_open('animetosho'))
            cb.record_failure('animetosho', category='torrent')  # Trip 2 -> 900s
            cb._cooldown_until['animetosho'] = 1.0
            self.assertTrue(cb.is_half_open('animetosho'))
            cb.record_failure('animetosho', category='torrent')  # Trip 3 -> 3600s
            snap = cb.get_snapshot()['animetosho']
            self.assertEqual(snap['trips'], 3)
            self.assertGreater(snap['remaining_s'], 3500)

            # Fresh instance loads persisted state from Window(10000)
            cb2 = AdaptiveCircuitBreaker(failure_threshold=1, cooldown_seconds=300)
            self.assertTrue(cb2.is_tripped('animetosho'))
            self.assertEqual(cb2.get_snapshot()['animetosho']['trips'], 3)

    def test_nf05_corrupted_live_mappings_db_restores_from_bak_on_sync_failure(self):
        with E2EHermeticEnv('22'), E2EMockServer() as srv:
            import service
            from resources.lib.ui import control, database

            dest_db = os.path.join(control.dataPath, 'mappings.db')
            bak_db = f"{dest_db}.bak"
            os.makedirs(control.dataPath, exist_ok=True)
            with sqlite3.connect(bak_db) as c:
                c.execute('CREATE TABLE anime (mal_id INTEGER PRIMARY KEY, kitsu_id INTEGER)')
                c.execute('INSERT INTO anime VALUES (52991, 46789)')
                c.commit()
            with open(dest_db, 'wb') as f:
                f.write(b'CORRUPTED_LIVE_DB_FILE')

            def _bad_handler(req_handler, method, path, parsed, headers, body):
                send_http_response(req_handler, 200, b'SQLite format 3\x00BROKEN_STAGE', 'application/octet-stream')
                return True

            srv._custom_handler = _bad_handler
            ok = service.update_mappings_db(url=f"{srv.get_base_url()}/bad.db")
            self.assertFalse(ok)
            ok_live, reason = database.verify_sqlite_integrity(dest_db)
            self.assertTrue(ok_live, reason)

    def test_nf06_episode_offset_isolated_to_scraper_and_never_alters_tracker_scrobble(self):
        with E2EHermeticEnv('22'):
            from resources.lib import MetaBrowser
            from resources.lib.ui import database, player

            database.update_show(52991, database.dumps({'name': 'Frieren', 'query': 'Frieren'}))
            database.set_series_override(52991, episode_offset=12)
            ov = database.get_series_override(52991)
            self.assertEqual(ov['episode_offset'], 12)

            captured_args = {}

            def _fake_helper(action_args):
                captured_args.update(action_args)
                return []

            with patch('resources.lib.pages.getSourcesHelper', side_effect=_fake_helper):
                MetaBrowser.get_sources(52991, '1', 'episode', rescrape=True)

            self.assertEqual(captured_args.get('episode'), '13')
            self.assertEqual(captured_args.get('canonical_episode'), '1')

            # WatchlistPlayer scrobbles canonical episode 1, never offset 13
            scrobbled = []
            wp = player.WatchlistPlayer()
            wp.mal_id = 52991
            wp.episode = 1
            wp.updated = False
            wp._watchlist_update = lambda mid, ep: (scrobbled.append((mid, ep)) or False)
            wp._update_watched_progress()
            self.assertEqual(scrobbled, [(52991, 1)])

    def test_nf06_series_overrides_exported_and_restored_in_settings_backup(self):
        with E2EHermeticEnv('22'):
            from resources.lib.ui import database, settings_manager

            database.set_series_override(
                52991,
                audio_lang='eng',
                sub_lang='eng',
                sub_mode='signs',
                preferred_provider='nyaa',
                intro_offset_s=3,
                outro_offset_s=-2,
                skip_filler_mode='skip',
                episode_offset=12,
            )
            with tempfile.TemporaryDirectory() as tmpdir:
                ok_exp, backup_path, _ = settings_manager.export_settings('all', tmpdir)
                self.assertTrue(ok_exp)
                database.delete_series_override(52991)
                self.assertIsNone(database.get_series_override(52991))

                ok_imp, _ = settings_manager.import_settings('all', backup_path)
                self.assertTrue(ok_imp)
                restored = database.get_series_override(52991)
                self.assertIsNotNone(restored)
                self.assertEqual(restored['audio_lang'], 'eng')
                self.assertEqual(restored['preferred_provider'], 'nyaa')
                self.assertEqual(restored['episode_offset'], 12)

    def test_nf07_and_nf08_sdh_ass_preserve_tags_and_drift_reconciler_dry_run_and_cancel(self):
        with E2EHermeticEnv('22') as env:
            from resources.lib.subtitles import download as sub_dl
            from resources.lib.ui import control, database
            from resources.lib.WatchlistFlavor import WatchlistFlavor

            ass_text = 'Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\an8}[wind howling] FERN: (gasps) Look ahead!'
            cleaned_ass = sub_dl.strip_sdh_hearing_impaired_tags(ass_text)
            self.assertIn('{\\an8}', cleaned_ass)
            self.assertNotIn('[wind howling]', cleaned_ass)
            self.assertNotIn('FERN:', cleaned_ass)
            self.assertIn('Look ahead!', cleaned_ass)

            # Drift dry-run count and cancelled confirmation
            control.setBool('anilist.enabled', True)
            control.setSetting('anilist.token', 't1')
            control.setBool('mal.enabled', True)
            control.setSetting('mal.token', 't2')
            database.save_watchlist_cache('anilist', 'CURRENT', [
                {'media': {'idMal': 52991, 'title': {'english': 'Frieren'}, 'episodes': 28}, 'progress': 10, 'updatedAt': 1700000200},
            ])
            database.save_watchlist_cache('mal', 'watching', [
                {'node': {'id': 52991, 'title': 'Frieren', 'num_episodes': 28}, 'list_status': {'num_episodes_watched': 6, 'updated_at': '2026-11-20T10:00:00Z'}},
            ])
            drifts = WatchlistFlavor.compute_watchlist_drift()
            self.assertEqual(WatchlistFlavor.reconcile_watchlist_drift(drifts, dry_run=True), 1)

            env.dialog_capture.yesno_response = False
            with patch.object(WatchlistFlavor, 'watchlist_update_episode_for_flavor', return_value=True) as mock_upd:
                res = invoke_plugin_route('watchlist_drift_auditor', params={'reconcile': 'true'})
                mock_upd.assert_not_called()
            self.assertTrue(any('Dry-Run Planned Mutations: 1' in t['text'] for t in res['textviewer_contents']))


if __name__ == '__main__':
    unittest.main()
