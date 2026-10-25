import os
import unittest
from unittest.mock import patch, MagicMock

import tests.conftest  # noqa: F401
from resources.lib.ui import control, database, source_utils
from resources.lib.ui.player import WatchlistPlayer


class TestStandardsAndResilienceV5413(unittest.TestCase):

    def setUp(self):
        self.test_dir = os.path.join(control.dataPath, 'test_v5413')
        os.makedirs(self.test_dir, exist_ok=True)
        self.test_cache_db = os.path.join(self.test_dir, 'test_cache.db')
        self._orig_cache_file = control.cacheFile
        control.cacheFile = self.test_cache_db

    def tearDown(self):
        control.cacheFile = self._orig_cache_file
        if os.path.exists(self.test_dir):
            import shutil
            shutil.rmtree(self.test_dir, ignore_errors=True)

    # 1. Unicode NFKD Transliteration in cleanTitle
    def test_clean_title_unicode_nfkd_decomposition(self):
        self.assertEqual(source_utils.cleanTitle('Pokémon'), 'pokemon')
        self.assertEqual(source_utils.cleanTitle('Ōsama Ranking'), 'osama ranking')
        self.assertEqual(source_utils.cleanTitle('Yū Yū Hakusho'), 'yu yu hakusho')
        self.assertEqual(source_utils.cleanTitle('Sousou no Frieren'), 'sousou no frieren')
        self.assertEqual(source_utils.cleanTitle("JoJo's Bizarre Adventure"), 'jojos bizarre adventure')
        self.assertEqual(source_utils.cleanTitle(''), '')
        self.assertEqual(source_utils.cleanTitle(None), '')

    # 2. Centralized Safe JSON Deserializer (control.loads_json)
    def test_loads_json_valid_and_invalid(self):
        self.assertEqual(control.loads_json('{"key": "value"}'), {'key': 'value'})
        self.assertEqual(control.loads_json('[1, 2, 3]'), [1, 2, 3])
        # Cloudflare / HTTP 502 HTML
        html_page = '<!DOCTYPE html><html><body>502 Bad Gateway</body></html>'
        self.assertIsNone(control.loads_json(html_page))
        self.assertEqual(control.loads_json(html_page, default={}), {})
        # Corrupt JSON
        self.assertIsNone(control.loads_json('{"unclosed": "brace"'))
        self.assertEqual(control.loads_json('', default='default'), 'default')
        self.assertIsNone(control.loads_json(None))

    # 3. LRU Cache on get_cache_check_reg
    def test_get_cache_check_reg_lru_cache(self):
        reg_int = source_utils.get_cache_check_reg(1)
        reg_str = source_utils.get_cache_check_reg('1')
        # Ensure identical cached object is returned
        self.assertIs(reg_int, reg_str)
        # Verify matching capability
        self.assertTrue(bool(reg_int.search('Anime Show - S01E01 [1080p]')))
        self.assertFalse(bool(reg_int.search('Anime Show - S01E02 [1080p]')))

    # 4. Dialog Text Sanitization (control.sanitize_dialog_text)
    def test_sanitize_dialog_text(self):
        # Null bytes and control characters stripped
        dirty = "Release\x00Title\x07With\x1bEscape"
        clean = control.sanitize_dialog_text(dirty)
        self.assertEqual(clean, "ReleaseTitleWithEscape")

        # Kodi markup preserved by default
        formatted = "[COLOR red]Alert[/COLOR] Something happened"
        self.assertEqual(control.sanitize_dialog_text(formatted), formatted)

        # Kodi markup stripped when strip_formatting=True
        self.assertEqual(
            control.sanitize_dialog_text(formatted, strip_formatting=True),
            "Alert Something happened"
        )
        self.assertEqual(control.sanitize_dialog_text(None), '')

    # 5. SQLite Cache Index on date and prune without VACUUM
    def test_cache_date_index_and_prune(self):
        database._init_cache_table()
        # Verify index exists in sqlite_master
        with database.SQL(self.test_cache_db) as cur:
            cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='cache'")
            indexes = [r['name'] for r in cur.fetchall()]
        self.assertIn('ix_cache', indexes)
        self.assertIn('ix_cache_date', indexes)

        # Seed expired and active cache entries
        with database.SQL(self.test_cache_db) as cur:
            cur.execute("INSERT INTO cache (key, value, date) VALUES ('old_key', 'old_val', 1000)")
            cur.execute("INSERT INTO cache (key, value, date) VALUES ('new_key', 'new_val', 2000000000)")
            cur.connection.commit()

        # Prune expired cache entries
        deleted = database.prune_expired_cache(30)
        self.assertEqual(deleted, 1)

        # Verify only new_key remains
        with database.SQL(self.test_cache_db) as cur:
            cur.execute("SELECT key FROM cache")
            remaining = [r['key'] for r in cur.fetchall()]
        self.assertEqual(remaining, ['new_key'])

    # 6. Player Bookmark Zero-Duration and Bounds Guard
    @patch('resources.lib.ui.control.jsonrpc')
    @patch('resources.lib.ui.control.clean_memory')
    @patch('resources.lib.ui.control.closeAllDialogs')
    def test_player_on_playback_stopped_duration_bounds(self, mock_close, mock_clean, mock_jsonrpc):
        player = WatchlistPlayer()
        player.context = True
        player.path = 'plugin://plugin.video.otaku.rpdev/play/episode'

        # Case A: total_time <= 60 (corrupt/buffering failure)
        player.total_time = 0
        player.current_time = 0
        player.onPlayBackStopped()
        mock_jsonrpc.assert_not_called()

        player.total_time = 45  # Under 60 seconds
        player.current_time = 25
        player.onPlayBackStopped()
        mock_jsonrpc.assert_not_called()

        # Case B: Out-of-bounds current_time
        player.total_time = 1400
        player.current_time = -10
        player.onPlayBackStopped()
        mock_jsonrpc.assert_not_called()

        # Case C: Valid playback between 10% and 90% (e.g. 50% watched)
        player.total_time = 1400
        player.current_time = 700
        player.onPlayBackStopped()
        mock_jsonrpc.assert_called_once()
        rpc_call = mock_jsonrpc.call_args[0][0]
        self.assertEqual(rpc_call['method'], 'Files.SetFileDetails')
        self.assertEqual(rpc_call['params']['resume']['position'], 700)
        self.assertEqual(rpc_call['params']['resume']['total'], 1400)

    # 7. Menu Customization visibility logic
    @patch('resources.lib.debrid.debrid_cloud.get_active_providers', return_value=['realdebrid'])
    def test_my_cloud_visibility_strictly_tied_to_menu_config(self, mock_providers):
        from resources.lib.Main import _collect_category_menu_items
        # When 'my_cloud' is NOT in menu.mainmenu.config
        with patch('resources.lib.ui.control.getStringList', return_value=['last_watched', 'next_up']):
            with patch('resources.lib.ui.control.getBool', return_value=True):
                items = _collect_category_menu_items('main', 'menu.mainmenu.config', '')
                cloud_items = [itm for itm in items if itm[1] == 'my_cloud']
                self.assertEqual(len(cloud_items), 0)

        # When 'my_cloud' IS in menu.mainmenu.config
        with patch('resources.lib.ui.control.getStringList', return_value=['last_watched', 'my_cloud']):
            with patch('resources.lib.ui.control.getBool', return_value=True):
                items = _collect_category_menu_items('main', 'menu.mainmenu.config', '')
                cloud_items = [itm for itm in items if itm[1] == 'my_cloud']
                self.assertEqual(len(cloud_items), 1)


if __name__ == '__main__':
    unittest.main()
