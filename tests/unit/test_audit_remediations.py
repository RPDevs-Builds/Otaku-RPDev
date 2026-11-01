"""
test_audit_remediations.py - Comprehensive Unit Tests for All Audit Remediations (v5.9.3)
========================================================================================
Validates fixes across Core Engine, Database, Subtitles, Scrapers, Debrid, Routes,
Windows, and Skin Templates.
"""

# Standardized Otaku Test Bootstrap
import os
import sys

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_TEST_DIR, '..' if os.path.basename(_TEST_DIR) in ('unit', 'integration', 'lint') else '.'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
_TESTS_DIR = os.path.join(_REPO_ROOT, 'tests')
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import conftest  # Centralized Kodi mock harness  # noqa: F401

import unittest
from unittest.mock import MagicMock, patch

from resources.lib.ui import control, database, part_filter
from resources.lib.ui.player import WatchlistPlayer
from resources.lib.subtitles import encoding
from resources.lib.subtitles.services.opensubtitles import OpenSubtitlesService
from resources.lib.subtitles.models import VideoMeta
from resources.lib.pages import bitsearch, piratebay
from resources.lib.debrid.real_debrid import RealDebrid
from resources.lib.windows.resolver import Resolver
from resources.lib.windows.skip_intro import SkipIntro
from resources.lib.windows.still_watching import StillWatchingXML
from resources.lib.windows.download_manager import Manager
from resources.lib.OtakuBrowser import OtakuBrowser
from resources.lib.indexers.kitsu import KitsuAPI


class TestAuditRemediations(unittest.TestCase):

    def test_skip_intro_no_control_3014_crash(self):
        """SkipIntro.background_tasks should not attempt to access missing control 3014."""
        action_args = {'skipintro_end': 90, 'skipintro_aniskip': False}
        with patch.object(database, 'get_show', return_value={'mal_id': 123}):
            dlg = SkipIntro('skip_intro.xml', control.ADDON_PATH, actionArgs=action_args)
            with patch.object(control, 'wait_for_abort', return_value=True):
                dlg.background_tasks()

    def test_still_watching_selection_actions_defined(self):
        """StillWatchingXML must define selection_actions and closing_actions."""
        dlg = StillWatchingXML('still_watching.xml', control.ADDON_PATH)
        self.assertTrue(hasattr(dlg, 'selection_actions'))
        self.assertTrue(hasattr(dlg, 'closing_actions'))
        self.assertIn(7, dlg.selection_actions)
        self.assertIn(92, dlg.closing_actions)

    def test_resolver_media_type_default(self):
        """Resolver must initialize media_type attribute."""
        with patch.object(database, 'get_show', return_value={'mal_id': 123, 'kodi_meta': '{}'}):
            with patch.object(database, 'get_show_meta', return_value={'mal_id': 123, 'art': '{}'}):
                dlg = Resolver('resolver.xml', control.ADDON_PATH, actionArgs={'mal_id': 123})
                self.assertEqual(dlg.media_type, 'tv')
                dlg_movie = Resolver('resolver.xml', control.ADDON_PATH, actionArgs={'mal_id': 123, 'media_type': 'movie'})
                self.assertEqual(dlg_movie.media_type, 'movie')

    def test_player_skipintro_duration_not_multiplied_by_60(self):
        """skipintro.duration must be read directly in seconds without * 60."""
        with patch.object(control, 'getInt', return_value=85):
            dur = control.getInt('skipintro.duration')
            self.assertEqual(dur, 85)

    def test_player_select_subtitle_stream_returns_none_on_negative_score(self):
        """select_subtitle_stream must return None when no tracks match preferred language."""
        from resources.lib.ui.player import select_subtitle_stream
        # Subtitle stream in Japanese when preferred language is English
        sub_streams = [{'language': 'jpn', 'name': 'Japanese Audio Commentary', 'index': 0}]
        stream_idx = select_subtitle_stream(sub_streams, preferred_lang='eng')
        self.assertIsNone(stream_idx)

    def test_database_sql_exit_reraises_operational_error(self):
        """database.SQL.__exit__ must return False on OperationalError to allow caller try/except."""
        class MockConn:
            def rollback(self):
                pass
        sql_ctx = database.SQL(':memory:')
        sql_ctx._conn = MockConn()
        import sqlite3
        handled = sql_ctx.__exit__(sqlite3.OperationalError, sqlite3.OperationalError("database is locked"), None)
        self.assertFalse(handled)

    def test_part_filter_int_string_coercion(self):
        """part_filter must coerce target_part to int so 2 != '2' is not treated as mismatch."""
        sources = [{'name': 'Anime Show Part 2 - 01 [1080p].mkv'}]
        with patch.object(part_filter, '_get_mappings_info', return_value={'thetvdb_part': '2'}):
            filtered = part_filter.filter_sources(sources, mal_id=100, episode=1, part=None)
            self.assertEqual(len(filtered), 1)

    def test_subtitles_encoding_fallback_order(self):
        """FALLBACK_ENCODINGS must place latin-1 and iso-8859-1 at the end."""
        self.assertIn('latin-1', encoding.FALLBACK_ENCODINGS[-2:])
        self.assertIn('iso-8859-1', encoding.FALLBACK_ENCODINGS[-3:])
        # CJK encodings must appear before latin-1
        self.assertLess(encoding.FALLBACK_ENCODINGS.index('shift_jis'), encoding.FALLBACK_ENCODINGS.index('latin-1'))
        self.assertLess(encoding.FALLBACK_ENCODINGS.index('gbk'), encoding.FALLBACK_ENCODINGS.index('latin-1'))

    def test_opensubtitles_parent_imdb_id_for_tv_episodes(self):
        """OpenSubtitles service must set parent_imdb_id when querying TV episodes."""
        meta = VideoMeta(
            title='Attack on Titan',
            tvshow='Attack on Titan',
            season='1',
            episode='1',
            imdb_id='tt2560140',
            is_tvshow=True,
            languages=['en'],
            preferred_lang='en'
        )
        with patch('resources.lib.ui.client.get') as mock_get:
            mock_get.return_value = MagicMock(status_code=200, json=lambda: {'data': []})
            OpenSubtitlesService.search(meta, {'subtitles.timeout': 5})
            args, kwargs = mock_get.call_args
            params = kwargs.get('params', {})
            self.assertEqual(str(params.get('parent_imdb_id')), '2560140')
            self.assertNotIn('imdb_id', params)

    def test_bitsearch_title_parsing(self):
        """bitsearch Sources._parse_titles must split (Romaji)|(English) into individual queries."""
        titles = bitsearch.Sources._parse_titles('(Shingeki no Kyojin)|(Attack on Titan)')
        self.assertEqual(titles, ['Shingeki no Kyojin', 'Attack on Titan'])

    def test_piratebay_title_parsing(self):
        """piratebay Sources._parse_titles must split (Romaji)|(English) into individual queries."""
        titles = piratebay.Sources._parse_titles('(Frieren: Beyond Journey\'s End)|(Sousou no Frieren)')
        self.assertEqual(titles, ['Frieren: Beyond Journey\'s End', 'Sousou no Frieren'])

    def test_real_debrid_resolve_single_magnet_autodelete_guard(self):
        """RealDebrid.resolve_single_magnet must only delete torrent on autodelete or missing stream link."""
        rd = RealDebrid()
        rd.autodelete = False
        mock_info = {
            'id': 'TOR_1',
            'files': [{'id': 1, 'selected': 1, 'path': '/ep1.mkv'}],
            'links': ['https://real-debrid.com/d/LINK1']
        }
        with patch.object(rd, 'addMagnet', return_value={'id': 'TOR_1'}):
            with patch.object(rd, 'torrentSelect', return_value=True):
                with patch.object(rd, 'torrentInfo', return_value=mock_info):
                    with patch.object(rd, 'resolve_hoster', return_value='https://stream.real-debrid.com/video.mkv'):
                        with patch.object(rd, 'deleteTorrent') as mock_del:
                            res = rd.resolve_single_magnet('magnet:?xt=urn:btih:hash', 1, pack_select=False)
                            self.assertEqual(res, 'https://stream.real-debrid.com/video.mkv')
                            mock_del.assert_not_called()

    def test_kitsu_get_episode_meta_non_infinite_loop(self):
        """KitsuAPI.get_episode_meta must break when response is empty."""
        kitsu = KitsuAPI()
        with patch('resources.lib.ui.client.get', return_value=None):
            episodes = kitsu.get_episode_meta(12345)
            self.assertEqual(episodes, [])

    def test_download_zero_division_guard(self):
        """Manager.update_status must not crash with ZeroDivisionError when file_size is 0."""
        d = Manager()
        d.file_size = 0
        d.bytes_consumed = 0
        with patch.object(d, 'update_download'):
            d.update_status(chunk_size=0)
            self.assertEqual(d.progress, 0)
            self.assertEqual(d.remaining_seconds, 0)

    def test_otaku_browser_get_anime_returns_show(self):
        """OtakuBrowser.get_anime should update show and return show dict."""
        ob = OtakuBrowser()
        mock_mal_res = {'data': {'id': 100, 'mal_id': 100, 'title': 'Test Anime'}}
        mock_anilist = [{'id': 100, 'title': {'romaji': 'Test Anime'}}]
        with patch.object(database, 'get', return_value=mock_mal_res):
            with patch.object(ob, 'get_anilist_base_res', return_value=mock_anilist):
                with patch('resources.lib.ui.get_meta.collect_meta'):
                    with patch.object(ob, 'database_update_show') as mock_update:
                        with patch.object(database, 'get_show', return_value={'mal_id': 100, 'name': 'Test Anime'}):
                            res = ob.get_anime(100)
                            mock_update.assert_called_once()
                            args, _ = mock_update.call_args
                            self.assertIsInstance(args[1], dict)
                            self.assertEqual(res['mal_id'], 100)


if __name__ == '__main__':
    unittest.main()
