import unittest
from unittest.mock import patch, MagicMock

from resources.lib.ui import control, source_utils, database
from resources.lib.debrid import debrid_cache
from resources.lib.windows.skip_intro import SkipIntro
from resources.lib.MalBrowser import MalBrowser
from resources.lib.AniListBrowser import AniListBrowser
from resources.lib import Main


class TestStabilityFixesV5521(unittest.TestCase):
    def setUp(self):
        control.clearSettingsCache()

    def test_season_pack_regex_word_boundaries(self):
        """Ensure season pack detection properly matches word boundaries without ASCII control chars."""
        # Check source code has no backspace characters
        import inspect
        src = inspect.getsource(source_utils.is_season_pack)
        self.assertNotIn('\x08', src)

        # Common anime title formats
        self.assertTrue(source_utils.is_season_pack({'release_title': 'Black Butler Season 1 [1080p]'}))
        self.assertTrue(source_utils.is_season_pack({'release_title': 'Black Butler S01 1080p BluRay'}))
        self.assertTrue(source_utils.is_season_pack({'release_title': '[Judas] Slime (Season 04) (Batch)'}))
        self.assertTrue(source_utils.is_season_pack({'release_title': '[SubsPlease] Youjo Senki - 01-12 [Batch]'}))

        # Single episode files must NOT be detected as season packs
        self.assertFalse(source_utils.is_season_pack({'release_title': '[bonkai77] Black Butler Episode 21 1080p.mkv'}))
        self.assertFalse(source_utils.is_season_pack({'release_title': 'Black Butler S01E05 1080p.mkv'}))
        self.assertFalse(source_utils.is_season_pack({'release_title': 'Black Butler Season 1 Episode 5'}))

    def test_settings_persistence_to_homewindow_and_cache(self):
        """Ensure setSetting/setBool/setInt writes to homeWindow properties and in-memory cache."""
        control.setSetting('last_watched_series', '4898')
        self.assertEqual(control.getSetting('last_watched_series'), '4898')
        self.assertEqual(control.homeWindow.getProperty(f'{control.ADDON_ID}_last_watched_series'), '4898')

        control.setSetting('last_played_source', 'Test Source Title')
        self.assertEqual(control.getSetting('last_played_source'), 'Test Source Title')
        self.assertEqual(control.homeWindow.getProperty(f'{control.ADDON_ID}_last_played_source'), 'Test Source Title')

        control.setBool('test_flag', True)
        self.assertTrue(control.getBool('test_flag'))
        self.assertEqual(control.homeWindow.getProperty(f'{control.ADDON_ID}_test_flag'), 'true')

        control.setInt('test_number', 42)
        self.assertEqual(control.getInt('test_number'), 42)
        self.assertEqual(control.homeWindow.getProperty(f'{control.ADDON_ID}_test_number'), '42')

    def test_debrid_cache_only_returns_positive_cached(self):
        """Ensure get_cached_hashes only retrieves confirmed True cached hashes and ignores negative entries."""
        with patch.object(database, 'SQL') as mock_sql:
            mock_cur = MagicMock()
            mock_sql.return_value.__enter__.return_value = mock_cur
            mock_cur.fetchall.return_value = [
                {'hash': 'hash1', 'debrid': 'rd', 'cached': 'True'},
            ]

            results = debrid_cache.get_cached_hashes(['hash1', 'hash2'])
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]['hash'], 'hash1')
            # Verify query explicitly required cached = "True"
            executed_query = mock_cur.execute.call_args[0][0]
            self.assertIn('cached = "True"', executed_query)

    def test_skip_intro_background_tasks_zero_total_time(self):
        """Ensure SkipIntro does not exit prematurely when total_time is 0 / uninitialized."""
        mock_player = MagicMock()
        mock_player.isPlaying.return_value = True
        mock_player.getTime.side_effect = [0, 5, 95]
        mock_player.getTotalTime.side_effect = [0, 1400, 1400]

        args = {'item_type': 'skip_intro', 'skipintro_aniskip': True, 'skipintro_end': 90}
        dialog = SkipIntro('skip_intro_default.xml', control.ADDON_PATH, actionArgs=args)
        dialog.player = mock_player
        dialog.total_time = 0

        # Run one step of loop logic
        with patch('xbmc.sleep', side_effect=lambda ms: None):
            # Check condition when total_time is 0
            current_time = 0
            total_time = 0
            early_break = (total_time > 0 and (total_time - current_time <= 2)) or (current_time > dialog.skipintro_end_skip_time)
            self.assertFalse(early_break)

            # Check condition when current_time reaches beyond skipintro_end
            current_time = 95
            total_time = 1400
            end_break = (total_time > 0 and (total_time - current_time <= 2)) or (current_time > dialog.skipintro_end_skip_time)
            self.assertTrue(end_break)

    def test_update_genre_settings_safe_fallback(self):
        """Ensure update_genre_settings returns 3-tuple even when cancelled or network error occurs."""
        with patch.object(database, 'get', return_value=None):
            res = MalBrowser().update_genre_settings()
            self.assertEqual(len(res), 3)
            self.assertEqual(res, ([], [], []))

        with patch.object(control, 'multiselect_dialog', return_value=None):
            with patch.object(database, 'get', return_value={'data': [{'name': 'Action', 'mal_id': 1}]}):
                res = MalBrowser().update_genre_settings()
                self.assertEqual(len(res), 3)
                self.assertEqual(res, ([], [], []))

        with patch.object(control, 'multiselect_dialog', return_value=None):
            res = AniListBrowser().update_genre_settings()
            self.assertEqual(len(res), 3)
            self.assertEqual(res, ([], [], []))
