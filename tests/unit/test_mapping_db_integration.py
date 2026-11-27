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


def _create_v2_mappings_db(path, last_updated=None, include_rules=True, include_v22=False, include_v23=False):
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
        ver = '2.3' if include_v23 else ('2.2' if include_v22 else '2.0')
        conn.execute("INSERT INTO build_meta VALUES ('schema_version', ?)", (ver,))
    if include_v22 or include_v23:
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
    if include_v23:
        conn.execute(
            "CREATE TABLE filler_ranges ("
            "mal_id INTEGER NOT NULL, ep_start INTEGER NOT NULL, "
            "ep_end INTEGER NOT NULL, filler_type TEXT NOT NULL, "
            "PRIMARY KEY (mal_id, ep_start, ep_end)) WITHOUT ROWID"
        )
        conn.execute("INSERT INTO filler_ranges VALUES (1001, 2, 3, 'Filler')")
        conn.execute("INSERT INTO filler_ranges VALUES (1001, 4, 4, 'Mixed Canon/Filler')")
        conn.execute("INSERT INTO filler_ranges VALUES (1001, 5, 5, 'Recap')")
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

            from otaku_service import sync as svc_sync
            with patch.object(svc_sync, 'MAPPINGS_MANIFEST_URL', f'{base}/manifest.json'), \
                 patch.object(svc_sync, 'MAPPINGS_XZ_URL', f'{base}/anime_mappings.db.xz'), \
                 patch.object(svc_sync, 'MAPPINGS_FALLBACK_URL', f'{base}/fallback.db'):
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

    def test_v23_filler_ranges_scraper_aliases_and_playback_title_matching(self):
        with E2EHermeticEnv('22'):
            from resources.lib import indexers
            from resources.lib.endpoints import anime_filler
            from resources.lib.pages import animekai, gogoanime, hianime, watchnixtoons2
            from resources.lib.routes import playback, tools
            from resources.lib.ui import control, database
            from resources.lib.ui.player import WatchlistPlayer
            from unittest.mock import MagicMock

            # 0. Graceful {} fallback on v2.2 DB lacking filler_ranges table
            _create_v2_mappings_db(control.mappingDB, include_rules=True, include_v22=True, include_v23=False)
            database.close_all_connections(control.mappingDB)
            self.assertEqual(database.get_mapping_filler_map(1001), {})

            # 1. Full v2.3 DB with filler_ranges + anime_aliases
            _create_v2_mappings_db(control.mappingDB, include_rules=True, include_v22=True, include_v23=True)
            database.close_all_connections(control.mappingDB)

            meta = database.get_mappings_metadata()
            self.assertEqual(meta['schema_version'], '2.3')
            self.assertEqual(meta['filler_range_count'], 3)
            self.assertEqual(
                database.get_mapping_filler_map(1001),
                {2: 'Filler', 3: 'Filler', 4: 'Mixed Canon/Filler', 5: 'Recap'},
            )

            # 2. Offline filler works for <=99 ep finished shows with ZERO HTTP requests + badge hydration
            control.setBool('interface.filler.badges', True)
            with patch('resources.lib.endpoints.anime_filler.get_data', side_effect=AssertionError("Must not call remote AFL")):
                fmap = anime_filler.get_filler_map(mal_id=1001, anime_eng_title='Test Saga', total_episodes=12, status='FINISHED')
            self.assertEqual(fmap.get(2), 'Filler')
            self.assertEqual(indexers.lookup_filler_tag(fmap, 4), 'Mixed Canon/Filler')
            cached_eps = [
                {'mal_id': 1001, 'number': n, 'filler': '', 'kodi_meta': database.dumps({'name': f'Ep {n}', 'info': {'title': f'Ep {n}', 'episode': n}, 'image': {}, 'art': {}})}
                for n in range(1, 7)
            ]
            processed = indexers.process_episodes(cached_eps, '', mal_id=1001)
            self.assertEqual(processed[1]['name'], 'Ep 2 [COLOR red][FILLER][/COLOR]')
            self.assertEqual(processed[3]['name'], 'Ep 4 [COLOR yellow][MIXED][/COLOR]')
            self.assertEqual(processed[4]['name'], 'Ep 5 [COLOR orange][RECAP][/COLOR]')
            self.assertEqual(processed[5]['name'], 'Ep 6 [COLOR limegreen][CANON][/COLOR]')

            # 3. Player binge auto-skip separates Filler/Recap vs Mixed Canon/Filler + per-series overrides
            for skip_mixed, ov_mode, expected in (
                (False, 'default', [4, 6]),
                (True, 'default', [6]),
                (True, 'keep', [2, 3, 4, 5, 6]),
                (False, 'skip_mixed', [6]),
                (True, 'skip', [4, 6]),
            ):
                wp = WatchlistPlayer.__new__(WatchlistPlayer)
                wp.mal_id = 1001
                wp.episode = 1
                wp.series_override = {'skip_filler_mode': ov_mode}
                wp.episodes = [{'number': n, 'filler': ''} for n in range(1, 7)]
                queued = []
                control.setBool('smartplay.skip_filler', True)
                control.setBool('smartplay.skip_mixed_filler', skip_mixed)
                with patch('resources.lib.ui.control.getBool', side_effect=lambda k, default=False, _sm=skip_mixed: _sm if k == 'smartplay.skip_mixed_filler' else (True if k in ('smartplay.skip_filler', 'general.smartplay') else default)), \
                     patch('resources.lib.indexers.process_episodes', side_effect=lambda eps, _: [{'url': f"play/1001/{e['number']}"} for e in eps]), \
                     patch('resources.lib.ui.control.bulk_dir_list', side_effect=lambda items, _: [(f"plugin://plugin.video.otaku.rpdev/{it['url']}", MagicMock()) for it in items]), \
                     patch('resources.lib.ui.player.playList.add', side_effect=lambda url, listitem: queued.append(int(url.rsplit('/', 1)[-1]))):
                    wp.build_playlist()
                self.assertEqual(queued, expected, f"Failed for skip_mixed={skip_mixed}, ov_mode={ov_mode}")

            # 4. Feed anime_aliases into hianime, animekai, watchnixtoons2, gogoanime
            hi = hianime.Sources()
            with patch('resources.lib.endpoints.malsync.get_title', return_value=None):
                kws = hi._search_keywords('Test Saga', 1001, {})
            self.assertIn('Test Saga Alternate Alias', kws)
            self.assertGreater(hi._score_candidate('Test Saga Alternate Alias', 'Test Saga', mal_id=1001), 140)

            ak = animekai.Sources()
            ak_html = json.dumps({'result': {'html': '<a class="aitem" href="/watch/test-saga-alias"><h6 class="title" data-jp="">Test Saga Alternate Alias</h6></a>'}})
            with patch.object(ak, '_get_request', return_value=ak_html):
                self.assertEqual(ak._search_anime('Test Saga', {}, mal_id=1001), 'test-saga-alias')

            wnt = watchnixtoons2.Sources()
            wnt_titles = wnt._build_search_titles('Test Saga', 'Test Saga EN', 'Test Saga', mapping_aliases=database.get_mapping_aliases(1001))
            self.assertIn(('alias', 'Test Saga Alternate Alias'), wnt_titles)

            gg = gogoanime.Sources()
            self.assertIn('Test Saga Alternate Alias', gg._search_keywords('Test Saga', {}, mal_id=1001))
            self.assertGreaterEqual(gg._score_candidate('Test Saga Alternate Alias', 'Test Saga', mal_id=1001), 140)

            # 5. playback.find_episode_by_title: offline DB match + AniZip en/x-jat fallback + inspect_mappings filler summary
            from resources.lib.ui.database_sync import SyncDatabase
            SyncDatabase._build_shows()
            SyncDatabase._build_episodes()
            database.update_show(1001, database.dumps({'name': 'Test Saga'}))
            ep_meta = database.dumps({'name': 'Secret Turnabout', 'info': {'title': 'Secret Turnabout', 'episode': 3}})
            database.update_episode(1001, 1, 3, '2026-11-21', ep_meta, '')
            hit_local = playback.find_episode_by_title([1001], ['Secret Turnabout'])
            self.assertIsNotNone(hit_local)
            self.assertEqual(hit_local['mal_id'], 1001)
            self.assertEqual(hit_local['episode_number'], 3)

            with patch('resources.lib.indexers.jikanmoe.JikanAPI.get_episode_meta', return_value=[]), \
                 patch('resources.lib.indexers.anizip.ANIZIPAPI.get_anime_info', return_value={
                     'episodes': {'4': {'episode': 4, 'title': {'en': 'Midnight Trial', 'x-jat': 'Mayonaka no Saiban'}}}
                 }):
                hit_az = playback.find_episode_by_title([1002], ['Mayonaka no Saiban'])
            self.assertEqual(hit_az['mal_id'], 1002)
            self.assertEqual(hit_az['episode_number'], 4)

            import resources.lib.windows.textviewer as tv_mod
            tv_cap = []

            class _SpyTV3:
                def __init__(self, xml_file, addon_path, **kwargs):
                    tv_cap.append(kwargs.get('instructions_text', ''))

                def run(self):
                    pass

                def close(self):
                    pass

            with patch.object(tv_mod, 'TextViewerXML', _SpyTV3):
                invoke_plugin_route('inspect_mappings/1001')
            self.assertIn('Offline Filler Tags:  4 episode(s)', tv_cap[0])

    def test_mapping_db_v24_year_season_and_trakt_namespace_filtering(self):
        with E2EHermeticEnv('22'):
            from resources.lib.ui import control, database, utils, BrowserBase
            from resources.lib.ui.database_sync import SyncDatabase
            from resources.lib import pages
            from resources.lib.routes import playback
            import resources.lib.windows.textviewer as tv_mod

            db_path = control.mappingDB
            database.close_all_connections(db_path)
            if os.path.exists(db_path):
                os.remove(db_path)
            conn = sqlite3.connect(db_path)
            conn.execute(
                'CREATE TABLE anime ('
                'mal_id INTEGER PRIMARY KEY, mal_dub_id INTEGER, anilist_id INTEGER, '
                'kitsu_id INTEGER, anidb_id INTEGER, simkl_id INTEGER, thetvdb_id INTEGER, '
                'themoviedb_id INTEGER, imdb_id INTEGER, trakt_id INTEGER, mal_title TEXT, '
                'mal_picture TEXT, thetvdb_season INTEGER, thetvdb_part INTEGER, '
                'duration INTEGER, score REAL, status TEXT, anime_media_type TEXT, '
                'global_media_type TEXT, anime_media_episodes TEXT, global_media_episodes TEXT, '
                'year INTEGER, anime_season TEXT)'
            )
            conn.execute('CREATE TABLE activities (sync_id INTEGER PRIMARY KEY, last_updated TEXT)')
            conn.execute(
                'CREATE TABLE franchise_links ('
                'mal_id INTEGER NOT NULL, related_mal_id INTEGER NOT NULL, '
                'relation_type TEXT NOT NULL, source TEXT NOT NULL, '
                'PRIMARY KEY (mal_id, related_mal_id, relation_type)) WITHOUT ROWID'
            )
            conn.execute("INSERT INTO activities VALUES (1, '1795300000')")
            conn.executemany(
                "INSERT INTO anime (mal_id, trakt_id, mal_title, status, anime_media_type, global_media_type, anime_media_episodes, year, anime_season) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (2814, 8630, 'Remake Chrono Saga', 'FINISHED', 'TV', 'show', '1 - 12', 2024, 'FALL'),
                    (2264, 8630, 'Remake Chrono Saga Movie', 'FINISHED', 'MOVIE', 'movie', '1 - 1', 1997, 'SUMMER'),
                ],
            )
            conn.execute("INSERT INTO franchise_links VALUES (2814, 2264, 'ALTERNATIVE', 'anilist')")
            conn.commit()
            conn.close()
            database.close_all_connections(db_path)

            # 1. Offline search & franchise expose year + anime_season and populate Kodi item info
            hits = database.search_mappings_by_title('Remake Chrono Saga', limit=5)
            self.assertEqual(hits[0]['mal_id'], 2814)
            self.assertEqual(hits[0]['year'], 2024)
            self.assertEqual(hits[0]['anime_season'], 'FALL')

            kodi_items = utils.allocate_offline_mapping_items(database.get_franchise_entries(2814), show_relation=True)
            self.assertEqual(len(kodi_items), 1)
            self.assertEqual(kodi_items[0]['info']['year'], 1997)
            self.assertEqual(kodi_items[0]['info']['premiered'], '1997-01-01')

            # 2. BrowserBase._resolve_target_year & pages.sortSources recover year from mappings.db when shows cache has none
            SyncDatabase._build_shows()
            database.update_show(2814, database.dumps({'name': 'Remake Chrono Saga'}))
            self.assertEqual(BrowserBase.BrowserBase._resolve_target_year(mal_id=2814, kodi_meta={}), '2024')

            sources = [
                {'release_title': 'Remake Chrono Saga (2001) 1080p', 'type': 'torrent', 'seeders': 50, 'size': '2.0 GB', 'quality': 2},
                {'release_title': 'Remake Chrono Saga (2024) 1080p', 'type': 'torrent', 'seeders': 10, 'size': '1.5 GB', 'quality': 2},
            ]
            ranked = pages.Sources.sortSources(sources, [], [], [], [], 'tv', 24, mal_id=2814, show_title='Remake Chrono Saga', season=1)
            self.assertEqual(ranked[0]['release_title'], 'Remake Chrono Saga (2024) 1080p')

            # 3. tools inspect_mappings surfaces Release Year / Cour
            cap = []

            class _SpyTV4:
                def __init__(self, xml_file, addon_path, **kwargs):
                    cap.append(kwargs.get('instructions_text', ''))

                def run(self):
                    pass

                def close(self):
                    pass

            with patch.object(tv_mod, 'TextViewerXML', _SpyTV4):
                invoke_plugin_route('inspect_mappings/2814')
            self.assertIn('Release Year / Cour:  2024 / FALL', cap[0])

            # 4. Playback Trakt namespace disambiguation: trakt_id=8630 resolves MOVIE 2264 for movie item_type
            played_movies = []
            with patch('resources.lib.OtakuBrowser.OtakuBrowser.get_anime_data'), \
                 patch.object(playback, 'PLAY_MOVIE', side_effect=lambda u, p: played_movies.append(u)), \
                 patch('resources.lib.ui.control.monitor.waitForAbort', return_value=False):
                playback.TMDB_HELPER('movie', {'actionArgs': json.dumps({'item_type': 'movie', 'trakt_id': 8630})})
            self.assertEqual(played_movies, ['2264/'])

    def test_mapping_db_runtime_consumers_simkl_subtitles_tmdb_and_scrapers(self):
        with E2EHermeticEnv('22'):
            from resources.lib.ui import control, database, source_utils
            from resources.lib.indexers.otaku import OtakuAPI
            from resources.lib.endpoints import tmdb
            from resources.lib.subtitles import meta as sub_meta
            from resources.lib.subtitles.models import VideoMeta
            from resources.lib.subtitles.services.subdl import SubDLService
            from resources.lib.subtitles.services.subsource import SubSourceService
            from resources.lib.pages import animepahe, anikoto

            db_path = control.mappingDB
            database.close_all_connections(db_path)
            _create_v2_mappings_db(db_path, include_rules=False, include_v22=True)
            conn = sqlite3.connect(db_path)
            conn.execute('ALTER TABLE anime ADD COLUMN year INTEGER')
            conn.execute('ALTER TABLE anime ADD COLUMN anime_season TEXT')
            conn.execute(
                'UPDATE anime SET simkl_id=77001, year=2024, anime_season="FALL", thetvdb_season=2 '
                'WHERE mal_id=1001'
            )
            conn.execute(
                "INSERT INTO anime (mal_id, imdb_id, mal_title, status, anime_media_type, year, anime_season, thetvdb_season) "
                "VALUES (1009, 'tt9991112', 'IMDb Only Art Show', 'FINISHED', 'TV', 2023, 'SPRING', 1)"
            )
            conn.commit()
            conn.close()
            database.close_all_connections(db_path)

            # 1. OtakuAPI.get_simkl_id hits offline mappings.db with 0 HTTP requests
            api = OtakuAPI()
            with patch('resources.lib.indexers.otaku.client.get', side_effect=AssertionError('unexpected HTTP call')):
                self.assertEqual(api.get_simkl_id(1001), 77001)

            # 2. endpoints.tmdb.getArt falls back to /find/{imdb_id}?external_source=imdb_id
            tmdb_calls = []

            class _Resp:
                def __init__(self, payload, status_code=200):
                    self._payload = payload
                    self.status_code = status_code

                def json(self, default=None):
                    return self._payload

            def _fake_tmdb_get(url, params=None):
                tmdb_calls.append((url, dict(params or {})))
                if 'find/tt9991112' in url:
                    return _Resp({'tv_results': [{'id': 91234}]})
                if 'tv/91234/images' in url:
                    return _Resp({'posters': [{'file_path': '/poster.jpg'}]})
                return _Resp({})

            with patch('resources.lib.endpoints.tmdb.client.get', side_effect=_fake_tmdb_get):
                art = tmdb.getArt({'imdb_id': 'tt9991112'}, 'tv')
            self.assertEqual(art.get('poster'), ['https://image.tmdb.org/t/p/w500/poster.jpg'])
            self.assertTrue(any('find/tt9991112' in u and p.get('external_source') == 'imdb_id' for u, p in tmdb_calls))

            # 3. subtitles.meta enriches imdb_id, year, original_title, and thetvdb_season from mappings.db
            sub_meta.publish_active_playback_meta({'tvshowtitle': 'Test Saga', 'episode': 4}, mal_id='1001')
            active = sub_meta.get_active_playback_meta()
            self.assertEqual(active['imdb_id'], 'tt1111111')
            self.assertEqual(active['year'], '2024')
            self.assertEqual(active['original_title'], 'Test Saga - Cour One')
            self.assertEqual(active['season'], '2')

            dict_meta = sub_meta.get_meta_from_dict({'title': 'Ep 4', 'tvshowtitle': 'Test Saga', 'episode': 4}, mal_id='1001')
            self.assertEqual(dict_meta.imdb_id, 'tt1111111')
            self.assertEqual(dict_meta.year, '2024')
            self.assertEqual(dict_meta.season, '2')

            # 4. SubDL TV search passes imdb_id, and SubSource falls back to searchType=imdb on HTTP 200 empty data
            subdl_params = {}

            def _fake_subdl_get(url, params=None, headers=None, timeout=15):
                subdl_params.update(params or {})
                return _Resp({'subtitles': []})

            vmeta = VideoMeta(
                title='Ep 4', tvshow='Test Saga', season='2', episode='4', year='2024', imdb_id='tt1111111'
            )
            with patch('resources.lib.subtitles.services.subdl.client.get', side_effect=_fake_subdl_get):
                SubDLService.search(vmeta, {'subtitles.subdl.apikey': 'k1', 'subtitles.timeout': 5})
            self.assertEqual(subdl_params.get('imdb_id'), 'tt1111111')
            self.assertEqual(subdl_params.get('type'), 'tv')

            subsrc_calls = []

            def _fake_subsource_get(url, params=None, headers=None, timeout=15):
                subsrc_calls.append((url, dict(params or {})))
                if url.endswith('/movies/search') and (params or {}).get('searchType') == 'text':
                    return _Resp({'data': []})
                if url.endswith('/movies/search') and (params or {}).get('searchType') == 'imdb':
                    return _Resp({'data': [{'movieId': 555, 'season': 2}]})
                if url.endswith('/subtitles'):
                    return _Resp({
                        'success': True,
                        'data': [{'subtitleId': 888, 'releaseInfo': ['Test.Saga.S02E04.srt'], 'language': 'english'}],
                    })
                return _Resp({})

            with patch('resources.lib.subtitles.services.subsource.client.get', side_effect=_fake_subsource_get):
                ss_res = SubSourceService.search(vmeta, {'subtitles.subsource.apikey': 'k2', 'subtitles.timeout': 5})
            self.assertEqual(len(ss_res), 1)
            self.assertTrue(any(p.get('searchType') == 'imdb' and p.get('imdb') == 'tt1111111' for _, p in subsrc_calls))

            # 5. source_utils.filter_sources merges mappings.db aliases before Debrid checks
            torrents = [
                {'name': '[Group] Test Saga Alternate Alias - 02 [1080p].mkv', 'hash': 'h_alias'},
                {'name': '[Group] Re:Test Saga - 02 [1080p].mkv', 'hash': 'h_deriv'},
            ]
            kept = source_utils.filter_sources('nyaa', torrents, 1001, season=1, episode=2, show_title='Test Saga')
            self.assertEqual([t['hash'] for t in kept], ['h_alias'])

            # 6. animepahe falls back from missing malsync title to mappings.db aliases, anikoto uses mal_title
            ap = animepahe.Sources()
            ap_json = json.dumps({'data': [{'title': 'Test Saga Alternate Alias', 'session': 'sess_1001', 'year': 2024}]})
            with patch('resources.lib.endpoints.malsync.get_title', return_value=None), \
                 patch.object(ap, '_resolve_session_from_malsync', return_value=None), \
                 patch('resources.lib.ui.database.get', return_value=ap_json), \
                 patch.object(ap, '_process_ap', return_value=[{'release_title': 'ap_ok'}]) as mock_ap:
                ap_sources = ap.get_sources(1001, 2)
            self.assertEqual(len(ap_sources), 1)
            mock_ap.assert_called_once()

            ak = anikoto.Sources()
            self.assertGreaterEqual(ak._score_candidate('Test Saga Alternate Alias', 'Test Saga', mal_id=1001), 140)
            ak_built_titles = []
            with patch('resources.lib.ui.database.get_show', return_value=None), \
                 patch('resources.lib.ui.database.get_show_meta', return_value=None), \
                 patch('resources.lib.ui.database.get_episode', return_value=None), \
                 patch.object(ak, '_build_source', side_effect=lambda u, t, ep, lang: ak_built_titles.append(t) or None):
                ak.get_sources(1001, 1)
            self.assertIn('Test Saga - Cour One', ak_built_titles)

            # 7. playback.TMDB_HELPER year remake disambiguation via mappings.db year
            from resources.lib.routes import playback
            conn2 = sqlite3.connect(db_path)
            conn2.executemany(
                "INSERT INTO anime (mal_id, mal_title, status, anime_media_type, year) VALUES (?, ?, 'FINISHED', 'MOVIE', ?)",
                [(3001, 'Classic Film Remake', 1998), (3002, 'Classic Film Remake', 2024)],
            )
            conn2.commit()
            conn2.close()
            database.close_all_connections(db_path)
            picked = []
            with patch('resources.lib.OtakuBrowser.OtakuBrowser.get_anime_data'), \
                 patch.object(playback, 'PLAY_MOVIE', side_effect=lambda u, p: picked.append(u)), \
                 patch('resources.lib.ui.control.monitor.waitForAbort', return_value=False):
                playback.TMDB_HELPER('movie', {'actionArgs': json.dumps({'item_type': 'movie', 'title': 'Classic Film Remake', 'year': 2024})})
            self.assertEqual(picked, ['3002/'])

    def test_offline_year_season_browsing_and_search_alias_merge(self):
        with E2EHermeticEnv('22'):
            from resources.lib import Main
            from resources.lib.ui import control, database, multipage, utils
            from resources.lib.routes import search

            # 1. Search menu surfaces Browse by Year & Season (Offline) without touching 24-item Main menu_order
            search_menu = Main.get_menu_items('search')
            self.assertIn('browse_year_season', [row[1] for row in search_menu])

            db_path = control.mappingDB
            database.close_all_connections(db_path)
            _create_v2_mappings_db(db_path, include_rules=False, include_v22=True)
            conn = sqlite3.connect(db_path)
            conn.execute('ALTER TABLE anime ADD COLUMN year INTEGER')
            conn.execute('ALTER TABLE anime ADD COLUMN anime_season TEXT')
            rows_seed = [
                (4100 + idx, f'Autumn Hit {idx}', 'FINISHED', 'TV', 2024, 'FALL', 8.0 + (idx % 5) * 0.1)
                for idx in range(45)
            ]
            rows_seed.append((4200, 'Winter Film', 'FINISHED', 'MOVIE', 2024, 'WINTER', 9.2))
            rows_seed.append((4201, 'Older Hit', 'FINISHED', 'TV', 2020, 'SPRING', 7.8))
            conn.executemany(
                "INSERT INTO anime (mal_id, mal_title, status, anime_media_type, year, anime_season, score) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows_seed,
            )
            conn.execute("INSERT OR IGNORE INTO anime_aliases (mal_id, title) VALUES (4201, 'Aki Special Alias')")
            conn.commit()
            conn.close()
            database.close_all_connections(db_path)

            # 2. DB query helpers aggregate years/seasons and paginate deterministically
            years = database.get_mapping_years(limit=10)
            by_year = {y['year']: y['count'] for y in years}
            self.assertEqual(by_year.get(2024), 46)
            self.assertEqual(by_year.get(2020), 1)

            sc = database.get_mapping_season_counts(2024)
            self.assertEqual(sc['total'], 46)
            self.assertEqual(sc['all_total'], 46)
            self.assertEqual(dict(sc['seasons']), {'WINTER': 1, 'FALL': 45})
            self.assertEqual({k: c for k, _lbl, c in sc['formats']}, {'tv': 45, 'movie': 1})

            sc_mv = database.get_mapping_season_counts(2024, media_format='movie')
            self.assertEqual(sc_mv['total'], 1)
            self.assertEqual(dict(sc_mv['seasons']), {'WINTER': 1})

            p1, has_next1 = database.browse_mappings_by_year_season(2024, 'FALL', page=1, per_page=40)
            p2, has_next2 = database.browse_mappings_by_year_season(2024, 'FALL', page=2, per_page=40)
            self.assertEqual(len(p1), 40)
            self.assertTrue(has_next1)
            self.assertEqual(len(p2), 5)
            self.assertFalse(has_next2)

            # 3. Routes browse_year_season & browse_year/* render format filters, directory items & pagination
            y_res = invoke_plugin_route('browse_year_season')
            self.assertTrue(any('browse_year/2024' in it[1] for it in y_res['directory_items']))

            c_res = invoke_plugin_route('browse_year/2024')
            urls = [it[1] for it in c_res['directory_items']]
            self.assertTrue(any('browse_year/2024/ALL' in u for u in urls))
            self.assertTrue(any('browse_year/2024/FALL' in u for u in urls))
            self.assertTrue(any('browse_year/2024?format=tv' in u for u in urls))
            self.assertTrue(any('browse_year/2024?format=movie' in u for u in urls))

            f_res = invoke_plugin_route('browse_year/2024/FALL')
            self.assertEqual(len(f_res['directory_items']), 42)  # [Filter Format] + 40 shows + Next Page (2)
            self.assertIn('browse_year_filter/2024/FALL', f_res['directory_items'][0][1])
            self.assertEqual(f_res['directory_items'][0][2].getProperty('SpecialSort'), 'top')
            self.assertTrue(any('Next Page (2)' in it[2].getLabel() for it in f_res['directory_items']))

            mv_res = invoke_plugin_route('browse_year/2024/ALL', params={'format': 'movie'})
            mv_urls = [it[1] for it in mv_res['directory_items']]
            self.assertTrue(any('play_movie/4200' in u for u in mv_urls))
            self.assertFalse(any('4100' in u for u in mv_urls))

            exec_calls = []
            with patch('resources.lib.ui.control.select_dialog', return_value=2), \
                 patch('resources.lib.ui.control.execute', side_effect=lambda cmd: exec_calls.append(cmd)):
                invoke_plugin_route('browse_year_filter/2024/ALL')
            self.assertTrue(any('browse_year/2024/ALL?format=movie' in c for c in exec_calls))

            # 4. SEARCH() merges offline alias matches on page 1 BEFORE trailing Next Page without duplicating live mal_ids
            live_dupe = utils.allocate_item('Duplicate Show', 'animes/4100/', True, False, [], '', {'UniqueIDs': {'mal_id': '4100'}})
            live_next = utils.allocate_item('Next Page (2)', 'search_anime/Aki?page=2', True, False, [], 'next.png', {'plot': 'Next Page (2)'}, 'next.png')
            merged = search._merge_offline_search_hits([live_dupe, live_next], 'Aki Special', '')
            merged_mids = [search._extract_item_mal_id(it) for it in merged]
            self.assertEqual(merged_mids.count('4100'), 1)
            self.assertIn('4201', merged_mids)
            self.assertTrue(multipage.is_next_page_item(merged[-1]))

    def test_idle_loop_daily_mappings_sync_guards(self):
        with E2EHermeticEnv('22'):
            import service
            from otaku_service import sync as svc_sync
            from resources.lib.ui import control

            # 1. Skips cleanly when playing video or inside 24h interval
            control.setInt('update.time.30', int(time.time()))
            with patch.object(svc_sync, 'update_mappings_db', return_value=True) as mock_upd:
                self.assertFalse(service._maybe_sync_daily_mappings())
                mock_upd.assert_not_called()

            control.setInt('update.time.30', 100)
            with patch.object(svc_sync.xbmc.Player, 'isPlayingVideo', return_value=True), \
                 patch.object(svc_sync, 'update_mappings_db', return_value=True) as mock_upd:
                self.assertFalse(service._maybe_sync_daily_mappings())
                mock_upd.assert_not_called()

            # 2. Triggers update_mappings_db() and refreshes update.time.30 when idle & overdue
            with patch.object(svc_sync.xbmc.Player, 'isPlayingVideo', return_value=False), \
                 patch('resources.lib.ui.control.is_device_in_standby', return_value=False), \
                 patch.object(svc_sync, 'update_mappings_db', return_value=True) as mock_upd, \
                 patch.object(svc_sync, 'update_metadata_db', return_value=True):
                self.assertTrue(service._maybe_sync_daily_mappings())
                mock_upd.assert_called_once()
                self.assertGreater(control.getInt('update.time.30'), 100)


if __name__ == '__main__':
    unittest.main()
