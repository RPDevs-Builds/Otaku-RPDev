# Otaku-RPDev v6.3.0 QA Signoff Ledger (`docs/teamwork/sprints/v6.3.0/QA_SIGNOFF.md`)

**Target Release:** `plugin.video.otaku.rpdev v6.3.0` | `context.otaku.rpdev v1.0.46` | `service.subtitles.otaku.rpdev v1.0.3`  
**QA Auditor:** `qa-verifier` & `coordinator`  
**Signoff Status:** `SIGNED OFF & READY FOR RELEASE (LOCAL COMMITS STAGED; AWAITING USER APPROVAL TO PUSH)`

---

## 1. Pre-Sprint vs. Final `v6.3.0` Metrics

| Gate / Metric | Baseline (`v6.2.19`) | Target (`v6.3.0`) | Final Verified (`v6.3.0`) | Status |
|---|---|---|---|---|
| **Ruff (`E9,F63,F7,F82,F811,F405,F541`)** | 0 violations | 0 violations | **0 violations** | **PASS** |
| **`compileall` (All 3 Add-ons + Tests + Scripts)** | 0 errors | 0 errors | **0 errors** | **PASS** |
| **Offline Unit / Lint / Integration Tests** | 1,035 passing | `>= 1,080` total | **1,070 discover + 126 E2E (`1,196` total executions)** | **PASS** |
| **Strict Project Warnings (`Deprecation` / `Resource`)** | 0 warnings | 0 warnings | **0 warnings** | **PASS** |
| **Module Coverage (`audit_function_coverage.py`)** | 100.0% | 100.0% | **100.0% (`140/140` modules)** | **PASS** |
| **Function Coverage (`audit_function_coverage.py`)** | 64.85% | `>= 65.0%` | **66.01%** | **PASS** |
| **`AGENTS.md` Context Budget (`< 22,000` bytes)** | 16,462 bytes | `< 22,000` bytes | **16,743 bytes** | **PASS** |
| **ONN `10.13.0.16` Read-Only Log Cursor (`CONCERNS.md`)** | `433385` (Review #18) | Read-Only Only | **`433385` (0 writes to device)** | **PASS** |

---

## 2. Work Package Verification Checklist

- [x] **Wave 1 (`SP-01`..`SP-03` — Gate 1)**:
  - [x] `SP-01` Governance board & sprint docs synced (`#30999+` `strings.po` floor, `unittest` runner, `16,743` byte `AGENTS.md`, `--fail-below 65` Gate 3 target).
  - [x] `SP-02` `C-34` Zero-Wait `resolve_silent()` lead-candidate pruning and `C-35` `wlf_auth` modal disposal + 300s idle timeout verified under `KodiProfile('22', strict_skin_controls=True)`.
  - [x] `SP-03` Strictly read-only `scripts/audit_onn_logs.py` tested offline against fixture logs and read-only cursor; `--fast` / `qa_fast.py` / `.pre-commit-config.yaml` / Wave-1 AST guardrails / `special:` & `MagicMock` repo hygiene verified.
  - [x] **Gate 1:** `python3 scripts/verify_all.py` (`--fail-below 60`, 0 failures, 0 project warnings) — Committed in `94852b4`.
- [x] **Wave 2 (`CR-01`..`CR-05` — Gate 2)**:
  - [x] `CR-01`: 0 case-insensitive studio logo filename collisions across `context.otaku.rpdev/resources/images/studios/{coloured,white}/` (530 unique PNGs per style); root `poster.png` `112.8 KB` (`< 350 KB`) & `icon.png` `31.9 KB` (`< 150 KB`) across all 3 addons.
  - [x] `CR-02`: All static DB reads (`info.db`, `mappings.db`) use `?mode=ro` URI, `timeout=30.0`, inode-replacement detection, and non-creation guard when missing; `_quarantine_and_recover_db` uses `SyncDatabase`.
  - [x] `CR-03`: All `.doModal()` and `.run()` sites wrapped in `try...finally: dlg.close(); del dlg`, `C-06` resolved, and `service.subtitles.otaku.rpdev` documented across all 7 docs (`AGENTS.md < 22,000` bytes).
  - [x] `CR-04`: `ci.yml`, `release.yml`, `release_addon.py`, `test_kodi_installs.py` tri-addon packaging, `--fail-below 65` target parity, and dry-run ZIP build pass.
  - [x] `CR-05`: 0 blocking `time.sleep(...)` calls in runtime modules; all subtitle/skip/easynews API keys scrubbed by `control.sanitize_log()`.
- [x] **Wave 3a (`NF-04`, `NF-06`)**:
  - [x] `AdaptiveCircuitBreaker` tested across torrent, embed, subtitle, metadata, and debrid categories with exponential tiers (`300s` -> `900s` -> `3600s`) and half-open recovery probes.
  - [x] `series_overrides` SQLite table (`SCHEMA_VERSION = '1.0.14'`) and playback/scraper profile overrides verified.
- [x] **Wave 3b (`NF-01`, `NF-02`, `NF-03`, `NF-05`, `NF-07`, `NF-08` — Gate 3)**:
  - [x] `NF-05`: `mappings.db` `.xz`/`.gz` decompression, SHA-256 verification, `PRAGMA quick_check`, and `.bak` rollback verified.
  - [x] `NF-01`: Multi-tracker conflict resolution (`highest_progress`, `primary_wins`, `latest_updated`), persistent `scrobble_retry_queue`, and `watchlist_telemetry` route verified.
  - [x] `NF-08`: Cross-Watchlist Drift Auditor diff (`compute_watchlist_drift`) and 1-click reconciliation (`reconcile_watchlist_drift`, `watchlist_drift_auditor`) verified across MAL, AniList, Kitsu, Simkl, and local DB.
  - [x] `NF-02`: Widget-aware `context.otaku.rpdev` (`v1.0.46`) quick actions (`seriesprofile`, `manualsubtitles`, widget `mal_id` resolution) verified.
  - [x] `NF-03`: Filler/Recap episode badges (`interface.filler.badges`), binge auto-skip filler (`smartplay.skip_filler`), and OP/ED offset tuning verified.
  - [x] `NF-07`: Subtitle Intelligence v2 (`service.subtitles.otaku.rpdev v1.0.3`) multi-candidate fallback, SDH tag stripper (`subtitles.strip_sdh_tags`), and subtitle provider circuit breaker verified.
  - [x] **Gate 3:** `python3 scripts/verify_all.py --fail-below 65` + `python3 scripts/e2e_v630_suite.py` passed all silos + 5-stage `REVIEW_PROCESS.md` sign-off.
- [x] **Wave 4 (`QA-01` — Local E2E, Docs Sync & Release Readiness)**:
  - [x] `python3 scripts/verify_all.py --fail-below 65` passed all 4 silos on final `v6.3.0` state.
  - [x] `python3 scripts/test_kodi_installs.py --versions 21 22 --mode hermetic` (plus `E2E-Track` Tier 1–4 suite) passed on Flatpak Kodi 21.3 & Kodi 22.0-RC2 with 0 `ERROR`s / `Invalid setting type` / `g_directoryCache` / SWIG leaks.
  - [x] `docs/CONCERNS.md` updated (`FIXED_VERIFIED_LOCAL_E2E`), versions bumped (`6.3.0` / `1.0.46` / `1.0.3`), `--no-gpg-sign` commits staged locally (**zero commits or tags pushed until final user approval**).
  - [ ] **Post-Release Passive ONN `10.13.0.16` Checklist** (to run read-only after user updates ONN via Kodi repo):
    - [ ] `python3 scripts/audit_onn_logs.py --concerns docs/CONCERNS.md` confirms clean `v6.3.0` update, 0 `C-34`/`C-35` regressions, 0 Python tracebacks, and clean Zero-Wait / subtitle playback.
