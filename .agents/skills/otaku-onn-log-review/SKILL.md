---
name: otaku-onn-log-review
description: >-
  Incremental read-only log review workflow for the ONN 4K Pro Kodi 22 device
  (10.13.0.16), docs/CONCERNS.md cursor updates, and live local Flatpak Kodi 22
  verification via kodi-env. Use when the user asks to review ONN logs, check
  device errors/warnings, or verify Otaku-RPDev fixes against real Kodi 22.
---

# Otaku-RPDev ONN Log Review & Local Kodi 22 Verification

## 1. Incremental Read-Only Log Fetch
1. Read `Next review offset` from `/mnt/sharedroot/projects/RPDevs-Builds/Otaku-RPDev/docs/CONCERNS.md`.
2. Fetch **only** new bytes via the read-only web log viewer (never push code, update add-ons, or send remote commands to `10.13.0.16`):
   ```bash
   curl -sS -D /tmp/onn_headers.txt --max-time 15 \
     "http://10.13.0.16:8081/tail?offset=<SAVED_OFFSET>" -o "<SCRATCH_FILE>"
   ```
3. Inspect `X-Seek-Offset` and the first 5 lines:
   - If the output begins with `Starting Kodi (` or `X-Seek-Offset < <SAVED_OFFSET>`, Kodi restarted and rotated `kodi.log`; record the new session start timestamp and set `Next review offset` to `X-Seek-Offset`.
   - Otherwise, set `Next review offset` to `<SAVED_OFFSET> + fetched_bytes` (matching `X-Seek-Offset`).

## 2. Structured Log Triage
- **Otaku activity**:
  ```bash
  grep -iE "otaku\.rpdev|OTAKU RPDEV" "<SCRATCH_FILE>"
  ```
  Verify:
  - Add-on version updates (`Found addon: 'plugin.video.otaku.rpdev v...'`) and `clean_settings` status (0 orphaned settings).
  - Per-provider scrape yields and wall-clock timings (`animetosho`, `nyaa`, `torrentio`, `nekobt`, `piratebay`, `hianime`, `anikoto`, `animepahe`) vs `sortSources` cutoff (`general.timeout`).
  - Playback health: chapter extraction, audio/subtitle track selection, Zero-Wait hits, season-pack reuse, and `OpenStream - Unable to create subtitle parser`.
- **Errors & warnings (filtering known non-Otaku noise)**:
  ```bash
  grep -iE "error <general>|warning <general>|Traceback|PythonToCpp|EXCEPTION" "<SCRATCH_FILE>" \
    | grep -vE "plugin\.video\.umbrella|service\.upnext|/fake/|Control [0-9]+ in window 10025|ParseChildManifest|JSONRPC: Empty batch|OutputPicture - timeout|ActiveAE"
  ```

## 3. Live Local Kodi 22 Verification (`kodi-env`)
Before releasing fixes via `scripts/release_addon.py`:
1. If overriding provider toggles for reproduction, back up `/mnt/sharedroot/projects/kodi-test-env/profiles/kodi22/userdata/addon_data/plugin.video.otaku.rpdev/settings.xml` to `settings.xml.bak`.
2. Launch `kodi-env headless 22` as a background daemon and wait for `JSONRPC.Ping == "pong"` on `http://127.0.0.1:8080/jsonrpc` (Basic auth `kodi:`).
3. Trigger `Player.Open` on the exact target route (e.g. `plugin://plugin.video.otaku.rpdev/play/<mal_id>/<ep>?rescrape=true`) and monitor `/mnt/sharedroot/projects/kodi-test-env/profiles/kodi22/temp/kodi.log`.
4. Audit `kodi.log` for provider timings, `sortSources` funnel counts, external subtitle attachment, and **0** `PythonToCpp` / `Traceback` / `OTAKU RPDEV` errors or warnings.
5. Always stop playback (`Input.Back`, `Player.Stop`), send `Application.Quit`, restore `settings.xml.bak` → `settings.xml`, and verify 0 background tasks remain running.

## 4. Update `docs/CONCERNS.md` & Release
- Update `Next review offset`, `Last line reviewed`, `Review history`, and `Open` / `Resolved` tables in `docs/CONCERNS.md`.
- Publish fixes strictly via `scripts/release_addon.py` (see the `otaku-release-and-verification` skill).
