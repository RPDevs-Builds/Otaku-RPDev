# Otaku-RPDev Documentation & Agentic Knowledge Hub

Central index of user guides, architecture specifications, schema/route/algorithm references, testing standards, automation specs, and project skills across `plugin.video.otaku.rpdev`, `context.otaku.rpdev`, and `service.subtitles.otaku.rpdev`.

---

## 1. Quick Task-to-Document Lookup (For Developers & LLM Agents)

| When You Are Working On... | Read This First |
|---|---|
| **Engineering rules, Kodi 21/22 C++ invariants, or release policy** | [AGENTS.md](../AGENTS.md) |
| **Feature capabilities across all 3 add-ons or brainstorming** | [FEATURES.md](FEATURES.md) |
| **Cross-addon IPC (`Window(10000)`), skin widgets, TMDb Helper, Trakt, or external APIs** | [INTEGRATIONS.md](INTEGRATIONS.md) |
| **SQLite schemas (`malSync.db`, `cache.db`, `mappings.db`, `anime_metadata.db`), properties, or `source` dicts** | [DATA_MODELS_AND_STATE.md](DATA_MODELS_AND_STATE.md) |
| **Adding/debugging `@Route` URLs, `context.otaku.rpdev` actions, or `1080i` `WindowXML` dialogs** | [ROUTING_AND_UI_MAP.md](ROUTING_AND_UI_MAP.md) |
| **Title scoring, 4-tier `sortSources`, Zero-Wait failover, subtitle sync math, or `[CANON]`/`[FILLER]` skip logic** | [ALGORITHMS_AND_LOGIC.md](ALGORITHMS_AND_LOGIC.md) |
| **Torrent/hoster/embed scrapers (`pages/*.py`), extractors, FlareSolverr/WAF, or debrid providers** | [SCRAPERS_AND_EXTRACTORS.md](SCRAPERS_AND_EXTRACTORS.md) |
| **Writing/expanding unit, integration, lint, or E2E tests and checking coverage gaps** | [TESTS.md](TESTS.md) & [TESTING.md](TESTING.md) |
| **Auditing live ONN `10.13.0.16` production logs or checking open/resolved concerns** | [CONCERNS.md](CONCERNS.md) |

---

## 2. Complete Documentation Catalog

### Core Architecture & Deep-Dive Engineering References
| Document | Audience | Purpose |
|---|---|---|
| [AGENTS.md](../AGENTS.md) | LLM Agents & Devs | Authoritative engineering invariants (mechanically kept `< 22 KB` for untruncated loading). |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Developers & LLMs | High-level system architecture, module hierarchy, scraping/playback overview, and SQLite split. |
| [DATA_MODELS_AND_STATE.md](DATA_MODELS_AND_STATE.md) | Developers & LLMs | Exact SQLite table schemas (`malSync.db`, `cache.db`, `search.db`, `mappings.db`, `anime_metadata.db`), `Window(10000)` property contracts, and internal dictionary/JSON schemas. |
| [ROUTING_AND_UI_MAP.md](ROUTING_AND_UI_MAP.md) | Developers & LLMs | Complete `@Route` / `@multi_route` endpoint registry, `context.otaku.rpdev` 18-action dispatch table, and all 41 `1080i` `WindowXML` templates with Control IDs and property bindings. |
| [ALGORITHMS_AND_LOGIC.md](ALGORITHMS_AND_LOGIC.md) | Developers & LLMs | Mathematical scoring formulas (`score_title_candidate`, 4-tier relevance gate), Zero-Wait & 4-reason failover state machine, subtitle scoring & `1.03` PAL rescaling math, and 4-tag `[CANON]`/`[MIXED]`/`[FILLER]`/`[RECAP]` skip matrix. |
| [SCRAPERS_AND_EXTRACTORS.md](SCRAPERS_AND_EXTRACTORS.md) | Developers & LLMs | Per-provider scraper playbook (17 `pages/*.py` modules), domain-agnostic embed extractors, Cloudflare WAF fast-fail / FlareSolverr bypass, and 8 debrid resolver contracts. |

### Features, Integrations & User Guides
| Document | Audience | Purpose |
|---|---|---|
| [README.md](../README.md) | Everyone | Project overview, installation, release highlights, and quickstart. |
| [FEATURES.md](FEATURES.md) | Everyone & LLMs | Complete feature catalog across `plugin.video.otaku.rpdev`, `service.subtitles.otaku.rpdev`, and `context.otaku.rpdev` with routes, UI, and extension seams. |
| [INTEGRATIONS.md](INTEGRATIONS.md) | Developers & LLMs | Tri-addon IPC contracts, Kodi skin/widget refresh & overlay themes, TMDb Helper & Trakt bridges, `Otaku-Mapping-DB` dual-DB sync, and external API contracts. |
| [CONFIGURATION_GUIDE.md](CONFIGURATION_GUIDE.md) | End Users | Hardware presets, all 12 settings categories, tuning danger zones, and troubleshooting. |

### Testing, QA, Telemetry & Roadmap
| Document | Audience | Purpose |
|---|---|---|
| [TESTING.md](TESTING.md) | Developers & LLMs | 6-silo testing architecture, dual Kodi 21/22 mock harness, anti-placeholder quality standards, and UI/Settings behavioral testing guide. |
| [TESTS.md](TESTS.md) | Everyone & LLMs | Complete test suite inventory (1,232 `test_*` defs), per-addon breakdown, live function coverage snapshot (`68.59%`), and P1–P3 expansion roadmap. |
| [AUTOMATION.md](AUTOMATION.md) | DevOps & LLMs | Unified `scripts/verify_all.py --json` gate, CI/Release parity, AST/quality/doc drift linters, and LLM agent workflow integration. |
| [CONCERNS.md](CONCERNS.md) | Maintainers & LLMs | Incremental live ONN 4K Pro (`10.13.0.16`, Kodi 22) device log review cursor (`309114`), open watch items, and `R-01`–`R-58` resolved ledger. |
| [PLANS.md](PLANS.md) | Maintainers & LLMs | Architecture roadmap & release milestone ledger (`v6.3.0` → `v6.4.11` delivered milestones + `v6.5.0+` strategic backlog). |
| [teamwork/README.md](teamwork/README.md) | Multi-Agent `/teamwork` | Swarm operating manual, role charters, [SPRINT_BOARD.md](teamwork/SPRINT_BOARD.md), [REVIEW_PROCESS.md](teamwork/REVIEW_PROCESS.md), [TESTING_PROCESS.md](teamwork/TESTING_PROCESS.md), and [v6.3.0 Sprint Archive](teamwork/sprints/v6.3.0/SPRINT_CHARTER.md). |

---

## 3. Project-Local Agent Skills (`.agents/skills/`)
- [otaku-testing-and-qa](../.agents/skills/otaku-testing-and-qa/SKILL.md): Authoring, refactoring, and triaging high-signal offline tests across all 6 silos, anti-placeholder guardrails, strict Kodi 22 UI/settings verification, negative-path quotas, and `scripts/verify_all.py --json` LLM triage.
- [otaku-onn-log-review](../.agents/skills/otaku-onn-log-review/SKILL.md): Strictly read-only ONN log auditing (`scripts/audit_onn_logs.py --concerns docs/CONCERNS.md`), `C-11` vs `C-14` vs `CR-01` taxonomy, two-stage graduation (`FIXED_VERIFIED_LOCAL_E2E` -> `PRODUCTION_CONFIRMED`), and local headless Kodi 21/22 verification.
- [otaku-release-and-verification](../.agents/skills/otaku-release-and-verification/SKILL.md): Tri-addon lockstep pre-flight verification (`--fail-below 65`, `e2e_v630_suite.py`), dry-run ZIP audit, and automated tag-to-CDN publishing via `scripts/release_addon.py`.
- [otaku-teamwork-and-audit](../.agents/skills/otaku-teamwork-and-audit/SKILL.md): End-to-end `/plan` -> `/teamwork` (with in-session quota fallback) -> Adversarial Claim-to-Code Closure -> `/learn` self-improvement cycle.
