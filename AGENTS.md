# Otaku-RPDev Development & Engineering Rules

Authoritative engineering invariants and operational mandates for `Otaku-RPDev` (`plugin.video.otaku.rpdev`, `service.otaku.rpdev`, `context.otaku.rpdev`, and `service.subtitles.otaku.rpdev`). See [docs/README.md](docs/README.md) for the full docs index ([docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/DATA_MODELS_AND_STATE.md](docs/DATA_MODELS_AND_STATE.md), [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md), [docs/PLANS.md](docs/PLANS.md), [docs/TESTING.md](docs/TESTING.md), [docs/AUTOMATION.md](docs/AUTOMATION.md), [docs/CONCERNS.md](docs/CONCERNS.md)), and `.agents/skills/` for operational runbooks.

---

## 1. Repository Architecture & Module Boundaries
- **`plugin.video.otaku.rpdev/`**: Primary video add-on for Kodi 20 (Nexus), 21 (Omega), and 22 (Piers); `default.py` (async changelog via `RunPlugin`), thin backwards-compat `service.py` shim, `resources/lib/` (`ui/`, `Main.py`, `routes/`, `pages/`, `debrid/`, `endpoints/`, `WatchlistFlavor/`, `subtitles/`, `windows/`), 41 1080i skin XMLs, and 455 interactive settings across 10 categories.
- **`service.otaku.rpdev/`**: Background daemon (`xbmc.service`) + shared module (`xbmc.python.module`, `resources/lib/otaku_service/`) owning `migration.py` (100% self-contained v1/v2 XML migration), `daemon.py` (15m OAuth/retry drain, standby-aware polling, hot-update transition, `<2s` passive WAL checkpoint + `1s` worker join), `sync.py` (`.xz`/`.gz` `mappings.db` + `anime_metadata.db` sync + `.bak` rollback), and 61 background/cache/maintenance/solver settings across 3 categories.
- **`context.otaku.rpdev/`**: Standalone widget-aware context add-on (`_resolve_widget_mal_id()`, `seriesprofile`, `manualsubtitles`, `inspectmappings`, RO `info.db`, 494 deduplicated studio PNGs/style, 0 collisions).
- **`service.subtitles.otaku.rpdev/`**: Native `xbmc.subtitle.module` service bridging VideoOSD to the 6-provider engine (`OpenSubtitles`, `SubDL`, `SubSource`, `Podnadpisi`, `BSPlayer`, `Addic7ed`).
- **Acyclic Quad-Addon DAG (`C-27`) & Cross-Addon Pinning (`C-28`)**: Companion add-ons must NEVER `<import addon="plugin.video.otaku.rpdev"/>` (`context` & `subtitles` import only `xbmc.python`; `service.otaku.rpdev` imports only `xbmc.python` + third-party `script.module.*`). Keep `control.ADDON_ID = 'plugin.video.otaku.rpdev'` and `control.SERVICE_ADDON_ID = 'service.otaku.rpdev'` statically pinned, with `otaku.service_settings_epoch` cache sync on both getter and setter paths.
- **`tests/`**: Hermetic offline suite (`conftest.py` socket guard + SWIG mocks, `tests/kodi_profile.py`, `unit/`, `integration/`, `lint/`, `e2e_v630/`, `fixtures/`).

---

## 2. Workspace Governance & Network Boundaries
- **Execution & Git Baseline**: Run `Otaku-RPDev` commands from `/mnt/sharedroot/projects/RPDevs-Builds/Otaku-RPDev`. All automated git commits must pass `--no-gpg-sign` and tags `--no-sign`. Never escape above `/mnt/sharedroot/projects/RPDevs-Builds/Otaku-RPDev/` or write `/tmp/` detours. Never push commits/tags without explicit user approval.
- **In-Session Execution Fallback**: If subagent quota is exhausted (`429 RESOURCE_EXHAUSTED`) or the user requests in-session work, do not spawn `/teamwork` sub-sessions; execute all synthesis and verification steps directly in the active session.
- **Two-Stage Concern Lifecycle & Read-Only Production Telemetry**:
  - **100% Read-Only Production (`10.13.0.16`)**: Audit ONN `10.13.0.16` strictly via `python3 scripts/audit_onn_logs.py --concerns docs/CONCERNS.md` (HTTP GET `/tail?offset=<N>`). Zero writes, sideloads, or restarts.
  - **Lifecycle Graduation**: Fixes verified in local headless Kodi 21/22 (`scripts/test_kodi_installs.py`) graduate to **`FIXED_VERIFIED_LOCAL_E2E`**, and advance to **`PRODUCTION_CONFIRMED`** only after passive read-only `audit_onn_logs.py` observation post-CDN update. Respect `C-11` (`Unable to create subtitle parser`) vs `C-14` (Premiumize CDN `peer(56)`) taxonomy.

---

## 3. Deployment & Addon Release Pipeline Mandate
- **Target Device Non-Interference**: Never push files via ADB, trigger `UpdateAddonRepos`, mutate device `Addons33.db`, or send remote control/update commands to live user hardware (`10.13.0.16`). The release boundary strictly ends at GitHub Releases + CDN sync (`https://kodi.repo.iamrp.dev`).
- **Single-Command Release Orchestrator (`scripts/release_addon.py`)**:
  - Publish releases via `python3 scripts/release_addon.py --bump patch --title "<Banner <=32 chars>" -m "<Bullets>"` (or `--dry-run` / `--verify-tag vX.Y.Z`).
  - Keep `news.txt` horizontal `=`/`-` dividers `<= 32` characters so lines fit inside `textviewer.xml` (`<width>600</width>`) without wrapping.
  - If Step 2 pre-flight fails after Step 1 bumped metadata, run `git checkout -- plugin.video.otaku.rpdev/{addon.xml,news.txt,changelog.txt}` before retrying `--bump patch`.

---

## 4. Dual Kodi 20/21 (Nexus/Omega) & Kodi 22 (Piers) Compatibility
- **`InfoTagVideo` Modernization**: Always use `vinfo = li.getVideoInfoTag()` typed setters; never call deprecated `ListItem.setInfo()`. Guard Kodi 22+ exclusive setters (`setOriginalLanguage`, `setTagLine`, `setSeasonPlot`, `setAvailableFanart`, `setHdrType`) with `hasattr(vinfo, ...)` and mirror values via `li.setProperty(...)` for Kodi 20/21.
- **SWIG Non-Null & `ListItem.setArt` Contracts**: Explicitly coerce every C++ argument (`str(val or '')`, `int(val or 0)` — never `str(None)`). Filter all artwork dicts through `control.clean_art_dict(art)` to unwrap single-element lists/tuples and drop non-strings before `setArt()`.
- **Dual BCP 47 & ISO 639-2 Language Matching**: Route all audio/subtitle selectors through `is_language_match()` so 2-letter BCP 47 (`ja`, `en`) and 3-letter ISO 639-2 (`jpn`, `eng`) match identically; keep `latin-1` last in encoding fallbacks.
- **Kodi 22 External Subtitle Parser & VFS Cache Contract (`C-11`/`C-29`/`C-30`/`C-32`/`C-33`)**:
  - `embed_extractor.get_sub()` must strip BOM/whitespace to byte 0, validate cues matching Kodi's `CDVDFactorySubtitle::CreateParser()`, auto-promote hour-less VTT cues, reject HTML/JSON/cue-less stubs with origin `source_url`/`?url=` fallback even on HTTP 200 error bodies, and pass `vfs_path='special://temp/...'` into `control.atomic_write_text()` (`xbmcvfs.rename()` -> `g_directoryCache.AddFile()`).
  - Never call `xbmcvfs.listdir()` inside `embed_extractor.del_subs()` (use `os.listdir()`); clear stale `otaku.embed_sub_signs_only` / `otaku.embed_sub_has_full_dialog` flags before each episode's `get_sub()` pass so `<45`-cue Signs-only `.vtt` triggers full-dialogue auto-download (and skip attaching sparse Signs-only sidecars when `subtitles.keywords == 1` Full Dialogue is requested); use unique per-play `sub_tag` nonces and skip `del_subs()` on queued Zero-Wait transitions.
  - `auto_download_subtitles()` must skip `Mismatch`/`Title Mismatch` results (`MAX_AUTO_ATTEMPTS = 6`) and abort immediately if `not xbmc.Player().isPlaying()`; 25fps PAL rescaling requires `max_sub_ts > video_dur * 1.03`.
- **`setDateTime()` & `setEpisode()` Sort Contracts**: Populate `li.setDateTime("YYYY-MM-DDTHH:MM:SS")` (guarded with `hasattr`) in `set_videotags()` for `SORT_METHOD_DATE`, and populate `info['episodes']` across all TV browse/watchlist views for `SORT_METHOD_EPISODE`.
- **Python 3.12–3.14 & Invoker Hygiene**: Zero PEP 594 removed stdlib imports (`cgi`, `pipes`, `imghdr`, `sunau`, etc.). Use `ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)` + `ssl.TLSVersion` bounds (never deprecated `ssl.PROTOCOL_TLSv1_*` / `PROTOCOL_TLS`). Use cooperative `super().__init__()`, `None` sentinels instead of mutable defaults, `control.log()` instead of `print()`, and keep `schedule_next_page_prefetch` a no-op (no detached `CPythonInvoker` threads).

---

## 5. Kodi C++ Settings Schema & Defensive Accessors
- Route all setting reads/writes through `control.py` (`getBool`, `getInt`, `getStr`, `getNumber`, `*List`). Guard module-load `xbmcaddon.Addon()` with static fallbacks for ZIP-upgrade transients.
- Coerce `settingid` and `value` with typed defaults *before* calling C++ `settings.set*` and *before* updating `_settings_cache` / `homeWindow`. Wrap all getters/setters in `try...except Exception:`.
- Derive dynamic setting prefixes (e.g., `EMBED_SKIP_PREFIXES`) from a single registry (`_EMBED_MODULES` in `pages/__init__.py`).
- Declare UI strings strictly within Kodi's `#30000`–`#30999` add-on range (`#31000+` is reserved for skins). Use `<level>4</level>` for internal settings, keep zero duplicate IDs, include new settings & `series_overrides` in `settings_manager.py`, and run `test_settings_schema_and_code_references.py` + `test_clean_settings.py`.

---

## 6. Memory Management & Low-RAM (1GB Android TV) Safeguards
- **64 KB UTF-8 Window Property Ceiling**: Reject payloads exceeding `65,536` UTF-8 bytes (`len(val_str.encode('utf-8', errors='replace')) > 65536`) in `_WindowProxy.setProperty` / `control.setGlobalProp`; store large payloads in SQLite WAL `cache.db`.
- **Modal `WindowXML` Disposal & Idle Watchdog (`C-06`/`C-35`)**: Wrap all `doModal()`/`.run()` calls in `try...finally: dlg.close(); del dlg`, return `control.exit_code()` from non-directory routes, and guard unattended auth modals (`WatchlistFlavorAuth`) with abort-responsive inactivity timers.
- **Non-Folder Flag for Modal Menu Items**: Menu items opening modal dialogs (e.g., `airing_calendar`) must set `isFolder=False, isPlayable=False`.

---

## 7. SQLite Concurrency, Static Dictionaries & Self-Healing
- **In-Memory Locks Only**: Never create `*.db.lock` files. Use `threading.RLock()` and `execute_write_with_retry()` with jittered backoff (`10–150ms`).
- **Read-Only URI & Low-RAM `mmap_size=0` (`C-37`)**: `info.db` / `mappings.db` must default to `is_readonly=True` (`file:{abs_path}?mode=ro`, `uri=True`, `timeout=float(self.timeout)`), skip write PRAGMAs/WAL checkpoints, and key pools by `(abs_path, is_readonly)`. Enforce `PRAGMA mmap_size = 0` on **both** RW and RO pools whenever `control.is_low_memory()` is true.
- **Non-Destructive Column-Level Migrations**: Create tables idempotently via `SyncDatabase._create_all_tables()` and invoke `_ensure_column_migrations()` (`PRAGMA table_info` + `ALTER TABLE`) unconditionally on startup (independent of `SCHEMA_VERSION` equality so mid-sprint dev DBs never skip new columns such as `series_overrides.episode_offset`). Preserve `_quarantine_and_recover_db()` (using `SyncDatabase()`) and passive `PRAGMA wal_checkpoint(PASSIVE)` in `service.py`.
- **Resilient `mappings.db` Sync**: `service.update_mappings_db()` supports `.xz`/`.gz`, validates SHA-256 and `PRAGMA quick_check(1)` via `database.verify_sqlite_integrity()` before swap, keeps `mappings.db.bak`, and auto-restores on failure.

---

## 8. Kodi GUI WindowXML & Single Event Dispatch Protocol
- **Single Event Dispatch & `BaseWindow.close()`**: Never handle Action IDs `7`, `100`, or double-click inside `onAction()` when `onClick(control_id)` exists; guard irreversible modal actions with an idempotency flag. Subclasses calling `BaseWindow.close()` must never set `self._win_closed = True` beforehand (causes `BaseWindow.close()` to return early without calling `super().close()`), and close tests must assert `xbmcgui.WindowXMLDialog.close` is invoked.
- **In-Place `ControlList` Updates**: Never call `list_control.reset()` to toggle/refresh rows (evicts C++ focus to index 0). Mutate `getListItem(idx)` in place, trim excess tail items via `removeItem(size - 1)` (guarded with `hasattr`), and restore `selectItem(pos)`. Retrieve control state *before* calling `self.close()`.
- **Skin XML & `<defaultcontrol>` Integrity**: Keep all 41 1080i XMLs valid (`ElementTree`), handle Android TV Back `[9, 10, 92, 216]`, and never set `<defaultcontrol>` to invisible or dynamically populated lists (call `self.setFocusId(X)` in Python after populating items).
- **Sort Methods & Pinning**: Register `"Default"` with `SORT_METHOD_UNSORTED` (never `SORT_METHOD_NONE`). Keep titles in `addSortMethod()` `labelMask` (`"%L"` / `"%H. %T"`) and metadata tokens (`%Y`, `%R`, `%E`, `%P`) strictly in `label2Mask`. Pin `Next Page` (`SpecialSort="bottom"`) and filter rows (`SpecialSort="top"`).
- **Headless Kodi 22 Captures**: In `Window 10140` (Settings), send `Input.Left` before iterating sidebar categories. Capture Xvfb screenshots with `import -window root -quality 92 <path>`.

---

## 9. Responsive Abort Loops & Teardown Safety
- Never execute `xbmc.sleep()` / `time.sleep()` >500ms in player, countdown, scraper, or service loops; use `control.monitor.waitForAbort(seconds)` or `<=200ms` ticks.
- **Always inspect `waitForAbort()`'s return value**: abort retries (`if control.monitor.waitForAbort(s): return None` / `break`) and skip delayed side effects (`sync_watchlist`, post-`RunPlugin` dialogs) when `True`.
- Bound scraper lifecycles (`self.canceled = True` in `finally`, check `abort_requested()`, cap timeouts `<=30s`).

---

## 10. Feature Preservation, Scraper Genericity & Playback Pipeline
*(Detailed scraper/embed flow: [docs/ARCHITECTURE.md §2–3](docs/ARCHITECTURE.md).)*
- **Zero-`soupsieve` BS4**: Never use `.select()` or `.select_one()` (AST lint enforced); use `.find()` / `.find_all()`.
- **Domain-Agnostic Scrapers & Parallel Single-Batch**: Never hardcode domains; derive origins via `urlparse`, `.rstrip('/')` bases, normalize smart quotes before slugging, and probe redirects with `Range: bytes=0-0` + `limit=1`. Torrent scrapers (`nyaa.py`, `animetosho.py`) must merge `show_pack` into `parallel_process`, deduplicate hashes before one batched `Debrid().torrentCacheCheck()`, and use thread-safe direct ↔ `translate.goog` failover (guarding `isinstance(status, int) and status >= 400`).
- **Scoring & Sequel Alias Parity**: Filter via `isolate_show_title()` / `score_title_candidate()` (exact `>=140`, alias `140`, approved `115–125`, derivatives `<=40`), invoke `source_utils.expand_sequel_season_aliases()` in **both** `filter_sources()` and `sortSources()`, and enforce 4-tier relevance gating.
- **Embeds, Chapters, Zero-Wait & `episode_offset` (`C-34`/`NF-06`/`O-8`/`O-9`)**: Keep multi-server fallback, category HTML fallbacks, WCO `inc/embed/index.php` + `/ad-verify`, synced `BrowserBase` subclasses, `tmdb_mapping_match()` priority, and defunct 0ms `[]` stubs. `Source Select` and `Rescrape` share a `30s` scrape timeout with early-termination disabled (`Rescrape` also clears `season_pack` and `domains.clear_mirror_failures()`); `HiAnime._scrape_mirror()` caches `(mirror, mal_id) -> anime_id` for 24h while keeping `_resolve_anime_id()` uncached for hermetic `database.get` tests. Query Kodi 22 `Player.GetChapters` first, prune dead lead candidates in `resolve_silent()`, route Zero-Wait via `WatchlistPlayer`, clear resume bookmarks at `>=90%`, preserve `|Authorization=...`, isolate `episode_offset` strictly to `MetaBrowser.get_sources()` scraper args, refresh Home widgets on stop/end via `_refresh_widgets_on_stop()` (`clearSettingsCache()` + `Container.Refresh`), tag episodes with `[CANON]`/`[MIXED]`/`[FILLER]`/`[RECAP]` (`Skip Filler & Recap` replays Canon+Mixed; `Skip All Including Mixed` plays only Canon), and escape spaces (`%20`) in `fanart.py` URLs.
- **Unified Adaptive Circuit Breaker (`NF-04`)**: Use `domains.adaptive_circuit_breaker` (`300s->900s->3600s` + half-open probes) across torrent, embed, subtitle, metadata, and debrid providers.

---

## 11. HTTP Transport, Debrid Resilience, Watchlists & OAuth
*(Full HTTP/WAF/Watchlist details: [docs/ARCHITECTURE.md §4](docs/ARCHITECTURE.md).)*
- Cast timeouts to `float(timeout)`; join query params via `domains.join_url()` (`'&' if '?' in url else '?'`); test TCP 443 before 53 in `is_internet_available()`; use `control.safe_json()` / `loads_json()` / `r.json(default={})` (never bare `json.loads()`).
- Use FlareSolverr `'returnOnlyCookies': False`, fail fast (`<500ms`) on hard Cloudflare IP blocks + 600s Turnstile cooldowns, probe direct CDNs first, retry HTTP 429/503 (`1–3s` jittered `Retry-After` on `waitForAbort()`), and drain persistent retries via `scrobble_retry_queue` in `service.py` (`NF-01`).
- Check OAuth expiry with a 300s buffer; batch AniList `idMal_in` in 50-item chunks; paginate `MediaListCollection`; recognize `WINDOW_VIDEOS` (`10025`); refresh watchlist cache only on Page 1; isolate Page 2+ sparse fields; require dry-run counts + `yesno_dialog` confirmation in `watchlist_drift_auditor` (`NF-08`).

---

## 12. Hermetic Testing, CI & Unified Verification Gate
- Tests must import `tests/conftest.py`, stay offline, validate Kodi 21/22 (`tests/kodi_profile.py`), assert consumer outcomes across all 516 settings (`test_all_settings_outcomes.py`), verify UI/routes (`KodiProfile('22', strict_skin_controls=True)`), and enforce a **2:1 negative/edge-to-happy ratio** on new `NF-*` code.
- **Linters (`tests/lint/`)**: `test_suite_quality.py`, `test_ast_integrity.py` (AST safety, `C-36` setting templates, acyclic 4-addon DAG, studio/asset bounds), and `test_docs_and_customizations.py` (`AGENTS.md` `< 19,500` soft / `< 22,000` hard cap, `--fail-below 65` parity, `CONCERN_PATTERNS`, `PLANS.md`, skill frontmatter, companion changelogs, `news.txt` `<= 32` chars).
- **Pre-Push Gates (`qa_fast.py`, `verify_all.py`, `e2e_v630_suite.py`)**: Fast: `python3 scripts/qa_fast.py`. Full: `python3 scripts/verify_all.py --fail-below 65` (single-pass PEP 669 `pytest`/`unittest` + 100% module coverage + strict `resources.*` warnings-as-errors; CI uses `--skip-coverage` on Python 3.11) + `python3 scripts/e2e_v630_suite.py`. See [docs/TESTING.md](docs/TESTING.md) and [docs/AUTOMATION.md](docs/AUTOMATION.md).

---

## 13. Automated Tag-Based Release & Dual-DB Sync
- **Single-Dispatch Release**: Commit cleanly (`--no-gpg-sign`) and run `python3 scripts/release_addon.py --bump patch --title "<Banner <=32 chars>" -m "<Bullets>"`. It bumps metadata, verifies 4-addon `<import>` parity, runs `verify_all.py --fail-below 65` + `e2e_v630_suite.py` concurrently with auto-rollback, commits/tags (`--no-sign`), pushes, watches CI, and verifies GitHub Release (4 ZIPs) + live CDN `https://kodi.repo.iamrp.dev/`.
- **Dual DB Sync & Schema Probing**: `otaku_service.sync._maybe_sync_daily_mappings()` syncs `mappings.db` + `anime_metadata.db` (`.etag` + SHA-256 vs `manifest.json`) with `update.time.30` guard; UI enriches via `database.enrich_rows_from_metadata_db()` / `metadata_fts`. Always probe post-v2.7 columns via `PRAGMA table_info`/`sqlite_master`. Keep this file `< 22,000` bytes.
