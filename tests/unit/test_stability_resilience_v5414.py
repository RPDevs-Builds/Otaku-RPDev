import http.client
import io
import json
import os
import unittest
import urllib.request
from unittest.mock import patch, MagicMock

import tests.conftest  # noqa: F401
from resources.lib.ui import client, control, database
from resources.lib.debrid import debrid_cache
from resources.lib.windows.resolver import Resolver
from resources.lib.windows.download_manager import Manager
from resources.lib.pages import Sources
from resources.lib.routes import playback, search


class TestStabilityResilienceV5414(unittest.TestCase):

    def setUp(self):
        self.test_dir = os.path.join(control.dataPath, 'test_v5414')
        os.makedirs(self.test_dir, exist_ok=True)
        self.test_search_db = os.path.join(self.test_dir, 'test_search.db')
        self.test_cache_db = os.path.join(self.test_dir, 'test_cache.db')
        self.test_downloads_json = os.path.join(self.test_dir, 'test_downloads.json')

        self._orig_search_db = control.searchHistoryDB
        self._orig_cache_db = control.cacheFile
        self._orig_downloads_json = control.downloads_json

        control.searchHistoryDB = self.test_search_db
        control.cacheFile = self.test_cache_db
        control.downloads_json = self.test_downloads_json

        client._session_openers.clear()

    def tearDown(self):
        control.searchHistoryDB = self._orig_search_db
        control.cacheFile = self._orig_cache_db
        control.downloads_json = self._orig_downloads_json

        if os.path.exists(self.test_dir):
            import shutil
            shutil.rmtree(self.test_dir, ignore_errors=True)

    # 1. 5MB Download Cap Fix in client.py
    @patch('urllib.request.build_opener')
    def test_client_request_no_limit_reads_large_payload(self, mock_build_opener):
        large_payload = b'X' * 6500000  # 6.5 MB (> 5MB)
        mock_response = MagicMock()
        mock_response.headers = {'Content-Length': str(len(large_payload)), 'Content-Type': 'application/octet-stream'}
        mock_response.read = MagicMock(return_value=large_payload)

        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_response
        mock_build_opener.return_value = mock_opener

        # Request with limit=None
        res = client.request('https://github.com/fake/anime_mappings.db', use_session=False)
        self.assertEqual(len(res), 6500000)
        mock_response.read.assert_called_once_with()

    @patch('urllib.request.build_opener')
    def test_client_request_incomplete_read_recovery(self, mock_build_opener):
        partial_data = b'partial data before disconnect'
        mock_response = MagicMock()
        mock_response.headers = {'Content-Length': '1000', 'Content-Type': 'application/octet-stream'}
        mock_response.read.side_effect = http.client.IncompleteRead(partial=partial_data)

        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_response
        mock_build_opener.return_value = mock_opener

        res = client.request('https://example.com/stream', use_session=False)
        self.assertEqual(res, partial_data)

    # 2. Scraper Worker Early Cancellation
    def test_scraper_workers_respect_cancellation(self):
        sources_mgr = Sources('get_sources.xml', 'special://home', actionArgs={'silent': True})
        sources_mgr.canceled = True
        sources_mgr.remainingProviders = ['gogo', 'animepahe']
        sources_mgr.torrentSources = []
        sources_mgr.hosterSources = []
        sources_mgr.embedSources = []
        sources_mgr.local_files = []
        sources_mgr.cloud_files = []

        # Calling worker when canceled must return immediately without scraping
        with patch('resources.lib.ui.database.get') as mock_db_get:
            sources_mgr._torrent_sources_worker('gogo', 'Naruto', 20, 1, 'airing', 'tv', False, 1, 1)
            mock_db_get.assert_not_called()
            self.assertEqual(len(sources_mgr.torrentSources), 0)

            sources_mgr._hoster_sources_worker('animepahe', 'Naruto', 20, 1, 'airing', 'tv', False, 1, 1)
            mock_db_get.assert_not_called()
            self.assertEqual(len(sources_mgr.hosterSources), 0)

            sources_mgr._embed_sources_worker('embed_id', MagicMock(), 'cache_key', '', False, 20, 1, 'tv', False)
            mock_db_get.assert_not_called()
            self.assertEqual(len(sources_mgr.embedSources), 0)

            sources_mgr.user_local_inspection('Naruto', 20, 1, 1)
            self.assertEqual(len(sources_mgr.local_files), 0)

            sources_mgr.user_cloud_inspection('Naruto', 20, 1, 1)
            self.assertEqual(len(sources_mgr.cloud_files), 0)

    # 3. Bounded Debrid Hash Joins & No VACUUM
    @patch('threading.Thread')
    def test_debrid_hash_joins_bounded_timeout(self, mock_thread_cls):
        mock_t1 = MagicMock()
        mock_t2 = MagicMock()
        mock_thread_cls.side_effect = [mock_t1, mock_t2]

        debrid_cache.check_rd_cache(['hash1'], 'tt12345', 1, 1)
        mock_t1.join.assert_called_with(timeout=8)
        mock_t2.join.assert_called_with(timeout=8)

        mock_t3 = MagicMock()
        mock_thread_cls.side_effect = [mock_t3]
        debrid_cache.check_ad_cache('tt12345', 1, 1)
        mock_t3.join.assert_called_with(timeout=8)

    def test_clear_debrid_cache_no_vacuum(self):
        debrid_cache._ensure_debrid_cache_table()
        with database.SQL(self.test_cache_db) as cur:
            cur.execute("INSERT INTO debrid_cache (hash, debrid, cached) VALUES ('h1', 'rd', 1)")
            cur.connection.commit()

        queries_executed = []
        with patch.object(database.SQL, '__enter__', autospec=True) as mock_enter:
            mock_cursor = MagicMock()
            def track_execute(sql, *args, **kwargs):
                queries_executed.append(sql)
            mock_cursor.execute.side_effect = track_execute
            mock_enter.return_value = mock_cursor

            debrid_cache.clear_debrid_cache()

        self.assertIn('DELETE FROM debrid_cache', queries_executed)
        self.assertNotIn('VACUUM', queries_executed)

    # 4. SQLite ROWID DESC Search History Optimization
    def test_search_history_rowid_desc(self):
        # Insert search history in sequence
        database.addSearchHistory('Bleach', 'anime')
        database.addSearchHistory('Naruto', 'anime')
        database.addSearchHistory('One Piece', 'anime')

        history = database.getSearchHistory('anime')
        # Expect newest to oldest order: One Piece, Naruto, Bleach
        self.assertEqual(history, ['One Piece', 'Naruto', 'Bleach'])

        # Updating/re-adding an existing term brings it to the top
        database.addSearchHistory('Bleach', 'anime')
        history_updated = database.getSearchHistory('anime')
        self.assertEqual(history_updated, ['Bleach', 'One Piece', 'Naruto'])

    # 5. Deterministic Resolver Reordering
    def test_resolver_reorder_sources_immediate_return(self):
        resolver = Resolver('resolver.xml', 'special://home', actionArgs={'episode': 2, 'mal_id': 1234})
        resolver.source_select = False
        resolver.episode = 2

        sources = [
            {'type': 'torrent', 'release_title': '[SubsPlease] Anime Show - 02 [1080p]'},
            {'type': 'torrent', 'release_title': '[Erai-raws] Anime Show - 02 [1080p]'},
            {'type': 'torrent', 'release_title': '[Judas] Anime Show - 02 [1080p]'},
        ]

        with patch('resources.lib.ui.control.getSetting', return_value='[Erai-raws] Anime Show - 01 [1080p]'):
            reordered = resolver.reorder_sources(list(sources))
            # Erai-raws must be swapped from index 1 to index 0
            self.assertEqual(reordered[0]['release_title'], '[Erai-raws] Anime Show - 02 [1080p]')
            self.assertEqual(reordered[1]['release_title'], '[SubsPlease] Anime Show - 02 [1080p]')

    # 6. Safe ast.literal_eval and Query Params
    @patch('resources.lib.ui.control.getSetting', return_value='')
    @patch('resources.lib.ui.control.addon_url', return_value='plugin://test/url')
    @patch('resources.lib.ui.database.get_episode', return_value=None)
    @patch('resources.lib.ui.database.get_show', return_value=None)
    @patch('resources.lib.MetaBrowser.get_anime_init', return_value=None)
    @patch('resources.lib.ui.control.draw_items')
    @patch('resources.lib.MetaBrowser.get_sources', return_value=[])
    def test_playback_rating_ast_eval_safe(self, *mocks):
        # Malformed rating string must not raise SyntaxError/ValueError
        malformed_rating = "{invalid:syntax[malformed"
        params = {'rating': malformed_rating, 'tvshowtitle': 'Test Show'}
        try:
            playback.PLAY('12345/1', params)
            # Must preserve raw string on syntax error fallback
            self.assertEqual(params['rating'], malformed_rating)
        except (ValueError, SyntaxError) as exc:
            self.fail(f"PLAY raised exception on malformed rating: {exc}")

    @patch('resources.lib.Main.plugin_url', 'search_anime/test')
    @patch('resources.lib.ui.control.getStr', return_value='mal')
    @patch('resources.lib.ui.control.draw_items')
    @patch('resources.lib.ui.control.schedule_next_page_prefetch')
    def test_search_page_safe_int(self, *mocks):
        from resources.lib import Main
        Main.BROWSER = MagicMock()
        Main.BROWSER.get_search.return_value = []

        # Invalid page params: non-numeric, empty string, None
        for invalid_page in ['invalid', '', None]:
            params = {'page': invalid_page}
            try:
                search.SEARCH('naruto', params)
                Main.BROWSER.get_search.assert_called_with('naruto', 1, '', 'search_anime')
            except (ValueError, TypeError) as exc:
                self.fail(f"SEARCH raised exception on invalid page {invalid_page}: {exc}")

    # 7. Resilient Download Manager Safe JSON Persistence & Reading
    def test_download_manager_safe_json(self):
        # Case A: Missing file returns empty dict
        if os.path.exists(self.test_downloads_json):
            os.remove(self.test_downloads_json)
        self.assertEqual(Manager._read_downloads_safe(), {})

        # Case B: Corrupt / HTML / incomplete JSON returns empty dict
        with open(self.test_downloads_json, 'w', encoding='utf-8') as f:
            f.write("<html>Bad Gateway</html>")
        self.assertEqual(Manager._read_downloads_safe(), {})

        # Case C: Valid JSON returns parsed data
        valid_data = {"hash123": {"url": "http://example.com/video.mp4", "progress": 50}}
        with open(self.test_downloads_json, 'w', encoding='utf-8') as f:
            json.dump(valid_data, f)
        self.assertEqual(Manager._read_downloads_safe(), valid_data)

        # Case D: cancel_task on missing hash does not raise KeyError
        dm = Manager()
        dm.download_ids = []
        try:
            dm.cancel_task("nonexistent_hash")
        except KeyError as exc:
            self.fail(f"cancel_task raised KeyError on missing hash: {exc}")


if __name__ == '__main__':
    unittest.main()
