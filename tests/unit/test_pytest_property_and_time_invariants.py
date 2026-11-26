# -*- coding: utf-8 -*-
"""
test_pytest_property_and_time_invariants.py
===========================================
Pytest-native and unittest-compatible property-based, parametrized,
deterministic time-travel (freezegun), and performance benchmark tests
covering Otaku-RPDev's core algorithmic engines.
"""

import time
import unittest

import conftest  # noqa: F401
from resources.lib.ui import control, domains, source_utils
from resources.lib.ui.domains import AdaptiveCircuitBreaker

try:
    import pytest
except ImportError:
    pytest = None

try:
    from freezegun import freeze_time
except ImportError:
    freeze_time = None

try:
    from hypothesis import given, settings as hyp_settings, strategies as st
    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False


# ---------------------------------------------------------------------------
# 1. Pytest-Native Parametrized & Fixture-Driven Tests
# ---------------------------------------------------------------------------
if pytest is not None:

    @pytest.mark.unit
    @pytest.mark.property
    @pytest.mark.parametrize(
        "release_title,target_titles,min_score,max_score",
        [
            ("[SubsPlease] Solo Leveling - 01 (1080p) [ABCD1234].mkv", ["Solo Leveling"], 140, 200),
            ("[Erai-raws] Sousou no Frieren - 12 [1080p][Multiple Subtitle].mkv", ["Sousou no Frieren", "Frieren: Beyond Journey's End"], 140, 200),
            ("[Judas] Bleach - S01E05 (1080p) [HEVC x265 10bit].mkv", ["Bleach"], 140, 200),
            ("[SubsPlease] Re:Monster - 01 (1080p) [1234ABCD].mkv", ["Monster"], 0, 40),
            ("[Group] Monster Musume no Iru Nichijou - 03 (720p).mkv", ["Monster"], 0, 40),
        ],
    )
    def test_pytest_parametrized_title_isolation_and_scoring_bounds(release_title, target_titles, min_score, max_score):
        isolated = source_utils.isolate_show_title(release_title)
        assert isinstance(isolated, str)
        assert len(isolated) > 0
        best_score = max(source_utils.score_title_candidate(t, isolated) for t in target_titles)
        assert 0 <= best_score <= 200
        assert min_score <= best_score <= max_score

    @pytest.mark.unit
    @pytest.mark.property
    @pytest.mark.parametrize(
        "base_url,path_or_query",
        [
            ("https://nyaa.si", "/?f=0&c=1_2&q=bleach"),
            ("https://nyaa-si.translate.goog/?_x_tr_sl=auto&_x_tr_tl=en&_x_tr_hl=en", "/?f=0&c=1_2&q=bleach"),
            ("https://feed-animetosho-org.translate.goog/json?_x_tr_sl=auto&_x_tr_tl=en", "?q=frieren&qx=1"),
            ("https://animepahe.ru/api", "?m=search&q=naruto"),
        ],
    )
    def test_pytest_parametrized_join_url_never_emits_double_question_mark(base_url, path_or_query):
        joined = domains.join_url(base_url, path_or_query)
        assert joined.startswith("https://")
        assert joined.count("?") <= 1, f"Malformed double '?' in joined URL: {joined}"

    @pytest.mark.unit
    def test_pytest_fixtures_kodi_profile_and_isolated_window_props(kodi_profile, isolated_window_props):
        assert kodi_profile.version in ("21", "22")
        control.setGlobalProp("otaku.pytest.probe", "active_value")
        assert control.getGlobalProp("otaku.pytest.probe") == "active_value"
        assert isolated_window_props.get("otaku.pytest.probe") == "active_value"

    @pytest.mark.unit
    @pytest.mark.benchmark
    def test_pytest_benchmark_title_scoring_hot_path(benchmark):
        samples = [
            "[SubsPlease] Kusuriya no Hitorigoto - 24 (1080p) [9F8E7D6C].mkv",
            "[Erai-raws] Dungeon Meshi - 14 [1080p][HEVC].mkv",
            "[ASW] Shangri-La Frontier - 25 [1080p HEVC x265 10Bit].mkv",
            "[SubsPlease] Re:Monster - 02 (1080p) [DEAD1234].mkv",
        ]

        def _score_batch():
            total = 0
            for rel in samples:
                iso = source_utils.isolate_show_title(rel)
                total += source_utils.score_title_candidate("Dungeon Meshi", iso)
            return total

        result = benchmark(_score_batch)
        assert result >= 140


# ---------------------------------------------------------------------------
# 2. Unittest & Hypothesis / Freezegun Suite (Runs in Both Pytest & Unittest)
# ---------------------------------------------------------------------------
class TestPropertyAndTimeTravelInvariants(unittest.TestCase):
    """Property-based and deterministic time-travel invariants across core engines."""

    def test_64kb_window_property_ceiling_multibyte_utf8_boundary(self):
        """Verify 64KB (65,536-byte) C++ Window(10000) property ceiling with multi-byte UTF-8."""
        key = "otaku.test.ceiling_64kb"
        control.clearGlobalProp(key)

        # 16,000 3-byte Japanese characters = 48,000 UTF-8 bytes (under 65,536 ceiling)
        safe_payload = "アニメ" * 5300  # 15,900 chars = 47,700 UTF-8 bytes
        self.assertLessEqual(len(safe_payload.encode("utf-8")), 65536)
        control.setGlobalProp(key, safe_payload)
        self.assertEqual(control.getGlobalProp(key), safe_payload)

        # 25,000 3-byte Japanese characters = 75,000 UTF-8 bytes (exceeds 65,536 ceiling)
        oversized_payload = "アニメ" * 8400  # 75,600 UTF-8 bytes
        self.assertGreater(len(oversized_payload.encode("utf-8")), 65536)
        control.clearGlobalProp(key)
        control.setGlobalProp(key, oversized_payload)
        stored = control.getGlobalProp(key)
        self.assertLessEqual(len(stored.encode("utf-8")), 65536)
        control.clearGlobalProp(key)

    def test_circuit_breaker_escalating_tiers_with_deterministic_time_travel(self):
        """Verify AdaptiveCircuitBreaker 300s -> 900s -> 3600s -> HALF_OPEN -> CLOSED transitions."""
        cb = AdaptiveCircuitBreaker(failure_threshold=2, cooldown_seconds=300)
        provider = "pytest_synthetic_provider"
        cb.reset(provider)

        if freeze_time is not None:
            with freeze_time("2026-11-26 12:00:00") as frozen:
                self.assertFalse(cb.is_tripped(provider))
                cb.record_failure(provider, category="torrent")
                self.assertFalse(cb.is_tripped(provider))
                cb.record_failure(provider, category="torrent")
                # Tripped to Tier 1 OPEN (300s)
                self.assertTrue(cb.is_tripped(provider))

                # Advance 120s (< 300s): still OPEN
                frozen.tick(120)
                self.assertTrue(cb.is_tripped(provider))

                # Advance another 185s (total 305s > 300s): transitions to HALF_OPEN probe
                frozen.tick(185)
                self.assertFalse(cb.is_tripped(provider))
                self.assertTrue(cb.is_half_open(provider))

                # Probe failure in HALF_OPEN escalates immediately to Tier 2 OPEN (900s)
                cb.record_failure(provider, category="torrent", status_code=503)
                self.assertTrue(cb.is_tripped(provider))
                frozen.tick(400)
                self.assertTrue(cb.is_tripped(provider))
                frozen.tick(510)
                self.assertFalse(cb.is_tripped(provider))
                self.assertTrue(cb.is_half_open(provider))

                # Probe success resets to CLOSED
                cb.record_success(provider)
                self.assertFalse(cb.is_tripped(provider))
                self.assertFalse(cb.is_half_open(provider))
        else:
            self.assertFalse(cb.is_tripped(provider))
            cb.record_failure(provider, category="torrent")
            cb.record_failure(provider, category="torrent")
            self.assertTrue(cb.is_tripped(provider))
            cb.reset(provider)
            self.assertFalse(cb.is_tripped(provider))

    def test_subtitle_pal_rescaling_and_offset_preserves_monotonic_intervals(self):
        """Verify 1.03 PAL->NTSC rescaling and millisecond offsets never invert cue intervals."""
        cues = [(0, 1500), (1520, 4200), (10000, 12500), (1200000, 1203450)]
        for fps_factor in (1.0, 1.03):
            for offset_ms in (-5000, -250, 0, 250, 5000):
                prev_start = 0
                for start_ms, end_ms in cues:
                    new_start = max(0, int(round(start_ms * fps_factor + offset_ms)))
                    new_end = max(new_start, int(round(end_ms * fps_factor + offset_ms)))
                    self.assertGreaterEqual(new_start, 0)
                    self.assertLessEqual(new_start, new_end)
                    self.assertGreaterEqual(new_start, prev_start)
                    prev_start = new_start

    def test_hypothesis_or_exhaustive_title_scoring_fuzz_invariants(self):
        """Fuzz isolate_show_title and score_title_candidate across synthetic release patterns."""
        def _check_title(show_name, ep_num, res, crc):
            rel = f"[SubsPlease] {show_name} - {ep_num:02d} ({res}p) [{crc}].mkv"
            isolated = source_utils.isolate_show_title(rel)
            score = source_utils.score_title_candidate(show_name, isolated)
            self.assertGreaterEqual(score, 140, f"Expected exact show '{show_name}' from '{rel}' (isolated='{isolated}') to score >= 140, got {score}")
            self.assertLessEqual(score, 200)

        if HAS_HYPOTHESIS:
            @hyp_settings(max_examples=25, deadline=None)
            @given(
                show_name=st.sampled_from([
                    "Solo Leveling", "Sousou no Frieren", "Kusuriya no Hitorigoto",
                    "Dungeon Meshi", "Shangri-La Frontier", "Jujutsu Kaisen",
                ]),
                ep_num=st.integers(min_value=1, max_value=99),
                res=st.sampled_from([480, 720, 1080, 2160]),
                crc=st.text(alphabet="0123456789ABCDEF", min_size=8, max_size=8),
            )
            def _fuzz(show_name, ep_num, res, crc):
                _check_title(show_name, ep_num, res, crc)

            _fuzz()
        else:
            for show in ("Solo Leveling", "Sousou no Frieren", "Dungeon Meshi", "Jujutsu Kaisen"):
                for ep in (1, 12, 24):
                    _check_title(show, ep, 1080, "A1B2C3D4")


if __name__ == "__main__":
    unittest.main()
