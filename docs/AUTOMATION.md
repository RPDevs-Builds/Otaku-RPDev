# Otaku-RPDev Verification Automation & LLM Integration

This document defines the unified verification runner, CI/release gate parity, automated drift linters, and machine-readable JSON interface built for developers and autonomous LLM agents.

---

## 1. Unified Multi-Silo Runner (`scripts/verify_all.py`)

Local development, GitHub Actions CI (`.github/workflows/ci.yml`), Release CI (`.github/workflows/release.yml`), `scripts/release_addon.py`, and LLM agents all invoke the exact same gate:

```bash
# Fast Tier-1 incremental QA (ruff + compileall + lints + targeted tests via .pre-commit-config.yaml)
python3 scripts/qa_fast.py

# Standard developer / CI run (Silos 1–4, --fail-below 65, strict project warnings-as-errors)
python3 scripts/verify_all.py --fail-below 65

# Dedicated v6.3.0 Opaque-Box E2E Suite (126 tests across suite_sp, suite_cr, suite_nf)
python3 scripts/e2e_v630_suite.py

# Strictly read-only ONN 4K Pro production telemetry auditor
python3 scripts/audit_onn_logs.py --concerns docs/CONCERNS.md --json <scratch>/onn_audit.json
```

### JSON Report Schema (`--json`)
```json
{
  "overall_status": "pass",
  "python_version": "3.12.3",
  "total_duration_s": 146.36,
  "strict_project_warnings": true,
  "silos": [
    {"name": "ruff", "status": "pass", "exit_code": 0, "duration_s": 0.13, "command": "..."},
    {"name": "compileall", "status": "pass", "exit_code": 0, "duration_s": 0.34, "command": "..."},
    {"name": "unittest", "status": "pass", "exit_code": 0, "duration_s": 70.45, "tests_run": 1070, "unittest_duration_s": 69.1},
    {"name": "coverage", "status": "pass", "exit_code": 0, "duration_s": 75.44, "function_coverage_pct": 66.01, "public_function_coverage_pct": 64.9, "module_coverage_pct": 100.0}
  ]
}
```
On failure, each failed silo object includes:
- `failed_tests`: exact `test_name (module.Class.method)` list (for `unittest`)
- `remediation`: actionable next command/fix hint
- `tail`: last 30 lines of captured output

For step-by-step LLM triage and test authoring recipes, see [otaku-testing-and-qa](../.agents/skills/otaku-testing-and-qa/SKILL.md).

---

## 2. Mechanical Drift Linters (`tests/lint/`)

| Linter File | What It Catches Automatically |
|---|---|
| `tests/lint/test_ast_integrity.py` | Bare `except:`, BS4 `.select()`/`.select_one()`, direct `json.loads()`, `super(Cls, self)`, mutable default args, raw `print()`, unchecked `waitForAbort()`, deprecated `ssl.PROTOCOL_TLS*`, deprecated `ListItem.setInfo()`, `int(timeout)` in `client.py`, invalid 1080i skin XML / `<defaultcontrol>` / BBCode, circular tri-addon `<requires>` dependencies, case-insensitive asset filename collisions, `>600 KB` PNGs, read-only `audit_onn_logs.py` AST safety, and repo-root VFS/mock leaks. |
| `tests/lint/test_suite_quality.py` | Zero-assertion tests, tautological `assertTrue(True)`, broad `except Exception: pass` inside tests, unexecuted `module_from_spec`, and `assertIsNotNone`-only placeholder tests. |
| `tests/lint/test_docs_and_customizations.py` | `AGENTS.md >= 22 KB` (preventing silent 24 KB truncation), invalid `.agents/skills/*/SKILL.md` YAML frontmatter, broken relative Markdown links across `README.md`/`AGENTS.md`/`CHANGEREPORT.md`/`PROJECT_REVIEW_REPORT.md`/`docs/**/*.md`/`skills`, `--fail-below 65` threshold parity across CI/scripts/docs, `CONCERN_PATTERNS` alignment with `docs/CONCERNS.md`, sequential `docs/PLANS.md` sections, `news.txt` dividers `> 32` chars, and malformed `docs/CONCERNS.md` cursor. |
| `tests/lint/test_function_coverage.py` | Dynamic discovery of 100% of `plugin.video.otaku.rpdev`, `context.otaku.rpdev`, and `service.subtitles.otaku.rpdev` `.py` modules with zero unreferenced/failing imports. |

---

## 3. CI & Release Pipeline Parity

Both `.github/workflows/ci.yml` (push/PR across Python 3.11–3.14) and `.github/workflows/release.yml` (tag `v*` across Python 3.11–3.13) execute `scripts/verify_all.py` and `scripts/e2e_v630_suite.py` concurrently (`--fail-below 65 --verbose` single-pass PEP 669 coverage on Python 3.12+, `--skip-coverage --verbose` on Python 3.11 to avoid slow `sys.settrace` duplication), and strip `tests/`, `docs/`, `teamwork/`, `__pycache__/`, and `scratch/` from all three release ZIPs (`plugin.video.otaku.rpdev`, `context.otaku.rpdev`, `service.subtitles.otaku.rpdev`). `scripts/release_addon.py` mirrors the same parallel gate locally (~72s) with automatic metadata rollback if pre-flight fails. See [otaku-release-and-verification](../.agents/skills/otaku-release-and-verification/SKILL.md) and [otaku-teamwork-and-audit](../.agents/skills/otaku-teamwork-and-audit/SKILL.md).
