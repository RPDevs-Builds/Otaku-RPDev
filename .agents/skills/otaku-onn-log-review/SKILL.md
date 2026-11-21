---
name: otaku-onn-log-review
description: >-
  Strictly read-only telemetry audit workflow for ONN 4K Pro (10.13.0.16) via
  scripts/audit_onn_logs.py, canonical concern taxonomy (C-11 vs C-14 vs CR-01),
  two-stage concern graduation (FIXED_VERIFIED_LOCAL_E2E -> PRODUCTION_CONFIRMED),
  and local headless Kodi 21/22 verification.
---

# Otaku-RPDev Read-Only ONN Log Review & Local Kodi 21/22 Verification

> [!CAUTION]
> **ONN `10.13.0.16` IS STRICTLY READ-ONLY PRODUCTION TELEMETRY.**
> **NEVER** push files via ADB, sideload builds, edit configs/databases in place, trigger `UpdateAddonRepos`, or restart `10.13.0.16`. It receives updates exclusively through the standard Kodi CDN repository (`https://kodi.repo.iamrp.dev/`). Execute all runtime/install tests in the local headless Flatpak Kodi 21/22 harness.

## 1. Primary Read-Only Log Audit (`scripts/audit_onn_logs.py`)
Run from `/mnt/sharedroot/projects/RPDevs-Builds/Otaku-RPDev`:
```bash
python3 scripts/audit_onn_logs.py --concerns docs/CONCERNS.md --json <scratch>/onn_audit.json
```
- Reads `Next review offset` from `docs/CONCERNS.md` and issues **only** an HTTP `GET http://10.13.0.16:8081/tail?offset=<N>` (timeout 10s; zero SSH/ADB subprocesses).
- For offline testing against captured fixtures:
  ```bash
  python3 scripts/audit_onn_logs.py --input tests/fixtures/onn_kodi_log_sample.txt --offset 0 --json -
  ```
- Inspect `rotated` and `next_offset`: if `Starting Kodi (` appears or `X-Seek-Offset < requested_offset`, update `Log session started` and reset `Next review offset` to `next_offset`.

## 2. Canonical Concern Taxonomy (`C-11` vs `C-14` vs `CR-01`)
Keep concern IDs strictly separated (enforced by `tests/lint/test_docs_and_customizations.py`):
- **`C-06`**: `CHANGE_LOG` / `SOLVER_INST` missing `exit_code()` / `GetDirectory - Error getting plugin://`.
- **`C-11`**: `OpenStream - Unable to create subtitle parser` (Kodi 22 WebVTT/ASS VFS / cue failures).
- **`C-14`**: External Premiumize CDN (`energycdn.com`) transient CURL-56 resets (`CCurlFile::CReadState::FillBuffer Failed: Failure when receiving data from the peer(56)`). **Never** conflate `C-14` with subtitle parser (`C-11`) or studio logo collisions (`CR-01`).
- **`C-34`**: Zero-Wait background `resolve_silent()` failing to prune dead lead candidates.
- **`C-35`**: `WatchlistFlavorAuth` modal missing `try...finally` disposal or screensaver idle timeout.

## 3. Local Headless Kodi 21 & 22 E2E Verification (`scripts/test_kodi_installs.py`)
Verify all fixes strictly in local Flatpak Kodi 21 (`21.3-Omega`) & Kodi 22 (`22.0-RC2`):
```bash
python3 scripts/test_kodi_installs.py --versions 21 22 --mode hermetic
```
Audit the local E2E output for `10/10` menus, `8/8` modals, `494/494` runtime settings, `Mock/Chapters` playback, clean shutdown `< 20s`, and `clean_audit=True` (`0` tracebacks / `Invalid setting type` / SWIG leaks).

## 4. Two-Stage Concern Graduation & Release
1. **`FIXED_VERIFIED_LOCAL_E2E`**: Earned after regression tests + `python3 scripts/verify_all.py --fail-below 65` + `scripts/e2e_v630_suite.py` + `scripts/test_kodi_installs.py --versions 21 22 --mode hermetic` pass locally.
2. **`PRODUCTION_CONFIRMED`**: Earned **only** after release via `scripts/release_addon.py` and passive read-only `scripts/audit_onn_logs.py` observation once `10.13.0.16` updates through Kodi's standard repository cycle.
3. Reference: [docs/CONCERNS.md](../../../docs/CONCERNS.md) and [docs/teamwork/TESTING_PROCESS.md](../../../docs/teamwork/TESTING_PROCESS.md).
