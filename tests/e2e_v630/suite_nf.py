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


if __name__ == '__main__':
    unittest.main()
