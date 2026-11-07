# RPDevs-Builds Project Workspace Rules

## Infrastructure Environment Reference
- **Single Source of Truth**: `/mnt/sharedroot/projects/infra-audit-engine/docs/CURRENT_ENV.yml` contains the authoritative state, node hardware specs, networking interfaces, OpenWrt configs, and Docker status across `t430`, `llmadmin01`, and `edge`.
- **Environment Audit Orchestrator**: Run `python src/orchestrator.py` from `/mnt/sharedroot/projects/infra-audit-engine` (using `.venv` Python 3.12) to refresh `CURRENT_ENV.yml` and log configuration drift.

## Reusable Helper Script Management Protocol
- **Script Location**: All reusable small/utility scripts created for organizational maintenance, repo auditing, telemetry, or fleet checks must be stored under `/home/llmuser/projects/.scripts/`.
- **Subdirectory Categorization**:
  - Python scripts: `/home/llmuser/projects/.scripts/python/`
  - Shell scripts: `/home/llmuser/projects/.scripts/shell/`
- **Master Script Registry**: Maintain `/home/llmuser/projects/.scripts/SCRIPTS.md`. Every script added must be documented with labels, path, description, and usage commands.

## Historical Plan & Walkthrough Archival Protocol
- **Plan Archival Location**: Historical copies of all Implementation Plans (`implementation_plan.md`) and Walkthroughs (`walkthrough.md`) must be archived under `/home/llmuser/projects/.plans/<date>/<project>/file_<datetime>.md`.
- **Master Plans Index**: Maintain `/home/llmuser/projects/.plans/INDEX.md`. Every archived plan and walkthrough must be cataloged in `INDEX.md` with links, dates, project names, and concise summaries.
- **Naming Pattern**: Format path as `/home/llmuser/projects/.plans/YYYY-MM-DD/<project_name>/implementation_plan_YYYY-MM-DD_HHMMSS.md` and `walkthrough_YYYY-MM-DD_HHMMSS.md`.

## Workspace Home & Execution Baseline
- **Execution Root**: All future projects and commands are launched from `/home/llmuser/projects` as the home directory of reference unless explicitly specified otherwise.

## Deployment & Addon Release Mandate
- **No Direct Target Updates**: Never push code or update addon files directly onto target devices (such as ONN Android TV / Kodi via ADB).
- **GitHub Pipeline Validation**: All releases must go through GitHub (`release_addon.py` -> GitHub push -> CDN repo update) so that the live device receives updates via the standard Kodi repository update mechanism. This rigorously tests the build process, metadata generation, and CI/CD distribution pipeline.

## Feature Preservation & Scraper Genericity Protocol
- **No Domain Hardcoding in Resolvers**: Scrapers and embed extractors must remain domain-agnostic. Never hardcode single-domain filters (e.g. `if 'domain' in decoded_url`) in hash decoders or server list parsers; always accept valid HTTP/HTTPS URLs and dynamically derive API origins (`f"{parsed.scheme}://{parsed.netloc}"`).
- **Multi-Server Fallback Order**: When multiple stream servers or mirrors are returned by a provider, collect them into prioritized candidate lists and attempt resolution sequentially. Never discard alternate hosts.
- **Upstream Feature Parity Guard**: Prior to refactoring any scraper, browser, or resolver, verify historical commits and upstream (Goldenfreddy0703/Otaku) to guarantee that generic decoding, multi-part handling, or extraction logic is not degraded.
