# Otaku-RPDev End-User Configuration Guide & Best Practices

Welcome to the **Otaku-RPDev Configuration Guide**. This handbook provides clear explanations for all 12 settings categories, tuned hardware presets, and safety guidelines for advanced tuning items to help you achieve optimal performance and prevent broken configurations.

---

## Table of Contents
1. [Settings Architecture Overview](#1-settings-architecture-overview)
2. [Quick-Start Hardware Presets](#2-quick-start-hardware-presets)
   - [Low-RAM / Streaming Stick Preset (FireStick, Onn TV, 1GB–2GB RAM)](#low-ram--streaming-stick-preset-firestick-onn-tv-1gb2gb-ram)
   - [High-Performance / Power User Preset (Nvidia Shield Pro, PC, 4GB+ RAM)](#high-performance--power-user-preset-nvidia-shield-pro-pc-4gb-ram)
3. [Category-by-Category Configuration Breakdown](#3-category-by-category-configuration-breakdown)
   - [Category 1: General](#category-1-general)
   - [Category 2: Providers](#category-2-providers)
   - [Category 3: Scraping](#category-3-scraping)
   - [Category 4: Cache & SQLite Tuning](#category-4-cache--sqlite-tuning)
   - [Category 5: Playback & SmartPlay](#category-5-playback--smartplay)
   - [Category 6: Subtitles (Embedded & External)](#category-6-subtitles-embedded--external)
   - [Category 7: Sort and Filter](#category-7-sort-and-filter)
   - [Category 8: Accounts (Debrid & Indexers)](#category-8-accounts-debrid--indexers)
   - [Category 9: Watchlist (Sync & Trackers)](#category-9-watchlist-sync--trackers)
   - [Category 10: Menu Customization](#category-10-menu-customization)
   - [Category 11: Context Menu Customization](#category-11-context-menu-customization)
   - [Category 12: Maintenance, Diagnostics & Storage](#category-12-maintenance-diagnostics--storage)
4. [Advanced Tuning Danger Zones (How Not to Break Your Setup)](#4-advanced-tuning-danger-zones-how-not-to-break-your-setup)
   - [SQLite PRAGMAs: Cache, MMAP & Memory Storage](#sqlite-pragmas-cache-mmap--memory-storage)
   - [CPython Language Invoker (Re-use Language Invoker)](#cpython-language-invoker-re-use-language-invoker)
   - [Custom View IDs](#custom-view-ids)
   - [Stream Size Limits vs. Missing Sources](#stream-size-limits-vs-missing-sources)
   - [Scraper Concurrency & Timeouts](#scraper-concurrency--timeouts)
   - [Data Recovery: Database Rebuild vs. Factory Reset](#data-recovery-database-rebuild-vs-factory-reset)
5. [Troubleshooting & Emergency Recovery](#5-troubleshooting--emergency-recovery)

---

## 1. Settings Architecture Overview

The Otaku-RPDev configuration interface is organized into **12 dedicated, domain-specific categories**:

```
├── 1. General               ── Addon startup, title formatting, view styles, artwork, and widgets
├── 2. Providers             ── Torrent trackers, Usenet indexers, and direct embed hosters
├── 3. Scraping              ── Scraper concurrency, timeouts, cloud filters, and local media
├── 4. Cache                 ── TTL lifetimes, SQLite performance PRAGMAs, and selective purges
├── 5. Playback              ── SmartPlay, audio track preferences, chapter marks, intro/outro skipping
├── 6. Subtitles             ── Unified subtitle engine: auto-download, embedded track matching, APIs
├── 7. Sort and Filter       ── Content catalog filters (year, season, format) + stream quality filters
├── 8. Accounts              ── Debrid authorization (Real-Debrid, Premiumize, TorBox, AllDebrid, etc.)
├── 9. Watchlist             ── Cloud sync (AniList, Kitsu, MyAnimeList, Simkl, Trakt) and pagination
├── 10. Menu Customization   ── Enable or disable main menu and category submenus
├── 11. Context Menu         ── Tailor right-click / context menu actions across media items
└── 12. Maintenance          ── Database diagnostics, storage compacting, downloads, solvers, backups
```

---

## 2. Quick-Start Hardware Presets

### Low-RAM / Streaming Stick Preset (FireStick, Onn TV, 1GB–2GB RAM)
For media sticks and low-memory Android TV devices where background memory pressure or Kodi crashes can occur:

| Setting Location | Setting Name | Recommended Value | Reason |
| :--- | :--- | :--- | :--- |
| **Maintenance -> Playback Helpers** | CPython Language Invoker | **Disabled** | Drops memory usage between navigation runs, preventing OS low-memory kills. |
| **Cache -> SQLite PRAGMAs** | Cache Size (MB) | `16 MB` | Prevents SQLite page cache from consuming excessive heap. |
| **Cache -> SQLite PRAGMAs** | MMAP Size (MB) | `0 MB` (Disabled) | Avoids virtual memory fragmentation on 32-bit Android runtimes. |
| **Cache -> SQLite PRAGMAs** | Temp Store in RAM | **Disabled** | Stores temporary sort tables on disk rather than RAM. |
| **Scraping -> Scraper Tuning** | Concurrency Workers | `4` to `6` | Prevents network thread exhaustion on weak Wi-Fi chips. |
| **Scraping -> Scraper Tuning** | Timeout | `15 seconds` | Gives slow network stacks ample time to resolve streams. |
| **General -> Artwork** | Fanart Limit | `2` to `3` | Reduces background image caching overhead. |
| **Watchlist -> General Sync** | Enable Watchlist Paging | **Enabled** | Loads 20–30 items at a time instead of 500+ items at once. |
| **Watchlist -> General Sync** | Per Page Watchlist View | `20` | Keeps list views snappy and scrolling smooth. |

---

### High-Performance / Power User Preset (Nvidia Shield Pro, PC, 4GB+ RAM)
For dedicated boxes, HTPCs, and mini-PCs with ample RAM and high-speed broadband:

| Setting Location | Setting Name | Recommended Value | Reason |
| :--- | :--- | :--- | :--- |
| **Maintenance -> Playback Helpers** | CPython Language Invoker | **Enabled** | Keeps Python hot in memory for instantaneous directory rendering. |
| **Cache -> SQLite PRAGMAs** | Cache Size (MB) | `64 MB` to `128 MB` | Ultra-fast database queries for massive catalogs. |
| **Cache -> SQLite PRAGMAs** | MMAP Size (MB) | `64 MB` to `128 MB` | Memory-mapped I/O eliminates kernel read calls for SQLite. |
| **Cache -> SQLite PRAGMAs** | Temp Store in RAM | **Enabled** | Indexes and sorting tables are generated directly in memory. |
| **Scraping -> Scraper Tuning** | Concurrency Workers | `10` to `12` | Scrapes all providers in parallel in under 3 seconds. |
| **Scraping -> Scraper Tuning** | Timeout | `10 seconds` | Fails fast on unresponsive mirrors. |
| **General -> Artwork** | Fanart Limit | `5` to `10` | Full rotating background artwork gallery per show. |
| **Watchlist -> General Sync** | Prefetch Metadata | **Enabled** | Background-caches next episodes for instant playback initiation. |

---

## 3. Category-by-Category Configuration Breakdown

### Category 1: General
- **Setup Wizard & Changelog**: Re-run the initial onboarding wizard at any time. Enable *Show Changelog every update* to see new features, bug fixes, and security patches whenever Otaku updates.
- **Titles & Display**: Choose between **English** (e.g., *Attack on Titan*) and **Romaji** (e.g., *Shingeki no Kyojin*). Enabling *Hide Unaired Episodes* prevents unfinished future schedule slots from cluttering season views.
- **View Types & Custom View IDs**: By default, Otaku selects Kodi's native list or poster views. If your skin supports specific view numeric IDs (e.g., Arctic Horizon, Pellucid, Aura), enable *Enable Custom View IDs* and enter your skin's container ID numbers.
- **Artwork & Styling**: Customize studio logos (white, coloured, or none), select preferred artwork providers (Fanart-TV, TMDb, TVDB), and adjust the **Fanart Limit** slider.

### Category 2: Providers
Configure your scrape sources:
- **Torrents / Debrid Providers**: Nyaa, Nyaa Alt, AnimeTosho, AnimeTosho Alt, NekoBT, Bitsearch, ThePirateBay, and Torrentio. (Torrentio includes an advanced configuration string for custom filters).
- **Usenet**: Easynews integration (requires Easynews account authorized in Accounts).
- **Direct Embed Providers**: Anikoto, AnimePahe, AnimePahe Alt, Animix, HiAnime, and WatchNixtoons2. HiAnime supports dynamic domain switching.

### Category 3: Scraping
- **Auto Try Next Source**: If a chosen stream fails or disconnects during playback start, Otaku will automatically fall back to the next best source without user intervention.
- **Cloud Inspection**: When using Debrid providers, cloud inspection verifies whether torrent contents match the requested season and episode before presenting them in the source list.
- **Local Media Folder**: Point Otaku to a local NAS or hard drive directory to merge your offline anime collection seamlessly with streamed sources.

### Category 4: Cache & SQLite Tuning
- **TTLs (Time-To-Live)**: Control how long scrapers, torrent hashes, metadata, and airing calendars remain in cache before querying APIs again.
- **SQLite Performance PRAGMAs**: Fine-tune the local SQLite database caching engine (`cache_size_mb`, `mmap_size_mb`, `synchronous`, `temp_store_ram`).
- **Selective Cache Purging**: Selectively purge scrapers, debrid hashes, or metadata without wiping watch history or credentials.

### Category 5: Playback & SmartPlay
- **SmartPlay**: Automatically plays the next episode upon completion, matches stream quality across episodes, and prefers matching embed servers for continuity.
- **Audio Stream Selection**: Specify whether your primary audio preference is Japanese, English Dub, or your system Kodi default language.
- **Auto-Skip (AniSkip)**: Seamlessly skips openings (OP) and endings (ED) using community timestamps from AniSkip. You can set intro/outro offsets (e.g., 2-second buffer) and toggle auto-skip vs. confirmation notification.
- **Chapter Markers**: Supports `ffprobe` chapter detection for local files and direct streams.

### Category 6: Subtitles (Embedded & External)
- **Subtitle Engine**: Automatically detects character encoding (`use_chardet`) to eliminate garbled text on international tracks. Set auto-download triggers, request timeouts (default: 8s), and preference for SDH (Deaf/Hard-of-Hearing) or Forced tracks.
- **Embedded Track Auto-Selection**: Automatically activates internal subtitle tracks matching your language. Configure keyword patterns (e.g., `dialogue`, `signs`, `full`) to prioritize specific release group styles. Enable *Dub Audio Subtitles* if you want subtitles active while watching English dubs.
- **External Subtitle Providers**: Built-in, direct integration with OpenSubtitles, SubDL, SubSource, Podnadpisi, BSPlayer, and Addic7ed without requiring secondary external addons.

### Category 7: Sort and Filter
- **Content Catalog Filters**: Filter browse and search directories by release year, broadcast season (Winter, Spring, Summer, Fall), media format (TV, Movie, OVA, ONA, Special), airing status, age rating (PG-13, R-17+), and country of origin.
- **Adult (18+) Filter**: Toggles adult / NSFW listings in search queries. Keep disabled for family-friendly media setups.
- **Source Resolution & Size Limits**: Limit streams by maximum and minimum resolution (4K, 1080p, 720p, SD) and set maximum download file sizes for movies and episodes (GB limits).
- **Source Priority**: Sort sources by Quality, Provider, Seeds, or Debrid cache status.
- **Release Title Keyword Filters**: Include or exclude specific release groups, codecs (e.g., `HEVC`, `AV1`), or audio profiles (`FLAC`, `AAC`) using 5 customizable filter rules.

### Category 8: Accounts
Connect and manage third-party service credentials:
- **Debrid Providers**: Real-Debrid, Premiumize, AllDebrid, Debrid-Link, TorBox, EasyDebrid.
- **Usenet**: Easynews.
- Uses OAuth device authentication where available—never stores plaintext passwords when token authentication is supported.

### Category 9: Watchlist
Connect personal anime tracking accounts:
- Supports **AniList**, **Kitsu**, **MyAnimeList (MAL)**, **Simkl**, and **Trakt**.
- **Startup Sync**: Automatically synchronize watched status and progress on Kodi launch.
- **Pagination & Performance**: For accounts with 500+ anime titles, enable *Watchlist Paging* and set *Per Page* (20–40) to prevent slow directory loads.
- **Episode Update Check**: Configures how often Otaku contacts trackers for new episode releases.

### Category 10 & 11: Menu & Context Customization
Toggle top-level menu categories (Movies, TV Shows, OVAs, ONAs, Airing Calendars) and tailor context menu options (Find Recommendations, Rescrape, Source Select, Mark as Watched, Clear Cache) to streamline navigation.

### Category 12: Maintenance, Diagnostics & Storage
- **Database Diagnostics**: Run SQLite PRAGMA `integrity_check`, inspect table size metrics, view scraper hit rates, and run SQLite `VACUUM` to compact storage and recover deleted record space.
- **Data Recovery**: View changelog, clear search history, rebuild database schema, and perform a factory reset.
- **Downloads & Local Storage**: Configure the local download folder path and launch the built-in background Download Manager.
- **Solvers**: Configure Flaresolverr or Megacloud solver URLs to bypass Cloudflare turnstile protection on web scrapers.
- **Backup & Restore**: Export your entire Otaku configuration (accounts, preferences, custom filters) to a `.json` backup file or restore it onto another device.

---

## 4. Advanced Tuning Danger Zones (How Not to Break Your Setup)

> [!WARNING]
> Incorrect configuration in these areas can cause severe slowdowns, Kodi crashes, or missing streams. Read these guidelines carefully before modifying advanced settings.

### SQLite PRAGMAs: Cache, MMAP & Memory Storage
Located under: `Cache -> SQLite Performance PRAGMAs`

1. **`db.sqlite.mmap_size_mb` (Memory-Mapped I/O)**:
   - *Safe Values*: `0` (Disabled) on FireSticks / 1GB RAM devices; `64` to `128` on Shield / PC.
   - *Danger*: Setting MMAP to 256MB+ on a 32-bit Android streaming stick will cause memory allocation failures (`std::bad_alloc`) and crash Kodi to the home screen.
2. **`db.sqlite.temp_store_ram` (In-Memory Temp Store)**:
   - *Safe Values*: `false` (Disk) on low-end devices; `true` on Shield/PC.
   - *Danger*: When enabled on devices with <2GB RAM, sorting a massive 2,000-item watchlist can exhaust available process RAM.
3. **`db.sqlite.synchronous` (Disk Sync Mode)**:
   - *Default*: `NORMAL`.
   - *Danger*: Setting this to `OFF` can corrupt your watchlist database if your device suffers a sudden power loss or Kodi is force-closed during a write.

---

### CPython Language Invoker (Re-use Language Invoker)
Located under: `Maintenance -> Playback Helpers`

- **What it does**: Controls whether Kodi terminates the Python process after every menu action (`false`) or keeps it alive in memory (`true`).
- **When to enable (`true`)**: Recommended for powerful devices (Shield Pro, PC, Mac, Linux). Navigating menus will be instant because the Python interpreter is already primed.
- **When to disable (`false`)**: Recommended for low-RAM streaming sticks (FireStick 4K, Chromecast with Google TV, Onn 4K). Keeping Python alive continuously consumes 80MB–150MB of RAM. If you encounter crashes when navigating back from video playback, **disable** this setting immediately.

---

### Custom View IDs
Located under: `General -> General Customization`

- **Setting**: `interface.viewidswitch` ("Enable Custom View IDs").
- **Danger**: View IDs are skin-specific integers (e.g., `50`, `500`, `501`). If you enable this setting and enter an ID number that your current Kodi skin does not define, directory listings will appear completely **blank** or invisible.
- **Recovery**: If directories disappear after editing View IDs, open `Settings -> General -> General Customization` and toggle *Enable Custom View IDs* to **Off**.

---

### Stream Size Limits vs. Missing Sources
Located under: `Sort and Filter -> Source Resolution & File Size Filters`

- **Settings**: `general.movie.maxGB` and `general.episode.maxGB`.
- **Common User Error**: Setting the episode size limit too low (e.g., `1 GB`). High-bitrate 1080p anime releases (such as BDMVs or multi-audio releases from SubsPlease or Erai-raws) frequently measure 1.2 GB to 2.5 GB per episode. Setting this limit to `1 GB` will cause Otaku to filter them out and report **"No stream available"**.
- **Safe Recommendation**: Set Episode Max Size to `0` (Unlimited) or at least `4 GB`. Set Movie Max Size to `0` or `15 GB+`.

---

### Scraper Concurrency & Timeouts
Located under: `Scraping -> Scraper Tuning`

- **Settings**: `scraper.concurrency.workers` and `general.timeout`.
- **Danger**: Setting concurrency workers to `20+` will overwhelm weak home routers and low-end Wi-Fi chips with simultaneous DNS queries and TLS handshakes, leading to dropped packets and failed scrapes.
- **Safe Recommendation**: Set workers between `4` and `10`. Keep timeout between `8` and `15` seconds.

---

### Data Recovery: Database Rebuild vs. Factory Reset
Located under: `Maintenance -> Data Recovery & Factory Reset`

- **Rebuild Database (`rebuild_database`)**:
  - *Safe*: Resets and cleans the internal SQLite schema, cleans cache tables, and pulls a fresh copy of your watchlists from your authenticated accounts (AniList, Kitsu, MAL).
  - *Does NOT delete*: Your account credentials, API keys, Debrid tokens, or general settings.
- **Factory Reset (`wipe_addon_data`)**:
  - *DESTRUCTIVE*: Completely wipes the `addon_data/plugin.video.otaku.rpdev/` directory. All credentials, API tokens, history, and custom settings will be irreversibly erased. Use this only as a last resort before reinstalling.

---

## 5. Troubleshooting & Emergency Recovery

### Issue: "No Stream Available" on Airing Shows
1. Go to `Sort and Filter -> Source Resolution & File Size Filters`. Verify that `Max GB` limits are not set too aggressively low.
2. Check `Accounts`. Verify that your Debrid account has an active, paid premium subscription and that its authorization token has not expired.
3. Open `Maintenance -> Database Diagnostics` and run **Force Sync Anime Mappings DB** to ensure recent title aliases and anime ID mappings are up to date.

### Issue: Subtitles are Garbled or Contain Strange Symbols
1. Open `Subtitles -> Subtitle Engine`.
2. Ensure **Detect Character Encoding (chardet)** is set to **Enabled**. This forces international subtitle tracks (e.g., Windows-1256, ISO-8859) to convert cleanly to UTF-8.

### Issue: Directory Listings are Blank or Won't Load
1. Open `General -> General Customization`.
2. Disable **Enable Custom View IDs**.
3. If still blank, open `Maintenance -> Database Diagnostics` and select **Check SQLite DB Integrity** followed by **Vacuum SQLite Databases**.

---

*Otaku-RPDev Configuration Guide — Documented and maintained for the RPDevs-Builds Project Workspace.*
