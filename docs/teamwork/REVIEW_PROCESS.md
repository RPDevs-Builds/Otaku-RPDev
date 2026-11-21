# Otaku-RPDev 5-Stage Structured Code Review Process (`docs/teamwork/REVIEW_PROCESS.md`)

Every work package (`SP-*`, `CR-*`, `NF-*`) in `docs/teamwork/SPRINT_BOARD.md` must pass this 5-stage review checklist before transitioning to `DONE`.

---

## Stage 1: Architectural & Boundary Compliance
- [ ] **Zero Target Device Interference:** Confirm no code, test, or script writes to, sideloads, or executes mutating commands against `10.13.0.16`.
- [ ] **Acyclic Tri-Addon Dependency Graph:** Verify `context.otaku.rpdev/addon.xml` and `service.subtitles.otaku.rpdev/addon.xml` ONLY import `xbmc.python` (`test_zero_circular_addon_dependencies`).
- [ ] **Context Budget Guard:** Verify `AGENTS.md` remains strictly `< 22,000` bytes (`test_agents_md_within_24kb_context_budget`).
- [ ] **Zero-`soupsieve` & Modern Stdlib:** Confirm zero `.select()` / `.select_one()` calls, zero PEP 594 deprecated imports, and `ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)` usage.

## Stage 2: Dual Kodi 20/21 & Kodi 22 (Piers) C++ / SWIG Safety
- [ ] **`InfoTagVideo` & Non-Null SWIG Coercion:** All metadata uses `li.getVideoInfoTag()` typed setters with `str(val or '')` / `int(val or 0)` coercion and `control.clean_art_dict(art)` before `setArt()`.
- [ ] **Kodi VFS `g_directoryCache` Synchronization:** Any file written to `special://temp/` or addon temp directories that Kodi C++ (`CFile::Open`, `CFile::Copy`, `CDVDFactorySubtitle::CreateParser`) opens must go through `control.atomic_write_text()` (`xbmcvfs.rename`) and never poison `g_directoryCache` via `xbmcvfs.listdir()`.
- [ ] **64 KB Window Property Ceiling & Modal Disposal:** Payloads `> 65,536` UTF-8 bytes are stored in SQLite WAL `cache.db`, and every `doModal()` call is wrapped in `try...finally: dlg.close(); del dlg`.
- [ ] **Single Event Dispatch & In-Place `ControlList` Mutation:** Zero Action ID `7`/`100` handling inside `onAction()` when `onClick()` exists; zero `list_control.reset()` calls during in-place row updates.

## Stage 3: Concurrency, SQLite, Transport & Adversarial Claim-to-Code Closure
- [ ] **SQLite Read-Only URI & Unconditional Column Idempotency:** Static databases (`info.db`, `mappings.db`) use `file:{abs_path}?mode=ro` (`uri=True`) and never run write PRAGMAs or WAL checkpoints. Mutable DB migrations create tables idempotently in `_create_all_tables()` and execute `_ensure_column_migrations()` (`PRAGMA table_info`) unconditionally on startup (independent of `SCHEMA_VERSION` equality).
- [ ] **Abort-Responsive Loops:** Zero `time.sleep()` or `xbmc.sleep()` calls `> 500ms`; all retry/poll delays use `if control.monitor.waitForAbort(seconds): return / break`.
- [ ] **Transport Hygiene:** Timeouts cast to `float(timeout)`, URLs joined via `'&' if '?' in url else '?'` / `domains.join_url()`, JSON parsed via `control.loads_json()` / `r.json(default={})`, and sensitive tokens/API keys registered in `control._SENSITIVE_SETTING_KEYS`.
- [ ] **Mandatory Adversarial Claim-to-Code Closure Audit:** Before marking any sprint ledger (`SPRINT_BOARD.md`, `QA_SIGNOFF.md`) complete, perform an independent adversarial pass proving:
  1. **Runtime Call-Site Wiring:** New helpers (`scrobble_retry_queue`, `episode_offset` isolation, `dry_run` confirmation gates) are wired into live loops/routes, not just unit-tested in isolation.
  2. **Settings & Profile Round-Trip:** Every new setting key and DB profile (`series_overrides`) is consumed by runtime code and round-tripped by `settings_manager.py` Backup & Restore.
  3. **Concern-Taxonomy Alignment:** `scripts/audit_onn_logs.py` `CONCERN_PATTERNS` regexes match canonical `docs/CONCERNS.md` definitions (`C-11` vs `C-14` vs `CR-01`).
  4. **Dry-Run Release ZIP Integrity:** Dry-run built ZIPs for all 3 add-ons contain `0` `tests/`, `docs/`, `teamwork/`, or `__pycache__/` entries and `0` case-insensitive filename collisions.

## Stage 4: Actionable Test Quality, Negative-Path Quota & Coverage Verification
- [ ] **Anti-Placeholder Compliance (`test_suite_quality.py`):** Every new/modified test contains concrete behavioral assertions, zero tautologies, zero broad `except Exception: pass`, and exercises real production consumers (no setting `set`$\rightarrow$`get` echoes).
- [ ] **Minimum 2:1 Negative/Edge-to-Happy Ratio:** Every `NF-*` feature ships at least two negative/edge tests per happy-path test (corruption rollback, `Retry-After` queue pruning, confirmation cancellation, `videodb://` safety, canonical scrobble isolation).
- [ ] **Strict Kodi 22 Profile Coverage:** WindowXML and settings tests run under `KodiProfile('22', strict_skin_controls=True, strict_settings=True)`.
- [ ] **Coverage Floor:** New modules are imported and exercised (`100%` module coverage; overall function coverage `>= 65.0%`).

## Stage 5: Unified Multi-Silo Gate Execution
- [ ] Run `python3 scripts/verify_all.py --fail-below 65` and `python3 scripts/e2e_v630_suite.py` and confirm all offline silos (`ruff`, `compileall`, `unittest`, `coverage`) exit `0` with `0` project `DeprecationWarning` or `ResourceWarning`.
