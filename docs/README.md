# Otaku-RPDev Documentation Hub

Central index of user guides, engineering references, testing standards, automation specs, and project skills across `plugin.video.otaku.rpdev`, `context.otaku.rpdev`, and `service.subtitles.otaku.rpdev`.

| Document | Audience | Purpose |
|---|---|---|
| [README.md](../README.md) | Everyone | Project overview, installation, release highlights, and quickstart. |
| [FEATURES.md](FEATURES.md) | Everyone & LLMs | Complete feature catalog across `plugin.video.otaku.rpdev`, `service.subtitles.otaku.rpdev`, and `context.otaku.rpdev` with routes, UI, and extension seams. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Developers & LLMs | Module map, scraping/filtering/relevance pipeline, Zero-Wait playback, Kodi 22 subtitles, SQLite WAL vs. read-only URI split. |
| [TESTING.md](TESTING.md) | Developers & LLMs | 6-silo testing architecture, dual Kodi 21/22 mock harness, anti-placeholder quality standards, and UI/Settings behavioral testing guide. |
| [AUTOMATION.md](AUTOMATION.md) | DevOps & LLMs | Unified `scripts/verify_all.py --json` gate, CI/Release parity, AST/quality/doc drift linters, and LLM agent workflow integration. |
| [CONFIGURATION_GUIDE.md](CONFIGURATION_GUIDE.md) | End Users | Hardware presets, all 12 settings categories, tuning danger zones, and troubleshooting. |
| [CONCERNS.md](CONCERNS.md) | Maintainers & LLMs | Incremental live ONN 4K Pro (`10.13.0.16`, Kodi 22) device log review cursor, open concerns, and historical resolutions. |
| [PLANS.md](PLANS.md) | Maintainers & LLMs | Phased `v6.3.0` architecture roadmap, environment safety boundaries, dependency graph, risk register, and Definition of Done. |
| [teamwork/README.md](teamwork/README.md) | Multi-Agent `/teamwork` | Swarm operating manual, role charters, [SPRINT_BOARD.md](teamwork/SPRINT_BOARD.md), [REVIEW_PROCESS.md](teamwork/REVIEW_PROCESS.md), [TESTING_PROCESS.md](teamwork/TESTING_PROCESS.md), and [v6.3.0 Sprint Charter](teamwork/sprints/v6.3.0/SPRINT_CHARTER.md). |
| [AGENTS.md](../AGENTS.md) | LLM Agents & Devs | Authoritative engineering invariants (mechanically kept `< 22 KB` for untruncated loading). |

## Project-Local Agent Skills (`.agents/skills/`)
- [otaku-testing-and-qa](../.agents/skills/otaku-testing-and-qa/SKILL.md): Authoring, refactoring, and triaging high-signal offline tests across all 6 silos, anti-placeholder guardrails, strict Kodi 22 UI/settings verification, negative-path quotas, and `scripts/verify_all.py --json` LLM triage.
- [otaku-onn-log-review](../.agents/skills/otaku-onn-log-review/SKILL.md): Strictly read-only ONN log auditing (`scripts/audit_onn_logs.py --concerns docs/CONCERNS.md`), `C-11` vs `C-14` vs `CR-01` taxonomy, two-stage graduation (`FIXED_VERIFIED_LOCAL_E2E` -> `PRODUCTION_CONFIRMED`), and local headless Kodi 21/22 verification.
- [otaku-release-and-verification](../.agents/skills/otaku-release-and-verification/SKILL.md): Tri-addon lockstep pre-flight verification (`--fail-below 65`, `e2e_v630_suite.py`), dry-run ZIP audit, and automated tag-to-CDN publishing via `scripts/release_addon.py`.
- [otaku-teamwork-and-audit](../.agents/skills/otaku-teamwork-and-audit/SKILL.md): End-to-end `/plan` -> `/teamwork` (with in-session quota fallback) -> Adversarial Claim-to-Code Closure -> `/learn` self-improvement cycle.
