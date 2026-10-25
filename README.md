# 📺 Otaku RPDev

[![Kodi version](https://img.shields.io/badge/Kodi-20%20(Nexus)%20%7C%2021%20(Omega)-blue?style=for-the-badge&logo=kodi)](https://kodi.tv/)
[![Python versions](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue?style=for-the-badge&logo=python)](https://python.org/)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/GPL-3.0)
[![Test Suite](https://img.shields.io/badge/Tests-168%20Passing-brightgreen?style=for-the-badge&logo=checkmarx)](https://github.com/RPDevs-Builds/Otaku-RPDev/actions)
[![CDN Repository](https://img.shields.io/badge/CDN-kodi.repo.iamrp.dev-blueviolet?style=for-the-badge)](https://kodi.repo.iamrp.dev/)

A hardened, high-performance, and resilient distribution of **Otaku** for Kodi, maintained by **RPDevs**. Engineered for living-room streaming with multi-Debrid auto-failover, cloud VFS browsing, in-process decryption, zero-fragmentation memory management, and 100% test coverage across all subsystems.

---

## 📖 The Origin Story: *"I Honestly Didn't Mean To Go This Far"*

I originally set out with a very modest, well-mannered plan: clone upstream [Goldenfreddy0703/Otaku](https://github.com/Goldenfreddy0703/Otaku) at **v5.4.3**, fix a couple of minor scraping bugs, clean up a couple of variable names, and submit a tidy pull request.

Then things took a turn.

One small patch led to fixing an unhandled exception. That led to noticing that video hoster streams required external dependencies, so I wrote a native in-process Python decryptor. That led to noticing memory leaks on Android TV boxes, so I hooked C-level `malloc_trim` into the player lifecycle. That led to database lockups, so I gutted legacy Python pickle serialization in favor of SQLite WAL and atomic persistence. Then scraper thread storms were locking up the UI, so I introduced cooperative cancellation tokens and circuit breakers. Before I knew it, I had overhauled the routing engine, decoupled 1,500+ functions, built an automated 168-test mock harness, and engineered an interactive cache maintenance GUI.

At this stage, submitting an upstream pull request would probably melt GitHub's diff engine. 

So this is now my personal sovereign version of Otaku—maintained with obsessive attention to stability, packaged cleanly, and distributed directly from my personal repository at [`https://kodi.repo.iamrp.dev/`](https://kodi.repo.iamrp.dev/).

---

## ⏱️ Zero-Wait Binge Architecture: Saving Hours Every Year

The crown jewel of Otaku RPDev is the speed at which you can binge anime from your couch without staring at scraping progress bars:

- **Background Source Pre-Caching**: While watching an episode, a quiet background worker pre-warms and resolves scraper results for the upcoming episode at 70% playback progress. When the credits roll or you click "Next", playback begins instantaneously—zero scraping dialogs, zero waiting.
- **Multi-Tier Source & Debrid Hash Caching**: Scraped torrents, embed links, season pack file listings, and cached Debrid availability hashes are stored in local SQLite cache. Selecting an episode you've browsed or re-watching a season starts instantly.
- **SQL-Level Watchlist Pagification**: Rather than loading massive watchlists of 1,000+ shows into Python memory on every click, watchlists (AniList, MyAnimeList, Kitsu, Simkl) are sliced and paginated directly at the database engine level with instant "Next Up" derivation.
- **SQLite MMAP & WAL Persistence**: Memory-mapped I/O and Write-Ahead Logging eliminate database lockups and disk bottlenecks, shaving off 10–20 seconds per episode that easily adds up to hours of saved time across a year of viewing.

---

## 📥 Installation & Automatic Updates

To receive automatic over-the-air updates, install via the official **RPDevs Kodi Repository**:

### Quick Setup via Kodi File Manager
1. Launch **Kodi**, navigate to **Settings (Gear Icon) → File Manager → Add source**.
2. Select `<None>` and enter the exact URL:
   ```
   https://kodi.repo.iamrp.dev/
   ```
3. Enter a name for the media source (e.g., `RPDev Repo`) and click **OK**.
4. Go back to Kodi Home, navigate to **Settings → Add-ons → Install from zip file**.
5. Select `RPDev Repo` and click **`repository.rpdevs-1.0.2.zip`**.
6. Once the repository add-on installs, navigate to:
   **Install from repository → RPDevs Add-on Repository → Video add-ons → Otaku RPDev → Install**.

All future updates (including scraper hotfixes and performance enhancements) will download automatically through Kodi's standard add-on update cycle.

---

## ⚡ What Changed Since Upstream v5.4.3?

Every single subsystem has been audited, benchmarked, hardened, and expanded. Here is a domain-by-domain overview of the enhancements introduced between **v5.4.3** and **v5.5.1**:

### 1. 🧹 Multi-Option Cache & Maintenance System (v5.5.1)
- **Selective Provider Cache Clearing**: When rescanning an anime for fresh embeds and torrents, users no longer have to wipe their entire metadata database or watchlist cache. The Context Menu option **"Clear Addon Cache"** opens a dedicated modal dialog (`clear_cache.xml`).
- **Interactive Descriptions**: As you navigate between **Provider Cache** (torrents, embeds, season packs, debrid hashes) and **All Cache & Database** (total nuclear reset), the description card dynamically explains the exact scope and consequences of each operation.
- **Remote & Keyboard Friendly**: Full support for D-pad navigation, Cancel button fallback, and ESC/Back dismissal.

### 2. 🧪 Automated Testing & 100% Error-Catching Architecture (v5.5.0)
- **168 Automated Tests in CI**: Expanded test suite spanning unit tests, integration lifecycles, and failure simulations.
- **Comprehensive Kodi Mock Harness**: Emulates `xbmc.Player`, `xbmcgui.WindowXMLDialog`, `xbmcgui.ListItem`, `xbmcplugin`, and dialogs completely in-memory, enabling full GUI and playback testing without running Kodi.
- **Typed Exception Guards**: Eliminated blind `except: pass` blocks across all external API endpoints (AniList, MyAnimeList, Kitsu, Simkl, MDBList, AniDB), ensuring network errors produce friendly user notifications rather than silent failures or lockups.

### 3. 🔐 Memory Management, Security & Database Hardening (v5.4.7 – v5.4.11)
- **In-Memory C-Level Trimming (`malloc_trim`)**: On Android TV and embedded devices (FireStick, Chromecast with Google TV, Onn boxes), playback threads often leave fragmented native heap memory. Otaku RPDev triggers `libc.malloc_trim(0)` upon playback stop, keeping memory usage minimal.
- **Pickle Eradication**: All legacy Python pickle caching was scrubbed in favor of atomic SQLite and JSON serialization, preventing deserialization vulnerabilities and database corruptions.
- **SQLite WAL & Checkpointing**: SQLite databases (`cache.db` and `malSync.db`) use Write-Ahead Logging (WAL) with automatic checkpoints on exit and disk-space pruning to avoid bloat.
- **SSRF & Path Traversal Guards**: Strict URI scheme whitelisting (`http`, `https`) and sanitization preventing local file inclusion or directory traversal.

### 4. 🚀 High-Performance Concurrency & Scraper Circuit Breakers (v5.4.7 – v5.4.14)
- **Cooperative Cancellation (`self.canceled`)**: When a user selects a source or hits Back during a search, background worker threads terminate immediately rather than wasting bandwidth and CPU cycles in the background.
- **Scraper Circuit Breaker**: If a provider or site goes offline or changes its Cloudflare challenge, Otaku RPDev detects consecutive failures and trips a cooldown timer, preventing scraping freezes.
- **Unicode NFKD Transliteration**: Japanese macrons, romaji variants, and stylized unicode symbols in anime titles are transliterated automatically, dramatically improving torrent and embed match rates.

### 5. 🔓 Native In-Process Video Stream Decryption (v5.4.6)
- **Megacloud & Rabbitstream Decryptor**: Embedded, pure-Python AES-CBC key-derivation and stream decryption engine.
- **Zero External Dependencies**: Eliminates requirements for external Node.js microservices, wasm binaries, or remote API proxies to extract video streams.

### 6. ☁️ Multi-Debrid Auto-Failover & Living-Room Cloud VFS (v5.4.1 – v5.4.14)
- **Debrid Cloud File Manager**: Direct living-room management of your personal Real-Debrid, TorBox, Premiumize, and AllDebrid clouds. Stream, rename, move to subfolders, or delete completed torrents directly from Kodi.
- **Multi-Provider Failover**: If your primary Debrid provider experiences downtime or API limits (HTTP 429), the resolver fails over to secondary configured debrid services automatically.
- **5MB Download Cap Removed**: Eliminated artificial file-size constraints on remote debrid downloads.

### 7. 🎧 Intelligent Audio & Subtitle Pairing (v5.4.9 – v5.4.12)
- **Dialogue vs. Signs/Songs Detection**: Distinguishes full dialogue English subtitle tracks from "forced" or "songs & signs" tracks by parsing MKV track titles and ASS/SSA script headers.
- **Automated Dub/Sub Selection**: Intelligently matches your audio language preference (Japanese vs. English) with the correct companion subtitle stream on playback launch.

### 8. 🎨 Living-Room UX & UI Polish (v5.4.13 – v5.4.16)
- **Instant Menu Auto-Refresh**: Changing your main menu layout in Add-on Settings immediately updates the root directory without requiring a Kodi restart or manual container refresh.
- **AnimeSchedule Bearer Integration**: Fixed calendar enrichment headers to support authenticated schedule requests.
- **Clean Skin Rendering**: Normalized animation studio textures and applied safety guards across `playing_next.py`, `source_select.py`, and `textviewer.py`, guaranteeing zero C++ skin exceptions on all platforms.

### 9. 🖱️ Comprehensive Context Menu Suite (`context.otaku.rpdev` v1.0.40)
- **Interactive Multi-Option Cache Purge**: Selecting **"Clear Addon Cache"** launches the new `clear_cache.xml` modal dialog, allowing users to choose between a selective Provider Cache clean rescan or a full database reset with dynamic descriptions.
- **Bulk Progress Sync ("Mark Episodes Up To Here as Watched")**: One-click bulk sync for anime seasons, marking all prior episodes as watched both locally and across configured remote watchlists (AniList, MyAnimeList, Kitsu, Simkl).
- **Normalized Movie & Episode Watched Routing**: Re-engineered `_extract_watch_target` to defensively parse `/mal_id/episode` targets across all playback schemes (`play_movie`, `play_oot`, `play_al`, `play_mal`, `watchlist_to_ep`), eliminating index errors.
- **Lossless Rescrape & Source Selection**: Preserves and forwards full video info tags, artwork properties, and resume timestamps when forcing a rescrape or manual source selection.
- **Direct Database Management & Discovery**: Instantly delete cached shows/episodes from local storage, open Watchlist Manager, customize per-show fanart, or trigger deep relations, recommendations, watch order, and statistics directly from any highlighted item.

---

## 📋 Release Summary

| Version | Highlights |
| :--- | :--- |
| **v5.5.1** | Interactive multi-option Clear Cache modal dialog (`clear_cache.xml`) with dynamic descriptions, dedicated Cancel button, selective Provider Cache vs All Cache & DB, news & README overhaul. |
| **v5.5.0** | Comprehensive mock test harness expansion (168 tests) with 100% typed error catching across all endpoints, debrid resolvers, scrapers, and watchlist flavors. |
| **v5.4.16**| AnimeSchedule Bearer authentication, non-blocking changelog, ghost trakt setting cleanup, studio texture normalization & UI guards. |
| **v5.4.15**| Instant targeted main menu auto-refresh upon saving menu customization settings. |
| **v5.4.14**| 5MB download cap removal, scraper cancellation tokens, debrid thread join timeout, ROWID-based search history. |
| **v5.4.13**| Streamlined Menu Customization and Watchlist settings, Unicode NFKD title transliteration, SQLite cache index. |
| **v5.4.12**| Pre-compiled regex constants across all scrapers, scraper circuit breaker, artwork cache purge, .ass subtitle detection, Debrid HTTP 429 backoff. |
| **v5.4.11**| Atomic persistence engine, SQLite WAL truncate, SSRF scheme validation, ETag 304 conditional updates, multi-Debrid auto-failover. |
| **v5.4.10**| Standards, resource management, and security hardening against path traversal. |
| **v5.4.9** | Intelligent full dialogue subtitle pairing, signs/songs filtering, and automated dub selection. |
| **v5.4.8** | Stalled torrent cleaner, scraper health CI, dynamic domains, and pickle scrub. |
| **v5.4.7** | Token sanitization in debug logs, `malloc_trim` heap cleanup, scraper concurrency bounds. |
| **v5.4.6** | Pure Python in-process Megacloud & Rabbitstream decryptor (zero external dependencies). |
| **v5.4.4 - v5.4.5** | Resolver NameError fixes, Skip Intro cold-open & EBML chapter reader, browser modularization. |
| **v5.4.0 - v5.4.3** | My Debrid Cloud living-room VFS (delete, rename, folder creation), SQLite MMAP & WAL tuning, countdown airing badges, spoiler blur. |

---

## 🛠️ Development & Testing

Otaku RPDev includes an extensive automated test suite that executes in pure Python without requiring a live Kodi installation:

```bash
# Clone the repository
git clone https://github.com/RPDevs-Builds/Otaku-RPDev.git
cd Otaku-RPDev

# Run the complete test suite
python3 -m unittest discover -s tests
```

### Packaging & Release
New releases are built and synced to the local CDN using `scripts/release_addon.py`:

```bash
python3 scripts/release_addon.py plugin.video.otaku.rpdev --version 5.5.1 -m "Multi-option Clear Cache dialog, news.txt and README overhaul"
```

---

## 📄 License

This project is licensed under the **GNU General Public License v3.0 (GPL-3.0)**. See the [LICENSE](LICENSE) file for details.
Otaku was originally created by the Otaku development team; this fork is independently maintained by **RPDevs**.
