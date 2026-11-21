# Otaku-RPDev Architecture & Subsystem Guide

Detailed reference for developers and contributors working on `plugin.video.otaku.rpdev`, `context.otaku.rpdev`, and `service.subtitles.otaku.rpdev`. For strict engineering invariants and guardrails, see [AGENTS.md](../AGENTS.md).

---

## 1. Repository & Module Map

```text
Otaku-RPDev/
├── plugin.video.otaku.rpdev/           # v6.3.0 primary video add-on
│   ├── default.py                      # Plugin router dispatch (async changelog offload)
│   ├── service.py                      # Background service (clean_settings, 15m OAuth & retry drain, .xz/.gz mappings sync, WAL checkpoint)
│   └── resources/
│       ├── settings.xml                # 494 declared settings (367 user-visible levels 0-3, 127 internal level 4)
│       ├── data/domains.json           # Dynamic provider domain registry & mirror lists
│       ├── skins/Default/1080i/        # 41 custom 1080i WindowXML / WindowXMLDialog templates
│       └── lib/
│           ├── Main.py & routes/       # Explicit re-exports + modular routes (playback, history, subtitles, tools, search, watchlist)
│           ├── pages/                  # Torrent, Usenet & embed scrapers + orchestrator (__init__.py)
│           ├── debrid/                 # Real-Debrid, Premiumize, AllDebrid, Debrid-Link, TorBox, EasyDebrid, Easynews
│           ├── ui/                     # control.py, database.py, database_sync.py, client.py, player.py, source_utils.py, embed_extractor.py, domains.py (AdaptiveCircuitBreaker), settings_manager.py
│           ├── subtitles/              # Subtitle Intelligence v2 (6 providers, SDH stripper, fallback, dual BCP 47 / ISO 639-2 matcher)
│           ├── endpoints/              # AniList, MAL, TMDb, TVDB, AniZip, AnimeFiller, AniSkip, IntroDB
│           ├── WatchlistFlavor/        # AniList, MyAnimeList, Kitsu, Simkl sync, Conflict Engine & Drift Auditor
│           └── windows/                # Custom WindowXML controllers (resolver, source_select, get_sources, filter_select, stats_window, anichart, etc.)
├── context.otaku.rpdev/                # v1.0.46 standalone widget-aware context menu add-on + 530 canonical PNGs per style (coloured/white)
├── service.subtitles.otaku.rpdev/      # v1.0.3 native Kodi xbmc.subtitle.module companion add-on (OSD search & auto-download)
├── scripts/                            # verify_all.py, qa_fast.py, e2e_v630_suite.py, audit_onn_logs.py, release_addon.py, audit_function_coverage.py, test_kodi_installs.py
├── tests/                              # 1,070+ discover tests + 126 E2E suite tests (dual Kodi 21/22 mocks, AST/quality/doc lints, 576-title dataset)
└── docs/                               # README.md, ARCHITECTURE.md, PLANS.md, TESTING.md, AUTOMATION.md, CONCERNS.md, CONFIGURATION_GUIDE.md, teamwork/
```

---

## 2. Scraping, Filtering & Relevance Pipeline

```mermaid
flowchart LR
    A["MetaBrowser.get_sources()"] --> B["pages/__init__.py<br/>ThreadPoolExecutor (<=30s)"]
    B --> C["Torrent Scrapers<br/>nyaa, animetosho, torrentio,<br/>nekobt, bitsearch, piratebay"]
    B --> D["Embed & Usenet<br/>hianime, anikoto, animepahe,<br/>wco, gogo, easynews"]
    C --> E["Direct <-> Alt Host Fallback<br/>+ Parallel show_pack"]
    E --> F["source_utils.filter_sources()<br/>+ expand_sequel_season_aliases()"]
    F --> G["Single Batched<br/>Debrid().torrentCacheCheck()"]
    G --> H["part_filter.filter_sources()<br/>(Chinese hardsub / part / batch)"]
    D --> H
    H --> I["sortSources()<br/>Audio filter -> 4-Tier Relevance Gate -> Quality/Size"]
```

Key design principles:
- **Zero-`soupsieve` HTML parsing**: Kodi's bundled `beautifulsoup4` omits `soupsieve`; all scrapers exclusively use `.find()` / `.find_all()`.
- **Parallel single-batch scraping (`nyaa.py`, `animetosho.py`)**: Episode queries and `show_pack` queries run in one `utils.parallel_process` pass, deduplicate candidate hashes, and execute a single batched `Debrid().torrentCacheCheck()` so scrapers complete in ~3–4s well inside a 15s `general.timeout`.
- **Automatic direct ↔ `translate.goog` failover**: If a scraper's configured host returns an HTTP error or missing content container, it transparently retries the opposite host (`animetosho.net` ↔ `animetosho-net.translate.goog`, `nyaa.si` ↔ `nyaa-si.translate.goog`) and sticky-switches for the remainder of the scrape.
- **Unified 0–200 scoring (`source_utils.score_title_candidate`)**: Exact matches (`>=140`), aliases (`140`), approved descriptors (`115–125`), and strict rejection of derivatives/wrong seasons (`<=40`). Sequel season aliases (`expand_sequel_season_aliases`) are applied both pre-Debrid (`filter_sources`) and post-Debrid (`sortSources`).
- **Unified Adaptive Circuit Breaker (`domains.AdaptiveCircuitBreaker`)**: Tracks failures across all provider classes (`torrent`, `embed`, `subtitle`, `metadata`, `debrid`) using exponential cooldown tiers (`300s` $\rightarrow$ `900s` $\rightarrow$ `3600s`), `HALF_OPEN` recovery probes, and `Window(10000)` persistence (`pages.circuit_breaker` / `ScraperCircuitBreaker` aliased cleanly).
- **Per-Series `episode_offset` Isolation (`MetaBrowser.get_sources`)**: Applies `series_overrides.episode_offset` strictly to outbound scraper `actionArgs['episode']` while keeping `canonical_episode` untouched for local history and remote watchlist scrobbling.

---

## 3. Playback, Zero-Wait Binge & Subtitle Intelligence v2

- **Zero-Wait Pre-Resolved Playback**: During active playback, `WatchlistPlayer` pre-scrapes and pre-resolves the next episode (pruning failing lead candidates in `resolve_silent()` and saving the remaining list via `database.set_episode_sources()`), bypassing scraping entirely when a cached season pack covers `ep + 1`.
- **Filler Badges & Binge Auto-Skip**: `endpoints/anime_filler.py:classify_filler_tag()` and `indexers/__init__.py` append colorized `[FILLER]` / `[RECAP]` badges (`interface.filler.badges`), while `WatchlistPlayer.build_playlist()` excludes filler episodes during binge playback (`smartplay.skip_filler` or per-series `skip_filler_mode`), preserving the list if all remaining episodes are filler.
- **Chapter & Auto-Skip Priority**:
  1. Native Kodi 22 demuxer chapters (`Player.GetChapters` JSON-RPC) — queried first, decoupled from `ffprobe`.
  2. Pre-probed container chapters (`ffprobe_chapters.attach_to_linkinfo`).
  3. AniSkip / Anime-Skip / IntroDB community timestamps (with per-series `intro_offset_s` / `outro_offset_s` adjustments from `series_overrides`).
- **Kodi 22 External Subtitle Contract & Subtitle Intelligence v2 (`embed_extractor.py` & `subtitles/`)**:
  - Aligned with Kodi 22 `CDVDFactorySubtitle::CreateParser()`: strips UTF-8 BOM + leading whitespace to byte 0, validates `.vtt`/`.srt`/`.ass` cues, auto-promotes hour-less VTT cues, rejects HTML/JSON/cue-less stubs with origin fallback even on HTTP 200 error bodies, and registers `special://temp/` URIs in `g_directoryCache` via `control.atomic_write_text(..., vfs_path=...)` (`os.listdir()` in `del_subs()`, never `xbmcvfs.listdir()`).
  - Detects sparse `<45`-cue Signs-only embed `.vtt` sidecars (`otaku.embed_sub_signs_only`) and clears stale flags between episodes to auto-upgrade to Full Dialogue across 6 providers (`opensubtitles`, `subdl`, `subsource`, `podnadpisi`, `bsplayer`, `addic7ed`).
  - `subtitles/download.py:strip_sdh_hearing_impaired_tags()` (`subtitles.strip_sdh_tags`) removes SDH brackets/speaker prefixes while preserving ASS `{...}` override tags; `auto_download_subtitles()` falls through failed candidates with circuit-breaker health tracking.

---

## 4. SQLite Concurrency, Low-RAM & Watchlist Sync Architecture

| Database | Mode | Notes |
|---|---|---|
| `cache.db`, `search.db`, `malSync.db` | Read-Write WAL | `malSync.db` (`SCHEMA_VERSION = '1.0.14'`) stores `shows`, `episodes`, `shows_meta`, `show_data`, `watchlist_cache` / `v_watchlist_items`, `series_overrides`, and `scrobble_retry_queue`. `SyncDatabase._ensure_column_migrations()` runs `PRAGMA table_info` + `ALTER TABLE` unconditionally on startup so mid-sprint columns never drift. |
| `info.db`, `mappings.db` | Read-Only URI (`?mode=ro`) | Static reference dictionaries; skips all write PRAGMAs and WAL checkpoints; safe for concurrent reads from `context.otaku.rpdev`. `service.update_mappings_db()` supports `.xz`/`.gz`, SHA-256 verification, `PRAGMA quick_check(1)` staging, `mappings.db.bak` backup, and automatic corruption rollback. |

- **Multi-Tracker Conflict Engine & Drift Auditor (`WatchlistFlavor/` & `WatchlistIntegration.py`)**: Resolves multi-tracker progress using `watchlist.sync.conflict_policy` (`0=highest_progress`, `1=primary_wins`, `2=latest_updated`), persists HTTP 429/5xx scrobble failures with `Retry-After` + exponential backoff into `scrobble_retry_queue` (replayed in `service.py`), exposes `watchlist_telemetry`, and provides `watchlist_drift_auditor` with dry-run mutation counts + confirmation dialogs.
- **64 KB Window Property Ceiling**: `_WindowProxy.setProperty` enforces `<= 65,536` UTF-8 bytes; large payloads reside in SQLite WAL tables.
- **Modal Dialog Cleanup**: Every `WindowXML` / `WindowXMLDialog` is closed and deleted (`del dlg`) inside `try ... finally:` blocks, and `SettingsBackupDialog` / `settings_manager.py` backs up and restores `series_overrides` alongside settings/logins.

---

## 5. Dual Kodi 20/21 & Kodi 22 Testing Architecture

- **Unified Multi-Silo Gate (`scripts/verify_all.py`)**: Shared identically by local development, GitHub Actions CI (`.github/workflows/ci.yml`), release CI (`.github/workflows/release.yml`), and `scripts/release_addon.py`. Runs expanded Ruff (`E9,F63,F7,F82,F811,F405,F541`), `compileall`, the 1,070+ offline suite + 126 `e2e_v630_suite.py` tests under strict project warnings-as-errors (`-W error::DeprecationWarning:resources -W error::ResourceWarning:resources`), and `audit_function_coverage.py --fail-below 65` (100% module coverage). See [TESTING.md](TESTING.md) and [AUTOMATION.md](AUTOMATION.md).
- **Hermetic Offline Suite (`tests/`)**: `tests/conftest.py` blocks live sockets and provides `MockWindowXMLDialog` lifecycle hooks (`onInit`, `onAction`, `onClick`, `onFocus`); `tests/kodi_profile.py` simulates both Kodi 21 (`MockInfoTagVideo21`, ISO 639-2 `jpn`/`eng`, empty `Player.GetChapters`) and Kodi 22 (`MockInfoTagVideo22`, strict SWIG non-null contracts, BCP 47 `ja`/`en`, native chapters) with real `settings.xml` schema validation and real 41-template 1080i skin XML control checks. `tests/lint/` enforces AST invariants (`test_ast_integrity.py`), anti-placeholder test quality (`test_suite_quality.py`), and rule/skill/doc drift (`test_docs_and_customizations.py`).
- **Headless Flatpak E2E (`scripts/test_kodi_installs.py` & `scripts/kodi_e2e_mock_server.py`)**: Runs real `tv.kodi.Kodi//stable` (21.3) and `tv.kodi.Kodi//beta` (22.0) under `xvfb-run` with an ephemeral loopback mock server serving Range-capable MKV streams (`sample_chapters.mkv`), external subtitles, and mock APIs.
