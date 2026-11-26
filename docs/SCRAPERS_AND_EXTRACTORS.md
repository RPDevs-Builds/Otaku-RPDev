# Otaku-RPDev Scrapers, Embed Extractors & Debrid Playbook

This playbook documents the implementation contracts, anti-bot fallbacks, mirror rotation strategies, and debrid cache-check workflows for all 17 scraper modules in [`resources/lib/pages/`](../plugin.video.otaku.rpdev/resources/lib/pages/), the embed extractor pipeline in [`resources/lib/ui/`](../plugin.video.otaku.rpdev/resources/lib/ui/), and the 8 debrid modules in [`resources/lib/debrid/`](../plugin.video.otaku.rpdev/resources/lib/debrid/).

---

## 1. Scraper Orchestration & Execution Pool ([`pages/__init__.py`](../plugin.video.otaku.rpdev/resources/lib/pages/__init__.py))

### 1.1 Parallel Worker Lifecycle
- **Fan-Out Dispatch**: `getSourcesHelper()` spawns concurrent worker threads across four provider classes:
  1. **Torrent Scrapers** (`nyaa`, `animetosho`, `torrentio`, `bitsearch`, `piratebay`, `nekobt`)
  2. **Debrid Cloud & Local Scanners** (`debrid_cloudfiles`, `localfiles`)
  3. **Usenet / Hoster Scrapers** (`easynews`)
  4. **Direct Embed Scrapers** (`hianime`, `anikoto`, `animepahe`, `gogoanime`, `watchnixtoons2`)
- **Timeout & Early-Exit Modes**:
  - **Standard Mode (`is_rescrape=False`)**: Runs up to `general.timeout` seconds (default `15s`). If adaptive early-termination is enabled and the pool accumulates enough cached sources at the user's target resolution tier, remaining slow workers are signaled to abort early.
  - **Full Discovery Mode (`is_rescrape=True`, triggered by `Source Select` or `Rescrape`)**: Enforces a minimum **`30s` timeout floor** (`max(timeout, 30)`), disables early termination (`early_exit_enabled = False`), resets HiAnime mirror cooldowns, and bypasses `AdaptiveCircuitBreaker` skips so all enabled providers finish.

---

## 2. Torrent, Cloud, Local & Hoster Scrapers

| Module | Provider ID | Source Type | Architecture & Key Invariants |
|---|---|---|---|
| [`pages/nyaa.py`](../plugin.video.otaku.rpdev/resources/lib/pages/nyaa.py) | `nyaa` | `torrent` | Queries Nyaa (`nyaa.si` / `nyaa.iss.one`) HTML/RSS feeds. Merges episode queries and `show_pack` batch queries into a **single** `parallel_process` pool, parses rows via BeautifulSoup `.find()`/`.find_all()` (zero `soupsieve`), deduplicates magnet infohashes, and invokes a **single batched** `Debrid().torrentCacheCheck()`. Supports thread-safe sticky `direct <-> translate.goog` alt-host switching. |
| [`pages/animetosho.py`](../plugin.video.otaku.rpdev/resources/lib/pages/animetosho.py) | `animetosho` | `torrent` | Queries AnimeTosho JSON API (`feed.animetosho.org/json`) by `anidb_id` and title queries (`show_pack` merged into primary parallel pool). Deduplicates hashes prior to single-batch `torrentCacheCheck()` and falls back between direct and `translate.goog` proxy on HTTP `>= 400` or connection reset. |
| [`pages/torrentio.py`](../plugin.video.otaku.rpdev/resources/lib/pages/torrentio.py) | `torrentio` | `torrent` | Queries Stremio-compatible Torrentio manifest API (`torrentio.strem.fun`) using `imdb_id` / `kitsu_id` (`stream/series/kitsu:<id>:<ep>.json`). Extracts infohashes, file indexes, and embedded seeder/size metadata before batch debrid cache verification. |
| [`pages/nekobt.py`](../plugin.video.otaku.rpdev/resources/lib/pages/nekobt.py) | `nekobt` | `torrent` | Queries NekoBT JSON API (`nekobt.to/api/v1/torrents/search`) with automatic token/pagination handling, title isolation scoring, and single-batch debrid cache check. |
| [`pages/bitsearch.py`](../plugin.video.otaku.rpdev/resources/lib/pages/bitsearch.py) | `bitsearch` | `torrent` | Scrapes Bitsearch magnet listings (`bitsearch.to/search`) with `isolate_show_title` + `score_title_candidate` filtering (`score >= 45`) and batch debrid verification. |
| [`pages/piratebay.py`](../plugin.video.otaku.rpdev/resources/lib/pages/piratebay.py) | `piratebay` | `torrent` | Queries Apibay JSON endpoint (`apibay.org/q.php`) in category `200` (Video), converts infohashes to magnet URIs, filters via `source_utils`, and batch-checks debrid cache. |
| [`pages/debrid_cloudfiles.py`](../plugin.video.otaku.rpdev/resources/lib/pages/debrid_cloudfiles.py) | `cloud` | `cloud` | Searches the user's personal cloud storage across enabled debrid accounts (`Real-Debrid`, `AllDebrid`, `Premiumize`, `TorBox`) for pre-existing matching episode files (`cached=True`). |
| [`pages/localfiles.py`](../plugin.video.otaku.rpdev/resources/lib/pages/localfiles.py) | `local` | `local` | Recursively scans the configured local/SMB/NFS media directory (`general.local_path`) for matching anime video files (`.mkv`, `.mp4`, `.avi`) and sidecar subtitles. |
| [`pages/easynews.py`](../plugin.video.otaku.rpdev/resources/lib/pages/easynews.py) | `easynews` | `hoster` | Queries Easynews Usenet member search API (`members.easynews.com/2.0/search/solr-search/`), filters out password-protected/virus/sample archives, and builds direct authenticated HTTP stream URLs. |

> [!IMPORTANT]
> **Torrent Scraper Mandatory Rules**:
> 1. **Single-Batch Debrid Cache Check**: Never call `Debrid().torrentCacheCheck()` inside per-query loops. Merge all episode and `show_pack` queries into one candidate list, deduplicate by lowercase `hash`, run `source_utils.filter_sources()` (which expands sequel aliases via `expand_sequel_season_aliases()`), and execute **one** `torrentCacheCheck()` call per scraper.
> 2. **Query-String-Safe `translate.goog` Joining**: Always append query parameters using `'&' if '?' in url else '?'` (or `domains.join_url()`) because `translate.goog` URLs already contain `?_x_tr_sl=auto&_x_tr_tl=en&_x_tr_hl=en`.

---

## 3. Direct Embed Scrapers & Extractor Chain

### 3.1 Embed Scrapers (`pages/*.py`)

| Module | Provider ID | Status | Architecture, Mirror Rotation & Caching |
|---|---|---|---|
| [`pages/hianime.py`](../plugin.video.otaku.rpdev/resources/lib/pages/hianime.py) | `hianime` | **Active** | Scrapes HiAnime mirrors (`hianime.to`, `hianime.nz`, `hianime.sx`, `hianime.mn`, `hianimez.to`, `aniwatchtv.to`). Caches resolved `(mirror, mal_id) -> anime_id` mappings in `cache.db` for **24 hours** (`_ANIME_ID_CACHE`) so consecutive episode binge-watching skips redundant search round-trips. Fetches AJAX episode list and server IDs (`sub`, `dub`, `raw`), rotates across healthy mirrors with per-mirror negative cooldowns (`reset_mirror_cooldowns()` on manual rescrape/source-select), and delegates stream extraction to `megaplay_extractor.py` / `megacloud_extractor.py`. |
| [`pages/anikoto.py`](../plugin.video.otaku.rpdev/resources/lib/pages/anikoto.py) | `anikoto` | **Active** | Scrapes AniKoto / dead-domain redirect mirrors with category-page HTML fallbacks, normalizes Sub and Dub server candidate lists, and resolves prioritized embed hosts sequentially via `embed_extractor.py`. |
| [`pages/animepahe.py`](../plugin.video.otaku.rpdev/resources/lib/pages/animepahe.py) | `animepahe` | **Active** | Queries AnimePahe API (`animepahe.ru/api?m=search` -> `m=release`), supports DDoS-Guard cookie/FlareSolverr bypass, and extracts Kwik (`kwik.si` / `kwik.cx`) HLS `.m3u8` streams with resolution and Sub/Dub badges. |
| [`pages/gogoanime.py`](../plugin.video.otaku.rpdev/resources/lib/pages/gogoanime.py) | `gogoanime` | **Active** | Scrapes Gogoanime / Anitaku mirrors (`anitaku.pe`, `gogoanime3.co`), resolves both `(Sub)` and `(Dub)` slug variants, and extracts prioritized multi-server embed links (`GogoCDN`, `Vidstreaming`, `StreamWish`, `Filemoon`). |
| [`pages/watchnixtoons2.py`](../plugin.video.otaku.rpdev/resources/lib/pages/watchnixtoons2.py) | `watchnixtoons2` | **Active** | Scrapes WatchNixToons2 / WCO catalog endpoints for English Dubbed and Subbed streams and resolves direct MP4/HLS video URLs with required `Referer` headers. |
| `aniwave.py`, `animekai.py`, `animixplay.py` | Defunct stubs | **Disabled / No-Op** | Retained as safe no-op stubs returning `[]` for backward settings schema compatibility after upstream domain shutdowns. |

### 3.2 Domain-Agnostic Embed Extractors (`resources/lib/ui/`)
- **[`ui/embed_extractor.py`](../plugin.video.otaku.rpdev/resources/lib/ui/embed_extractor.py)**: Central dispatcher (`load_video_from_url(in_url)`) supporting 20+ embed host families (`Kwik`, `MegaPlay`, `MegaCloud`, `RapidCloud`, `VidStreaming`, `GogoCDN`, `StreamWish`, `Filemoon`, `Doodstream`, `Mp4Upload`, `Luluvdo`, `StreamTape`, `Voe`, `YourUpload`, `OkRu`, `Sibnet`).
  - **Domain-Agnostic Invariant**: Never hardcode single domains in hash decoders or server parsers; always derive origins dynamically via `f"{parsed.scheme}://{parsed.netloc}"`.
  - **Multi-Server Fallback Order**: When a scraper supplies a candidate list of server URLs, `Resolver` attempts extraction sequentially until a valid stream (`HTTP 200`/`206` verified with `Range: bytes=0-0`) succeeds.
- **[`ui/megaplay_extractor.py`](../plugin.video.otaku.rpdev/resources/lib/ui/megaplay_extractor.py) & [`ui/megacloud_extractor.py`](../plugin.video.otaku.rpdev/resources/lib/ui/megacloud_extractor.py)**:
  - Decrypts MegaPlay / MegaCloud / RapidCloud AJAX `getSources` payloads, extracts `.m3u8` master playlists and `.vtt` subtitle tracks (`tracks` array), downloads and validates `.vtt` subtitles via `embed_extractor.get_sub()`, and flags sparse `< 45`-cue Signs-only tracks (`is_sparse_signs`).

---

## 4. Anti-Bot / Cloudflare WAF Fast-Fail & Debrid Resolver Matrix

### 4.1 Cloudflare WAF & FlareSolverr Protocol ([`ui/client.py`](../plugin.video.otaku.rpdev/resources/lib/ui/client.py))
1. **Hard WAF `<500ms` Fast-Fail**: Responses matching hard IP blocks (`Attention Required! | Cloudflare`, `Sorry, you have been blocked`) or unsolvable interactive Turnstile gates immediately trip a negative host cooldown in `AdaptiveCircuitBreaker` without blocking scraper worker threads.
2. **FlareSolverr Direct HTML Return (`returnOnlyCookies: False`)**: Because Python `urllib` has a different JA3/JA4 TLS fingerprint from Chromium, replaying `cf_clearance` cookies over `urllib` fails on modern Cloudflare zones. When FlareSolverr is enabled (`general.flaresolverr.url`), `client.py` always requests the solved HTML body directly from FlareSolverr.

### 4.2 Debrid Provider Matrix (`resources/lib/debrid/`)

| Module | Provider Class | Batch Cache Check Endpoint / Strategy | Season-Pack File Selection & Rate-Limit Contract |
|---|---|---|---|
| [`debrid/real_debrid.py`](../plugin.video.otaku.rpdev/resources/lib/debrid/real_debrid.py) | `RealDebrid` | Combines local SQLite hash cache ([`debrid/debrid_cache.py`](../plugin.video.otaku.rpdev/resources/lib/debrid/debrid_cache.py)) + `/torrents/instantAvailability` / unrestrict check | Adds magnet -> selects matching video file ID via `source_utils.get_best_match()` -> `/unrestrict/link`. Honors HTTP 429 `Retry-After` (`<= 3s` + jitter). |
| [`debrid/all_debrid.py`](../plugin.video.otaku.rpdev/resources/lib/debrid/all_debrid.py) | `AllDebrid` | `/v4/magnet/instant` batch hash check + `debrid_cache.py` | Uploads magnet (`/v4/magnet/upload`), inspects file tree, unlocks target episode link (`/v4/link/unlock`). |
| [`debrid/premiumize.py`](../plugin.video.otaku.rpdev/resources/lib/debrid/premiumize.py) | `Premiumize` | `/api/cache/check` (`items[]` batch infohash array) | Uses `/api/transfer/directdl` to list season-pack contents and selects exact episode stream URL. |
| [`debrid/debrid_link.py`](../plugin.video.otaku.rpdev/resources/lib/debrid/debrid_link.py) | `DebridLink` | `/api/v2/seedbox/cached` batch hash query | Adds magnet to `/api/v2/seedbox/add` and matches episode filename in `files` array. |
| [`debrid/torbox.py`](../plugin.video.otaku.rpdev/resources/lib/debrid/torbox.py) | `TorBox` | `/v1/api/torrents/checkcached` (`hash` list, `list_files=true`) | Creates torrent (`/v1/api/torrents/createtorrent`), matches episode file ID, and calls `/v1/api/torrents/requestdl`. |
| [`debrid/easydebrid.py`](../plugin.video.otaku.rpdev/resources/lib/debrid/easydebrid.py) | `EasyDebrid` | `/v1/link/lookup` batch magnet cache check | Generates direct debrid links via `/v1/link/generate` and matches target episode via `source_utils.get_best_match()`. |
