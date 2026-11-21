# Otaku-RPDev v6.3.0 Sprint Charter (`docs/teamwork/sprints/v6.3.0/SPRINT_CHARTER.md`)

**Target Release:** `plugin.video.otaku.rpdev v6.3.0` | `context.otaku.rpdev v1.0.46` | `service.subtitles.otaku.rpdev v1.0.3`  
**Baseline Release:** `plugin.video.otaku.rpdev v6.2.19` | `context.otaku.rpdev v1.0.45` | `service.subtitles.otaku.rpdev v1.0.2`  
**Charter Date:** `2026-11-21`

---

## 1. Sprint Mission
Deliver **Otaku-RPDev v6.3.0**, unifying all `v6.2.x` field lessons (`C-01`–`C-35`) with tri-addon asset/SQLite/abort-safety parity (`SP-01`–`SP-03`, `CR-01`–`CR-05`) and eight major user-facing capabilities (`NF-01`–`NF-08`): multi-tracker conflict resolution & 429 retry queueing, widget-aware context actions, filler/recap badges & binge auto-skip, unified adaptive circuit breaking, compressed & self-healing `mappings.db` sync, per-series override profiles, Subtitle Intelligence v2, and a cross-watchlist drift auditor.

---

## 2. Non-Negotiable Operational Constraints
1. **Strict Environment Isolation:**
   - **Local Headless Flatpak Kodi 21.3 & Kodi 22.0-RC2 (`scripts/test_kodi_installs.py`)** is the **ONLY** runtime test environment for installing builds, rendering UI dialogs, and running E2E playback tests.
   - **ONN 4K Pro (`10.13.0.16`)** is strictly **READ-ONLY LOG REVIEW ONLY** (`http://10.13.0.16:8081/tail?offset=<N>`). Never push files, sideload zips, edit configs, or trigger remote commands on `10.13.0.16`.
2. **Acyclic Tri-Addon Dependency Graph:**
   - `plugin.video.otaku.rpdev` depends on `context.otaku.rpdev` (`1.0.46`) and `service.subtitles.otaku.rpdev` (`1.0.3`).
   - Neither companion add-on may declare `<import addon="plugin.video.otaku.rpdev"/>` (`test_zero_circular_addon_dependencies`).
3. **Kodi 22 C++ VFS & SWIG Safety:**
   - All temporary file writes opened by Kodi C++ must register in `g_directoryCache` via `control.atomic_write_text()` (`xbmcvfs.rename` + `special://temp/` URI awareness), and `del_subs()` must never call `xbmcvfs.listdir()`.
   - Every `doModal()` call must be wrapped in `try...finally: dlg.close(); del dlg`.
4. **Non-Destructive Schema Evolution:**
   - New tables (`series_overrides`, `scrobble_retry_queue`) must be created idempotently in `SyncDatabase._create_all_tables()` with `SCHEMA_VERSION` bumped to `'1.0.14'` via `_migrate_database()`.

---

## 3. Scope Summary (16 Work Packages)
- **Diagnostics & Tooling (`SP-01`..`SP-03`)**: Read-only ONN Review #18 (`offset=433385`), `C-34` Zero-Wait `resolve_silent()` lead-candidate pruning, `C-35` `wlf_auth` modal disposal & idle screensaver timeout, and `scripts/audit_onn_logs.py`.
- **Cross-Cutting Parity (`CR-01`..`CR-05`)**: 41 studio logo case-collision group deduplication + PNG size optimization (`poster.png`/`icon.png`), SQLite WAL/URI read-only parity, tri-addon documentation sync (`AGENTS.md < 22 KB`, `CHANGEREPORT.md`, `docs/*.md`), tri-addon CI/release/E2E parity, 11 blocking `time.sleep` $\rightarrow$ `waitForAbort` conversions, and `sanitize_log` key expansion.
- **New Features (`NF-01`..`NF-08`)**:
  - `NF-01`: Multi-tracker conflict engine + persistent 429 scrobble retry queue + Telemetry Inspector
  - `NF-02`: Widget-aware `context.otaku.rpdev` (`v1.0.46`) quick actions
  - `NF-03`: Filler/Recap episode badges + Binge auto-skip filler + OP/ED offset tuning
  - `NF-04`: Unified `AdaptiveCircuitBreaker` across torrent, embed, subtitle, metadata, and debrid providers
  - `NF-05`: Compressed `.xz`/`.gz` + SHA-256 + `PRAGMA quick_check` + `.bak` rollback for `mappings.db`
  - `NF-06`: Per-Series Override Profiles (`series_overrides` SQLite table + dialog + player/scraper routing)
  - `NF-07`: Subtitle Intelligence v2 (multi-candidate download fallback, SDH tag stripper, provider circuit breaker)
  - `NF-08`: Cross-Watchlist Drift Auditor & 1-click reconciliation

---

## 4. Wave Schedule & Gate Alignment
- **Wave 1 (`M1`, Gate 1 `--fail-below 60`)**: `SP-01`..`SP-03` (`C-34`, `C-35`, `audit_onn_logs.py`, fast QA, Wave-1 AST guardrails, repo hygiene).
- **Wave 2 (`M2`, Gate 2 `--fail-below 60` + dry-run tri-addon ZIP)**: `CR-01`..`CR-05`.
- **Wave 3a (`M3a`) -> Wave 3b (`M3b`, Gate 3 `--fail-below 65`)**: `NF-04` + `NF-06` -> parallel `NF-01`, `NF-02`, `NF-03`, `NF-05`, `NF-07`, `NF-08` (all new `strings.po` IDs **`#30999+`**).
- **Parallel `E2E-Track` & Wave 4 (`M4`, `QA-01`)**: Local headless Kodi 21/22 E2E, docs sync, local `--no-gpg-sign` staging (**no push/publish until final user approval**).
