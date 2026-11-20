# Otaku-RPDev Documentation Hub

Central index of user guides, engineering references, testing standards, automation specs, and project skills.

| Document | Audience | Purpose |
|---|---|---|
| [README.md](../README.md) | Everyone | Project overview, installation, release highlights, and quickstart. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Developers & LLMs | Module map, scraping/filtering/relevance pipeline, Zero-Wait playback, Kodi 22 subtitles, SQLite WAL vs. read-only URI split. |
| [TESTING.md](TESTING.md) | Developers & LLMs | 6-silo testing architecture, dual Kodi 21/22 mock harness, anti-placeholder quality standards, and UI/Settings behavioral testing guide. |
| [AUTOMATION.md](AUTOMATION.md) | DevOps & LLMs | Unified `scripts/verify_all.py --json` gate, CI/Release parity, AST/quality/doc drift linters, and LLM agent workflow integration. |
| [CONFIGURATION_GUIDE.md](CONFIGURATION_GUIDE.md) | End Users | Hardware presets, all 12 settings categories, tuning danger zones, and troubleshooting. |
| [CONCERNS.md](CONCERNS.md) | Maintainers & LLMs | Incremental live ONN 4K Pro (`10.13.0.16`, Kodi 22) device log review cursor, open concerns, and historical resolutions. |
| [AGENTS.md](../AGENTS.md) | LLM Agents & Devs | Authoritative engineering invariants (mechanically kept `< 22 KB` for untruncated loading). |

## Project-Local Agent Skills (`.agents/skills/`)
- [otaku-testing-and-qa](../.agents/skills/otaku-testing-and-qa/SKILL.md): Authoring, refactoring, and triaging high-signal offline tests across all 6 silos, anti-placeholder guardrails, strict Kodi 22 UI/settings verification, and `scripts/verify_all.py --json` LLM triage.
- [otaku-onn-log-review](../.agents/skills/otaku-onn-log-review/SKILL.md): Incremental read-only ONN log reviews, log-rotation handling, noise triage, `docs/CONCERNS.md` updates, and local headless Kodi 22 verification via `kodi-env`.
- [otaku-release-and-verification](../.agents/skills/otaku-release-and-verification/SKILL.md): Unified pre-flight verification (`scripts/verify_all.py`) and automated tag-to-CDN publishing via `scripts/release_addon.py`.
