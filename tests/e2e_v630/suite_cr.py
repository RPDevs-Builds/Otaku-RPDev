# -*- coding: utf-8 -*-
"""
suite_cr.py — Opaque-Box E2E Tests for CR-01..CR-05 & ABI (v6.3.0)
==================================================================
CR-01: Studio Logo Case-Collision Deduplication & Root PNG Compression (12 tests)
CR-02: SQLite WAL / Read-Only URI (?mode=ro) & Recovery Parity (12 tests)
CR-03: Tri-Addon Kodi 21/22 Modal Disposal, C-06 change_log, & Docs Sync (12 tests)
CR-04: CI/Release Hardening & Tri-Addon Packaging Parity (12 tests)
CR-05: Abort-Safe waitForAbort Sweep & _SENSITIVE_SETTING_KEYS Log Redaction (12 tests)
ABI:   Tri-Addon Packaging (6.3.0/1.0.46/1.0.3) & Kodi 21/22 ABI Parity (12 tests)
"""

import ast
import hashlib
import os
import re
import sqlite3
import tempfile
import threading
import time
import unittest
import warnings
import xml.etree.ElementTree as ET
import zipfile
from unittest.mock import MagicMock, patch

from tests.e2e_v630 import e2e_helpers
from tests.e2e_v630.e2e_helpers import (
    ADDON_ROOT,
    CONTEXT_ROOT,
    E2EHermeticEnv,
    E2EMockServer,
    REPO_ROOT,
    SUBTITLE_ROOT,
    assert_repo_clean_of_leaks,
    feature,
    invoke_context_action,
    invoke_plugin_route,
    invoke_subtitle_service,
    run_cli_script,
    send_http_response,
    tier,
)
from tests.lint import test_ast_integrity, test_docs_and_customizations


# ==============================================================================
# CR-01: Studio Logo Case-Collision Deduplication & Root PNG Compression
# ==============================================================================

class TestCR01StudioAssetsAndRootPNGs(unittest.TestCase):
    """CR-01: 6 Tier 1 + 6 Tier 2 opaque-box tests."""

    @tier(1)
    @feature('CR-01')
    def test_cr01_t1_studio_dirs_zero_case_collisions(self):
        studios_root = os.path.join(CONTEXT_ROOT, 'resources', 'images', 'studios')
        for style in ('coloured', 'white'):
            sdir = os.path.join(studios_root, style)
            files = [f for f in os.listdir(sdir) if f.lower().endswith('.png')]
            self.assertGreaterEqual(len(files), 494)
            lowered = [f.lower() for f in files]
            self.assertEqual(len(set(lowered)), len(lowered), f"Case-collision in {sdir}")

        for addon_dir in (ADDON_ROOT, CONTEXT_ROOT, SUBTITLE_ROOT):
            for dirpath, _dirnames, filenames in os.walk(addon_dir):
                if '__pycache__' in dirpath:
                    continue
                lowered = [fn.lower() for fn in filenames]
                self.assertEqual(len(set(lowered)), len(lowered), f"Case-collision in {dirpath}")

    @tier(1)
    @feature('CR-01')
    def test_cr01_t1_studio_logo_variants_resolve_coloured(self):
        with E2EHermeticEnv('22'):
            from resources.lib.ui import control
            variants = [
                'Eight Bit', '8-bit', '8-Bit',
                'Bones', 'BONES',
                'Liden Films', 'LIDEN FILMS',
                'Madhouse', 'MADHOUSE',
            ]
            for name in variants:
                resolved = control.get_studio_logo_path(name, 'coloured')
                self.assertTrue(resolved, f"Empty studio path for {name}")
                self.assertTrue(resolved.lower().endswith('.png'))
                self.assertTrue(os.path.isfile(resolved), f"Missing file {resolved}")
                self.assertIn(os.path.join('studios', 'coloured'), os.path.normpath(resolved))

    @tier(1)
    @feature('CR-01')
    def test_cr01_t1_studio_logo_variants_resolve_white(self):
        with E2EHermeticEnv('22'):
            from resources.lib.ui import control
            for name in ('Eight Bit', '8-bit', 'BONES', 'Liden Films', 'Madhouse'):
                white_p = control.get_studio_logo_path(name, 'white')
                coloured_p = control.get_studio_logo_path(name, 'coloured')
                self.assertTrue(white_p)
                self.assertTrue(os.path.isfile(white_p))
                self.assertIn(os.path.join('studios', 'white'), os.path.normpath(white_p))
                self.assertNotEqual(os.path.normpath(white_p), os.path.normpath(coloured_p))

    @tier(1)
    @feature('CR-01')
    def test_cr01_t1_xbmc_add_dir_applies_studio_art_by_setting(self):
        with E2EHermeticEnv('22'):
            import conftest
            from resources.lib.ui import control

            for style in ('coloured', 'white'):
                conftest.mock_xbmcplugin.reset()
                control.setSetting('artwork.studios', style)
                control.xbmc_add_dir(
                    'Frieren',
                    'animes/52991',
                    {},
                    {'title': 'Frieren', 'studio': ['Madhouse']},
                    None,
                    False,
                    True,
                    False,
                )
                self.assertEqual(len(conftest.mock_xbmcplugin.directory_items), 1)
                li = conftest.mock_xbmcplugin.directory_items[0][2]
                studio_art = li.getArt('studio')
                self.assertTrue(studio_art)
                self.assertTrue(os.path.isfile(studio_art))
                self.assertIn(os.path.join('studios', style), os.path.normpath(studio_art))
                self.assertEqual(li.getArt('tvshow.studio'), studio_art)
                self.assertEqual(li.getProperty('StudioIcon'), studio_art)
                self.assertEqual(li.getProperty('StudioLogo'), studio_art)
                self.assertEqual(li.getProperty('Studio'), 'Madhouse')

            conftest.mock_xbmcplugin.reset()
            control.setSetting('artwork.studios', 'none')
            control.xbmc_add_dir(
                'Frieren',
                'animes/52991',
                {},
                {'title': 'Frieren', 'studio': ['Madhouse']},
                None,
                False,
                True,
                False,
            )
            li_none = conftest.mock_xbmcplugin.directory_items[0][2]
            self.assertEqual(li_none.getArt('studio'), '')
            self.assertEqual(li_none.getProperty('StudioIcon'), '')

    @tier(1)
    @feature('CR-01')
    def test_cr01_t1_root_poster_and_icon_png_sizes_and_headers(self):
        png_magic = b'\x89PNG\r\n\x1a\n'
        for addon_dir in (ADDON_ROOT, CONTEXT_ROOT, SUBTITLE_ROOT):
            poster_path = os.path.join(addon_dir, 'poster.png')
            icon_path = os.path.join(addon_dir, 'icon.png')
            self.assertTrue(os.path.isfile(poster_path))
            self.assertTrue(os.path.isfile(icon_path))
            self.assertLess(os.path.getsize(poster_path), 350 * 1024)
            self.assertLess(os.path.getsize(icon_path), 150 * 1024)
            with open(poster_path, 'rb') as pf:
                self.assertEqual(pf.read(8), png_magic)
            with open(icon_path, 'rb') as icf:
                self.assertEqual(icf.read(8), png_magic)

    @tier(1)
    @feature('CR-01')
    def test_cr01_t1_ast_integrity_asset_lint_passes(self):
        method_name = 'test_zero_case_insensitive_asset_collisions_and_oversized_pngs'
        self.assertTrue(hasattr(test_ast_integrity.TestASTIntegrity, method_name))
        suite = unittest.TestSuite([test_ast_integrity.TestASTIntegrity(method_name)])
        result = unittest.TextTestRunner(verbosity=0).run(suite)
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(result.testsRun, 1)

    @tier(2)
    @feature('CR-01')
    def test_cr01_t2_studio_logo_none_and_empty_inputs(self):
        with E2EHermeticEnv('22'):
            from resources.lib.ui import control
            self.assertEqual(control.get_studio_logo_path('', 'coloured'), '')
            self.assertEqual(control.get_studio_logo_path(None, 'coloured'), '')
            self.assertEqual(control.get_studio_logo_path('Madhouse', None), '')
            self.assertEqual(control.get_studio_logo_path('Madhouse', ''), '')
            self.assertEqual(control.get_studio_logo_path('Madhouse', 'none'), '')

    @tier(2)
    @feature('CR-01')
    def test_cr01_t2_studio_logo_unknown_studio_no_crash(self):
        with E2EHermeticEnv('22'):
            from resources.lib.ui import control
            for style in ('coloured', 'white'):
                res = control.get_studio_logo_path('NonExistentStudio_XYZ_999', style)
                self.assertIsInstance(res, str)
                self.assertFalse(os.path.exists(res))

    @tier(2)
    @feature('CR-01')
    def test_cr01_t2_xbmc_add_dir_studio_slash_string_and_sparse_list(self):
        with E2EHermeticEnv('22'):
            import conftest
            from resources.lib.ui import control
            control.setSetting('artwork.studios', 'coloured')

            conftest.mock_xbmcplugin.reset()
            control.xbmc_add_dir(
                'ShowA', 'animes/1', {}, {'title': 'ShowA', 'studio': 'Madhouse / Bones'},
                None, False, True, False,
            )
            li1 = conftest.mock_xbmcplugin.directory_items[0][2]
            self.assertEqual(li1.getProperty('Studio'), 'Madhouse')
            self.assertTrue(os.path.isfile(li1.getArt('studio')))

            conftest.mock_xbmcplugin.reset()
            control.xbmc_add_dir(
                'ShowB', 'animes/2', {}, {'title': 'ShowB', 'studio': [None, '', '  Eight Bit  ']},
                None, False, True, False,
            )
            li2 = conftest.mock_xbmcplugin.directory_items[0][2]
            self.assertEqual(li2.getProperty('Studio'), 'Eight Bit')
            self.assertTrue(os.path.isfile(li2.getArt('studio')))

    @tier(2)
    @feature('CR-01')
    def test_cr01_t2_studio_logo_case_and_punctuation_normalization(self):
        with E2EHermeticEnv('22'):
            from resources.lib.ui import control
            pa1 = control.get_studio_logo_path('P.A.WORKS', 'coloured')
            pa2 = control.get_studio_logo_path('p a works', 'coloured')
            jc = control.get_studio_logo_path('J.C.STAFF', 'coloured')
            ufo1 = control.get_studio_logo_path('ufotable', 'coloured')
            ufo2 = control.get_studio_logo_path('UFOTABLE', 'coloured')
            for p in (pa1, pa2, jc, ufo1, ufo2):
                self.assertTrue(os.path.isfile(p), f"Expected existing PNG for {p}")
            self.assertTrue(os.path.samefile(pa1, pa2))
            self.assertTrue(os.path.samefile(ufo1, ufo2))

    @tier(2)
    @feature('CR-01')
    def test_cr01_t2_addon_xml_declared_assets_exist_and_under_ceiling(self):
        for addon_dir in (ADDON_ROOT, CONTEXT_ROOT, SUBTITLE_ROOT):
            tree = ET.parse(os.path.join(addon_dir, 'addon.xml'))
            assets = tree.getroot().find('.//assets')
            self.assertIsNotNone(assets)
            checked = 0
            for child in assets:
                rel = (child.text or '').strip()
                if rel:
                    asset_path = os.path.join(addon_dir, rel)
                    self.assertTrue(os.path.isfile(asset_path), f"Missing asset {asset_path}")
                    sz = os.path.getsize(asset_path)
                    self.assertGreater(sz, 0)
                    if rel.lower().endswith('.png'):
                        self.assertLess(sz, 600 * 1024, f"Oversized root PNG: {asset_path}")
                    checked += 1
            self.assertGreaterEqual(checked, 2)

    @tier(2)
    @feature('CR-01')
    def test_cr01_t2_studio_logo_index_cache_isolated_between_styles(self):
        with E2EHermeticEnv('22'):
            from resources.lib.ui import control
            control._studio_logo_index_cache.clear()
            c_path = control.get_studio_logo_path('Madhouse', 'coloured')
            w_path = control.get_studio_logo_path('Madhouse', 'white')
            self.assertTrue(os.path.isfile(c_path))
            self.assertTrue(os.path.isfile(w_path))
            self.assertNotEqual(os.path.normpath(c_path), os.path.normpath(w_path))


# ==============================================================================
# CR-02: SQLite WAL / Read-Only URI (?mode=ro) & Recovery Parity
# ==============================================================================

class TestCR02SQLiteWALAndRecovery(unittest.TestCase):
    """CR-02: 6 Tier 1 + 6 Tier 2 opaque-box tests."""

    @tier(1)
    @feature('CR-02')
    def test_cr02_t1_static_dbs_enforce_readonly_uri_and_skip_write_pragmas(self):
        with E2EHermeticEnv('22') as env:
            from resources.lib.ui import control, database
            map_db = os.path.join(env.profile_dir, 'mappings.db')
            with sqlite3.connect(map_db) as c:
                c.execute('CREATE TABLE anime (mal_id INTEGER PRIMARY KEY)')
                c.execute('INSERT INTO anime VALUES (52991)')
                c.commit()
            control.mappingDB = map_db

            connect_calls = []
            orig_connect = database.dbapi2.connect

            def _spy_connect(target, *args, **kwargs):
                connect_calls.append((target, dict(kwargs)))
                return orig_connect(target, *args, **kwargs)

            with patch.object(database.dbapi2, 'connect', side_effect=_spy_connect):
                with database.SQL(control.mappingDB) as cur:
                    cur.execute('SELECT mal_id FROM anime')
                    row = cur.fetchone()
                    self.assertEqual(row['mal_id'], 52991)
                with database.SQL(control.infoDB) as cur2:
                    cur2.execute("SELECT api_name FROM info WHERE api_name='MyAnimeList'")
                    info_row = cur2.fetchone()
                    self.assertEqual(info_row['api_name'], 'MyAnimeList')

            uri_targets = [c[0] for c in connect_calls]
            self.assertIn(f"file:{os.path.abspath(map_db)}?mode=ro", uri_targets)
            self.assertIn(f"file:{os.path.abspath(control.infoDB)}?mode=ro", uri_targets)
            for _tgt, kw in connect_calls:
                self.assertTrue(kw.get('uri'))
                self.assertEqual(float(kw.get('timeout')), 30.0)
            self.assertFalse(os.path.exists(map_db + '-wal'))
            self.assertFalse(os.path.exists(map_db + '-shm'))

    @tier(1)
    @feature('CR-02')
    def test_cr02_t1_mutable_dbs_enable_wal_and_pool_isolates_ro_vs_rw(self):
        with E2EHermeticEnv('22') as env:
            from resources.lib.ui import database
            mut_db = os.path.join(env.profile_dir, 'mut_test.db')
            with database.SQL(mut_db, is_readonly=False) as cur_rw:
                cur_rw.execute('CREATE TABLE t (id INTEGER PRIMARY KEY)')
                cur_rw.execute('INSERT INTO t VALUES (7)')
                cur_rw.connection.commit()
                cur_rw.execute('PRAGMA journal_mode')
                jmode = cur_rw.fetchone()
                self.assertEqual(list(jmode.values())[0].lower(), 'wal')
                conn_rw_1 = cur_rw.connection

            with database.SQL(mut_db, is_readonly=True) as cur_ro:
                conn_ro = cur_ro.connection
                cur_ro.execute('SELECT id FROM t')
                self.assertEqual(cur_ro.fetchone()['id'], 7)

            with database.SQL(mut_db, is_readonly=False) as cur_rw2:
                conn_rw_2 = cur_rw2.connection

            self.assertIsNot(conn_rw_1, conn_ro)
            self.assertIs(conn_rw_1, conn_rw_2)

    @tier(1)
    @feature('CR-02')
    def test_cr02_t1_checkpoint_and_vacuum_operate_on_mutable_skip_static(self):
        with E2EHermeticEnv('22') as env:
            from resources.lib.ui import control, database
            database.cache_insert('ck_key', "'ck_val'")
            database.addSearchHistory('Frieren', 'anime')
            database.update_show('52991', database.dumps({'name': 'Frieren'}))

            map_db = os.path.join(env.profile_dir, 'mappings.db')
            with sqlite3.connect(map_db) as c:
                c.execute('CREATE TABLE anime (mal_id INTEGER PRIMARY KEY)')
                c.commit()
            os.chmod(map_db, 0o444)
            control.mappingDB = map_db
            try:
                database.checkpoint_databases(truncate=True)
                database.vacuum_all_databases()
            finally:
                os.chmod(map_db, 0o644)

            for dbp in (control.cacheFile, control.searchHistoryDB, control.malSyncDB):
                with database.SQL(dbp, is_readonly=True) as cur:
                    cur.execute('PRAGMA integrity_check')
                    res = list(cur.fetchone().values())[0]
                    self.assertEqual(res.lower(), 'ok')

    @tier(1)
    @feature('CR-02')
    def test_cr02_t1_quarantine_and_recover_corrupt_malsync_db_with_syncdatabase(self):
        with E2EHermeticEnv('22'):
            from resources.lib.ui import control, database
            database.close_all_connections(control.malSyncDB)
            with open(control.malSyncDB, 'wb') as f:
                f.write(b'NOT A SQLITE FILE')
            with open(control.malSyncDB + '-wal', 'wb') as fw:
                fw.write(b'corrupt wal')

            database._quarantine_and_recover_db(control.malSyncDB)

            quarantined = [fn for fn in os.listdir(os.path.dirname(control.malSyncDB)) if '.corrupt.' in fn]
            self.assertGreaterEqual(len(quarantined), 2)

            # Recovery must recreate tables cleanly via SyncDatabase (no OtakuDatabase ImportError)
            database.update_show(52991, b'{"name":"Frieren"}')
            row = database.get_show(52991)
            self.assertIsNotNone(row)
            self.assertEqual(row['mal_id'], 52991)

    @tier(1)
    @feature('CR-02')
    def test_cr02_t1_quarantine_and_recover_cache_and_search_dbs(self):
        with E2EHermeticEnv('22'):
            from resources.lib.ui import control, database
            database.close_all_connections()
            for p in (control.cacheFile, control.searchHistoryDB):
                with open(p, 'wb') as f:
                    f.write(b'CORRUPT HEADER BYTES 0123456789')

            database.cache_insert('k1', "'v1'")
            database.addSearchHistory('Frieren', 'anime')

            cached = database.cache_get('k1')
            self.assertIsNotNone(cached)
            self.assertEqual(cached['value'], "'v1'")
            self.assertEqual(database.getSearchHistory('anime'), ['Frieren'])

    @tier(1)
    @feature('CR-02')
    def test_cr02_t1_test_kodi_installs_sqlite_connect_uses_explicit_timeout(self):
        script_path = os.path.join(REPO_ROOT, 'scripts', 'test_kodi_installs.py')
        with open(script_path, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=script_path)

        connect_calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == 'connect' and isinstance(node.func.value, ast.Name) and node.func.value.id == 'sqlite3':
                    has_timeout = any(kw.arg == 'timeout' for kw in node.keywords)
                    connect_calls.append((node.lineno, has_timeout))

        self.assertGreaterEqual(len(connect_calls), 2)
        missing = [ln for ln, ok in connect_calls if not ok]
        self.assertEqual(missing, [], f"sqlite3.connect missing timeout= at lines: {missing}")

        from scripts.test_kodi_installs import seed_test_databases
        with tempfile.TemporaryDirectory(prefix='otaku_seed_') as td:
            seed_test_databases(td)
            addon_data = os.path.join(td, 'userdata', 'addon_data', 'plugin.video.otaku.rpdev')
            with sqlite3.connect(os.path.join(addon_data, 'malSync.db'), timeout=30.0) as c1:
                ep_cnt = c1.execute('SELECT COUNT(*) FROM episodes WHERE mal_id=52991').fetchone()[0]
                self.assertEqual(ep_cnt, 3)
            with sqlite3.connect(os.path.join(addon_data, 'search.db'), timeout=30.0) as c2:
                vals = [r[0] for r in c2.execute('SELECT value FROM anime').fetchall()]
                self.assertIn('Frieren', vals)

    @tier(2)
    @feature('CR-02')
    def test_cr02_t2_readonly_uri_blocks_sql_mutations(self):
        with E2EHermeticEnv('22') as env:
            from resources.lib.ui import control, database
            map_db = os.path.join(env.profile_dir, 'mappings.db')
            with sqlite3.connect(map_db) as c:
                c.execute('CREATE TABLE anime (mal_id INTEGER PRIMARY KEY)')
                c.commit()
            control.mappingDB = map_db
            before_mtime = os.path.getmtime(map_db)
            with open(map_db, 'rb') as f:
                before_bytes = f.read()

            with self.assertRaises(sqlite3.OperationalError) as ctx:
                with database.SQL(control.mappingDB, is_readonly=True) as cur:
                    cur.execute('CREATE TABLE evil (x INT)')
            self.assertIn('readonly', str(ctx.exception).lower())
            with open(map_db, 'rb') as f:
                self.assertEqual(f.read(), before_bytes)
            self.assertEqual(os.path.getmtime(map_db), before_mtime)

    @tier(2)
    @feature('CR-02')
    def test_cr02_t2_missing_mappings_db_returns_empty_without_creating_file(self):
        with E2EHermeticEnv('22') as env:
            from resources.lib.ui import control, database
            missing_path = os.path.join(env.profile_dir, 'nonexistent_mappings.db')
            control.mappingDB = missing_path
            self.assertEqual(database.get_mappings(52991, 'mal_id'), {})
            self.assertEqual(database.get_unique_ids(52991, 'mal_id'), {})
            self.assertEqual(database.get_mal_ids(52991, 'mal_id'), [])
            self.assertFalse(os.path.exists(missing_path))

    @tier(2)
    @feature('CR-02')
    def test_cr02_t2_missing_info_db_falls_back_to_builtin_api_info(self):
        with E2EHermeticEnv('22') as env:
            from resources.lib.ui import control, database
            missing_info = os.path.join(env.profile_dir, 'missing_info.db')
            control.infoDB = missing_info

            mal_info = database.get_info('MyAnimeList')
            rd_info = database.get_info('Real-Debrid')
            unk_info = database.get_info('UnknownAPI_XYZ')

            self.assertTrue(mal_info.get('client_id'))
            self.assertTrue(rd_info.get('client_id'))
            self.assertEqual(unk_info, {'api_name': 'UnknownAPI_XYZ', 'client_id': '', 'client_secret': '', 'api_key': ''})
            self.assertFalse(os.path.exists(missing_info))

    @tier(2)
    @feature('CR-02')
    def test_cr02_t2_inode_replacement_invalidates_pooled_ro_connection(self):
        with E2EHermeticEnv('22') as env:
            from resources.lib.ui import control, database
            map_db = os.path.join(env.profile_dir, 'mappings.db')
            v1_tmp = os.path.join(env.profile_dir, 'mappings_v1.db')
            v2_tmp = os.path.join(env.profile_dir, 'mappings_v2.db')
            with sqlite3.connect(v1_tmp) as c1:
                c1.execute('CREATE TABLE anime (mal_id INTEGER PRIMARY KEY, kitsu_id INTEGER)')
                c1.execute('INSERT INTO anime VALUES (1, 101)')
                c1.commit()
            os.replace(v1_tmp, map_db)
            control.mappingDB = map_db

            self.assertEqual(database.get_mappings(1, 'mal_id').get('kitsu_id'), 101)

            with sqlite3.connect(v2_tmp) as c2:
                c2.execute('CREATE TABLE anime (mal_id INTEGER PRIMARY KEY, kitsu_id INTEGER)')
                c2.execute('INSERT INTO anime VALUES (2, 202)')
                c2.commit()
            os.replace(v2_tmp, map_db)

            self.assertEqual(database.get_mappings(2, 'mal_id').get('kitsu_id'), 202)

    @tier(2)
    @feature('CR-02')
    def test_cr02_t2_execute_write_with_retry_succeeds_and_exhausts_cleanly(self):
        with E2EHermeticEnv('22'):
            from resources.lib.ui import database
            cur = MagicMock()
            cur.execute.side_effect = [
                sqlite3.OperationalError('database is locked'),
                sqlite3.OperationalError('database is locked'),
                'OK_RESULT',
            ]
            res = database.execute_write_with_retry(cur, 'INSERT INTO x VALUES (1)', (), max_retries=3)
            self.assertEqual(res, 'OK_RESULT')
            self.assertEqual(cur.execute.call_count, 3)

            cur2 = MagicMock()
            cur2.execute.side_effect = sqlite3.OperationalError('database is locked')
            with self.assertRaises(sqlite3.OperationalError):
                database.execute_write_with_retry(cur2, 'INSERT INTO x VALUES (2)', (), max_retries=3)
            self.assertEqual(cur2.execute.call_count, 3)

    @tier(2)
    @feature('CR-02')
    def test_cr02_t2_close_thread_and_all_connections_cleans_worker_pools(self):
        with E2EHermeticEnv('22') as env:
            from resources.lib.ui import database
            wdb = os.path.join(env.profile_dir, 'worker_pool.db')

            def _worker():
                with database.SQL(wdb) as cur:
                    cur.execute('CREATE TABLE IF NOT EXISTS w (id INTEGER)')
                    cur.connection.commit()

            t = threading.Thread(target=_worker)
            t.start()
            t.join(timeout=5.0)

            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always', ResourceWarning)
                database.close_thread_connections()
                database.close_all_connections()

            self.assertEqual(len(database._all_thread_conns), 0)
            res_warnings = [w for w in caught if issubclass(w.category, ResourceWarning)]
            self.assertEqual(res_warnings, [])
            os.remove(wdb)
            self.assertFalse(os.path.exists(wdb))


# ==============================================================================
# CR-03: Tri-Addon Kodi 21/22 Modal Disposal, C-06 change_log, & Docs Sync
# ==============================================================================

class TestCR03ModalDisposalAndDocsSync(unittest.TestCase):
    """CR-03: 6 Tier 1 + 6 Tier 2 opaque-box tests."""

    @tier(1)
    @feature('CR-03')
    def test_cr03_t1_change_log_route_opens_disposes_and_exits_cleanly(self):
        with E2EHermeticEnv('22', strict_skin_controls=True):
            from resources.lib.ui import control
            from resources.lib.windows.base_window import BaseWindow

            control.setSetting('changelog.version', '0.0.0')
            seen_xmls = []

            def _tv_domodal(self_win):
                seen_xmls.append(self_win._xml_file if hasattr(self_win, '_xml_file') else 'textviewer.xml')
                self_win.onInit()
                self_win.onClick(2062)

            with patch('xbmcgui.WindowXMLDialog.doModal', new=_tv_domodal), \
                 patch.object(control, 'exit_code', wraps=control.exit_code) as mock_exit:
                res = invoke_plugin_route('change_log', handle=3)

            self.assertGreaterEqual(len(seen_xmls), 1)
            self.assertEqual(control.getSetting('changelog.version'), control.ADDON_VERSION)
            self.assertEqual(control.getSetting('otaku.version'), control.ADDON_VERSION)
            mock_exit.assert_called()
            self.assertEqual(len(list(BaseWindow._active_windows)), 0)
            self.assertIsInstance(res['directory_items'], list)

    @tier(1)
    @feature('CR-03')
    def test_cr03_t1_solver_inst_and_sort_select_and_source_filter_dispose_modals(self):
        with E2EHermeticEnv('22', strict_skin_controls=True):
            from resources.lib.windows.base_window import BaseWindow
            inits = []

            def _simulate_modal(self_win):
                inits.append(type(self_win).__name__)
                if hasattr(self_win, 'onInit'):
                    self_win.onInit()
                self_win.close()

            with patch('xbmcgui.WindowXMLDialog.doModal', new=_simulate_modal):
                invoke_plugin_route('solver_inst', handle=4)
                invoke_plugin_route('sort_select', handle=5)
                invoke_plugin_route('source_filter', handle=6)

            self.assertIn('TextViewerXML', inits)
            self.assertIn('SortSelect', inits)
            self.assertIn('FilterSelect', inits)
            self.assertEqual(len(list(BaseWindow._active_windows)), 0)

    @tier(1)
    @feature('CR-03')
    def test_cr03_t1_anime_statistics_route_populates_and_disposes_stats_window(self):
        with E2EHermeticEnv('22', strict_skin_controls=True):
            from resources.lib import MetaBrowser
            from resources.lib.windows.base_window import BaseWindow

            payload = {
                'total': 1000,
                'watching': 100,
                'completed': 700,
                'on_hold': 50,
                'dropped': 50,
                'plan_to_watch': 100,
                'scores': [{'score': i, 'percentage': 10, 'votes': 100} for i in range(1, 11)],
            }
            captured_props = {}

            def _stats_modal(self_win):
                self_win.onInit()
                captured_props['total'] = self_win.getProperty('otaku.stats.total')
                captured_props['bar10'] = self_win.getControl(4010)._percent
                self_win.onClick(3001)

            mock_browser = MagicMock()
            mock_browser.get_statistics_payload.return_value = payload
            with patch.object(MetaBrowser, '_get_browser', return_value=mock_browser), \
                 patch('xbmcgui.WindowXMLDialog.doModal', new=_stats_modal):
                invoke_plugin_route('anime_statistics/52991', handle=8)

            self.assertEqual(captured_props.get('total'), '1,000')
            self.assertEqual(captured_props.get('bar10'), 100.0)
            self.assertEqual(len(list(BaseWindow._active_windows)), 0)

    @tier(1)
    @feature('CR-03')
    def test_cr03_t1_ast_all_domodal_and_run_calls_wrapped_in_try_finally(self):
        targets = [
            os.path.join(ADDON_ROOT, 'resources', 'lib', 'routes', 'tools.py'),
            os.path.join(ADDON_ROOT, 'service.py'),
            os.path.join(ADDON_ROOT, 'resources', 'lib', 'Main.py'),
            os.path.join(ADDON_ROOT, 'resources', 'lib', 'WatchlistIntegration.py'),
        ]
        bare_calls = []
        for path in targets:
            with open(path, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read(), filename=path)

            def _walk(node, in_try_finally=False):
                if isinstance(node, ast.FunctionDef) and node.name in ('doModal', 'run'):
                    return
                if isinstance(node, ast.Try):
                    for stmt in node.body:
                        _walk(stmt, in_try_finally=bool(node.finalbody) or in_try_finally)
                    for h in node.handlers:
                        _walk(h, in_try_finally=bool(node.finalbody) or in_try_finally)
                    for stmt in node.orelse:
                        _walk(stmt, in_try_finally=bool(node.finalbody) or in_try_finally)
                    for stmt in node.finalbody:
                        _walk(stmt, in_try_finally=in_try_finally)
                    return
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr in ('doModal', 'run'):
                        if not in_try_finally:
                            bare_calls.append((os.path.relpath(path, REPO_ROOT), node.lineno, node.func.attr))
                for child in ast.iter_child_nodes(node):
                    _walk(child, in_try_finally=in_try_finally)

            _walk(tree, False)

        self.assertEqual(bare_calls, [], f"Bare .doModal()/.run() calls without try...finally: {bare_calls}")

    @tier(1)
    @feature('CR-03')
    def test_cr03_t1_agents_md_budget_and_docs_lint_suite_pass(self):
        agents_size = os.path.getsize(os.path.join(REPO_ROOT, 'AGENTS.md'))
        self.assertLess(agents_size, 22000)
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(test_docs_and_customizations.TestDocsAndCustomizations)
        res = unittest.TextTestRunner(verbosity=0).run(suite)
        self.assertTrue(res.wasSuccessful())
        self.assertGreaterEqual(res.testsRun, 5)

    @tier(1)
    @feature('CR-03')
    def test_cr03_t1_service_subtitles_addon_documented_across_all_docs(self):
        doc_paths = [
            'AGENTS.md',
            'CHANGEREPORT.md',
            'docs/ARCHITECTURE.md',
            'docs/TESTING.md',
            'docs/AUTOMATION.md',
            'docs/CONFIGURATION_GUIDE.md',
            'docs/README.md',
        ]
        missing = []
        for rel in doc_paths:
            with open(os.path.join(REPO_ROOT, rel), 'r', encoding='utf-8') as f:
                if 'service.subtitles.otaku.rpdev' not in f.read():
                    missing.append(rel)
        self.assertEqual(missing, [], f"Docs missing service.subtitles.otaku.rpdev: {missing}")

    @tier(2)
    @feature('CR-03')
    def test_cr03_t2_change_log_and_solver_inst_missing_txt_files_no_crash(self):
        with E2EHermeticEnv('22', strict_skin_controls=True):
            from resources.lib.ui import control
            import service
            captured_props = {}

            def _tv_capture(self_win):
                self_win.onInit()
                captured_props['changelog'] = self_win.getProperty('otaku.changelog_text')
                captured_props['news'] = self_win.getProperty('otaku.news_text')
                captured_props['text'] = self_win.getProperty('otaku.text')
                self_win.close()

            with tempfile.TemporaryDirectory(prefix='otaku_notxt_') as empty_dir:
                with patch.object(control, 'ADDON_PATH', empty_dir), \
                     patch('xbmcgui.WindowXMLDialog.doModal', new=_tv_capture):
                    service.getChangeLog()
                    service.getInstructions()

            self.assertEqual(captured_props.get('changelog'), '')
            self.assertEqual(captured_props.get('news'), '')
            self.assertEqual(captured_props.get('text'), '')

    @tier(2)
    @feature('CR-03')
    def test_cr03_t2_modal_exception_during_domodal_still_cleans_up(self):
        with E2EHermeticEnv('22', strict_skin_controls=True):
            from resources.lib import MetaBrowser
            from resources.lib.windows.base_window import BaseWindow

            payload = {'total': 10, 'watching': 1, 'completed': 5, 'on_hold': 1, 'dropped': 1, 'plan_to_watch': 2, 'scores': []}
            mock_browser = MagicMock()
            mock_browser.get_statistics_payload.return_value = payload
            for route in ('sort_select', 'source_filter', 'change_log', 'anime_statistics/52991'):
                with patch.object(MetaBrowser, '_get_browser', return_value=mock_browser), \
                     patch('xbmcgui.WindowXMLDialog.doModal', side_effect=RuntimeError('simulated modal error')):
                    invoke_plugin_route(route, handle=12)
                self.assertEqual(len(list(BaseWindow._active_windows)), 0)

    @tier(2)
    @feature('CR-03')
    def test_cr03_t2_textviewer_and_stats_window_dismiss_on_all_back_actions(self):
        with E2EHermeticEnv('22', strict_skin_controls=True):
            from resources.lib.windows.textviewer import TextViewerXML
            from resources.lib.windows.stats_window import StatsWindow

            for aid in (9, 10, 92, 216):
                tv = TextViewerXML('textviewer.xml', ADDON_ROOT, heading='H', changelog_text='C', news_text='N')
                tv.onInit()
                tv.onAction(type('Act', (), {'getId': lambda _s, a=aid: a})())
                self.assertTrue(tv.actioned)

                sw = StatsWindow('anime_statistics.xml', ADDON_ROOT, stats={'total': 5, 'scores': []}, heading='Stats')
                sw.onInit()
                closed = []
                sw.close = lambda c=closed: c.append(aid)
                sw.onAction(type('Act', (), {'getId': lambda _s, a=aid: a})())
                self.assertEqual(closed, [aid])

            tv_btn = TextViewerXML('textviewer.xml', ADDON_ROOT, heading='H')
            tv_btn.onClick(2062)
            self.assertTrue(tv_btn.actioned)

            sw_btn = StatsWindow('anime_statistics.xml', ADDON_ROOT, stats={'total': 5, 'scores': []}, heading='Stats')
            btn_closed = []
            sw_btn.close = lambda: btn_closed.append(3001)
            sw_btn.onClick(3001)
            self.assertEqual(btn_closed, [3001])

    @tier(2)
    @feature('CR-03')
    def test_cr03_t2_anime_statistics_empty_id_or_empty_payload_notifies_without_modal(self):
        with E2EHermeticEnv('22', strict_skin_controls=True) as env:
            from resources.lib import MetaBrowser
            from resources.lib.ui import control

            mock_browser = MagicMock()
            mock_browser.get_statistics_payload.return_value = None
            with patch('xbmcgui.WindowXMLDialog.doModal') as mock_domodal:
                with patch.object(MetaBrowser, '_get_browser', return_value=mock_browser):
                    invoke_plugin_route('anime_statistics/', handle=13)
                    invoke_plugin_route('anime_statistics/52991', handle=14)
            mock_domodal.assert_not_called()
            self.assertGreaterEqual(len(env.dialog_capture.notifications), 2)
            self.assertEqual(env.dialog_capture.notifications[-1]['message'], control.lang(30463))

    @tier(2)
    @feature('CR-03')
    def test_cr03_t2_root_default_py_changelog_auto_dispatch_guards(self):
        import conftest
        with E2EHermeticEnv('22'):
            from resources.lib.ui import control
            with patch('resources.lib.Main._draw_category_main_menu', return_value=None):
                # (a) showchangelog == 1
                control.setSetting('otaku.version', '0.0.0')
                control.setSetting('changelog.version', '0.0.0')
                control.setInt('showchangelog', 1)
                with patch.object(control, 'is_addon_visible', return_value=True):
                    res_a = invoke_plugin_route('', handle=15)
                self.assertFalse(any('change_log' in c for c in res_a['executebuiltin_calls']))
                self.assertEqual(control.getSetting('otaku.version'), control.ADDON_VERSION)

                # (b) Player().isPlaying() == True
                control.setSetting('otaku.version', '0.0.0')
                control.setSetting('changelog.version', '0.0.0')
                control.setInt('showchangelog', 0)
                with patch.object(control, 'is_addon_visible', return_value=True), \
                     patch.object(conftest.mock_xbmc.Player, 'isPlaying', return_value=True):
                    res_b = invoke_plugin_route('', handle=16)
                self.assertFalse(any('change_log' in c for c in res_b['executebuiltin_calls']))

                # (c) is_addon_visible() == False
                control.setSetting('otaku.version', '0.0.0')
                control.setSetting('changelog.version', '0.0.0')
                with patch.object(control, 'is_addon_visible', return_value=False):
                    res_c = invoke_plugin_route('', handle=17)
                self.assertFalse(any('change_log' in c for c in res_c['executebuiltin_calls']))

    @tier(2)
    @feature('CR-03')
    def test_cr03_t2_kodi_21_and_22_compat_on_tools_modals_and_changelog(self):
        assert_repo_clean_of_leaks()
        for ver in ('21', '22'):
            with E2EHermeticEnv(ver, strict_skin_controls=(ver == '22')):
                with patch('xbmcgui.WindowXMLDialog.doModal', new=lambda s: s.onInit() if hasattr(s, 'onInit') else None):
                    invoke_plugin_route('change_log', handle=18)
                    invoke_plugin_route('sort_select', handle=19)
                    invoke_plugin_route('source_filter', handle=20)
        assert_repo_clean_of_leaks()


# ==============================================================================
# CR-04: CI/Release Hardening & Tri-Addon Packaging Parity
# ==============================================================================

class TestCR04CIReleaseAndPackaging(unittest.TestCase):
    """CR-04: 6 Tier 1 + 6 Tier 2 opaque-box tests."""

    @tier(1)
    @feature('CR-04')
    def test_cr04_t1_tri_addon_manifests_and_acyclic_dependencies(self):
        addons = {}
        for aid in ('plugin.video.otaku.rpdev', 'context.otaku.rpdev', 'service.subtitles.otaku.rpdev'):
            tree = ET.parse(os.path.join(REPO_ROOT, aid, 'addon.xml'))
            root = tree.getroot()
            self.assertEqual(root.get('id'), aid)
            imps = {imp.get('addon') for imp in root.findall('./requires/import') if imp.get('addon')}
            exts = {ext.get('point') for ext in root.findall('./extension') if ext.get('point')}
            addons[aid] = (imps, exts)

        self.assertIn('context.otaku.rpdev', addons['plugin.video.otaku.rpdev'][0])
        self.assertIn('service.subtitles.otaku.rpdev', addons['plugin.video.otaku.rpdev'][0])
        self.assertIn('xbmc.python.pluginsource', addons['plugin.video.otaku.rpdev'][1])
        self.assertIn('xbmc.service', addons['plugin.video.otaku.rpdev'][1])
        self.assertEqual(addons['context.otaku.rpdev'][0], {'xbmc.python'})
        self.assertIn('kodi.context.item', addons['context.otaku.rpdev'][1])
        self.assertEqual(addons['service.subtitles.otaku.rpdev'][0], {'xbmc.python'})
        self.assertIn('xbmc.subtitle.module', addons['service.subtitles.otaku.rpdev'][1])

    @tier(1)
    @feature('CR-04')
    def test_cr04_t1_workflows_enforce_verify_all_and_tri_addon_packaging(self):
        with open(os.path.join(REPO_ROOT, '.github', 'workflows', 'ci.yml'), 'r', encoding='utf-8') as f:
            ci_yml = f.read()
        with open(os.path.join(REPO_ROOT, '.github', 'workflows', 'release.yml'), 'r', encoding='utf-8') as f:
            rel_yml = f.read()

        self.assertIn('scripts/verify_all.py', ci_yml)
        self.assertIn('--fail-below', ci_yml)
        for pyver in ('3.11', '3.12', '3.13'):
            self.assertIn(pyver, ci_yml)

        self.assertIn('scripts/verify_all.py', rel_yml)
        self.assertIn('--fail-below', rel_yml)
        for aid in ('plugin.video.otaku.rpdev', 'context.otaku.rpdev', 'service.subtitles.otaku.rpdev'):
            self.assertIn(aid, rel_yml)
        self.assertIn('SHA256SUMS.txt', rel_yml)
        self.assertIn('MD5SUMS.txt', rel_yml)
        self.assertIn('cdn-repo', rel_yml)

    @tier(1)
    @feature('CR-04')
    def test_cr04_t1_release_addon_dry_run_validates_current_metadata(self):
        ver = ET.parse(os.path.join(ADDON_ROOT, 'addon.xml')).getroot().get('version')
        proc = run_cli_script(
            'scripts/release_addon.py',
            ['--version', ver, '--dry-run', '--skip-tests'],
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn(f'verified for v{ver}', proc.stdout)
        self.assertIn('[DRY RUN]', proc.stdout)

    @tier(1)
    @feature('CR-04')
    def test_cr04_t1_tri_addon_zip_packaging_and_checksum_generation(self):
        from scripts import release_addon
        with tempfile.TemporaryDirectory(prefix='otaku_zip_') as out_dir:
            zip_paths = []
            for aid, entry in (
                ('plugin.video.otaku.rpdev', 'default.py'),
                ('context.otaku.rpdev', 'default.py'),
                ('service.subtitles.otaku.rpdev', 'service.py'),
            ):
                src_dir = os.path.join(REPO_ROOT, aid)
                ver, _ = release_addon.get_addon_xml_version_and_news(os.path.join(src_dir, 'addon.xml'))
                zpath = os.path.join(out_dir, f'{aid}-{ver}.zip')
                excl_dirs = {'__pycache__', 'tests', 'scratch'}
                if aid == 'context.otaku.rpdev':
                    excl_dirs.add('scripts')

                with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for root, dirnames, filenames in os.walk(src_dir):
                        dirnames[:] = [d for d in dirnames if d not in excl_dirs and not d.startswith('.')]
                        for fn in filenames:
                            if fn.startswith('.') or fn.endswith(('.pyc', '.pyo')):
                                continue
                            full = os.path.join(root, fn)
                            arc = os.path.join(aid, os.path.relpath(full, src_dir))
                            zf.write(full, arc)

                with zipfile.ZipFile(zpath, 'r') as zf:
                    names = zf.namelist()
                    self.assertIn(f'{aid}/addon.xml', names)
                    self.assertIn(f'{aid}/{entry}', names)
                    self.assertFalse(any('__pycache__' in n or n.endswith(('.pyc', '.pyo')) for n in names))
                    lowered = [n.lower() for n in names]
                    self.assertEqual(len(set(lowered)), len(lowered))
                zip_paths.append(zpath)

            sha_lines = []
            md5_lines = []
            for zp in zip_paths:
                with open(zp, 'rb') as zf:
                    data = zf.read()
                sha_lines.append(f"{hashlib.sha256(data).hexdigest()}  {os.path.basename(zp)}\n")
                md5_lines.append(f"{hashlib.md5(data).hexdigest()}  {os.path.basename(zp)}\n")
            sha_file = os.path.join(out_dir, 'SHA256SUMS.txt')
            md5_file = os.path.join(out_dir, 'MD5SUMS.txt')
            with open(sha_file, 'w', encoding='utf-8') as sf:
                sf.writelines(sha_lines)
            with open(md5_file, 'w', encoding='utf-8') as mf:
                mf.writelines(md5_lines)
            with open(sha_file, encoding='utf-8') as sf_in:
                self.assertEqual(len(sf_in.readlines()), 3)
            with open(md5_file, encoding='utf-8') as mf_in:
                self.assertEqual(len(mf_in.readlines()), 3)

    @tier(1)
    @feature('CR-04')
    def test_cr04_t1_verify_all_cli_and_targeted_coverage_json(self):
        help_proc = run_cli_script('scripts/verify_all.py', ['--help'])
        self.assertEqual(help_proc.returncode, 0)
        for flag in ('--fail-below', '--skip-coverage', '--e2e', '--no-strict-warnings', '--json'):
            self.assertIn(flag, help_proc.stdout)

        with tempfile.TemporaryDirectory(prefix='otaku_cov_') as td:
            cov_json = os.path.join(td, 'cov.json')
            cov_proc = run_cli_script(
                'scripts/audit_function_coverage.py',
                ['--test-target', 'tests.lint.test_ast_integrity', '--fail-below', '0', '--json', cov_json],
            )
            self.assertIn(cov_proc.returncode, (0, 1))
            with open(cov_json, 'r', encoding='utf-8') as jf:
                data = e2e_helpers.conftest.sys.modules['json'].load(jf)
            self.assertGreaterEqual(data['summary']['total_source_files'], 144)
            self.assertIn('module_coverage_pct', data['summary'])
            self.assertIn('function_coverage_pct', data['summary'])
            self.assertTrue(data.get('files'))

    @tier(1)
    @feature('CR-04')
    def test_cr04_t1_news_txt_and_changelog_release_metadata_format(self):
        from scripts import release_addon
        addon_xml = os.path.join(ADDON_ROOT, 'addon.xml')
        news_path = os.path.join(ADDON_ROOT, 'news.txt')
        changelog_path = os.path.join(ADDON_ROOT, 'changelog.txt')
        ver, _ = release_addon.get_addon_xml_version_and_news(addon_xml)

        errors = release_addon.validate_release_metadata(addon_xml, news_path, changelog_path, ver)
        self.assertEqual(errors, [])

        with open(news_path, 'r', encoding='utf-8') as nf:
            news_lines = nf.read().splitlines()
        self.assertTrue(any(f'[B]OTAKU RPDEV v{ver}[/B]' in ln for ln in news_lines[:15]))
        for ln in news_lines:
            s = ln.strip()
            if s and (set(s) == {'='} or set(s) == {'-'}):
                self.assertLessEqual(len(s), 32)

        with open(changelog_path, 'r', encoding='utf-8') as cf:
            head = cf.readline()
        self.assertRegex(head, rf'^Changelog v{re.escape(ver)} \(\d{{4}}-\d{{2}}-\d{{2}}\):')

    @tier(2)
    @feature('CR-04')
    def test_cr04_t2_release_metadata_rejects_version_mismatch(self):
        from scripts import release_addon
        with tempfile.TemporaryDirectory(prefix='otaku_rel_mm_') as td:
            axml = os.path.join(td, 'addon.xml')
            news = os.path.join(td, 'news.txt')
            chg = os.path.join(td, 'changelog.txt')
            with open(axml, 'w', encoding='utf-8') as f:
                f.write('<addon id="plugin.video.otaku.rpdev" version="6.2.99"><extension point="xbmc.addon.metadata"><news>v6.2.99</news></extension></addon>')
            with open(news, 'w', encoding='utf-8') as f:
                f.write('========================\n[B]OTAKU RPDEV v6.3.0[/B]\n========================\n')
            with open(chg, 'w', encoding='utf-8') as f:
                f.write('Changelog v6.3.0 (2026-11-21):\n- ok\n')
            errs = release_addon.validate_release_metadata(axml, news, chg, '6.3.0')
            self.assertTrue(any("addon.xml version is '6.2.99', expected '6.3.0'" in e for e in errs))

    @tier(2)
    @feature('CR-04')
    def test_cr04_t2_news_txt_divider_32_vs_33_char_boundary(self):
        from scripts import release_addon
        with tempfile.TemporaryDirectory(prefix='otaku_div_') as td:
            axml = os.path.join(td, 'addon.xml')
            news = os.path.join(td, 'news.txt')
            chg = os.path.join(td, 'changelog.txt')
            with open(axml, 'w', encoding='utf-8') as f:
                f.write('<addon id="plugin.video.otaku.rpdev" version="6.3.0"><extension point="xbmc.addon.metadata"><news>v6.3.0</news></extension></addon>')
            with open(chg, 'w', encoding='utf-8') as f:
                f.write('Changelog v6.3.0 (2026-11-21):\n- ok\n')

            with open(news, 'w', encoding='utf-8') as f:
                f.write(f"{'=' * 32}\n[B]OTAKU RPDEV v6.3.0[/B]\n{'-' * 32}\n")
            self.assertEqual(release_addon.validate_release_metadata(axml, news, chg, '6.3.0'), [])

            with open(news, 'w', encoding='utf-8') as f:
                f.write(f"{'=' * 33}\n[B]OTAKU RPDEV v6.3.0[/B]\n{'-' * 33}\n")
            errs = release_addon.validate_release_metadata(axml, news, chg, '6.3.0')
            self.assertEqual(len(errs), 2)
            self.assertTrue(all('divider length is 33 chars (max 32)' in e for e in errs))

    @tier(2)
    @feature('CR-04')
    def test_cr04_t2_circular_addon_dependency_cycle_detection_boundary(self):
        with tempfile.TemporaryDirectory(prefix='otaku_cyc_') as td:
            manifests = {
                'plugin.video.otaku.rpdev': ['context.otaku.rpdev'],
                'context.otaku.rpdev': ['service.subtitles.otaku.rpdev'],
                'service.subtitles.otaku.rpdev': ['plugin.video.otaku.rpdev'],
            }
            graph = {}
            for aid, deps in manifests.items():
                adir = os.path.join(td, aid)
                os.makedirs(adir, exist_ok=True)
                imp_xml = ''.join(f'<import addon="{d}" version="1.0.0"/>' for d in deps)
                with open(os.path.join(adir, 'addon.xml'), 'w', encoding='utf-8') as f:
                    f.write(f'<addon id="{aid}" version="1.0.0"><requires>{imp_xml}</requires></addon>')
                tree = ET.parse(os.path.join(adir, 'addon.xml'))
                graph[aid] = [e.get('addon') for e in tree.getroot().findall('./requires/import')]

            cycles = []
            state = {}

            def _dfs(node, stack):
                state[node] = 1
                stack.append(node)
                for nxt in graph.get(node, []):
                    if nxt in graph:
                        if state.get(nxt) == 1:
                            idx = stack.index(nxt)
                            cycles.append(' -> '.join(stack[idx:] + [nxt]))
                        elif state.get(nxt, 0) == 0:
                            _dfs(nxt, stack)
                stack.pop()
                state[node] = 2

            for node in graph:
                if state.get(node, 0) == 0:
                    _dfs(node, [])

            self.assertEqual(
                cycles,
                ['plugin.video.otaku.rpdev -> context.otaku.rpdev -> service.subtitles.otaku.rpdev -> plugin.video.otaku.rpdev'],
            )

    @tier(2)
    @feature('CR-04')
    def test_cr04_t2_audit_coverage_fail_below_threshold_boundary(self):
        proc = run_cli_script(
            'scripts/audit_function_coverage.py',
            ['--test-target', 'tests.lint.test_docs_and_customizations', '--fail-below', '65.0'],
        )
        self.assertEqual(proc.returncode, 1)
        combined = proc.stdout + proc.stderr
        self.assertIn('[FAIL]', combined)
        self.assertIn('65.0%', combined)

    @tier(2)
    @feature('CR-04')
    def test_cr04_t2_release_addon_bump_version_and_news_demotion(self):
        from scripts import release_addon
        self.assertEqual(release_addon.calculate_next_version('6.2.19', bump_type='patch'), '6.2.20')
        self.assertEqual(release_addon.calculate_next_version('6.2.19', bump_type='minor'), '6.3.0')
        self.assertEqual(release_addon.calculate_next_version('6.2.19', bump_type='major'), '7.0.0')
        self.assertEqual(release_addon.calculate_next_version('6.2', bump_type='patch'), '6.2.1')
        self.assertEqual(release_addon.calculate_next_version('6.2.19', explicit_ver='v6.3.0'), '6.3.0')

        with tempfile.TemporaryDirectory(prefix='otaku_news_demote_') as td:
            news_p = os.path.join(td, 'news.txt')
            with open(news_p, 'w', encoding='utf-8') as f:
                f.write("========================================\n[B]OTAKU RPDEV v6.2.19[/B]\n========================================\nOld item\n")
            release_addon.update_news_txt(news_p, '6.3.0', 'v6.3.0 Release', ['Feature one'])
            with open(news_p, encoding='utf-8') as nf:
                content = nf.read()
            self.assertIn('[B]OTAKU RPDEV v6.3.0[/B]', content)
            self.assertIn('-' * 32, content)
            for ln in content.splitlines():
                s = ln.strip()
                if s and (set(s) == {'='} or set(s) == {'-'}):
                    self.assertLessEqual(len(s), 32)

    @tier(2)
    @feature('CR-04')
    def test_cr04_t2_release_metadata_missing_files_and_stale_changelog(self):
        from scripts import release_addon
        with tempfile.TemporaryDirectory(prefix='otaku_rel_miss_') as td:
            axml = os.path.join(td, 'addon.xml')
            news = os.path.join(td, 'news.txt')
            chg = os.path.join(td, 'changelog.txt')
            with open(axml, 'w', encoding='utf-8') as f:
                f.write('<addon id="plugin.video.otaku.rpdev" version="6.3.0"><extension point="xbmc.addon.metadata"><news>v6.3.0</news></extension></addon>')

            errs_missing = release_addon.validate_release_metadata(axml, news, chg, '6.3.0')
            self.assertTrue(any('Missing' in e and 'news.txt' in e for e in errs_missing))
            self.assertTrue(any('Missing' in e and 'changelog.txt' in e for e in errs_missing))

            with open(news, 'w', encoding='utf-8') as f:
                f.write('[B]OTAKU RPDEV v6.3.0[/B]\n')
            with open(chg, 'w', encoding='utf-8') as f:
                f.write('Changelog v6.2.19 (2026-11-20):\n- old\n')
            errs_stale = release_addon.validate_release_metadata(axml, news, chg, '6.3.0')
            self.assertTrue(any('changelog.txt does not start with' in e for e in errs_stale))


# ==============================================================================
# CR-05: Abort-Safe waitForAbort Sweep & _SENSITIVE_SETTING_KEYS Log Redaction
# ==============================================================================

class TestCR05AbortLoopsAndSanitizeLog(unittest.TestCase):
    """CR-05: 6 Tier 1 + 6 Tier 2 opaque-box tests."""

    @tier(1)
    @feature('CR-05')
    def test_cr05_t1_mal_update_calendar_aborts_immediately(self):
        with E2EHermeticEnv('22'), E2EMockServer() as srv:
            from resources.lib.ui import control
            from resources.lib.endpoints import mal as mal_mod

            def _sched(req_handler, method, path, parsed, headers, body):
                send_http_response(req_handler, status=500, body='err')
                return True

            srv.add_route('/schedules', _sched)
            control.monitor._get_monitor().requestAbort()

            orig_base = mal_mod.Mal._BASE_URL
            mal_mod.Mal._BASE_URL = srv.get_base_url()
            t0 = time.monotonic()
            try:
                mal_mod.Mal().update_calendar()
            finally:
                mal_mod.Mal._BASE_URL = orig_base
            elapsed = time.monotonic() - t0
            self.assertLess(elapsed, 0.5)

    @tier(1)
    @feature('CR-05')
    def test_cr05_t1_indexers_exit_under_500ms_on_abort(self):
        with E2EHermeticEnv('22') as env, E2EMockServer() as srv:
            from resources.lib.ui import control
            from resources.lib.indexers import anidb, jikanmoe, kitsu, otaku

            map_db = os.path.join(env.profile_dir, 'mappings.db')
            with sqlite3.connect(map_db) as c:
                c.execute('CREATE TABLE anime (mal_id INTEGER PRIMARY KEY, anidb_id INTEGER, kitsu_id INTEGER)')
                c.execute('INSERT INTO anime VALUES (52991, 17617, 46789)')
                c.commit()
            control.mappingDB = map_db

            anidb_xml = '<anime><titles><title>Frieren</title></titles><episodes><episode><epno>1</epno><title>Ep1</title><length>24</length><airdate>2023-09-29</airdate></episode></episodes></anime>'
            jikan_pages = {'pagination': {'has_next_page': True, 'last_visible_page': 4}, 'data': [{'mal_id': 1, 'title': 'Ep1', 'aired': '2023-09-29'}]}
            kitsu_hits = [0]

            def _idx_handler(req_handler, method, path, parsed, headers, body):
                if path == '/anidb':
                    send_http_response(req_handler, 200, anidb_xml, 'application/xml')
                    return True
                if path.startswith('/kitsu'):
                    kitsu_hits[0] += 1
                    kitsu_payload = {'data': [{'attributes': {'number': kitsu_hits[0], 'canonicalTitle': f'Ep{kitsu_hits[0]}', 'airdate': '2023-09-29'}}], 'links': {}}
                    if kitsu_hits[0] < 3:
                        kitsu_payload['links']['next'] = f'{srv.get_base_url()}/kitsu/next'
                    send_http_response(req_handler, 200, e2e_helpers.conftest.sys.modules['json'].dumps(kitsu_payload), 'application/json')
                    return True
                if path.startswith('/anime/'):
                    send_http_response(req_handler, 200, e2e_helpers.conftest.sys.modules['json'].dumps(jikan_pages), 'application/json')
                    return True
                return False

            srv._custom_handler = _idx_handler

            control.setInt('anidb_last_request', int(time.time()))
            control.monitor._get_monitor().requestAbort()

            anidb_api = anidb.ANIDBAPI()
            anidb_api.base_url = f"{srv.get_base_url()}/anidb"
            kitsu_api = kitsu.KitsuAPI()
            kitsu_api.baseUrl = f"{srv.get_base_url()}/kitsu"
            otaku_api = otaku.OtakuAPI()
            otaku_api.baseUrl = srv.get_base_url()
            otaku_api.kitsuBaseUrl = f"{srv.get_base_url()}/kitsu"
            otaku_api.anidbBaseUrl = f"{srv.get_base_url()}/anidb"
            jikan_api = jikanmoe.JikanAPI()
            jikan_api.baseUrl = srv.get_base_url()

            t0 = time.monotonic()
            anidb_api.get_episode_meta(52991)
            kitsu_api.get_episode_meta(46789)
            otaku_api.get_episode_meta(52991)
            otaku_api.get_anidb_episode_meta(52991)
            otaku_api.get_kitsu_episode_meta(52991)
            jikan_api.get_episode_meta(52991)
            self.assertLess(time.monotonic() - t0, 0.5)

    @tier(1)
    @feature('CR-05')
    def test_cr05_t1_animeschedule_calendar_and_route_search_aborts(self):
        with E2EHermeticEnv('22'), E2EMockServer() as srv:
            from resources.lib import AnimeSchedule
            from resources.lib.ui import control

            timetable = [
                {'route': f'show-{i}', 'title': f'Show {i}', 'episodeNumber': 1, 'airType': 'sub', 'episodeDate': '2026-11-21T12:00:00Z'}
                for i in range(12)
            ]

            def _as_handler(req_handler, method, path, parsed, headers, body):
                if path.startswith('/timetables'):
                    send_http_response(req_handler, 200, e2e_helpers.conftest.sys.modules['json'].dumps(timetable), 'application/json')
                    return True
                send_http_response(req_handler, 500, 'err')
                return True

            srv._custom_handler = _as_handler
            control.monitor._get_monitor().requestAbort()

            orig_base = AnimeSchedule.BASE_URL
            AnimeSchedule.BASE_URL = srv.get_base_url()
            t0 = time.monotonic()
            try:
                cal = AnimeSchedule.AnimeScheduleCalendar()
                cal.token = 'test_token'
                res = cal.get_calendar_data(days=1, types=['sub'], force_refresh=True)
            finally:
                AnimeSchedule.BASE_URL = orig_base
            elapsed = time.monotonic() - t0
            self.assertLess(elapsed, 0.5)
            self.assertIsInstance(res, list)

    @tier(1)
    @feature('CR-05')
    def test_cr05_t1_sanitize_log_redacts_all_cr05_sensitive_setting_keys(self):
        with E2EHermeticEnv('22'):
            import conftest
            from resources.lib.ui import control
            keys = (
                'realdebrid.token', 'mal.token', 'kitsu.token', 'simkl.token',
                'subtitles.subdl.apikey', 'subtitles.subsource.apikey',
                'subtitles.opensubtitles.password', 'animeskip.apikey', 'easynews.password',
            )
            conftest.mock_xbmc.log.reset_mock()
            for idx, key in enumerate(keys):
                secret = f'sec_{idx}_ABCDEFGH99'
                control.setSetting(key, secret)
                control.log(f'https://api.example.com auth error secret={secret}', 'info')
                logged = str(conftest.mock_xbmc.log.call_args[0][0])
                self.assertNotIn(secret, logged, f"Secret leaked for {key}")
                self.assertIn('[REDACTED]', logged)

    @tier(1)
    @feature('CR-05')
    def test_cr05_t1_sanitize_log_redacts_bearer_url_json_and_basic_auth(self):
        with E2EHermeticEnv('22'):
            import conftest
            from resources.lib.ui import control
            cases = [
                ('Bearer tok_12345678', 'Bearer [REDACTED]', 'tok_12345678'),
                ('GET https://x.test/ep?api_key=abc999&token=xyz111', '[REDACTED]', 'abc999'),
                ('{"password": "pw_secret_9", "auth": "au_secret_9"}', '[REDACTED]', 'pw_secret_9'),
                ('https://user1:pass12345@host.local/a.mkv', 'https://user1:[REDACTED]@host.local/a.mkv', 'pass12345'),
            ]
            for raw, expected_sub, forbidden_sub in cases:
                conftest.mock_xbmc.log.reset_mock()
                control.log(raw, 'warning')
                logged = str(conftest.mock_xbmc.log.call_args[0][0])
                self.assertIn(expected_sub, logged)
                self.assertNotIn(forbidden_sub, logged)

    @tier(1)
    @feature('CR-05')
    def test_cr05_t1_ast_forbids_blocking_sleep_and_unchecked_wait_for_abort(self):
        cr05_files = [
            os.path.join(ADDON_ROOT, 'resources', 'lib', 'AnimeSchedule.py'),
            os.path.join(ADDON_ROOT, 'resources', 'lib', 'endpoints', 'mal.py'),
            os.path.join(ADDON_ROOT, 'resources', 'lib', 'indexers', 'kitsu.py'),
            os.path.join(ADDON_ROOT, 'resources', 'lib', 'indexers', 'anidb.py'),
            os.path.join(ADDON_ROOT, 'resources', 'lib', 'indexers', 'otaku.py'),
            os.path.join(ADDON_ROOT, 'resources', 'lib', 'indexers', 'jikanmoe.py'),
        ]
        sleep_hits = []
        for path in cr05_files:
            with open(path, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read(), filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr == 'sleep' and isinstance(node.func.value, ast.Name) and node.func.value.id == 'time':
                        sleep_hits.append((os.path.relpath(path, REPO_ROOT), node.lineno))
        self.assertEqual(sleep_hits, [], f"Forbidden time.sleep() calls remain in CR-05 files: {sleep_hits}")

        unchecked = []
        for path in test_ast_integrity._iter_addon_py_files():
            with open(path, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read(), filename=path)
            unchecked.extend(test_ast_integrity._find_unchecked_wait_for_abort(tree, os.path.relpath(path, REPO_ROOT)))
        self.assertEqual(unchecked, [], f"Unchecked waitForAbort calls: {unchecked}")

    @tier(2)
    @feature('CR-05')
    def test_cr05_t2_abort_mid_retry_halts_subsequent_requests(self):
        with E2EHermeticEnv('22'), E2EMockServer() as srv:
            from resources.lib.ui import control
            from resources.lib.endpoints import mal as mal_mod

            hits = []

            def _sched(req_handler, method, path, parsed, headers, body):
                hits.append(parsed.query)
                control.monitor._get_monitor().requestAbort()
                send_http_response(req_handler, 500, 'err')
                return True

            srv.add_route('/schedules', _sched)
            orig_base = mal_mod.Mal._BASE_URL
            mal_mod.Mal._BASE_URL = srv.get_base_url()
            t0 = time.monotonic()
            try:
                mal_mod.Mal().update_calendar()
            finally:
                mal_mod.Mal._BASE_URL = orig_base
            self.assertEqual(len(hits), 1)
            self.assertLess(time.monotonic() - t0, 0.5)

    @tier(2)
    @feature('CR-05')
    def test_cr05_t2_jikan_3req_per_sec_throttle_respects_abort(self):
        with E2EHermeticEnv('22'), E2EMockServer() as srv:
            from resources.lib.ui import control
            from resources.lib.indexers.jikanmoe import JikanAPI

            now = time.monotonic()
            orig_ts = list(JikanAPI._request_timestamps)
            JikanAPI._request_timestamps = [now, now, now]
            control.monitor._get_monitor().requestAbort()
            api = JikanAPI()
            api.baseUrl = srv.get_base_url()
            t0 = time.monotonic()
            try:
                res = api.get_anime_synopsis(52991)
            finally:
                JikanAPI._request_timestamps = orig_ts
            self.assertLess(time.monotonic() - t0, 0.5)
            self.assertIsNone(res)

    @tier(2)
    @feature('CR-05')
    def test_cr05_t2_anidb_rate_limit_boundary_0s_vs_4s(self):
        with E2EHermeticEnv('22') as env, E2EMockServer() as srv:
            from resources.lib.ui import control
            from resources.lib.indexers.anidb import ANIDBAPI

            map_db = os.path.join(env.profile_dir, 'mappings.db')
            with sqlite3.connect(map_db) as c:
                c.execute('CREATE TABLE anime (mal_id INTEGER PRIMARY KEY, anidb_id INTEGER)')
                c.execute('INSERT INTO anime VALUES (52991, 17617)')
                c.commit()
            control.mappingDB = map_db

            anidb_hits = []
            anidb_xml = '<anime><titles><title>Frieren</title></titles><episodes><episode><epno>1</epno><title>Ep1</title><length>24</length><airdate>2023-09-29</airdate></episode></episodes></anime>'

            def _adb(req_handler, method, path, parsed, headers, body):
                anidb_hits.append(path)
                send_http_response(req_handler, 200, anidb_xml, 'application/xml')
                return True

            srv.add_route('/anidb', _adb)
            api = ANIDBAPI()
            api.base_url = f"{srv.get_base_url()}/anidb"

            # Case A: recent request + abort -> 0 HTTP hits in <0.5s
            control.setInt('anidb_last_request', int(time.time()))
            control.monitor._get_monitor().requestAbort()
            t0 = time.monotonic()
            res_a = api.get_episode_meta(52991)
            self.assertLess(time.monotonic() - t0, 0.5)
            self.assertEqual(res_a, [])
            self.assertEqual(len(anidb_hits), 0)

            # Case B: >= 4s elapsed without abort -> proceeds immediately
            control.monitor.cleanup()
            control.setInt('anidb_last_request', int(time.time()) - 4)
            t1 = time.monotonic()
            res_b = api.get_episode_meta(52991)
            self.assertLess(time.monotonic() - t1, 0.5)
            self.assertEqual(len(anidb_hits), 1)
            self.assertEqual(len(res_b['episodes']), 1)
            self.assertEqual(res_b['episodes'][0]['episode'], 1)

    @tier(2)
    @feature('CR-05')
    def test_cr05_t2_sanitize_log_token_length_boundary_5_vs_6_chars(self):
        with E2EHermeticEnv('22'):
            from resources.lib.ui import control

            control.setSetting('subtitles.subdl.apikey', '12345')
            msg_5 = 'https://api.subdl.com/check value=12345'
            self.assertIn('12345', control.sanitize_log(msg_5))

            control.setSetting('subtitles.subdl.apikey', '123456')
            msg_6 = 'https://api.subdl.com/check value=123456'
            san_6 = control.sanitize_log(msg_6)
            self.assertNotIn('123456', san_6)
            self.assertIn('[REDACTED]', san_6)

            self.assertIn('abc4567', control.sanitize_log('Bearer abc4567'))
            self.assertEqual(control.sanitize_log('Bearer abc45678'), 'Bearer [REDACTED]')

    @tier(2)
    @feature('CR-05')
    def test_cr05_t2_sanitize_log_non_string_payloads_and_exceptions(self):
        with E2EHermeticEnv('22'):
            import conftest
            from resources.lib.ui import control

            self.assertEqual(control.sanitize_log(None), 'None')
            self.assertEqual(control.sanitize_log(42), '42')

            dict_res = control.sanitize_log({'token': 'secretDictVal'})
            self.assertNotIn('secretDictVal', dict_res)
            self.assertIn('[REDACTED]', dict_res)

            exc_res = control.sanitize_log(RuntimeError('GET https://x.test?token=tokVal123 failed'))
            self.assertNotIn('tokVal123', exc_res)
            self.assertIn('[REDACTED]', exc_res)

            conftest.mock_xbmc.log.reset_mock()
            control.log(RuntimeError('GET https://x.test?token=tokVal123 failed'), 'error')
            self.assertNotIn('tokVal123', str(conftest.mock_xbmc.log.call_args[0][0]))

    @tier(2)
    @feature('CR-05')
    def test_cr05_t2_sanitize_log_benign_message_passthrough(self):
        with E2EHermeticEnv('22'):
            from resources.lib.ui import control
            s1 = '[COLOR gold]Episode 12[/COLOR] loaded (1080p)'
            self.assertEqual(control.sanitize_log(s1), s1)
            self.assertEqual(control.sanitize_log(''), '')


# ==============================================================================
# ABI: Tri-Addon Packaging (6.3.0/1.0.46/1.0.3) & Kodi 21/22 ABI Parity
# ==============================================================================

class TestABITriAddonAndKodiParity(unittest.TestCase):
    """ABI: 6 Tier 1 + 6 Tier 2 opaque-box tests."""

    @tier(1)
    @feature('ABI')
    def test_abi_t1_kodi21_vs_kodi22_set_videotags_parity(self):
        import xbmcgui
        info = {
            'title': 'Episode 1',
            'mediatype': 'episode',
            'premiered': '2025-10-12',
            'tagline': 'A New Journey',
            'originallanguage': 'ja',
            'season_plot': 'Season summary',
            'available_fanart': ['http://127.0.0.1/f.jpg'],
            'hdr_type': 'hdr10',
            'cast': [{'name': 'Frieren', 'role': 'Mage', 'index': 0, 'thumbnail': ''}],
            'studio': 'Madhouse',
            'UniqueIDs': {'mal_id': '52991'},
        }
        with E2EHermeticEnv('21', strict_settings=True):
            from resources.lib.ui import control
            li21 = xbmcgui.ListItem('Ep 1')
            control.set_videotags(li21, dict(info))
            self.assertEqual(li21.getDateTime(), '2025-10-12T00:00:00')
            self.assertEqual(li21.getProperty('SeasonPlot'), 'Season summary')
            self.assertEqual(li21.getProperty('tagline'), 'A New Journey')
            self.assertEqual(li21.getProperty('OriginalLanguage'), 'ja')

        with E2EHermeticEnv('22', strict_settings=True):
            from resources.lib.ui import control
            li22 = xbmcgui.ListItem('Ep 1')
            control.set_videotags(li22, dict(info))
            v22 = li22.getVideoInfoTag()
            self.assertEqual(v22.getTagLine(), 'A New Journey')
            self.assertEqual(v22.getOriginalLanguage(), 'ja')
            self.assertEqual(v22.getSeasonPlot(), 'Season summary')
            self.assertEqual(v22.getHdrType(), 1)
            self.assertEqual(v22.getAvailableFanart(), ['http://127.0.0.1/f.jpg'])

    @tier(1)
    @feature('ABI')
    def test_abi_t1_companion_addon_control_binding_and_subtitle_service(self):
        with E2EHermeticEnv('22', strict_settings=True) as env, E2EMockServer() as srv:
            from resources.lib.ui import control
            from resources.lib.subtitles.models import SubtitleResult, VideoMeta

            self.assertEqual(control.ADDON_ID, 'plugin.video.otaku.rpdev')
            sub_res = SubtitleResult(
                service_name='opensubtitles',
                display_name='OpenSubtitles',
                name='Frieren.01.srt',
                lang='English',
                lang_code='en',
                download_url=f'{srv.get_base_url()}/sub.srt',
                auto_identified=True,
                match_reason='AniDB Hash',
                sync=True,
                impaired=True,
            )
            meta = VideoMeta(tvshow='Frieren', title='Frieren', season=1, episode=1, languages=['eng'], preferred_lang='eng')
            with open(os.path.join(REPO_ROOT, 'tests', 'fixtures', 'media', 'sample.srt'), 'rb') as sf:
                srt_bytes = sf.read()

            with patch('resources.lib.subtitles.get_meta_from_player', return_value=meta), \
                 patch('resources.lib.subtitles.search_subtitles', return_value=[sub_res]):
                search_out = invoke_subtitle_service('search', {'languages': 'English'}, handle=9)
            self.assertEqual(search_out['emitted'], 1)
            li = search_out['directory_items'][0][2]
            self.assertEqual(li.getProperty('sync'), 'true')
            self.assertEqual(li.getProperty('hearing_imp'), 'true')
            self.assertEqual(li.getProperty('otaku.auto_identified'), 'true')
            self.assertTrue(any(args[0] == 9 for args in search_out['end_of_directory']))

            dl_url = search_out['directory_items'][0][1]
            payload_val = dl_url.split('payload=', 1)[1]
            with patch('resources.lib.subtitles.get_meta_from_player', return_value=meta), \
                 patch('resources.lib.subtitles.services.opensubtitles.OpenSubtitlesService.download', return_value=srt_bytes):
                dl_out = invoke_subtitle_service('download', {'payload': payload_val}, handle=10)
            self.assertEqual(dl_out['emitted'], 1)
            staged_path = dl_out['directory_items'][0][1]
            self.assertTrue(staged_path.startswith(env.subtitle_temp_dir))
            self.assertTrue(os.path.isfile(staged_path))

    @tier(1)
    @feature('ABI')
    def test_abi_t1_dual_bcp47_and_iso639_2_stream_selection(self):
        for ver in ('21', '22'):
            with E2EHermeticEnv(ver, strict_settings=True):
                from resources.lib.ui import control, player
                control.setBool('general.kodi_language', False)
                control.setInt('preferred.audio', 0)
                control.setInt('preferred.subtitle', 1)

                wp = player.WatchlistPlayer()
                wp.preferred_audio = 0
                wp.preferred_subtitle_setting = 1
                wp.setup_audio_and_subtitles()

                self.assertEqual(wp._audio_stream, 0)
                self.assertEqual(wp._subtitle_stream, 0)
                self.assertTrue(player.is_language_match('en-US', '', 'eng'))
                self.assertTrue(player.is_language_match('jpn', '', 'ja'))

    @tier(1)
    @feature('ABI')
    def test_abi_t1_demuxer_chapters_kodi22_native_vs_kodi21_fallback(self):
        with E2EHermeticEnv('22', strict_settings=True):
            from resources.lib.ui import player
            wp22 = player.WatchlistPlayer()
            wp22.total_time = 1440
            wp22.skipintro_aniskip_enable = True
            wp22.skipoutro_aniskip_enable = True
            wp22.skipintro_offset = 0
            wp22.skipoutro_offset = 0
            wp22.process_ffprobe_chapter_skips()
            self.assertTrue(wp22.skipintro_aniskip)
            self.assertEqual((wp22.skipintro_start, wp22.skipintro_end), (90, 180))
            self.assertTrue(wp22.skipoutro_aniskip)
            self.assertEqual((wp22.skipoutro_start, wp22.skipoutro_end), (1320, 1410))

        with E2EHermeticEnv('21', strict_settings=True):
            from resources.lib.ui import player
            wp21 = player.WatchlistPlayer()
            wp21.total_time = 1440
            wp21.skipintro_aniskip_enable = True
            wp21.skipoutro_aniskip_enable = True
            wp21.skipintro_offset = 0
            wp21.skipoutro_offset = 0
            self.assertFalse(wp21.query_demuxer_chapters())
            wp21.ffprobe_chapters = [
                {'title': 'OP', 'start': 85.0, 'end': 175.0},
                {'title': 'ED', 'start': 1310.0, 'end': 1400.0},
            ]
            wp21.process_ffprobe_chapter_skips()
            self.assertTrue(wp21.skipintro_aniskip)
            self.assertEqual((wp21.skipintro_start, wp21.skipintro_end), (85, 175))
            self.assertTrue(wp21.skipoutro_aniskip)

    @tier(1)
    @feature('ABI')
    def test_abi_t1_external_sub_vfs_rename_and_del_subs_cache_safety(self):
        with E2EHermeticEnv('22') as env, E2EMockServer() as srv:
            import xbmcvfs
            from resources.lib.ui import control, embed_extractor

            vtt_cues = '\n\n'.join(
                f"00:{i:02d}.000 --> 00:{i:02d}.500\nDialogue line {i}" for i in range(1, 51)
            )
            vtt_body = '\ufeffWEBVTT\n\n' + vtt_cues

            def _vtt(req_handler, method, path, parsed, headers, body):
                send_http_response(req_handler, 200, vtt_body, 'text/vtt; charset=utf-8', is_head=(method == 'HEAD'))
                return True

            srv.add_route('/sub.vtt', _vtt)
            rename_calls = []
            orig_rename = xbmcvfs.rename

            def _spy_rename(src, dst):
                rename_calls.append((src, dst))
                return orig_rename(src, dst)

            with patch.object(xbmcvfs, 'rename', side_effect=_spy_rename), \
                 patch.object(xbmcvfs, 'listdir') as spy_listdir:
                entry = embed_extractor.get_sub(f"{srv.get_base_url()}/sub.vtt", 'eng', sub_tag='abi_vtt')
                self.assertIsNotNone(entry)
                self.assertTrue(any('special://temp/TemporarySubs.abi_vtt' in d for _, d in rename_calls))
                real_sub = os.path.join(env.temp_dir, os.path.basename(entry['path']))
                with open(real_sub, 'rb') as sf:
                    self.assertTrue(sf.read(6).startswith(b'WEBVTT'))
                self.assertEqual(control.getGlobalProp('otaku.embed_sub_has_full_dialog'), 'true')

                embed_extractor.del_subs()
                spy_listdir.assert_not_called()
                self.assertFalse(os.path.exists(real_sub))
                self.assertEqual(control.getGlobalProp('otaku.embed_sub_has_full_dialog'), '')

    @tier(1)
    @feature('ABI')
    def test_abi_t1_context_addon_actions_dispatch_on_kodi21_and_22(self):
        import xbmcgui
        for ver in ('21', '22'):
            with E2EHermeticEnv(ver):
                li = xbmcgui.ListItem('Ep 4', path='plugin://plugin.video.otaku.rpdev/play/52991/4')
                li.getVideoInfoTag().setTitle('Episode 4')
                li.getVideoInfoTag().setTvShowTitle('Frieren')

                cmds_rec = invoke_context_action('findrecommendations', li)
                self.assertEqual(cmds_rec, ['Container.Update(plugin://plugin.video.otaku.rpdev/find_recommendations/play/52991/4)'])

                cmds_re = invoke_context_action('rescrape', li)
                self.assertIn('PlayMedia(plugin://plugin.video.otaku.rpdev/play/52991/4?', cmds_re[0])
                self.assertIn('rescrape=true', cmds_re[0])

                cmds_ss = invoke_context_action('sourceselect', li)
                self.assertIn('source_select=true', cmds_ss[0])

                self.assertEqual(
                    invoke_context_action('markedaswatched', li),
                    ['RunPlugin(plugin://plugin.video.otaku.rpdev/marked_as_watched/52991/4)'],
                )
                self.assertEqual(
                    invoke_context_action('markedasunwatched', li),
                    ['RunPlugin(plugin://plugin.video.otaku.rpdev/marked_as_unwatched/52991/4)'],
                )
                self.assertEqual(
                    invoke_context_action('markpreviouswatched', li),
                    ['RunPlugin(plugin://plugin.video.otaku.rpdev/mark_previous_watched/52991/4)'],
                )
                self.assertEqual(
                    invoke_context_action('clearcache', li),
                    ['RunPlugin(plugin://plugin.video.otaku.rpdev/clear_cache)'],
                )

    @tier(2)
    @feature('ABI')
    def test_abi_t2_swig_non_null_coercion_under_kodi22_strict(self):
        import xbmcgui
        with E2EHermeticEnv('22', strict_settings=True):
            from resources.lib.ui import control
            li = xbmcgui.ListItem('Safe')
            control.set_videotags(
                li,
                {
                    'title': None,
                    'plot': None,
                    'cast': [{'name': None, 'role': None, 'index': None, 'thumbnail': None}],
                    'UniqueIDs': {'mal_id': None, 'imdb': 'tt1'},
                    'studio': [None],
                },
            )
            vinfo = li.getVideoInfoTag()
            self.assertEqual(vinfo.getUniqueIDs(), {'imdb': 'tt1'})
            self.assertEqual(vinfo.getTitle(), '')
            control.setSetting('realdebrid.token', None)
            self.assertEqual(control.getSetting('realdebrid.token'), '')

    @tier(2)
    @feature('ABI')
    def test_abi_t2_strict_settings_schema_type_mismatch_caught_by_kodi22(self):
        import xbmcaddon
        with E2EHermeticEnv('22', strict_settings=True):
            from resources.lib.ui import control
            self.assertIsInstance(control.getBool('provider.nyaa'), bool)
            self.assertIsInstance(control.getInt('general.timeout'), int)

            settings_obj = xbmcaddon.Addon('plugin.video.otaku.rpdev').getSettings()
            with self.assertRaises(TypeError) as ctx:
                settings_obj.getInt('provider.nyaa')
            self.assertIn("Setting 'provider.nyaa' is of type 'boolean'", str(ctx.exception))

    @tier(2)
    @feature('ABI')
    def test_abi_t2_get_sub_html_fallback_and_signs_only_cue_boundary(self):
        with E2EHermeticEnv('22'), E2EMockServer() as srv:
            from resources.lib.ui import control, embed_extractor

            sparse_srt = '\n\n'.join(f"{i}\n00:00:0{i},000 --> 00:00:0{i},500\nSign {i}" for i in range(1, 5))
            full_srt = '\n\n'.join(f"{i}\n00:00:{i:02d},000 --> 00:00:{i:02d},500\nLine {i}" for i in range(1, 46))

            def _sub_handler(req_handler, method, path, parsed, headers, body):
                if path == '/proxy':
                    send_http_response(req_handler, 200, '<html><body>502 Bad Gateway</body></html>', 'text/html')
                    return True
                if path == '/sparse.srt':
                    send_http_response(req_handler, 200, sparse_srt, 'text/plain')
                    return True
                if path == '/full.srt':
                    send_http_response(req_handler, 200, full_srt, 'text/plain')
                    return True
                if path == '/bad.html':
                    send_http_response(req_handler, 200, '<!DOCTYPE html><html>error</html>', 'text/html')
                    return True
                return False

            srv._custom_handler = _sub_handler
            base = srv.get_base_url()

            sparse_entry = embed_extractor.get_sub(f"{base}/proxy?url={base}/sparse.srt", 'eng', sub_tag='abi_sparse')
            self.assertIsNotNone(sparse_entry)
            self.assertTrue(sparse_entry['is_signs_only'])
            self.assertEqual(control.getGlobalProp('otaku.embed_sub_signs_only'), 'true')

            full_entry = embed_extractor.get_sub(f"{base}/proxy?url={base}/full.srt", 'eng', sub_tag='abi_full')
            self.assertIsNotNone(full_entry)
            self.assertFalse(full_entry['is_signs_only'])
            self.assertEqual(control.getGlobalProp('otaku.embed_sub_has_full_dialog'), 'true')

            bad_entry = embed_extractor.get_sub(f"{base}/bad.html", 'eng', sub_tag='abi_bad')
            self.assertIsNone(bad_entry)

    @tier(2)
    @feature('ABI')
    def test_abi_t2_subtitle_service_disabled_empty_query_and_bad_payload(self):
        with E2EHermeticEnv('22', strict_settings=True):
            from resources.lib.ui import control

            control.setBool('subtitles.enabled', False)
            out_disabled = invoke_subtitle_service('search', {'languages': 'English'}, handle=7)
            self.assertEqual(out_disabled['emitted'], 0)
            self.assertTrue(any(args[0] == 7 for args in out_disabled['end_of_directory']))

            control.setBool('subtitles.enabled', True)
            for action, params in (
                ('manualsearch', {'searchstring': ''}),
                ('download', {'payload': '{bad'}),
                ('bogus', {}),
            ):
                out = invoke_subtitle_service(action, params, handle=7)
                self.assertEqual(out['emitted'], 0)
                self.assertTrue(any(args[0] == 7 for args in out['end_of_directory']))

    @tier(2)
    @feature('ABI')
    def test_abi_t2_tri_addon_version_lockstep_and_python314_clean_imports(self):
        plugin_root = ET.parse(os.path.join(ADDON_ROOT, 'addon.xml')).getroot()
        ctx_root = ET.parse(os.path.join(CONTEXT_ROOT, 'addon.xml')).getroot()
        sub_root = ET.parse(os.path.join(SUBTITLE_ROOT, 'addon.xml')).getroot()

        def _parse_ver(v):
            return tuple(int(p) for p in (v or '').split('.'))

        plugin_ver = plugin_root.get('version')
        ctx_ver = ctx_root.get('version')
        sub_ver = sub_root.get('version')

        self.assertGreaterEqual(_parse_ver(plugin_ver), (6, 3, 0))
        self.assertGreaterEqual(_parse_ver(ctx_ver), (1, 0, 46))
        self.assertGreaterEqual(_parse_ver(sub_ver), (1, 0, 3))

        imp_versions = {e.get('addon'): e.get('version') for e in plugin_root.findall('./requires/import')}
        self.assertEqual(imp_versions.get('context.otaku.rpdev'), ctx_ver)
        self.assertEqual(imp_versions.get('service.subtitles.otaku.rpdev'), sub_ver)

        removed_stdlib = {'cgi', 'pipes', 'imghdr', 'sunau'}
        bad_imports = []
        for path in test_ast_integrity._iter_addon_py_files():
            with open(path, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read(), filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split('.')[0] in removed_stdlib:
                            bad_imports.append((os.path.relpath(path, REPO_ROOT), alias.name))
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.split('.')[0] in removed_stdlib:
                        bad_imports.append((os.path.relpath(path, REPO_ROOT), node.module))
        self.assertEqual(bad_imports, [], f"Removed Python 3.13/3.14 stdlib imports found: {bad_imports}")

    @tier(2)
    @feature('ABI')
    def test_abi_t2_bcp47_subtags_and_window_property_64kb_ceiling(self):
        with E2EHermeticEnv('22', strict_settings=True):
            from resources.lib.ui import control, player

            self.assertTrue(player.is_language_match('pt-BR', '', 'por'))
            self.assertTrue(player.is_language_match('zh-Hans', '', 'chi'))
            self.assertFalse(player.is_language_match(None, '', 'eng'))
            self.assertFalse(player.is_language_match('', '', 'eng'))

            ok_payload = 'A' * 65536
            control.setGlobalProp('otaku.e2e_64kb', ok_payload)
            self.assertEqual(len(control.getGlobalProp('otaku.e2e_64kb')), 65536)

            over_payload = 'B' * 65537
            control.setGlobalProp('otaku.e2e_over64kb', over_payload)
            self.assertEqual(control.getGlobalProp('otaku.e2e_over64kb'), '')
