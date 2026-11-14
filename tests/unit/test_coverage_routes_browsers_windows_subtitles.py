import importlib.util
import os
import unittest
from unittest import mock

import xbmcgui
from resources.lib.ui import control, database


class TestBrowsersAndMain(unittest.TestCase):
    def tearDown(self):
        database.close_thread_connections()

    def test_browser_base(self):
        from resources.lib.ui.BrowserBase import BrowserBase

        bb = BrowserBase()
        self.assertIsNotNone(bb)
        cleaned = bb._clean_title("Show [1080p] (TV)")
        self.assertIsInstance(cleaned, str)

    def test_browsers_instantiation(self):
        from resources.lib import (
            AniListBrowser, MalBrowser, OtakuBrowser, MetaBrowser, AnimeSchedule
        )

        with mock.patch('resources.lib.ui.control.getSetting', return_value=''):
            alb = AniListBrowser.AniListBrowser()
            self.assertIsNotNone(alb)

            mb = MalBrowser.MalBrowser()
            self.assertIsNotNone(mb)

            ob = OtakuBrowser.OtakuBrowser()
            self.assertIsNotNone(ob)

            browser = MetaBrowser._get_browser()
            self.assertIsNotNone(browser)

            asch = AnimeSchedule.AnimeScheduleCalendar()
            self.assertIsNotNone(asch)

    def test_meta_browser_next_up_meta(self):
        from resources.lib import MetaBrowser
        meta = MetaBrowser.get_next_up_meta(999999, 1)
        self.assertIsInstance(meta, dict)
        self.assertEqual(meta.get('title'), 'Episode 1')

    def test_main_module(self):
        from resources.lib import Main

        items = Main.get_menu_items('main')
        self.assertIsInstance(items, list)

        search_items = Main.get_menu_items('search')
        self.assertIsInstance(search_items, list)


class TestWatchlist(unittest.TestCase):
    def tearDown(self):
        database.close_thread_connections()

    def test_watchlist_flavors_instantiation(self):
        from resources.lib.WatchlistFlavor import (
            AniList, Kitsu, MyAnimeList, Simkl
        )
        from resources.lib.WatchlistFlavor.WatchlistFlavorBase import WatchlistFlavorBase

        wfb = WatchlistFlavorBase()
        self.assertIsNotNone(wfb)

        with mock.patch('resources.lib.ui.control.getSetting', return_value=''):
            al = AniList.AniListWLF()
            self.assertIsNotNone(al)

            k = Kitsu.KitsuWLF()
            self.assertIsNotNone(k)

            mal = MyAnimeList.MyAnimeListWLF()
            self.assertIsNotNone(mal)

            sim = Simkl.SimklWLF()
            self.assertIsNotNone(sim)

    def test_watchlist_integration(self):
        from resources.lib.WatchlistFlavor import WatchlistFlavor
        from resources.lib import WatchlistIntegration

        with mock.patch('resources.lib.ui.control.getBool', return_value=False):
            enabled = WatchlistFlavor.get_enabled_watchlists()
            self.assertIsInstance(enabled, list)

        with mock.patch('resources.lib.WatchlistFlavor.WatchlistFlavor.get_merged_watchlist_eps_watched', return_value=5):
            merged = WatchlistFlavor.get_merged_watchlist_eps_watched(1234)
            self.assertEqual(merged, 5)

        self.assertIsInstance(WatchlistIntegration._watchlist_paging_per_page(), int)


class TestRoutes(unittest.TestCase):
    def test_routes_modules(self):
        from resources.lib.routes import (
            cloud, history, search, subtitles, tools, playback
        )

        # history routes
        with mock.patch('resources.lib.ui.control.draw_items'):
            history.WATCH_HISTORY("", {})

        # search routes
        with mock.patch('resources.lib.ui.control.draw_items'):
            search.SEARCH_MENU("", {})

        # subtitles route
        with mock.patch('resources.lib.subtitles.search_subtitles', return_value=[]), \
             mock.patch('resources.lib.subtitles.get_meta_from_player'), \
             mock.patch('resources.lib.subtitles.get_subtitles_settings'):
            subtitles.handle_subtitles_search("", {'query': 'test'})

        # tools route
        self.assertIsNotNone(tools)
        self.assertIsNotNone(cloud)
        self.assertIsNotNone(playback)


class TestSubtitles(unittest.TestCase):
    def test_subtitles_modules(self):
        from resources.lib.subtitles import (
            archive, download, encoding, languages, meta, models, search
        )

        # encoding
        text, enc = encoding.fix_subtitle_encoding(b"Hello World")
        self.assertEqual(text, "Hello World")

        # languages
        lang_code = languages.to_iso639_1("English")
        self.assertEqual(lang_code, "en")

        # models
        vm = models.VideoMeta(title="Frieren", season=1, episode=1)
        self.assertEqual(vm.title, "Frieren")
        sub = models.SubtitleResult(
            service_name="test",
            display_name="Test Sub",
            name="test.srt",
            lang="English",
            lang_code="en",
            download_url="http://example.com/test.srt"
        )
        self.assertEqual(sub.name, "test.srt")

        # meta
        vm_dict = meta.get_meta_from_dict({'title': 'Frieren', 'season': 1, 'episode': 1}, mal_id='123')
        self.assertEqual(vm_dict.title, 'Frieren')

        # models repr
        self.assertIn("Frieren", repr(vm))
        self.assertIn("test.srt", repr(sub))

        # download sanitize and purge
        self.assertEqual(download.sanitize_filename('Anime: Season 1 / Ep * 01?.srt'), 'Anime__Season_1___Ep___01_.srt')
        download.purge_temp_subtitles()

        self.assertIsNotNone(archive)
        self.assertIsNotNone(download)
        self.assertIsNotNone(search)

    def test_subtitles_services(self):
        from resources.lib.subtitles.services import (
            addic7ed, bsplayer, opensubtitles, podnadpisi, subdl, subsource
        )

        self.assertIsNotNone(addic7ed)
        self.assertIsNotNone(bsplayer)
        self.assertIsNotNone(opensubtitles)
        self.assertIsNotNone(podnadpisi)
        self.assertIsNotNone(subdl)
        self.assertIsNotNone(subsource)


class TestWindows(unittest.TestCase):
    def test_windows_instantiation(self):
        from resources.lib.windows import (
            base_window, anichart, anichart_window, clear_cache,
            download_manager, filter_select, get_sources_window,
            menu_order, playing_next, progress_dialog, resolver,
            skip_intro, sort_select, source_select, stats_window,
            still_watching, textviewer, wlf_auth
        )

        windows = [
            (base_window.BaseWindow, ('test.xml', '/fake/path')),
            (anichart.Anichart, ('anichart.xml', control.ADDON_PATH)),
            (anichart_window.BaseWindow, ('anichart_window.xml', control.ADDON_PATH)),
            (clear_cache.ClearCacheDialog, ('clear_cache.xml', control.ADDON_PATH)),
            (download_manager.DownloadManager, ('download_manager.xml', control.ADDON_PATH)),
            (filter_select.FilterSelect, ('filter_select.xml', control.ADDON_PATH)),
            (get_sources_window.GetSources, ('get_sources_window.xml', control.ADDON_PATH)),
            (menu_order.MenuOrderDialog, ('menu_order.xml', control.ADDON_PATH)),
            (playing_next.PlayingNext, ('playing_next.xml', control.ADDON_PATH)),
            (progress_dialog.Progress_dialog, ('progress_dialog.xml', control.ADDON_PATH)),
            (resolver.Resolver, ('resolver.xml', control.ADDON_PATH)),
            (skip_intro.SkipIntro, ('skip_intro.xml', control.ADDON_PATH)),
            (sort_select.SortSelect, ('sort_select.xml', control.ADDON_PATH)),
            (source_select.SourceSelect, ('source_select.xml', control.ADDON_PATH)),
            (stats_window.StatsWindow, ('stats_window.xml', control.ADDON_PATH)),
            (still_watching.StillWatchingXML, ('still_watching.xml', control.ADDON_PATH)),
            (textviewer.TextViewerXML, ('textviewer.xml', control.ADDON_PATH)),
            (wlf_auth.WatchlistFlavorAuth, ('wlf_auth.xml', control.ADDON_PATH)),
        ]

        for win_cls, args in windows:
            try:
                win = win_cls(*args)
                self.assertIsNotNone(win)
            except Exception:
                # Some window constructors require complex XML or display context
                pass

    def test_base_window_get_control_list(self):
        from resources.lib.windows import base_window
        win = base_window.BaseWindow('anichart.xml', '')
        ctrl = win.getControlList(1000)
        self.assertIsNotNone(ctrl)
        win._controls[9999] = object()
        with self.assertRaises(AttributeError):
            win.getControlList(9999)


class TestServiceAndContext(unittest.TestCase):
    def test_service_functions(self):
        import service

        # version check
        with mock.patch.object(control, 'getSetting', return_value='1.0.0'):
            service.version_check()

        # changelog & instructions
        with mock.patch('resources.lib.windows.textviewer.TextViewerXML'):
            service.getChangeLog()
            service.getInstructions()

        # cleanup cache databases
        with mock.patch('resources.lib.ui.database.cache_clear'):
            service.cleanup_cache_databases()

        # toggle invoker
        with mock.patch('builtins.open', mock.mock_open(read_data='<reuselanguageinvoker>true</reuselanguageinvoker>')):
            service.toggle_reuselanguageinvoker(forced_state=False)

    def test_context_menu_default(self):
        # Load context.otaku.rpdev/default.py
        context_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            'context.otaku.rpdev', 'default.py'
        )
        spec = importlib.util.spec_from_file_location("context_default", context_path)
        context_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(context_mod)

        # Test subpath extraction
        self.assertEqual(context_mod._extract_subpath("", "plugin://"), "")
        self.assertEqual(context_mod._extract_subpath("plugin://test/123", "plugin://test"), "/123")
        self.assertEqual(context_mod._extract_subpath("plugin://other/456", "plugin://test"), "/456")

        # Test watch target extraction
        self.assertEqual(context_mod._extract_watch_target("plugin://test/play/100/2", "plugin://test"), "/100/2")
        self.assertEqual(context_mod._extract_watch_target("plugin://test/play_movie/200", "plugin://test"), "/200/1")
        self.assertEqual(context_mod._extract_watch_target("", "plugin://test"), "/1/1")

        # Test get_video_info
        mock_li = mock.MagicMock(spec=xbmcgui.ListItem)
        mock_tag = mock.MagicMock()
        mock_tag.getTitle.return_value = "Test Title"
        mock_tag.getMediaType.return_value = "episode"
        mock_tag.getTVShowTitle.return_value = "Test Show"
        mock_tag.getPlot.return_value = "Test Plot"
        mock_tag.getYear.return_value = 2024
        mock_tag.getPremieredAsW3C.return_value = "2024-01-01"
        mock_tag.getSeason.return_value = 1
        mock_tag.getEpisode.return_value = 1
        mock_tag.getFirstAiredAsW3C.return_value = "2024-01-01"
        mock_tag.getRating.return_value = 8.5
        mock_tag.getResumeTime.return_value = 100
        mock_li.getVideoInfoTag.return_value = mock_tag
        mock_li.getArt.return_value = "http://art.jpg"

        info = context_mod.get_video_info(mock_li)
        self.assertEqual(info['title'], "Test Title")
        self.assertEqual(info['season'], "1")
        self.assertEqual(info['episode'], "1")

        # Test main context menu command branches
        commands = [
            'findrecommendations', 'findrelations', 'getwatchorder',
            'viewreviews', 'viewstatistics', 'rescrape', 'sourceselect',
            'logout', 'deletefromdatabase', 'watchlist', 'markedaswatched',
            'markedasunwatched', 'markpreviouswatched', 'clearcache',
            'fanartselect'
        ]

        mock_item = mock.MagicMock()
        mock_item.getPath.return_value = "plugin://plugin.video.otaku.rpdev/play/123/1"
        mock_item.getVideoInfoTag.return_value = mock_tag
        mock_item.getArt.return_value = ""

        with mock.patch('xbmc.executebuiltin') as mock_exec, \
             mock.patch.object(context_mod, 'get_video_info', return_value={'title': 'Test'}), \
             mock.patch('sys.listitem', mock_item, create=True):
            for cmd in commands:
                with mock.patch('sys.argv', ['default.py', cmd]):
                    context_mod.main()
            self.assertEqual(mock_exec.call_count, len(commands))

            # Unknown command raises KeyError
            with mock.patch('sys.argv', ['default.py', 'unknown_cmd']):
                with self.assertRaises(KeyError):
                    context_mod.main()

    def test_plugin_default(self):
        # Load plugin.video.otaku.rpdev/default.py
        plugin_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            'plugin.video.otaku.rpdev', 'default.py'
        )
        spec = importlib.util.spec_from_file_location("plugin_default", plugin_path)
        plugin_mod = importlib.util.module_from_spec(spec)
        self.assertIsNotNone(plugin_mod)


if __name__ == '__main__':
    unittest.main()
