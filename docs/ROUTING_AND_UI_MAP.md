# Otaku-RPDev Plugin Routing & WindowXML UI Reference Map

This reference catalogs every `@Route` and `@multi_route` endpoint across `plugin.video.otaku.rpdev`, every action dispatched by `context.otaku.rpdev`, the query entrypoint of `service.subtitles.otaku.rpdev`, and the control ID / property matrix for all 41 `1080i` `WindowXML` templates.

---

## 1. `plugin.video.otaku.rpdev` Route Registry

Routing is dispatched via [`ui/router.py`](../plugin.video.otaku.rpdev/resources/lib/ui/router.py) (`@Route` and `@multi_route`). Note that `_browser_list_route_paths('<slug>')` automatically registers four path variants per catalog endpoint: `<slug>`, `<slug>/*`, `movies/<slug>/*`, and `tv_shows/<slug>/*`.

### 1.1 Catalog, Browse & Metadata Routes ([`Main.py`](../plugin.video.otaku.rpdev/resources/lib/Main.py))

| Handler Function | Route Pattern(s) | Directory / Modal Mode | Description |
|---|---|---|---|
| `INDEX` | `/` (root) | `draw_items` (`isFolder=True`) | Main menu hub (ordered by `MenuOrderDialog` preferences). |
| `MOVIES_MENU` / `TV_SHOWS_MENU` | `movies`, `tv_shows` | `draw_items` (`isFolder=True`) | Media-type filtered top-level catalog menus. |
| `ANIMES_PAGE` | `animes/*` (`animes/<mal_id>/<eps_watched>`) | `draw_items` (`viewType='episodes'`) | Resolves and renders the episode directory for `<mal_id>` via [`MetaBrowser.get_anime_init()`](../plugin.video.otaku.rpdev/resources/lib/MetaBrowser.py) with `[CANON]`/`[MIXED]`/`[FILLER]`/`[RECAP]` badges. |
| `AIRING_CALENDAR` | `airing_calendar` | Modal `WindowXML` (`anichart.xml`) | Launches the 7-day tabbed `Anichart` airing calendar (`isFolder=False`). |
| `FIND_RECOMMENDATIONS` | `find_recommendations/*` | `draw_items` (`tvshows`) | Fetches similar/recommended anime for `<mal_id>` from active browser flavor (`AniList`/`MAL`/`Otaku`). |
| `FIND_RELATIONS` | `find_relations/*` | `draw_items` (`tvshows`) | Lists sequels, prequels, side-stories, and spin-offs for `<mal_id>`. |
| `WATCH_ORDER` | `watch_order/*` | `draw_items` (`tvshows`) | Traverses release/chronological watch order chain for `<mal_id>`. |
| `ANIME_REVIEWS` / `VIEW_REVIEW` | `anime_reviews/*`, `view_review/*` | Directory -> Modal `TextViewerXML` | Lists user reviews for `<mal_id>` and opens selected full-text review. |
| `ANIME_STATISTICS` | `anime_statistics/*` | Modal `StatsWindow` (`anime_statistics.xml`) | Renders score distribution bar charts and watch status breakdowns for `<mal_id>`. |
| `AIRING_LAST_SEASON` / `AIRING_THIS_SEASON` / `AIRING_NEXT_SEASON` | `_browser_list_route_paths('airing_*_season')` | `draw_items` (`tvshows`) | Seasonal anime directories with pinned `[Filter...]` (`SpecialSort="top"`) and `Next Page` (`SpecialSort="bottom"`). |
| `TRENDING_*` (`LAST_YEAR`, `THIS_YEAR`, `LAST_SEASON`, `THIS_SEASON`, `ALL_TIME_TRENDING`) | `_browser_list_route_paths('trending_*')` | `draw_items` (`tvshows`) | Trending anime lists across all time horizons. |
| `POPULAR_*` / `VOTED_*` / `FAVOURITES_*` / `TOP_100` | `_browser_list_route_paths('popular_*' \| 'voted_*' \| 'favourites_*' \| 'top_100')` | `draw_items` (`tvshows`) | Popularity, user score, favorites, and Top 100 directories. |
| `GENRES` & `GENRE_*` (19 direct genre routes) | `genres/*`, `genre_action`..`genre_thriller` | `draw_items` (`tvshows`) | Multi-genre tag picker plus 19 direct single-genre catalog routes. |
| `MULTIPAGE_FILTER` / `MULTIPAGE_CLEAR_FILTER` | `multipage_filter*`, `multipage_clear_filter*` | Action (`Container.Refresh`) | Opens `FilterSelect` modal (`filter_select.xml`) or clears active A-Z / Year / Format / Audio filter on any paginated catalog view. |

---

### 1.2 Playback, Scene Jump & Watched-State Routes ([`routes/playback.py`](../plugin.video.otaku.rpdev/resources/lib/routes/playback.py))

| Handler Function | Route Pattern(s) | Mode | Description |
|---|---|---|---|
| `PLAY` | `play/*` (`play/<mal_id>/<episode>`) | Playable (`setResolvedUrl`) | Primary episode playback coordinator. Checks `_try_preresolved_handoff()` first; otherwise invokes `MetaBrowser.get_sources()` (`is_rescrape=True` when `rescrape=true` or `source_select=true`), `SourceSelect` or `Resolver.resolve_silent()` pruning, and `WatchlistPlayer.handle_player()`. |
| `PLAY_MOVIE` | `play_movie/*` (`play_movie/<mal_id>/`) | Playable (`setResolvedUrl`) | Movie/OVA playback coordinator (mirrors `PLAY` pipeline with movie scrapers). |
| `TMDB_HELPER` | `tmdb_helper` | Playable / Directory redirect | External player bridge for `plugin.video.themoviedb.helper`. Resolves `mal_id`/`tmdb_id`/`tvdb_id`/`imdb_id`/`title`+`year` and delegates to `PLAY` or `PLAY_MOVIE`. |
| `PLAYBACK_OPTIONS` | `playback_options/*` | Modal Select Dialog | Opens quick action menu (`Source Select`, `Rescrape & Autoplay`, `Series Profile`, `Inspect Mappings`, `Find Recommendations`, `Find Relations`). |
| `MARKED_AS_WATCHED` / `MARKED_AS_UNWATCHED` / `MARK_PREVIOUS_WATCHED` | `marked_as_watched/*`, `marked_as_unwatched/*`, `mark_previous_watched/*` | Background Action (`RunPlugin`) | Updates watched status locally and across all enabled watchlist flavors (`MAL`, `AniList`, `Kitsu`, `Simkl`) and queues offline failures in `scrobble_retry_queue`. |
| `STEP_SCENE_MARKER` / `SCENE_MARKERS` | `step_scene_marker/*`, `scene_markers` | Active Player Action | Steps forward/backward (`step_scene_marker/next` or `prev`) or opens a chapter/OP/ED picker modal during active playback using `otaku.scene_markers`. |

---

### 1.3 Watchlist, Next Up & Telemetry Routes ([`WatchlistIntegration.py`](../plugin.video.otaku.rpdev/resources/lib/WatchlistIntegration.py))

| Handler Function | Route Pattern(s) | Mode | Description |
|---|---|---|---|
| `WL_LOGIN` / `WL_LOGOUT` | `watchlist_login/*`, `watchlist_logout/*` | Action (`isFolder=False`) | Authenticates (`mal`, `anilist`, `kitsu`, `simkl`) via `WatchlistFlavorAuth` (`wlf_auth_*.xml`) or OAuth device PIN flow, or clears credentials. |
| `WATCHLIST` | `watchlist/*` | `draw_items` (`isFolder=True`) | Renders status buckets (`Next Up`, `Currently Watching`, `Completed`, `On Hold`, `Dropped`, `Plan to Watch`) for a tracker flavor. |
| `NEXT_UP` / `NEXT_UP_PAGES` | `next_up`, `next_up_pages/*` | `draw_items` (`episodes`) | Paginated "Next Up" episode feed across active watchlists (supports home-screen widget embedding). |
| `WATCHLIST_STATUS_TYPE` / `WATCHLIST_STATUS_TYPE_PAGES` | `watchlist_status_type/*`, `watchlist_status_type_pages/*` | `draw_items` (`tvshows`) | Renders shows in a specific status bucket with per-item exception isolation for unrated/unwatched Page 2+ entries. |
| `WATCHLIST_TO_EP` | `watchlist_to_ep/*` | `draw_items` (`episodes`) | Resolves a watchlist show entry directly to its episode directory positioned at `eps_watched`. |
| `CONTEXT_MENU` | `watchlist_manager/*` | Modal Select Dialog | Opens the multi-tracker status, episode progress, and score editor for `<mal_id>`. |
| `PRECACHE_WATCHLIST_NOW` | `precache_watchlist_now` | Background Action | Forces an immediate background sync and metadata pre-cache of active watchlists. |
| `WATCHLIST_TELEMETRY` / `WATCHLIST_DRIFT_AUDITOR` | `watchlist_telemetry`, `watchlist_drift_auditor` | Modal `TextViewerXML` | Displays multi-tracker sync health metrics, scrobble retry queue state, and cross-tracker episode drift audit reports. |

---

### 1.4 Cloud, History, Search, Subtitles & Tools Routes

| Module | Handler Functions & Route Patterns | Description |
|---|---|---|
| [`routes/cloud.py`](../plugin.video.otaku.rpdev/resources/lib/routes/cloud.py) | `MY_CLOUD` (`my_cloud`), `MY_CLOUD_BROWSER` (`my_cloud/*`), `PLAY_CLOUD_FILE` (`play_cloud_file/*`), `CLOUD_CREATE_FOLDER` (`cloud_create_folder/*`), `CLOUD_RENAME_ITEM` (`cloud_rename_item/*`), `CLOUD_MOVE_ITEM` (`cloud_move_item/*`), `DELETE_CLOUD_ITEM` (`delete_cloud_item/*`), `CLOUD_PURGE_STALLED` (`cloud_purge_stalled/*`) | Full debrid cloud file manager (`Real-Debrid`, `AllDebrid`, `Premiumize`, `Debrid-Link`, `TorBox`) with direct video playback and stalled magnet cleanup. |
| [`routes/history.py`](../plugin.video.otaku.rpdev/resources/lib/routes/history.py) | `WATCH_HISTORY` (`watch_history`), `CLEAR_WATCH_HISTORY` (`clear_watch_history`), `CLEAR_LAST_WATCHED` (`clear_last_watched`), `REMOVE_WATCH_HISTORY` (`remove_watch_history/*`) | Local watch history list (`watch_history.json`) and item removal actions. |
| [`routes/search.py`](../plugin.video.otaku.rpdev/resources/lib/routes/search.py) | `SEARCH_MENU` (`search`), `SEARCH_HISTORY` (`search_history/*`), `SEARCH` (`search/*`), `EDIT_SEARCH_ITEM` (`edit_search_item/*`), `REMOVE_SEARCH_ITEM` (`remove_search_item/*`), `CLEAR_SEARCH_HISTORY` (`clear_search_history/*`), `BROWSE_YEAR_MENU` (`browse_year_season`), `BROWSE_YEAR_SEASON` (`browse_year/*`), `BROWSE_YEAR_FILTER` (`browse_year_filter/*`) | Scoped search (`show`, `movie`, `both`) stored in `search.db` plus Year × Season archive browser. |
| [`routes/subtitles.py`](../plugin.video.otaku.rpdev/resources/lib/routes/subtitles.py) | `handle_subtitles_search` (`search_subtitles`, `subtitles/search/*`), `handle_set_kodi_subtitle_service` (`set_kodi_subtitle_service`), `handle_open_subtitle_settings` (`open_subtitle_settings`) | Bridges manual subtitle search into `service.subtitles.otaku.rpdev` and configures Kodi's default TV/Movie subtitle provider via JSON-RPC. |
| [`routes/tools.py`](../plugin.video.otaku.rpdev/resources/lib/routes/tools.py) | `TOOLS_MENU` (`tools`), `SERIES_PROFILE` (`series_profile/*`), `INSPECT_MAPPINGS` (`inspect_mappings/*`), `SELECT_RELEASE_GROUPS` (`select_release_groups/*`), `DOWNLOAD_MANAGER` (`download_manager`), `SORT_SELECT` (`sort_select`), `SOURCE_FILTER` (`source_filter`), `MENU_ORDER` (`menu_order`), `CLEAR_CACHE` (`clear_cache`), `CLEAR_SCRAPERS_CACHE`, `CLEAR_DEBRID_CACHE`, `CLEAR_METADATA_CACHE`, `REFRESH_HIANIME_DOMAINS`, `REBUILD_DATABASE`, `DATABASE_STATS`, `SCRAPER_STATS`, `VACUUM_DATABASES`, `CHECK_DB_INTEGRITY`, `SYSTEM_HEALTH_DIAGNOSTICS`, `SYNC_MAPPINGS`, `IMPORT_SETTINGS`, `EXPORT_SETTINGS`, `SETUP_WIZARD`, `TOGGLE_LANGUAGE_INVOKER`, `TOGGLE_IPV6`, `TOGGLE_HTTP2`, `CLEAN_SETTINGS`, `UI_REVIEW_WINDOW` (`ui_review_window/*`) | Maintenance, diagnostics, per-series profile & multi-select release-group picker, database integrity/vacuum, settings backup/restore, network stack toggles, and WindowXML review harness. |

---

## 2. Companion Add-on Routing (`context.otaku.rpdev` & `service.subtitles.otaku.rpdev`)

### 2.1 `context.otaku.rpdev` 18-Action Dispatch Table ([`context.otaku.rpdev/default.py`](../context.otaku.rpdev/default.py))
Each `<item>` in [`context.otaku.rpdev/addon.xml`](../context.otaku.rpdev/addon.xml) invokes `default.py <action>` (or an `action_<name>.py` thin shim). On external skin widgets (`videodb://`, `library://`, TMDB Helper), `_resolve_widget_mal_id()` resolves the show's `mal_id` via `UniqueID` or local `shows`/`mappings.db` title lookup before dispatching:

| Context Arg (`sys.argv[1]`) | Visibility Property (`Window(10000)`) | Builtin Execution Target |
|---|---|---|
| `playbackoptions` | `context.otaku.rpdev.playbackoptions` | `RunPlugin(plugin://plugin.video.otaku.rpdev/playback_options/<subpath>)` |
| `sourceselect` | `context.otaku.rpdev.sourceselect` | `PlayMedia(plugin://plugin.video.otaku.rpdev/play/<target>?source_select=true&...)` |
| `rescrape` | `context.otaku.rpdev.rescrape` | `PlayMedia(plugin://plugin.video.otaku.rpdev/play/<target>?rescrape=true&...)` |
| `seriesprofile` | `context.otaku.rpdev.seriesprofile` | `RunPlugin(plugin://plugin.video.otaku.rpdev/series_profile/<subpath>)` |
| `watchlist` | `context.otaku.rpdev.watchlist` | `RunPlugin(plugin://plugin.video.otaku.rpdev/watchlist_manager/<subpath>)` |
| `markedaswatched` | `context.otaku.rpdev.markedaswatched` | `RunPlugin(plugin://plugin.video.otaku.rpdev/marked_as_watched/<target>)` |
| `markedasunwatched` | `context.otaku.rpdev.markedasunwatched` | `RunPlugin(plugin://plugin.video.otaku.rpdev/marked_as_unwatched/<target>)` |
| `markpreviouswatched` | `context.otaku.rpdev.markpreviouswatched` | `RunPlugin(plugin://plugin.video.otaku.rpdev/mark_previous_watched/<target>)` |
| `findrecommendations` | `context.otaku.rpdev.findrecommendations` | `Container.Update(plugin://plugin.video.otaku.rpdev/find_recommendations/<subpath>)` |
| `findrelations` | `context.otaku.rpdev.findrelations` | `Container.Update(plugin://plugin.video.otaku.rpdev/find_relations/<subpath>)` |
| `getwatchorder` | `context.otaku.rpdev.getwatchorder` | `Container.Update(plugin://plugin.video.otaku.rpdev/watch_order/<subpath>)` |
| `viewreviews` | `context.otaku.rpdev.viewreviews` | `Container.Update(plugin://plugin.video.otaku.rpdev/anime_reviews/<subpath>)` |
| `viewstatistics` | `context.otaku.rpdev.viewstatistics` | `Container.Update(plugin://plugin.video.otaku.rpdev/anime_statistics/<subpath>)` |
| `fanartselect` | `context.otaku.rpdev.fanartselect` | `Container.Update(plugin://plugin.video.otaku.rpdev/fanart_select/<subpath>)` |
| `inspectmappings` | `context.otaku.rpdev.inspectmappings` | `RunPlugin(plugin://plugin.video.otaku.rpdev/inspect_mappings/<mal_id>)` |
| `manualsubtitles` | `context.otaku.rpdev.manualsubtitles` | `RunPlugin(plugin://plugin.video.otaku.rpdev/search_subtitles)` |
| `deletefromdatabase` | `context.otaku.rpdev.deletefromdatabase` | `RunPlugin(plugin://plugin.video.otaku.rpdev/delete_anime_database/<subpath>)` |
| `logout` / `clearcache` | `context.otaku.rpdev.logout` / `clearcache` | `RunPlugin(plugin://plugin.video.otaku.rpdev/watchlist_logout/<flavor>)` / `clear_cache` |

---

## 3. WindowXML Dialog & 1080i Skin Template Matrix

All custom dialogs inherit from [`BaseWindow` (`windows/base_window.py`)](../plugin.video.otaku.rpdev/resources/lib/windows/base_window.py).

> [!CAUTION]
> **Three Mandatory WindowXML Invariants**:
> 1. **In-Place `ListItem` Mutation**: Never call `self.list_control.reset()` to refresh rows; mutate existing items via `self.list_control.getListItem(idx).setProperty(...)` and trim tail rows with `removeItem(size - 1)` to prevent Kodi C++ focus eviction.
> 2. **Single Event Dispatch**: When `onClick(self, controlID)` is implemented, never handle Action ID `7` (`ACTION_SELECT_ITEM`) or `100` (`ACTION_MOUSE_LEFT_CLICK`) inside `onAction()`; Kodi dispatches `onClick()` automatically.
> 3. **Clean Dialog Teardown**: Never set `self._win_closed = True` before calling `self.close()` (`BaseWindow.close()` short-circuits if `_win_closed` is already `True`), and always `del dlg` inside `try...finally` after `doModal()`.

| Python Controller (`resources/lib/windows/`) | 1080i XML Template(s) (`resources/skins/Default/1080i/`) | Interactive Control IDs | Key Window / ListItem Properties |
|---|---|---|---|
| [`anichart.py:Anichart`](../plugin.video.otaku.rpdev/resources/lib/windows/anichart.py) | `anichart.xml` | `1000` (Anime Grid), `60` (Scrollbar), `2050`/`2051`/`2052` (NF-15 Kodi 22+ Inline Trailer Preview Overlay) | `item.info.title`, `item.info.plot`, `item.info.aired`, `item.art.poster`, `anichart.trailer_active` |
| [`stats_window.py:StatsWindow`](../plugin.video.otaku.rpdev/resources/lib/windows/stats_window.py) | `anime_statistics.xml` | `3001` (Close), `4001`–`4010` (Score Bars 1–10), `4101`–`4110` (Score Labels) | `otaku.stats.total`, status distribution properties |
| [`clear_cache.py:ClearCacheDialog`](../plugin.video.otaku.rpdev/resources/lib/windows/clear_cache.py) | `clear_cache.xml` | `1000` (Cache Tier List), `3001` (Close) | `cache.option_title`, `cache.option_description` |
| [`download_manager.py:DownloadManager`](../plugin.video.otaku.rpdev/resources/lib/windows/download_manager.py) | `download_manager.xml` | `1000` (Queue List), `2000` (Action Panel), `3100` (Clear Completed), `3101` (Close), `17` (Scrollbar) | `item.info.title`, `item.info.status`, `item.info.progress`, `item.info.speed`, `item.info.eta` |
| [`filter_select.py:FilterSelect`](../plugin.video.otaku.rpdev/resources/lib/windows/filter_select.py) | `filter_select.xml` | `1000`/`1111` (A-Z), `2000`/`2222` (Year), `3000`/`3333` (Format), `4000`/`4444` (Status), `5000`/`5555` (Audio), `6000`–`6003` (Apply/Clear/Close) | `label`, `value`, `is_enabled` |
| [`get_sources_window.py:GetSources`](../plugin.video.otaku.rpdev/resources/lib/windows/get_sources_window.py) | `get_sources.xml`, `get_sources_alt.xml` | `1001` (Cancel Button), `2000` (Progress Bar) | `4k_sources`, `1080p_sources`, `720p_sources`, `sd_sources`, `total_sources`, `cached_torrents`, `uncached_torrents`, `cloud_sources`, `embed_sources`, `local_sources`, `remaining_providers_count`, `remaining_providers_list` |
| [`menu_order.py:MenuOrderDialog`](../plugin.video.otaku.rpdev/resources/lib/windows/menu_order.py) | `menu_order.xml` | `1000` (Menu Item List), `3001` (Move Up), `3002` (Move Down), `3003` (Toggle Visibility), `3004` (Reset Defaults), `3005` (Save), `3006` (Cancel) | `menu_title`, `menu_description`, `status_badge`, `is_enabled` |
| [`playing_next.py:PlayingNext`](../plugin.video.otaku.rpdev/resources/lib/windows/playing_next.py) | `playing_next_default.xml`, `_af.xml`, `_af2.xml`, `_ah2.xml`, `_auramod.xml`, `_az.xml`, `_tb.xml` | `3001` / `3000` (Play Now), `3002` / `3012` (Cancel/Close), `3014` (Countdown Progress) | `item.info.title`, `item.info.tvshowtitle`, `item.info.episode`, `item.art.thumb`, `skip_preview` |
| [`skip_intro.py:SkipIntro`](../plugin.video.otaku.rpdev/resources/lib/windows/skip_intro.py) | `skip_intro_default.xml`, `_af.xml`, `_af2.xml`, `_ah2.xml`, `_auramod.xml`, `_az.xml`, `_tb.xml` + `skip_outro_*.xml` | `3001` / `3000` (Skip Segment), `3002` / `3012` (Dismiss), `3003` (Watch Credits) | `otaku.skipintro.label`, `skip_preview` |
| [`still_watching.py:StillWatchingXML`](../plugin.video.otaku.rpdev/resources/lib/windows/still_watching.py) | `still_watching.xml` | `3001` (Continue Watching), `3002` (Stop Playback), `3014` (Progress) | `stillwatching.title`, `stillwatching.prompt` |
| [`progress_dialog.py:Progress_dialog`](../plugin.video.otaku.rpdev/resources/lib/windows/progress_dialog.py) | `progress_dialog.xml` | `3002` (Cancel), `3003` (Copy Code), `3005` (Progress), `4001` (QR Image) | `qr_code`, `otaku.text`, `otaku.heading`, `progress` |
| [`resolver.py:Resolver`](../plugin.video.otaku.rpdev/resources/lib/windows/resolver.py) | `resolver.xml`, `resolver_alt.xml` | `1001` (Cancel Resolution) | `source_provider`, `source_resolution`, `source_size`, `source_info`, `release_title`, `debrid_provider` |
| [`source_select.py:SourceSelect`](../plugin.video.otaku.rpdev/resources/lib/windows/source_select.py) | `source_select.xml`, `source_select_alt.xml` | `1000` (Source List), `1001` (Close), `15`/`17` (Scrollbars) | `source_provider`, `source_type`, `source_resolution`, `source_size`, `source_seeders`, `source_info`, `release_title`, `debrid_provider` |
| [`series_profile.py:SeriesProfileDialog`](../plugin.video.otaku.rpdev/resources/lib/windows/series_profile.py) | `series_profile.xml` | `1000` (11-Row Override List incl. `preferred_group`, `excluded_groups`), `3001` (Edit), `3002`/`3003` (Step), `3004` (Reset), `3005` (Save), `3006` (Cancel) | `series_title`, `series_subtitle`, `series_poster`, `field_key`, `value_badge`, `is_overridden`, `skip_preview` |
| [`settings_backup.py:SettingsBackupDialog`](../plugin.video.otaku.rpdev/resources/lib/windows/settings_backup.py) | `settings_backup.xml` | `1000` (Backup Action List), `3001` (Close) | `backup.header`, `backup.subtitle`, `title`, `description` |
| [`sort_select.py:SortSelect`](../plugin.video.otaku.rpdev/resources/lib/windows/sort_select.py) | `sort_select.xml` | `1000`–`8000` (8 Sort Hierarchy Levels), `9000`–`9007` (Save/Reset/Close) | `max_level`, per-tier sort attribute toggles |
| [`textviewer.py:TextViewerXML`](../plugin.video.otaku.rpdev/resources/lib/windows/textviewer.py) | `textviewer.xml`, `textviewer_1.xml` | `2000` (Close), `2001` (Action), `2060` (Textbox), `2062` (Scrollbar) | `otaku.heading`, `otaku.text`, `otaku.changelog_text`, `otaku.news_text` |
| [`wlf_auth.py:WatchlistFlavorAuth`](../plugin.video.otaku.rpdev/resources/lib/windows/wlf_auth.py) | `wlf_auth_anilist.xml`, `wlf_auth_mal.xml` | `1000`–`1003` (Token/Auth Inputs), `2000` (Authorize), `4000` (Cancel) | `qr_code`, `otaku.service` |
