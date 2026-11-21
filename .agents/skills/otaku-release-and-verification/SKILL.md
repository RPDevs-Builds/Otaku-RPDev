---
name: otaku-release-and-verification
description: >-
  Tri-addon lockstep pre-flight gate and automated GitHub Actions release pipeline
  for Otaku-RPDev (plugin.video.otaku.rpdev, context.otaku.rpdev, and
  service.subtitles.otaku.rpdev) via verify_all.py --fail-below 65,
  e2e_v630_suite.py, dry-run ZIP audit, and scripts/release_addon.py.
---

# Otaku-RPDev Tri-Addon Verification & Release Runbook

Run all commands from `/mnt/sharedroot/projects/RPDevs-Builds/Otaku-RPDev`.

## 1. Unified Pre-Flight Gates (CI / Release Parity)
Both `.github/workflows/ci.yml` and `.github/workflows/release.yml` enforce:
```bash
python3 scripts/verify_all.py --fail-below 65 --verbose
python3 scripts/e2e_v630_suite.py
python3 scripts/test_kodi_installs.py --versions 21 22 --mode hermetic
```
- Silos executed by `verify_all.py`: `ruff` (`E9,F63,F7,F82,F811,F405,F541`), `compileall`, `unittest discover -s tests` (strict `resources.*` warnings-as-errors), and `audit_function_coverage.py --fail-below 65` (100% module coverage across all 3 add-ons).
- Quick incremental check while editing: `python3 scripts/qa_fast.py`.

## 2. Tri-Addon Packaging & Dry-Run ZIP Audit
Before tagging a release:
1. Verify all 3 `addon.xml` manifests form an acyclic DAG (`context.otaku.rpdev` and `service.subtitles.otaku.rpdev` depend only on `xbmc.python`).
2. Confirm dry-run release ZIPs for all 3 add-ons exclude `tests/`, `docs/`, `teamwork/`, `__pycache__/`, and `scratch/`, and have `0` case-insensitive filename collisions across studio logos and assets (`CR-01` / `CR-04`).
3. Ensure `news.txt` horizontal `=`/`-` dividers stay `<= 32` characters (multi-line release banners in `update_news_txt()` demote cleanly to 32-char `---` dividers).

## 3. Automated Tag-Based Release (`scripts/release_addon.py`)
Never push files directly to live Kodi hardware (`10.13.0.16`). Publish strictly via GitHub Actions tag releases (`v*`):
```bash
python3 scripts/release_addon.py \
  --bump patch \
  --title "<Short Banner Title <=32 chars>" \
  -m "- Bullet 1
- Bullet 2"
```
- Use `--dry-run` for metadata + pre-flight validation without committing or pushing, and `--verify-tag vX.Y.Z` to verify GitHub Release assets (`SHA256SUMS.txt`, `MD5SUMS.txt`, and all 3 add-on `.zip`s) plus HTTP 200 CDN availability on `https://kodi.repo.iamrp.dev/`.
- If Step 2 pre-flight fails after Step 1 bumped metadata files, revert before re-running:
  ```bash
  git checkout -- \
    plugin.video.otaku.rpdev/addon.xml \
    plugin.video.otaku.rpdev/news.txt \
    plugin.video.otaku.rpdev/changelog.txt
  ```
- All manual git commits must pass `--no-gpg-sign` (`git commit --no-gpg-sign -m "..."`) and annotated tags `--no-sign`.

## 4. References
- Pipeline specification: [docs/AUTOMATION.md](../../../docs/AUTOMATION.md)
- Release gate checklist: [docs/teamwork/REVIEW_PROCESS.md](../../../docs/teamwork/REVIEW_PROCESS.md)
