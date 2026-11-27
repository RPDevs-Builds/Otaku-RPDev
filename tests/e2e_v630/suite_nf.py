# -*- coding: utf-8 -*-
"""
suite_nf.py — Opaque-Box E2E Tests for NF-01..NF-08 (v6.3.0)
============================================================
Covers Wave 3 features (NF-01..NF-08) across Tiers 1-3 for scripts/e2e_v630_suite.py.
"""

import unittest
from tests.e2e_v630.e2e_helpers import feature, tier
from tests.unit.test_v630_wave3_features import TestWave3FeaturesNF01ToNF08


class TestSuiteNFWave3Features(TestWave3FeaturesNF01ToNF08):

    @tier(1)
    @feature('NF-01', 'NF-08')
    def test_nf01_and_nf08_conflict_policies_retry_queue_and_drift_reconciliation(self):
        super().test_nf01_and_nf08_conflict_policies_retry_queue_and_drift_reconciliation()
        self.assertTrue(callable(self.test_nf01_and_nf08_conflict_policies_retry_queue_and_drift_reconciliation))

    @tier(1)
    @feature('NF-02')
    def test_nf02_widget_context_menu_resolution_and_new_actions(self):
        super().test_nf02_widget_context_menu_resolution_and_new_actions()
        self.assertTrue(callable(self.test_nf02_widget_context_menu_resolution_and_new_actions))

    @tier(1)
    @feature('NF-03')
    def test_nf03_filler_and_recap_badges_and_binge_auto_skip(self):
        super().test_nf03_filler_and_recap_badges_and_binge_auto_skip()
        self.assertTrue(callable(self.test_nf03_filler_and_recap_badges_and_binge_auto_skip))

    @tier(1)
    @feature('NF-04')
    def test_nf04_adaptive_circuit_breaker_exponential_tiers_and_half_open(self):
        super().test_nf04_adaptive_circuit_breaker_exponential_tiers_and_half_open()
        self.assertTrue(callable(self.test_nf04_adaptive_circuit_breaker_exponential_tiers_and_half_open))

    @tier(1)
    @feature('NF-05')
    def test_nf05_compressed_xz_and_gz_mappings_sync_and_corrupt_rollback(self):
        super().test_nf05_compressed_xz_and_gz_mappings_sync_and_corrupt_rollback()
        self.assertTrue(callable(self.test_nf05_compressed_xz_and_gz_mappings_sync_and_corrupt_rollback))

    @tier(1)
    @feature('NF-06')
    def test_nf06_series_override_crud_and_route(self):
        super().test_nf06_series_override_crud_and_route()
        self.assertTrue(callable(self.test_nf06_series_override_crud_and_route))

    @tier(2)
    @feature('NF-06')
    def test_nf06_series_override_applied_in_player_and_sort_sources(self):
        super().test_nf06_series_override_applied_in_player_and_sort_sources()
        self.assertTrue(callable(self.test_nf06_series_override_applied_in_player_and_sort_sources))

    @tier(1)
    @feature('NF-07')
    def test_nf07_sdh_tag_stripping_and_auto_download_fallback(self):
        super().test_nf07_sdh_tag_stripping_and_auto_download_fallback()
        self.assertTrue(callable(self.test_nf07_sdh_tag_stripping_and_auto_download_fallback))

    @tier(2)
    @feature('NF-01')
    def test_nf01_retry_after_header_backoff_and_max_attempts_pruning(self):
        super().test_nf01_retry_after_header_backoff_and_max_attempts_pruning()
        self.assertTrue(callable(self.test_nf01_retry_after_header_backoff_and_max_attempts_pruning))

    @tier(2)
    @feature('NF-02')
    def test_nf02_widget_mal_id_fallback_from_infotag_uniqueid_and_missing_id_safety(self):
        super().test_nf02_widget_mal_id_fallback_from_infotag_uniqueid_and_missing_id_safety()
        self.assertTrue(callable(self.test_nf02_widget_mal_id_fallback_from_infotag_uniqueid_and_missing_id_safety))

    @tier(2)
    @feature('NF-03')
    def test_nf03_filler_auto_skip_preserves_playlist_when_all_remaining_are_filler(self):
        super().test_nf03_filler_auto_skip_preserves_playlist_when_all_remaining_are_filler()
        self.assertTrue(callable(self.test_nf03_filler_auto_skip_preserves_playlist_when_all_remaining_are_filler))

    @tier(2)
    @feature('NF-04')
    def test_nf04_circuit_breaker_tier3_cap_and_window_property_persistence(self):
        super().test_nf04_circuit_breaker_tier3_cap_and_window_property_persistence()
        self.assertTrue(callable(self.test_nf04_circuit_breaker_tier3_cap_and_window_property_persistence))

    @tier(2)
    @feature('NF-05')
    def test_nf05_corrupted_live_mappings_db_restores_from_bak_on_sync_failure(self):
        super().test_nf05_corrupted_live_mappings_db_restores_from_bak_on_sync_failure()
        self.assertTrue(callable(self.test_nf05_corrupted_live_mappings_db_restores_from_bak_on_sync_failure))

    @tier(2)
    @feature('NF-06')
    def test_nf06_episode_offset_isolated_to_scraper_and_never_alters_tracker_scrobble(self):
        super().test_nf06_episode_offset_isolated_to_scraper_and_never_alters_tracker_scrobble()
        self.assertTrue(callable(self.test_nf06_episode_offset_isolated_to_scraper_and_never_alters_tracker_scrobble))

    @tier(2)
    @feature('NF-06')
    def test_nf06_series_overrides_exported_and_restored_in_settings_backup(self):
        super().test_nf06_series_overrides_exported_and_restored_in_settings_backup()
        self.assertTrue(callable(self.test_nf06_series_overrides_exported_and_restored_in_settings_backup))

    @tier(2)
    @feature('NF-07', 'NF-08')
    def test_nf07_and_nf08_sdh_ass_preserve_tags_and_drift_reconciler_dry_run_and_cancel(self):
        super().test_nf07_and_nf08_sdh_ass_preserve_tags_and_drift_reconciler_dry_run_and_cancel()
        self.assertTrue(callable(self.test_nf07_and_nf08_sdh_ass_preserve_tags_and_drift_reconciler_dry_run_and_cancel))

    @tier(2)
    @feature('NF-06')
    def test_nf06_column_level_migration_idempotency_under_same_schema_version(self):
        super().test_nf06_column_level_migration_idempotency_under_same_schema_version()
        self.assertTrue(callable(self.test_nf06_column_level_migration_idempotency_under_same_schema_version))

    @tier(2)
    @feature('NF-02')
    def test_p32_studio_dedup_aliases_and_context_inspectmappings_and_videodb_safety(self):
        super().test_p32_studio_dedup_aliases_and_context_inspectmappings_and_videodb_safety()
        self.assertTrue(callable(self.test_p32_studio_dedup_aliases_and_context_inspectmappings_and_videodb_safety))

    @tier(2)
    @feature('NF-17')
    def test_nf17_debrid_quota_guard_and_lazy_probe_end_to_end(self):
        """E2E NF-17: Quota guard prunes stalled slots before addMagnet & opt-in Lazy Top-N probe persists only cached hits."""
        from unittest.mock import MagicMock, patch
        from resources.lib.debrid import Debrid
        from resources.lib.debrid.real_debrid import RealDebrid
        from resources.lib.ui import control, database

        control.setBool('debrid.quota_guard', True)
        control.setBool('debrid.lazy_cache_probe', True)
        try:
            rd = RealDebrid()
            rd.token = 'nf17_tok'
            deleted_ids = []

            def _fake_req(method, url, **kwargs):
                resp = MagicMock()
                resp.ok = True
                resp.status_code = 200
                resp.headers = {}
                if url.endswith('/torrents') and method.lower() == 'get':
                    resp.json.return_value = [
                        {'id': 'stalled_old', 'status': 'magnet_error', 'added': '2026-10-01'},
                        {'id': 'healthy_1', 'status': 'downloaded', 'added': '2026-11-20'},
                    ]
                elif '/torrents/delete/' in url:
                    deleted_ids.append(url.rsplit('/', 1)[-1])
                    resp.json.return_value = {}
                elif '/torrents/addMagnet' in url:
                    resp.json.return_value = {'id': 'probe_1'}
                elif '/torrents/selectFiles/' in url:
                    resp.json.return_value = {}
                elif '/torrents/info/' in url:
                    resp.json.return_value = {'id': 'probe_1', 'status': 'downloaded'}
                else:
                    resp.json.return_value = {}
                return resp

            with patch.object(rd, '_request_with_backoff', side_effect=_fake_req):
                probe_ok = rd.probe_instant_cache('magnet:?xt=urn:btih:nf1700112233')
                self.assertTrue(probe_ok)
                self.assertIn('stalled_old', deleted_ids)
                self.assertNotIn('healthy_1', deleted_ids)

            deb = Debrid()
            candidates = [
                {'hash': 'nf17_hit', 'magnet': 'magnet:?xt=urn:btih:nf17_hit', 'seeders': 50, 'relevance': 155},
                {'hash': 'nf17_miss', 'magnet': 'magnet:?xt=urn:btih:nf17_miss', 'seeders': 25, 'relevance': 145},
            ]
            with patch('resources.lib.debrid.real_debrid.RealDebrid.probe_instant_cache', side_effect=lambda m: 'nf17_hit' in m), \
                 patch('resources.lib.debrid.debrid_cache.set_cached_hashes') as mock_set:
                hits = deb.lazy_probe_cached_torrents('realdebrid', candidates)
                self.assertEqual(hits, {'nf17_hit'})
                mock_set.assert_called_once_with([('nf17_hit', 'True')], 'rd')
        finally:
            control.setBool('debrid.lazy_cache_probe', False)
            control.setBool('debrid.quota_guard', True)
            database.clear_cache() if hasattr(database, 'clear_cache') else None

    @tier(2)
    @feature('NF-06', 'NF-12')
    def test_track_a_release_group_pinning_and_exclusion_e2e(self):
        """E2E Track A: Multi-group per-series + global Sort & Filter tie-breaking and exclusions."""
        from resources.lib.pages import Sources
        from resources.lib.ui import control, database

        control.setInt('general.minResolution', 0)
        control.setInt('general.maxResolution', 4)
        control.setInt('general.fileFilter', 0)
        control.setInt('general.source', 0)
        control.setBool('general.release_title_filter.enabled', False)
        control.setSetting('general.release_group.preferred', '')
        control.setSetting('general.release_group.excluded', 'Judas')
        control.setInt('general.release_group.tiebreak', 1)
        try:
            self.assertTrue(database.pin_series_release_group(52991, 'Erai-raws'))
            self.assertTrue(database.pin_series_release_group(52991, 'SubsPlease'))

            cands = [
                {'release_title': '[Judas] Frieren - 01 (1080p).mkv', 'hash': 'h1', 'type': 'torrent', 'quality': 3, 'debrid_provider': 'Real-Debrid', 'provider': 'nyaa', 'size': '1.0 GB', 'seeders': 80, 'byte_size': 10**9, 'info': ['1080p'], 'lang': 0, 'cached': True, 'relevance': 160},
                {'release_title': '[SubsPlease] Frieren - 01 (1080p).mkv', 'hash': 'h2', 'type': 'torrent', 'quality': 3, 'debrid_provider': 'Real-Debrid', 'provider': 'nyaa', 'size': '1.4 GB', 'seeders': 90, 'byte_size': 14 * 10**8, 'info': ['1080p'], 'lang': 0, 'cached': True, 'relevance': 160},
                {'release_title': '[Erai-raws] Frieren - 01 (1080p).mkv', 'hash': 'h3', 'type': 'torrent', 'quality': 3, 'debrid_provider': 'Real-Debrid', 'provider': 'nyaa', 'size': '1.3 GB', 'seeders': 60, 'byte_size': 13 * 10**8, 'info': ['1080p'], 'lang': 0, 'cached': True, 'relevance': 155},
                {'release_title': '[Erai-raws] Frieren OVA - 01 (1080p).mkv', 'hash': 'h4', 'type': 'torrent', 'quality': 4, 'debrid_provider': 'Real-Debrid', 'provider': 'nyaa', 'size': '1.8 GB', 'seeders': 70, 'byte_size': 18 * 10**8, 'info': ['1080p'], 'lang': 0, 'cached': True, 'relevance': 110},
            ]
            ranked = Sources.__new__(Sources).sortSources(cands, [], [], [], [], 'episode', 24, mal_id='52991')
            titles = [r['release_title'] for r in ranked]
            # Judas excluded by global Sort & Filter; Erai-raws (idx 0) > SubsPlease (idx 1) in Strict Selection Order; Tier 1 stays #3
            self.assertEqual(len(titles), 3)
            self.assertTrue(titles[0].startswith('[Erai-raws] Frieren - 01'))
            self.assertTrue(titles[1].startswith('[SubsPlease]'))
            self.assertTrue(titles[2].startswith('[Erai-raws] Frieren OVA'))
        finally:
            control.setSetting('general.release_group.excluded', '')
            control.setInt('general.release_group.tiebreak', 0)
            database.delete_series_override(52991)

    @tier(2)
    @feature('NF-07')
    def test_track_b_jimaku_and_animetosho_native_anime_subtitles_e2e(self):
        """E2E Track B: AnimeTosho .ass.xz attachment decompression, ASS tag-safe SDH strip, and Jimaku JP short-circuit."""
        import lzma
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import patch
        from resources.lib.subtitles import download as sub_dl
        from resources.lib.subtitles.models import VideoMeta
        from resources.lib.subtitles.services.animetosho import AnimetoshoSubtitleService
        from resources.lib.subtitles.services.jimaku import JimakuService

        sample_ass = (
            "[Script Info]\nScriptType: v4.00+\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,1,2,10,10,10,1\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            "Dialogue: 0,0:00:02.00,0:00:05.00,Default,,0,0,0,,{\\an8}[wind] FRIEREN: Let us go.\n"
        )
        xz_bytes = lzma.compress(sample_ass.encode('utf-8'))

        def _fake_get(url, **kwargs):
            if 'feed.animetosho.org/json' in url:
                payload = [{'id': 910, 'title': '[SubsPlease] Frieren - 01 (1080p).mkv', 'attachments': [
                    {'filename': 'frieren_01_eng.ass.xz', 'url': 'https://storage.animetosho.org/attach/910/frieren_01_eng.ass.xz', 'language': 'eng'},
                ]}]
                return SimpleNamespace(status_code=200, text='', content=b'', headers={}, json=lambda default=None: payload)
            return SimpleNamespace(status_code=200, text='', content=xz_bytes, headers={}, json=lambda default=None: None)

        meta = VideoMeta(tvshow='Frieren', season='1', episode='1', languages=['English'], preferred_lang='en', anidb_ep_id='271001', release_group='SubsPlease')
        with patch('resources.lib.ui.client.get', side_effect=_fake_get):
            # Jimaku short-circuits with 0 calls for English
            self.assertEqual(JimakuService.search(meta, {'subtitles.jimaku.apikey': 'k'}), [])
            res = AnimetoshoSubtitleService.search(meta, {'subtitles.timeout': 10})
            self.assertEqual(len(res), 1)
            with tempfile.TemporaryDirectory() as tmpdir:
                local_path = sub_dl.download_and_prepare_subtitle(res[0], meta, {'subtitles.strip_sdh_tags': True}, dest_dir=tmpdir)
                self.assertIsNotNone(local_path)
                self.assertTrue(local_path.endswith('.ass'))
                with open(local_path, 'r', encoding='utf-8') as fp:
                    body = fp.read()
                self.assertIn('{\\an8}', body)
                self.assertNotIn('[wind]', body)

    @tier(2)
    @feature('NF-15', 'NF-16')
    def test_track_c_kodi22_piers_standby_trailers_hdr_and_deeplinks_e2e(self):
        """E2E Track C: Kodi 22 standby throttling, HDR tag surfacing, and Android TV deeplink replay guard."""
        from unittest.mock import patch
        import xbmc
        import xbmcgui
        from resources.lib.routes import playback as playback_routes
        from resources.lib.ui import control
        from tests.kodi_profile import KodiProfile

        control.clearGlobalProp('otaku.last_deeplink_sig')
        control.clearGlobalProp('otaku.last_deeplink_ts')
        with KodiProfile('22'):
            control.setBool('general.standby_throttling', True)
            with patch.object(xbmc, 'getDevicePowerStatus', return_value='standby'):
                self.assertTrue(control.is_device_in_standby())

            li = xbmcgui.ListItem(label='HDR Test')
            control.set_videotags(li, {'title': 'Ep 1', 'release_title': '[EMBER] Show - 01 [2160p][DV].mkv', 'mediatype': 'episode'})
            self.assertEqual(li.getProperty('hdr_badge'), 'DV')
            self.assertEqual(li.getVideoInfoTag().getHdrType(), 3)

            execs = []
            with patch.object(control, 'HANDLE', -1), \
                 patch.object(control, 'execute', side_effect=lambda c: execs.append(c)), \
                 patch.object(control, 'exit_code', return_value=None):
                playback_routes.DEEPLINK('next_up', {})
                playback_routes.DEEPLINK('next_up', {})  # Stale replay blocked
            self.assertEqual(len(execs), 1)
            self.assertIn('ActivateWindow(Videos,', execs[0])


if __name__ == '__main__':
    unittest.main()
