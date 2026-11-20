---
name: otaku-release-and-verification
description: >-
  Pre-flight verification gate and automated tag-based release pipeline for
  Otaku-RPDev (ruff, compileall, -W default unittest suite, coverage audit,
  and scripts/release_addon.py GitHub Actions + CDN sync). Use when validating
  changes or publishing a new Otaku-RPDev release.
---

# Otaku-RPDev Verification & Release Runbook

Run all commands from `/mnt/sharedroot/projects/RPDevs-Builds/Otaku-RPDev`.

## 1. Local Pre-Flight Verification Gate (`scripts/verify_all.py`)
Run the unified multi-silo gate (identical to GitHub Actions `ci.yml`, `release.yml`, and `scripts/release_addon.py`):
```bash
python3 scripts/verify_all.py --fail-below 60
```
For machine-readable LLM diagnostics (JSON report with failing test IDs, coverage metrics, and remediation hints):
```bash
python3 scripts/verify_all.py --fail-below 60 --json /tmp/verify_report.json
```
- Silos executed in order: `ruff` (`E9,F63,F7,F82,F811,F405,F541`), `compileall`, `unittest discover -s tests` (strict project warnings-as-errors for `resources.*` `DeprecationWarning`/`ResourceWarning`), and `audit_function_coverage.py --fail-below 60` (100% module coverage). Pass `--e2e` to also run headless Flatpak Kodi 22 E2E.
- For fast targeted lint + settings + UI checks during development:
  ```bash
  python3 -W default -m unittest \
    tests/lint/test_ast_integrity.py \
    tests/lint/test_suite_quality.py \
    tests/lint/test_docs_and_customizations.py \
    tests/unit/test_settings_schema_and_code_references.py \
    tests/unit/test_all_settings_outcomes.py \
    tests/unit/test_end_user_ui_and_routes.py \
    tests/unit/test_kodi_21_22_dual_compat.py
  ```

## 2. Automated Tag-Based Release (`scripts/release_addon.py`)
Never push code directly to live Kodi devices. Publish strictly via the release orchestrator:
```bash
python3 scripts/release_addon.py \
  --bump patch \
  --title "<Short Banner Title <=32 chars>" \
  -m "- Bullet 1
- Bullet 2"
```
- Use `--bump minor` / `--bump major` or `--version X.Y.Z` only when explicitly requested.
- Use `--dry-run` for metadata + pre-flight validation without committing or pushing.
- Use `--verify-tag vX.Y.Z` to re-verify GitHub Release assets and live CDN propagation at `https://kodi.repo.iamrp.dev/`.

## 3. Recovering from a Failed Pre-Flight Inside `release_addon.py`
If `release_addon.py` fails during Step 2 (after Step 1 bumped metadata files), revert the 3 metadata files before re-running `--bump patch` so `changelog.txt` does not accumulate duplicate headers:
```bash
git checkout -- \
  plugin.video.otaku.rpdev/addon.xml \
  plugin.video.otaku.rpdev/news.txt \
  plugin.video.otaku.rpdev/changelog.txt
```
- All manual git commits must pass `--no-gpg-sign` (`git commit --no-gpg-sign -m "..."`).
