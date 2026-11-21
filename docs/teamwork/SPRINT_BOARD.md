# Otaku-RPDev v6.3.0 Master Sprint Board (`docs/teamwork/SPRINT_BOARD.md`)

Tracks all 16 work packages (`SP-01`–`SP-03`, `CR-01`–`CR-05`, `NF-01`–`NF-08`), parallel `E2E-Track`, and `QA-01` (plus live ONN Review #18 items `C-34`, `C-35`) across 4 execution waves (+ parallel `E2E_testing_track`).

---

## Wave Summary & Status Ledger

| ID | Wave | Category | Title | Owner | Target Files | Verification Gate | Status |
|---|---|---|---|---|---|---|---|
| **SP-01** | Wave 1 (`M1`) | Diagnostics | Read-Only ONN `10.13.0.16` Real-Usage Log Audit (Review #18, offset `433385`) & Governance Board Sync | `wave1-foundation` | `docs/CONCERNS.md` (cursor preserved), `docs/teamwork/*` | `test_docs_and_customizations.py` | **DONE** |
| **SP-02** | Wave 1 (`M1`) | Diagnostics | Open Concerns Closure (`C-34` Zero-Wait `resolve_silent` pruning & `C-35` `wlf_auth` modal disposal/idle timeout) | `wave1-foundation` | `windows/resolver.py`, `ui/player.py`, `WatchlistIntegration.py`, `windows/wlf_auth.py`, `tests/unit/test_c34_c35_regressions.py` | `test_c34_c35_regressions.py`, `test_windowxml_event_dispatch.py` | **DONE** |
| **SP-03** | Wave 1 (`M1`) | Tooling & QA | Read-Only ONN Log Auditor (`scripts/audit_onn_logs.py`), Fast QA Runner, `.pre-commit-config.yaml`, Wave-1 AST Guardrails & Repo Hygiene | `wave1-foundation` | `scripts/audit_onn_logs.py`, `scripts/verify_all.py`, `scripts/qa_fast.py`, `.pre-commit-config.yaml`, `tests/conftest.py`, `.gitignore`, `tests/lint/test_ast_integrity.py`, `tests/unit/test_audit_onn_logs.py` | `verify_all.py` (Gate 1 `--fail-below 60`) | **DONE** |
| **CR-01** | Wave 2 (`M2`) | Asset Hygiene | Studio Case-Collision Deduplication (41 groups incl. `8-Bit`/`8-bit`/`8bit`) & `poster.png` (`<350 KB`)/`icon.png` (`<150 KB`) Optimization | `wave2-hardening` | `context.otaku.rpdev/resources/images/studios/{coloured,white}/*`, `*/poster.png`, `*/icon.png`, `tests/lint/test_ast_integrity.py` | `test_ast_integrity.py`, `suite_cr.py` | **DONE** |
| **CR-02** | Wave 2 (`M2`) | SQLite Parity | `v6.2.x` SQLite WAL / Read-Only URI Parity Across All 3 Add-ons & E2E Harness | `wave2-hardening` | `ui/database.py`, `context.otaku.rpdev/default.py`, `scripts/test_kodi_installs.py` | `test_database_concurrency.py`, `suite_cr.py` | **DONE** |
| **CR-03** | Wave 2 (`M2`) | Compliance | Tri-Addon Kodi 21/22 Compliance, Modal Disposal Sweep, `C-06` & Documentation Sync (`service.subtitles.otaku.rpdev`) | `wave2-hardening` | `AGENTS.md` (`<22 KB`), `CHANGEREPORT.md`, `docs/*.md`, `routes/tools.py`, `service.py` | `test_docs_and_customizations.py`, `suite_cr.py` | **DONE** |
| **CR-04** | Wave 2 (`M2`) | CI / Release | Tri-Addon Packaging, `.github/workflows/{ci,release}.yml` (`--fail-below 65` target parity), Dry-Run ZIP & Kodi Manifest Validation | `wave2-hardening` | `.github/workflows/{ci,release}.yml`, `scripts/release_addon.py`, `scripts/test_kodi_installs.py` | `verify_all.py`, dry-run tri-addon ZIP build | **DONE** |
| **CR-05** | Wave 2 (`M2`) | Transport & Abort | `v6.2.x` Abort-Safe `waitForAbort` Sweep (11 blocking sleeps) & `sanitize_log` Secret Key Expansion | `wave2-hardening` | `AnimeSchedule.py`, `endpoints/mal.py`, `indexers/{kitsu,anidb,otaku,jikanmoe}.py`, `ui/control.py` | `test_ast_integrity.py`, `suite_cr.py` | **DONE** |
| **NF-04** | Wave 3a (`M3a`) | Core Resilience | Unified Adaptive Circuit Breaker Across Torrent, Embed, Subtitle, Metadata & Debrid Providers | `wave3-core` | `ui/domains.py`, `pages/__init__.py`, `routes/tools.py` | `test_v630_wave3_features.py`, `suite_nf.py` | **DONE** |
| **NF-06** | Wave 3a (`M3a`) | Personalization | Per-Series Override Profiles (`series_overrides` SQLite Table, `SCHEMA_VERSION = '1.0.14'`, Dialog & Player/Sort Wiring) | `wave3-core` | `ui/database.py`, `ui/database_sync.py`, `ui/player.py`, `pages/__init__.py`, `routes/tools.py` | `test_v630_wave3_features.py`, `suite_nf.py` | **DONE** |
| **NF-05** | Wave 3b (`M3b`) | Data Integrity | Compressed `.xz`/`.gz` + SHA-256 + `PRAGMA quick_check` + `.bak` Rollback for `mappings.db` | `wave3-features` | `service.py`, `ui/database.py`, `routes/tools.py` | `test_v630_wave3_features.py`, `suite_nf.py` | **DONE** |
| **NF-01** | Wave 3b (`M3b`) | Watchlists | Multi-Tracker Conflict Engine + Persistent 429 Scrobble Retry Queue + Telemetry Inspector | `wave3-features` | `WatchlistIntegration.py`, `WatchlistFlavor/*`, `ui/database.py`, `ui/database_sync.py`, `service.py`, `routes/tools.py` | `test_v630_wave3_features.py`, `suite_nf.py` | **DONE** |
| **NF-08** | Wave 3b (`M3b`) | Watchlists | Cross-Watchlist Drift Auditor & 1-Click Reconciliation Across AniList, MAL, Kitsu, Simkl & Local DB | `wave3-features` | `WatchlistIntegration.py`, `routes/tools.py`, `ui/database.py` | `test_v630_wave3_features.py`, `suite_nf.py` | **DONE** |
| **NF-02** | Wave 3b (`M3b`) | Context Menu | Widget-Aware `context.otaku.rpdev` (`v1.0.46`) Quick Actions (Series Profile, Subtitles, Widget ID Resolution) | `wave3-features` | `context.otaku.rpdev/{addon.xml,default.py}`, `ui/control.py`, `routes/subtitles.py`, `resources/settings.xml` | `test_v630_wave3_features.py`, `suite_nf.py` | **DONE** |
| **NF-03** | Wave 3b (`M3b`) | Playback UX | Filler/Recap Episode Badges + Binge Auto-Skip Filler + Per-Series OP/ED Skip Offset Tuning | `wave3-features` | `endpoints/anime_filler.py`, `indexers/__init__.py`, `ui/player.py`, `resources/settings.xml` | `test_v630_wave3_features.py`, `suite_nf.py` | **DONE** |
| **NF-07** | Wave 3b (`M3b`) | Subtitles v2 | Subtitle Intelligence v2 (Multi-Candidate Download Fallback, SDH Tag Stripper, Provider Health Breaker) | `wave3-features` | `subtitles/{__init__,download,search}.py`, `service.subtitles.otaku.rpdev/addon.xml` (`v1.0.3`) | `test_v630_wave3_features.py`, `suite_nf.py` | **DONE** |
| **E2E-Track** | Parallel (`E2E`) | E2E Testing | Opaque-Box Tier 1–4 E2E Test Infrastructure & Suite (`suite_sp.py`, `suite_cr.py`, `suite_nf.py` — 110 tests) | `e2e-track` | `scripts/e2e_v630_suite.py`, `tests/e2e_v630/*` | `110/110` passing | **DONE** |
| **QA-01** | Wave 4 (`M4`) | Release Gate | Unified Pre-Flight (`--fail-below 65`, `1,062` unit + `110` E2E tests = `1,172` total) + Headless Kodi 21/22 E2E + Docs Sync + `--no-gpg-sign` Local Commit Staging (No Push Until Final User Approval) | `qa-verifier` & `coordinator` | `scripts/verify_all.py`, `scripts/test_kodi_installs.py`, `docs/CONCERNS.md`, `CHANGEREPORT.md`, `changelog.txt`, `news.txt`, `README.md`, `QA_SIGNOFF.md` | Full 4-Tier `TESTING_PROCESS.md` | **DONE** |

---

## Wave & Gate Schedule

| Milestone | Wave | Scope | Exit Gate | Status |
|---|---|---|---|---|
| `M1_wave1_diagnostics_qa` | Wave 1 | `SP-01`, `SP-02`, `SP-03` + repo hygiene | **Gate 1**: `python3 scripts/verify_all.py` (`--fail-below 60`, 0 failures, 0 project warnings) | **DONE** |
| `M2_wave2_hardening` | Wave 2 | `CR-01`..`CR-05` | **Gate 2**: `verify_all.py` + `kodi-addon-checker`/manifest check + dry-run tri-addon ZIP build, 0 case collisions, 0 circular deps, 100% module coverage | **DONE** |
| `M3a_wave3_core_infra` | Wave 3a | `NF-04`, `NF-06` | `SyncDatabase` `1.0.14` + `AdaptiveCircuitBreaker` green | **DONE** |
| `M3b_wave3_parallel_features` | Wave 3b | `NF-01`, `NF-02`, `NF-03`, `NF-05`, `NF-07`, `NF-08` | **Gate 3**: `python3 scripts/verify_all.py --fail-below 65` (`>=1,080` combined tests, 5-stage `REVIEW_PROCESS.md`) | **DONE** |
| `E2E_testing_track` | Parallel | `E2E-Track` (Tiers 1–4, 110 tests) | `scripts/e2e_v630_suite.py` green | **DONE** |
| `M4_wave4_e2e_release` | Wave 4 | `QA-01` (Local Kodi 21/22 E2E, Tier 5 adversarial, docs sync, local `--no-gpg-sign` staging; **no push until approval**) | `QA_SIGNOFF.md` signed + release-readiness dossier | **DONE** |
