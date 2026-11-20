# Otaku-RPDev Device Log Concerns

Tracks errors and warnings from the Kodi log on the ONN device (10.13.0.16, Kodi 22.0-RC2, Android ARM 32-bit).
Source: web log viewer `http://10.13.0.16:8081/tail?offset=<N>` (read-only).

## Review cursor (incremental reviews only)

Do **not** re-read the whole log. Start the next review at the saved offset and only classify new lines.

| Field | Value |
|---|---|
| Log session started | 2026-11-19 12:06:38 (Kodi start) |
| Last line reviewed | 2026-11-19 22:01:32.350 |
| **Next review offset** | **415056** (`/tail?offset=415056` / `adb shell tail -c +415057 kodi.log`) |
| Add-on version at last review | v6.2.10 (live on device since 2026-11-19 21:16:24) |

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
| 7 | 2026-11-19 15:41 | 15:02 to 15:40 (kodi.log bytes 151158 to 180275) | Incremental ADB review spanning live update to v6.2.7 (15:30:01). Confirmed C-05 zero re-prunes on update; identified C-18 (valid Blood Lad batch torrents dropped by `relevance_gate=0` in `sortSources` due to `+ OVA`, `1-10+OVA Complete`, `BD`, and truncated `[` tags in `isolate_show_title`). |
| 8 | 2026-11-19 16:04 | 15:41 to 16:03 (kodi.log bytes 180276 to 198957) | Incremental ADB review of Blood Lad Ep 8 -> Ep 9 transition under v6.2.7. Caught C-16 EOF callback race (`isPlaying()` flips False before `onPlayBackEnded()` fires, wiping `otaku.preResolved_*`) and C-19 (background pre-scrape running for non-existent Ep 2 of movies / Ep N+1 of season finales). |
| 9 | 2026-11-19 17:45 | 16:03 to 16:25 (kodi.log bytes 198958 to 210963) + live local Kodi 22 & Kodi 21 verification | Full code audit of C-01..C-19 + real-time interactive verification in local Flatpak Kodi 22.0-RC2 (Piers) and Kodi 21.3 (Omega). Graduated C-01..C-05, C-07..C-10, C-12, C-13, C-15..C-19 to Resolved; fixed 3 live-caught Kodi 22 bugs (`mappings.db` readonly checkpoint, `build_playlist` unsorted slicing, `smartplay.preresolve` `getBool` + `total_time=None` + EOF `getTime` guards). |
| 10 | 2026-11-19 22:18 | 16:38 to 22:01 (kodi.log bytes 210964 to 415056) | Incremental web log review spanning live ONN update to **v6.2.10** (21:16:24). Verified **2/2 consecutive live Zero-Wait Pre-Resolved Stream Hits** (`53889` Ep 2 & Ep 3), **0** focus errors, **0** `CCurlFile::Stat`, **0** `Passing None`, **0** `clean_settings` re-prunes, and **0** Python tracebacks under v6.2.10. Pinpointed `C-11` (`source: 1024` external subtitle parser failure specifically on Zero-Wait Ep 2/3 transitions), logged new `C-20` (arc-titled sequel Dual-Audio torrent dropped by `relevance_gate=0` on *Blue Exorcist* `33506`/`53889`), and noted `C-01` 10-min cooldown expiring between 20-min binge episodes. |

---

## Open Otaku-RPDev concerns

| ID | Severity | Concern | Total | First seen | Last seen | Trend | Status |
|---|---|---|---|---|---|---|---|
| C-06 | Low | Directory-load failures: `GetDirectory - Error getting plugin://plugin.video.otaku.rpdev/` plus `plugin://` plus `/tools` | 4 events (3 + 1 pre-update) | 11-15 16:49 | 11-19 21:16 | Only during hot-update unpack | Hardened in v6.2.6 & v6.2.9; 21:16 hit occurred 13s before v6.2.10 unpack (0 post-update); keep watching |
| C-14 | Low | CURL receive error 56: `CCurlFile::CReadState::FillBuffer Failed: Failure when receiving data from the peer(56)` during stream download | 10 (5 + 5 pre-update) | 11-16 09:46 | 11-19 19:03 | Transient CDN network drop (0 on v6.2.10) | External CDN/network transient; Kodi reconnects cleanly; keep watching |

### Details and watch notes

**C-06 Directory-load failures (hot-update unpack window)**
- Hardened in v6.2.6 (non-blocking async changelog dispatch) and v6.2.9 (`control.end_directory()` allows `handle >= 0`). The 4th event at `21:16:11` occurred 13 seconds before Kodi unpacked `v6.2.10` (`21:16:24`), with 0 occurrences after update.

**C-14 CURL receive failure (error 56)**
- Transient TCP/HTTP peer disconnect from upstream streaming CDNs during segment download. 5 occurrences pre-update (`16:53`–`19:03`), 0 under `v6.2.10`. Handled transparently by Kodi's reconnect loop.

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
| R-17 | C-18 Valid batch torrents dropped by `relevance_gate=0` (`Blood Lad` missing torrent sources) | Fixed in v6.2.8. Normalized batch episode ranges, bundled `+ OVA`/`+ Special` extras, unclosed truncated `[` tags, and trailing `Complete`/`Batch`/`BD` markers in `isolate_show_title()` while keeping standalone OVAs/derivatives `<= 40`. |
| R-18 | C-16 Zero-Wait EOF callback race & C-19 movie/season-finale phantom pre-scrape | Fixed in v6.2.8. `keepAlive()` only clears `otaku.preResolved_*` on explicit `_user_stopped_or_errored` or `playList.size() <= 1`, and `_trigger_background_prescrape()` guards against movies and `next_ep > episode_count`. Verified live on Kodi 22 (natural EOF Blood Lad Ep 8 -> Ep 9 Zero-Wait hit). |
| R-19 | C-01 & C-13 Persistent cross-invocation mirror cooldowns & `translate.goog` alt URL join | Fixed in v6.2.9. Persisted `domains._FAILED_MIRRORS` and `ScraperCircuitBreaker` in `Window(10000)`, added `domains.join_url()`, fixed trailing `/` on `translate.goog` alt URLs, and checked `is_mirror_healthy` before `malsync` in `animepahe.py`. Verified live on Kodi 22 (0ms cooldown skip across plugin invocations). |
| R-20 | C-03 & C-09 Failing embed/proxy host cooldown & failover deprioritization | Fixed in v6.2.9. `resolver.py` marks failing embed/direct stream origins via `mark_mirror_failure(..., cooldown=300)` on playback abort and deprioritizes unhealthy hosts across `reorder_sources()`, `remaining`, and `resolve_silent()`. |
| R-21 | C-07 Case-insensitive `Content-Type` MIME hook & `Files.SetFileDetails` plugin-URI guard | Fixed in v6.2.9. Normalized `hook_mimetype` (lowercase + strip `; charset=...`), registered `application/x-mpegurl`, used case-insensitive header lookup in `resolver.py`/`playback.py`, and guarded `Files.SetFileDetails` via `_resolve_resume_target_file()`. Verified 0 `CCurlFile::Stat` errors live on Kodi 21 & 22. |
| R-22 | C-08, C-10 & C-17 Remaining `ListItem` None coercion, VTT `<}` sanitization & HiAnime refreshed-mirror dedup | Fixed in v6.2.9. Coerced `ListItem` label/property inputs in `settings_backup`/`clear_cache`/`filter_select`/`menu_order`, sanitized malformed `<}` VTT tags + warning log in `embed_extractor.get_sub()`, and passed `failed_embed_urls` + `_last_mirror_resolved` in `hianime.py` refreshed-mirrors loop. |
| R-23 | Live Kodi 22 findings: read-only `mappings.db` WAL checkpoint, unsorted `build_playlist()` slicing, `getFirstAired()` deprecation | Fixed in v6.2.9. Removed static read-only `mappingDB` from `checkpoint_databases()`/`vacuum_all_databases()`, sorted `build_playlist()` numerically by episode number, and preferred `getFirstAiredAsW3C()`/`getPremieredAsW3C()`. Verified 0 errors/warnings live on Kodi 21 & 22. |
| R-24 | Live Kodi 22 findings: `smartplay.preresolve` `getBool`, `total_time=None` `TypeError`, and EOF `getTime()` `RuntimeError` guards | Fixed in v6.2.9. Switched `routes/playback.py` to `control.getBool('smartplay.preresolve', default=True)`, guarded `total_time or 0` in `onPlayBackEnded()`/`onPlayBackStopped()`, and wrapped `getTime()`/`getPlayingFile()` in `try...except RuntimeError`. Verified 0 exceptions live on Kodi 21 & 22. |
| R-25 | C-11 `OpenStream - Unable to create subtitle parser` (`source: 1024`) on Zero-Wait episode transitions | Fixed in v6.2.11. Skipped `del_subs()` in `onPlayBackEnded()` when a next playlist item is queued, scoped Zero-Wait temp subtitle filenames with `sub_tag=f"{mal_id}_{episode}"`, and added HTML error-page rejection + BOM/WEBVTT header normalization in `embed_extractor.get_sub()`. Verified live on Kodi 22 (`MAL 53889` Ep 1 -> Ep 2 Zero-Wait opened `source: 1024` via `CDVDSubtitlesLibass` with 0 parser errors). |
| R-26 | C-20 Arc-subtitled sequel Dual-Audio torrents dropped by `relevance_gate=0` & C-01 10-min AnimePahe binge cooldown | Fixed in v6.2.11. Expanded `has_exact_arc_subtitle` in `source_utils.py` to accept `:` subtitles, registered `<Base> Season N` aliases in `pages/__init__.py:sortSources()` when `season >= 2` (retaining `Blue Exorcist S03` while rejecting `S01`), and raised AnimePahe empty-API cooldown to `3600s` (verified live on Kodi 22). |
