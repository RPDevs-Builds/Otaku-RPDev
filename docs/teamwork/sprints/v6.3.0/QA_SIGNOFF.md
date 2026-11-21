# Otaku-RPDev v6.3.0 QA Signoff Ledger (`docs/teamwork/sprints/v6.3.0/QA_SIGNOFF.md`)

**Target Release:** `plugin.video.otaku.rpdev v6.3.0` | `context.otaku.rpdev v1.0.46` | `service.subtitles.otaku.rpdev v1.0.3`  
**QA Auditor:** `qa-verifier`  
**Signoff Status:** `PENDING /TEAMWORK EXECUTION`

---

## 1. Pre-Sprint Baseline Metrics (Verified in `/plan` on `v6.2.19`)

| Gate / Metric | Baseline (`v6.2.19`) | Target (`v6.3.0`) | Status |
|---|---|---|---|
| **Ruff (`E9,F63,F7,F82,F811,F405,F541`)** | 0 violations | 0 violations | Baseline Green |
| **`compileall` (All 3 Add-ons + Tests + Scripts)** | 0 errors | 0 errors | Baseline Green |
| **Offline Unit / Lint / Integration Tests** | 1,035 passing | `>= 1,080` passing | Baseline Green |
| **Strict Project Warnings (`Deprecation` / `Resource`)** | 0 warnings | 0 warnings | Baseline Green |
| **Module Coverage (`audit_function_coverage.py`)** | 100.0% | 100.0% | Baseline Green |
| **Function Coverage (`audit_function_coverage.py`)** | 64.85% | `>= 65.0%` | Baseline Green |
| **`AGENTS.md` Context Budget (`< 22,000` bytes)** | 16,462 bytes | `< 22,000` bytes | Baseline Green |
| **ONN `10.13.0.16` Read-Only Log Cursor (`CONCERNS.md`)** | `433385` (Review #18) | Read-Only Only | Baseline Green |

---

## 2. Work Package Verification Checklist (To Be Completed by `qa-verifier`)

- [ ] **Wave 1 (`SP-01`..`SP-03` — Gate 1)**:
  - [ ] `SP-01` Governance board & sprint docs synced (`#30999+` `strings.po` floor, `unittest` runner, `16,462` byte `AGENTS.md` baseline, `--fail-below 65` Gate 3 target).
  - [ ] `SP-02` `C-34` Zero-Wait `resolve_silent()` lead-candidate pruning and `C-35` `wlf_auth` modal disposal + idle timeout verified under `KodiProfile('22', strict_skin_controls=True)`.
  - [ ] `SP-03` Strictly read-only `scripts/audit_onn_logs.py` tested offline against fixture logs and read-only cursor; `--fast` / `qa_fast.py` / `.pre-commit-config.yaml` / Wave-1 AST guardrails / `special:` & `MagicMock` repo hygiene verified.
  - [ ] **Gate 1:** `python3 scripts/verify_all.py` (`--fail-below 60`, 0 failures, 0 project warnings).
- [ ] **Wave 2 (`CR-01`..`CR-05` — Gate 2)**:
  - [ ] `CR-01`: 0 case-insensitive studio logo filename collisions across `context.otaku.rpdev/resources/images/studios/{coloured,white}/`; root `poster.png` `< 350 KB` & `icon.png` `< 150 KB` across all 3 addons (lint ceiling `< 600 KB`).
  - [ ] `CR-02`: All static DB reads (`info.db`, `mappings.db`) use `?mode=ro` URI and `timeout=30.0`.
  - [ ] `CR-03`: All `.doModal()` sites wrapped in `try...finally: dlg.close(); del dlg`, `C-06` resolved, and `service.subtitles.otaku.rpdev` documented (`AGENTS.md < 22,000` bytes).
  - [ ] `CR-04`: `ci.yml`, `release.yml`, `release_addon.py`, `test_kodi_installs.py` tri-addon packaging, `--fail-below 65` target parity, and dry-run ZIP build pass.
  - [ ] `CR-05`: 0 blocking `time.sleep(...) > 0.5s` calls in runtime modules; all subtitle/skip API keys scrubbed by `control.sanitize_log()`.
- [ ] **Wave 3a (`NF-04`, `NF-06`)**:
  - [ ] `AdaptiveCircuitBreaker` tested across torrent, embed, subtitle, metadata, and debrid categories.
  - [ ] `series_overrides` SQLite table (`SCHEMA_VERSION = '1.0.14'`) and playback/scraper profile overrides verified.
- [ ] **Wave 3b (`NF-01`, `NF-02`, `NF-03`, `NF-05`, `NF-07`, `NF-08` — Gate 3)**:
  - [ ] `NF-05`: `mappings.db` `.xz`/`.gz` decompression, SHA-256 verification, `PRAGMA quick_check`, and `.bak` rollback verified.
  - [ ] `NF-01`: Multi-tracker conflict resolution, persistent `scrobble_retry_queue` on HTTP 429/503, and Telemetry Inspector verified.
  - [ ] `NF-08`: Cross-Watchlist Drift Auditor diff and 1-click reconciliation verified across MAL, AniList, Kitsu, Simkl, and local DB.
  - [ ] `NF-02`: Widget-aware `context.otaku.rpdev` (`v1.0.46`) quick actions verified.
  - [ ] `NF-03`: Filler/Recap episode badges, binge auto-skip filler, and OP/ED offset tuning verified.
  - [ ] `NF-07`: Subtitle Intelligence v2 (`service.subtitles.otaku.rpdev v1.0.3`) multi-candidate fallback and SDH tag stripper verified.
  - [ ] **Gate 3:** `python3 scripts/verify_all.py --fail-below 65` passed all 4 silos (`>= 1,080` tests, 100% module coverage, `>= 65.0%` function coverage) + 5-stage `REVIEW_PROCESS.md` sign-off.
- [ ] **Wave 4 (`QA-01` — Local E2E, Docs Sync & Release Readiness)**:
  - [ ] `python3 scripts/verify_all.py --fail-below 65` passed all 4 silos on final `v6.3.0` state.
  - [ ] `python3 scripts/test_kodi_installs.py --versions 21 22 --mode hermetic` (plus `E2E-Track` Tier 1–4 & Tier 5 adversarial suite) passed on Flatpak Kodi 21.3 & Kodi 22.0-RC2 with 0 `ERROR`s / `Invalid setting type` / `g_directoryCache` / SWIG leaks.
  - [ ] `docs/CONCERNS.md` updated (`FIXED_VERIFIED_LOCAL_E2E`), versions bumped (`6.3.0` / `1.0.46` / `1.0.3`), `--no-gpg-sign` commits staged locally (**zero commits or tags pushed until final user approval**).
  - [ ] **Post-Release Passive ONN `10.13.0.16` Checklist** (to run read-only after user updates ONN via Kodi repo):
    - [ ] `python3 scripts/audit_onn_logs.py --concerns docs/CONCERNS.md` confirms clean `v6.3.0` update, 0 `C-34`/`C-35` regressions, 0 Python tracebacks, and clean Zero-Wait / subtitle playback.
