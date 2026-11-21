---
name: otaku-testing-and-qa
description: >-
  Authoring, refactoring, and triaging high-signal offline tests across all 6
  Otaku-RPDev testing silos (lint, unit, integration, e2e_v630, dual Kodi 21/22
  UI/settings behavior, coverage, qa_fast.py, and verify_all.py --fail-below 65).
  Use when adding tests, fixing test failures or warnings, auditing coverage,
  or updating tests/lint/ guardrails.
---

# Otaku-RPDev Testing & QA Runbook

Run all commands from `/mnt/sharedroot/projects/RPDevs-Builds/Otaku-RPDev`. Never detour scratch files to `/tmp/` when a project scratch directory is available, and never touch `10.13.0.16` during testing.

## 1. Fast Loop, E2E Suite & Unified Verification Gate
1. **Fast Incremental Developer QA (`scripts/qa_fast.py`)**:
   ```bash
   python3 scripts/qa_fast.py --tests tests/unit/<target_test>.py
   ```
2. **Full Opaque-Box `v6.3.0` E2E Suite (`scripts/e2e_v630_suite.py`)**:
   ```bash
   python3 scripts/e2e_v630_suite.py
   ```
   (Executes `suite_sp.py`, `suite_cr.py`, and `suite_nf.py` — every `test_*` method in `tests/e2e_v630/suite_*.py` must contain at least one `self.assert*` call directly in its AST body.)
3. **Unified Multi-Silo Gate (`--fail-below 65`) with JSON Triage**:
   ```bash
   python3 scripts/verify_all.py --fail-below 65 --verbose
   ```
   On failure, re-run only the failing module with strict project warnings:
   ```bash
   python3 -W default -W error::DeprecationWarning:resources -W error::ResourceWarning:resources \
     -m unittest tests/unit/<target_test>.py -v
   ```

## 2. Actionable Test Quality & Negative-Path Quota (2:1 Minimum)
- **Zero false positives (`tests/lint/test_suite_quality.py`)**: Never write zero-assertion tests, tautologies (`assertTrue(True)`, `assertEqual(x, x)`), broad `except Exception: pass` inside `test_*`, `module_from_spec()` without `exec_module()`, or `assertIsNotNone`-only import checks.
- **2:1 Negative/Edge-to-Happy Quota for New Features (`NF-*`)**: For every happy-path test, include at least two negative/edge-case tests:
  - **Scrobble Queue Backoff (`NF-01`)**: Test `Retry-After` parsing/clamping, attempt increment on failed replay, and pruning after 5 attempts.
  - **Widget & Non-Otaku Item Safety (`NF-02`)**: Test `InfoTagVideo.getUniqueIDs()` (`mal`/`mal_id`) fallback AND empty/non-Otaku `videodb://` items returning `[]`.
  - **Mappings `.bak` Rollback (`NF-05`)**: Test corrupted live `mappings.db` recovery from `.bak` on failed sync download, plus SHA-256 mismatch rejection.
  - **Scraper-Only `episode_offset` & Migration Idempotency (`NF-06`)**: Test `episode_offset` altering `actionArgs['episode']` while leaving `canonical_episode` / scrobble callbacks untouched, `SettingsBackup` round-trip, and `SyncDatabase()` adding missing columns via `_ensure_column_migrations()` even when `SCHEMA_VERSION` matches.
  - **SDH Tag Preservation & Drift Confirmation (`NF-07`/`NF-08`)**: Test ASS `{\an8}` override preservation during SDH tag stripping and `watchlist_drift_auditor` dry-run mutation counts + cancelled `yesno_dialog` (`MockDialog.yesno_response = False`) preventing bulk writes.
- **Settings & WindowXML Tests**: Assert real consumer outcomes (`test_all_settings_outcomes.py`, never `set`→`get` echoes), wrap WindowXML tests in `KodiProfile('22', strict_skin_controls=True)`, and keep all `strings.po` IDs inside `#30000`–`#30999`.
- **Non-vacuous linters (`tests/lint/*.py`)**: Always compute `_REPO_ROOT = os.path.dirname(os.path.dirname(_TEST_DIR))` and assert a minimum scanned-item floor.

## 3. References
- Architecture & 6-silo specification: [docs/TESTING.md](../../../docs/TESTING.md)
- Unified gate JSON schema & CI/Release parity: [docs/AUTOMATION.md](../../../docs/AUTOMATION.md)
- Multi-agent 4-tier QA workflow: [docs/teamwork/TESTING_PROCESS.md](../../../docs/teamwork/TESTING_PROCESS.md)
