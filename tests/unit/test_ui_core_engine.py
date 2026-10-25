"""
test_ui_core_engine.py - Unit Tests for Core Engine & Utilities (Phase 2)
========================================================================
Covers control.py, client.py, database.py, and utils.py error resilience,
transactional rollback, schema handling, atomic writes, and string parsing.
"""

import os
import unittest
import tempfile
import json
from unittest.mock import patch, MagicMock

import conftest
from resources.lib.ui import control, client, database, utils


class TestUICoreEngine(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="otaku_core_test_")
        self.db_path = os.path.join(self.temp_dir, "test_core.db")

    def tearDown(self):
        database.close_thread_connections()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_control_detect_max_threads(self):
        threads = control._detect_max_threads()
        self.assertIsInstance(threads, int)
        self.assertGreaterEqual(threads, 2)
        self.assertLessEqual(threads, 8)

    def test_control_sanitize_log(self):
        control.setSetting('realdebrid.token', 'SUPER_SECRET_RD_TOKEN')
        msg = "Error occurred while fetching with token SUPER_SECRET_RD_TOKEN for user"
        sanitized = control.sanitize_log(msg)
        self.assertNotIn("SUPER_SECRET_RD_TOKEN", sanitized)
        self.assertIn("[REDACTED]", sanitized)

    def test_control_atomic_writes(self):
        target_json = os.path.join(self.temp_dir, "test.json")
        target_text = os.path.join(self.temp_dir, "test.txt")
        target_bin = os.path.join(self.temp_dir, "test.bin")

        self.assertTrue(control.atomic_write_json(target_json, {"status": "ok", "version": 5}))
        with open(target_json, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data["version"], 5)

        self.assertTrue(control.atomic_write_text(target_text, "Hello Otaku!"))
        with open(target_text, 'r', encoding='utf-8') as f:
            self.assertEqual(f.read(), "Hello Otaku!")

        self.assertTrue(control.atomic_write_bytes(target_bin, b"\x00\x01\x02\x03"))
        with open(target_bin, 'rb') as f:
            self.assertEqual(f.read(), b"\x00\x01\x02\x03")

    def test_control_set_videotags(self):
        li = control.xbmcgui.ListItem("Attack on Titan")
        meta = {
            'title': 'Attack on Titan',
            'mediatype': 'tvshow',
            'tvshowtitle': 'Attack on Titan',
            'plot': 'Humanity lives inside walls...',
            'year': 2013,
            'premiered': '2013-04-07',
            'status': 'Ended',
            'genre': ['Action', 'Fantasy'],
            'mpaa': 'TV-MA',
            'rating': {'score': 8.5, 'votes': 15000},
            'season': 1,
            'episode': 1,
            'aired': '2013-04-07',
            'playcount': 2,
            'duration': 1440,
            'code': 'SNK-01',
            'studio': ['WIT STUDIO', 'Production I.G'],
            'country': ['Japan'],
            'OriginalTitle': '進撃の巨人',
            'UniqueIDs': {'mal_id': '16498', 'imdb': 'tt2560140'},
            'resume': 600.0
        }
        control.set_videotags(li, meta)
        vtag = li.getVideoInfoTag()
        self.assertEqual(vtag.getTitle(), 'Attack on Titan')
        self.assertEqual(vtag.getMediaType(), 'tvshow')
        self.assertEqual(vtag.getYear(), 2013)
        self.assertEqual(vtag.getStudios(), ['WIT STUDIO'])
        self.assertEqual(li.getProperty('mal_id'), '16498')
        self.assertEqual(vtag.getResumePoint(), 600.0)

    def test_client_ssl_contexts(self):
        unverified = client._get_ssl_context(verify=False)
        self.assertIsNotNone(unverified)
        verified = client._get_ssl_context(verify=True)
        self.assertIsNotNone(verified)

    def test_client_url_helpers(self):
        self.assertTrue(client._validate_url_scheme("https://api.jikan.moe/v4"))
        self.assertTrue(client._validate_url_scheme("http://127.0.0.1:8080/"))
        with self.assertRaises(ValueError):
            client._validate_url_scheme("file:///etc/passwd")
        with self.assertRaises(ValueError):
            client._validate_url_scheme("ftp://example.com")

        url_with_hdrs = client._url_with_headers("http://example.com/video.mkv", {"User-Agent": "Kodi", "Referer": "http://site.com"})
        self.assertIn("|User-Agent=Kodi|Referer=", url_with_hdrs)

        stripped, hdrs = client._strip_url(url_with_hdrs)
        self.assertEqual(stripped, "http://example.com/video.mkv")
        self.assertEqual(hdrs.get('User-Agent'), 'Kodi')

    def test_database_sql_context_and_rollback(self):
        with database.SQL(self.db_path) as cur:
            cur.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, val TEXT)")
            cur.execute("INSERT INTO test_table (val) VALUES ('item1')")
            cur.connection.commit()

        with database.SQL(self.db_path) as cur:
            cur.execute("SELECT val FROM test_table WHERE id=1")
            row = cur.fetchone()
            self.assertEqual(row['val'], 'item1')

        # Test explicit transaction rollback on error
        try:
            with database.SQL(self.db_path) as cur:
                cur.execute("BEGIN TRANSACTION")
                cur.execute("INSERT INTO test_table (val) VALUES ('item2')")
                raise ValueError("Forced error during transaction")
        except ValueError:
            pass

        with database.SQL(self.db_path) as cur:
            cur.execute("SELECT COUNT(*) as count FROM test_table")
            self.assertEqual(cur.fetchone()['count'], 1)

    def test_database_search_history(self):
        with patch.object(control, 'searchHistoryDB', self.db_path):
            with database.SQL(self.db_path) as cur:
                cur.execute("CREATE TABLE IF NOT EXISTS anime_history (search_query TEXT, time_stamp TEXT)")
                cur.connection.commit()

            database.addSearchHistory("Naruto", "anime")
            history = database.getSearchHistory("anime")
            self.assertIn("Naruto", history)

            database.clearSearchHistory()
            history_after = database.getSearchHistory("anime")
            self.assertEqual(len(history_after), 0)

    def test_utils_get_season(self):
        titles = ["Shingeki no Kyojin", "Attack on Titan Season 2", "進撃の巨人 Season 2"]
        season = utils.get_season(titles, 99999)
        self.assertEqual(season, 2)

        titles_s1 = ["Death Note", "デスノート"]
        season_s1 = utils.get_season(titles_s1, 99998)
        self.assertEqual(season_s1, 1)

    def test_utils_allocate_item(self):
        item = utils.allocate_item(
            name="Episode 1",
            url="play_episode/1",
            isfolder=False,
            isplayable=True,
            cm=[("Play", "PlayMedia")],
            image="http://example.com/icon.png",
            poster="http://example.com/poster.png"
        )
        self.assertEqual(item['name'], "Episode 1")
        self.assertFalse(item['isfolder'])
        self.assertTrue(item['isplayable'])
        self.assertEqual(item['image']['poster'], "http://example.com/poster.png")


if __name__ == "__main__":
    unittest.main()
