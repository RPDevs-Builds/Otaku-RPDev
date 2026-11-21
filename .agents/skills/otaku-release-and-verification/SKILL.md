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

## 0. Fast Deterministic Release Dispatch (Default Path)
When changes are tested and the user asks to release/push a new version, dispatch **one command** directly — do **not** run redundant full `verify_all.py` / `e2e_v630_suite.py` pre-checks beforehand or reinvent git tag commands:
1. Check `git status --short`; commit any pending working-tree edits cleanly (`git commit --no-gpg-sign -m "..."`).
2. Run `python3 scripts/test_kodi_installs.py --versions 21 22 --mode hermetic` **only if** add-on runtime code changed since the last clean headless Kodi 21/22 run.
3. Dispatch immediately:
   ```bash
   python3 scripts/release_addon.py \
     --bump patch \
     --title "<Short Banner Title <=32 chars>" \
     -m "- Bullet 1;- Bullet 2"
   ```
   Step 2 runs `verify_all.py --fail-below 65` (single-pass PEP 669 `unittest+cov` on Python 3.12+) and `e2e_v630_suite.py` **concurrently** (~72s local gate), auto-rolls back `addon.xml`/`news.txt`/`changelog.txt` if pre-flight fails, pushes `main` + `vX.Y.Z`, watches GitHub Actions (`release.yml` ~1.5–2m), and verifies GitHub Release + live CDN `https://kodi.repo.iamrp.dev/`.

## 1. Unified Pre-Flight Gates (CI / Release Parity)
Both `.github/workflows/ci.yml` and `.github/workflows/release.yml` execute `verify_all.py` and `e2e_v630_suite.py` in parallel (`--fail-below 65 --verbose` on Python 3.12+, `--skip-coverage --verbose` on Python 3.11 to avoid slow `sys.settrace` duplication):
```bash
python3 scripts/verify_all.py --fail-below 65 --verbose
python3 scripts/e2e_v630_suite.py
python3 scripts/test_kodi_installs.py --versions 21 22 --mode hermetic
```
- Silos executed by `verify_all.py`: `ruff` (`E9,F63,F7,F82,F811,F405,F541`), `compileall`, and combined single-pass `unittest+cov` on Python 3.12+ (enforcing strict `resources.*` warnings-as-errors, 100% module coverage, and `>= 65%` function coverage in ~70s instead of running all 1,076 tests twice).
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
