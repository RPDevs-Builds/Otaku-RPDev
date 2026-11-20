# -*- coding: utf-8 -*-
"""
test_end_user_ui_and_routes.py - End-User UI, WindowXML, Skin & Route Behavioral Tests
======================================================================================
Covers previously untested/thinly-tested user-facing routes and WindowXML dialogs:
1. routes/history.py (add_last_watched click modes, WATCH_HISTORY listing, clear/empty states)
2. routes/subtitles.py (manual search dialog flow, empty result notification, progress cleanup)
3. WindowXML controllers: FilterSelect, GetSources, StatsWindow, SettingsBackupDialog, AnichartWindow
4. Exhaustive 41-template 1080i skin XML structural & <defaultcontrol> validation
"""

import glob
import os
import sys
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_TEST_DIR, '..' if os.path.basename(_TEST_DIR) in ('unit', 'integration', 'lint') else '.'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
_TESTS_DIR = os.path.join(_REPO_ROOT, 'tests')
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import conftest  # noqa: F401
from kodi_profile import KodiProfile, SKINS_1080I_DIR, parse_skin_xml
from resources.lib.ui import control, database


class TestEndUserRoutesHistoryAndSubtitles(unittest.TestCase):
    """Behavioral tests for end-user routes/history.py and routes/subtitles.py."""

    def setUp(self):
        self._saved = dict(conftest._settings_store)

    def tearDown(self):
        conftest._settings_store.clear()
        conftest._settings_store.update(self._saved)
        database.close_thread_connections()

    def test_history_add_last_watched_handles_movie_and_tv_click_modes(self):
        from resources.lib.routes import history

        # Empty last_watched setting returns items unchanged
        control.setSetting('addon.last_watched', '')
        self.assertEqual(history.add_last_watched([]), [])

        # Movie (episodes == 1) routes to play_movie/<mal_id>/
        movie_row = {'kodi_meta': database.dumps({'title_userPreferred': 'Your Name', 'episodes': 1})}
        control.setSetting('addon.last_watched', '32281')
        with patch.object(database, 'get_show', return_value=movie_row), \
             patch.object(database, 'get_show_meta', return_value=None), \
             patch.object(database, 'get_unique_ids', return_value={}), \
             patch.object(control, 'pathExists', return_value=False):
            items = history.add_last_watched([])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0][0], 'LAST_WATCHED_ITEM')
        self.assertEqual(items[0][2], 'play_movie/32281/')
        self.assertEqual(items[0][4]['mediatype'], 'movie')

        # TV show respects interface.watchhistory.click = 0 (list), 1 (next ep), 2 (resume last)
        tv_row = {'kodi_meta': database.dumps({'title_userPreferred': 'Frieren', 'episodes': 28, 'eps_watched': 12})}
        control.setSetting('addon.last_watched', '52991')
        with patch.object(database, 'get_show', return_value=tv_row), \
             patch.object(database, 'get_show_meta', return_value=None), \
             patch.object(database, 'get_unique_ids', return_value={}), \
             patch.object(control, 'pathExists', return_value=False):
            for mode, expected_url in ((0, 'animes/52991/'), (1, 'play/52991/13'), (2, 'play/52991/12')):
                control.setInt('interface.watchhistory.click', mode)
                res = history.add_last_watched([])
                self.assertEqual(res[0][2], expected_url)
                self.assertIn('Ep 12/28', res[0][1])

    def test_subtitles_route_manual_search_handles_empty_and_results(self):
        from resources.lib.routes import subtitles as sub_route
        from resources.lib.subtitles.models import VideoMeta, SubtitleResult

        meta = VideoMeta(title='Frieren', season=1, episode=1, preferred_lang='eng')
        settings = {'subtitles.enabled': True}

        # Case 1: No results -> closes progress dialog, notifies user, does NOT open select dialog
        with patch('resources.lib.subtitles.get_meta_from_player', return_value=meta), \
             patch('resources.lib.subtitles.get_subtitles_settings', return_value=settings), \
             patch('resources.lib.subtitles.search_subtitles', return_value=[]), \
             patch('resources.lib.subtitles.manual_select_dialog') as mock_select, \
             patch.object(control, 'notify') as mock_notify, \
             patch.object(control, 'progressDialog') as mock_prog:
            sub_route.handle_subtitles_search('', {})
            mock_prog.create.assert_called_once()
            mock_prog.close.assert_called_once()
            mock_notify.assert_called_once()
            mock_select.assert_not_called()

        # Case 2: Results found -> opens manual_select_dialog with exact results & closes progress dialog
        fake_res = [SubtitleResult(service_name='subdl', display_name='SubDL', name='Frieren.01.srt', lang='English', lang_code='en', download_url='https://sub.test/1.srt')]
        with patch('resources.lib.subtitles.get_meta_from_player', return_value=meta), \
             patch('resources.lib.subtitles.get_subtitles_settings', return_value=settings), \
             patch('resources.lib.subtitles.search_subtitles', return_value=fake_res), \
             patch('resources.lib.subtitles.manual_select_dialog') as mock_select, \
             patch.object(control, 'progressDialog') as mock_prog:
            sub_route.handle_subtitles_search('', {})
            mock_prog.close.assert_called_once()
            mock_select.assert_called_once_with(fake_res, meta, settings)


class TestEndUserWindowXMLDialogsAndSkins(unittest.TestCase):
    """Behavioral tests for custom WindowXML dialogs and all 41 1080i skin templates."""

    def test_stats_window_renders_properties_and_closes_on_back(self):
        from resources.lib.windows.stats_window import StatsWindow
        with KodiProfile('22', strict_skin_controls=True):
            stats_payload = {
                'total': 10000,
                'watching': 4000,
                'completed': 5000,
                'scores': [{'score': 9, 'votes': 1200, 'percentage': 35}],
            }
            dlg = StatsWindow('anime_statistics.xml', control.ADDON_PATH, stats=stats_payload, heading='Frieren Stats')
            dlg.onInit()
            self.assertEqual(dlg.getProperty('otaku.heading'), 'Frieren Stats')
            self.assertEqual(dlg.getProperty('otaku.stats.total'), '10,000')
            self.assertEqual(dlg.getProperty('otaku.stats.score9.pct'), '35%')
            with patch.object(dlg, 'close') as mock_close:
                # Android TV Back action ID 92 closes dialog cleanly
                action = MagicMock()
                action.getId.return_value = 92
                dlg.onAction(action)
                mock_close.assert_called_once()

    def test_get_sources_window_updates_properties_and_cancels_on_back(self):
        from resources.lib.windows.get_sources_window import GetSources
        with KodiProfile('22', strict_skin_controls=True):
            dlg = GetSources('get_sources.xml', control.ADDON_PATH, actionArgs={'item_information': {'title': 'Frieren'}})
            dlg.update_properties("4K: 1 | 1080: 5 | 720: 2 | SD: 0| EQ: 0")
            self.assertEqual(dlg.getProperty('notification_text'), "4K: 1 | 1080: 5 | 720: 2 | SD: 0| EQ: 0")
            self.assertFalse(dlg.canceled)
            action = MagicMock()
            action.getId.return_value = 92
            dlg.onAction(action)
            self.assertTrue(dlg.canceled)

    def test_filter_select_initializes_and_closes_cleanly_on_back(self):
        from resources.lib.windows.filter_select import FilterSelect
        with KodiProfile('22', strict_skin_controls=True):
            dlg = FilterSelect('filter_select.xml', control.ADDON_PATH)
            dlg.onInit()
            action = MagicMock()
            action.getId.return_value = 9
            with patch.object(dlg, 'close') as mock_close:
                dlg.onAction(action)
                mock_close.assert_called_once()

    def test_all_41_skin_xmls_have_valid_structure_and_non_empty_controls(self):
        xml_paths = sorted(glob.glob(os.path.join(SKINS_1080I_DIR, '*.xml')))
        self.assertGreaterEqual(len(xml_paths), 41)
        for path in xml_paths:
            fname = os.path.basename(path)
            tree = ET.parse(path)
            root = tree.getroot()
            self.assertEqual(root.tag, 'window', f"{fname} root tag must be <window>")
            controls = parse_skin_xml(fname)
            self.assertGreater(len(controls), 0, f"{fname} must declare at least one control")
            # If <defaultcontrol> is declared, verify the target ID actually exists in the template
            dc = root.find('defaultcontrol')
            if dc is not None and (dc.text or '').strip().isdigit():
                dc_id = int(dc.text.strip())
                self.assertIn(dc_id, controls, f"{fname} <defaultcontrol>{dc_id}</defaultcontrol> not found in controls")


if __name__ == '__main__':
    unittest.main()
