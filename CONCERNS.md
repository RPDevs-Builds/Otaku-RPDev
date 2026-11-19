# Otaku-RPDev Device Log Concerns

Tracks errors and warnings from the Kodi log on the ONN device (10.13.0.16, Kodi 22.0-RC2, Android ARM 32-bit).
Source: web log viewer `http://10.13.0.16:8081/tail?offset=<N>` (read-only).

## Review cursor (incremental reviews only)

Do **not** re-read the whole log. Start the next review at the saved offset and only classify new lines.

| Field | Value |
|---|---|
| Log session started | 2026-11-19 12:06:38 (Kodi start) |
| Last line reviewed | 2026-11-19 12:25:19.381 |
| **Next review offset** | **75948** (`/tail?offset=75948` / `adb shell cat kodi.log`) |
| Add-on version at last review | v6.2.4 |

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

---

## Open Otaku-RPDev concerns

| ID | Severity | Concern | Total | First seen | Last seen | Trend | Status |
|---|---|---|---|---|---|---|---|
| C-01 | Medium | `AnimePahe: search API returned no data` on every scrape (Cloudflare 403 block) | 76 | 11-15 07:14 | 11-19 12:14 | Repeating | Hardened in v6.2.5 (cooldown circuit breaker) |
| C-02 | Medium | Otaku dialogs cannot focus default list on open: `Control 1100/2000/1000 in window 130xx has been asked to focus, but it can't` | about 105 | 11-15 07:14 | 11-19 12:14 | Repeating | Resolved in v6.2.5 (skins defaultcontrol cleanup) |
| C-03 | Medium | Playback fails to start for an HLS source, with no automatic fail-over to the next source (see C-09) | 2 | 11-15 07:15 | 11-16 02:48 | Not seen in reviews 3-4 | Open |
| C-04 | Low | `Torrentio: No kitsu_id or imdb_id found, skipping` for newly released shows | 2 | 11-15 17:28 | 11-15 17:44 | Not seen in reviews 2-4 | Open |
| C-05 | Low | `clean_settings` re-prunes the same 11 settings on every add-on update (settings are rewritten by Kodi's in-memory copy) | 3 | 11-15 06:43 | 11-15 17:04 | Only on updates | Open |
| C-06 | Low | Directory-load failures: `GetDirectory - Error getting plugin://plugin.video.otaku.rpdev/` plus `plugin://` plus `/tools` | 2 events | 11-15 16:49 | 11-16 02:49 | Low frequency | Open |
| C-07 | Low | HLS probe rejected: `CCurlFile::Stat - <stream>/master.m3u8 Failed: HTTP response code said error(22)` | about 53 | 11-15 14:14 | 11-19 12:14 | Repeating | Open |
| C-08 | Low | `Passing None where a string is expected is deprecated` (a `None` goes to a Kodi API call from an unknown caller) | 2 | 11-15 06:47 | 11-15 16:58 | Not seen in reviews 2-4 | Open |
| C-09 | Medium | HLS proxy failure: `megacloud.animanga.fun/ts-proxy` returns HTTP 502 and the segment download fails 3 times | 1 incident | 11-16 02:48 | 11-16 02:48 | Not seen in reviews 3-4 | Open |
| C-10 | Low | `get_sub: request failed for https://megacloud.animanga.fun/fetch?url=...eng-2.vtt` (logged at info level) | 1 | 11-16 02:48 | 11-16 02:48 | Not seen in reviews 3-4 | Open |
| C-11 | Low | `OpenStream - Unable to create subtitle parser` at the start of a stream | 3 | 11-16 02:48 | 11-16 02:49 | Not seen in reviews 3-4 | Open |
| C-12 | High | Download action crash: `AttributeError: 'NoneType' object has no attribute 'getSelectedPosition'` in `source_select.py:244` (`self.close()` called before position query) | 1 | 11-16 06:36 | 11-16 06:36 | Single occurrence | Resolved in v6.2.5 |
| C-13 | Medium | HiAnime scraper thread freeze: sequential 30s timeouts across 6 dead mirrors freeze scrape pipeline for ~3 minutes before trying fallback | 2 incidents | 11-16 06:34 | 11-19 11:53 | Scraper stalls on dead mirrors | Resolved in v6.2.5 (fast-fail) |
| C-14 | Low | CURL receive error 56: `CCurlFile::CReadState::FillBuffer Failed: Failure when receiving data from the peer(56)` during stream download | 2 | 11-16 09:46 | 11-16 09:56 | Transient network drop | Open |
| C-15 | CRITICAL | Fatal Python callback crash: `TypeError: in method 'ListItem_setArt', argument 2 of type 'XBMCAddon::Properties const &'` in `resolver.py:354`. Prevents playback of movies/episodes when artwork dictionary contains non-strings (lists from `merge_artwork`) | 6 | 11-19 11:53 | 11-19 12:10 | Repeating, crashes playback on affected titles | Resolved in v6.2.5 |

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
