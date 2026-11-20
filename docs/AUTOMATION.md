# Otaku-RPDev Verification Automation & LLM Integration

This document defines the unified verification runner, CI/release gate parity, automated drift linters, and machine-readable JSON interface built for developers and autonomous LLM agents.

---

## 1. Unified Multi-Silo Runner (`scripts/verify_all.py`)

Local development, GitHub Actions CI (`.github/workflows/ci.yml`), Release CI (`.github/workflows/release.yml`), `scripts/release_addon.py`, and LLM agents all invoke the exact same gate:

```bash
# Standard developer / CI run (Silos 1–4, strict project warnings-as-errors)
python3 scripts/verify_all.py

# Machine-readable JSON output for LLM agent consumption
python3 scripts/verify_all.py --json /tmp/verify_report.json

# Include headless Flatpak Kodi 22 hermetic E2E suite (Silo 5)
python3 scripts/verify_all.py --e2e --json /tmp/verify_report.json
```

### JSON Report Schema (`--json`)
```json
{
  "overall_status": "pass",
  "python_version": "3.12.3",
  "total_duration_s": 131.81,
  "strict_project_warnings": true,
  "silos": [
    {"name": "ruff", "status": "pass", "exit_code": 0, "duration_s": 0.11, "command": "..."},
    {"name": "compileall", "status": "pass", "exit_code": 0, "duration_s": 0.3, "command": "..."},
    {"name": "unittest", "status": "pass", "exit_code": 0, "duration_s": 66.28, "tests_run": 1014, "unittest_duration_s": 64.871},
    {"name": "coverage", "status": "pass", "exit_code": 0, "duration_s": 65.12, "function_coverage_pct": 64.28, "public_function_coverage_pct": 63.29, "module_coverage_pct": 100.0}
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
| `tests/lint/test_ast_integrity.py` | Bare `except:`, BS4 `.select()`/`.select_one()`, direct `json.loads()`, `super(Cls, self)`, mutable default args, raw `print()`, unchecked `waitForAbort()`, deprecated `ssl.PROTOCOL_TLS*`, deprecated `ListItem.setInfo()`, `int(timeout)` in `client.py`, invalid 1080i skin XML / `<defaultcontrol>` / BBCode. |
| `tests/lint/test_suite_quality.py` | Zero-assertion tests, tautological `assertTrue(True)`, broad `except Exception: pass` inside tests, unexecuted `module_from_spec`, and `assertIsNotNone`-only placeholder tests. |
| `tests/lint/test_docs_and_customizations.py` | `AGENTS.md >= 22 KB` (preventing silent 24 KB truncation), invalid `.agents/skills/*/SKILL.md` YAML frontmatter, broken relative Markdown links across `README.md`/`AGENTS.md`/`docs/*.md`, `news.txt` dividers `> 32` chars, and malformed `docs/CONCERNS.md` cursor. |
| `tests/lint/test_function_coverage.py` | Dynamic discovery of 100% of plugin + context `.py` modules with zero unreferenced/failing imports. |

---

## 3. CI & Release Pipeline Parity

Both `.github/workflows/ci.yml` (push/PR across Python 3.11–3.14) and `.github/workflows/release.yml` (tag `v*` across Python 3.11–3.13) run `python3 scripts/verify_all.py`, guaranteeing that release builds enforce the exact same test-quality, doc-drift, strict warning, and function coverage gates as PR checks.
