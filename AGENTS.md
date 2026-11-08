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
- **`context.otaku.rpdev/`**: Standalone Kodi context menu extension. Uses defensive `_extract_subpath()` regex parsing for third-party skin widgets (Aura, Arctic Horizon, Cosmic) and accesses `info.db` strictly in read-only / `DELETE` journal mode to avoid cross-addon locks.
- **`resource.images.animestudio.{coloured,white}/`**: Bundled studio logo packs (normalize `InfoTagVideo` studios to primary animation studio to prevent multi-studio texture 404 spam).
- **`tests/`**: Hermetic offline test suite (`tests/conftest.py` C++ SWIG mocks + socket network guard, `tests/unit/`, `tests/integration/`, `tests/lint/`, `tests/fixtures/`).

---

## 2. Workspace Governance, Scripts, Archives & Network Boundaries
- **Infrastructure Source of Truth**: `/mnt/sharedroot/projects/infra-audit-engine/docs/CURRENT_ENV.yml` (refresh via `.venv/bin/python src/orchestrator.py` in `/mnt/sharedroot/projects/infra-audit-engine`).
- **Execution Baseline**: Default workspace root is `/home/llmuser/projects` (`/mnt/sharedroot/projects`); run `Otaku-RPDev` test and build commands from `/mnt/sharedroot/projects/RPDevs-Builds/Otaku-RPDev`. All git commits must explicitly pass `--no-gpg-sign` (`git commit --no-gpg-sign -m "..."`) to prevent non-interactive agent terminal hangs.
- **Reusable Helper Scripts**: Store reusable maintenance/audit/release scripts under `/home/llmuser/projects/.scripts/python/` or `/home/llmuser/projects/.scripts/shell/` and register every script in `/home/llmuser/projects/.scripts/SCRIPTS.md`. Purge one-off migration scripts after use.
- **Historical Plan & Walkthrough Archival**: Archive every `implementation_plan.md` and `walkthrough.md` to `/home/llmuser/projects/.plans/YYYY-MM-DD/Otaku-RPDev/<type>_YYYY-MM-DD_HHMMSS.md` and catalog it in `/home/llmuser/projects/.plans/INDEX.md`.
- **Network & DNS Filter Respect**: Never attempt to bypass NextDNS, firewall rules, or sandbox boundaries. Handle DNS-blocked streaming domains (`127.0.0.1` / connection refused) gracefully via multi-server failover and report blocked domains to the user.

---

## 3. Deployment & Addon Release Pipeline Mandate
- **Target Device Non-Interference & No Direct Updates**:
  - Live target devices (such as ONN Android TV `10.13.0.16`) are user-managed media centers in active use.
  - Never push code, assets, or addon files directly onto target devices via ADB.
  - Never trigger repository updates (`UpdateAddonRepos`), manipulate device SQLite databases (`Addons33.db`), invoke remote management scripts (`kodi_remote_cli.py -U`), or issue JSON-RPC/input commands to live target hardware.
  - The agent's release pipeline boundary strictly terminates when the release package is published to GitHub Releases and synchronized to the Kodi repository CDN (`https://kodi.repo.iamrp.dev`). The user updates their own devices when they choose.
- **Modernized Tag-Based GitHub Actions Release Pipeline**:
  All releases are driven automatically by Git version tags (`v*`) via `.github/workflows/release.yml`:
  1. Prepend human-readable release highlights to `plugin.video.otaku.rpdev/news.txt` and `plugin.video.otaku.rpdev/changelog.txt`.
  2. Bump `version="X.Y.Z"` in `plugin.video.otaku.rpdev/addon.xml`.
  3. Commit: `git commit -m "chore(release): bump plugin.video.otaku.rpdev to vX.Y.Z - <Highlights>"`.
  4. Tag and push: `git tag vX.Y.Z && git push origin main --tags`.
  5. GitHub Actions release workflow automatically executes:
     - **Pre-Flight Test Gate**: Matrix build across Python 3.11, 3.12, and 3.13 running `ruff`, `compileall`, and all 589+ unit and AST integrity tests.
     - **Package & GitHub Release**: Validates version matching `addon.xml`, extracts notes from `news.txt`, packages clean `plugin.video.otaku.rpdev-<version>.zip` and SHA256/MD5 checksums, publishing release assets directly to GitHub Releases (`RPDevs-Builds/Otaku-RPDev`).
     - **Sync to Kodi CDN Repository**: Clones `rpdev-cdn/kodi.repo.iamrp.dev` using repository secret `CDN_REPO_TOKEN`, copies ZIP and metadata, runs `tools/generate_repo.py`, and commits/pushes to `main`, triggering automated GitHub Pages deployment to `https://kodi.repo.iamrp.dev`.
  6. **Offline / Emergency Fallback**: `scripts/release_addon.py` is preserved solely for offline or manual emergency packaging when GitHub Actions is inaccessible; standard releases must always traverse the tag-based CI/CD pipeline.

---

## 4. Dual Kodi 20/21 (Nexus/Omega) & Kodi 22 (Piers) Compatibility
- **`InfoTagVideo` Modernization**: Always populate metadata via `vinfo = li.getVideoInfoTag()` with typed setters (`setTitle`, `setPlot`, `setYear`, `setGenres`, `setCast`, `setDuration`). Never call deprecated `ListItem.setInfo()`. For Kodi 22+ exclusive setters (`setOriginalLanguage`, `setTagLine`, `setSeasonPlot`), guard with `hasattr(vinfo, ...)` inside `try...except` and mirror values to `li.setProperty(...)` for Kodi 20/21 skin compatibility.
- **SWIG Non-Null Type Contracts**: Kodi 22 SWIG directors reject `None` for `std::string` / numeric arguments with fatal `TypeError` exceptions. Explicitly coerce every argument passed to `xbmc.Actor`, `xbmcgui.ListItem(str(name or ''))`, `vinfo`, and `_AddonProxy.setSetting(str(id or ''), str(val if val is not None else ''))`. Never use `str(val)` on nullable values (which writes literal `'None'`).
- **Dual BCP 47 & ISO 639-2 Language Matching**: Route all audio and subtitle track selectors through `is_language_match()` (`LANGUAGE_SYNONYMS`) so 2-letter BCP 47 / regional tags (`ja`, `en`, `en-US` in Kodi 22) and 3-letter ISO 639-2 codes (`jpn`, `eng` in Kodi 20/21) match identically. Position `latin-1` last in subtitle encoding fallbacks.
- **Python 3.12–3.14 Clean Runtimes & Invoker Hygiene**:
  - Zero imports of PEP 594 removed stdlib modules (`cgi`, `pipes`, `imghdr`, `sunau`, `crypt`, `chunk`, `uu`, `telnetlib`, etc.).
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
- **Streaming Video Range Headers in Redirect Probes**: When resolving redirects on video URLs in scraper workers (e.g., `_follow_redirect_url`), never execute unconstrained `urlopen()` or `client.get()`. Always supply `Range: bytes=0-0` and bound byte reads (`limit=1`) to avoid buffering stream payloads into RAM.
- **Single-IP AdGate Concurrency Guard**: Streaming hosts with timestamped AdGate sessions (e.g. `embed.wcostream.com`) enforce a single active verification session per client IP. Scrapers must process audio variants sequentially (SUB then DUB) rather than concurrently to prevent IP-level session invalidation (`HTTP 503 Servers Busy`).
- **Multi-Server Candidate Retention**: Collect all enabled stream servers/mirrors into prioritized candidate lists and attempt resolution sequentially (`hianime.py`, `gogoanime.py`, etc.). Never place an early `break` after the first server match.
- **Modern Embed Scraper Architecture & Fallbacks**:
  - **Canonical Domain Selection & TLS Health**: Select active mirrors with complete, valid Cloudflare TLS certificate chains (e.g. `https://gogoanime.me/`). Avoid domains missing intermediate certificates (e.g. Let's Encrypt `YR1` omissions) or ccTLDs frequently sinkholed by NextDNS (e.g. `.bz`).
  - **Pre-Rendered Category Page Fallback**: Modern embed sites frequently deprecate AJAX episode loaders (`/load-list-episode`) while pre-rendering complete episode listings inside static category HTML (`/category/{slug}` inside `<div id="episode-items">`). Scrapers must implement category page parsing as an automatic fallback for movies, specials, OVAs, or when direct episode slug generation fails.
  - **Server Class Normalization**: Normalize obfuscated or generic player button CSS classes (e.g. class `anime` -> Vidstreaming/Goone) to standard internal resolver IDs (`vidcdn`, `streamwish`, `mp4upload`, `doodstream`, `filemoon`) and process all valid candidate servers sequentially without premature `break`s.
  - **Unicode Quote Normalization**: Normalize typographic/smart quotes (`’`, `‘`, `“`, `”`) to standard ASCII quotes (`'`, `"`) before constructing search query slugs or comparing candidate aliases to prevent search 404s.
- **Upstream Scraper Redundancy Audit Protocol**: Prior to implementing or reverse-engineering complex new embed scrapers (e.g. providers utilizing encrypted catalog payloads or Shadow DOM player wrappers), perform a backend source trace. If the candidate platform merely proxies streams from providers already natively implemented in Otaku (e.g. Miruro proxying AniKoto and AnimePahe), reject integration to eliminate redundant WAF friction, proxy bottlenecks, and maintenance overhead.
- **Upstream Feature Parity & Defunct Stubs**: Check `Goldenfreddy0703/Otaku` history/PRs before refactoring browsers, resolvers, or mappers so multi-part/generic logic is never degraded. In `TMDB_HELPER` (`routes/playback.py`), evaluate `tmdb_mapping_match()` against `mappings.db` season layouts *before* fuzzy `find_episode_by_title()`. Replace permanently defunct scrapers (`aniwave.py`, `animixplay.py`) with 0ms stubs returning `[]`.
- **Demuxer Chapters, Scrobbling & Stream Headers**:
  - In `WatchlistPlayer` (`player.py`), execute `query_demuxer_chapters()` (`Player.GetChapters` JSON-RPC, playerid 1) **first** on playback start, completely decoupled from `ffprobe.chapters.enable` and prior to waiting on external AniSkip APIs; snap missing final chapter end bounds (`if end <= start: end = total`).
  - Route Zero-Wait playback through `WatchlistPlayer`, decouple resume bookmark saving from `self.context` (clearing bookmarks at `>=90%`), and preserve `|Authorization=...` pipe headers on authenticated streams (e.g., Easynews).

---

## 11. HTTP Transport, Debrid Resilience, Watchlists & OAuth
- **Sub-Second Float Timeouts & Streaming Downloads**: Always cast HTTP timeouts to `float(timeout)` (never `int(timeout)`, which truncates `0.5s` to `0`). Never reintroduce single-read byte caps that truncate multi-megabyte database/archive downloads in `client.py`.
- **HTTPS TCP Port 443 Reachability Invariant**: `control.is_internet_available` must verify internet connectivity by attempting a non-blocking TCP socket connection on port 443 across major HTTPS CDN endpoints (`cloudflare-dns.com`, `www.gstatic.com`, `api.github.com`) before falling back to port 53. Port 53 plaintext DNS probes fail on secured networks, corporate firewalls, and NextDNS/DoH configurations.
- **Universal Defensive JSON Decoding**: Never invoke bare `json.loads()` or unguarded `r.json()` on HTTP responses, FlareSolverr/DDG proxy payloads (`cfcookie`, `ddgcookie`), or SQLite `cache.db` values (`VIEW_REVIEW`). Always use `control.safe_json(resp, default=...)`, `control.loads_json(raw, default=...)`, or `r.json(default={})`, and verify `isinstance(data, dict)` before `.get()`.
- **FlareSolverr Direct HTML Return (JA3/JA4 Bypass)**: Replaying FlareSolverr `cf_clearance` cookies over standard Python `urllib`/`urllib3` fails on Cloudflare WAF due to JA3/JA4 TLS fingerprint mismatch (returning HTTP 403). When solving Cloudflare-protected pages with FlareSolverr, always use `'returnOnlyCookies': False` (`solve_request`) to fetch and return the solved HTML directly from FlareSolverr's Chromium browser. Accept modern DDoS-Guard tokens (`__ddg1_`, `__ddg8_`, `__ddg9_`, `__ddg10_`, or any `__ddg` prefix).
- **Hard WAF IP Block Fast-Fail & Negative Turnstile Cooldown**: FlareSolverr cannot solve Interactive Turnstile challenges or hard Cloudflare ASN/IP blocks (`Attention Required! | Cloudflare`). Scrapers and HTTP clients must inspect response bodies for hard WAF block signatures and fail fast immediately (<500ms). Maintain a negative cooldown cache (e.g., 600s) for hosts that fail interactive challenges to prevent repeated multi-minute scraping hangs.
- **Lazy Challenge-Only FlareSolverr Stream Probing**: In `Resolver.prefetch_play_link`, never unconditionally route CDN stream URLs through FlareSolverr when `fs_enable=True`. Direct CDN endpoints must be probed directly first (`HEAD` / `Range: bytes=0-0` `GET`); FlareSolverr should only be invoked lazily if a challenge status code (`403`, `429`, `503`) is returned by a Cloudflare or DDoS-Guard host.
- **Jittered 429/503 Backoff**: All debrid and external API clients must catch HTTP 429 (and 503 where applicable), parse `float(r.headers.get('Retry-After', 1))`, clamp backoff to `min(max(wait, 1.0), 3.0) + random.uniform(0.1, 0.4)`, abort immediately if `control.monitor.waitForAbort(wait)` returns `True`, and retry once before failing.
- **Proactive OAuth Refresh & Watchlist Scaling**:
  - Check OAuth token expiry with a 300s pre-flight buffer (`expiry > 0 and time.time() > expiry - 300`) in API/Debrid headers (`RealDebrid`, `DebridLink`, `MyAnimeList`, `Kitsu`) alongside the 15-minute `service.py` refresh loop.
  - Chunk AniList `idMal_in` GraphQL queries into 50-item batches and paginate `MediaListCollection` via `$chunk`/`$perChunk` (`hasNextChunk`) to prevent HTTP 400 errors on 300+ item lists.
  - Recognize `WINDOW_VIDEOS` (`10025`) in `control.is_addon_visible()`, run `_should_refresh_cache()` strictly on Page 1 (`offset == 0`), never suppress `Next Page` when `page > 1`, and maintain the 168-hour SQLite cache on `anime_filler`.

---

## 12. Hermetic Testing, CI & Pre-Commit Verification Gate
- **Hermetic Offline Test Contract**: All unit/integration tests must include the standard standalone bootstrap importing `conftest` (`tests/conftest.py`), which enforces an offline socket guard blocking live external network calls (`_hermetic_socket_connect`). Store scraper HTML/JSON payloads as deterministic golden fixtures under `tests/fixtures/`. Diagnostic scripts that query live provider networks (`scripts/check_scraper_health.py` or live validation scripts) must never import `conftest` or must restore the original socket before initiating network connections.
- **Headless Kodi 21 & 22 Smoke Test Tool (`scripts/test_kodi_installs.py`)**: For pre-release runtime validation, run `python3 scripts/test_kodi_installs.py`. This script spins up isolated Xvfb headless instances of both Kodi 21 (Omega) and Kodi 22 (Piers), dynamically extracts the current version from `addon.xml`, tests fresh add-on installation, verifies JSON-RPC ping and add-on enable status, and scans `kodi.log` for fatal C++ errors, invalid setting types, or SWIG exceptions.
- **Mandatory 4-Step Local Verification Gate**: Run and pass all four checks from `/mnt/sharedroot/projects/RPDevs-Builds/Otaku-RPDev` before every commit or release:
  1. `python3 -m unittest discover tests` (589+ unit, integration, and adversarial tests; 0 failures/errors)
  2. `python3 -m unittest tests/lint/test_ast_integrity.py` (AST syntax, zero bare `except:`, zero `pickle`, zero `.select(` / `.select_one(`, 38 skin XMLs valid)
  3. `python3 -m unittest tests/unit/test_settings_schema_and_code_references.py tests/unit/test_clean_settings.py`
  4. `python3 -m compileall -q plugin.video.otaku.rpdev context.otaku.rpdev tests`
