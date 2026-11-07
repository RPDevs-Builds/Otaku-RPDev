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

## Kodi 22 (Piers) Subsystem & C++ Setting Invariants
- **Defensive Setting Accessors**: Always route setting reads and writes through `control.py` helpers. Never assume a setting key exists; accessors must catch C++ exceptions and supply safe fallback values.
- **AST Schema Auditing on Setting Removals**: Prior to removing or renaming any setting from `resources/settings.xml`, run full AST schema verification (`test_settings_schema_and_code_references.py`) to confirm that zero residual runtime references remain across code, skins, and services.
- **Responsive Abort Loops**: Never execute synchronous `xbmc.sleep()` calls exceeding 500ms in player, countdown, or background service loops. Use non-blocking `control.monitor.waitForAbort(seconds)` to guarantee immediate responsiveness during player abort or Kodi shutdown.

## SQLite Concurrency & Static Dictionary Access Protocol
- **Read-Only URI Enforcement**: All auxiliary readers querying static dictionaries (`info.db`, `mappings.db`) must enforce URI read-only mode (`file:...db?mode=ro`).
- **Connection Key Separation**: SQLite connection caches must partition connection pools by `(db_path, mode)` so read-only connection handles are never mixed with or starved by write transactions.

## Kodi GUI WindowXML & Event Handling Protocol
- **In-Place ListItem Mutation**: Never call `self.list_control.reset()` to toggle item states in custom WindowXML dialogs. Mutate `ListItem` properties in place (`getListItem(idx).setProperty(...)`) to prevent Kodi C++ focus eviction.
- **Single Event Dispatch**: Do not forward action ID 7 (Enter/Select) from `onAction()` to `onClick()`; Kodi automatically dispatches `onClick(control_id)`. Double routing causes actions to fire twice.

## HTTP Transport & Rate-Limiting Invariants
- **Float Timeout Precision**: HTTP client methods must cast timeouts to `float(timeout)` rather than `int(timeout)` to prevent sub-second timeouts (`0.5`s) from truncating to 0.
- **Defensive JSON Decoding**: Never assume API responses are valid JSON. Always route parsing through `safe_json()` or `r.json(default={})` to gracefully handle HTML error/challenge responses from Cloudflare or streaming hosts.
- **Debrid & API 429 Backoff**: All external debrid and metadata API callers must catch HTTP 429, respect `Retry-After` headers (capped to 3 seconds with jitter), and retry once before failing.

## Memory Management & Low-RAM Streaming Device Safeguards
- **64KB Window Property Ceiling**: Never store payloads exceeding 64KB in Kodi C++ window properties (`_window.setProperty`). Large datasets must be stored in SQLite WAL `cache.db` to prevent heap fragmentation on 1GB RAM streaming devices.
- **Proactive OAuth Refresh**: Always evaluate OAuth token expiry with a 300-second buffer (`time.time() > expiry - 300`) prior to issuing API calls, and maintain token freshness via the background 15-minute service loop.
