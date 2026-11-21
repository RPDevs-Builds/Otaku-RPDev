# Otaku-RPDev 4-Tier Testing & QA Process (`docs/teamwork/TESTING_PROCESS.md`)

Defines the mandatory 4-tier verification pipeline for **Otaku-RPDev v6.3.0**, enforcing strict separation between the local headless Kodi 21/22 E2E test bed and passive read-only ONN `10.13.0.16` telemetry review.

---

## Tier 1: Real-Time Local Developer & Worker QA (During Authoring)
Executed continuously by each worker before marking any task complete:
1. **Targeted Unit & Consumer Tests (with strict project warnings-as-errors):**
   ```bash
   python3 -W default -W error::DeprecationWarning:resources -W error::ResourceWarning:resources \
     -m unittest tests/unit/<target_test_file>.py -v
   ```
2. **Mechanical Lint & Drift Guardrails:**
   ```bash
   python3 -m unittest \
     tests/lint/test_ast_integrity.py \
     tests/lint/test_suite_quality.py \
     tests/lint/test_docs_and_customizations.py -v
   ```
3. **Settings Schema & Orphan Pruner Verification (whenever touching `settings.xml` or `strings.po`):**
   ```bash
   python3 -m unittest \
     tests/unit/test_settings_schema_and_code_references.py \
     tests/unit/test_clean_settings.py \
     tests/unit/test_all_settings_outcomes.py -v
   ```

---

## Tier 2: Unified Multi-Silo Pre-Flight Gate (`scripts/verify_all.py`)
Executed at the end of every wave and inside GitHub Actions CI (`ci.yml`, `release.yml`) and `scripts/release_addon.py` (Waves 1–2 enforce default `--fail-below 60`; Gate 3 / `v6.3.0` release enforces `--fail-below 65`):
```bash
python3 scripts/verify_all.py --fail-below 65 --json <scratch>/verify_v630.json
```
- **Silo 1 (`ruff`)**: `ruff check --select E9,F63,F7,F82,F811,F405,F541` across `plugin.video.otaku.rpdev`, `context.otaku.rpdev`, `service.subtitles.otaku.rpdev`, `tests`, `scripts`.
- **Silo 2 (`compileall`)**: Bytecode syntax validation across all 5 directories.
- **Silo 3 (`unittest`)**: Full offline discovery (`>= 1,080` tests) with `-W error::DeprecationWarning:resources -W error::ResourceWarning:resources`.
- **Silo 4 (`coverage`)**: `scripts/audit_function_coverage.py --fail-below 65` enforcing **100% module coverage** and **`>= 65.0%` function coverage**.

---

## Tier 3: Local Headless Flatpak Kodi 21.3 (Omega) & Kodi 22.0-RC2 (Piers) E2E Harness
The **ONLY** runtime test environment for installing add-on builds, testing C++ settings deserialization, rendering WindowXML dialogs, and verifying playback:
```bash
python3 scripts/test_kodi_installs.py --versions 21 22 --mode hermetic
```
Verifies all 15 runtime E2E gates inside real isolated Kodi 21 and Kodi 22 Flatpak instances under `xvfb-run`:
1. Tri-addon installation & manifest registration (`plugin.video.otaku.rpdev`, `context.otaku.rpdev`, `service.subtitles.otaku.rpdev`).
2. C++ `CAddonSettings` deserialization of all declared settings with `0` `Invalid setting type` errors.
3. Core directory navigation across all 10 primary menus.
4. Modal `WindowXML` lifecycle across custom dialogs with `0` focus or SWIG director leaks.
5. Browser backends (`OtakuBrowser`, `MalBrowser`, `AniListBrowser`) & search.
6. Episode listing, filler/recap badges, and `InfoTagVideo` population.
7. Spoiler shield image masking.
8. Metadata indexers (`Simkl`, `AniZip`, `Jikan`, `Kitsu`, `Otaku`).
9. Setting-effect verification on rendered `ListItem` output.
10. Reviews, Watchlist Drift Auditor, Series Override Profile, and System Health routes.
11. `service.py` startup (`clean_settings`, `SyncDatabase._migrate_database()`, `mappings.db` integrity check).
12. `context.otaku.rpdev` & `service.subtitles.otaku.rpdev` companion route execution.
13. `VideoPlayer` playback with chapter population and VFS-registered subtitles.
14. Clean `< 10s` `Application.Quit` teardown (verifying abort-responsive `waitForAbort` loops).
15. Zero-tolerance `kodi.log` audit (`0` Python tracebacks, `0` deprecations, `0` resource warnings, `0` SWIG leaks).

---

## Tier 4: Post-Release Passive Read-Only ONN `10.13.0.16` Telemetry Review
Executed **after** `scripts/release_addon.py` publishes `v6.3.0` to GitHub Releases and `https://kodi.repo.iamrp.dev/`, and after the user updates their ONN device via Kodi's standard repository update mechanism:
```bash
python3 scripts/audit_onn_logs.py --concerns docs/CONCERNS.md
```
- Reads `http://10.13.0.16:8081/tail?offset=<Next review offset>` strictly read-only.
- Audits real-world playback, Zero-Wait transitions, subtitle auto-downloads, and watchlist syncs.
- Updates `docs/CONCERNS.md` review cursor and graduates verified concerns to Resolved.
