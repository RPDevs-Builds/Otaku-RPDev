# Otaku-RPDev Development & Engineering Rules

Authoritative engineering invariants and operational mandates for `Otaku-RPDev` (`plugin.video.otaku.rpdev`, `context.otaku.rpdev`, and `service.subtitles.otaku.rpdev`). See [docs/README.md](docs/README.md) for the full documentation index ([docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/TESTING.md](docs/TESTING.md), [docs/AUTOMATION.md](docs/AUTOMATION.md), [docs/CONFIGURATION_GUIDE.md](docs/CONFIGURATION_GUIDE.md), [docs/CONCERNS.md](docs/CONCERNS.md)), and `.agents/skills/` for operational runbooks.

---

## 1. Repository Architecture & Module Boundaries
- **`plugin.video.otaku.rpdev/`**: Primary video add-on targeting Kodi 20 (Nexus), Kodi 21 (Omega), and Kodi 22 (Piers).
  - `default.py` (plugin router; dispatches auto-changelog asynchronously so modal dialogs never block root `GetDirectory`), `service.py` (`clean_settings`, 15m proactive OAuth refresh, passive SQLite WAL checkpoints).
  - `resources/lib/ui/` (`control.py`, `database.py`, `client.py`, `player.py`, `source_utils.py`, `embed_extractor.py`, `domains.py`), `Main.py` & `routes/`, `pages/`, `debrid/`, `endpoints/`, `WatchlistFlavor/`, `subtitles/`, `windows/` & `resources/skins/Default/1080i/` (41 XML templates).
- **`context.otaku.rpdev/`**: Standalone context menu add-on (`_extract_subpath()` regex parsing for skin widgets; read-only `info.db`; 530 coloured/white studio logos under `resources/images/studios/`).
- **`service.subtitles.otaku.rpdev/`**: Native Kodi `xbmc.subtitle.module` service add-on bridging Kodi's VideoOSD subtitle dialog to `plugin.video.otaku.rpdev`'s multi-provider subtitle engine (SubDL, SubSource, OpenSubtitles, Podnapisi, Animetosho).
- **`tests/`**: Hermetic offline suite (`tests/conftest.py` socket guard + SWIG mocks, `tests/kodi_profile.py` Kodi 21/22 simulation, `tests/unit/`, `tests/integration/`, `tests/lint/`, `tests/fixtures/`).

---

## 2. Workspace Governance & Network Boundaries
- **Execution & Git Baseline**: Run `Otaku-RPDev` commands from `/mnt/sharedroot/projects/RPDevs-Builds/Otaku-RPDev`. All automated git commits must pass `--no-gpg-sign`. Never escape above `/mnt/sharedroot/projects/RPDevs-Builds/Otaku-RPDev/` (or `Kodi-Debugging/` for debug tasks).
- **Direct Output & Non-Truncation**: Write outputs directly to designated destinations (no `/tmp/` detours). Never unilaterally prune or truncate comprehensive audit/test scopes.
- **Target Device Diagnostics**: Inspect live devices (e.g., ONN `10.13.0.16`) read-only via `http://10.13.0.16:8081/tail?offset=<N>` or direct non-mutating ADB CLI; never drive interactive human scripts (`kodi_debug.py`). Respect DNS/NextDNS/firewall boundaries; handle blocked hosts via failover.

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
- **Kodi 22 External Subtitle Parser & VFS Cache Contract**: `embed_extractor.get_sub()` must strip BOM and leading whitespace to byte 0, validate cues matching Kodi's `CDVDFactorySubtitle::CreateParser()` (`.vtt`/`.srt`/`.ass`, rejecting HTML/JSON/cue-less stubs, auto-promoting hour-less VTT cues, and falling back to origin `source_url`/`?url=` even on HTTP 200 error bodies), verify `atomic_write_text(...) is not False`, and use unique per-play `sub_tag` nonces in `resolver.py` and `routes/playback.py` to avoid `special://temp/` `g_directoryCache` collisions and Zero-Wait `del_subs()` races.
- **`setDateTime()` & `setEpisode()` Sort Contracts**: Populate `li.setDateTime("YYYY-MM-DDTHH:MM:SS")` (guarded with `hasattr`) in `set_videotags()` for `SORT_METHOD_DATE`, and populate `info['episodes']` across all TV browse/watchlist views for `SORT_METHOD_EPISODE`.
- **Python 3.12–3.14 & Invoker Hygiene**: Zero PEP 594 removed stdlib imports (`cgi`, `pipes`, `imghdr`, `sunau`, etc.). Use `ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)` + `ssl.TLSVersion` bounds (never deprecated `ssl.PROTOCOL_TLSv1_*` / `PROTOCOL_TLS`). Use cooperative `super().__init__()`, `None` sentinels instead of mutable defaults, `control.log()` instead of `print()`, and keep `schedule_next_page_prefetch` a no-op (no detached `CPythonInvoker` threads).

---

## 5. Kodi C++ Settings Schema & Defensive Accessors
- Route all setting reads/writes through `control.py` (`getBool`, `getInt`, `getStr`, `getNumber`, `*List`). Guard module-load `xbmcaddon.Addon()` with static fallbacks for ZIP-upgrade transients.
- Coerce `settingid` and `value` with typed defaults *before* calling C++ `settings.set*` and *before* updating `_settings_cache` / `homeWindow`. Wrap all getters/setters in `try...except Exception:`.
- Derive dynamic setting prefixes (e.g., `EMBED_SKIP_PREFIXES`) from a single registry (`_EMBED_MODULES` in `pages/__init__.py`).
- Use `<level>4</level>` for internal settings, keep zero duplicate `<setting id="...">` declarations, and run `test_settings_schema_and_code_references.py` + `test_clean_settings.py` before modifying `resources/settings.xml`.

---

## 6. Memory Management & Low-RAM (1GB Android TV) Safeguards
- **64 KB UTF-8 Window Property Ceiling**: Reject payloads exceeding `65,536` UTF-8 bytes (`len(val_str.encode('utf-8', errors='replace')) > 65536`) in `_WindowProxy.setProperty` / `control.setGlobalProp`; store large payloads in SQLite WAL `cache.db`.
- **Modal `WindowXML` Disposal**: Wrap `doModal()` in `try...finally:` calling `dlg.close()`, `del dlg`, and clearing references.
- **Non-Folder Flag for Modal Menu Items**: Menu items opening modal dialogs (e.g., `airing_calendar`) must set `isFolder=False, isPlayable=False`.

---

## 7. SQLite Concurrency, Static Dictionaries & Self-Healing
- **In-Memory Locks Only**: Never create `*.db.lock` files. Use `threading.RLock()` and `execute_write_with_retry()` with jittered backoff (`10–150ms`).
- **Read-Only URI & Pool Separation**: Static dictionaries (`info.db`, `mappings.db`) must default to `is_readonly=True`, connect via `file:{abs_path}?mode=ro` (`uri=True`, `timeout=float(self.timeout)`), skip all write PRAGMAs and WAL checkpoints, and key thread-local pools by `(abs_path, is_readonly)`.
- **Non-Destructive Migrations**: Evolve schemas via `PRAGMA table_info` + `ALTER TABLE` in `_migrate_database()`; never wipe user DBs on upgrade. Preserve `_quarantine_and_recover_db()` self-healing and passive `PRAGMA wal_checkpoint(PASSIVE)` in `service.py`.

---

## 8. Kodi GUI WindowXML & Single Event Dispatch Protocol
- **Single Event Dispatch**: Never handle Action IDs `7`, `100`, or double-click inside `onAction()` when `onClick(control_id)` exists; guard irreversible modal actions with an idempotency flag.
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
- **Zero-`soupsieve` BS4**: Never use `.select()` or `.select_one()` (enforced by AST lint); use `.find()` and `.find_all()`.
- **Domain-Agnostic Scrapers & Extractors**: Never hardcode single-domain filters; derive origins via `urllib.parse.urlparse`, normalize base URLs with `.rstrip('/')`, and normalize Unicode smart quotes (`’`/`“`/`”`) before slugging. Probe video redirects with `Range: bytes=0-0` and `limit=1`.
- **Parallelized Single-Batch Scrapers & Direct ↔ Alt Host Fallback**: Torrent scrapers (`nyaa.py`, `animetosho.py`) must merge `show_pack` queries into the primary `parallel_process` pool, deduplicate candidate hashes before a single batched `Debrid().torrentCacheCheck()` (preventing 15s `general.timeout` cutoffs), and implement thread-safe direct ↔ `translate.goog` alt-host fallback with sticky host switching and `warning` diagnostics (guarding HTTP status checks with `isinstance(status, int) and status >= 400`).
- **Candidate Scoring, Sequel Alias Parity & 4-Tier Relevance Gating**:
  - Route parsing through `isolate_show_title()` and `score_title_candidate()` (exact `>=140`, alias `140`, approved descriptors `115–125`, derivatives/wrong seasons `<=40`, strict word boundaries for short titles).
  - Always invoke `source_utils.expand_sequel_season_aliases()` inside **both** `source_utils.filter_sources()` (pre-Debrid) and `pages/__init__.py:sortSources()` (post-Debrid) so season-numbered Dub/Dual-Audio releases for arc-subtitled sequels are never dropped early.
  - Enforce 4-tier relevance sorting in `sortSources()` before quality/size.
- **Embed Resilience & Upstream Parity**: Retain all multi-server candidates sequentially; implement static category-page HTML fallbacks; break fast on dead mirrors and apply `domains.mark_mirror_failure()` cooldowns on WAF 403/empty responses; process WCO SUB/DUB sequentially (single-IP AdGate) using the `inc/embed/index.php` + `/ad-verify` handshake; reject proxy-only scrapers; keep `BrowserBase` / `AniListBrowser` / `MalBrowser` / `OtakuBrowser` multipage signatures synchronized; check `Goldenfreddy0703/Otaku` history/PRs before refactoring; evaluate `tmdb_mapping_match()` before fuzzy title matching; keep defunct scrapers as 0ms `[]` stubs.
- **Chapters, Zero-Wait & Headers**: Query native Kodi 22 `Player.GetChapters` first (decoupled from `ffprobe.chapters.enable`), snap missing final chapter end bounds, route Zero-Wait through `WatchlistPlayer`, clear resume bookmarks at `>=90%`, and preserve `|Authorization=...` pipe headers.

---

## 11. HTTP Transport, Debrid Resilience, Watchlists & OAuth
- Cast timeouts to `float(timeout)`; never reintroduce single-read byte caps on streaming downloads.
- **Query-String-Safe Parameter Joining**: Always join URL query params with `'&' if '?' in url else '?'` and `domains.join_url()` so `translate.goog` alt URLs carrying `?_x_tr_*` never receive a double `?`.
- Test TCP port 443 HTTPS endpoints before port 53 in `control.is_internet_available`.
- Never call bare `json.loads()` or unguarded `r.json()`; always use `control.safe_json()` / `control.loads_json()` / `r.json(default={})`.
- **FlareSolverr & WAF**: Use `'returnOnlyCookies': False` (JA3/JA4 bypass), fail fast (<500ms) on hard Cloudflare IP blocks with 600s negative Turnstile cooldowns, and probe direct CDN URLs first before lazy FlareSolverr invocation on 403/429/503.
- **429 Backoff & OAuth**: Catch HTTP 429/503, clamp jittered `Retry-After` to `1.0–3.0s`, abort on `waitForAbort()`, and retry once. Check OAuth expiry with a 300s buffer (`time.time() > expiry - 300`).
- **Watchlists**: Batch AniList `idMal_in` in 50-item chunks, paginate `MediaListCollection`, recognize `WINDOW_VIDEOS` (`10025`), refresh cache only on Page 1, and isolate sparse Page 2+ item errors with `.get()` + per-item `try...except`.

---

## 12. Hermetic Testing, CI & Unified Verification Gate
- All unit/integration tests must import `tests/conftest.py` (offline socket guard + SWIG mocks) and stay hermetic via `tests/fixtures/`. Validate dual Kodi 21/22 behavior via `tests/kodi_profile.py`, all 467 settings via real consumer calls in `test_all_settings_outcomes.py`, UI/routes via `test_end_user_ui_and_routes.py`, and scoring via the 576-title dataset (`test_top100_hermetic_regression.py`).
- **Actionable Test Quality Guardrails (`tests/lint/`)**: `test_suite_quality.py` forbids zero-assertion tests, tautologies, broad `except Exception: pass` swallowing in tests, unexecuted `module_from_spec`, and import-only `assertIsNotNone` placeholders. `test_ast_integrity.py` enforces code invariants (zero `soupsieve`, zero deprecated `ssl.PROTOCOL_TLS*`/`ListItem.setInfo()`, zero `int(timeout)`). `test_docs_and_customizations.py` enforces the `< 22 KB` `AGENTS.md` cap, skill frontmatter, `news.txt` divider width, and Markdown link integrity.
- **Non-Vacuous Linters & Strict UI/Consumer Testing**: Every `tests/lint/*.py` module must compute `_REPO_ROOT = os.path.dirname(os.path.dirname(_TEST_DIR))` and assert a minimum scanned-item floor (`>= 90` test files, `>= 5` docs) so broken paths never pass vacuously. Settings tests must assert real consumer outcomes (no `set`→`get` echoes), and WindowXML tests must run under `KodiProfile('22', strict_skin_controls=True)`.
- **Unified Pre-Flight Gate (`scripts/verify_all.py`)** — identical locally, in `ci.yml`, in `release.yml`, and in `scripts/release_addon.py`:
  - Run `python3 scripts/verify_all.py --fail-below 60` (or `--json <path>` for structured LLM diagnostics, `--e2e` for headless Kodi 22).
  - Executes 4 mandatory silos: `ruff check --select E9,F63,F7,F82,F811,F405,F541`, `compileall`, `unittest discover -s tests` with strict project warnings-as-errors (`-W error::DeprecationWarning:resources -W error::ResourceWarning:resources`), and `audit_function_coverage.py --fail-below 60` (100% module coverage).
- See [docs/TESTING.md](docs/TESTING.md) and [docs/AUTOMATION.md](docs/AUTOMATION.md) for detailed recipes and headless Kodi 21/22 E2E commands.

---

## 13. Automated Tag-Based Release Workflow
- Release directly with `python3 scripts/release_addon.py --bump patch --title "<Short Banner <=32 chars>" -m "<Bullets>"` (auto-updates `addon.xml`/`news.txt`/`changelog.txt`, runs `scripts/verify_all.py --fail-below 60`, commits `--no-gpg-sign`, tags `--no-sign`, pushes `main` + `vX.Y.Z`, watches GitHub Actions CI, and verifies GitHub Release + live CDN `https://kodi.repo.iamrp.dev/`).
- Store all `Otaku-RPDev` project-specific rules in this file (keeping it strictly `< 22,000` bytes; enforced by `test_docs_and_customizations.py`).
