# Otaku-RPDev Data Models, SQLite Schemas & State Contracts

This reference documents every persistent SQLite database schema, in-memory `Window(10000)` / `Window(home)` property contract, JSON file format, and standardized internal Python dictionary schema across the tri-addon ecosystem (`plugin.video.otaku.rpdev`, `service.subtitles.otaku.rpdev`, `context.otaku.rpdev`).

> [!IMPORTANT]
> **SQLite Concurrency & Connection Pool Invariant**:
> - Read/write user databases (`malSync.db`, `cache.db`, `search.db`) open in **WAL mode** (`PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000`).
> - Static bundled/companion dictionary databases (`mappings.db`, `anime_metadata.db`, `info.db`) **must** be opened via read-only URI (`file:<path>?mode=ro`).
> - Connection caches in [`ui/database.py`](../plugin.video.otaku.rpdev/resources/lib/ui/database.py) partition connection handles by `(db_path, mode)` so read-only readers are never blocked or mixed with write transactions.

---

## 1. Read/Write User SQLite Databases (`special://profile/addon_data/plugin.video.otaku.rpdev/`)

### 1.1 `malSync.db` (Core Metadata, Episodes, Watchlist & Scrobble State)
Managed by [`ui/database.py`](../plugin.video.otaku.rpdev/resources/lib/ui/database.py) and [`ui/database_sync.py`](../plugin.video.otaku.rpdev/resources/lib/ui/database_sync.py). Schema migrations are version-gated via the `activities` table (`otaku_version`) and explicit `ALTER TABLE` column checks.

| Table | Primary Key / Unique Constraint | Columns & Types | Purpose |
|---|---|---|---|
| `activities` | `sync_id INTEGER PRIMARY KEY` | `sync_id INTEGER`, `otaku_version TEXT NOT NULL` | Tracks active schema version and triggers automatic migrations in [`database_sync.py`](../plugin.video.otaku.rpdev/resources/lib/ui/database_sync.py). |
| `shows` | `mal_id INTEGER PRIMARY KEY` (`UNIQUE(mal_id)`) | `mal_id INTEGER`, `anilist_id INTEGER`, `simkl_id INTEGER`, `kitsu_id INTEGER`, `kodi_meta BLOB NOT NULL`, `anime_schedule_route TEXT NOT NULL` | Core anime series directory. `kodi_meta` stores pickled dict with `name`, `title_userPreferred`, `ename`, `synonyms`, `episodes`, `status`, `rating`, `plot`, `year`, `country`, `studio`, and `genre`. |
| `shows_meta` | `mal_id INTEGER PRIMARY KEY` (`UNIQUE(mal_id)`) | `mal_id INTEGER`, `meta_ids BLOB`, `art BLOB` | Cross-provider ID dictionary (`thetvdb_id`, `themoviedb_id`, `anidb_id`, `imdb_id`, `trakt_id`) and multi-provider artwork dictionary (`poster`, `fanart`, `clearlogo`, `clearart`, `banner`, `landscape`, `thumb`). |
| `episodes` | `FOREIGN KEY(mal_id) REFERENCES shows(mal_id) ON DELETE CASCADE` | `mal_id INTEGER NOT NULL`, `season INTEGER NOT NULL`, `kodi_meta BLOB NOT NULL`, `last_updated TEXT NOT NULL`, `number INTEGER NOT NULL`, `filler TEXT`, `anidb_ep_id INTEGER` | Per-episode metadata (`number` = 1-based episode number). `filler` stores canonical classification (`Canon`, `Manga Canon`, `Anime Canon`, `Mixed Canon/Filler`, `Filler`, `Recap`). `kodi_meta` contains `info` (`title`, `plot`, `aired`, `rating`, `duration`, `episode`, `season`) and `image` (`thumb`, `fanart`). |
| `show_data` | `mal_id INTEGER PRIMARY KEY` (`UNIQUE(mal_id)`) | `mal_id INTEGER`, `data BLOB NOT NULL`, `last_updated TEXT NOT NULL` | Raw upstream show payload cache (Simkl/AniList/MAL episode list response) keyed by `mal_id` and ISO date `last_updated`. |
| `watchlist_cache` | `id INTEGER PRIMARY KEY AUTOINCREMENT`, `UNIQUE(service, status, item_order)` | `id INTEGER`, `service TEXT NOT NULL`, `status TEXT NOT NULL`, `mal_id INTEGER`, `item_order INTEGER NOT NULL`, `data BLOB NOT NULL`, `last_updated INTEGER NOT NULL` | Local SQLite cache for user watchlist rows per tracker (`mal`, `anilist`, `kitsu`, `simkl`) and status bucket (`current`, `completed`, `on_hold`, `dropped`, `plan_to_watch`, `next_up`). |
| `watchlist_activity` | `service TEXT PRIMARY KEY` | `service TEXT`, `activity_timestamp TEXT NOT NULL`, `last_checked INTEGER NOT NULL` | Last upstream activity hash/timestamp per tracker to support conditional delta-sync without re-downloading unchanged lists. |
| `anilist_enrichment` | `mal_id INTEGER PRIMARY KEY` | `mal_id INTEGER`, `data BLOB NOT NULL`, `last_updated INTEGER NOT NULL` | Cached AniList GraphQL enrichment (`relations`, `recommendations`, `studios`, `characters`, `nextAiringEpisode`, `stats`). |
| `series_overrides` | `mal_id INTEGER PRIMARY KEY` | `mal_id INTEGER`, `audio_lang TEXT`, `sub_lang TEXT`, `sub_mode TEXT`, `preferred_provider TEXT`, `intro_offset_s INTEGER DEFAULT 0`, `outro_offset_s INTEGER DEFAULT 0`, `episode_offset INTEGER DEFAULT 0`, `sub_offset_ms INTEGER DEFAULT 0`, `skip_filler_mode TEXT DEFAULT 'default'`, `updated_at INTEGER NOT NULL` | Per-series overrides (`SCHEMA_VERSION = '1.0.16'`) configured via `SeriesProfileDialog` ([`windows/series_profile.py`](../plugin.video.otaku.rpdev/resources/lib/windows/series_profile.py)) and chapter-aligned calibration. Loaded at playback/subtitle prep to override global audio/subtitle/provider/offset/filler settings. |
| `scrobble_retry_queue` | `id INTEGER PRIMARY KEY AUTOINCREMENT`, `UNIQUE(service, action, mal_id)` | `id INTEGER`, `service TEXT NOT NULL`, `action TEXT NOT NULL`, `mal_id INTEGER NOT NULL`, `episode INTEGER DEFAULT 0`, `status TEXT DEFAULT ''`, `score INTEGER DEFAULT 0`, `attempts INTEGER DEFAULT 0`, `next_retry_at INTEGER NOT NULL`, `last_error TEXT DEFAULT ''`, `created_at INTEGER NOT NULL` | Durable offline/429 retry queue for failed tracker scrobble and status-update mutations. Drained every 15 minutes by [`service.py`](../plugin.video.otaku.rpdev/service.py) and `WatchlistFlavor.process_scrobble_retry_queue()`. |

---

### 1.2 `cache.db` (TTL Response Cache, Provider Circuit-Breaker & Multipage Jobs)

| Table | Primary Key / Unique Constraint | Columns & Types | Purpose |
|---|---|---|---|
| `cache` | `key TEXT UNIQUE` | `key TEXT UNIQUE`, `value TEXT`, `date INTEGER` | General key-value function call cache (`database.get(fn, duration_hours, *args)`) and 64KB window-property overflow storage. `key` is an MD5/SHA hash of `(function_name, args, kwargs)`; `value` is hex-encoded pickled payload; `date` is Unix timestamp. |
| `multipage_jobs` | `id INTEGER PRIMARY KEY AUTOINCREMENT`, `job_key TEXT UNIQUE` | `id INTEGER`, `job_key TEXT UNIQUE`, `provider TEXT`, `browser_method TEXT`, `url_path TEXT`, `route TEXT`, `params TEXT`, `current_page INTEGER`, `target_page INTEGER`, `status TEXT`, `priority INTEGER DEFAULT 0`, `error_count INTEGER DEFAULT 0`, `last_error TEXT`, `created_at INTEGER`, `updated_at INTEGER` | Persistent job queue for background multipage catalog prefetching. |

> [!NOTE]
> **Adaptive Circuit-Breaker & Stream Cache Keys in `cache.db`**:
> - Provider health state (`AdaptiveCircuitBreaker` in [`ui/client.py`](../plugin.video.otaku.rpdev/resources/lib/ui/client.py)) and HiAnime mirror health are persisted inside `cache.db` under namespaced keys (`cb_health:<provider>`, `stream_cache:<mal_id>:<episode>`), surviving across Kodi Python invoker calls.

---

### 1.3 `search.db` (Search History by Media Scope)

| Table | Primary Key / Unique Constraint | Columns & Types | Purpose |
|---|---|---|---|
| `show` | `value TEXT UNIQUE` | `value TEXT UNIQUE` | Recent anime show/series search queries. |
| `movie` | `value TEXT UNIQUE` | `value TEXT UNIQUE` | Recent anime movie search queries. |
| `both` | `value TEXT UNIQUE` | `value TEXT UNIQUE` | Recent combined (`all` / `both`) search queries. |

---

## 2. Read-Only Static Bundled & Companion Databases (`?mode=ro`)

### 2.1 `mappings.db` & `anime_metadata.db` (`script.otaku.mappings` / `Otaku-Mapping-DB`)
Delivered via the companion `script.otaku.mappings` module or synced on-demand via `sync_mappings` from the nightly [`Otaku-Mapping-DB`](https://github.com/RPDevs-Builds/Otaku-Mapping-DB) release pipeline (with fallback to `resources/data/mappings.db`).

- **`mappings` table (`mappings.db`)**:
  - Primary Key: `mal_id INTEGER PRIMARY KEY`
  - Cross-ID Columns: `anilist_id INTEGER`, `kitsu_id INTEGER`, `simkl_id INTEGER`, `anidb_id INTEGER`, `thetvdb_id INTEGER`, `themoviedb_id INTEGER`, `imdb_id TEXT`, `anisearch_id INTEGER`, `livechart_id INTEGER`, `notify_moe_id TEXT`, `anime_planet_id TEXT`
  - Season/Part Mapping Columns: `thetvdb_season INTEGER`, `thetvdb_part INTEGER`, `themoviedb_season INTEGER`, `episode_offset INTEGER`
- **`anime_metadata.db` (Nightly Vacuumed Enrichment Store)**:
  - Stores offline pre-aggregated titles, synonyms, release years, episode counts, studio mappings, and genre tags for ~30,000+ anime entries to accelerate cold catalog loads without live GraphQL round-trips.

---

## 3. `Window(10000)` / `Window(home)` Property Registry & 64KB Ceiling

All window property reads and writes route through [`ui/control.py`](../plugin.video.otaku.rpdev/resources/lib/ui/control.py) (`getGlobalProp`, `setGlobalProp`, `clearGlobalProp`, `setWindowProp`).

> [!WARNING]
> **64KB C++ Window Property Ceiling**:
> Kodi stores `xbmcgui.Window(10000).setProperty(key, val)` in the C++ GUI heap. Payloads exceeding **65,536 bytes** (`len(val.encode('utf-8', errors='replace')) > 65536`) are forbidden in `Window(10000)` and must be offloaded to `cache.db` to prevent heap fragmentation on 1GB–2GB Android TV devices (e.g., ONN 4K Box).

### 3.1 Cross-Addon & Playback Window Properties (`Window(10000)`)

| Property Key | Producer | Consumer | Format / Schema | Lifecycle |
|---|---|---|---|---|
| `otaku.mal_id` | `WatchlistPlayer`, `routes/playback.py` | `service.subtitles.otaku.rpdev`, `context.otaku.rpdev` | String integer (`"21"`) | Set on playback start; cleared on playback stop. |
| `otaku.active_playback_meta` | `WatchlistPlayer.onPlayBackStarted` | `service.subtitles.otaku.rpdev/service.py` | JSON object: `{"mal_id": int, "anilist_id": int, "anidb_id": int, "tvdb_id": int, "tmdb_id": int, "imdb_id": str, "title": str, "romaji_title": str, "english_title": str, "synonyms": list[str], "season": int, "episode": int, "abs_episode": int, "year": int, "media_type": "episode"\|"movie"}` | Set before/at playback start; cleared on playback end/stop/error. |
| `otaku.active_source_is_dub` | `Resolver`, `routes/playback.py` | `WatchlistPlayer`, `service.subtitles.otaku.rpdev` | `"true"` or `""` | Tracks whether the resolved stream is an English Dub / Dual-Audio track. |
| `otaku.preResolved_malId` | `WatchlistPlayer` (80% / -180s trigger) | `routes/playback.py:_try_preresolved_handoff` | String integer (`"21"`) | Set when background next-episode pre-resolve completes; consumed & cleared on next episode launch. |
| `otaku.preResolved_episode` | `WatchlistPlayer` | `routes/playback.py:_try_preresolved_handoff` | String integer (`"2"`) | Matched with `otaku.preResolved_malId` to verify exact episode handoff. |
| `otaku.preResolved_url` | `WatchlistPlayer` | `routes/playback.py:_try_preresolved_handoff` | Resolved HTTP/HTTPS stream URL | Direct playable URL for Zero-Wait instant episode transition. |
| `otaku.preResolved_data` | `WatchlistPlayer` | `routes/playback.py:_try_preresolved_handoff` | JSON object: `{"url": str, "subs": list[str], "headers": dict, "source": dict, "candidates": list[dict], "ts": float}` | Full pre-resolved bundle including backup failover candidates and external subtitle paths. Expires after 20 minutes (`1200s`). |
| `otaku.consecutive_autoplay` | `WatchlistPlayer` | `StillWatchingXML` (`still_watching.py`) | String integer (`"0"`..`"N"`) | Increments on automatic UpNext episode transitions; triggers "Are You Still Watching?" prompt at threshold (default 3). |
| `otaku.scene_markers` | `WatchlistPlayer` | `routes/playback.py` (`STEP_SCENE_MARKER`, `SCENE_MARKERS`) | JSON array: `[{"type": "intro"\|"outro"\|"recap"\|"canon", "label": str, "start": float, "end": float}]` | Active episode chapter/OP/ED/scene markers for instant jump navigation. |
| `otaku.current_scene_marker` | `WatchlistPlayer` | `SkipIntro` (`skip_intro.py`) | JSON object: `{"type": str, "label": str, "start": float, "end": float}` | Currently active skippable segment while inside an OP/ED window. |
| `otaku.skipintro.label` | `WatchlistPlayer` | `skip_intro_*.xml`, `skip_outro_*.xml` | Localized button label (`"Skip Intro"`, `"Skip Outro"`, `"Skip Recap"`) | Bound to button label in Skip Intro/Outro overlay XMLs. |
| `script.trakt.ids` | `WatchlistPlayer.onPlayBackStarted` | `script.trakt` Kodi service | JSON object: `{"tmdb": int, "tvdb": int, "imdb": str, "mal": int, "slug": str}` | Standard Trakt scrobbler interoperability contract; cleared on playback stop. |
| `context.otaku.rpdev.*` | [`service.py:sync_context_menu_properties`](../plugin.video.otaku.rpdev/service.py) | [`context.otaku.rpdev/addon.xml`](../context.otaku.rpdev/addon.xml) `<visible>` conditions | `"true"` or `"false"` | Mirrors `context.otaku.rpdev.*` boolean visibility settings into `Window(10000)` at startup and on `onSettingsChanged()`. |
| `otaku.memory_pressure` | [`control.enforce_memory_watermark`](../plugin.video.otaku.rpdev/resources/lib/ui/control.py) | `service.py` (`MultipageWorker`) | `"true"` or `""` | Active on 32-bit hosts when VmRSS >= `general.memory_watermark_mb` (900 MB) or VmSize >= 2600 MB; cleared with 85% hysteresis. |
| `otaku.memory_concurrency_limit` | `control.enforce_memory_watermark` | `service.py` / workers | `"1"` or `""` | Concurrency cap published alongside `otaku.memory_pressure`. |
| `otaku.dns_gate_until` | [`client.ConnectivityGate`](../plugin.video.otaku.rpdev/resources/lib/ui/client.py) | `client.request()`, `AdaptiveCircuitBreaker` | Float Unix timestamp string (`<= now + 15.0`) | Shared 15s DNS/connectivity drop gate requiring `>= 2` distinct host failures within 5s or failed internet probe. |

---

## 4. Standardized Internal Python Dictionary & JSON Schemas

### 4.1 Scraper & Resolver `source` Dictionary Contract
Every scraper in [`resources/lib/pages/*.py`](../plugin.video.otaku.rpdev/resources/lib/pages/) returns a list of standardized `source` dictionaries consumed by `source_utils.filter_sources()`, `pages/__init__.py:sortSources()`, `windows/source_select.py`, and `windows/resolver.py`:

```python
{
    "release_title": str,       # Raw release or embed title (e.g., "[SubsPlease] Solo Leveling - 01 (1080p) [ABCD1234].mkv")
    "hash": str,                # Magnet infohash (40-char hex), direct embed URL, or local file path
    "provider": str,            # Lowercase scraper ID (e.g., "nyaa", "animetosho", "hianime", "animepahe", "local")
    "type": str,                # "torrent" | "cloud" | "hoster" | "embed" | "local" | "direct"
    "quality": int,             # Resolution tier: 3 (4K/2160p), 2 (1080p), 1 (720p), 0 (SD/480p)
    "debrid_provider": str,     # "Real-Debrid" | "AllDebrid" | "Premiumize" | "Debrid-Link" | "TorBox" | "EasyDebrid" | ""
    "size": str,                # Human-readable size badge (e.g., "1.42 GB")
    "byte_size": int,           # Raw size in bytes for tie-break sorting
    "info": list[str],          # Parsed codec/audio/group tags (e.g., ["HEVC", "10BIT", "DUAL-AUDIO", "AAC", "BATCH"])
    "lang": int,                # Audio language code: 0 (Sub/Japanese), 2 (Dub/English), 3 (Dual-Audio)
    "sub_lang": str,            # Explicit subtitle language code if known (e.g., "eng", "")
    "seeders": int,             # Torrent seeder count (-1 or 0 for embeds/cloud)
    "episode_re": str,          # Matched episode number string for season-pack file extraction
    "cached": bool,             # True for cached debrid torrents / direct embeds; False for uncached magnets
    "_relevance_tier": int,     # Populated by sortSources(): 3 (exact >=140), 2 (strong >=95), 1 (acceptable >=45), 0 (weak)
    "_relevance_score": int,    # Populated by sortSources(): 0..200 candidate title score from score_title_candidate()
}
```

### 4.2 Persistent JSON Files (`special://profile/addon_data/plugin.video.otaku.rpdev/`)
- **`watch_history.json`**: Ordered JSON array of recently watched show/episode descriptors (`mal_id`, `title`, `episode`, `season`, `poster`, `fanart`, `route`, `timestamp`) capped to prevent unbounded growth.
- **`download_queue.json`**: Managed by [`windows/download_manager.py`](../plugin.video.otaku.rpdev/resources/lib/windows/download_manager.py); tracks active, paused, completed, and failed HTTP stream downloads (`id`, `title`, `url`, `dest_path`, `status`, `bytes_downloaded`, `total_bytes`, `speed`, `eta`, `headers`).
- **Settings Backup JSON (`otaku_settings_backup_*.json`)**: Managed by [`windows/settings_backup.py`](../plugin.video.otaku.rpdev/resources/lib/windows/settings_backup.py); stores timestamped key-value snapshots of `settings.xml` partitioned by category (`general`, `debrid`, `scrapers`, `watchlist`, `playback`, `subtitles`, `context`).
