# Otaku-RPDev Quad-Addon & External Integrations Guide

Technical reference for how **`plugin.video.otaku.rpdev`**, **`service.otaku.rpdev`**, **`context.otaku.rpdev`**, and **`service.subtitles.otaku.rpdev`** integrate with each other, Kodi skins/widgets, third-party Kodi add-ons (`TMDb Helper`, `Trakt`), the offline `Otaku-Mapping-DB` ecosystem, and external API providers.

> **Related Docs:** [FEATURES.md](FEATURES.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [TESTS.md](TESTS.md) · [CONFIGURATION_GUIDE.md](CONFIGURATION_GUIDE.md) · [AGENTS.md](../AGENTS.md)

---

## 1. Quad-Addon Inter-Process Contracts

### 1.1 Acyclic Dependency DAG (`C-27`) & Settings Pinning (`C-28`)
- Companion add-ons must **never** declare `<import addon="plugin.video.otaku.rpdev"/>` (preventing circular dependency deadlocks in Kodi 22 `DialogAddonInfo.xml`, enforced by `test_zero_circular_addon_dependencies` in `tests/lint/test_ast_integrity.py`).
  - `context.otaku.rpdev/addon.xml` and `service.subtitles.otaku.rpdev/addon.xml` declare **only** `<import addon="xbmc.python" version="3.0.1"/>`.
  - `service.otaku.rpdev/addon.xml` declares `xbmc.python` + third-party `script.module.*` dependencies only, exposing `<extension point="xbmc.service" library="service.py"/>` and `<extension point="xbmc.python.module" library="resources/lib"/>`.
- `control.ADDON_ID` remains statically pinned to `'plugin.video.otaku.rpdev'` and `control.SERVICE_ADDON_ID` to `'service.otaku.rpdev'`. `control.py` transparently routes all 30 `SERVICE_SETTING_IDS` keys to `service_settings` (with `otaku.service_settings_epoch` cache sync and resilient `RuntimeError` fallback).

### 1.2 `plugin.video.otaku.rpdev` ↔ `service.otaku.rpdev`
- **Startup Upgrade Safety**: `service.otaku.rpdev/service.py` runs self-contained `otaku_service.migration.migrate_service_settings()` first (zero plugin imports, idempotent via `service.migrated_from_plugin_v1`), then verifies via plain-text disk check that `plugin.video.otaku.rpdev` is v6.7.0+ (no `xbmc.service`, exposes `SERVICE_ADDON_ID`) before mutating `sys.path` or importing `resources.*`.
- **Bidirectional Settings Sync**: `Monitor.onSettingsChanged()` and `control.set*()` writes to `SERVICE_SETTING_IDS` both bump `Window(10000).Property(otaku.service_settings_epoch)`. `Monitor.check_plugin_settings_changed()` watches plugin `settings.xml` `(st_mtime_ns, st_size)` at `5s` active / `1s` settings-open / `60s` standby intervals.
- **`xbmc.python.module` Shared Leaf Infrastructure (`service.otaku.rpdev` v1.1.0+)**: `otaku_service` exposes AST-enforced zero-plugin-dependency leaf modules (`metrics.py`, `safe_json.py`, `connectivity.py`, `circuit_breaker.py`, `sqlite_pool.py`, `migration.py`) consumed by both `service.otaku.rpdev` and `plugin.video.otaku.rpdev` (`ui/control.py`, `ui/client.py`, `ui/domains.py`, `ui/database.py`).
- **1-Click Settings Access**: `plugin.video.otaku.rpdev` exposes `open_service_settings` (`Addon.OpenSettings(service.otaku.rpdev)`) in General settings and Tools, while `service.otaku.rpdev` owns Cache & Database, Maintenance, and Solvers/Network/Debug settings.

### 1.2 `plugin.video.otaku.rpdev` ↔ `context.otaku.rpdev`
- **Home-Window Visibility Flags**: `control.process_context()` in `plugin.video.otaku.rpdev` publishes boolean flags (`Window(home).Property(context.otaku.rpdev.<action>) = 'true'|'false'`) matching the user's Context Customization toggles.
- **Widget & External `ListItem` Resolution (`context.otaku.rpdev/default.py`)**:
  - `_resolve_widget_mal_id(item, path)` resolves `mal_id` in order:
    1. `item.getVideoInfoTag().getUniqueIDs()` (`mal_id` / `mal`) or `getUniqueID('mal_id'|'mal')`
    2. `item.getProperty('mal_id' | 'otaku.mal_id' | 'UniqueID(mal_id)')`
    3. URL query string parameters (`?mal_id=...` or `?id=...`)
  - Non-Otaku `videodb://` and `library://` items without a resolved `mal_id` safely no-op.
- **Shared Static Dictionary (`info.db`)**: `context.otaku.rpdev/info.db` is queried by `plugin.video.otaku.rpdev` strictly in SQLite URI read-only mode (`file:...info.db?mode=ro`, `is_readonly=True`) with `PRAGMA mmap_size = 0` on low-memory devices.

### 1.3 `plugin.video.otaku.rpdev` ↔ `service.subtitles.otaku.rpdev`
- **Active Playback Metadata Handoff**: On playback start, `WatchlistPlayer.keepAlive()` calls `subtitles.publish_active_playback_meta(...)` to publish title, show title, season, episode, year, and `UniqueIDs` (`mal_id`, `imdb`, `tmdb`, `tvdb`, `anidb`) to `Window(10000)` (`otaku.active_playback_meta`), and clears it on stop/end.
- **VFS Cache-Safe Temp Staging (`C-30`)**: `service.subtitles.otaku.rpdev` stages downloaded OSD subtitles inside its own profile directory (`special://profile/addon_data/service.subtitles.otaku.rpdev/temp/`) rather than `special://temp/`, avoiding Kodi C++ `g_directoryCache` collisions with `embed_extractor.del_subs()`.

---

## 2. Kodi Skins, Home Screen Widgets & Overlay Themes

### 2.1 Home Screen Widget Refresh Lifecycle (`O-9`)
- During playback startup (`WatchlistPlayer.keepAlive()`), `Main.save_to_watch_history(self.mal_id, self.episode)` updates `watch_history.json` and `control.setSetting('addon.last_watched', str(self.mal_id))`.
- When playback stops, ends (without a queued next playlist item), or aborts on error, `WatchlistPlayer._refresh_widgets_on_stop()` calls `control.clearSettingsCache()` and `control.execute('Container.Refresh')` so Kodi Home Screen widgets pointing to `last_watched`, `watch_history`, or `next_up` reload immediately.

### 2.2 Per-Skin Overlay Theme Auto-Selection
- Custom playback overlays (`playing_next_*.xml`, `skip_intro_*.xml`, `skip_outro_*.xml` under `resources/skins/Default/1080i/`) ship in **7 skin-matched variants**:
  - `default` (Estuary / stock), `af` (Arctic Fuse), `af2` (Arctic Fuse 2), `ah2` (Arctic Horizon 2), `auramod` (AuraMod), `az` (Arctic Zephyr / Martian), `tb` (Titan Bingie).
- Non-Estuary font references exist strictly inside their matching theme XML files; `Default/1080i` base dialogs use Estuary fonts exclusively (`C-40`).

---

## 3. Third-Party Kodi Add-on Bridges

### 3.1 TMDb Helper (`plugin.video.themoviedb.helper`)
- **Route**: `plugin://plugin.video.otaku.rpdev/tmdb_helper` (`routes/playback.py:TMDB_HELPER`).
- Accepts `item_type` (`movie` / `episode`), `tmdb_id`, `title_url`, `season_number`, `episode_number`, and `source_select=true|false`.
- Resolves TMDb IDs to canonical `mal_id` via `mappings.db` (`get_mappings(tmdb_id, 'themoviedb_id')`) with title/season fallback, then routes directly into Otaku's `PLAY` / `PLAY_MOVIE` pipeline.

### 3.2 Trakt (`script.trakt`)
- When `trakt.enabled` is true, `WatchlistPlayer` publishes `Window(10000).Property(script.trakt.ids)` JSON (`tmdb`, `tvdb`, `imdb`, `mal` IDs enriched from `mappings.db` / `anime_metadata.db`) on playback start (`publish_trakt_ids`) and clears it on playback stop/end (`clear_trakt_ids`).

---

## 4. `Otaku-Mapping-DB` Dual-Database Pipeline

Managed by `service.py` (`_maybe_sync_daily_mappings`, `update_mappings_db`, `update_metadata_db`) and queried in read-only URI mode (`?mode=ro`) by `ui/database.py`:

| Artifact | Local Path | Key Tables / Capabilities |
|---|---|---|
| `anime_mappings.db.xz` | `control.mappingDB` (`mappings.db`) | `mappings` (cross-ID translation), `tvdb_rules` (split-cour episode offsets), `filler_ranges` (`Filler`, `Mixed Canon/Filler`, `Recap` ranges; untagged episodes in mapped shows default to `Canon`), `anime_aliases` |
| `anime_metadata.db.xz` | `control.metadataDB` (`anime_metadata.db`) | `anime_metadata` (offline catalog rows, synopses, studios, ratings, `schedule_ids`), `metadata_fts` (offline FTS title/alias search) |
| `manifest.json` | Remote checksum manifest | Raw SHA-256 verification before atomic swap; `.etag` sidecars for HTTP 304 fast-skip; `PRAGMA quick_check(1)` + `.bak` automatic corruption rollback |

---

## 5. External Provider & API Contracts

- **Watchlist Trackers (`WatchlistFlavor/`)**: `AniList` (GraphQL, 50-ID `idMal_in` batching, `MediaListCollection` pagination), `MyAnimeList` (OAuth2 PKCE + token refresh), `Kitsu` (JSON:API + token refresh), `Simkl` (OAuth PIN + sync). Coordinated by `watchlist.sync.conflict_policy` (`highest_progress`, `primary_wins`, `latest_updated`), `scrobble_retry_queue` (`Retry-After` + disabled-service cleanup + `last_error` logging), and `watchlist_drift_auditor`.
- **Debrid & Usenet (`debrid/`)**: `RealDebrid`, `Premiumize`, `AllDebrid`, `DebridLink`, `TorBox`, `EasyDebrid`, `Easynews`. All callers respect HTTP 429 `Retry-After` (capped at 3s with jitter on `waitForAbort`).
- **Intro/Outro Skip APIs (`endpoints/`)**: Queried after Kodi 22 native demuxer chapters (`Player.GetChapters`) and `ffprobe` chapters: `AniSkip` → `Anime-Skip` → `IntroDB` (adjusted by per-series `intro_offset_s` / `outro_offset_s`).
- **Online Subtitle Services (`subtitles/services/`)**: `opensubtitles`, `subdl`, `subsource`, `podnadpisi`, `bsplayer`, `addic7ed`, plus native anime providers **`jimaku`** (`https://jimaku.cc/api/`, `Authorization: <key>`, Japanese-only short-circuit, `anilist_id -> mal_id -> kitsu_id -> title`) and **`animetosho`** (`https://feed.animetosho.org/json`, `eid -> aid -> q`, bounded detail fetches `<= 2`, standalone `.ass`/`.srt`/`.xz` attachments) — all guarded by `AdaptiveCircuitBreaker` (`category="subtitle"`), episode/title mismatch filtering, ASS-tag-safe SDH stripping, release-group match scoring, and 25fps PAL speedup rescaling (`max_sub_ts > video_dur * 1.03`).
- **WAF & Proxy Failover (`ui/client.py`, `ui/domains.py`)**: Direct ↔ `translate.goog` sticky host failover (`nyaa`, `animetosho`), FlareSolverr direct HTML return (`returnOnlyCookies: False`), fast-fail Cloudflare hard-block/Turnstile negative cooldowns, and `endpoints/fanart.py` `%20` URL space escaping (`_sanitize_art_url`).
