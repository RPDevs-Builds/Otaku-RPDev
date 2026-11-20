---
name: otaku-testing-and-qa
description: >-
  Authoring, refactoring, and triaging high-signal offline tests across all 6
  Otaku-RPDev testing silos (lint, unit, integration, dual Kodi 21/22 UI/settings
  behavior, coverage, and scripts/verify_all.py --json LLM diagnostics). Use when
  adding tests, fixing test failures or warnings, auditing coverage, or updating
  tests/lint/ guardrails.
---

# Otaku-RPDev Testing & QA Runbook

Run all commands from `/mnt/sharedroot/projects/RPDevs-Builds/Otaku-RPDev`.

## 1. Unified Verification & LLM Triage Loop
1. Run the unified multi-silo gate with structured JSON output:
   ```bash
   python3 scripts/verify_all.py --fail-below 60 --json /tmp/verify_report.json
   ```
2. On failure, inspect `silos[]` in `/tmp/verify_report.json` (`failed_tests`, `remediation`, `tail`) and re-run only the failing module with strict project warnings:
   ```bash
   python3 -W default -W error::DeprecationWarning:resources -W error::ResourceWarning:resources \
     -m unittest tests/unit/<target_test>.py -v
   ```
3. Re-run full `python3 scripts/verify_all.py --fail-below 60` before committing and remove temporary `/tmp/verify_report.json`.

## 2. Actionable Test Authoring Rules (Enforced by `tests/lint/test_suite_quality.py`)
- **Zero false positives**: Never write zero-assertion tests, tautologies (`assertTrue(True)`, `assertEqual(x, x)`), broad `except Exception: pass` inside `test_*`, `module_from_spec()` without `exec_module()`, or `assertIsNotNone`-only import checks.
- **Settings tests (`test_all_settings_outcomes.py`)**: Never stop at `control.setBool(k, v); assertEqual(control.getBool(k), v)`. Invoke the real production consumer (`sortSources`, `WatchlistPlayer`, `domains.get_domain`, `database.SQL` PRAGMAs, `subtitles.get_subtitles_settings`, `SourceSelect.populate_sources`, etc.) and assert the observable behavior change.
- **UI & WindowXML tests (`test_end_user_ui_and_routes.py`)**:
  - Wrap dialog execution in `KodiProfile('22', strict_skin_controls=True)` so missing 1080i skin control IDs raise `RuntimeError`.
  - Rely on `MockWindowXMLDialog` base hooks (`onInit`, `onAction`, `onClick`, `onFocus`) in `tests/conftest.py` for realistic `super()` dispatch.
  - Assert concrete window properties, list item counts/labels, Back actions (`[9, 10, 92, 216]`), and single-dispatch `onClick`.
- **Non-vacuous linters (`tests/lint/*.py`)**:
  - Compute `_REPO_ROOT = os.path.dirname(os.path.dirname(_TEST_DIR))` (files in `tests/lint/` are 2 levels below repo root).
  - Always assert a non-vacuous scan floor (e.g., `self.assertGreaterEqual(scanned, 90)`) so a broken path can never pass silently on 0 files.

## 3. References
- Architecture & 6-silo specification: [docs/TESTING.md](../../../docs/TESTING.md)
- Unified gate JSON schema & CI/Release parity: [docs/AUTOMATION.md](../../../docs/AUTOMATION.md)
