# -*- coding: utf-8 -*-
"""
test_mapping_db_integration.py — Hermetic tests for Otaku-Mapping-DB v2.0 integration
=====================================================================================
Covers:
  - service.update_mappings_db() rolling .xz + manifest.json SHA-256 + upstream fallback
  - database.resolve_mappings_with_fallback() local -> cache.db -> AniZip -> Simkl overlay
  - database.get_tvdb_rules() & playback.tmdb_mapping_match() split-cour rule resolution
  - part_filter.part_info() indexed thetvdb_id sibling discovery
  - tools.generate_diagnostics_report() mapping metrics/stale tag & INSPECT_MAPPINGS overlay
"""

import hashlib
import json
import lzma
import os
import sqlite3
import sys
import time
import unittest
from unittest.mock import patch

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_TEST_DIR, '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import conftest  # noqa: F401
from tests.e2e_v630.e2e_helpers import E2EHermeticEnv, E2EMockServer, invoke_plugin_route, send_http_response


def _create_v2_mappings_db(path, last_updated=None, include_rules=True, include_v22=False):
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE activities (sync_id INTEGER PRIMARY KEY, last_updated TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE anime (mal_id INTEGER PRIMARY KEY, mal_dub_id INTEGER, anilist_id INTEGER, "
        "kitsu_id INTEGER, anidb_id INTEGER, simkl_id INTEGER, thetvdb_id INTEGER, "
        "themoviedb_id INTEGER, imdb_id INTEGER, trakt_id INTEGER, mal_title TEXT, "
        "mal_picture TEXT, thetvdb_season INTEGER, thetvdb_part INTEGER, "
        "duration INTEGER, score REAL, status TEXT, anime_media_type TEXT, "
        "global_media_type TEXT, anime_media_episodes TEXT, global_media_episodes TEXT, UNIQUE(mal_id))"
    )
    conn.execute(
        "INSERT INTO anime (mal_id, mal_dub_id, anilist_id, kitsu_id, anidb_id, thetvdb_id, themoviedb_id, imdb_id, "
        "mal_title, mal_picture, status, thetvdb_season, thetvdb_part, anime_media_type, anime_media_episodes, global_media_episodes) VALUES "
        "(1001, 1001, 2001, 3001, 4001, 55501, 66601, 'tt1111111', 'Test Saga - Cour One', '12/1001.jpg', 'FINISHED', 1, 1, 'TV', '1 - 12', '1 - 12'), "
        "(1002, NULL, 2002, 3002, 4002, 55501, 66601, 'tt1111111', 'Test Saga - Cour Two', '12/1002.jpg', 'FINISHED', 1, 2, 'TV', '1 - 13', '13 - 25')"
    )
    ts = str(int(last_updated if last_updated is not None else time.time()))
    conn.execute("INSERT INTO activities VALUES (1, ?)", (ts,))
    if include_rules:
        conn.execute(
            "CREATE TABLE tvdb_rules (mal_id INTEGER NOT NULL, tvdb_id INTEGER, season INTEGER NOT NULL, "
            "rule_type TEXT NOT NULL, range_start INTEGER NOT NULL, range_end INTEGER, "
            "ep_start INTEGER NOT NULL, absolute_start INTEGER, source TEXT NOT NULL, "
            "PRIMARY KEY (mal_id, season, rule_type, range_start, ep_start))"
        )
        conn.execute(
            "INSERT INTO tvdb_rules VALUES (1002, 55501, 1, 'cour', 13, 25, 1, 13, 'malsync_rules')"
        )
        conn.execute("CREATE TABLE build_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO build_meta VALUES ('schema_version', ?)", ('2.2' if include_v22 else '2.0',))
    if include_v22:
        conn.execute(
            "CREATE TABLE anime_aliases ("
            "mal_id INTEGER NOT NULL, title TEXT NOT NULL COLLATE NOCASE, "
            "PRIMARY KEY (mal_id, title)) WITHOUT ROWID"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS ix_aliases_title ON anime_aliases (title)")
        conn.execute("INSERT INTO anime_aliases VALUES (1001, 'Test Saga Alternate Alias')")
        conn.execute("INSERT INTO anime_aliases VALUES (1002, 'Test Saga Part 2 English')")
        conn.execute(
            "CREATE TABLE franchise_links ("
            "mal_id INTEGER NOT NULL, related_mal_id INTEGER NOT NULL, "
            "relation_type TEXT NOT NULL, source TEXT NOT NULL, "
            "PRIMARY KEY (mal_id, related_mal_id, relation_type)) WITHOUT ROWID"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS ix_franchise_rel ON franchise_links (related_mal_id)")
        conn.execute("INSERT INTO franchise_links VALUES (1001, 1002, 'SEQUEL', 'anilist')")
        conn.execute("INSERT INTO franchise_links VALUES (1002, 1001, 'PREQUEL', 'anilist_inv')")
        conn.execute("CREATE TABLE schedule_ids (mal_id INTEGER PRIMARY KEY, syobocal_tid INTEGER, annict_id INTEGER)")
        conn.execute("INSERT INTO schedule_ids VALUES (1001, 7001, 8001)")
    conn.commit()
    conn.close()


class TestMappingDbIntegration(unittest.TestCase):

    def test_update_mappings_db_manifest_xz_sha_and_fallback(self):
        with E2EHermeticEnv('22'), E2EMockServer() as srv:
            import service
            from resources.lib.ui import control, database

            db_src = os.path.join(control.dataPath, 'tmp_src.db')
            _create_v2_mappings_db(db_src)
            with open(db_src, 'rb') as f:
                raw_db = f.read()
            os.remove(db_src)
            xz_db = lzma.compress(raw_db)
            raw_sha = hashlib.sha256(raw_db).hexdigest()

            mode = {'state': 'ok'}

            def _handler(req_handler, method, path, parsed, headers, body):
                if path == '/manifest.json':
                    sha = ('0' * 64) if mode['state'] == 'bad_sha' else raw_sha
                    payload = json.dumps({'files': {'raw': {'sha256': sha}}}).encode('utf-8')
                    send_http_response(req_handler, 200, payload, 'application/json')
                    return True
                if path == '/anime_mappings.db.xz':
                    if mode['state'] == 'primary_fail':
                        send_http_response(req_handler, 503, b'unavailable', 'text/plain')
                        return True
                    send_http_response(req_handler, 200, xz_db, 'application/x-xz', extra_headers={'ETag': '"m-v2"'})
                    return True
                if path == '/fallback.db':
                    send_http_response(req_handler, 200, raw_db, 'application/octet-stream')
                    return True
                return False

            srv._custom_handler = _handler
            base = srv.get_base_url()

            with patch.object(service, 'MAPPINGS_MANIFEST_URL', f'{base}/manifest.json'), \
                 patch.object(service, 'MAPPINGS_XZ_URL', f'{base}/anime_mappings.db.xz'), \
                 patch.object(service, 'MAPPINGS_FALLBACK_URL', f'{base}/fallback.db'):
                # 1. Valid manifest SHA-256 + .xz succeeds
                self.assertTrue(service.update_mappings_db())
                meta = database.get_mappings_metadata()
                self.assertEqual(meta['row_count'], 2)
                self.assertEqual(meta['rule_count'], 1)
                self.assertEqual(meta['schema_version'], '2.0')

                # 2. Manifest SHA-256 mismatch aborts cleanly
                mode['state'] = 'bad_sha'
                self.assertFalse(service.update_mappings_db())

                # 3. Primary 503 falls back automatically to fallback.db
                mode['state'] = 'primary_fail'
                self.assertTrue(service.update_mappings_db())

    def test_resolve_mappings_with_fallback_cache_anizip_and_simkl(self):
        with E2EHermeticEnv('22'), E2EMockServer() as srv:
            from resources.lib.ui import control, database
            from resources.lib.pages.nekobt import Sources as NekoSources
            from resources.lib.pages.torrentio import Sources as TorrentioSources

            _create_v2_mappings_db(control.mappingDB)
            database.close_all_connections(control.mappingDB)

            # Local complete entry never triggers HTTP
            hit = database.resolve_mappings_with_fallback(1001)
            self.assertEqual(hit['thetvdb_id'], 55501)
            self.assertEqual(hit['_mapping_source'], 'mappings.db')

            # Unmapped 63752 resolves via AniZip -> cached in cache.db -> zero repeat calls
            calls = {'anizip': 0, 'simkl': 0}

            def _az_get(url, params=None, timeout=5, **kwargs):
                class _Resp:
                    def __init__(self, status_code, payload):
                        self.status_code = status_code
                        self.ok = (status_code == 200)
                        self._payload = payload

                    def json(self, default=None):
                        return self._payload

                if 'ani.zip' in url:
                    calls['anizip'] += 1
                    mid = int((params or {}).get('mal_id') or 0)
                    if mid == 63752:
                        return _Resp(200, {
                            'mappings': {
                                'mal_id': 63752,
                                'anilist_id': 209504,
                                'kitsu_id': 50768,
                                'anidb_id': 19954,
                                'thetvdb_id': 475631,
                                'themoviedb_id': 325158,
                                'imdb_id': 'tt41095208',
                            },
                            'episodes': {'1': {'seasonNumber': 1}},
                        })
                    return _Resp(404, {})
                return _Resp(404, {})

            with patch('resources.lib.ui.client.get', side_effect=_az_get), \
                 patch('resources.lib.indexers.simkl.SIMKLAPI.get_mapping_ids_from_simkl', return_value={}):
                res1 = database.resolve_mappings_with_fallback(63752)
                self.assertEqual(res1['thetvdb_id'], 475631)
                self.assertEqual(res1['anidb_id'], 19954)
                self.assertEqual(res1['kitsu_id'], 50768)
                self.assertIn('live overlay', res1['_mapping_source'])
                self.assertEqual(calls['anizip'], 1)

            # Second call reads cache.db cleanly without HTTP
            with patch('resources.lib.ui.client.get', side_effect=AssertionError("Should hit cache.db")):
                self.assertEqual(NekoSources()._get_tvdb_id(63752), 475631)
                tsrc = TorrentioSources()
                tsrc.media_type = 'tv'
                with patch.object(tsrc, 'process_torrentio_episodes', return_value=[]):
                    tsrc.get_sources('test', 63752, 1, 'ONGOING', 'tv')
                self.assertEqual(tsrc.kitsu_id, 50768)
                self.assertEqual(tsrc.imdb_id, 'tt41095208')

            # AniZip empty -> falls back to SIMKLAPI
            def _simkl_mock(mid, send_id):
                calls['simkl'] += 1
                return {'anidb': 98765, 'tvdb': 87654, 'simkl': 76543}

            with patch('resources.lib.ui.client.get', side_effect=_az_get), \
                 patch('resources.lib.indexers.simkl.SIMKLAPI.get_mapping_ids_from_simkl', side_effect=_simkl_mock):
                res_s = database.resolve_mappings_with_fallback(77777)
                self.assertEqual(res_s['anidb_id'], 98765)
                self.assertEqual(res_s['thetvdb_id'], 87654)
                self.assertEqual(calls['simkl'], 1)

    def test_tvdb_rules_playback_matching_and_part_filter_and_tools_diagnostics(self):
        with E2EHermeticEnv('22'):
            from resources.lib.ui import control, database, part_filter
            from resources.lib.routes import playback, tools
            import resources.lib.windows.textviewer as tv_mod

            # 0. Legacy DB without tvdb_rules/build_meta returns [] cleanly with zero errors
            _create_v2_mappings_db(control.mappingDB, include_rules=False)
            database.close_all_connections(control.mappingDB)
            self.assertEqual(database.get_tvdb_rules(1002), [])
            legacy_meta = database.get_mappings_metadata()
            self.assertEqual(legacy_meta['row_count'], 2)
            self.assertEqual(legacy_meta['rule_count'], 0)

            # Build DB aged 20 days to verify [STALE >14d] alert in diagnostics report
            stale_ts = time.time() - (20 * 86400)
            _create_v2_mappings_db(control.mappingDB, last_updated=stale_ts, include_rules=True)
            database.close_all_connections(control.mappingDB)

            # 1. tvdb_rules split-cour lookup: S01E16 maps to MAL 1002 ep 4 (16 - 13 + 1)
            with patch('resources.lib.ui.client.get', return_value=None):
                m = playback.tmdb_mapping_match('66601', [('themoviedb_id', '66601')], 1, 16)
            self.assertIsNotNone(m)
            self.assertEqual(m['mal_id'], 1002)
            self.assertEqual(m['episode_number'], 4)

            # 2. part_filter indexed thetvdb_id lookup finds sibling Cour One/Two
            num, own, others = part_filter.part_info(1002)
            self.assertEqual(num, 2)
            self.assertEqual(own, 'courtwo')
            self.assertIn('courone', others)

            # 3. tools.generate_diagnostics_report() surfaces Rows, Rules, Age & [STALE >14d]
            report = tools.generate_diagnostics_report()
            self.assertIn('Rows: 2', report)
            self.assertIn('Rules: 1', report)
            self.assertIn('[STALE >14d]', report)

            # 4. INSPECT_MAPPINGS surfaces live overlay when missing locally
            captured = []

            class _SpyTV:
                def __init__(self, xml_file, addon_path, **kwargs):
                    captured.append(kwargs.get('instructions_text', ''))

                def run(self):
                    pass

                def close(self):
                    pass

            with patch.object(database, 'resolve_mappings_with_fallback', return_value={
                'mal_id': 63752, 'anilist_id': 209504, 'kitsu_id': 50768,
                'anidb_id': 19954, 'thetvdb_id': 475631, 'themoviedb_id': 325158,
                '_mapping_source': 'live overlay (AniZip/Simkl)',
            }), patch.object(tv_mod, 'TextViewerXML', _SpyTV):
                invoke_plugin_route('inspect_mappings/63752')
            self.assertEqual(len(captured), 1)
            self.assertIn('live overlay (AniZip/Simkl)', captured[0])
            self.assertIn('475631', captured[0])

    def test_v22_aliases_franchise_search_relations_maldub_offset_and_sequel(self):
        with E2EHermeticEnv('22'):
            from resources.lib.ui import control, database, divide_flavors, utils
            from resources.lib import MetaBrowser
            from resources.lib.routes import tools
            import resources.lib.windows.textviewer as tv_mod

            # 0. v2.0 DB without v2.2 tables returns safe fallbacks
            _create_v2_mappings_db(control.mappingDB, include_rules=True, include_v22=False)
            database.close_all_connections(control.mappingDB)
            self.assertEqual(database.get_mapping_aliases(1001), ['Test Saga - Cour One'])
            self.assertEqual(database.get_schedule_ids(1001), {})
            # Sibling fallback finds 1002 even without franchise_links table
            self.assertEqual(database.get_sequel_mal_id(1001).get('mal_id'), 1002)

            # 1. Full v2.2 DB with anime_aliases, franchise_links, and schedule_ids
            _create_v2_mappings_db(control.mappingDB, include_rules=True, include_v22=True)
            database.close_all_connections(control.mappingDB)

            meta = database.get_mappings_metadata()
            self.assertEqual(meta['schema_version'], '2.2')
            self.assertEqual(meta['alias_count'], 2)
            self.assertEqual(meta['franchise_link_count'], 2)
            self.assertEqual(meta['schedule_id_count'], 1)

            aliases = database.get_mapping_aliases(1001)
            self.assertIn('Test Saga - Cour One', aliases)
            self.assertIn('Test Saga Alternate Alias', aliases)

            hits = database.search_mappings_by_title('Test Saga Alternate Alias')
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]['mal_id'], 1001)

            franchise = database.get_franchise_entries(1001)
            self.assertEqual(len(franchise), 1)
            self.assertEqual(franchise[0]['relation_type'], 'SEQUEL')
            self.assertEqual(franchise[0]['mal_id'], 1002)

            self.assertEqual(database.get_schedule_ids(1001), {'syobocal_tid': 7001, 'annict_id': 8001})

            # 2. Offline tvdb_rules episode offset inside get_source_context (no HTTP to ani.zip)
            self.assertEqual(database.get_episode_offset_from_mappings(1002, 1), 12)
            with patch.object(utils, 'get_anizip_summary', side_effect=AssertionError("Must not call remote AniZip")):
                season, hints = utils.get_source_context(1002, {'name': 'Test Saga - Cour Two'}, 1, 3)
            self.assertEqual(season, 1)
            self.assertEqual(hints['absolute_episode'], 15)

            # 3. mal_dub_id DB fallback inside divide_flavors._MalDubMap
            divide_flavors._mal_dub_cache = None
            dub_map = divide_flavors._get_mal_dub()
            self.assertEqual(dub_map.get('1001'), 1001)
            self.assertTrue('1001' in dub_map)
            self.assertIsNone(dub_map.get('1002'))

            # 4. Offline FIND_RELATIONS & SEARCH fallbacks when remote APIs return []
            with patch.object(MetaBrowser.BROWSER, 'get_relations', return_value=[]):
                rel_res = invoke_plugin_route('find_relations/1001')
            rel_items = rel_res['directory_items']
            self.assertEqual(len(rel_items), 1)
            self.assertIn('Test Saga - Cour Two [Sequel]', rel_items[0][2].getLabel())

            with patch.object(MetaBrowser.BROWSER, 'get_search', return_value=[]):
                search_res = invoke_plugin_route('search_anime/Alternate%20Alias')
            search_items = search_res['directory_items']
            self.assertEqual(len(search_items), 1)
            self.assertEqual(search_items[0][2].getLabel(), 'Test Saga - Cour One')

            # 5. INSPECT_MAPPINGS & System Health Diagnostics surface v2.2 schedule/aliases/franchise
            captured = []

            class _SpyTV2:
                def __init__(self, xml_file, addon_path, **kwargs):
                    captured.append(kwargs.get('instructions_text', ''))

                def run(self):
                    pass

                def close(self):
                    pass

            with patch.object(tv_mod, 'TextViewerXML', _SpyTV2):
                invoke_plugin_route('inspect_mappings/1001')
            self.assertEqual(len(captured), 1)
            self.assertIn('7001 / 8001', captured[0])
            self.assertIn('Test Saga Alternate Alias', captured[0])
            self.assertIn('Test Saga - Cour Two', captured[0])

            report = tools.generate_diagnostics_report()
            self.assertIn('Aliases: 2', report)
            self.assertIn('Franchise: 2', report)


if __name__ == '__main__':
    unittest.main()
