# Sprint Cycle Template (`docs/teamwork/templates/SPRINT_CYCLE_TEMPLATE.md`)

**Target Milestone:** `vX.Y.Z`  
**Baseline Version:** `vA.B.C`  
**Sprint Start Date:** `YYYY-MM-DD`  
**Coordinator:** `coordinator`

---

## 1. Pre-Sprint Diagnostic & Read-Only ONN Log Review
- **Saved `docs/CONCERNS.md` Offset:** `<offset_start>` -> `<offset_end>`
- **New / Open Concerns Cataloged:** `C-XX`, `C-YY`
- **Baseline `scripts/verify_all.py` Metrics:**
  - Tests Passing: `<N>`
  - Function Coverage: `<X.XX>%`
  - Module Coverage: `100.0%`

## 2. Environment Boundary Confirmation
- [ ] Local Headless Flatpak Kodi 21 & 22 E2E harness verified available (`scripts/test_kodi_installs.py`).
- [ ] ONN `10.13.0.16` strictly locked to read-only log inspection (`scripts/audit_onn_logs.py`).

## 3. Wave Schedule & Worker Roster
| Wave | Worker Name | Owned Work Packages | Owned Files | Gate |
|---|---|---|---|---|
| Wave 1 | `wave1-...` | `SP-*`, `CR-*` | `...` | `verify_all.py` |
| Wave 2 | `wave2-...` | `NF-*` | `...` | `verify_all.py` |

## 4. Sprint Exit Criteria
- [ ] All work packages in `TASKS.md` marked `DONE` and reviewed against `REVIEW_PROCESS.md`.
- [ ] `python3 scripts/verify_all.py --fail-below <target>` passes all 4 silos with 0 warnings.
- [ ] `python3 scripts/test_kodi_installs.py --versions 21 22 --mode hermetic` passes 15/15 gates.
- [ ] `QA_SIGNOFF.md` completed and release published via `scripts/release_addon.py`.
