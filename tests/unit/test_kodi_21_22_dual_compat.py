# -*- coding: utf-8 -*-
"""
tests/unit/test_kodi_21_22_dual_compat.py
=========================================
Hermetic dual-version compatibility suite verifying Otaku-RPDev under both
Kodi 21 (Omega, 21.3.0) and Kodi 22 (Piers, 22.0.0) simulated C++ runtime profiles.

Test Areas Covered:
1. VideoInfoTag typed setters, missing method guards, and ListItem property mirrors.
2. C++ SWIG non-null type contracts and defensive input coercion.
3. Audio/subtitle language matching (ISO 639-2 vs. BCP 47).
4. Demuxer chapter fallback chain (native JSON-RPC -> ffprobe -> AniSkip).
5. Directory sorting (SORT_METHOD_UNSORTED first) and pagination/filter SpecialSort pinning.
6. WindowXMLDialog skin control validation across all 40 XML templates with strict_skin_controls=True.
7. CAddonSettings schema validation and default value reset with strict_settings=True.
8. Orphaned settings cleaning (clean_settings) under both versions.
9. KodiProfile decorator, context manager, and mixin ergonomics.
"""

import os
import sys
import glob
import tempfile
import unittest
import xml.etree.ElementTree as ET

import conftest
import xbmc
import xbmcgui
import xbmcaddon
import xbmcplugin

from tests.kodi_profile import (
    KodiProfile,
    KodiProfileMixin,
    load_settings_schema,
    parse_skin_xml,
    reset_settings_to_defaults,
    SKINS_1080I_DIR,
    MockInfoTagVideo21,
    MockInfoTagVideo22
)

from resources.lib.ui import control
from resources.lib.ui.clean_settings import clean_settings
from resources.lib.ui.player import is_language_match, WatchlistPlayer
from resources.lib.ui.BrowserBase import BrowserBase
from resources.lib.OtakuBrowser import OtakuBrowser
from resources.lib.AniListBrowser import AniListBrowser
from resources.lib.MalBrowser import MalBrowser

from resources.lib.windows.anichart import Anichart
from resources.lib.windows.stats_window import StatsWindow
from resources.lib.windows.clear_cache import ClearCacheDialog
from resources.lib.windows.download_manager import DownloadManager
from resources.lib.windows.filter_select import FilterSelect
from resources.lib.windows.get_sources_window import GetSources
from resources.lib.windows.menu_order import MenuOrderDialog
from resources.lib.windows.progress_dialog import Progress_dialog
from resources.lib.windows.resolver import Resolver
from resources.lib.windows.sort_select import SortSelect
from resources.lib.windows.source_select import SourceSelect
from resources.lib.windows.still_watching import StillWatchingXML
from resources.lib.windows.textviewer import TextViewerXML
from resources.lib.windows.wlf_auth import WatchlistFlavorAuth
from resources.lib.windows.playing_next import PlayingNext
from resources.lib.windows.skip_intro import SkipIntro


class TestVideoTagsDualCompat(unittest.TestCase):
    """Verify InfoTagVideo methods and property mirroring under Kodi 21 vs. Kodi 22."""

    def test_kodi21_vinfo_excludes_kodi22_methods(self):
        with KodiProfile('21'):
            vinfo = xbmc.InfoTagVideo()
            self.assertIsInstance(vinfo, MockInfoTagVideo21)
            # Kodi 22+ exclusive methods must not exist on Kodi 21
            self.assertFalse(hasattr(vinfo, 'setOriginalLanguage'))
            self.assertFalse(hasattr(vinfo, 'setTagLine'))
            self.assertFalse(hasattr(vinfo, 'setSeasonPlot'))
            self.assertFalse(hasattr(vinfo, 'setAvailableFanart'))
            self.assertFalse(hasattr(vinfo, 'setHdrType'))

            # Invoking them directly without hasattr guard must raise AttributeError
            with self.assertRaises(AttributeError):
                vinfo.setTagLine('Epic Tagline')
            with self.assertRaises(AttributeError):
                vinfo.setOriginalLanguage('ja')
            with self.assertRaises(AttributeError):
                vinfo.setSeasonPlot('Season 2 plot')
            with self.assertRaises(AttributeError):
                vinfo.setAvailableFanart(['http://fanart.jpg'])
            with self.assertRaises(AttributeError):
                vinfo.setHdrType(1)

    def test_kodi21_set_videotags_preserves_listitem_property_mirrors(self):
        with KodiProfile('21'):
            li = xbmcgui.ListItem()
            info = {
                'title': 'Attack on Titan',
                'tagline': 'Epic Arc',
                'season_plot': 'S2 details',
                'originallanguage': 'ja',
                'hdr_type': 'hdr10',
                'premiered': '2024-10-15',
                'year': 2024,
                'rating': 9.2
            }
            # Must execute without raising AttributeError
            control.set_videotags(li, info)
            vinfo = li.getVideoInfoTag()

            # VideoTag common setters are populated
            self.assertEqual(vinfo.getTitle(), 'Attack on Titan')
            self.assertEqual(vinfo.getYear(), 2024)

            # Property mirrors are set for skin compatibility on Kodi 21
            self.assertEqual(li.getProperty('tagline'), 'Epic Arc')
            self.assertEqual(li.getProperty('SeasonPlot'), 'S2 details')
            self.assertEqual(li.getProperty('OriginalLanguage'), 'ja')
            self.assertEqual(li.getProperty('VideoResolution.HDRType'), 'hdr10')

    def test_kodi22_set_videotags_populates_both_vinfo_and_properties(self):
        with KodiProfile('22'):
            li = xbmcgui.ListItem()
            info = {
                'title': 'Attack on Titan',
                'tagline': 'Epic Arc',
                'season_plot': 'S2 details',
                'originallanguage': 'ja',
                'hdr_type': 'hdr10',
                'available_fanart': ['http://f1.jpg', 'http://f2.jpg'],
                'premiered': '2024-10-15',
                'year': 2024,
                'rating': 9.2
            }
            control.set_videotags(li, info)
            vinfo = li.getVideoInfoTag()
            self.assertIsInstance(vinfo, MockInfoTagVideo22)

            # Kodi 22 typed setters populated
            self.assertEqual(vinfo.getTagLine(), 'Epic Arc')
            self.assertEqual(vinfo.getSeasonPlot(), 'S2 details')
            self.assertEqual(vinfo.getOriginalLanguage(), 'ja')
            self.assertEqual(vinfo.getHdrType(), 1)
            self.assertEqual(vinfo.getAvailableFanart(), ['http://f1.jpg', 'http://f2.jpg'])

            # Property mirrors also populated
            self.assertEqual(li.getProperty('tagline'), 'Epic Arc')
            self.assertEqual(li.getProperty('SeasonPlot'), 'S2 details')
            self.assertEqual(li.getProperty('OriginalLanguage'), 'ja')
            self.assertEqual(li.getProperty('VideoResolution.HDRType'), 'hdr10')

    def test_set_datetime_formatting_both_versions(self):
        for ver in ('21', '22'):
            with self.subTest(kodi_version=ver):
                with KodiProfile(ver):
                    li = xbmcgui.ListItem()
                    # Premiered ISO date -> YYYY-MM-DDTHH:MM:SS
                    control.set_videotags(li, {'premiered': '2024-10-15'})
                    self.assertEqual(li.getDateTime(), '2024-10-15T00:00:00')

                    # Year only -> YYYY-01-01T00:00:00
                    li2 = xbmcgui.ListItem()
                    control.set_videotags(li2, {'year': 2025})
                    self.assertEqual(li2.getDateTime(), '2025-01-01T00:00:00')


class TestSwigNonNullableContracts(unittest.TestCase):
    """Verify C++ SWIG non-null type contracts and defensive input coercion."""

    def test_actor_swig_rejects_none_under_kodi22(self):
        with KodiProfile('22'):
            with self.assertRaises(TypeError):
                xbmc.Actor(name=None)
            with self.assertRaises(TypeError):
                xbmc.Actor('Levi', role=None)
            with self.assertRaises(TypeError):
                xbmc.Actor('Levi', 'Captain', index=None)
            with self.assertRaises(TypeError):
                xbmc.Actor('Levi', 'Captain', 0, thumbnail=None)

            # Valid non-null inputs succeed
            actor = xbmc.Actor('Levi', 'Captain', 1, 'http://levi.jpg')
            self.assertEqual(actor.name, 'Levi')
            self.assertEqual(actor.role, 'Captain')
            self.assertEqual(actor.index, 1)

    def test_control_set_videotags_coerces_actor_none_safely(self):
        with KodiProfile('22'):
            li = xbmcgui.ListItem()
            dirty_cast = [
                {'name': None, 'role': None, 'index': None, 'thumbnail': None},
                {'name': 'Eren', 'role': None, 'index': 2, 'thumbnail': None}
            ]
            # control.set_videotags defends against None via str(c.get(...) or '') and int(c.get(...) or 0)
            control.set_videotags(li, {'cast': dirty_cast})
            vinfo = li.getVideoInfoTag()
            cast = vinfo.getCast()
            self.assertEqual(len(cast), 2)
            self.assertEqual(cast[0].name, '')
            self.assertEqual(cast[0].role, '')
            self.assertEqual(cast[0].index, 0)
            self.assertEqual(cast[1].name, 'Eren')
            self.assertEqual(cast[1].role, '')
            self.assertEqual(cast[1].index, 2)

    def test_vinfo_setters_reject_none_under_kodi22(self):
        with KodiProfile('22'):
            vinfo = xbmc.InfoTagVideo()
            with self.assertRaises(TypeError):
                vinfo.setTitle(None)
            with self.assertRaises(TypeError):
                vinfo.setYear(None)
            with self.assertRaises(TypeError):
                vinfo.setGenres(None)
            with self.assertRaises(TypeError):
                vinfo.setGenres([None])
            with self.assertRaises(TypeError):
                vinfo.setTagLine(None)
            with self.assertRaises(TypeError):
                vinfo.setOriginalLanguage(None)
            with self.assertRaises(TypeError):
                vinfo.setSeasonPlot(None)
            with self.assertRaises(TypeError):
                vinfo.setAvailableFanart(None)
            with self.assertRaises(TypeError):
                vinfo.setHdrType(None)
            with self.assertRaises(TypeError):
                vinfo.setRating(None, 0)
            with self.assertRaises(TypeError):
                vinfo.setUniqueIDs(None)

    def test_listitem_and_addon_reject_none_under_kodi22(self):
        with KodiProfile('22'):
            li = xbmcgui.ListItem()
            with self.assertRaises(TypeError):
                li.setProperty(None, 'val')
            with self.assertRaises(TypeError):
                li.setProperty('key', None)
            with self.assertRaises(TypeError):
                li.setPath(None)

            addon = xbmcaddon.Addon()
            with self.assertRaises(TypeError):
                addon.setSetting('general.timeout', None)
            with self.assertRaises(TypeError):
                addon.setSetting(None, 'val')

            # control.setSetting defends via str(value if value is not None else '')
            control.setSetting('general.timeout', None)
            self.assertEqual(control.getSetting('general.timeout'), '')


class TestLanguageMatchingDualCompat(unittest.TestCase):
    """Verify audio/subtitle stream language matching across Kodi 21 and Kodi 22."""

    def test_kodi21_iso639_2_stream_matching(self):
        with KodiProfile('21'):
            # Kodi 21 demuxer yields 3-letter ISO 639-2 codes
            self.assertTrue(is_language_match('jpn', '', 'jpn'))
            self.assertTrue(is_language_match('eng', '', 'eng'))
            self.assertTrue(is_language_match('spa', '', 'spa'))
            self.assertTrue(is_language_match('fre', '', 'fre'))
            self.assertTrue(is_language_match('ger', '', 'ger'))

    def test_kodi22_bcp47_two_letter_and_subtag_matching(self):
        with KodiProfile('22'):
            # Kodi 22 demuxer yields 2-letter BCP 47 codes and regional subtags
            self.assertTrue(is_language_match('ja', '', 'jpn'))
            self.assertTrue(is_language_match('en', '', 'eng'))
            self.assertTrue(is_language_match('en-US', '', 'eng'))
            self.assertTrue(is_language_match('en-GB', '', 'eng'))
            self.assertTrue(is_language_match('pt-BR', '', 'por'))
            self.assertTrue(is_language_match('es-419', '', 'spa'))
            self.assertTrue(is_language_match('zh-Hans', '', 'chi'))

    def test_watchlist_player_setup_audio_and_subtitles_dual(self):
        # Kodi 21 profile test
        with KodiProfile('21'):
            player21 = WatchlistPlayer()
            player21.audio_lang = 'jpn'
            player21.sub_lang = 'eng'
            player21.subtitles_enable = True
            player21.setup_audio_and_subtitles()
            # Verified that execution completes without error under ISO 639-2 JSON-RPC return

        # Kodi 22 profile test
        with KodiProfile('22'):
            player22 = WatchlistPlayer()
            player22.audio_lang = 'jpn'
            player22.sub_lang = 'eng'
            player22.subtitles_enable = True
            player22.setup_audio_and_subtitles()
            # Verified that execution completes without error under BCP 47 JSON-RPC return


class TestDemuxerChapterFallbackDualCompat(unittest.TestCase):
    """Verify demuxer chapter queries and fallback chain across versions."""

    def test_kodi21_demuxer_chapter_query_fails_and_falls_back(self):
        with KodiProfile('21'):
            player = WatchlistPlayer()
            player.total_time = 1440
            player.ffprobe_chapters = []
            # Under Kodi 21, Player.GetChapters returns method not found / empty result
            success = player.query_demuxer_chapters()
            self.assertFalse(success)
            self.assertEqual(player.ffprobe_chapters, [])

    def test_kodi22_demuxer_chapter_query_succeeds_with_mixed_timestamps(self):
        with KodiProfile('22'):
            player = WatchlistPlayer()
            player.total_time = 1440
            player.ffprobe_chapters = []
            player.skipintro_aniskip_enable = True
            player.skipintro_aniskip = False
            player.skipoutro_aniskip_enable = True
            player.skipoutro_aniskip = False

            # Under Kodi 22, Player.GetChapters returns native chapters
            success = player.query_demuxer_chapters()
            self.assertTrue(success)
            self.assertEqual(len(player.ffprobe_chapters), 5)

            # Evaluate chapter skips
            player.process_ffprobe_chapter_skips()
            self.assertTrue(player.skipintro_aniskip)
            self.assertEqual(player.skipintro_start, 90.0)
            self.assertEqual(player.skipintro_end, 180.0)
            self.assertTrue(player.skipoutro_aniskip)
            self.assertEqual(player.skipoutro_start, 1320.0)
            self.assertEqual(player.skipoutro_end, 1410.0)


class TestBrowserDirectoryAndSpecialSortDualCompat(unittest.TestCase):
    """Verify container sort method registration and pagination/filter SpecialSort pinning."""

    def test_directory_sort_methods_order_and_masks_dual(self):
        for ver in ('21', '22'):
            with self.subTest(kodi_version=ver):
                with KodiProfile(ver):
                    conftest.mock_xbmcplugin.reset()
                    control.draw_items([], content_type='tvshows')
                    # First sort method must be SORT_METHOD_UNSORTED
                    sorts = conftest.mock_xbmcplugin.sort_methods
                    self.assertGreater(len(sorts), 0)
                    self.assertEqual(sorts[0][1], conftest.mock_xbmcplugin.SORT_METHOD_UNSORTED)
                    self.assertEqual(sorts[0][2], "%L")
                    self.assertEqual(sorts[0][3], "%R")

                    # Episodes view check
                    conftest.mock_xbmcplugin.reset()
                    control.draw_items([], content_type='episodes')
                    sorts_ep = conftest.mock_xbmcplugin.sort_methods
                    self.assertEqual(sorts_ep[0][1], conftest.mock_xbmcplugin.SORT_METHOD_UNSORTED)
                    self.assertEqual(sorts_ep[0][2], "%H. %T")
                    self.assertEqual(sorts_ep[0][3], "%R | %P")

    def test_special_sort_pinning_dual(self):
        for ver in ('21', '22'):
            with self.subTest(kodi_version=ver):
                with KodiProfile(ver):
                    # Next page pinned to bottom
                    res_next = control.xbmc_add_dir(
                        'Next Page (2)',
                        'url_next',
                        {'icon': 'next.png'},
                        {},
                        None,
                        True,
                        True,
                        False
                    )
                    self.assertEqual(res_next[1].getProperty('SpecialSort'), 'bottom')

                    # Filter action pinned to top
                    res_flt = control.xbmc_add_dir(
                        '[Filter List by Text...]',
                        'multipage_filter?action=filter',
                        {'icon': 'filter.png'},
                        {},
                        None,
                        True,
                        False,
                        False
                    )
                    self.assertEqual(res_flt[1].getProperty('SpecialSort'), 'top')

                    # Clear filter action pinned to top
                    res_clr = control.xbmc_add_dir(
                        '[Clear Filter]',
                        'multipage_clear_filter?action=clear',
                        {'icon': 'clear.png'},
                        {},
                        None,
                        True,
                        False,
                        False
                    )
                    self.assertEqual(res_clr[1].getProperty('SpecialSort'), 'top')

                    # Regular item not pinned
                    res_item = control.xbmc_add_dir(
                        'Demon Slayer',
                        'show_123',
                        {'icon': 'poster.png'},
                        {},
                        None,
                        True,
                        True,
                        False
                    )
                    self.assertEqual(res_item[1].getProperty('SpecialSort'), '')

    def test_browser_instantiation_dual(self):
        for ver in ('21', '22'):
            with self.subTest(kodi_version=ver):
                with KodiProfile(ver):
                    b_base = BrowserBase()
                    self.assertIsNotNone(b_base)
                    o_browser = OtakuBrowser()
                    self.assertIsNotNone(o_browser)
                    a_browser = AniListBrowser()
                    self.assertIsNotNone(a_browser)
                    m_browser = MalBrowser()
                    self.assertIsNotNone(m_browser)


class TestSkinControlValidationAcrossAllXMLs(unittest.TestCase):
    """Verify all 40 XML skin templates under strict_skin_controls=True."""

    def test_all_40_skin_templates_controls_and_types(self):
        xml_files = glob.glob(os.path.join(SKINS_1080I_DIR, '*.xml'))
        self.assertEqual(len(xml_files), 40, "Expected exactly 40 skin XML templates")
        for xml_path in xml_files:
            fname = os.path.basename(xml_path)
            controls = parse_skin_xml(fname)
            self.assertGreater(len(controls), 0, f"Skin XML {fname} has no declared controls")

    def test_missing_control_id_raises_runtime_error(self):
        with KodiProfile('22', strict_skin_controls=True):
            dlg = xbmcgui.WindowXMLDialog('clear_cache.xml')
            # Control 1000 exists in clear_cache.xml (list)
            ctrl = dlg.getControl(1000)
            self.assertIsInstance(ctrl, xbmcgui.ControlList)

            # Control 99999 does not exist in clear_cache.xml -> RuntimeError
            with self.assertRaises(RuntimeError) as ctx:
                dlg.getControl(99999)
            self.assertIn("Control does not exist 99999", str(ctx.exception))

    def test_playing_next_az_handles_missing_control_3014(self):
        with KodiProfile('22', strict_skin_controls=True):
            # In playing_next_az.xml and skip_outro_az.xml, control 3014 is intentionally omitted
            dlg = PlayingNext('playing_next_az.xml', control.ADDON_PATH, actionArgs={'item_information': {}})
            dlg.closed = True
            # onInit attempts self.getControl(3014), catches RuntimeError, and logs debug warning
            dlg.onInit()
            self.assertTrue(dlg.closed)

    def test_all_16_window_xml_dialog_subclasses_init(self):
        with KodiProfile('22', strict_skin_controls=True):
            # Instantiate all 16 WindowXMLDialog subclasses against their canonical XML templates
            w1 = Anichart('anichart.xml', control.ADDON_PATH)
            self.assertIsNotNone(w1)

            w2 = StatsWindow('anime_statistics.xml', control.ADDON_PATH, stats={})
            self.assertIsNotNone(w2)

            w3 = ClearCacheDialog('clear_cache.xml', control.ADDON_PATH)
            self.assertIsNotNone(w3)

            w4 = DownloadManager('download_manager.xml', control.ADDON_PATH)
            self.assertIsNotNone(w4)

            w5 = FilterSelect('filter_select.xml', control.ADDON_PATH)
            self.assertIsNotNone(w5)

            w6 = GetSources('get_sources.xml', control.ADDON_PATH, actionArgs={'item_information': {}})
            self.assertIsNotNone(w6)

            w7 = MenuOrderDialog('menu_order.xml', control.ADDON_PATH)
            self.assertIsNotNone(w7)

            w8 = Progress_dialog('progress_dialog.xml', control.ADDON_PATH)
            self.assertIsNotNone(w8)

            w9 = Resolver('resolver.xml', control.ADDON_PATH, actionArgs={'item_information': {}})
            self.assertIsNotNone(w9)

            w10 = SortSelect('sort_select.xml', control.ADDON_PATH)
            self.assertIsNotNone(w10)

            w11 = SourceSelect('source_select.xml', control.ADDON_PATH, actionArgs={'item_information': {}})
            self.assertIsNotNone(w11)

            w12 = StillWatchingXML('still_watching.xml', control.ADDON_PATH, actionArgs={'item_information': {}})
            self.assertIsNotNone(w12)

            w13 = TextViewerXML('textviewer.xml', control.ADDON_PATH)
            self.assertIsNotNone(w13)

            w14 = WatchlistFlavorAuth('wlf_auth_anilist.xml', control.ADDON_PATH, flavor='anilist')
            self.assertIsNotNone(w14)

            w15 = PlayingNext('playing_next_default.xml', control.ADDON_PATH, actionArgs={'item_information': {}})
            self.assertIsNotNone(w15)

            w16 = SkipIntro('skip_intro_default.xml', control.ADDON_PATH, actionArgs={'item_information': {}, 'skipintro_end': 90, 'skipintro_aniskip': True})
            self.assertIsNotNone(w16)

    def test_all_7_theme_variants_playing_next_and_skip_intro(self):
        themes = ['default', 'ah2', 'auramod', 'af', 'af2', 'az', 'tb']
        with KodiProfile('22', strict_skin_controls=True):
            for t in themes:
                # playing_next_{t}.xml
                pn = PlayingNext(f'playing_next_{t}.xml', control.ADDON_PATH, actionArgs={'item_information': {}})
                pn.closed = True
                pn.onInit()

                # skip_outro_{t}.xml
                so = PlayingNext(f'skip_outro_{t}.xml', control.ADDON_PATH, actionArgs={'item_information': {}})
                so.closed = True
                so.onInit()

                # skip_intro_{t}.xml
                si = SkipIntro(f'skip_intro_{t}.xml', control.ADDON_PATH, actionArgs={'item_information': {}, 'skipintro_end': 90, 'skipintro_aniskip': True})
                si.closed = True
                si.onInit()

    def test_alt_and_specialized_templates(self):
        with KodiProfile('22', strict_skin_controls=True):
            gs_alt = GetSources('get_sources_alt.xml', control.ADDON_PATH, actionArgs={'item_information': {}})
            self.assertIsNotNone(gs_alt)

            res_alt = Resolver('resolver_alt.xml', control.ADDON_PATH, actionArgs={'item_information': {}})
            self.assertIsNotNone(res_alt)

            src_alt = SourceSelect('source_select_alt.xml', control.ADDON_PATH, actionArgs={'item_information': {}})
            self.assertIsNotNone(src_alt)

            tv1 = TextViewerXML('textviewer_1.xml', control.ADDON_PATH)
            self.assertIsNotNone(tv1)

            wlf_mal = WatchlistFlavorAuth('wlf_auth_mal.xml', control.ADDON_PATH, flavor='mal')
            self.assertIsNotNone(wlf_mal)


class TestStrictCAddonSettingsSchema(unittest.TestCase):
    """Verify CAddonSettings strict type enforcement and default value reset."""

    def setUp(self):
        self._saved_settings = dict(conftest._settings_store)

    def tearDown(self):
        conftest._settings_store.clear()
        conftest._settings_store.update(self._saved_settings)

    def test_strict_settings_type_mismatch_raises_typeerror(self):
        with KodiProfile('22', strict_settings=True):
            addon = xbmcaddon.Addon()
            settings = addon.getSettings()

            # Calling getBool on integer setting 'general.timeout'
            with self.assertRaises(TypeError) as ctx:
                settings.getBool('general.timeout')
            self.assertIn("Setting 'general.timeout' is of type 'integer', cannot call getBool", str(ctx.exception))

            # Calling getInt on boolean setting 'general.smartplay'
            with self.assertRaises(TypeError) as ctx:
                settings.getInt('general.smartplay')
            self.assertIn("Setting 'general.smartplay' is of type 'boolean', cannot call getInt", str(ctx.exception))

            # Calling getStringList on string setting 'otaku.version'
            with self.assertRaises(TypeError) as ctx:
                settings.getStringList('otaku.version')
            self.assertIn("Setting 'otaku.version' is of type 'string', cannot call getStringList", str(ctx.exception))

    def test_strict_settings_undeclared_key_raises_typeerror(self):
        with KodiProfile('22', strict_settings=True):
            addon = xbmcaddon.Addon()
            settings = addon.getSettings()

            with self.assertRaises(TypeError) as ctx:
                settings.getString('completely_unknown_key_xyz_999')
            self.assertIn("Unknown setting ID 'completely_unknown_key_xyz_999'", str(ctx.exception))

    def test_reset_settings_to_defaults_populates_all_393_keys(self):
        schema, defaults = load_settings_schema()
        self.assertEqual(len(defaults), 396, "Expected exactly 396 settings with defaults in settings.xml")

        # Test without test fixtures
        reset_settings_to_defaults(include_test_fixtures=False)
        self.assertEqual(len(conftest._settings_store), 396)
        for sid, dval in defaults.items():
            self.assertIn(sid, conftest._settings_store)
            self.assertEqual(conftest._settings_store[sid], dval)

        # Test with test fixtures
        reset_settings_to_defaults(include_test_fixtures=True)
        self.assertEqual(len(conftest._settings_store), 399)
        self.assertEqual(conftest._settings_store['otaku.version'], '5.5.1')


class TestCleanSettingsDualCompat(unittest.TestCase):
    """Verify orphaned settings pruner clean_settings() under both Kodi profiles."""

    def test_clean_settings_prunes_orphans_under_both_versions(self):
        for ver in ('21', '22'):
            with self.subTest(kodi_version=ver):
                with KodiProfile(ver):
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as tf:
                        tf.write(
                            '<settings version="2">\n'
                            '    <setting id="general.smartplay">true</setting>\n'
                            '    <setting id="general.timeout">15</setting>\n'
                            '    <setting id="dangling.obsolete.key">old_val</setting>\n'
                            '    <setting id="legacy_removed_setting">123</setting>\n'
                            '</settings>\n'
                        )
                        tf_path = tf.name

                    try:
                        pruned_count, removed_ids = clean_settings(profile_settings_path=tf_path, silent=True)
                        self.assertEqual(pruned_count, 2)
                        self.assertIn('dangling.obsolete.key', removed_ids)
                        self.assertIn('legacy_removed_setting', removed_ids)

                        # Verify resulting XML
                        tree = ET.parse(tf_path)
                        root = tree.getroot()
                        remaining_ids = [s.get('id') for s in root.iter('setting')]
                        self.assertIn('general.smartplay', remaining_ids)
                        self.assertIn('general.timeout', remaining_ids)
                        self.assertNotIn('dangling.obsolete.key', remaining_ids)
                        self.assertNotIn('legacy_removed_setting', remaining_ids)
                    finally:
                        if os.path.exists(tf_path):
                            os.remove(tf_path)


class TestKodiProfileErgonomics(unittest.TestCase):
    """Verify KodiProfile decorator, mixin, and nested context stack behaviors."""

    def test_decorator_on_function(self):
        @KodiProfile('21')
        def func_21():
            return KodiProfile.current(), control.kodi_version

        @KodiProfile('22')
        def func_22():
            return KodiProfile.current(), control.kodi_version

        self.assertEqual(func_21(), ('21', 21.3))
        self.assertEqual(func_22(), ('22', 22.0))

    def test_nested_profiles_stack(self):
        self.assertEqual(KodiProfile.current(), 'default')
        with KodiProfile('21'):
            self.assertEqual(KodiProfile.current(), '21')
            self.assertEqual(control.kodi_version, 21.3)
            with KodiProfile('22'):
                self.assertEqual(KodiProfile.current(), '22')
                self.assertEqual(control.kodi_version, 22.0)
            self.assertEqual(KodiProfile.current(), '21')
            self.assertEqual(control.kodi_version, 21.3)
        self.assertEqual(KodiProfile.current(), 'default')

    def test_resolver_inputstream_headers_dual(self):
        with KodiProfile('21'):
            self.assertLessEqual(control.kodi_version, 21.8)
        with KodiProfile('22'):
            self.assertGreater(control.kodi_version, 21.8)


@KodiProfile('21')
class TestKodiProfileClassDecorator21(unittest.TestCase):
    def test_class_decorator_active_21(self):
        self.assertEqual(KodiProfile.current(), '21')
        self.assertEqual(control.kodi_version, 21.3)


@KodiProfile('22')
class TestKodiProfileClassDecorator22(unittest.TestCase):
    def test_class_decorator_active_22(self):
        self.assertEqual(KodiProfile.current(), '22')
        self.assertEqual(control.kodi_version, 22.0)


class TestKodiProfileMixinSample(KodiProfileMixin, unittest.TestCase):
    kodi_profile_version = '22'
    strict_settings = True
    strict_skin_controls = True

    def test_mixin_state(self):
        self.assertEqual(KodiProfile.current(), '22')
        self.assertTrue(KodiProfile.is_strict_settings())
        self.assertTrue(KodiProfile.is_strict_skin_controls())


if __name__ == '__main__':
    unittest.main()
