# Otaku-RPDev v6.3.0 Granular Task Checklist (`docs/teamwork/sprints/v6.3.0/TASKS.md`)

Exhaustive file-level implementation and test verification checklist for `/teamwork` execution of **Otaku-RPDev v6.3.0**.

---

## Wave 1: Diagnostics, Open Concerns Closure & QA Foundation (`M1_wave1_diagnostics_qa`)

- [x] **SP-01: Read-Only ONN `10.13.0.16` Log Review #18 (`offset=225187` $\rightarrow$ `433385`) & Governance Sync**
  - Cataloged 8-hour overnight session (`1,692` lines) in [CONCERNS.md](../../../CONCERNS.md), verified `C-30`, `C-32`, `C-33` resolved in production, and logged `C-34` & `C-35`.
  - Synchronized `docs/teamwork/SPRINT_BOARD.md`, `TASKS.md`, `QA_SIGNOFF.md`, `README.md`, and `TESTING_PROCESS.md` (`#30000`–`#30999` `strings.po` boundary, `unittest` runner, `--fail-below 65` Gate 3 target, `16,462` byte `AGENTS.md` baseline).
- [x] **SP-02 (`DONE`): Remediate `C-34` (Zero-Wait `resolve_silent` pruning) & `C-35` (`wlf_auth` disposal + idle timeout)**
  - `plugin.video.otaku.rpdev/resources/lib/windows/resolver.py` & `ui/player.py`: In `resolve_silent()`, mark failed `embed`/`direct` mirror cooldowns, prune failed lead candidates from the cached episode sources list, and persist the pruned list via `database.set_episode_sources()` (or `clear_episode_sources()` when empty) so subsequent playback doesn't re-try dead lead candidates.
  - `plugin.video.otaku.rpdev/resources/lib/WatchlistIntegration.py` & `windows/wlf_auth.py`: Wrap `WatchlistFlavorAuth.doModal()` in `try...finally: dlg.close(); del dlg` and add an abort-responsive idle auto-close timer (default 300s without key/mouse action) so unattended auth dialogs never block Kodi's screensaver (`window 12600`).
  - **Tests:** `tests/unit/test_c34_c35_regressions.py`, `tests/unit/test_windowxml_event_dispatch.py`.
- [x] **SP-03 (`DONE`): Read-Only ONN Auditor, Fast QA Foundation, AST Guardrails & Repo Hygiene**
  - Create strictly read-only `scripts/audit_onn_logs.py` (HTTP GET `http://10.13.0.16:8081/tail?offset=<N>` or `--input <local_log_file>`) supporting `--concerns docs/CONCERNS.md`, `--offset`, `--url`, `--input`, `--timeout`, and `--json`, plus offline fixture `tests/fixtures/onn_kodi_log_sample.txt` and `tests/unit/test_audit_onn_logs.py`.
  - Add `--fast` / `--tests` to `scripts/verify_all.py`, thin `scripts/qa_fast.py`, and `.pre-commit-config.yaml` (`repo: local`: `ruff`, `compileall`, `test_ast_integrity.py`, `test_docs_and_customizations.py`, `test_suite_quality.py`).
  - Expand `tests/lint/test_ast_integrity.py` with Wave-1-safe guardrails (`audit_onn_logs.py` read-only AST check + repo-root `special:`/`MagicMock` leak guardrails; `CR-01` asset checks deferred to Wave 2).
  - Fix repo hygiene leaks in `tests/conftest.py` (`TEST_SANDBOX_ROOT` + full `special://` translation + `service.subtitles.otaku.rpdev` addon path), update `.gitignore`, and `git rm -rf "special:" "MagicMock"`.
- **Gate 1:** `python3 scripts/verify_all.py` (`--fail-below 60`, 0 failures, 0 project warnings, 0 repo-root leak artifacts).

---

## Wave 2: Codebase Hardening & Tri-Addon Parity (`M2_wave2_hardening`)

- [x] **CR-01: Studio Logo Case-Collision Deduplication & PNG Asset Compression**
  - Deduplicate all 41 case-insensitive collision groups in `context.otaku.rpdev/resources/images/studios/coloured/` and `white/` (including `8-bit.png`/`8-Bit.png`/`8bit.png`/`Eight Bit.png`/`Eight bit.png`).
  - Optimize `poster.png` (`< 350 KB`) and `icon.png` (`< 150 KB`) across `plugin.video.otaku.rpdev/`, `context.otaku.rpdev/`, and `service.subtitles.otaku.rpdev/`.
  - **Tests:** Add `test_zero_case_insensitive_asset_collisions_and_oversized_pngs` in `tests/lint/test_ast_integrity.py`.
- [x] **CR-02: `v6.2.x` SQLite WAL / Read-Only URI Parity**
  - Audit all `sqlite3.connect` and `SQL(...)` sites across `plugin.video.otaku.rpdev`, `context.otaku.rpdev`, `service.subtitles.otaku.rpdev`, and `scripts/test_kodi_installs.py`; enforce `timeout=30.0`, read-only URI mode (`?mode=ro`) for static databases (`info.db`, `mappings.db`), and fix `database.py:261`.
  - **Tests:** `tests/unit/test_database_concurrency.py`.
- [x] **CR-03: Tri-Addon Kodi 21/22 Compliance, Modal Disposal, `C-06` & Docs Sync**
  - Wrap remaining bare `.doModal()` calls (`routes/tools.py` lines `27, 547`, `service.py`, `windows/{stats_window,textviewer}.py`) in `try...finally: dlg.close(); del dlg`, resolve `C-06` `CHANGE_LOG` `exit_code`/directory handling, and add AST modal-disposal check.
  - Document `service.subtitles.otaku.rpdev` across `AGENTS.md` (`< 22,000` bytes), `CHANGEREPORT.md`, `docs/ARCHITECTURE.md`, `docs/TESTING.md`, `docs/AUTOMATION.md`, `docs/CONFIGURATION_GUIDE.md`, and `docs/README.md`.
  - **Tests:** `tests/lint/test_docs_and_customizations.py`.
- [x] **CR-04: CI / Release Tri-Addon Packaging & E2E Parity**
  - Harden `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `scripts/release_addon.py`, and `scripts/test_kodi_installs.py` for tri-addon validation/packaging, `--fail-below 65` target parity, zero case-collision ZIP check, dry-run ZIP build, and addon manifest validation.
  - **Tests:** `tests/unit/test_coverage_routes_browsers_windows_subtitles.py`.
- [x] **CR-05: Abort-Safe `waitForAbort` Sweep (11 Blocking Sleeps) & `sanitize_log` Expansion**
  - Replace `time.sleep(...) > 0.5s` in `AnimeSchedule.py` (`533, 537`), `endpoints/mal.py` (`27, 41`), `indexers/kitsu.py` (`46`), `indexers/anidb.py` (`31`), `indexers/otaku.py` (`62, 120, 243`), and `indexers/jikanmoe.py` (`31, 84`) with `if control.monitor.waitForAbort(...): return / break`.
  - Add `'subtitles.subdl.apikey'`, `'subtitles.subsource.apikey'`, `'subtitles.opensubtitles.password'`, and `'animeskip.apikey'` to `control._SENSITIVE_SETTING_KEYS`.
  - **Tests:** `tests/lint/test_ast_integrity.py`, `tests/unit/test_atomic_and_security.py`.
- **Gate 2:** `verify_all.py` + `kodi-addon-checker`/manifest check + dry-run tri-addon ZIP build (0 case collisions, 0 circular deps, 100% module coverage).

---

## Wave 3a: Core Infrastructure (`M3a_wave3_core_infra`)

- [x] **NF-04: Unified Adaptive Circuit Breaker (`ui/domains.py`)**
  - Implement `AdaptiveCircuitBreaker` in `resources/lib/ui/domains.py` supporting provider categories (`torrent`, `embed`, `subtitle`, `metadata`, `debrid`) with adaptive exponential cooldowns (`300s` $\rightarrow$ `900s` $\rightarrow$ `3600s`), half-open recovery probes, `Window(10000)` + SQLite persistence, and System Health diagnostics integration.
  - Keep `ScraperCircuitBreaker` compatibility alias/wrapper in `pages/__init__.py`.
  - **Tests:** `tests/unit/test_ui_core_engine.py`.
- [x] **NF-06: Per-Series Override Profiles (`series_overrides` Table & Dialog)**
  - Add `series_overrides` table in `SyncDatabase` (`SCHEMA_VERSION = '1.0.14'`) and CRUD helpers (`get_series_override`, `set_series_override`, `delete_series_override`) in `database.py`.
  - Wire per-series overrides (`audio_lang`, `sub_lang`, `sub_mode`, `preferred_provider`, `intro_offset_s`, `outro_offset_s`, `skip_filler_mode`) into `WatchlistPlayer` (`ui/player.py`), `pages/__init__.py:sortSources()`, and a `series_profile` route in `routes/tools.py`.
  - **Tests:** `tests/unit/test_series_overrides_and_profiles.py`.

---

## Wave 3b: Parallel `v6.3.0` Feature Expansion (`M3b_wave3_parallel_features`)

All new `settings.xml` / `strings.po` IDs stay strictly within `#30000`–`#30999` (`#30582`–`#30589`) and are synced with `Settings Backup & Restore` and `test_settings_schema_and_code_references.py`.

- [x] **NF-05: Compressed `.xz`/`.gz` + SHA-256 + `PRAGMA quick_check` + `.bak` Rollback for `mappings.db`**
  - Enhance `service.py:update_mappings_db()` and `database.py:verify_sqlite_integrity(db_path)` to support `.xz`/`.gz` decompression, optional SHA-256 verification, `PRAGMA quick_check` on the downloaded staging file before replacing `mappings.db`, automatic backup to `mappings.db.bak`, and rollback from `mappings.db.bak` on corruption.
  - **Tests:** `tests/unit/test_database_concurrency.py`, `tests/unit/test_atomic_and_security.py`.
- [x] **NF-01: Multi-Tracker Conflict Engine + Persistent 429 Retry Queue + Telemetry Inspector**
  - Add `scrobble_retry_queue` table in `SyncDatabase` (`1.0.14`, `database_sync.py` & `database.py`) to persist failed/rate-limited (HTTP 429/503/network) scrobble requests across MAL, AniList, Kitsu, and Simkl.
  - Process due retry queue entries in `service.py`'s background maintenance loop with abort-responsive backoff.
  - Implement multi-tracker conflict resolution (`watchlist.sync.conflict_policy`: `highest_progress`, `primary_wins`, `latest_updated`) in `WatchlistIntegration.py` and surface scrobble queue/conflict metrics in System Health & Diagnostics (`routes/tools.py`).
  - **Tests:** `tests/unit/test_all_auth_and_watchlists_hardening.py`.
- [x] **NF-08: Cross-Watchlist Drift Auditor & 1-Click Reconciliation**
  - Implement `compute_watchlist_drift()` and `reconcile_watchlist_drift()` in `WatchlistIntegration.py` comparing cached/live episode progress & status across all logged-in flavors + local `episodes` watch state.
  - Expose `watchlist_drift_auditor` route in `routes/tools.py` with interactive diff report and 1-click sync reconciliation.
  - **Tests:** `tests/unit/test_all_auth_and_watchlists_hardening.py`.
- [x] **NF-02: Widget-Aware `context.otaku.rpdev` (`v1.0.46`) Quick Actions**
  - Upgrade `context.otaku.rpdev/default.py` and `addon.xml` (`v1.0.46`) to extract `mal_id`/`episode` from skin widget items and add quick context menu actions for **Series Playback Profile** (`series_profile`) and **Manual Subtitle Search** (`search_subtitles`).
  - Fix `control.process_context()` (`markedasunwatched` + new toggles) and support explicit `mal_id`/`episode` in `routes/subtitles.py`.
  - **Tests:** `tests/unit/test_context_menu_and_actions.py`.
- [x] **NF-03: Filler/Recap Badges + Binge Auto-Skip Filler + OP/ED Offset Tuning**
  - Parse filler/recap classifications in `endpoints/anime_filler.py` & `indexers/__init__.py` to append colorized `[FILLER]` / `[RECAP]` badges when `interface.filler.badges` is enabled.
  - Support `smartplay.skip_filler` (and per-series `skip_filler_mode` from `NF-06`) in `WatchlistPlayer.build_playlist()`, plus per-series `intro_offset_s` / `outro_offset_s` adjustments in `WatchlistPlayer`.
  - **Tests:** `tests/unit/test_autoskip_and_chapters.py`, `tests/integration/test_end_to_end_user_journeys.py`.
- [x] **NF-07: Subtitle Intelligence v2 (`service.subtitles.otaku.rpdev v1.0.3`)**
  - Enhance `subtitles/__init__.py:auto_download_subtitles()` with multi-candidate fallback, add optional SDH hearing-impaired bracket/speaker tag cleaning (`subtitles.strip_sdh_tags`) in `subtitles/download.py`, and integrate `AdaptiveCircuitBreaker` (`NF-04`) into `subtitles/search.py`.
  - Bump `service.subtitles.otaku.rpdev/addon.xml` to `v1.0.3` and update `plugin.video.otaku.rpdev/addon.xml` import.
  - **Tests:** `tests/unit/test_subtitle_service_and_auto_download.py`.
- **Gate 3:** `python3 scripts/verify_all.py --fail-below 65` (`>= 1,080` tests, `100%` module coverage, `>= 65.0%` function coverage, 5-stage [REVIEW_PROCESS.md](../../REVIEW_PROCESS.md) sign-off).

---

## Parallel Track: Opaque-Box E2E Suite (`E2E_testing_track`)

- [x] **E2E-Track (`DONE`)**: Requirement-driven Tier 1–4 E2E infrastructure & suite (`suite_sp.py`, `suite_cr.py`, `suite_nf.py` — 110 tests).

---

## Wave 4: Local Headless Kodi 21/22 E2E, Docs Sync & Release Readiness (`M4_wave4_e2e_release`)

- [x] **QA-01: Execute 4-Tier Verification & Stage `v6.3.0` Locally (No Push Until Final User Approval)**
  - Run `python3 scripts/verify_all.py --fail-below 65` (`>= 1,080` tests, `100%` module coverage, `>= 65.0%` function coverage, `0` warnings).
  - Run `python3 scripts/test_kodi_installs.py --versions 21 22 --mode hermetic` (all E2E gates green across Kodi 21.3 & Kodi 22.0-RC2, plus Tier 5 adversarial hardening).
  - Bump tri-addon versions (`6.3.0` / `1.0.46` / `1.0.3`), update `docs/CONCERNS.md` (`FIXED_VERIFIED_LOCAL_E2E`), `CHANGEREPORT.md`, `changelog.txt`, `news.txt`, `README.md`, `SPRINT_BOARD.md`, and complete [QA_SIGNOFF.md](QA_SIGNOFF.md) (including the post-release passive read-only checklist for `10.13.0.16`).
  - Stage local `--no-gpg-sign` commits cleanly (**do NOT push commits or tags until final user approval**) and deliver the release-readiness dossier.
