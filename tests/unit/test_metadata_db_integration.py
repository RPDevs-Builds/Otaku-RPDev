# -*- coding: utf-8 -*-
"""Unit tests for full anime_metadata.db + anime_mappings.db integration in Otaku-RPDev."""

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch


class TestMetadataDBIntegration(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.map_db = os.path.join(self.tmpdir.name, 'anime_mappings.db')
        self.meta_db = os.path.join(self.tmpdir.name, 'anime_metadata.db')

        # Build minimal anime_mappings.db
        conn = sqlite3.connect(self.map_db)
        conn.execute("CREATE TABLE activities (sync_id INTEGER PRIMARY KEY, last_updated TEXT NOT NULL)")
        conn.execute(
            "CREATE TABLE anime ("
            "mal_id INTEGER PRIMARY KEY, mal_dub_id INTEGER, anilist_id INTEGER, "
            "kitsu_id INTEGER, anidb_id INTEGER, simkl_id INTEGER, thetvdb_id INTEGER, "
            "themoviedb_id INTEGER, imdb_id TEXT, trakt_id INTEGER, mal_title TEXT, "
            "mal_picture TEXT, thetvdb_season INTEGER, thetvdb_part INTEGER, "
            "duration INTEGER, score REAL, status TEXT, anime_media_type TEXT, "
            "global_media_type TEXT, anime_media_episodes TEXT, global_media_episodes TEXT, "
            "year INTEGER, anime_season TEXT, episodes INTEGER, title_english TEXT, "
            "genres TEXT, studios TEXT, start_date TEXT, trakt_slug TEXT)"
        )
        conn.execute(
            "CREATE TABLE schedule_ids ("
            "mal_id INTEGER PRIMARY KEY, syobocal_tid INTEGER, annict_id INTEGER, "
            "livechart_id INTEGER, anisearch_id INTEGER, anime_planet_id TEXT, "
            "animenewsnetwork_id INTEGER, animecountdown_id INTEGER)"
        )
        conn.execute("CREATE TABLE build_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO activities VALUES (1, '1700000000')")
        conn.execute(
            "INSERT INTO anime (mal_id, anilist_id, thetvdb_id, mal_title, title_english, "
            "anime_media_type, global_media_type, status, year, anime_season, episodes, trakt_slug) "
            "VALUES (1, 1, 76885, 'Cowboy Bebop', 'Cowboy Bebop', 'TV', 'show', 'FINISHED', 1998, 'SPRING', 26, 'cowboy-bebop')"
        )
        conn.execute("INSERT INTO schedule_ids VALUES (1, 100, 200, 300, 400, 'cowboy-bebop', 13, 500)")
        conn.commit()
        conn.close()

        # Build minimal anime_metadata.db
        mconn = sqlite3.connect(self.meta_db)
        mconn.execute(
            "CREATE TABLE anime_metadata ("
            "mal_id INTEGER PRIMARY KEY, mal_title TEXT NOT NULL, title_english TEXT, "
            "title_native TEXT, mal_picture TEXT, anime_media_type TEXT NOT NULL, "
            "global_media_type TEXT NOT NULL, status TEXT, episodes INTEGER, duration INTEGER, "
            "score REAL, year INTEGER, anime_season TEXT, start_date TEXT, end_date TEXT, "
            "genres TEXT, studios TEXT, synopsis TEXT, age_rating TEXT, banner_image TEXT, "
            "trailer_yt_id TEXT, country_of_origin TEXT, dub_status TEXT, provenance_json TEXT)"
        )
        mconn.execute(
            "CREATE TABLE external_ids ("
            "mal_id INTEGER PRIMARY KEY, mal_dub_id INTEGER, anilist_id INTEGER, kitsu_id INTEGER, "
            "anidb_id INTEGER, simkl_id INTEGER, thetvdb_id INTEGER, themoviedb_id INTEGER, "
            "imdb_id TEXT, trakt_id INTEGER, trakt_slug TEXT, syobocal_tid INTEGER, "
            "annict_id INTEGER, livechart_id INTEGER, anisearch_id INTEGER, anime_planet_id TEXT, "
            "animenewsnetwork_id INTEGER, animecountdown_id INTEGER)"
        )
        mconn.execute(
            "CREATE TABLE anime_aliases ("
            "mal_id INTEGER NOT NULL, alias TEXT NOT NULL, alias_norm TEXT NOT NULL, source_type TEXT NOT NULL)"
        )
        mconn.execute("CREATE TABLE build_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        mconn.execute(
            "CREATE VIRTUAL TABLE metadata_fts USING fts5("
            "mal_title, title_english, title_native, aliases_text, content='')"
        )
        mconn.execute(
            "INSERT INTO anime_metadata VALUES ("
            "1, 'Cowboy Bebop', 'Cowboy Bebop', 'カウボーイビバップ', 'https://img/cb.jpg', 'TV', 'show', "
            "'FINISHED', 26, 1440, 8.75, 1998, 'SPRING', '1998-04-03', '1999-04-24', "
            "'Action,Sci-Fi', 'Sunrise', 'Crime is timeless in 2071.', 'R - 17+', "
            "'https://img/cb_banner.jpg', 'gY5nDXOtv_o', 'JP', 'COMPLETE', '{}')"
        )
        mconn.execute(
            "INSERT INTO external_ids VALUES (1, 1, 1, 1, 23, 123, 76885, 30991, 'tt0213338', 30991, 'cowboy-bebop', 100, 200, 300, 400, 'cowboy-bebop', 13, 500)"
        )
        mconn.execute("INSERT INTO anime_aliases VALUES (1, 'カウボーイビバップ', 'カウボーイビバップ', 'native')")
        mconn.execute(
            "INSERT INTO metadata_fts (rowid, mal_title, title_english, title_native, aliases_text) "
            "VALUES (1, 'Cowboy Bebop', 'Cowboy Bebop', 'カウボーイビバップ', 'カウボーイビバップ')"
        )
        mconn.execute("INSERT INTO build_meta VALUES ('synopsis_count', '1')")
        mconn.execute("INSERT INTO build_meta VALUES ('schema_version', '2.8')")
        mconn.commit()
        mconn.close()

    def tearDown(self):
        from resources.lib.ui import database
        database.close_all_connections()
        self.tmpdir.cleanup()

    def test_metadata_db_info_and_offline_enrichment(self):
        from resources.lib.ui import control, database, utils

        with patch.object(control, 'mappingDB', self.map_db), patch.object(control, 'metadataDB', self.meta_db):
            info = database.get_metadata_db_info()
            self.assertEqual(info['row_count'], 1)
            self.assertEqual(info['alias_count'], 1)
            self.assertEqual(info['external_id_count'], 1)
            self.assertEqual(info['synopsis_count'], 1)

            meta = database.get_offline_anime_metadata(1)
            self.assertEqual(meta['title_native'], 'カウボーイビバップ')
            self.assertEqual(meta['age_rating'], 'R - 17+')
            self.assertEqual(meta['trailer_yt_id'], 'gY5nDXOtv_o')
            self.assertEqual(meta['livechart_id'], 300)

            uids = database.get_unique_ids(1, 'mal_id')
            self.assertEqual(uids['trakt_slug'], 'cowboy-bebop')
            self.assertEqual(uids['livechart'], 300)
            self.assertEqual(uids['ann'], 13)

            rows, has_next = database.browse_mappings_by_year_season(1998, 'SPRING')
            self.assertFalse(has_next)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['synopsis'], 'Crime is timeless in 2071.')

            items = utils.allocate_offline_mapping_items(rows)
            self.assertEqual(len(items), 1)
            self.assertIn('Crime is timeless in 2071.', items[0]['info']['plot'])
            self.assertEqual(items[0]['info']['mpaa'], 'R - 17+')
            self.assertEqual(items[0]['info']['trailer'], 'plugin://plugin.video.youtube/play/?video_id=gY5nDXOtv_o')
            self.assertEqual(items[0]['image']['banner'], 'https://img/cb_banner.jpg')

    def test_service_sync_calls_both_mappings_and_metadata(self):
        import service
        from resources.lib.ui import control

        with patch.object(control, 'getInt', return_value=0), \
             patch.object(control, 'setInt'), \
             patch.object(control, 'abort_requested', return_value=False), \
             patch.object(control, 'is_device_in_standby', return_value=False), \
             patch.object(service, 'update_mappings_db', return_value=True) as mock_map, \
             patch.object(service, 'update_metadata_db', return_value=True) as mock_meta:
            ok = service._maybe_sync_daily_mappings(interval_s=86400)
            self.assertTrue(ok)
            mock_map.assert_called_once()
            mock_meta.assert_called_once()
