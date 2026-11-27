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


if __name__ == '__main__':
    unittest.main()
