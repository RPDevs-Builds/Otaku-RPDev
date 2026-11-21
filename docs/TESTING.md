# Otaku-RPDev Testing Architecture & Quality Standards

Otaku-RPDev uses a **6-silo testing architecture** designed so every test produces an actionable signal (catching real regressions, schema drift, SWIG errors, or user-visible defects) rather than inflating test counts with placeholder checks.

---

## 1. The 6 Testing Silos

| Silo | Location / Command | What It Enforces |
|---|---|---|
| **1. Static & Syntax** | `ruff check --select E9,F63,F7,F82,F811,F405,F541` + `compileall` | Zero syntax errors, undefined names, star-import ambiguities (`F405`), shadowed redefinitions (`F811`), or dead f-strings (`F541`). |
| **2. AST, Quality & Doc Lints** | `tests/lint/` (`test_ast_integrity.py`, `test_suite_quality.py`, `test_docs_and_customizations.py`, `test_function_coverage.py`) | Mechanical enforcement of `AGENTS.md` invariants, anti-placeholder test quality rules, rule/skill/doc drift checks, and dynamic 100% module import coverage. |
| **3. Behavioral Unit Matrix** | `tests/unit/` | Dual Kodi 21/22 compatibility (`KodiProfile`), exhaustive 494-setting consumer-outcome checks (`test_all_settings_outcomes.py`), WindowXML/skin/route behavior (`test_end_user_ui_and_routes.py`), scrapers, debrid, subtitles, `v6.3.0` Wave 1/3 regressions, and 576-title scoring regression (`test_top100_hermetic_regression.py`). |
| **4. End-to-End Integration & Opaque Suite** | `tests/integration/` & `tests/e2e_v630/` (`scripts/e2e_v630_suite.py`) | Cross-subsystem offline user journeys + 126 opaque-box E2E tests (`suite_sp.py`, `suite_cr.py`, `suite_nf.py`). Minimum **2:1 negative/edge-to-happy test ratio** required for all `NF-*` features. |
| **5. Coverage Gate** | `scripts/audit_function_coverage.py --fail-below 65` | 100% source module import coverage and `>= 65%` live-traced function coverage (`sys.monitoring` / `sys.settrace`; `66.03%` verified at `v6.3.1`). Executed in a single strict-warning pass with Silo 3 inside `verify_all.py` on Python 3.12+. |
| **6. Headless Real Kodi 21/22** | `scripts/test_kodi_installs.py` / `kodi-env headless 22` | Real Flatpak Kodi 21.3 (Omega) & 22.0-RC2 (Piers) execution under Xvfb across `plugin.video.otaku.rpdev`, `context.otaku.rpdev`, and `service.subtitles.otaku.rpdev` with zero-tolerance `kodi.log` audits. |

Run Tier-1 fast incremental QA or the full Silos 1–5 gate anywhere via:
```bash
python3 scripts/qa_fast.py
python3 scripts/e2e_v630_suite.py
python3 scripts/verify_all.py --fail-below 65
```

For strictly read-only post-release production telemetry verification on ONN `10.13.0.16`, use `python3 scripts/audit_onn_logs.py --concerns docs/CONCERNS.md` (see [TESTING_PROCESS.md](teamwork/TESTING_PROCESS.md)).

---

## 2. Anti-Placeholder Quality Standards (`tests/lint/test_suite_quality.py`)

To prevent false-positive tests from masking bugs as the suite scales past 1,000 tests, `tests/lint/test_suite_quality.py` **fails CI immediately** on:
- **Zero-assertion tests**: Every `test_*` method must execute at least one concrete assertion.
- **Tautologies**: `assertTrue(True)`, `assertTrue(... or True)`, `assertFalse(False)`, `assertEqual(x, x)`.
- **Swallowed failures**: `except Exception: pass` or bare `except: pass` inside `test_*` methods (which silently catch `AssertionError` and crashes).
- **Unexecuted module specs**: `importlib.util.module_from_spec(...)` without `exec_module(...)`.
- **Import-only placeholders**: Tests whose only assertions are `assertIsNotNone(<var>)`.

### Writing High-Signal Tests
- **Settings tests**: Never just `control.setBool(k, True); assertTrue(control.getBool(k))`. Always invoke the real production consumer (`sortSources`, `WatchlistPlayer`, `domains.get_domain`, `database.SQL` PRAGMA query, `subtitles.get_subtitles_settings`, `SourceSelect.populate_sources`, etc.) and assert the observable behavior change.
- **UI / WindowXML tests**: Wrap dialog tests in `KodiProfile('22', strict_skin_controls=True)` so missing XML control IDs raise `RuntimeError`. Rely on the base `onInit`/`onAction`/`onClick`/`onFocus` hooks on `MockWindowXMLDialog` in `tests/conftest.py` for realistic `super()` dispatch, assert concrete window properties/list items, verify Back actions (`[9, 10, 92, 216]`), and verify `onClick` single-dispatch.
- **2:1 Negative/Edge-to-Happy Quota**: Every new `NF-*` feature must ship at least two negative/edge tests for each happy-path test (covering corruption rollback, HTTP 429 `Retry-After` pruning, dialog cancellation, non-Otaku `videodb://` safety, and `episode_offset` scrobble isolation).
- **Non-Vacuous Linters (`tests/lint/*.py`)**: Files inside `tests/lint/` sit two levels below repo root — always compute `_REPO_ROOT = os.path.dirname(os.path.dirname(_TEST_DIR))` (never a single `..`) and assert a minimum scanned-item floor (e.g., `assertGreaterEqual(scanned, 90)`) so a path bug can never pass silently on 0 files.
- **Project warnings-as-errors**: `verify_all.py` runs `unittest` with `-W error::DeprecationWarning:resources -W error::ResourceWarning:resources`, turning any warning emitted by `plugin.video.otaku.rpdev` into a hard failure.
