---
name: otaku-teamwork-and-audit
description: >-
  End-to-end Otaku-RPDev engineering lifecycle combining /plan, /teamwork (or
  in-session fallback on quota/request), Stage 3 Adversarial Claim-to-Code Closure,
  and /learn synthesis. Use when planning multi-wave sprints, auditing worker
  completion claims, or eliminating repo-wide documentation/linter drift.
---

# Otaku-RPDev Multi-Agent Execution, Adversarial Closure & `/learn` Cycle

Execute all operations inside `/mnt/sharedroot/projects/RPDevs-Builds/Otaku-RPDev/`. Zero writes or mutating commands against `10.13.0.16`.

## 1. Execution Modes (`/teamwork` vs. In-Session Fallback)
1. Use `/plan` first to align read-only baselines (`docs/CONCERNS.md`, `docs/PLANS.md`, `docs/teamwork/SPRINT_BOARD.md`).
2. Execute waves strictly in dependency order with `scripts/verify_all.py --fail-below 65` + `scripts/e2e_v630_suite.py` between gates.
3. **In-Session Fallback Rule**: If spawning `/teamwork` sub-sessions encounters `429 RESOURCE_EXHAUSTED` or the user asks to run in the active session, complete the entire workflow in-session without spawning subagents.

## 2. Mandatory Stage 3 Adversarial Claim-to-Code Closure Audit
Never accept self-reported completion at face value before release or sign-off. Run an independent adversarial trace checking:
1. **Live Call-Site Wiring**: Confirm helpers are wired into production callers (e.g., `scrobble_retry_queue` replay inside `service.py`, `episode_offset` isolated to `MetaBrowser.get_sources()` away from `canonical_episode` scrobbling, `watchlist_drift_auditor` dry-run count + `yesno_dialog` gate).
2. **Column-Level Schema Idempotency**: Verify `SyncDatabase._create_all_tables()` invokes `_ensure_column_migrations()` (`PRAGMA table_info`) unconditionally on startup regardless of `SCHEMA_VERSION` equality.
3. **Settings & Profile Round-Trip**: Confirm every new setting is within `#30000`–`#30999`, consumed in runtime code, and serialized/restored alongside `series_overrides` in `settings_manager.py`.
4. **Dry-Run Release ZIP & Concern Taxonomy Check**: Verify dry-run built ZIPs across all 3 add-ons strip `tests/`, `docs/`, `teamwork/`, `__pycache__/`, and `scratch/`, contain `0` case collisions, and `CONCERN_PATTERNS` in `scripts/audit_onn_logs.py` matches `docs/CONCERNS.md`.
5. **Negative/Edge Quota (2:1)**: Ensure every `NF-*` package has at least 2 negative/edge tests per happy-path test.

## 3. Post-Release `/learn` Synthesis Loop
1. Extract live ground truth first (addon manifests, `settings.xml`, `strings.po`, `ALL_SERVICES`, `verify_all.py`, CI workflows, test output).
2. Encode newly discovered bugs or drift patterns directly into executable `tests/lint/` checks (`test_ast_integrity.py`, `test_docs_and_customizations.py`) rather than prose alone.
3. Sync docs (`AGENTS.md < 22,000` bytes, `docs/*.md`, `CHANGEREPORT.md`, `docs/teamwork/*`) and `.agents/skills/*/SKILL.md`.
4. Verify with `scripts/qa_fast.py`, `scripts/verify_all.py --fail-below 65 --verbose`, and `scripts/e2e_v630_suite.py`.

## 4. References
- Governance hub: [docs/teamwork/README.md](../../../docs/teamwork/README.md)
- Code review checklist: [docs/teamwork/REVIEW_PROCESS.md](../../../docs/teamwork/REVIEW_PROCESS.md)
- Phased roadmap: [docs/PLANS.md](../../../docs/PLANS.md)
