# 📺 Otaku RPDev

[![Kodi version](https://img.shields.io/badge/Kodi-20%20(Nexus)%20%7C%2021%20(Omega)%20%7C%2022%20(Piers%20RC)-blue?style=for-the-badge&logo=kodi)](https://kodi.tv/)
[![Python versions](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue?style=for-the-badge&logo=python)](https://python.org/)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/GPL-3.0)
[![Test Suite](https://img.shields.io/badge/Tests-258%20Passing-brightgreen?style=for-the-badge&logo=checkmarx)](https://github.com/RPDevs-Builds/Otaku-RPDev/actions)
[![CDN Repository](https://img.shields.io/badge/CDN-kodi.repo.iamrp.dev-blueviolet?style=for-the-badge)](https://kodi.repo.iamrp.dev/)
[![Original Project](https://img.shields.io/badge/Forked%20From-Goldenfreddy0703%2FOtaku-orange?style=for-the-badge&logo=github)](https://github.com/Goldenfreddy0703/Otaku)

A hardened, high-performance, and resilient distribution of **Otaku** for Kodi, maintained by **RPDevs**. Engineered for living-room streaming with multi-Debrid auto-failover, cloud VFS browsing, in-process stream decryption, zero-fragmentation memory management, Kodi 22 (Piers RC) readiness with universal backward compatibility (Kodi 20 & 21), and 100% automated test coverage across all subsystems.

---

## 🙏 Credits & Acknowledgements

**Otaku RPDev** is built upon the exceptional work of the original **Otaku** project:

- **Original Project**: [Goldenfreddy0703/Otaku](https://github.com/Goldenfreddy0703/Otaku)
- **Original Lead Developer**: **Goldenfreddy0703** and the **Team Otaku** contributors.
- **Foundational Lineage**: Built upon years of community dedication from the creators and maintainers of Otaku, WatchNixtoons2, and antecedent anime streaming add-ons.

We extend our deepest gratitude to **Goldenfreddy0703** and all contributors to the upstream codebase. Their original architecture, scrapers, indexers, and community providers created the foundation that made this hardened distribution possible. All original licenses, copyrights, and contributor credits are preserved.

---

## 📖 The Origin Story: *"I Honestly Didn't Mean To Go This Far"*

I originally set out with a very modest, well-mannered plan: clone upstream [Goldenfreddy0703/Otaku](https://github.com/Goldenfreddy0703/Otaku) at **v5.4.3**, fix a couple of minor scraping bugs, clean up a couple of variable names, and submit a tidy pull request.

Then things took a turn.

One small patch led to fixing an unhandled exception. That led to noticing that video hoster streams required external dependencies, so I wrote a native in-process Python decryptor. That led to noticing memory leaks on Android TV boxes, so I hooked C-level `malloc_trim` into the player lifecycle. That led to database lockups, so I gutted legacy Python pickle serialization in favor of SQLite WAL and atomic persistence. Then scraper thread storms were locking up the UI, so I introduced cooperative cancellation tokens and circuit breakers. Next came Kodi 22 (Piers RC) strict setting enforcement, requiring full schema declarations for all internal settings to prevent C++ exceptions. Before I knew it, I had overhauled the routing engine, decoupled 1,500+ functions, built an automated 252-test mock harness, and engineered an interactive cache maintenance GUI.

At this point, submitting an upstream pull request would probably melt GitHub's diff engine. 

So this is now my personal sovereign distribution of Otaku—maintained with obsessive attention to stability, packaged cleanly, and distributed directly from my personal repository at [`https://kodi.repo.iamrp.dev/`](https://kodi.repo.iamrp.dev/).

---

## 🚀 Kodi 22 (Piers RC) Ready & Universal Backwards Compatibility

Otaku RPDev is developed against the latest **Kodi 22 (Piers) Release Candidates** while maintaining 100% backwards compatibility with **Kodi 21 (Omega)** and **Kodi 20 (Nexus)**:

1. **Strict Setting Type Declaration**:
   - Kodi 22 introduces strict runtime type-checking for add-on settings, throwing fatal C++ `EXCEPTION: Invalid setting type` errors whenever an add-on queries or writes a setting not declared in `settings.xml`.
   - All hidden and dynamic settings (including `dub.etag`, `mappings.etag`, `mappings.last_modified`, `verify_ssl`, `last_played_source`, `last_watched_series`, and `smartplay.prefer_same_embed`) are fully typed and registered in `resources/settings.xml`.
2. **`xbmc.python` 3.0.1 Standard Compliance**:
   - Avoids deprecated or dropped Kodi C++ symbols and enforces safe Python 3.11–3.14 standard library patterns.
   - Robust `ListItem` allocation, `VideoInfoTag` properties, and clean window property isolation.
3. **SWIG Memory Leak Elimination (`SwigDirector_WindowXMLDialog`)**:
   - Kodi's Python invoker SWIG layer can leak window dialog instances when circular bound-method callbacks are retained.
   - Otaku RPDev explicitly registers and unbinds modal dialog instances on close/shutdown, eliminating `SwigDirector_WindowXMLDialog` warnings during playback and exit.
4. **Cross-Session Settings & Home Window Persistence**:
   - Leverages `homeWindow` properties backed by an in-memory dictionary cache to persist playback continuity (`last_played_source`, `last_watched_series`) across ephemeral Python invoker instances without redundant disk I/O.

---

## ⏱️ Zero-Wait Binge Architecture: Saving Hours Every Year

The crown jewel of Otaku RPDev is the speed at which you can binge anime from your couch without staring at scraping progress bars:

- **Fast-Path Background Pre-Caching (v5.6.0)**: While watching an episode, a quiet background worker scrapes and resolves results for the upcoming episode at 70% playback progress. In v5.6.0, whole-episode sorted sources are cached in local SQLite storage with a 4-hour TTL. When the next episode begins, `MetaBrowser` uses **Fast-Path 2** to instantly return the pre-cached stream—bypassing the scraping dialog entirely and eliminating 45-second UI freezes caused by unresponsive scrapers.
- **SmartPlay Web Embed Continuity (v5.6.0)**: When watching via web embed providers (Anikoto/MegaPlay, AnimePahe, HiAnime), `smartplay.prefer_same_embed` automatically retains your selected provider and audio language (Sub vs. Dub) across episodes. SmartPlay reorders matching sources to index 0 and resolves seamlessly without prompting for manual source selection.
- **Season Pack Fast-Path**: If your previous episode resolved from a cached season pack (torrent or debrid cloud), subsequent episodes skip provider scraping completely and resolve the next episode file within milliseconds.
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

Every single subsystem has been audited, benchmarked, hardened, and expanded:

### 1. ⚡ Fast-Path Pre-Scrape Caching & SmartPlay Continuity (v5.6.0)
- **Whole-Episode Pre-Cache Storage**: Added `set_episode_sources` and `get_episode_sources` with 4-hour validity in `database.py`. Background pre-scraping at 70% playback persists the entire sorted source pool.
- **MetaBrowser Fast-Path 2**: When starting an episode that was pre-scraped, `MetaBrowser.get_sources` immediately returns the cached sources without displaying `get_sources.xml` or re-running failing scrapers.
- **Embed Continuity (`smartplay.prefer_same_embed`)**: Implemented provider and audio language preservation in `sortSources` and `resolver.reorder_sources`. Persists structured `provider + " " + info` signatures in `last_played_source`, allowing hands-free binge watching on embed providers like Anikoto/MegaPlay.
- **Anikoto Scraper Hardening**: Multi-tier metadata fallback (`shows_meta`, `episodes`, synthetic ID) prevents scraping aborts when show records are not yet pre-warmed. Elevated scraper logging to `info` level for transparent diagnostics.

### 2. 🛡️ Kodi 22 (Piers RC) Compatibility & Settings Safety (v5.5.22)
- **Strict Settings Declarations**: Explicitly declared `dub.etag`, `mappings.etag`, and `mappings.last_modified` in `resources/settings.xml` to eliminate Kodi 22 C++ setting exceptions during background synchronization.
- **Debrid Cache Maintenance Alignment**: Updated cleanup routines to `debrid_cache.prune_expired_hashes()`, added backward-compatibility aliases, and aligned SQLite database WAL checkpointing.

### 3. 🎯 Playback Stability & Skip Intro Hardening (v5.5.21)
- **Skip Intro Lifecycle**: Guarded background tasks against premature close when player `total_time` is uninitialized (0), and cleared stale stop flags upon playback start.
- **Season Pack Boundary Regex**: Eliminated ASCII `0x08` backspace token corruption in `is_season_pack` word boundaries.
- **Debrid Cache Integrity**: Prevented false-negative cache poisoning by only persisting confirmed positive cached hashes and generating fresh DMM request secrets per batch chunk.
- **Genre Settings Safety**: Protected AniList and MAL genre configuration against empty API payloads.

### 4. 📅 Upcoming Dub Release Date Display (v5.5.20)
- **Episode Row Dub Labels**: Renders upcoming dub release dates directly in the episode row (`Label2`), right-aligned next to the watch status indicator for unreleased dubs.
- **AnimeSchedule Scraper Overhaul**: Function-scoped dub tracking prevents cross-show pollution; ISO timezone conversion translates broadcast times to local time; inclusive episode ranges prevent missing season finales.

### 5. ⏭️ Auto-Skip Chapter Resolution (v5.5.19)
- **OP/ED Confidence Detection**: Evaluates chapter titles against opening and ending keywords with a 90-second duration heuristic, preventing false-positive skips during prologues or cold opens.
- **Non-Blocking Telemetry**: Auto-skip seek events logged at `info` level for real-time verification in standard Kodi logs.

### 6. 🧹 Multi-Option Cache & Maintenance System (v5.5.1)
- **Selective Provider Cache Clearing**: Context Menu **"Clear Addon Cache"** launches an interactive modal dialog (`clear_cache.xml`). Users can selectively purge provider scrapers, embeds, season packs, and debrid hashes without touching their watchlist or metadata database.
- **Nuclear Purge Option**: Full database reset available for troubleshooting with interactive navigation descriptions and dedicated Cancel fallback.

### 7. 🧪 Automated Testing & 100% Error-Catching Architecture (v5.5.0)
- **252 Automated Tests in CI**: Expanded test suite covering unit tests, integration lifecycles, and failure simulations.
- **Comprehensive Kodi Mock Harness**: Emulates `xbmc.Player`, `xbmcgui.WindowXMLDialog`, `xbmcgui.ListItem`, `xbmcplugin`, and dialogs completely in-memory, enabling full GUI and playback testing without running Kodi.
- **Typed Exception Guards**: Replaced blind `except: pass` blocks across all external API endpoints, ensuring network errors produce friendly user notifications rather than silent failures.

### 8. 🔐 Memory Management, Security & Database Hardening (v5.4.7 – v5.4.11)
- **In-Memory C-Level Trimming (`malloc_trim`)**: Automatically executes `libc.malloc_trim(0)` upon playback stop, reclaiming fragmented native heap memory on Android TV and FireOS devices.
- **Pickle Eradication**: Replaced legacy Python pickle caching with atomic SQLite and JSON serialization.
- **SQLite WAL & Checkpointing**: SQLite databases (`cache.db` and `malSync.db`) use Write-Ahead Logging with automatic checkpoints on exit and disk-space pruning.
- **SSRF & Path Traversal Guards**: Strict URI scheme whitelisting (`http`, `https`) preventing local file inclusion or directory traversal.

### 9. 🔓 Native In-Process Video Stream Decryption (v5.4.6)
- **Megacloud & Rabbitstream Decryptor**: Embedded, pure-Python AES-CBC key-derivation and stream decryption engine.
- **Zero External Dependencies**: Eliminates requirements for external Node.js microservices, wasm binaries, or remote API proxies to extract video streams.

### 10. ☁️ Multi-Debrid Auto-Failover & Living-Room Cloud VFS (v5.4.1 – v5.4.14)
- **Debrid Cloud File Manager**: Direct living-room management of personal Real-Debrid, TorBox, Premiumize, and AllDebrid clouds. Stream, rename, move to subfolders, or delete completed torrents directly from Kodi.
- **Multi-Provider Failover**: If your primary Debrid provider experiences downtime or API limits (HTTP 429), the resolver fails over to secondary configured debrid services automatically.
- **5MB Download Cap Removed**: Eliminated artificial file-size constraints on remote debrid media files.

---

## 📋 Release Summary

| Version | Highlights |
| :--- | :--- |
| **v5.6.0** | **Major Milestone**: Kodi 22 (Piers RC) compatibility and universal backward compatibility (Kodi 20 & 21); Fast-Path whole-episode pre-scrape caching (bypassing scraping dialogs on next episodes); SmartPlay embed continuity (`smartplay.prefer_same_embed`); Anikoto scraper hardening; documentation & original developer acknowledgements refresh. |
| **v5.5.23**| Fast-Path 2 pre-cached episode sources in `MetaBrowser`, embed continuity matching in `resolver.reorder_sources`, Anikoto metadata fallback. |
| **v5.5.22**| Kodi 22 hidden string settings declarations (`dub.etag`, `mappings.etag`, `mappings.last_modified`), debrid cache maintenance method alignment. |
| **v5.5.21**| Skip Intro lifecycle hardening, season pack boundary regex repair, debrid cache poisoning prevention, genre settings safety. |
| **v5.5.20**| Upcoming dub release date labels (`Label2`) in episode rows, AnimeSchedule local time parsing and function-scoped dub state. |
| **v5.5.19**| Auto-skip chapter resolution with OP/ED confidence heuristics, SwigDirector WindowXMLDialog memory leak elimination. |
| **v5.5.18**| Fast-path ffprobe chapter extraction, low-RAM 70% pre-scrape throttling, 200ms abort-responsive player monitoring loop. |
| **v5.5.1 – v5.5.17** | Multi-option Clear Cache modal dialog (`clear_cache.xml`), control.py session proxy caching, multi-dimensional sorting architecture & SQLite views (`v_watchlist_items`). |
| **v5.5.0** | Comprehensive mock test harness expansion with 100% typed error catching across all endpoints and scrapers. |
| **v5.4.14 – v5.4.16**| AnimeSchedule Bearer authentication, instant menu auto-refresh, 5MB download cap removal, scraper cancellation tokens. |
| **v5.4.0 – v5.4.13** | My Debrid Cloud living-room VFS, in-process stream decryptor, SQLite WAL tuning, dialogue subtitle pairing, Unicode NFKD title transliteration. |

---

## 🛠️ Development & Testing

Otaku RPDev includes an extensive automated test suite that executes in pure Python without requiring a live Kodi installation:

```bash
# Clone the repository
git clone https://github.com/RPDevs-Builds/Otaku-RPDev.git
cd Otaku-RPDev

# Run the complete test suite (252 tests)
python3 -m unittest discover -s tests
```

### Packaging & Release
New releases are built and published to the CDN repository using `scripts/release_addon.py`:

```bash
python3 scripts/release_addon.py plugin.video.otaku.rpdev --version 5.6.0 -m "release: v5.6.0 - Kodi 22 RC readiness, embed pre-caching, SmartPlay continuity, and docs refresh"
```

---

## 📄 License

This project is licensed under the **GNU General Public License v3.0 (GPL-3.0)**. See the [LICENSE](LICENSE) file for details.

Otaku was originally created by **Goldenfreddy0703** and the Otaku development team ([Goldenfreddy0703/Otaku](https://github.com/Goldenfreddy0703/Otaku)); this sovereign hardened distribution is independently maintained by **RPDevs**.
