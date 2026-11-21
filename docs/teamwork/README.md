# Otaku-RPDev Multi-Agent `/teamwork` Operating Manual (`docs/teamwork/README.md`)

Authoritative coordination protocol, role charters, workspace isolation rules, and quality gates for executing **Otaku-RPDev v6.3.0** via `/teamwork`.

---

## 1. Golden Environmental Invariant (Non-Negotiable)

> [!CAUTION]
> **ONN 4K Pro (`10.13.0.16`) is a live end-user production media center.**
> - **STRICTLY READ-ONLY LOG REVIEW ONLY** (`http://10.13.0.16:8081/tail?offset=<N>` HTTP GET or offline `--input` fixture via `scripts/audit_onn_logs.py` — zero subprocess SSH/ADB).
> - **NEVER** push files, sideload zips, edit files in place, trigger `UpdateAddonRepos`, manipulate `Addons33.db`, or issue remote control commands to `10.13.0.16`.
> - **Local Headless Flatpak Kodi 21 & 22 (`scripts/test_kodi_installs.py`)** is the **ONLY** runtime test bed for addon installation, UI rendering, and E2E playback verification.

---

## 2. Swarm Roster & Role Charters

| Roster Name | Role Title | Primary Ownership | Workspace Mode |
|---|---|---|---|
| `coordinator` | Lead Architect & Release Integrator | Wave scheduling, cross-worker merge integration, `resources/settings.xml` + `strings.po` schema lock, `scripts/verify_all.py` (`Gate 1/2` `--fail-below 60`, `Gate 3` `--fail-below 65`), headless Kodi 21/22 E2E, local `--no-gpg-sign` staging (**no push until approval**) | `inherit` |
| `wave1-foundation` | Wave 1 Diagnostics & QA Foundation Engineer (`M1`) | `SP-01`..`SP-03` (`SPRINT_BOARD.md` sync, `C-34`/`C-35` closure + regression tests, read-only `scripts/audit_onn_logs.py`, fast QA runner, `.pre-commit-config.yaml`, Wave-1 AST guardrails, `tests/conftest.py` repo hygiene) | `share` |
| `wave2-hardening` | Wave 2 Codebase Hardening & Parity Engineer (`M2`) | `CR-01`..`CR-05` (studio collision cleanup, PNG optimization, SQLite WAL/RO URI parity, modal disposal & `C-06` & tri-addon docs sync, CI/release packaging parity, abort-safe `waitForAbort` & `sanitize_log`) | `share` |
| `wave3-core` | Wave 3a Core Infrastructure Engineer (`M3a`) | `NF-04` (`AdaptiveCircuitBreaker` in `domains.py`), `NF-06` (`series_overrides` table in `SyncDatabase` `1.0.14` & profile dialog) | `share` |
| `wave3-features` | Wave 3b Parallel Feature Engineers (`M3b`) | `NF-05` (`mappings.db` `.xz`/`.gz` + SHA-256 + `quick_check` + `.bak` rollback), `NF-01` (multi-tracker conflict engine & `scrobble_retry_queue`), `NF-08` (Cross-Watchlist Drift Auditor), `NF-02` (widget-aware `context.otaku.rpdev` quick actions), `NF-03` (filler/recap badges, binge auto-skip filler, OP/ED offset tuning), `NF-07` (Subtitle Intelligence v2) | `share` |
| `e2e-track` | Parallel Opaque-Box E2E Track (`E2E_testing_track`) | Requirement-driven Tier 1–4 E2E suite (`TEST_INFRA.md` -> `TEST_READY.md`) | `share` |
| `qa-verifier` | Independent Code Reviewer & E2E QA Auditor (`M4`) | Executes 5-stage `REVIEW_PROCESS.md` audit, anti-placeholder test verification (`test_suite_quality.py`), `scripts/verify_all.py --fail-below 65`, and headless Kodi 21/22 E2E signoff (`QA_SIGNOFF.md`) | `inherit` |

---

## 3. Shared File Locking & Merge Protocol

To prevent merge conflicts across concurrent workers:
1. **`resources/settings.xml` & `resources/language/resource.language.en_gb/strings.po`**:
   - Workers propose new setting IDs and string IDs (**`#30999+`**; `#30000`–`#30998` are already allocated) in their wave completion report or apply them in a single coordinated wave handoff validated immediately with `python3 -m unittest tests/unit/test_settings_schema_and_code_references.py tests/unit/test_clean_settings.py tests/unit/test_all_settings_outcomes.py -v`.
2. **`resources/lib/ui/database.py` & `resources/lib/ui/database_sync.py`**:
   - Wave 3a (`M3a`) lands schema additions (`series_overrides`, `SCHEMA_VERSION = '1.0.14'`) first; Wave 3b (`M3b`) adds `scrobble_retry_queue` on top of the updated schema.
3. **`AGENTS.md` Context Budget (`< 22,000` bytes)**:
   - Only `coordinator` or `wave2-hardening` (`CR-03`) edits `AGENTS.md`, immediately running `python3 -m unittest tests.lint.test_docs_and_customizations` to verify the byte count stays strictly `< 22,000` bytes.
4. **Git Commit Invariant**:
   - Every commit across all workers must pass `--no-gpg-sign` (`git commit --no-gpg-sign -m "..."`), and commits/tags are staged locally only — never pushed until final user approval.

---

## 4. Directory Index (`docs/teamwork/`)

- [SPRINT_BOARD.md](SPRINT_BOARD.md): Master prioritized task ledger (`SP-01`–`SP-03`, `CR-01`–`CR-05`, `NF-01`–`NF-08`, `E2E-Track`, `QA-01`, `C-34`, `C-35`).
- [REVIEW_PROCESS.md](REVIEW_PROCESS.md): 5-stage structured code review checklist enforced before any task moves to `DONE`.
- [TESTING_PROCESS.md](TESTING_PROCESS.md): 4-tier QA verification pipeline (local unit/lint -> `verify_all.py` -> headless Kodi 21/22 E2E -> post-release passive read-only `10.13.0.16` log audit).
- [templates/SPRINT_CYCLE_TEMPLATE.md](templates/SPRINT_CYCLE_TEMPLATE.md): Reusable template for future sprint cycles.
- [templates/ADR_TEMPLATE.md](templates/ADR_TEMPLATE.md): Architecture Decision Record template.
- [sprints/v6.3.0/SPRINT_CHARTER.md](sprints/v6.3.0/SPRINT_CHARTER.md): Charter, scope, and architectural boundaries for `v6.3.0`.
- [sprints/v6.3.0/TASKS.md](sprints/v6.3.0/TASKS.md): File-level implementation checklist and test mapping for `v6.3.0`.
- [sprints/v6.3.0/QA_SIGNOFF.md](sprints/v6.3.0/QA_SIGNOFF.md): Pre-release verification ledger and signoff checklist for `v6.3.0`.
