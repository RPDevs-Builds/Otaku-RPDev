# -*- coding: utf-8 -*-
"""
test_subtitle_service_and_auto_download.py
==========================================
Actionable unit and cross-subsystem tests verifying:
1. Sanitized 10.13.0.16 all-6-services subtitle configuration parity.
2. Auto-identified subtitle match classification (Hash Match, Release Match,
   Exact Ep, Season Pack, IMDb Match, Manual) and Kodi/dialog indicator badges.
3. Companion Kodi xbmc.subtitle.module (service.subtitles.otaku.rpdev/service.py):
   - action=search (auto-identification + SYNC/CC/flag/rating ListItem props)
   - action=manualsearch (parsed SxxEyy / custom string across enabled providers)
   - action=download (Kodi 22 CDVDFactorySubtitle validation + atomic write + unique sub_tag)
   - Single-source settings integration with Settings - Otaku RPDev > Subtitles
4. WatchlistPlayer automatic subtitle downloading when no subtitles are available:
   - Torrent/debrid streams with 0 subtitles
   - Embed & direct streams with missing sidecar subtitles
   - general.kodi_language=true mode
   - general.dubsubtitles=false guard on English Dub audio
   - Invalid HTTP 200 HTML subtitle rejection + candidate fallthrough
5. Interactive manual_select_dialog ([Manual Search...] keyboard flow) & routes/subtitles.py.
"""

import importlib.util
import json
import os
import sys
import unittest
import urllib.parse
from unittest.mock import MagicMock, patch

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_TEST_DIR))
_TESTS_DIR = os.path.join(_REPO_ROOT, 'tests')
for _p in (_REPO_ROOT, _TESTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import conftest  # noqa: F401
import xbmc
import xbmcgui
import xbmcplugin

from resources.lib.ui import control
from resources.lib import subtitles
from resources.lib.subtitles.models import VideoMeta, SubtitleResult
from resources.lib.subtitles import search as sub_search
from resources.lib.subtitles import meta as sub_meta
from resources.lib.subtitles import download as sub_download
from resources.lib.subtitles import languages as sub_languages
from resources.lib.routes import subtitles as sub_routes
from resources.lib.ui import player as player_mod

FIXTURE_CONFIG_PATH = os.path.join(_REPO_ROOT, 'tests', 'fixtures', 'subtitle_config_all_services.json')
SUB_SERVICE_PATH = os.path.join(_REPO_ROOT, 'service.subtitles.otaku.rpdev', 'service.py')
SUB_ADDON_XML_PATH = os.path.join(_REPO_ROOT, 'service.subtitles.otaku.rpdev', 'addon.xml')
SUB_SETTINGS_XML_PATH = os.path.join(_REPO_ROOT, 'service.subtitles.otaku.rpdev', 'resources', 'settings.xml')


def _load_subtitle_service_module():
    spec = importlib.util.spec_from_file_location('subtitle_service_main', SUB_SERVICE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules['subtitle_service_main'] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_all_services_fixture():
    with open(FIXTURE_CONFIG_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith('_')}


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text='', content=b''):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.content = content or text.encode('utf-8')

    def json(self, default=None):
        if self._json_data is None:
            return default if default is not None else {}
        return self._json_data


class TestSubtitleServiceAndAutoDownload(unittest.TestCase):
    """End-to-end verification of native subtitle service, auto-download, manual search, and indicators."""

    @classmethod
    def setUpClass(cls):
        cls.svc_mod = _load_subtitle_service_module()
        cls.fixture_cfg = _load_all_services_fixture()

    def setUp(self):
        control._settings_cache.clear()
        sub_meta.clear_active_playback_meta()
        xbmcplugin.directory_items = []
        xbmcplugin.end_of_directory_called = False
        # Apply sanitized 10.13.0.16 all-6-services configuration
        for k, v in self.fixture_cfg.items():
            if isinstance(v, bool):
                control.setBool(k, v)
            elif isinstance(v, int):
                control.setInt(k, v)
            else:
                control.setSetting(k, str(v))
        control.setBool('general.kodi_language', False)

    def tearDown(self):
        sub_meta.clear_active_playback_meta()

    # ── 1. Manifest & Sanitized All-6-Services Config ────────────────────────

    def test_companion_addon_xml_and_settings_valid(self):
        import xml.etree.ElementTree as ET
        tree = ET.parse(SUB_ADDON_XML_PATH)
        root = tree.getroot()
        self.assertEqual(root.attrib.get('id'), 'service.subtitles.otaku.rpdev')
        ext = root.find("./extension[@point='xbmc.subtitle.module']")
        self.assertIsNotNone(ext)
        self.assertEqual(ext.attrib.get('library'), 'service.py')

        # Settings schema points back to Settings - Otaku RPDev > Subtitles
        stree = ET.parse(SUB_SETTINGS_XML_PATH)
        sroot = stree.getroot()
        open_btn = sroot.find(".//setting[@id='open_otaku_settings']/data")
        self.assertIsNotNone(open_btn)
        self.assertIn('open_subtitle_settings', open_btn.text or '')

    def test_all_six_services_loaded_from_otaku_settings(self):
        settings = subtitles.get_subtitles_settings()
        for svc in ('opensubtitles', 'subdl', 'subsource', 'podnadpisi', 'bsplayer', 'addic7ed'):
            self.assertTrue(settings[f'subtitles.provider.{svc}'], f"Provider {svc} should be enabled")
        self.assertEqual(settings['subtitles.opensubtitles.username'], 'test_os_user')
        self.assertEqual(settings['subtitles.subdl.apikey'], 'test_subdl_apikey_placeholder')
        self.assertEqual(settings['subtitles.subsource.apikey'], 'test_subsource_apikey_placeholder')
        self.assertTrue(settings['subtitles.prefer_sdh'])
        self.assertEqual(settings['subtitles.timeout'], 15)
        self.assertEqual(settings['subtitles.results_limit'], 20)

    # ── 2. Auto-Identified Indicators & Manual Query Parsing ─────────────────

    def test_manual_search_query_parser_variants(self):
        p1 = sub_meta.parse_manual_search_query('Frieren Beyond Journeys End S01E05')
        self.assertEqual(p1['title'], 'Frieren Beyond Journeys End')
        self.assertEqual(p1['season'], '1')
        self.assertEqual(p1['episode'], '5')

        p2 = sub_meta.parse_manual_search_query('Solo Leveling Season 2 Episode 12')
        self.assertEqual(p2['title'], 'Solo Leveling')
        self.assertEqual(p2['season'], '2')
        self.assertEqual(p2['episode'], '12')

        p3 = sub_meta.parse_manual_search_query('Spirited Away 2001')
        self.assertEqual(p3['title'], 'Spirited Away')
        self.assertEqual(p3['year'], '2001')
        self.assertEqual(p3['episode'], '')

    def test_auto_identified_match_classification_and_indicators(self):
        meta = VideoMeta(
            tvshow='Frieren',
            season='1',
            episode='5',
            imdb_id='tt22248376',
            filename='[SubsPlease] Frieren - S01E05 (1080p).mkv',
            languages=['English'],
            preferred_lang='en',
            filehash='abcdef1234567890',
        )
        settings = subtitles.get_subtitles_settings()

        exact_hash = SubtitleResult('opensubtitles', 'OpenSubtitles', 'Frieren.S01E05.srt', 'English', 'en', sync=True, season=1, episode=5)
        exact_ep = SubtitleResult('subdl', 'SubDL', 'Frieren.S01E05.WEB.srt', 'English', 'en', season=1, episode=5)
        season_pack = SubtitleResult('subsource', 'SubSource', 'Frieren.S01.Complete.zip', 'English', 'en', season=1, episode=None)
        wrong_ep = SubtitleResult('podnadpisi', 'Podnadpisi', 'Frieren.S01E09.srt', 'English', 'en', season=1, episode=9)

        for r in (exact_hash, exact_ep, season_pack, wrong_ep):
            sub_search.score_result(r, meta, settings)

        self.assertTrue(exact_hash.auto_identified)
        self.assertEqual(exact_hash.match_confidence, 'exact')
        self.assertEqual(exact_hash.match_reason, 'Hash Match')
        self.assertIn('AUTO • Hash Match', subtitles.format_result_badge(exact_hash))

        self.assertTrue(exact_ep.auto_identified)
        self.assertEqual(exact_ep.match_reason, 'Exact Ep')
        self.assertIn('AUTO • Exact Ep', subtitles.format_kodi_listitem_label2(exact_ep))

        self.assertTrue(season_pack.auto_identified)
        self.assertEqual(season_pack.match_reason, 'Season Pack')
        self.assertIn('AUTO • Season Pack', subtitles.format_dialog_label(season_pack))

        self.assertFalse(wrong_ep.auto_identified)
        self.assertEqual(wrong_ep.match_reason, 'Mismatch')

        # Conflicting SxxEyy in filename overrides stale provider metadata (e.g. SubDL returning S01E33 for S01E05)
        conflicting_ep = SubtitleResult('subdl', 'SubDL', 'Frieren.S01E33.CR.WEB-DL.AAC.2.0-OWL', 'English', 'en', season=1, episode=5)
        sub_search.score_result(conflicting_ep, meta, settings)
        self.assertFalse(conflicting_ep.auto_identified)
        self.assertEqual(conflicting_ep.match_reason, 'Mismatch')
        # Non-subtitle dotted suffix like '.0-OWL' must NOT be misparsed as file extension
        lbl_owl = subtitles.format_kodi_listitem_label2(conflicting_ep)
        self.assertIn('([B]SRT[/B])', lbl_owl)
        self.assertNotIn('0-OWL[/B])', lbl_owl)

        # Manual search result without exact ep match gets [MANUAL] indicator
        manual_meta = VideoMeta(title='Frieren', search_string='Frieren', is_manual_search=True, is_tvshow=False, languages=['English'], preferred_lang='en')
        manual_res = SubtitleResult('podnadpisi', 'Podnadpisi', 'Frieren.Movie.srt', 'English', 'en')
        sub_search.score_result(manual_res, manual_meta, settings)
        self.assertFalse(manual_res.auto_identified)
        self.assertEqual(manual_res.match_confidence, 'manual')
        self.assertIn('[MANUAL]', subtitles.format_kodi_listitem_label2(manual_res))

    # ── 3. Kodi xbmc.subtitle.module Service Actions ─────────────────────────

    def test_kodi_subtitle_service_action_search_emits_sync_and_auto_indicators(self):
        sub_meta.publish_active_playback_meta(
            {'tvshowtitle': 'Frieren', 'season': 1, 'episode': 5, 'UniqueIDs': {'imdb': 'tt22248376'}},
            mal_id='52991',
            filename='Frieren.S01E05.1080p.mkv',
        )
        fake_auto = SubtitleResult(
            'opensubtitles', 'OpenSubtitles', 'Frieren.S01E05.1080p.srt', 'English', 'en',
            download_url='https://api.opensubtitles.com/api/v1/download',
            rating=4.5, sync=True, impaired=True, season=1, episode=5,
            action_args={'file_id': 999},
        )
        fake_auto.auto_identified = True
        fake_auto.match_confidence = 'exact'
        fake_auto.match_reason = 'Release Match'

        with patch.object(subtitles, 'search_subtitles', return_value=[fake_auto]), \
             patch.object(xbmcplugin, 'endOfDirectory', wraps=xbmcplugin.endOfDirectory) as mock_eod:
            emitted = self.svc_mod.handle_request(
                42,
                '?action=search&languages=English&preferredlanguage=English',
            )

        self.assertEqual(emitted, 1)
        mock_eod.assert_called_once_with(42)
        self.assertEqual(len(xbmcplugin.directory_items), 1)
        _handle, url, li, is_folder = xbmcplugin.directory_items[0]
        self.assertFalse(is_folder)
        self.assertIn('plugin://service.subtitles.otaku.rpdev/?action=download&payload=', url)
        self.assertEqual(li.getProperty('sync'), 'true')
        self.assertEqual(li.getProperty('hearing_imp'), 'true')
        self.assertEqual(li.getProperty('otaku.auto_identified'), 'true')
        self.assertEqual(li.getProperty('otaku.match_reason'), 'Release Match')
        self.assertIn('AUTO • Release Match', li.getLabel2())
        self.assertIn('OpenSubtitles', li.getLabel2())

    def test_kodi_subtitle_service_action_manualsearch_passes_parsed_query(self):
        captured = {}

        def _fake_search(meta, settings):
            captured['meta'] = meta
            r = SubtitleResult('subdl', 'SubDL', 'Dandadan.S01E03.srt', 'English', 'en', season=1, episode=3)
            sub_search.score_result(r, meta, settings)
            return [r]

        with patch.object(subtitles, 'search_subtitles', side_effect=_fake_search):
            emitted = self.svc_mod.handle_request(
                7,
                '?action=manualsearch&searchstring=Dandadan+S01E03&languages=English&preferredlanguage=English',
            )

        self.assertEqual(emitted, 1)
        self.assertTrue(captured['meta'].is_manual_search)
        self.assertEqual(captured['meta'].title, 'Dandadan')
        self.assertEqual(captured['meta'].season, '1')
        self.assertEqual(captured['meta'].episode, '3')
        self.assertEqual(len(xbmcplugin.directory_items), 1)
        _, _, li, _ = xbmcplugin.directory_items[0]
        self.assertEqual(li.getProperty('sync'), 'true')
        self.assertIn('AUTO • Exact Ep', li.getLabel2())

    def test_kodi_subtitle_service_action_download_validates_and_returns_local_file(self):
        valid_srt = b"1\n00:00:01,000 --> 00:00:03,500\nHello from Otaku Subtitles!\n"
        payload = urllib.parse.quote_plus(json.dumps({
            'service_name': 'subdl',
            'display_name': 'SubDL',
            'name': 'Frieren.S01E05.srt',
            'lang': 'English',
            'lang_code': 'en',
            'download_url': 'https://dl.subdl.com/test.srt',
            'action_args': {'url': '/test.srt'},
            'season': 1,
            'episode': 5,
            'auto_identified': True,
            'match_reason': 'Exact Ep',
        }))

        with patch('resources.lib.subtitles.services.subdl.SubDLService.download', return_value=valid_srt):
            emitted = self.svc_mod.handle_request(9, f'?action=download&payload={payload}')

        self.assertEqual(emitted, 1)
        self.assertEqual(len(xbmcplugin.directory_items), 1)
        _, local_path, _, _ = xbmcplugin.directory_items[0]
        self.assertTrue(os.path.isfile(local_path))
        self.assertTrue(local_path.endswith('.srt'))
        with open(local_path, 'r', encoding='utf-8') as f:
            written = f.read()
        self.assertIn('Hello from Otaku Subtitles!', written)
        self.assertEqual(control.getGlobalProp('otaku.subtitle.auto_loaded'), 'true')
        try:
            os.remove(local_path)
        except OSError:
            pass

    def test_download_rejects_kodi22_invalid_html_200_error_page(self):
        html_200 = b"<!DOCTYPE html><html><body>Cloudflare rate limit</body></html>"
        res = SubtitleResult('subdl', 'SubDL', 'bad.srt', 'English', 'en', download_url='https://dl.subdl.com/bad.srt')
        meta = VideoMeta(tvshow='Frieren', season='1', episode='5', preferred_lang='en')
        with patch('resources.lib.subtitles.services.subdl.SubDLService.download', return_value=html_200):
            out = sub_download.download_and_prepare_subtitle(res, meta, subtitles.get_subtitles_settings())
        self.assertIsNone(out)

    # ── 4. Player Auto-Download When No Subtitles Are Available ──────────────

    def test_player_auto_downloads_for_embed_without_subtitles_and_kodi_language_mode(self):
        p = player_mod.WatchlistPlayer()
        p.mal_id = '52991'
        p.episode = 5
        p.type = 'embed'
        p.provider = 'hianime'

        # Case A: Embed stream with 0 subtitles -> triggers auto_download_subtitles
        with patch.object(control, 'jsonrpc', return_value={'result': {'audiostreams': [{'index': 0, 'language': 'jpn', 'name': 'Japanese'}], 'subtitles': []}}), \
             patch.object(subtitles, 'auto_download_subtitles', return_value=True) as mock_auto:
            res = p._ensure_subtitles_available()
        self.assertTrue(res)
        mock_auto.assert_called_once()

        # Case B: general.kodi_language=True with 0 subtitles -> still triggers auto_download_subtitles
        control.setBool('general.kodi_language', True)
        with patch.object(control, 'jsonrpc', side_effect=[
            {'result': {'audiostreams': [{'index': 0, 'language': 'ja', 'name': 'Japanese'}], 'subtitles': []}},
            {'result': {'value': 'English'}},
        ]), patch.object(subtitles, 'auto_download_subtitles', return_value=True) as mock_auto2:
            p.setup_audio_and_subtitles()
        mock_auto2.assert_called_once()

        # Case C: English Dub audio with general.dubsubtitles=False -> skips unwanted full dialogue auto-download
        control.setBool('general.kodi_language', False)
        control.setBool('general.dubsubtitles', False)
        control.setBool('subtitles.prefer_forced', False)
        with patch.object(subtitles, 'auto_download_subtitles', return_value=True) as mock_auto3:
            skipped = p._trigger_auto_subtitle_download(preferred_subtitle_lang='eng', is_eng_audio=True)
        self.assertFalse(skipped)
        mock_auto3.assert_not_called()

    def test_auto_download_fallthrough_on_bad_first_candidate_and_sets_osd_indicator(self):
        bad_cand = SubtitleResult('subdl', 'SubDL', 'Frieren.S01E05.bad.srt', 'English', 'en', season=1, episode=5)
        bad_cand.auto_identified = True
        bad_cand.match_reason = 'Exact Ep'
        good_cand = SubtitleResult('opensubtitles', 'OpenSubtitles', 'Frieren.S01E05.good.srt', 'English', 'en', season=1, episode=5)
        good_cand.auto_identified = True
        good_cand.match_reason = 'Release Match'

        meta = VideoMeta(tvshow='Frieren', season='1', episode='5', preferred_lang='en')
        mock_player = MagicMock()
        mock_player.isPlaying.return_value = True

        with patch.object(subtitles, 'search_subtitles', return_value=[bad_cand, good_cand]), \
             patch.object(subtitles, 'download_subtitle', side_effect=[None, '/tmp/good.en.srt']), \
             patch('resources.lib.subtitles.xbmc.Player', return_value=mock_player), \
             patch.object(control, 'notify') as mock_notify:
            ok = subtitles.auto_download_subtitles(meta=meta, settings=subtitles.get_subtitles_settings())

        self.assertTrue(ok)
        mock_player.setSubtitles.assert_called_once_with('/tmp/good.en.srt')
        mock_player.showSubtitles.assert_called_once_with(True)
        self.assertEqual(control.getGlobalProp('otaku.subtitle.auto_loaded'), 'true')
        self.assertIn('Auto • Release Match', control.getGlobalProp('otaku.subtitle.auto_label'))
        mock_notify.assert_called_once()
        self.assertIn('Auto • Release Match', mock_notify.call_args[0][1])

    # ── 5. Manual Select Dialog & Routes ─────────────────────────────────────

    def test_manual_select_dialog_supports_custom_manual_search_and_routes(self):
        manual_res = SubtitleResult('podnadpisi', 'Podnadpisi', 'Bleach.S01E01.srt', 'English', 'en', season=1, episode=1)
        manual_res.auto_identified = True
        manual_res.match_reason = 'Exact Ep'

        mock_dlg = MagicMock()
        # First click index 0 ([Manual Search...]), type query, then click index 1 (first result)
        mock_dlg.select.side_effect = [0, 1]
        mock_dlg.input.return_value = 'Bleach S01E01'
        mock_player = MagicMock()
        mock_player.isPlaying.return_value = True

        with patch('resources.lib.subtitles.xbmcgui.Dialog', return_value=mock_dlg), \
             patch.object(subtitles, 'search_subtitles', return_value=[manual_res]), \
             patch.object(subtitles, 'download_subtitle', return_value='/tmp/bleach.en.srt'), \
             patch('resources.lib.subtitles.xbmc.Player', return_value=mock_player):
            ok = subtitles.manual_select_dialog([], VideoMeta(title='Unknown', preferred_lang='en'), subtitles.get_subtitles_settings())

        self.assertTrue(ok)
        mock_dlg.input.assert_called_once()
        mock_player.setSubtitles.assert_called_once_with('/tmp/bleach.en.srt')

        # Test set_kodi_subtitle_service & open_subtitle_settings routes
        with patch.object(control, 'jsonrpc', return_value={'result': True}) as mock_rpc, \
             patch.object(control, 'notify') as mock_notify:
            sub_routes.handle_set_kodi_subtitle_service('', {})
        self.assertEqual(mock_rpc.call_count, 2)
        mock_notify.assert_called_once()

        with patch.object(control.xbmc, 'executebuiltin') as mock_exec:
            sub_routes.handle_open_subtitle_settings('', {})
        mock_exec.assert_called_once_with(f'Addon.OpenSettings({control.ADDON_ID})')


if __name__ == '__main__':
    unittest.main()
