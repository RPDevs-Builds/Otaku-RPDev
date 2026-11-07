# Comprehensive Project Review and Improvement Report: Otaku-RPDev

**Target Project:** `/mnt/sharedroot/projects/RPDevs-Builds/Otaku-RPDev`  
**Date:** 2026-11-07  
**Author:** Project Orchestrator (incorporating Explorer Survey Teams 1, 2, and 3)  
**Status:** Approved for Implementation  
**Baseline Test Execution:** `python3 -m unittest discover tests` — 517 tests passed in 22.5s (0 failures, 0 errors).

---

## Executive Summary

A project-wide code review was conducted across the Otaku-RPDev codebase, evaluating architecture, code quality, performance, concurrency, memory safeguards, Kodi 20/21/22 subsystem invariants, and test baseline health. 

Otaku-RPDev exhibits strong modularity, clean metadata population via `InfoTagVideo`, and an extensive hermetic test suite (517 unit and integration tests). However, the investigation identified several critical and high-priority improvement opportunities across:
1. **WindowXML Event Routing:** Double action dispatch on Action ID 7 (Enter/Select) across 8 dialogs due to simultaneous handling in both `onAction()` and Kodi's native `onClick()`.
2. **Memory Safeguards & 64KB Ceiling:** Review payloads (>100KB) cached in C++ window properties (`control.setGlobalProp`), risking heap fragmentation on low-RAM streaming devices; absence of 64KB ceiling validation.
3. **Scraper Genericity & Fallback Chains:** Hardcoded embed origins in `watchnixtoons2.py` preventing dynamic domain adaptation, and premature loop termination in `gogoanime.py` pruning alternate stream hosts.
4. **Demuxer Chapter Fallback Chain:** Inversion of chapter detection in `player.py`, waiting for external web AniSkip before demuxer chapters and gating native Kodi 22 demuxer chapter queries behind an `ffprobe` binary check.
5. **SQLite Concurrency & Static Dictionaries:** Incomplete read-only URI defaults for `mappings.db`, causing write pragmas and WAL locks during read operations.
6. **SWIG Non-Null Type Contracts & Setting Accessors:** Uncoerced values passed to `ListItem` and `setSetting`, plus unhandled `TypeError` exceptions in setting type conversions.
7. **Responsive Abort Loops:** Synchronous multi-second blocking sleeps (`xbmc.sleep()`, `time.sleep()`) exceeding 500ms in playback and scraping loops, impairing player responsiveness and Kodi shutdown.
8. **Transport Robustness & Defensive JSON:** Unsafe JSON parsing without fallbacks, integer timeout truncation in debrid clients, and missing proactive OAuth token expiration buffers.

---

## Detailed Findings and Remediation Catalog

### Domain 1: Kodi GUI Subsystem & WindowXML Event Handling

#### Finding 1.1: Double Action Dispatch on Action ID 7 in WindowXML Dialogs [Priority: CRITICAL]
- **Affected Files & Lines:**
  - `plugin.video.otaku.rpdev/resources/lib/windows/playing_next.py`: lines 97–100
  - `plugin.video.otaku.rpdev/resources/lib/windows/skip_intro.py`: lines 75–78
  - `plugin.video.otaku.rpdev/resources/lib/windows/clear_cache.py`: lines 130–141
  - `plugin.video.otaku.rpdev/resources/lib/windows/download_manager.py`: lines 38–41
  - `plugin.video.otaku.rpdev/resources/lib/windows/wlf_auth.py`: lines 71–74
  - `plugin.video.otaku.rpdev/resources/lib/windows/textviewer.py`: lines 50–53
  - `plugin.video.otaku.rpdev/resources/lib/windows/anichart.py`: lines 79–83
  - `plugin.video.otaku.rpdev/resources/lib/windows/still_watching.py`: lines 50–57
- **Rationale:** Kodi's C++ GUI engine dispatches `onClick(control_id)` whenever Enter/Select is activated on a focused control. Capturing Action ID 7 (or 100) inside `onAction()` and routing to `self.handle_action()` causes the action to be processed twice in immediate succession. In `PlayingNext` and `SkipIntro`, this triggers duplicate stream seeks and window closing race conditions.
- **Remediation Plan:** Remove Action ID 7 (and Action 100 where handled by `onClick`) handling from `onAction()` in all 8 dialog classes. Allow Kodi's native event dispatcher to route selection events to `onClick(control_id)` exclusively. Retain back/cancel action IDs in `onAction()`.

#### Finding 1.2: Destructive List Resets in Download Manager [Priority: MEDIUM]
- **Affected Files & Lines:**
  - `plugin.video.otaku.rpdev/resources/lib/windows/download_manager.py`: line 79
- **Rationale:** Calling `self.display_list.reset()` when the task count changes forces Kodi's C++ GUI to evict active list control focus, resetting user selection to item 0.
- **Remediation Plan:** Update items in-place using `display_list.getListItem(idx).setProperty(...)` or adjust items incrementally without wiping the entire control list.

---

### Domain 2: Performance, Resource Management & Memory Safeguards

#### Finding 2.1: 64KB Window Property Ceiling Violation & Reviews Offloading [Priority: CRITICAL]
- **Affected Files & Lines:**
  - `plugin.video.otaku.rpdev/resources/lib/Main.py`: lines 331–333, 423
  - `plugin.video.otaku.rpdev/resources/lib/ui/control.py`: lines 281–284 (`_WindowProxy.setProperty`), lines 934–937 (`setGlobalProp`)
- **Rationale:** Kodi C++ window properties (`_window.setProperty`) are stored in un-compacted memory maps. Arbitrary multi-entry user review payloads dumped via `control.setGlobalProp('otaku.reviews.cache', json.dumps(reviews))` frequently exceed 64KB–150KB, risking memory fragmentation and crashes on 1GB RAM streaming devices.
- **Remediation Plan:**
  1. Offload user review payload caching to SQLite WAL `cache.db` via `database.cache_insert` / `database.cache_get` using a dedicated cache key (`otaku_reviews_{anime_id}`).
  2. Implement an explicit 64KB (`65536` bytes) ceiling guard in `_WindowProxy.setProperty` and `control.setGlobalProp`. If a payload exceeds 64KB, truncate or log a warning and reject the C++ property write.

#### Finding 2.2: Responsive Abort Loops and Synchronous Sleep Replacement [Priority: HIGH]
- **Affected Files & Lines:**
  - `plugin.video.otaku.rpdev/resources/lib/routes/playback.py`: lines 392, 395, 435, 438, 552, 643, 721, 824
  - `plugin.video.otaku.rpdev/resources/lib/pages/watchnixtoons2.py`: line 419 (`time.sleep(5)`), line 291 (`time.sleep(2)`)
  - `plugin.video.otaku.rpdev/resources/lib/debrid/premiumize.py`: line 151 (`control.sleep(5000)`)
  - `plugin.video.otaku.rpdev/resources/lib/windows/sort_select.py`: lines 496, 513, 523, 533 (`control.sleep(1000)`)
- **Rationale:** Calling synchronous `xbmc.sleep()` or Python `time.sleep()` for >500ms blocks the OS thread. When Kodi signals abort or shutdown, these blocking sleeps prevent clean termination and freeze the player interface.
- **Remediation Plan:** Replace synchronous sleeps exceeding 500ms with non-blocking `control.monitor.waitForAbort(seconds)`. If `waitForAbort` returns `True`, immediately abort execution and exit cleanly.

#### Finding 2.3: SQLite Concurrency & Static Dictionary Read-Only Defaults [Priority: HIGH]
- **Affected Files & Lines:**
  - `plugin.video.otaku.rpdev/resources/lib/ui/database.py`: lines 226–234, 1625, 1817
- **Rationale:** `mappings.db` is an immutable reference database. However, `SQL.__init__` omitted `mapping_path` from default read-only checks, allowing callers in `get_database_stats()` and `check_database_integrity()` to open `mappings.db` read-write, triggering unnecessary WAL pragma executions and potential write-lock contention.
- **Remediation Plan:** Add `mappings.db` path to the default read-only check in `database.py`. Enforce URI mode `file:{abs_path}?mode=ro` for all read-only connections. Ensure the connection cache partitions handles by `(abs_path, is_readonly)`.

---

### Domain 3: Scraper Genericity & Kodi Compatibility

#### Finding 3.1: Scraper Domain Hardcoding in WatchNixtoons2 [Priority: HIGH]
- **Affected Files & Lines:**
  - `plugin.video.otaku.rpdev/resources/lib/pages/watchnixtoons2.py`: lines 319–323, 382, 399, 510, 529
- **Rationale:** `watchnixtoons2.py` defines `_embed_api_origin(self, embed_url)` to derive API origins dynamically, but fails to use it in 4 critical locations, hardcoding `'https://embed.wcostream.com'`. When WCO rotates embed domains, advertisement and video link extraction fails.
- **Remediation Plan:** Replace hardcoded `https://embed.wcostream.com` with `self._embed_api_origin(embed_url)` dynamically across all advertisement, ad-verify, and embed fallback URLs.

#### Finding 3.2: Premature Server Candidate Pruning in GogoAnime [Priority: HIGH]
- **Affected Files & Lines:**
  - `plugin.video.otaku.rpdev/resources/lib/pages/gogoanime.py`: lines 164–167
- **Rationale:** In `_process_gogo`, the server iteration loop executes `break` after appending the first enabled server. If a host goes offline, alternate mirrors are lost.
- **Remediation Plan:** Remove the premature `break` on line 167. Append all valid enabled servers to `sources` to maintain multi-server candidate fallback resilience.

#### Finding 3.3: Demuxer Chapter Fallback Chain and Decoupling from ffprobe [Priority: HIGH]
- **Affected Files & Lines:**
  - `plugin.video.otaku.rpdev/resources/lib/ui/player.py`: lines 535–549, 907–918
- **Rationale:** `player.py` waits 3000ms for external AniSkip web responses before querying container chapters. Furthermore, native Kodi 22 demuxer chapter queries (`Player.GetChapters` via JSON-RPC) are gated behind `if not control.getBool('ffprobe.chapters.enable')`. Native Kodi 22 demuxer chapter extraction does not require an ffprobe binary and should execute first as the most authoritative local source.
- **Remediation Plan:** Invert the skip fallback sequence: first attempt native Kodi 22 JSON-RPC `Player.GetChapters` directly. If native chapters are absent, attempt pre-probed chapters, and finally AniSkip / external timestamps.

---

### Domain 4: Code Quality, SWIG Contracts & Modernization

#### Finding 4.1: SWIG Non-Null Contracts & Defensive Setting Accessors [Priority: HIGH]
- **Affected Files & Lines:**
  - `plugin.video.otaku.rpdev/resources/lib/ui/control.py`: lines 254, 811–888, 1399
- **Rationale:** Passing `None` to `xbmcgui.ListItem(name)` triggers fatal SWIG `TypeError`. In `control.py`, `_settings_cache` assignments for `setInt` and `setNumber` sit outside `try...except`, crashing if `value` is `None` or unparseable. `setStringList`, `setBoolList`, `setIntList`, `setNumberList` lack exception handling.
- **Remediation Plan:**
  1. Wrap `name` in `str(name or '')` at `control.py:1399`.
  2. Coerce `value` to `str(value or '')` in `_AddonProxy.setSetting()`.
  3. Enclose all type conversions and cache updates inside `try...except` blocks with safe default fallbacks; guard list setters defensively.

#### Finding 4.2: HTTP Transport Precision, Defensive JSON & Jittered 429 Backoff [Priority: MEDIUM]
- **Affected Files & Lines:**
  - `plugin.video.otaku.rpdev/resources/lib/ui/client.py`: line 1000, lines 1131, 1174
  - `plugin.video.otaku.rpdev/resources/lib/ui/control.py`: lines 1758–1761 (`safe_json`)
  - `plugin.video.otaku.rpdev/resources/lib/debrid/easynews.py`: lines 44, 98
  - `plugin.video.otaku.rpdev/resources/lib/debrid/real_debrid.py`: line 27, line 205
  - `plugin.video.otaku.rpdev/resources/lib/debrid/debrid_link.py`: line 21, line 32
- **Rationale:** `int(_TIMEOUT)` truncates sub-second timeouts in `easynews.py`. `control.safe_json` crashes with `AttributeError` when passed raw `str`/`bytes`. Debrid 429 retry loops lack randomized jitter and use blocking sleeps. Real-Debrid and Debrid-Link lack proactive 300s buffer token expiry evaluations.
- **Remediation Plan:** Cast timeouts to `float(timeout)`. Update `control.safe_json` to parse raw `str`/`bytes` with fallback. Add `random.uniform(0.1, 0.4)` jitter and `control.monitor.waitForAbort()` to 429 retry loops. Add proactive token refresh checks (`time.time() > expiry - 300`).

#### Finding 4.3: Python 3 Clean Runtimes & Code Smell Elimination [Priority: LOW]
- **Affected Files & Lines:**
  - `resources/lib/pages/__init__.py`: line 152
  - `resources/lib/windows/playing_next.py`: lines 51, 65
  - `resources/lib/windows/skip_intro.py`: lines 43, 50
  - `resources/lib/windows/resolver.py`: line 664
  - `resources/lib/windows/source_select.py`: line 165
  - `resources/lib/windows/wlf_auth.py`: line 36
  - `resources/lib/windows/get_sources_window.py`: line 39
  - `resources/lib/AnimeSchedule.py`: line 41
  - `resources/lib/ui/BrowserBase.py`: line 109
  - `resources/lib/ui/embed_extractor.py`: line 387
  - `resources/lib/ui/control.py`: line 96
- **Rationale:** Legacy Python 2/3 `super(ClassName, self)` patterns violate modern Python 3.12+ clean runtimes. Mutable default arguments (`types=['sub', 'dub', 'raw']`, `data={}`, `datas=[]`) leak state across invocations in Kodi's persistent Python invoker. Raw `print()` bypasses Kodi logging levels.
- **Remediation Plan:** Convert to `super().__init__()` / `super().method()`. Replace mutable defaults with `None` and initialize in body. Replace raw `print()` with `control.log()`.

---

## Actionable Remediation Roadmap

| Milestone | Scope & Target Files | Key Improvements | Dependencies |
|:---|:---|:---|:---|
| **M1: Core Subsystem Invariants** | `ui/control.py`, `ui/database.py`, `Main.py`, `ui/client.py` | SWIG non-null coercion, defensive setting accessors, 64KB window property ceiling guard, review cache offload to SQLite `cache.db`, static DB read-only URI defaults, defensive `safe_json` | None |
| **M2: WindowXML GUI Modernization** | `windows/` (`playing_next.py`, `skip_intro.py`, `clear_cache.py`, `download_manager.py`, `wlf_auth.py`, `textviewer.py`, `anichart.py`, `still_watching.py`) | Single event dispatch (remove Action 7/100 from `onAction`), in-place list updates, modernize `super()` | M1 |
| **M3: Scrapers, Demuxer & Playback** | `pages/watchnixtoons2.py`, `pages/gogoanime.py`, `ui/player.py`, `routes/playback.py` | Dynamize embed API origins, remove premature `break` in GogoAnime, native Kodi 22 demuxer chapter fallback chain, responsive abort sleeps | M1 |
| **M4: Transport, Rate Limits & Clean Code** | `debrid/` (`easynews.py`, `real_debrid.py`, `debrid_link.py`, `premiumize.py`), `AnimeSchedule.py`, `ui/BrowserBase.py`, `ui/embed_extractor.py` | Float timeout precision, jittered 429 backoff, proactive OAuth expiry buffer, eliminate mutable default arguments, remove raw `print()` | M1 |
| **M5: Final Verification & Test Hardening** | `tests/` across repository | Run all 517 baseline tests, add new unit tests for remediated behaviors, verify zero regressions | M1, M2, M3, M4 |

---

## Verification Methodology
1. **Automated Unit & Integration Test Suite**:
   ```bash
   cd /mnt/sharedroot/projects/RPDevs-Builds/Otaku-RPDev
   python3 -m unittest discover tests
   ```
   *Pass Criteria:* 517+ tests run cleanly with 0 failures, 0 errors, and zero regressions.
2. **AST Integrity & Setting Schema Audit**:
   ```bash
   python3 -m unittest tests/lint/test_ast_integrity.py
   python3 -m unittest tests/unit/test_settings_schema_and_code_references.py
   ```
3. **Syntax & Runtime Compilation Check**:
   ```bash
   python3 -m compileall plugin.video.otaku.rpdev context.otaku.rpdev tests
   ```
   *Pass Criteria:* Zero compilation errors, clean byte-compilation across all target modules.
