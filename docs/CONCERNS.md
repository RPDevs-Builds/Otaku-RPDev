# Otaku-RPDev Device Log Concerns

Tracks errors and warnings from the Kodi log on the ONN device (10.13.0.16, Kodi 22.0-RC2, Android ARM 32-bit).
Source: web log viewer `http://10.13.0.16:8081/tail?offset=<N>` (read-only).

## Review cursor (incremental reviews only)

Do **not** re-read the whole log. Start the next review at the saved offset and only classify new lines.

| Field | Value |
|---|---|
| Log session started | 2026-11-19 12:06:38 (Kodi start) |
| Last line reviewed | 2026-11-19 14:45:53.095 |
| **Next review offset** | **151157** (`/tail?offset=151157` / `adb shell tail -c +151158 kodi.log`) |
| Add-on version at last review | v6.2.6 (live on device since 13:55:58; C-17 fix landing in v6.2.7) |

Notes:
- If Kodi restarts, the log rotates and the offset resets to 0. A review that returns far fewer bytes than the saved offset means a new session, so start from 0 and update the "session started" row.
- Counts below are cumulative across reviews. "Seen" is the last date or time the item appeared.

## Review history

| # | Reviewed | Log range | Scope |
|---|---|---|---|
| 1 | 2026-11-15 23:09 | 06:37 to 23:10 (full session) | Initial baseline review of the whole log |
| 2 | 2026-11-16 03:01 | 23:16 to 03:00 (bytes 622299 to 772676) | Incremental; new and repeating concerns only |
| 3 | 2026-11-16 10:48 | 03:03 to 10:11 (kodi.old.log) & 10:43 to 10:44 (kodi.log) | Incremental review covering session end and restart. Identified C-12 (download AttributeError) & C-13 (HiAnime sequential timeout freeze). |
| 4 | 2026-11-19 12:28 | 11:50 to 12:02 (kodi.old.log) & 12:06 to 12:25 (kodi.log) | Incremental review via direct ADB connection. Identified CRITICAL C-15 (resolver.py ListItem_setArt crash blocking playback) and updated counts. |
| 5 | 2026-11-19 13:14 | 12:30 to 13:10 (kodi.log bytes 75948 to 102635) | Incremental ADB review + full codebase audit. Identified C-16 (Zero-Wait pre-resolved stream property wipe on episode transition) and mapped root causes for C-02 through C-10. |
| 6 | 2026-11-19 14:56 | 13:14 to 14:45 (kodi.log bytes 102636 to 151157) | Incremental ADB review spanning live update to v6.2.6 (13:55:58). Confirmed C-01/C-02/C-04/C-05/C-07/C-15 clean under v6.2.6; identified C-17 (HiAnime 6-mirror redundant loop adding ~22.5s stall on 0-source embeds). |

---

## Open Otaku-RPDev concerns

| ID | Severity | Concern | Total | First seen | Last seen | Trend | Status |
|---|---|---|---|---|---|---|---|
| C-01 | Medium | `AnimePahe: search API returned no data` on every scrape (Cloudflare 403 block) | 80 (78 + 2 pre-update) | 11-15 07:14 | 11-19 13:36 | Downgraded to info in v6.2.6 | Verified in v6.2.6 (13:59 logged at `info`; cooldown circuit breaker active) |
| C-02 | Medium | Otaku dialogs cannot focus default list on open: `Control 1100/2000/1000 in window 130xx has been asked to focus, but it can't` | about 109 (pre-update) | 11-15 07:14 | 11-19 13:42 | Eliminated in v6.2.6 | Verified in v6.2.6 (zero focus errors across 5 dialogs) |
| C-03 | Medium | Playback fails to start for an HLS source, with no automatic fail-over to the next source (see C-09) | 2 | 11-15 07:15 | 11-16 02:48 | Not seen in reviews 3-6 | Resolved in v6.2.6 (30s timeout aborts, fast-fail `OnStop`, cache clear) |
| C-04 | Low | `Torrentio: No kitsu_id or imdb_id found, skipping` for newly released shows | 2 | 11-15 17:28 | 11-15 17:44 | Not seen in reviews 2-6 | Verified in v6.2.6 (downgraded to info log) |
| C-05 | Low | `clean_settings` re-prunes the same 11 settings on every add-on update (settings are rewritten by Kodi's in-memory copy) | 4 | 11-15 06:43 | 11-19 13:56 | Only on updates | Verified in v6.2.6 (pruned cleanly on update; monitor next update for 0 re-prunes) |
| C-06 | Low | Directory-load failures: `GetDirectory - Error getting plugin://plugin.video.otaku.rpdev/` plus `plugin://` plus `/tools` | 3 events | 11-15 16:49 | 11-19 13:56 | Transient during hot-update | Hardened in v6.2.6 (non-blocking async changelog dispatch; monitor outside updates) |
| C-07 | Low | HLS probe rejected: `CCurlFile::Stat - <stream>/master.m3u8 Failed: HTTP response code said error(22)` | about 58 (pre-update) | 11-15 14:14 | 11-19 13:20 | Eliminated in v6.2.6 | Verified in v6.2.6 (zero `CCurlFile::Stat` errors on 13:59 HLS playback) |
| C-08 | Low | `Passing None where a string is expected is deprecated` (a `None` goes to a Kodi API call from an unknown caller) | 2 | 11-15 06:47 | 11-15 16:58 | Not seen in reviews 2-6 | Resolved in v6.2.6 (`BaseWindow`/`Anichart`/`SourceSelect` `setProperty` None & list coercion) |
| C-09 | Medium | HLS proxy failure: `megacloud.animanga.fun/ts-proxy` returns HTTP 502 and the segment download fails 3 times | 1 incident | 11-16 02:48 | 11-16 02:48 | Not seen in reviews 3-6 | Resolved in v6.2.6 (fast-fail `OnStop` triggers automatic failover) |
| C-10 | Low | `get_sub: request failed for https://megacloud.animanga.fun/fetch?url=...eng-2.vtt` (logged at info level) | 1 | 11-16 02:48 | 11-16 02:48 | Not seen in reviews 3-6 | Hardened in v6.2.6 (proxy-to-origin `?url=` / `source_url` fallback) |
| C-11 | Low | `OpenStream - Unable to create subtitle parser` at the start of a stream | 3 | 11-16 02:48 | 11-16 02:49 | Not seen in reviews 3-6 | Open (external subtitles already prioritized in `resolver.py`) |
| C-12 | High | Download action crash: `AttributeError: 'NoneType' object has no attribute 'getSelectedPosition'` in `source_select.py:244` (`self.close()` called before position query) | 1 | 11-16 06:36 | 11-16 06:36 | Single occurrence | Resolved in v6.2.5 |
| C-13 | Medium | HiAnime scraper thread freeze: sequential 30s timeouts across 6 dead mirrors freeze scrape pipeline for ~3 minutes before trying fallback | 2 incidents | 11-16 06:34 | 11-19 11:53 | Scraper stalls on dead mirrors | Resolved in v6.2.5 (fast-fail) |
| C-14 | Low | CURL receive error 56: `CCurlFile::CReadState::FillBuffer Failed: Failure when receiving data from the peer(56)` during stream download | 5 (3 + 2) | 11-16 09:46 | 11-19 14:32 | Transient network drop | Open (CDNs/transient; Kodi reconnects cleanly) |
| C-15 | CRITICAL | Fatal Python callback crash: `TypeError: in method 'ListItem_setArt', argument 2 of type 'XBMCAddon::Properties const &'` in `resolver.py:354`. Prevents playback of movies/episodes when artwork dictionary contains non-strings (lists from `merge_artwork`) | 6 | 11-19 11:53 | 11-19 12:10 | Eliminated | Verified in v6.2.6 (zero exceptions on Blue Exorcist: The Movie) |
| C-16 | High | Zero-Wait pre-resolved stream handoff wiped on natural episode EOF transition (`player.py:585`) & non-callable `int(episode)` passed as `watchlist_update` (`routes/playback.py:226`) | 4 transitions (pre-update) | 11-19 12:36 | 11-19 13:42 | Pending v6.2.6 marathon check | Resolved in v6.2.6 (awaiting first multi-episode marathon under v6.2.6) |
| C-17 | Medium | HiAnime redundant 6-mirror loop on 0-source embeds: healthy mirrors sharing the same catalog/embed URL all retry sequentially (~22.5s scrape stall) | 1 incident (6 mirrors) | 11-19 13:59 | 11-19 13:59 | New in review 6 | Resolved in v6.2.7 |

### Details and recommended remediation

**C-01 AnimePahe search returns no data**
- It fails on every scrape (57 times so far), costing about 1 to 2 s each time. The provider looks permanently down or changed.
- Fix: add a circuit breaker that skips AnimePahe for a few hours after N consecutive empty results. Also re-verify the search endpoint and its headers.

**C-02 Default list cannot take focus**
- Confirmed against the skins: `<defaultcontrol>` is a list that is empty or not yet visible at open time.
  - `resolver.xml` uses 1100.
  - `get_sources.xml` uses 2000.
  - `source_select.xml` uses 1000, and its Python also calls `setFocusId(1000)`.
- Window IDs (13000, 13001, 13002) are assigned dynamically, so they are not tied to a particular dialog. The control ID identifies the dialog.
- Fix: for `resolver` and `get_sources`, point `defaultcontrol` at an always-visible control or remove it. Focus the list only after it has items, for example with `setFocusId` after population.
- Impact is mostly log noise. Remote focus may be briefly missing on open.

**C-03 and C-09 HLS source fails and does not fail over**
- At 02:48 the stream for MAL 49114 episode 11 stalled after repeated HTTP 502 from the `megacloud.animanga.fun` ts-proxy. The user re-opened it. Reusing the pre-scraped sources then produced a stream with no usable video, and the player exited within about 1 s. The user moved on to episode 12, which played.
- Fix:
  - When playback ends within a few seconds of starting and no video stream was opened, treat it as a failed source and automatically try the next source in the list (a "Zero-Wait" fallback).
  - Mark the failing source or proxy host as bad for a short time.
  - Invalidate the pre-scraped source cache for that episode on a playback failure, so a retry does not reuse a dead URL.
- Also log the resolver outcome and the chosen source URL host at error level when an item is "not playable" (the same gap as the 07:15 `play/28121/8` event).

**C-04 Torrentio has no IDs for new shows**
- Expected for brand-new titles. Add a title-based fallback lookup, or downgrade the log level to info.

**C-05 Settings pruned again on every update**
- Kodi holds settings in memory and writes the stale keys back (`multipage.*`, `aniwave.skip*`, `april_fools_day`, `provider.animix`).
- Fix: only log or notify when the pruned set differs from the previous run. Optionally prune at service start before the first settings write.

**C-06 Directory-load failures (unattributed)**
- Events: 11-15 16:49:52 to 16:50:08 and 11-16 02:49:47, about 10 hours apart.
- Both times Kodi tried to list `plugin://plugin.video.otaku.rpdev/` and `plugin://` from a background thread while video was playing, and no Otaku traceback was logged.
- Correction: an earlier note suggested these might coincide with a read-only ADB copy of `cache.db`. The 02:49 occurrence had no ADB activity, so that explanation does not hold.
- This looks like an external client or scheduled scan browsing the add-on tree. Treat it as low risk and keep watching.
- If it recurs, enable debug logging for that minute to identify the caller, and make the add-on root route tolerate a non-interactive listing.

**C-07 HLS HEAD probe rejected**
- Kodi's pre-check on `master.m3u8` gets an HTTP error, but playback proceeds.
- Fix: pass the same `User-Agent` and `Referer` headers on the stream URL (`url|Referer=...&User-Agent=...`), or accept it as harmless.

**C-08 None passed to a Kodi API**
- The caller is unknown because the log is info-level only.
- Fix: coerce Kodi API arguments with `str(x or '')`, and enable debug logging if it recurs.

**C-10 Subtitle fetch failed**
- Subtitles are optional. Add a retry or alternate-host fallback for the proxy `fetch` URL, and log at warning level.

**C-11 Subtitle parser could not be created**
- Kodi could not parse a subtitle stream attached to the HLS manifest (likely an unsupported or segmented WebVTT stream). Playback continues.
- Fix: prefer external `.vtt` or `.srt` subtitle tracks over in-manifest subtitle streams when both exist.

**C-12 Download action crash in source select**
- In `windows/source_select.py` lines 243-244, `self.close()` was executed *before* calling `self.display_list.getSelectedPosition()`. Closing the window nullifies `self.display_list`, raising `AttributeError: 'NoneType' object has no attribute 'getSelectedPosition'`.
- Fix: Use `self.position` (already obtained on line 232: `self.position = self.display_list.getSelectedPosition()`) to extract `source = [self.displayed_sources[self.position]]` before closing.

**C-13 HiAnime scraper thread freeze across dead mirrors**
- HiAnime iterates through mirrors sequentially. When multiple mirrors fail, it attempts up to 3 keyword queries on each dead mirror, each taking ~10s before timing out (total 30s per mirror, freezing the scraper thread for 3 minutes across 6 dead mirrors).
- Fix:
  - If a mirror fails to return any response (`html is None`) on the first search keyword, fail fast and break out of the keyword loop immediately instead of repeating 2 more searches on the same dead mirror.
  - Lower per-request search probe timeout from default 10s to 5s.

**C-14 CURL receive failure (error 56)**
- Transient TCP/HTTP peer disconnect during stream segment download. Handled by Kodi's retry loop.

**C-15 (CRITICAL) ListItem_setArt TypeError crashing playback**
- In `windows/resolver.py:354`, `item.setArt(art)` is called with an `art` dictionary where values contain non-strings (such as single-item lists like `['https://...']` returned by `get_meta.py:merge_artwork` for `poster`, `thumb`, `fanart`, or dicts).
- Kodi C++ SWIG bindings for `ListItem_setArt(Properties const &)` strictly enforce `std::map<std::string, std::string>`. Passing any non-string dictionary value raises `TypeError: in method 'ListItem_setArt', argument 2 of type 'XBMCAddon::Properties const &'` and aborts playback with `Error resolving item. Item '...' is not playable.`
- Reproducible: Caused 6 consecutive playback failures on "Blue Exorcist: The Movie" (MAL ID 11737) on 2026-11-19.
- Fix:
  - Add centralized `control.clean_art_dict(art)` helper that guarantees all dictionary values are non-empty strings, extracts `val[0]` if a list/tuple, and strips any non-string entries.
  - Update `resolver.py`: sanitize `self.image`, ensure `_build_art_dict` unwraps list/tuple entries for all art keys, and sanitize via `clean_art_dict` before `item.setArt`.
  - Update `playback.py:206`: sanitize `params.get('image')` via `clean_art_dict` before `item.setArt`.

**C-16 Zero-Wait pre-resolved stream handoff wipe & invalid scrobble callback**
- During marathon playback (Review #5, Blood Lad MAL 11633 Ep 1 → Ep 2 → Ep 3), background pre-scraping at 70% resolved the next episode (`Player: Zero-Wait direct stream pre-resolved`), yet the natural EOF transition still fell back to `resolver.xml`.
- Root causes:
  1. `ui/player.py:585-588` cleared `otaku.preResolved_*` unconditionally when `keepAlive()` exited after `onPlayBackEnded()`, wiping the properties milliseconds before the next playlist item's `PLAY` route ran.
  2. `routes/playback.py:226` passed `int(episode)` instead of the callable `watchlist_update_episode` function as the 2nd argument (`watchlist_update`) to `WatchlistPlayer.handle_player(...)`, which would raise `TypeError: 'int' object is not callable` upon reaching `watchlist.update.percent`.
- Fix:
  - Track `self._playback_ended` in `WatchlistPlayer`, clear `otaku.preResolved_*` on `onPlayBackStopped()` / `onPlayBackError()` and at `keepAlive()` exit only when `not self._playback_ended` or `playList.size() <= 1`, and guard `callable(self._watchlist_update)` in `_update_watched_progress()`.
  - Pass `watchlist_update_episode` as argument 2 in `routes/playback.py:226`.

**C-17 HiAnime redundant 6-mirror loop on 0-source embeds (~22.5s scrape stall)**
- During Review #6 (Blue Exorcist: The Movie, MAL 11737, dub, 13:59:14–13:59:37), all 6 healthy HiAnime mirrors (`hianime.at`, `hianime.ba`, `hianime.gy`, `hianime.lu`, `hianime.tr`, `hianimetv.bz`) returned the exact same show (`ID: 519`, Score `160`) and the exact same failing embed (`https://zokoanime.video/stream/mal/11737/1/dub` → `No player id in embed page`).
- Because `hianime.py` only broke out of the mirror loop when `sources` was non-empty, a healthy mirror that resolved the catalog/servers cleanly but yielded 0 streams still iterated through all 5 remaining identical mirrors, holding `get_sources` open ~16s past every other scraper.
- Fix:
  - Track `_last_mirror_resolved` in `_scrape_mirror()` (set when the mirror responds cleanly with no catalog match or resolves servers cleanly) and deduplicate `failed_embed_urls` across mirrors.
  - Break out of the mirror loop in `get_sources()` once a healthy mirror responds cleanly with 0 streams, while preserving failover on unreachable/dead mirrors (`ConnectionError`) or broken mirror API endpoints.

---

## Non-Otaku items (informational)

| Severity | Item | Total | Last seen | Recommendation |
|---|---|---|---|---|
| Medium | `service.upnext` raises `AttributeError: cannot modify read-only attribute 'UpNextPlayer.stop_count'` | 4 | 11-15 17:45 | Update or disable Up Next. Otaku has its own Playing Next dialog and the two overlap. Not seen in review 2. |
| Medium | MediaCodec decoder error burst (`dequeueInputBuffer` / `dequeueOutputBuffer failed`, render errors) | about 78 | 11-15 16:44 | Single burst. Check whether it follows a particular stream. Not seen in review 2. |
| Low | `OutputPicture - timeout waiting for buffer` | 60 | 11-16 02:50 | Video render stalls. Often follows a switch of display refresh rate. |
| Low | `JSONRPC: Empty batch call` | 42 | 11-16 02:38 | About every 30 min from an external JSON-RPC client. Not Otaku. |
| Low | Skin `Control 50/52/54/55 in window 10025` cannot focus | about 100 | 11-16 02:48 | Kodi Videos window in the active skin; ignore. |
| Cosmetic | `ParseChildManifest: Cannot detect container type from media url, fallback to TS` | 51 | 11-16 02:48 | Inputstream.adaptive noise for HLS streams. |
| Low | `ActiveAE large audio sync error`, plus CURL receive failures (56 and 33) | 8, 3 | 11-15 13:01 | Single network or audio hiccup. Not seen in review 2. |
| Cosmetic | `CDVDMessageQueue(audio/video)::Put MSGQ_NOT_INITIALIZED` | 3 | 11-16 02:48 | Occurs when a stream fails to open (see C-09). |

---

## Resolved or no longer observed

| ID | Concern | Resolution |
|---|---|---|
| R-01 | Empty This Season and Trending/Popular/Voted/Favourites This Season and This Year lists (MAL/Otaku) | Fixed in v6.2.4 (start-date-only bounds). Confirmed working on the device. |
| R-02 | Page 2+ of catalogue lists not loading | Fixed in v6.2.2 (URL query handling). |
| R-03 | C-15 Fatal Python callback crash `TypeError: in method 'ListItem_setArt'` in `resolver.py:354` | Fixed in v6.2.5. Implemented `control.clean_art_dict(art)` and safe list unwrapping across `_build_art_dict`, `resolver.py`, and `playback.py`. |
| R-04 | C-12 Download context action crash `AttributeError: 'NoneType' object has no attribute 'getSelectedPosition'` | Fixed in v6.2.5. Extracted selected source before `self.close()` in `source_select.py`. |
| R-05 | C-02 Dialog defaultcontrol focus noise across 1080i skins (`Control 1100/2000/1000 ... cannot focus`) | Fixed in v6.2.5. Removed invalid/unfocusable `<defaultcontrol>` tags in `resolver.xml`, `resolver_alt.xml`, `get_sources.xml`, `get_sources_alt.xml`, `source_select.xml`, and `source_select_alt.xml`. |
| R-06 | C-01 AnimePahe 403 search failure warning spam | Hardened in v6.2.5. Integrated with `domains.is_mirror_healthy` failure cooldown and silenced warning log spam. |
| R-07 | C-13 HiAnime scraper thread freeze across dead mirrors | Hardened in v6.2.5. Fast-fail break on first keyword failure avoids wasting 20+ seconds on non-responsive mirrors. |
| R-08 | C-16 Zero-Wait pre-resolved stream property wipe & invalid scrobble callback | Fixed in v6.2.6. Preserved `otaku.preResolved_*` across natural `onPlayBackEnded()` playlist transitions and passed `watchlist_update_episode` in `routes/playback.py`. |
| R-09 | C-07 HLS/DASH `CCurlFile::Stat` HTTP error 22 on Kodi 21/22 | Fixed in v6.2.6. Enabled `setContentLookup(False)` and explicit `setMimeType(...)` in `_DASH_HOOK`/`_HLS_HOOK` across all Kodi versions. |
| R-10 | C-03 & C-09 Playback startup 30s timeout & fast-fail `Player.OnStop` failover | Fixed in v6.2.6. Timeout aborts for failover, `Monitor` tracks `Player.OnPlay` vs prior playback so <2s failures abort promptly, and `clear_episode_sources()` invalidates stale caches. |
| R-11 | C-08 `Passing None where a string is expected` in WindowXML properties | Fixed in v6.2.6. Added defensive `setProperty` overrides in `BaseWindow` and `anichart_window.BaseWindow`, plus list/None guards in `source_select.py` and `anichart.py`. |
| R-12 | C-02 Remaining dynamic-list & grouplist `<defaultcontrol>` focus noise | Fixed in v6.2.6. Removed premature `<defaultcontrol>1000</defaultcontrol>` from `anichart.xml`, `clear_cache.xml`, `download_manager.xml`, `menu_order.xml`, and `settings_backup.xml`, and fixed `wlf_auth_mal.xml` (`1002`). |
| R-13 | C-05 `clean_settings` re-pruning on every add-on update | Fixed in v6.2.6. Reordered `clean_settings()` after `control.setSetting('otaku.version', ...)` in `service.py` and added shutdown teardown prune. |
| R-14 | C-06 Synchronous modal changelog blocking root `GetDirectory` | Hardened in v6.2.6. Gated auto-changelog in `default.py` on `is_addon_visible()` + idle player and dispatched asynchronously via `RunPlugin(.../change_log)`. |
| R-15 | C-04 Torrentio missing IDs warning & C-10 subtitle proxy failure | Fixed/Hardened in v6.2.6. Downgraded Torrentio missing-ID log to `'info'` and added `get_sub()` fallback to `source_url` and `?url=` origin URL. |
| R-16 | C-17 HiAnime redundant 6-mirror loop on 0-source embeds (~22.5s stall) | Fixed in v6.2.7. Short-circuits mirror iteration after a healthy mirror resolves cleanly with 0 streams and deduplicates failed embed URLs while preserving dead-mirror failover. |
