# Otaku-RPDev Comprehensive Test Suite Inventory & Expansion Guide

Complete audit and reference map of the **Otaku-RPDev** test suite (**1,232 `test_*` definitions** across `tests/lint/`, `tests/unit/`, `tests/integration/`, and `tests/e2e_v630/`), broken down by add-on and subsystem with live function-coverage data and an actionable expansion roadmap.

> **Related Docs:** [TESTING.md](TESTING.md) (6-silo rules & how to write tests) · [AUTOMATION.md](AUTOMATION.md) (CI/CD & `verify_all.py`) · [FEATURES.md](FEATURES.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [AGENTS.md](../AGENTS.md)

---

## 1. Suite Executive Summary & Verification Matrix

| Gate / Runner | Command | Scope & What It Executes | Runtime / Threshold |
|---|---|---|---|
| **Fast QA Gate** | `python3 scripts/qa_fast.py` (or `pytest -m lint`) | Ruff (`E9,F63,F7,F82,F811,F405,F541`), `compileall`, `tests/lint/` (`46` tests) | ~22s; zero warnings/errors |
| **Unified Full Gate** | `python3 scripts/verify_all.py --fail-below 65` | Ruff, `compileall`, all `tests/lint/` + `tests/unit/` + `tests/integration/` (`1,135` tests via `pytest` default / `unittest` fallback) + single-pass PEP 669 function coverage | ~95–115s; `>= 65.0%` (`68.59%` live) |
| **Pytest Direct & Parallel** | `pytest -q` / `pytest -n auto --dist loadfile` | All `test_*.py` + `suite_*.py` (`1,270` collected items; filterable by `-m "lint\|unit\|integration\|e2e\|property\|benchmark"`) | Multi-core via `pytest-xdist` |
| **Opaque E2E Suite** | `python3 scripts/e2e_v630_suite.py` (or `pytest -m e2e`) | `tests/e2e_v630/` (`suite_sp.py`, `suite_cr.py`, `suite_nf.py` — `145` executed tests across `v6.3.0+` stories) | ~70–90s; strict offline harness |
| **Coverage Audit** | `python3 scripts/audit_function_coverage.py --fail-below 65` | Live-traced function & module coverage across `145` source files | `100.0%` files (`145/145`), `68.59%` functions (`1524/2222`) |
| **Headless Real Kodi** | `python3 scripts/test_kodi_installs.py` | Flatpak Kodi 21.3 & 22.0 under `xvfb-run` + `scripts/kodi_e2e_mock_server.py` | Manual / local E2E verification |
| **ONN Log Audit** | `python3 scripts/audit_onn_logs.py --concerns docs/CONCERNS.md` | Read-only `10.13.0.16` Kodi log pattern & concern regression check | Read-only HTTP `/tail` |

### Offline Mock & Harness Layer (`tests/`)

- **`tests/conftest.py`**: Blocks live network sockets, stubs `xbmc`, `xbmcaddon`, `xbmcgui` (`MockWindowXMLDialog` with `onInit`/`onAction`/`onClick`/`onFocus` lifecycle), `xbmcplugin`, and `xbmcvfs`, auto-tags `pytest` items with `lint`/`unit`/`integration`/`e2e` markers, and provides reusable `@pytest.fixture` helpers (`kodi_profile`, `kodi22_strict`, `isolated_window_props`, `reset_kodi_settings`).
- **`tests/unit/test_pytest_property_and_time_invariants.py`**: Property-based fuzzing (`hypothesis` / `@pytest.mark.parametrize` for `isolate_show_title`, `score_title_candidate`, `domains.join_url`, 64KB UTF-8 window property ceiling, and `1.03` PAL subtitle rescaling monotonicity), deterministic time-travel tests (`freezegun` across `AdaptiveCircuitBreaker` `300s -> 900s -> 3600s -> HALF_OPEN -> CLOSED`), and hot-path micro-benchmarks (`pytest-benchmark`).
- **`tests/kodi_profile.py`**: Dual-version `KodiProfile('21'|'22', strict_skin_controls=True)` simulating Kodi 21 (`MockInfoTagVideo21`, ISO 639-2 `jpn`/`eng`, empty chapters) and Kodi 22 (`MockInfoTagVideo22`, strict SWIG non-null contracts, BCP 47 `ja`/`en`, `Player.GetChapters`), plus real `settings.xml` and 1080i skin XML control validation.
- **`tests/e2e_v630/e2e_helpers.py`**: `E2EHermeticEnv` (isolated temp `userdata`, SQLite DBs, `KodiProfile`) and `E2EMockServer` (local HTTP server for scraper/debrid/subtitle/mappings E2E journeys).

---

## 2. Cross-Addon Lint & Quality Gate (`tests/lint/` — 46 `test_*` defs)

Enforces invariants across `plugin.video.otaku.rpdev`, `service.subtitles.otaku.rpdev`, and `context.otaku.rpdev`:

| File | `test_*` | Enforced Invariants |
|---|---|---|
| `tests/lint/test_ast_integrity.py` | `27` | Zero circular `<requires>/<import>` dependencies across all 3 add-ons, zero `soupsieve` (`.select`/`.select_one`), `PROTOCOL_TLS_CLIENT` enforcement, zero Python 3.13/3.14 removed stdlib imports, `settings.xml` parity, 1080i skin XML nav-ID integrity, `WindowXML` disposal, `super().__init__()` |
| `tests/lint/test_docs_and_customizations.py` | `9` | `AGENTS.md` `< 22,000` bytes, `.agents/skills/*/SKILL.md` YAML frontmatter, relative Markdown link resolution across `README.md`/`docs/*.md`, `news.txt` `<= 32`-char dividers, `CONCERNS.md` integer cursor, `--fail-below 65` parity, companion `addon.xml` ↔ `changelog.txt` version parity |
| `tests/lint/test_function_coverage.py` | `5` | Dynamic 100% module import coverage across all 3 add-ons (`_TARGET_FILES`), ensuring no orphan/untested source file escapes tracking |
| `tests/lint/test_suite_quality.py` | `5` | Anti-placeholder gate: forbids zero-assertion tests, tautologies, `except Exception: pass` in `test_*`, unexecuted `module_from_spec`, and `assertIsNotNone`-only tests |

---

## 3. Per-Addon Test Breakdown

### A. `plugin.video.otaku.rpdev` (Core Video Add-on — `~1,130+` `test_*` defs)

#### 1. Core UI, Router, WindowXML & Settings
- **Settings & Schema**: `test_all_settings_outcomes.py` (`14`), `test_settings_schema_and_code_references.py` (`14`), `test_settings_manager.py` (`13`), `test_settings_routes_audit.py` (`2`), `test_setup_wizard.py` (`11`), `test_clean_settings.py` (`3`).
- **WindowXML & UI Events**: `test_windows_dialogs.py` (`4`), `test_windowxml_event_dispatch.py` (`12`), `test_end_user_ui_and_routes.py` (`6`), `test_ui_core_engine.py` (`10`), `test_clear_cache_dialog.py` (`11`), `test_menu_order.py` (`23`), `test_menu_auto_refresh.py` (`6`), `test_colors.py` (`3`), `test_changelog_dismissal.py` (`4`), `test_v640_features.py` (`4` — NF-12 `SeriesProfileDialog` save/cancel/back close & overrides).

#### 2. Scrapers, Candidate Scoring & Filtering
- **Top-100 & Scoring Matrix**: `test_top100_hermetic_regression.py` (`5` — 576-title matrix across all 7 scrapers), `test_scraper_candidate_scoring.py` (`16`), `test_centralized_title_scoring.py` (`17`), `test_part_filter.py` (`5`), `test_source_type_filter.py` (`6`).
- **Provider Scrapers & Transport**: `test_scrapers_all.py` (`10`), `test_scrapers_offline.py` (`7`), `test_bitsearch_and_piratebay.py` (`13`), `test_gogoanime.py` (`6`), `test_watchnixtoons2.py` (`7`), `test_megacloud.py` (`6`), `test_flaresolverr_and_scraper_remediations.py` (`10`), `test_domains.py` (`12`), `test_performance_and_circuit_breaker.py` (`6`), `test_coverage_scrapers_debrid.py` (`14`).

#### 3. Debrid, Cloud, Playback, Zero-Wait & Chapters
- **Debrid & Cloud**: `test_debrid_resolvers.py` (`6`), `test_debrid_and_playback_m1c.py` (`8`), `test_cloud_vfs.py` (`5`), `test_premiumize_oauth.py` (`8`).
- **Playback, Failover & Chapters**: `test_still_watching_and_preresolve.py` (`5`), `test_embed_precaching_and_continuity.py` (`6`), `test_chapter_extractor.py` (`14`), `test_chapter_and_window_cleanup.py` (`8`), `test_animeskip.py` (`10`), `test_introdb.py` (`18`), `test_upstream_pr500_tmdb_helper.py` (`3`), `test_upstream_pr497_innovations.py` (`2`).

#### 4. Indexers, Endpoints, Mappings DB & Watchlists
- **Indexers & Endpoints**: `test_coverage_endpoints_indexers.py` (`35` — includes `fanart.py` URL space escaping & `anime_filler`), `test_endpoints_all.py` (`9`), `test_routes_and_indexers.py` (`4`), `test_dub_label.py` (`3`), `test_mal_current_period_ranked_lists.py` (`3`).
- **Mappings & Metadata DBs**: `test_mapping_db_integration.py` (`9` — `filler_ranges`, `[CANON]`/`[MIXED]`/`[FILLER]`/`[RECAP]`, `tvdb_rules`), `test_metadata_db_integration.py` (`3`).
- **Watchlists & Multipage**: `test_all_auth_and_watchlists_hardening.py` (`22`), `test_watchlist_flavors.py` (`6`), `test_watchlist_paging.py` (`14`), `test_watchlist_precaching_and_paging.py` (`6`), `test_watchlist_sorting.py` (`8`), `test_simkl_auth.py` (`8`), `test_multipage_sorting.py` (`55`), `test_multipage_adversarial.py` (`13`), `test_multipage_refresh_and_ceiling_adversarial.py` (`10`).

#### 5. Database, Lifecycle, Security, Kodi 21/22 & Regressions
- **Core Persistence & Stability**: `test_database_and_client.py` (`17`), `test_atomic_and_security.py` (`7`), `test_security_and_memory.py` (`9`), `test_cpython_invoker_lifecycle.py` (`13`), `test_system_health_and_recovery.py` (`6`), `test_kodi_21_22_dual_compat.py` (`32`), `test_mock_harness_capabilities.py` (`7`).
- **Wave / Audit / Regression Suites**: `test_v630_wave3_features.py` (`20`), `test_v642_hardening.py` (`10`), `test_concerns_deep_audit_v629.py` (`13`), `test_concerns_remediations_v625.py` (`12`), `test_review10_fixes_v6211.py` (`7`), `test_review12_fixes_v6213.py` (`5`), `test_upstream_pr_parity_v6210.py` (`8`), `test_audit_remediations.py` (`15`), `test_audit_onn_logs.py` (`10`), `test_challenger_m1_2_adversarial.py` (`14`), `test_challenger_m3_adversarial.py` (`4`), `test_c34_c35_regressions.py` (`9`), `test_milestone2_adversarial_hardening.py` (`6`), `test_milestone_v6_hardening.py` (`12`), `test_performance_and_flair.py` (`11`), `test_project_state_audit_v626.py` (`8`), `test_resilience_and_ui.py` (`10`), `test_resource_and_stability.py` (`10`), `test_stability_fixes.py` (`7`), `test_stability_resilience.py` (`10`), `test_standards_and_security.py` (`5`), `test_standards_resilience.py` (`7`), `test_subsystem_hardening_v597.py` (`11`), `test_subsystem_hardening_v598.py` (`11`).

#### 6. Integration & Opaque E2E (`tests/integration/` & `tests/e2e_v630/`)
- `tests/integration/test_end_to_end_user_journeys.py` (`4`), `test_full_system_lifecycle.py` (`4`), `test_resolvers_and_routes.py` (`5`).
- `tests/e2e_v630/suite_sp.py` (`23` — stability/performance invariants), `suite_cr.py` (`72` — critical/cross-addon regressions), `suite_nf.py` (`18` + inherited Wave 3 tests — `NF-*` features with >=2:1 negative/edge-to-happy ratio).

---

### B. `service.subtitles.otaku.rpdev` (Native Subtitle Companion)

- **Coverage**: `service.subtitles.otaku.rpdev/service.py` achieves **88.9% (`8/9`)** function coverage.
- **Test Files**:
  - `tests/unit/test_subtitle_service_and_auto_download.py` (`25`): `action=search`, `action=manualsearch`, `action=download`, `sync`/`hearing_imp` badges, profile `temp/` staging, Kodi 22 BOM/WEBVTT/VFS `g_directoryCache` contract, `auto_download_subtitles` mismatch skipping & playback-stop abort, 25fps PAL rescaling, sparse Signs-only `.vtt` auto-upgrade.
  - `tests/unit/test_subtitles.py` (`26`) & `tests/unit/test_native_subtitles.py` (`25`): 6-provider parsers (`opensubtitles`, `subdl`, `subsource`, `podnadpisi`, `bsplayer`, `addic7ed`), archive extraction, SDH tag stripping, language normalization.
  - `tests/unit/test_coverage_routes_browsers_windows_subtitles.py` (`14`), `tests/unit/test_review10_fixes_v6211.py` (`7`), `tests/e2e_v630/suite_cr.py`, plus `tests/lint/` (`test_ast_integrity.py`, `test_docs_and_customizations.py`, `test_function_coverage.py`).

---

### C. `context.otaku.rpdev` (Global Context Menu Companion)

- **Coverage**: `context.otaku.rpdev/default.py` achieves **100.0% (`6/6`)** function coverage.
- **Test Files**:
  - `tests/unit/test_context_menu_and_actions.py` (`6`): dispatches across `addon.xml` actions, `_extract_subpath`, `_extract_watch_target`, `get_video_info`.
  - `tests/unit/test_anime_studio_resources.py` (`9`): verifies `studios/` and `genres/` PNG asset packs (`coloured` & `white`, 494+ icons) and `info.db` parity.
  - `tests/unit/test_v642_hardening.py` (`10`), `tests/unit/test_v630_wave3_features.py` (`20`), `tests/unit/test_all_settings_outcomes.py` (`14`), `tests/unit/test_concerns_remediations_v625.py` (`12`), `tests/e2e_v630/suite_cr.py`, `suite_nf.py`: widget `UniqueID`/`mal_id` resolution, non-Otaku `videodb://` safety, `process_context()` home-window properties.
  - `tests/lint/`: circular dependency check, `addon.xml` ↔ `changelog.txt` version parity.

---

## 4. Fixtures & Standalone QA Scripts

- **Fixtures (`tests/fixtures/`)**: `top_100_anime_dataset.json`, `comprehensive_anime_dataset.json`, `subtitle_config_all_services.json`, `onn_kodi_log_sample.txt`, `media/sample_chapters.mkv`, `media/sample.srt`, plus JSON/HTML snapshots under `anilist/`, `animeschedule/`, `anizip/`, `debrid/`, `kitsu/`, `mal/`, `scrapers/`, `simkl/`.
- **Additional Scripts (`scripts/`)**: `audit_kodi22_features.py`, `capture_kodi_screenshots.py`, `check_scraper_health.py`, `test_autoskip_coverage.py`.

---

## 5. Live Coverage Snapshot & Expansion Roadmap

From `python3 scripts/audit_function_coverage.py --fail-below 65` (`1,119` unit/integration/lint tests):
- **Overall**: `145/145` (`100.0%`) source files covered; `1,524/2,222` (`68.59%`) total functions; `1,071/1,599` (`66.98%`) public functions.

### Lowest-Coverage Modules (`plugin.video.otaku.rpdev`, `functions_count >= 4`)

| Module | Function Coverage | Priority Expansion Focus |
|---|---|---|
| `resources/lib/OtakuBrowser.py` | `7.7%` (`1/13`) | Browse/search/pagination delegation & error fallbacks |
| `resources/lib/debrid/all_debrid.py` | `16.7%` (`3/18`) | Pin auth, magnet/cache checks, 429/error handling |
| `resources/lib/debrid/premiumize.py` | `20.0%` (`6/30`) | Folder/transfer CRUD, directdl, stalled purge |
| `resources/lib/WatchlistFlavor/Kitsu.py` | `24.1%` (`7/29`) | OAuth refresh, episode/status/score mutations, 404/429 paths |
| `resources/lib/MalBrowser.py` | `24.2%` (`15/62`) | Genre/season/calendar pagers & malformed response handling |
| `resources/lib/indexers/otaku.py` | `27.3%` (`6/22`) | Episode indexing, `append_episodes`, filler/dub merge |
| `resources/lib/debrid/debrid_link.py` | `28.6%` (`4/14`) | OAuth refresh, torrent add/check, link resolution |
| `resources/lib/ui/embed_extractor.py` | `30.6%` (`11/36`) | Host extractors, VTT/SRT/ASS edge cases, origin fallback |
| `resources/lib/pages/debrid_cloudfiles.py` | `33.3%` (`2/6`) | Multi-debrid cloud file matching across episode/season queries |
| `resources/lib/pages/torrentio.py` | `33.3%` (`3/9`) | Stream parsing, season/episode filtering, debrid cache batching |
| `resources/lib/Main.py` | `34.1%` (`28/82`) | Genre/category directory builders & custom menu ordering |
| `resources/lib/pages/watchnixtoons2.py` | `34.8%` (`16/46`) | Sub/Dub sequential scraping & `/ad-verify` fallback |
| `resources/lib/debrid/torbox.py` | `35.3%` (`6/17`) | Usenet/torrent cache check & link unrestricting |
| `resources/lib/windows/settings_backup.py` | `37.5%` (`3/8`) | Modal interactions for scoped export/restore (`series_overrides`) |
| `resources/lib/windows/download_manager.py` | `39.3%` (`11/28`) | Queue progress updates, cancel/retry buttons, cleanup |

### Strategic Expansion Targets by Add-on

1. **`plugin.video.otaku.rpdev`**:
   - Add negative/error-path tests for `all_debrid.py`, `debrid_link.py`, `torbox.py`, and `premiumize.py` (using `E2EMockServer`).
   - Expand `OtakuBrowser.py`, `MalBrowser.py`, and `Main.py` directory-builder coverage under `KodiProfile('22')`.
   - Add targeted unit tests for `pages/debrid_cloudfiles.py`, `pages/localfiles.py`, and `service.py` 15-minute daemon loop branches (standby skip, retry drain, WAL checkpoint).
2. **`service.subtitles.otaku.rpdev`**:
   - Cover the remaining uncovered branch in `service.py` via direct `sys.argv` `__main__` entrypoint invocation tests.
   - Add corrupted/nested `.rar`/`.7z` archive fallback tests and multi-language Kodi `DialogSubtitles` query edge cases.
3. **`context.otaku.rpdev`**:
   - Add an XML `<visible>` condition matrix test validating every `context.otaku.rpdev/addon.xml` rule (`DBTYPE`, `Player.HasMedia`, `Window(home).Property(...)`, `ListItem.UniqueID(mal_id)`).
   - Add read-only `?mode=ro` query tests against `context.otaku.rpdev/info.db` and unit tests for `scripts/harvest_anime_studios.py` & `scripts/generate_missing_studios.py`.
