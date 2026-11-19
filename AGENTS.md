# Otaku-RPDev Development & Engineering Rules

Authoritative engineering invariants, architectural contracts, and operational mandates for `Otaku-RPDev` (`plugin.video.otaku.rpdev` & `context.otaku.rpdev`), synthesized from project-wide audits, upstream parity reviews (`Goldenfreddy0703/Otaku`), and 420+ historical implementation plans.

---

## 1. Repository Architecture & Module Boundaries
- **`plugin.video.otaku.rpdev/`**: Primary video add-on targeting Kodi 20 (Nexus), Kodi 21 (Omega), and Kodi 22 (Piers).
  - **Entrypoints**: `default.py` (plugin router dispatch; decouples modal changelog display from root `GetDirectory` to prevent 45s timeouts) and `service.py` (startup maintenance, `clean_settings`, 15-minute proactive OAuth refresh, and passive SQLite WAL checkpoints).
  - **Core Subsystems (`resources/lib/ui/`)**: `control.py` (Kodi C++ settings/window/ListItem abstraction), `database.py` (thread-safe SQLite pools, migrations, corruption auto-recovery), `client.py` (HTTP/TLS/FlareSolverr transport), `player.py` (`WatchlistPlayer` playback, scrobbling, chapters, subtitles), `source_utils.py`, and `embed_extractor.py` / `megaplay_extractor.py`.
  - **Routing & Menus (`resources/lib/Main.py`, `resources/lib/routes/`)**: Modular route handlers (`playback.py`, `tools.py`, `search.py`, `watchlist.py`, etc.) and 24 customizable menus across 8 content categories.
  - **Providers & Resolvers**: `resources/lib/pages/` (torrent, Usenet, and embed scrapers orchestrated by `pages/__init__.py`) and `resources/lib/debrid/` (`real_debrid.py`, `torbox.py`, `all_debrid.py`, `debrid_link.py`, `premiumize.py`, `easydebrid.py`, `easynews.py`).
  - **Metadata & Watchlists**: `resources/lib/endpoints/` (`anilist.py`, `mal.py`, `tmdb.py`, `tvdb.py`, `anizip.py`, `anime_filler.py`, `aniskip.py`) and `resources/lib/WatchlistFlavor/` (`AniList.py`, `MyAnimeList.py`, `Kitsu.py`, `Simkl.py`).
  - **GUI (`resources/lib/windows/`, `resources/skins/Default/1080i/`)**: Custom `WindowXML` / `WindowXMLDialog` controllers and 38 1080i XML skin templates.
- **`context.otaku.rpdev/`**: Standalone Kodi context menu extension. Uses defensive `_extract_subpath()` regex parsing for third-party skin widgets (Aura, Arctic Horizon, Cosmic) and accesses `info.db` strictly in read-only / `DELETE` journal mode to avoid cross-addon locks. Contains consolidated anime studio logo packs under `resources/images/studios/{coloured,white}/` (580 logos each).
- **`tests/`**: Hermetic offline test suite (`tests/conftest.py` C++ SWIG mocks + socket network guard, `tests/kodi_profile.py` dual Kodi 21/22 runtime simulation harness, `tests/unit/`, `tests/integration/`, `tests/lint/`, `tests/fixtures/`).

---

## 2. Workspace Governance, Scripts, Archives & Network Boundaries
- **Infrastructure Source of Truth**: `/mnt/sharedroot/projects/infra-audit-engine/docs/CURRENT_ENV.yml` (refresh via `.venv/bin/python src/orchestrator.py` in `/mnt/sharedroot/projects/infra-audit-engine`).
- **Execution Baseline**: Default workspace root is `/home/llmuser/projects` (`/mnt/sharedroot/projects`); run `Otaku-RPDev` test and build commands from `/mnt/sharedroot/projects/RPDevs-Builds/Otaku-RPDev`. All git commits must explicitly pass `--no-gpg-sign` (`git commit --no-gpg-sign -m "..."`) to prevent non-interactive agent terminal hangs.
- **Strict Project Directory Confinement**: All commands (`grep`, `find`, `sed`, `git`, `python`, `pytest`, `ruff`, etc.) and file operations must operate strictly within the assigned project root (`/mnt/sharedroot/projects/RPDevs-Builds/Otaku-RPDev/` or `/mnt/sharedroot/projects/RPDevs-Builds/Kodi-Debugging/` for debug tasks). Never escape above the project boundary into parent directory `/mnt/sharedroot/projects/RPDevs-Builds/` or workspace root `/mnt/sharedroot/projects/` where other projects reside.
- **Direct Output Destination Mandate**: When an output directory is explicitly specified (e.g. `/mnt/sharedroot/projects/RPDevs-Builds/Kodi-Debugging/screenshots/`), all generated outputs, including intermediate test captures and diagnostics, must be written directly to that destination. Never take detours through `/tmp/` or arbitrary locations when a project destination has been designated.
- **Comprehensive Scope Non-Truncation Mandate**: When a request specifies a "comprehensive" review, audit, or test across all functions, windows, or settings, NEVER unilaterally prune, shortcut, or truncate the scope (e.g. capturing only 12 screenshots when 40+ are required, or skipping settings submenus). Enumerate the exhaustive list of targets upfront in the implementation plan checklist and execute against every single item.
- **Reusable Helper Scripts**: Store reusable maintenance/audit/release scripts under `/home/llmuser/projects/.scripts/python/` or `/home/llmuser/projects/.scripts/shell/` and register every script in `/home/llmuser/projects/.scripts/SCRIPTS.md`. Purge one-off migration scripts after use.
- **Historical Plan & Walkthrough Archival**: Archive every `implementation_plan.md` and `walkthrough.md` to `/home/llmuser/projects/.plans/YYYY-MM-DD/Otaku-RPDev/<type>_YYYY-MM-DD_HHMMSS.md` and catalog it in `/home/llmuser/projects/.plans/INDEX.md`.
- **Target Device Direct ADB Diagnostics Protocol**: When inspecting device logs, system properties, or diagnostic states on target devices (such as the ONN Android TV at `10.13.0.16`), always connect and query directly via standard ADB CLI commands (`adb -s 10.13.0.16:5555 shell ...`). Never attempt to drive automated agent debugging workflows through interactive end-user scripts (e.g. `kodi_debug.py`), which are designed strictly for human terminal usage.
- **Network & DNS Filter Respect**: Never attempt to bypass NextDNS, firewall rules, or sandbox boundaries. Handle DNS-blocked streaming domains (`127.0.0.1` / connection refused) gracefully via multi-server failover and report blocked domains to the user.

---

## 3. Deployment & Addon Release Pipeline Mandate
- **Target Device Non-Interference & No Direct Updates**:
  - Live target devices (such as ONN Android TV `10.13.0.16`) are user-managed media centers in active use.
  - Never push code, assets, or addon files directly onto target devices via ADB.
  - Never trigger repository updates (`UpdateAddonRepos`), manipulate device SQLite databases (`Addons33.db`), invoke remote management scripts (`kodi_remote_cli.py -U`), or issue JSON-RPC/input commands to live target hardware.
  - The agent's release pipeline boundary strictly terminates when the release package is published to GitHub Releases and synchronized to the Kodi repository CDN (`https://kodi.repo.iamrp.dev`). The user updates their own devices when they choose.
- **Single-Command Tag-Based Release Orchestrator (`scripts/release_addon.py`)**:
  All releases are driven through `python3 scripts/release_addon.py` and `.github/workflows/release.yml`. Never run ad-hoc manual `gh` or `curl` sequences outside the orchestrator (`gh repo set-default RPDevs-Builds/Otaku-RPDev` is pre-configured, and the orchestrator passes `-R RPDevs-Builds/Otaku-RPDev` explicitly):
  1. **Prepare or Auto-Bump Metadata**:
     - Either update `plugin.video.otaku.rpdev/addon.xml` (`version="X.Y.Z"`), `plugin.video.otaku.rpdev/news.txt` (keep horizontal `=` / `-` dividers **<= 32 characters** so lines fit cleanly inside `resources/skins/Default/1080i/textviewer.xml` `id="2001"`, `<width>600</width>` without multi-row wrapping), and `plugin.video.otaku.rpdev/changelog.txt` (`Changelog vX.Y.Z (YYYY-MM-DD):`) first, then run:
       ```bash
       python3 scripts/release_addon.py
       ```
     - Or let `scripts/release_addon.py` bump and format all 3 metadata files automatically:
       ```bash
       python3 scripts/release_addon.py --bump patch --title "Short Banner Title" -m "Bullet 1\nBullet 2"
       ```
     - For pre-flight validation without committing, tagging, or pushing:
       ```bash
       python3 scripts/release_addon.py --dry-run
       ```
  2. **Automated Pre-Flight, Tagging & CI/CD Verification** (executed automatically by `scripts/release_addon.py`):
     - Validates `addon.xml`, `news.txt` (`<= 32` char dividers), and `changelog.txt` synchronization for `vX.Y.Z`.
     - Executes the Pre-Flight Verification Gate (`ruff check --select E9,F63,F7,F82`, `python3 -m compileall -q`, `python3 -W default -m unittest discover -s tests -v`, and `python3 scripts/audit_function_coverage.py --fail-below 60`).
     - Commits (`git commit --no-gpg-sign`), creates an unsigned annotated tag (`git tag -a vX.Y.Z --no-sign`), and pushes `main` and `vX.Y.Z` to `origin`.
     - Watches `.github/workflows/release.yml` (`gh run watch -R RPDevs-Builds/Otaku-RPDev`), verifies GitHub Release assets (`plugin.video.otaku.rpdev-X.Y.Z.zip`, `SHA256SUMS.txt`, `MD5SUMS.txt`), and polls the live CDN (`https://kodi.repo.iamrp.dev/addons.xml`, `https://kodi.repo.iamrp.dev/addons.xml.md5`, and `https://kodi.repo.iamrp.dev/plugin.video.otaku.rpdev/plugin.video.otaku.rpdev-X.Y.Z.zip`) until `HTTP 200` and MD5 match are confirmed.
     - Re-verify any published tag at any time via `python3 scripts/release_addon.py --verify-tag v6.1.3`.

---

## 4. Dual Kodi 20/21 (Nexus/Omega) & Kodi 22 (Piers) Compatibility
- **`InfoTagVideo` Modernization**: Always populate metadata via `vinfo = li.getVideoInfoTag()` with typed setters (`setTitle`, `setPlot`, `setYear`, `setGenres`, `setCast`, `setDuration`). Never call deprecated `ListItem.setInfo()`. For Kodi 22+ exclusive setters (`setOriginalLanguage`, `setTagLine`, `setSeasonPlot`), guard with `hasattr(vinfo, ...)` inside `try...except` and mirror values to `li.setProperty(...)` for Kodi 20/21 skin compatibility.
- **SWIG Non-Null Type Contracts & `ListItem.setArt` Strict String Mapping**: Kodi 22 SWIG directors reject `None` for `std::string` / numeric arguments with fatal `TypeError` exceptions. Explicitly coerce every argument passed to `xbmc.Actor`, `xbmcgui.ListItem(str(name or ''))`, `vinfo`, and `_AddonProxy.setSetting(str(id or ''), str(val if val is not None else ''))`. Never use `str(val)` on nullable values (which writes literal `'None'`). For `ListItem.setArt(art)`, Kodi C++ SWIG bindings strictly enforce `std::map<std::string, std::string>`. Passing dictionaries containing lists (such as `['https://...']` returned by metadata mergers like `get_meta.py:merge_artwork`), nested dicts, numbers, or `None` values raises fatal `TypeError: in method 'ListItem_setArt', argument 2 of type 'XBMCAddon::Properties const &'`. All artwork dictionaries passed to `setArt()` must be filtered through `control.clean_art_dict(art)` to unwrap single-element lists/tuples to strings and drop non-strings.
- **Dual BCP 47 & ISO 639-2 Language Matching**: Route all audio and subtitle track selectors through `is_language_match()` (`LANGUAGE_SYNONYMS`) so 2-letter BCP 47 / regional tags (`ja`, `en`, `en-US` in Kodi 22) and 3-letter ISO 639-2 codes (`jpn`, `eng` in Kodi 20/21) match identically. Position `latin-1` last in subtitle encoding fallbacks.
- **Kodi `ListItem.setDateTime()` & `VideoInfoTag.setEpisode()` Contracts**:
  - Kodi 20+ sorts `SORT_METHOD_DATE` using `ListItem.setDateTime("YYYY-MM-DDTHH:MM:SS")`, not `vinfo.setPremiered()` / `vinfo.setYear()`. Always populate `li.setDateTime(...)` (guarded via `hasattr(li, 'setDateTime')`) from `premiered`, `aired`, or `YYYY-01-01` fallback in `control.set_videotags()`.
  - Populate `info['episodes']` across all `tvshows` browse views (`AniListBrowser`, `MalBrowser`, `OtakuBrowser`) and `WatchlistFlavor` status views, and map `episode`, `episodes`, `total_episodes`, and `total_episodes_count` to `vinfo.setEpisode()` so `SORT_METHOD_EPISODE` sorts reliably.
- **Python 3.12–3.14 Clean Runtimes & Invoker Hygiene**:
  - Zero imports of PEP 594 removed stdlib modules (`cgi`, `pipes`, `imghdr`, `sunau`, `crypt`, `chunk`, `uu`, `telnetlib`, etc.).
  - Never use deprecated `ssl.PROTOCOL_TLS*` constants (`PROTOCOL_TLSv1`, `PROTOCOL_TLSv1_1`, `PROTOCOL_TLSv1_2`, `PROTOCOL_TLS`). Always construct contexts with `ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)` + `ssl.TLSVersion` bounds (`minimum_version` / `maximum_version`), load CA certificates via `load_verify_locations` / `load_default_certs` when `verify=True`, and set `check_hostname = False` before `verify_mode = ssl.CERT_NONE` when `verify=False`.
  - Always use Python 3 cooperative `super().__init__()` / `super().method()`, never `super(ClassName, self)`.
  - Never use mutable default arguments (`def fn(items=[], data={})`); use `None` sentinels initialized inside the function body so state never leaks across persistent `reuselanguageinvoker` executions.
  - Never use raw `print()`; route diagnostics through `control.log()` / `xbmc.log()`.
  - Keep `control.schedule_next_page_prefetch` as a safe no-op; never spawn detached background `CPythonInvoker` threads that cause 10–30s shutdown freezes on Kodi 22 / Android TV.

---

## 5. Kodi C++ Settings Schema & Defensive Accessors
- **Centralized Defensive Accessors**: Route all internal setting reads/writes through `control.py` (`getBool`, `getInt`, `getStr`, `getNumber`, `setBool`, `setInt`, `setStr`, `setNumber`, and `*List` variants). Protect module-load `xbmcaddon.Addon()` initialization with static fallback constants to survive transient `RuntimeError: Unknown addon id` during addon ZIP upgrades.
- **Coerce Before C++ & Cache Writes**: Inside every `control.py` setter, coerce `settingid` and `value` inside `try...except (ValueError, TypeError)` with typed defaults (`0`, `0.0`, `''`, `[]`) *before* calling `settings.set*` **and** *before* updating `_settings_cache` or `homeWindow.setProperty`. Wrap all scalar and `*List` getters/setters in `try...except Exception:` so undeclared or mismatched keys never crash worker threads.
- **Single Source of Truth for Dynamic Settings**: Derive dynamic setting prefixes (e.g., `EMBED_SKIP_PREFIXES` from `_EMBED_MODULES` in `pages/__init__.py`) from a single authoritative registry rather than duplicating provider tuples across `pages/__init__.py` and `player.py`.
- **Mandatory AST Schema, Deduplication & Credential Audits**: Prior to adding, uncommenting, renaming, or removing any setting in `resources/settings.xml` (use `<level>4</level>` for hidden internal settings), perform a whole-file search to ensure zero duplicate `<setting id="...">` entries across all levels. Run `test_settings_schema_and_code_references.py` and `test_clean_settings.py` to guarantee zero orphaned runtime references and confirm `clean_settings` never prunes user OAuth/Debrid credentials.

---

## 6. Memory Management & Low-RAM (1GB Android TV) Safeguards
- **64KB Window Property Ceiling (UTF-8 Byte-Measured)**: Never store payloads exceeding `65,536` UTF-8 bytes in Kodi C++ window properties (`_WindowProxy.setProperty`, `control.setGlobalProp`). Always measure encoded byte length via `len(val_str.encode('utf-8', errors='replace')) > 65536` (not `len(val_str)`, which misses 3–4 byte UTF-8 characters). Store large datasets (such as multi-entry user reviews `otaku_reviews_{mal_id}`) in SQLite WAL `cache.db`.
- **WindowXML C++ Object Disposal & Lifecycle**: Always wrap modal dialog invocations (`doModal()`) in `try ... finally:` blocks that call `dlg.close()`, execute `del dlg`, and clear instance references (`self.dialog = None`) to prevent C++ `WindowXML` memory leaks across marathon autoplay sessions.
- **Modal Dialog Menu Item Flagging**: Menu items that trigger modal `WindowXMLDialog` windows (such as `airing_calendar` launching `Anichart.doModal()`) must explicitly specify `isFolder=False, isPlayable=False` in `control.directoryItem()`. Declaring dialog-opening items as folders causes Kodi's navigation engine to stall or display empty directory errors upon dialog dismissal.

---

## 7. SQLite Concurrency, Static Dictionaries & Self-Healing
- **In-Memory Locks Only**: Never create filesystem `.lock` files (`*.db.lock`), which orphan on sudden power loss or Android task kills. Use `threading.RLock()` and `execute_write_with_retry()` with jittered backoff (`10ms–150ms`).
- **Automatic Read-Only URI Mode & Pool Isolation**: Static reference databases (`control.infoDB` `info.db` and `control.mappingDB` `mappings.db`) must default to `is_readonly=True` in `database.SQL`, connect via `file:{abs_path}?mode=ro` (`uri=True`, `timeout=float(self.timeout)`), **skip all write PRAGMAs** (`journal_mode=WAL`, `synchronous=NORMAL`) when `is_readonly` is `True`, and partition thread-local connection caches by `(abs_path, is_readonly)` tuples (evicting all tuple/string variants in `close_thread_connections`).
- **Non-Destructive Migrations & Auto-Recovery**: Never wipe user databases via `re_build_database(True)` during version upgrades; evolve schemas via `PRAGMA table_info` + `ALTER TABLE` in `_migrate_database()`. Preserve `_quarantine_and_recover_db()` self-healing on `DatabaseError` and passive `PRAGMA wal_checkpoint(PASSIVE)` in `service.py`. Avoid blocking `VACUUM` during normal scraping/playback flows.

---

## 8. Kodi GUI WindowXML & Single Event Dispatch Protocol
- **Single Event Dispatch (`onClick` Exclusivity)**: Never handle Action ID `7` (`xbmcgui.ACTION_SELECT_ITEM`), Action ID `100` (`xbmcgui.ACTION_MOUSE_LEFT_CLICK`), or `xbmcgui.ACTION_MOUSE_DOUBLE_CLICK` inside `onAction()` when `onClick(control_id)` is present. Kodi's C++ GUI engine natively dispatches `onClick(control_id)` on Enter/Select/Click; handling selection in `onAction()` fires actions twice (causing double stream seeks, double resolvers, and close race conditions). Guard irreversible modal actions with an idempotency flag (`self._activated` / `self.actioned`).
- **Non-Destructive In-Place `ControlList` Updates**: Never call `list_control.reset()` to toggle item states, reorder items (`menu_order.py`), or refresh task progress (`download_manager.py`), as `reset()` evicts C++ focus to index `0`. Update existing items via `getListItem(idx).setProperty(...)` / `setLabel(...)`, trim excess tail items via `removeItem(size - 1)` (guarded with `hasattr(ctrl, 'removeItem')` for mock compatibility), and restore `selectItem(pos)`.
- **Skin XML Integrity**: All 38 XML files in `resources/skins/Default/1080i/` must remain well-formed (`xml.etree.ElementTree` validated in `test_ast_integrity.py`) with valid `<defaultcontrol>` IDs and Android TV Back action `9` (`[9, 10, 92, 216]`) handled in `onAction()`.
- **WindowXML Control Lifecycle on Context Actions**: In custom WindowXML dialogs, never call `self.close()` before retrieving user selection or position data from C++ controls (e.g., `self.display_list.getSelectedPosition()`). Calling `self.close()` tears down C++ controls and nullifies Python references (`self.display_list = None`), raising fatal `AttributeError` exceptions.
- **Skin `<defaultcontrol>` Invariant for Dynamic & Invisible Controls**: Never designate invisible controls (`<visible>false</visible>`), empty placeholder lists, or dynamic lists that are populated in Python `onInit()` as `<defaultcontrol>` in WindowXML skin files. Kodi evaluates `<defaultcontrol>` during window initialization (`LOAD_ON_GUI_INIT`) before Python populates items, triggering C++ warnings (`Control X in window Y has been asked to focus, but it can't`). For dynamic lists, omit `<defaultcontrol>` and set focus programmatically in Python (`self.setFocusId(X)`) once list items are added.
- **Directory Sort Methods & Label Mask Preservation**:
  - Always register `"Default"` sorting with `xbmcplugin.SORT_METHOD_UNSORTED`, never `xbmcplugin.SORT_METHOD_NONE` (which Kodi renders as a duplicate `"Date"` entry).
  - Never pass metadata formatters (`%Y`, `%R`, `%E`, `%P`) into the 3rd argument (`labelMask`) of `xbmcplugin.addSortMethod()`, as that overwrites displayed item titles. Keep item titles in `labelMask` (`"%L"` for shows/movies/videos/seasons/fallback, `"%H. %T"` for episodes) and place secondary metadata strictly in `label2Mask`.
  - Pin pagination and filter control rows in `control.xbmc_add_dir()` (`SpecialSort="bottom"` for `Next Page` / `next.png` rows and `SpecialSort="top"` for `multipage_filter` / `multipage_clear_filter` rows) so Kodi sorting never scatters them into content in either Ascending or Descending order.
- **Kodi 22 Headless Settings Category Traversal (`Window 10140`)**: Kodi 22 settings dialogs initially grant focus to the first item of the center content panel. Automated category traversal scripts must first verify window `10140` is active, dispatch `Input.Left` to shift focus to the category sidebar, and only then dispatch sequential `Input.Down` actions to iterate through all 12 categories (`General` through `Maintenance`).
- **Direct Virtual Framebuffer Capture**: For headless Xvfb screenshot captures, use ImageMagick `import -window root -quality 92 <path>` directly to standard compressed 1920x1080 JPEG. Avoid raw XWD format dumps which produce uncompressed pixmaps prone to decoder failures.

---

## 9. Responsive Abort Loops & Teardown Safety
- **No Blocking Sleeps >500ms**: Never call `xbmc.sleep()` or `time.sleep()` for >500ms in playback, countdowns, scrapers, dialogs, or background services. Slice polling loops into `<=100–200ms` ticks checking `abortRequested()` or call `control.monitor.waitForAbort(seconds)`.
- **Mandatory Inspection of `waitForAbort()` Return Value**: Calling `waitForAbort(seconds)` without checking its boolean return is a bug:
  - In retry/backoff loops (debrid `_request_with_backoff`, Jikan 429 retries, WCO session retries): `if control.monitor.waitForAbort(wait_seconds): return None` (or `break`) so HTTP calls are never reissued during shutdown.
  - Before delayed side effects (e.g., `if not control.monitor.waitForAbort(3): service.sync_watchlist(True)` in `routes/playback.py` and `player.py`, or post-`RunPlugin` dialogs in `sort_select.py`): skip execution when `True` to prevent teardown socket errors.
- **Bounded Scraper Lifecycles**: Enforce `self.canceled = True` in `getSources()` `finally` blocks, check `control.abort_requested()` in scraper worker loops, bound debrid hash-check joins, and cap provider scraping timeouts to `<=30s`. On user cancellation in `source_utils.user_select()`, return standardized `[{dict_key: '', 'path': ''}]` and reset `best_match=False`.

---

## 10. Feature Preservation, Scraper Genericity & Playback Pipeline
- **Zero-`soupsieve` Beautiful Soup Invariant**: Kodi's `script.module.beautifulsoup4` does not bundle `soupsieve`. Calling `.select()` or `.select_one()` raises `NotImplementedError` inside Kodi runtimes. All HTML scrapers must exclusively use `find()` and `find_all()` with attributes or predicate functions. This is permanently enforced via the AST lint gate in `test_ast_integrity.py`.
- **Domain-Agnostic Scrapers & Extractors**: Never hardcode single-domain filters (e.g., `if 'megaplay.buzz' in url`) or static embed hosts (`https://embed.wcostream.com`). Derive origins dynamically via `urllib.parse.urlparse` using `scheme = parsed.scheme or 'https'` (`f"{scheme}://{parsed.netloc}"`), normalize base URLs with `.rstrip('/')` before path concatenation (preventing `//` 301 Cloudflare triggers), and match query parameters position-agnostically (`[?&]pid=([0-9]+)`).
- **WatchNixtoons2 2026 WCO Player Protocol**: Free stream extraction on WCO must select `inc/embed/index.php` embeds (explicitly skipping `vhs.wcostream.com` paywall iframes) and execute the full handshake: capture `PHPSESSID`, fetch `pre-init.js?v2`, issue `POST /ad-verify` (`HTTP 204` + `Origin: https://embed.wcostream.com`), wait `5.2s` via non-blocking `waitForAbort`, and query `inc/embed/video-js-old.php` with `Referer: original_embed_url`. Always follow video stream redirects with `Range: bytes=0-0` and `limit=1` to avoid memory bloat.
- **Artwork List Unwrapping & Spoiler Masking**: Metadata and indexing routines unwrapping artwork from dictionaries or caches must unwrap `list` or `tuple` types (e.g., via `_pick_art_str(val)`) to a single string before assigning to `ListItem` artwork properties (`thumb`, `poster`, `fanart`). Passing list literals into art properties corrupts thumbnail rendering and bypasses spoiler shield masks.
- **Alphanumeric-Normalized Studio Artwork Resolution**: Studio logo resolution must normalize studio names by stripping non-alphanumeric characters (`re.sub(r'[^a-z0-9]+', '', name.lower())`) against an in-memory cached directory index of the local studio icon pack (`context.otaku.rpdev/resources/images/studios/{coloured,white}/`). This guarantees resilient matching across metadata provider variations (casing, punctuation, and multi-studio `' / '` separators) with zero network overhead.
- **Streaming Video Range Headers in Redirect Probes**: When resolving redirects on video URLs in scraper workers (e.g., `_follow_redirect_url`), never execute unconstrained `urlopen()` or `client.get()`. Always supply `Range: bytes=0-0` and bound byte reads (`limit=1`) to avoid buffering stream payloads into RAM.
- **Single-IP AdGate Concurrency Guard**: Streaming hosts with timestamped AdGate sessions (e.g. `embed.wcostream.com`) enforce a single active verification session per client IP. Scrapers must process audio variants sequentially (SUB then DUB) rather than concurrently to prevent IP-level session invalidation (`HTTP 503 Servers Busy`).
- **Multi-Server Candidate Retention**: Collect all enabled stream servers/mirrors into prioritized candidate lists and attempt resolution sequentially (`hianime.py`, `gogoanime.py`, etc.). Never place an early `break` after the first server match.
- **Candidate Scoring Engine, Title Isolation & 4-Tier Relevance Gating**:
  - **Release Title Isolation (`source_utils.isolate_show_title`)**: All release title parsing must route through `isolate_show_title`, which strips release groups, resolution/codec tags, and file extensions while decoupling episode boundaries across hyphenated (`- 01`), space-separated (`Title 01`), dot-separated (`Title.E01`), and season-episode (`S01E01`) notations. Normalization for comparisons must use `clean_title_for_matching` to preserve distinct word boundaries.
  - **Unified 0–200 Scoring Engine (`source_utils.score_title_candidate`)**: Replace naive substring matching with calibrated heuristic scoring:
    - Exact canonical/main title matches score `>= 140` (`150`).
    - Validated alias matches score `140`.
    - Approved release descriptors (`(Dub)`, `(Sub)`, `(TV)`, `(Movie)`) score `115–125` (valid `>= 110`).
    - Derivative titles (e.g. "Re:Monster", "Monster Musume" for query "Monster") and sequel mismatches are penalized to `<= 40` (typically `0–10`).
    - Ultra-short titles ($\le 8$ characters or single-word, e.g. *Monster*, *Air*, *K*, *C*, *Another*) enforce strict word-boundary token equality; length inflation without alias matches is strictly penalized.
  - **Centralized Source Filtering (`source_utils.filter_sources`)**: Automatically drops sources scoring `<= 40`, eliminating derivative torrents and episode-title false positives before display or playback.
  - **4-Tier Autoplay Relevance Gating (`pages/__init__.py:sortSources`)**: Sort candidates into 4 relevance tiers (Tier 1: `>= 140`, Tier 2: `>= 110`, Tier 3: `>= 70`, Tier 4: fallback) *before* quality, debrid, and size sorting. This prevents higher-resolution derivative releases from usurping authentic episodes in SmartPlay autoplay.
  - **Scraper-Specific Candidate Ranking**: All active scrapers (`hianime.py`, `gogoanime.py`, `animepahe.py`, `anikoto.py`, `watchnixtoons2.py`, `animetosho.py`, `nyaa.py`) must integrate candidate scoring, enforce score cutoffs, and never fall back to unranked index `0` search results.
- **Modern Embed Scraper Architecture & Fallbacks**:
  - **Canonical Domain Selection & TLS Health**: Select active mirrors with complete, valid Cloudflare TLS certificate chains (e.g. `https://gogoanime.me/`). Avoid domains missing intermediate certificates (e.g. Let's Encrypt `YR1` omissions) or ccTLDs frequently sinkholed by NextDNS (e.g. `.bz`).
  - **Pre-Rendered Category Page Fallback**: Modern embed sites frequently deprecate AJAX episode loaders (`/load-list-episode`) while pre-rendering complete episode listings inside static category HTML (`/category/{slug}` inside `<div id="episode-items">`). Scrapers must implement category page parsing as an automatic fallback for movies, specials, OVAs, or when direct episode slug generation fails.
  - **Server Class Normalization**: Normalize obfuscated or generic player button CSS classes (e.g. class `anime` -> Vidstreaming/Goone) to standard internal resolver IDs (`vidcdn`, `streamwish`, `mp4upload`, `doodstream`, `filemoon`) and process all valid candidate servers sequentially without premature `break`s.
  - **Unicode Quote Normalization**: Normalize typographic/smart quotes (`’`, `‘`, `“`, `”`) to standard ASCII quotes (`'`, `"`) before constructing search query slugs or comparing candidate aliases to prevent search 404s.
- **Upstream Scraper Redundancy Audit Protocol**: Prior to implementing or reverse-engineering complex new embed scrapers (e.g. providers utilizing encrypted catalog payloads or Shadow DOM player wrappers), perform a backend source trace. If the candidate platform merely proxies streams from providers already natively implemented in Otaku (e.g. Miruro proxying AniKoto and AnimePahe), reject integration to eliminate redundant WAF friction, proxy bottlenecks, and maintenance overhead.
- **Scraper Mirror Fast-Fail & WAF 403 Circuit Breakers**: Scrapers resolving titles across multiple mirrors must break out of keyword candidate searches immediately if a mirror returns no response (`html is None` / connection failure / timeout) on the first keyword, rather than sequentially stalling on remaining keywords. When a provider's search API consistently fails with HTTP 403 (Cloudflare WAF) or empty responses, mark the mirror as failed via `domains.mark_mirror_failure()` (initiating a failure cooldown) and downgrade logging to info level to prevent log noise on every playback scrape.
- **Upstream Feature Parity & Defunct Stubs**: Check `Goldenfreddy0703/Otaku` history/PRs before refactoring browsers, resolvers, or mappers so multi-part/generic logic is never degraded. In `TMDB_HELPER` (`routes/playback.py`), evaluate `tmdb_mapping_match()` against `mappings.db` season layouts *before* fuzzy `find_episode_by_title()`. Replace permanently defunct scrapers (`aniwave.py`, `animixplay.py`) with 0ms stubs returning `[]`.
- **Browser Subclass Parity & Multipage Bounded Caching**:
  - When modifying `BrowserBase` or paginated view pipelines (`process_multipage_view`, `peek_fn`, `filter_text`), keep method signatures and routing synchronized across all three browser classes (`AniListBrowser`, `MalBrowser`, `OtakuBrowser`).
  - Keep multipage pre-caching bounded in SQLite WAL tables (`multipage_cache`, `multipage_precache_queue`) within the configured page/item ceilings (`20` pages / `1,000` entries), and integrate cleanly with Kodi's native directory sort/filter model (`multipage.py`).
- **Demuxer Chapters, Scrobbling & Stream Headers**:
  - In `WatchlistPlayer` (`player.py`), execute `query_demuxer_chapters()` (`Player.GetChapters` JSON-RPC, playerid 1) **first** on playback start, completely decoupled from `ffprobe.chapters.enable` and prior to waiting on external AniSkip APIs; snap missing final chapter end bounds (`if end <= start: end = total`).
  - Route Zero-Wait playback through `WatchlistPlayer`, decouple resume bookmark saving from `self.context` (clearing bookmarks at `>=90%`), and preserve `|Authorization=...` pipe headers on authenticated streams (e.g., Easynews).

---

## 11. HTTP Transport, Debrid Resilience, Watchlists & OAuth
- **Sub-Second Float Timeouts & Streaming Downloads**: Always cast HTTP timeouts to `float(timeout)` (never `int(timeout)`, which truncates `0.5s` to `0`). Never reintroduce single-read byte caps that truncate multi-megabyte database/archive downloads in `client.py`.
- **Modern TLS Contexts (`client.py`)**: Enforce `ssl.PROTOCOL_TLS_CLIENT` + `ssl.TLSVersion` bounds rather than legacy `ssl.PROTOCOL_TLSv1_*` constants so HTTP requests run warning-free on Python 3.12–3.14.
- **HTTPS TCP Port 443 Reachability Invariant**: `control.is_internet_available` must verify internet connectivity by attempting a non-blocking TCP socket connection on port 443 across major HTTPS CDN endpoints (`cloudflare-dns.com`, `www.gstatic.com`, `api.github.com`) before falling back to port 53. Port 53 plaintext DNS probes fail on secured networks, corporate firewalls, and NextDNS/DoH configurations.
- **Universal Defensive JSON Decoding**: Never invoke bare `json.loads()` or unguarded `r.json()` on HTTP responses, FlareSolverr/DDG proxy payloads (`cfcookie`, `ddgcookie`), or SQLite `cache.db` values (`VIEW_REVIEW`). Always use `control.safe_json(resp, default=...)`, `control.loads_json(raw, default=...)`, or `r.json(default={})`, and verify `isinstance(data, dict)` before `.get()`.
- **FlareSolverr Direct HTML Return (JA3/JA4 Bypass)**: Replaying FlareSolverr `cf_clearance` cookies over standard Python `urllib`/`urllib3` fails on Cloudflare WAF due to JA3/JA4 TLS fingerprint mismatch (returning HTTP 403). When solving Cloudflare-protected pages with FlareSolverr, always use `'returnOnlyCookies': False` (`solve_request`) to fetch and return the solved HTML directly from FlareSolverr's Chromium browser. Accept modern DDoS-Guard tokens (`__ddg1_`, `__ddg8_`, `__ddg9_`, `__ddg10_`, or any `__ddg` prefix).
- **Hard WAF IP Block Fast-Fail & Negative Turnstile Cooldown**: FlareSolverr cannot solve Interactive Turnstile challenges or hard Cloudflare ASN/IP blocks (`Attention Required! | Cloudflare`). Scrapers and HTTP clients must inspect response bodies for hard WAF block signatures and fail fast immediately (<500ms). Maintain a negative cooldown cache (e.g., 600s) for hosts that fail interactive challenges to prevent repeated multi-minute scraping hangs.
- **Lazy Challenge-Only FlareSolverr Stream Probing**: In `Resolver.prefetch_play_link`, never unconditionally route CDN stream URLs through FlareSolverr when `fs_enable=True`. Direct CDN endpoints must be probed directly first (`HEAD` / `Range: bytes=0-0` `GET`); FlareSolverr should only be invoked lazily if a challenge status code (`403`, `429`, `503`) is returned by a Cloudflare or DDoS-Guard host.
- **Jittered 429/503 Backoff**: All debrid and external API clients must catch HTTP 429 (and 503 where applicable), parse `float(r.headers.get('Retry-After', 1))`, clamp backoff to `min(max(wait, 1.0), 3.0) + random.uniform(0.1, 0.4)`, abort immediately if `control.monitor.waitForAbort(wait)` returns `True`, and retry once before failing.
- **Proactive OAuth Refresh & Watchlist Scaling**:
  - Check OAuth token expiry with a 300s pre-flight buffer (`expiry > 0 and time.time() > expiry - 300`) in API/Debrid headers (`RealDebrid`, `DebridLink`, `MyAnimeList`, `Kitsu`) alongside the 15-minute `service.py` refresh loop.
  - Chunk AniList `idMal_in` GraphQL queries into 50-item batches and paginate `MediaListCollection` via `$chunk`/`$perChunk` (`hasNextChunk`) to prevent HTTP 400 errors on 300+ item lists.
  - Recognize `WINDOW_VIDEOS` (`10025`) in `control.is_addon_visible()`, run `_should_refresh_cache()` strictly on Page 1 (`offset == 0`), never suppress `Next Page` when `page > 1`, maintain the 168-hour SQLite cache on `anime_filler`, and guard all optional/nullable fields in watchlist status item builders (`Simkl`, `AniList`, `MyAnimeList`, `Kitsu`) with `.get()` defaults plus per-item exception isolation (`viewfunc`) so sparse Page 2+ entries (unrated/unwatched items without timestamps or posters) log warnings instead of aborting the whole page.

---

## 12. Hermetic Testing, CI & Pre-Commit Verification Gate
- **Hermetic Offline Test Contract**: All unit/integration tests must include the standard standalone bootstrap importing `conftest` (`tests/conftest.py`), which enforces an offline socket guard blocking live external network calls (`_hermetic_socket_connect`). Store scraper HTML/JSON payloads as deterministic golden fixtures under `tests/fixtures/`. Diagnostic scripts that query live provider networks (`scripts/check_scraper_health.py` or live validation scripts) must never import `conftest` or must restore the original socket before initiating network connections.
- **Dual-Profile Mock Architecture (`tests/kodi_profile.py` & `tests/conftest.py`)**:
  - Switchable `KodiProfile('21' | '22')` context manager and class decorator simulating target Kodi C++ major releases offline:
    - **Kodi 21 (`21.3.0` Omega)**: `MockInfoTagVideo21` excludes Kodi 22+ exclusive methods (`setOriginalLanguage`, `setTagLine`, `setSeasonPlot`, `setAvailableFanart`, `setHdrType`) so missing `hasattr(vinfo, ...)` guards fail immediately; stream audio/subtitle language tags yield 3-letter ISO 639-2 codes (`jpn`, `eng`); `Player.GetChapters` JSON-RPC returns `{}` to verify fallback to `ffprobe` / `AniSkip`.
    - **Kodi 22 (`22.0.0` Piers)**: `MockInfoTagVideo22` exposes Kodi 22+ typed setters and strictly enforces SWIG non-null type contracts (passing `None` raises fatal `TypeError`); stream language tags yield 2-letter BCP 47 codes (`ja`, `en`); `Player.GetChapters` returns container chapters (`result.chapters`).
  - **Strict Settings Schema Enforcement (`strict_settings=True`)**: Validates setting access types against canonical `settings.xml` schema (`getBool`/`getInt`/`getNumber`/`getString`/`getStringList`), pre-seeding defaults from XML `<default>` tags on reset.
  - **Real Skin XML Control Verification (`strict_skin_controls=True`)**: Parses `<control id="...">` and `<param name="id">` across all 38 templates under `resources/skins/Default/1080i/` and raises `RuntimeError` if Python code calls `getControl(missing_id)`.
  - Exercised across dual-version matrix in `tests/unit/test_kodi_21_22_dual_compat.py`.
- **Exhaustive Settings Toggle & Outcome Matrix (`tests/unit/test_all_settings_outcomes.py`)**:
  - Comprehensive behavioral test matrix covering all 467 declared settings (`340` user-visible level 0–3 settings with 100% tooltip coverage + `127` internal/legacy level 4 settings), asserted equal to declared schema without omissions.
  - Toggles every boolean (`True`/`False`), steps every enum option and numeric slider, overrides path/string/list settings, executes action routes, and asserts concrete observable outcomes (sort/filter pruning, PRAGMA adjustments, provider enablement/exclusion, subtitle scoring, debrid cloud behavior, UI menu states, SQLite WAL cache keys).
  - Schema & localization integrity verified in `tests/unit/test_settings_schema_and_code_references.py` (100% of user-visible settings and all 12 `<category>` elements possess valid help tooltips, with zero duplicate IDs and valid `#30000–#30999` boundaries).
- **Module & Function Coverage Auditor (`scripts/audit_function_coverage.py` & `tests/lint/test_function_coverage.py`)**:
  - Enforces 100% module coverage (0 unreferenced or unimported source modules out of all 139 `.py` files across `plugin.video.otaku.rpdev` and `context.otaku.rpdev`).
  - Parses AST and tracks runtime symbol coverage via Python 3.12+ `sys.monitoring` (with transparent `sys.settrace` fallback on earlier Python versions).
  - Generates machine-readable JSON/Markdown coverage reports and enforces function coverage thresholds (`--fail-below 60`) in CI and pre-commit gates.
- **Headless Flatpak Kodi 21 & 22 E2E Suite & Mock Server (`scripts/test_kodi_installs.py` & `scripts/kodi_e2e_mock_server.py`)**:
  - Runs headless Flatpak instances inside `xvfb-run` for both `tv.kodi.Kodi//stable` (21.3-Omega) and `tv.kodi.Kodi//beta` (22.0~rc1-Piers).
  - Supported execution modes: `--mode hermetic` (default offline with zero network egress), `--mode live` (with live debrid/scrapers if configured), and `--mode all` (hermetic + live).
  - Features an ephemeral deterministic loopback HTTP mock server (`scripts/kodi_e2e_mock_server.py` on `127.0.0.1`) serving mock FlareSolverr (`/v1`), mock Megacloud (`/ms`), metadata endpoints, local video streaming with `Range` byte-serving from `tests/fixtures/media/sample_chapters.mkv` (with embedded EBML chapter markers), and external subtitles (`sample.srt`).
  - Validates fresh installation, directory generation, setting mutation effects, WindowXML modal dialog lifecycle across all custom dialogs, context menu dispatch, `service.py` lifecycle, clean quit (<10s), and zero-tolerance `kodi.log` audits (failing on Python tracebacks, `DeprecationWarning`, `ResourceWarning`, or SWIG memory leaks).
- **576-Title Comprehensive Dataset & 5-Gate Hermetic Regression Suite**:
  - The authoritative offline validation dataset is `tests/fixtures/comprehensive_anime_dataset.json` (576 unique, deduplicated anime titles spanning the Top 100 and the Top 50 across 18 genres, with canonical metadata, aliases, and distractor vectors).
  - All candidate scoring, title isolation, and scraper candidate selection changes must be verified against `tests/unit/test_top100_hermetic_regression.py` across all 5 validation gates (Monster isolation, negative distractor rejection, threshold invariants, provider candidate selection, and parametric comprehensive dataset evaluation) with 100% precision and recall offline.
- **Mandatory 5-Step Local Verification Gate**: Run and pass all five checks from `/mnt/sharedroot/projects/RPDevs-Builds/Otaku-RPDev` before every commit or release:
  1. `python3 -W default -m unittest discover tests` (860+ unit, integration, and hermetic regression tests; 0 failures/errors, and treat any project `DeprecationWarning`/`ResourceWarning` emitted during test runs as an actionable defect to fix before release)
  2. `python3 -W default -m unittest tests/lint/test_ast_integrity.py tests/lint/test_function_coverage.py tests/unit/test_settings_schema_and_code_references.py tests/unit/test_all_settings_outcomes.py tests/unit/test_kodi_21_22_dual_compat.py`
  3. `python3 scripts/audit_function_coverage.py --fail-below 60`
  4. `python3 -m compileall -q plugin.video.otaku.rpdev context.otaku.rpdev tests scripts`
  5. `ruff check --select E9,F63,F7,F82 plugin.video.otaku.rpdev context.otaku.rpdev tests scripts`

---

## 13. Automated Tag-Based Release Workflow
- **Canonical One-Command Release (Do NOT re-read `.github/workflows/release.yml` or `scripts/release_addon.py` before releasing)**: Whenever ready to commit and release the next version from `/mnt/sharedroot/projects/RPDevs-Builds/Otaku-RPDev`, run directly:
  ```bash
  python3 scripts/release_addon.py --bump patch --title "<Short Banner Title <=32 chars>" -m "<Bullet 1>;<Bullet 2>;<Bullet 3>"
  ```
  - Use `--bump minor` / `--bump major` or `--version X.Y.Z` only when explicitly requested; default is `--bump patch`.
  - If `addon.xml`, `news.txt`, and `changelog.txt` were already updated manually for an untagged target version, invoke `python3 scripts/release_addon.py` with no bump flags.
- **Automated Pipeline Responsibilities (`scripts/release_addon.py`)**:
  1. Updates `plugin.video.otaku.rpdev/addon.xml` (`version` & `<news>`), `plugin.video.otaku.rpdev/news.txt` (`<=32`-char header dividers), and `plugin.video.otaku.rpdev/changelog.txt`.
  2. Executes the local Pre-Flight Verification Gate (`ruff`, `compileall`, `python3 -W default -m unittest discover tests`, `scripts/audit_function_coverage.py --fail-below 60`).
  3. Stages and commits all changes (`git commit --no-gpg-sign`), creates annotated tag `vX.Y.Z` (`git tag -a vX.Y.Z ... --no-sign`), and pushes `main` and `vX.Y.Z` to `origin`.
  4. Triggers and monitors `.github/workflows/release.yml` (Python 3.11/3.12/3.13 test matrix -> zip package + `SHA256SUMS.txt`/`MD5SUMS.txt` -> GitHub Release -> `rpdev-cdn/kodi.repo.iamrp.dev` CDN sync) and verifies live CDN propagation at `https://kodi.repo.iamrp.dev/`.
- **Rule Updates Belong in Project `AGENTS.md`**: Store all `Otaku-RPDev` project rules, testing invariants, and release procedures in this file (`/mnt/sharedroot/projects/RPDevs-Builds/Otaku-RPDev/AGENTS.md`), never in workspace-parent `.agents/AGENTS.md`.
