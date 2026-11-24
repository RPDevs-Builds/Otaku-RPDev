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

    # ── 6. C-28 Companion Addon Binding & C-29 Signs-Only Embed Upgrade ──────

    def test_signs_only_embed_vtt_triggers_full_dialogue_auto_download(self):
        """C-29: Sparse Signs-only embed sidecar (<45 cues) must auto-download Full Dialogue when requested."""
        from resources.lib.ui import embed_extractor

        signs_vtt = (
            "WEBVTT\n\n"
            "00:01.020 --> 00:06.770\n<b>EPISODE 9</b>\n\n"
            "05:55.870 --> 05:59.000\n<b>TORAYA</b>\n"
        )
        control.clearGlobalProp('otaku.embed_sub_signs_only')
        control.clearGlobalProp('otaku.embed_sub_has_full_dialog')

        with patch('resources.lib.ui.embed_extractor.client.get', return_value=_FakeResponse(200, text=signs_vtt)):
            sub_info = embed_extractor.get_sub('https://cdn.example/signs.vtt', 'eng', sub_tag='58516_9_test')

        self.assertIsNotNone(sub_info)
        self.assertTrue(sub_info['is_signs_only'])
        self.assertEqual(sub_info['cue_count'], 2)
        self.assertEqual(control.getGlobalProp('otaku.embed_sub_signs_only'), 'true')

        # Now simulate WatchlistPlayer with Full Dialogue requested (keywords=1, dubsubtitles=True)
        control.setBool('general.kodi_language', False)
        control.setBool('general.subtitles.keyword', True)
        control.setBool('general.dubsubtitles', True)
        control.setBool('subtitles.prefer_forced', False)
        control.setBool('subtitles.enabled', True)
        control.setBool('subtitles.auto_search', True)

        p = player_mod.WatchlistPlayer()
        p.preferred_audio = 1
        p.preferred_subtitle_setting = 1
        p.preferred_subtitle_keyword = 1  # Dialog (Full Dialogue)
        p.preferred_subtitle_type = 0
        p.setAudioStream = MagicMock()
        p.setSubtitleStream = MagicMock()
        p.showSubtitles = MagicMock()

        with patch.object(
            control, 'jsonrpc',
            return_value={
                'result': {
                    'audiostreams': [{'index': 0, 'language': 'und', 'name': ''}],
                    'subtitles': [{'index': 0, 'language': 'eng', 'name': '(External)', 'isforced': False}],
                }
            },
        ), patch.object(subtitles, 'auto_download_subtitles', return_value=True) as mock_auto:
            p.setup_audio_and_subtitles()

        mock_auto.assert_called_once()
        # Because auto_download_subtitles attached full dialogue, do not overwrite back to signs-only stream 0
        p.setSubtitleStream.assert_not_called()

    def test_companion_addon_id_binds_control_to_otaku_plugin(self):
        """C-28: Importing control from service.subtitles.otaku.rpdev must bind ADDON_ID to plugin.video.otaku.rpdev."""
        self.assertEqual(control.ADDON_ID, 'plugin.video.otaku.rpdev')
        # Verify the companion-addon redirect logic in control.py source directly via isolated check
        control_src_path = os.path.join(_REPO_ROOT, 'plugin.video.otaku.rpdev', 'resources', 'lib', 'ui', 'control.py')
        with open(control_src_path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("('service.subtitles.otaku.rpdev', 'context.otaku.rpdev')", src)
        self.assertIn("settings.getBool(key, default)", src)

    def test_atomic_write_text_uses_xbmcvfs_rename_for_kodi_directory_cache(self):
        """C-30: control.atomic_write_text must prefer xbmcvfs.rename() so Kodi C++ g_directoryCache.AddFile() runs."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            dest = os.path.join(tmp_dir, 'test_sub.en.12345.srt')
            rename_calls = []

            def _fake_vfs_rename(src, dst):
                rename_calls.append((src, dst))
                os.replace(src, dst)
                return True

            with patch.object(control.xbmcvfs, 'rename', side_effect=_fake_vfs_rename):
                ok = control.atomic_write_text(dest, "1\n00:00:01,000 --> 00:00:03,000\nHello\n")

            self.assertTrue(ok)
            self.assertEqual(len(rename_calls), 1)
            self.assertEqual(rename_calls[0][1], dest)
            self.assertTrue(os.path.isfile(dest))
            with open(dest, 'r', encoding='utf-8') as f:
                self.assertIn('Hello', f.read())

    def test_download_syncs_vfs_file_if_kodi_cache_hides_written_subtitle(self):
        """C-30: If xbmcvfs.exists(dest_path) reports False after write (stale g_directoryCache), sync via xbmcvfs.File."""
        import tempfile
        valid_srt = b"1\n00:00:01,000 --> 00:00:04,000\nSync line.\n"
        fake_svc = MagicMock()
        fake_svc.download.return_value = valid_srt

        result = SubtitleResult(
            service_name='subsource',
            display_name='SubSource',
            name='Blue.Exorcist.S04E10.srt',
            lang='English',
            lang_code='en',
            download_url='https://api.subsource.net/api/v1/subtitles/1/download',
        )
        meta = VideoMeta(title='Blue Exorcist', tvshow='Blue Exorcist', season=4, episode=10, is_tvshow=True)
        vfs_writes = []

        class _TrackingVFSFile:
            def __init__(self, path, mode='r'):
                self.path = path
                self.mode = mode
            def write(self, data):
                vfs_writes.append((self.path, self.mode, data))
                return len(data)
            def close(self):
                pass

        with tempfile.TemporaryDirectory() as tmp_dir, \
             patch.dict(sub_download.ALL_SERVICES, {'subsource': fake_svc}), \
             patch.object(sub_download.xbmcvfs, 'exists', return_value=False), \
             patch.object(sub_download.xbmcvfs, 'File', _TrackingVFSFile):
            path = sub_download.download_and_prepare_subtitle(result, meta, {'subtitles.use_chardet': False}, dest_dir=tmp_dir)

        self.assertIsNotNone(path)
        self.assertTrue(path.startswith(tmp_dir))
        self.assertEqual(len(vfs_writes), 1)
        self.assertEqual(vfs_writes[0][0], path)
        self.assertEqual(vfs_writes[0][1], 'w')
        self.assertIn(b'Sync line.', vfs_writes[0][2])

    def test_subsource_and_anime_dash_episode_auto_identification(self):
        """C-31: Anime '- 10' filenames and SubSource season matches should be auto-identified."""
        meta = VideoMeta(
            title='Blue Exorcist -Beyond the Snow Saga-',
            tvshow='Blue Exorcist -Beyond the Snow Saga-',
            season=4,
            episode=10,
            languages=['English'],
            preferred_lang='en',
            is_tvshow=True,
        )
        dash_sub = SubtitleResult(
            service_name='subsource',
            display_name='SubSource',
            name='[SubsPlease] Blue Exorcist -Beyond the Snow Saga- - 10 (1080p).srt',
            lang='English',
            lang_code='en',
            season=4,
        )
        sub_search.score_result(dash_sub, meta, {})
        self.assertTrue(dash_sub.auto_identified)
        self.assertEqual(dash_sub.match_reason, 'Exact Ep')

        pack_sub = SubtitleResult(
            service_name='subsource',
            display_name='SubSource',
            name='Blue.Exorcist.Beyond.the.Snow.Saga.WEB-DL.1080p.zip',
            lang='English',
            lang_code='en',
            season=4,
        )
        sub_search.score_result(pack_sub, meta, {})
        self.assertTrue(pack_sub.auto_identified)
        self.assertEqual(pack_sub.match_reason, 'Season Pack')

    def test_service_download_uses_own_profile_temp_dir(self):
        """C-30: service.subtitles.otaku.rpdev action=download stages files in its own addon_data temp dir."""
        import tempfile
        svc = _load_subtitle_service_module()
        with tempfile.TemporaryDirectory() as tmp_profile:
            payload = urllib.parse.quote_plus(json.dumps({
                'service_name': 'subsource',
                'display_name': 'SubSource',
                'name': 'Blue.Exorcist.S04E10.srt',
                'lang': 'English',
                'lang_code': 'en',
                'download_url': 'https://api.subsource.net/api/v1/subtitles/99/download',
                'action_args': {'sub_id': '99'},
            }))
            captured_dest_dirs = []

            def _fake_dl(result, meta, settings, dest_dir=None):
                captured_dest_dirs.append(dest_dir)
                out = os.path.join(dest_dir or tmp_profile, 'Blue_Exorcist.en.12345.srt')
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with open(out, 'w', encoding='utf-8') as f:
                    f.write("1\n00:00:01,000 --> 00:00:02,000\nHi\n")
                return out

            fake_addon = MagicMock()
            fake_addon.getAddonInfo.return_value = tmp_profile
            with patch.object(svc.xbmcaddon, 'Addon', return_value=fake_addon), \
                 patch.object(svc.xbmcvfs, 'translatePath', side_effect=lambda p: p), \
                 patch.object(subtitles, 'download_subtitle', side_effect=_fake_dl), \
                 patch.object(xbmcplugin, 'addDirectoryItem') as mock_add, \
                 patch.object(xbmcplugin, 'endOfDirectory'):
                emitted = svc.handle_request(77, f'?action=download&payload={payload}')

            self.assertEqual(emitted, 1)
            self.assertEqual(captured_dest_dirs, [os.path.join(tmp_profile, 'temp')])
            mock_add.assert_called_once()

    def test_del_subs_resets_stale_full_dialog_flag_so_next_ep_signs_only_auto_upgrades(self):
        """C-32: Stale otaku.embed_sub_has_full_dialog='true' from a prior episode must be cleared before get_sub()."""
        from resources.lib.ui import embed_extractor

        # Simulate prior episode (e.g. 58516 Ep 12) leaving embed_sub_has_full_dialog='true' in Window(10000)
        control.setGlobalProp('otaku.embed_sub_has_full_dialog', 'true')
        control.setGlobalProp('otaku.embed_sub_signs_only', 'false')

        # Incoming episode calls del_subs() before fetching its own Signs-only sidecar
        embed_extractor.del_subs()
        self.assertEqual(control.getGlobalProp('otaku.embed_sub_has_full_dialog'), '')
        self.assertEqual(control.getGlobalProp('otaku.embed_sub_signs_only'), '')

        signs_vtt = "WEBVTT\n\n01:32.020 --> 01:37.990\n<b>EPISODE 8</b>\n\n23:34.930 --> 23:39.940\n<b>NEXT TIME</b>\n"

        class _FakeResp:
            status_code = 200
            text = signs_vtt

        with patch('resources.lib.ui.embed_extractor.client.get', return_value=_FakeResp()):
            info = embed_extractor.get_sub('https://cdn.example/ep8.vtt', 'eng', sub_tag='59226_8_test')

        self.assertIsNotNone(info)
        self.assertTrue(info['is_signs_only'])
        self.assertEqual(control.getGlobalProp('otaku.embed_sub_signs_only'), 'true')
        self.assertEqual(control.getGlobalProp('otaku.embed_sub_has_full_dialog'), '')

        # Also verify _ensure_subtitles_available() upgrades Signs-only sidecars when prefer_forced=False
        control.setBool('subtitles.enabled', True)
        control.setBool('subtitles.auto_search', True)
        control.setBool('subtitles.prefer_forced', False)
        control.setBool('general.dubsubtitles', True)
        p = player_mod.WatchlistPlayer()
        with patch.object(
            control, 'jsonrpc',
            return_value={
                'result': {
                    'audiostreams': [{'index': 0, 'language': 'und', 'name': ''}],
                    'subtitles': [{'index': 0, 'language': 'eng', 'name': '(External)', 'isforced': False}],
                }
            },
        ), patch.object(subtitles, 'auto_download_subtitles', return_value=True) as mock_auto:
            self.assertTrue(p._ensure_subtitles_available())
        mock_auto.assert_called_once()

    def test_get_sub_registers_special_temp_uri_in_kodi_vfs_cache(self):
        """C-33: get_sub() must pass special://temp/ vfs_path to atomic_write_text and sync xbmcvfs.File if hidden."""
        import tempfile
        from resources.lib.ui import embed_extractor

        vtt_body = "WEBVTT\n\n01:32.020 --> 01:37.990\n<b>EPISODE 8</b>\n"

        class _FakeResp:
            status_code = 200
            text = vtt_body

        rename_pairs = []
        vfs_writes = []

        class _TrackVFS:
            def __init__(self, path, mode='r'):
                self.path = path
                self.mode = mode
            def write(self, data):
                vfs_writes.append((self.path, self.mode, data))
                return len(data)
            def close(self):
                pass

        with tempfile.TemporaryDirectory() as tmp_temp:
            def _translate(p):
                if p == 'special://temp/':
                    return tmp_temp
                if p.startswith('special://temp/'):
                    return os.path.join(tmp_temp, p[len('special://temp/'):])
                return p

            def _fake_rename(src, dst):
                rename_pairs.append((src, dst))
                os.replace(_translate(src), _translate(dst))
                return True

            with patch('resources.lib.ui.embed_extractor.client.get', return_value=_FakeResp()), \
                 patch.object(embed_extractor.xbmcvfs, 'translatePath', side_effect=_translate), \
                 patch.object(control.xbmcvfs, 'rename', side_effect=_fake_rename), \
                 patch.object(embed_extractor.xbmcvfs, 'exists', return_value=False), \
                 patch.object(embed_extractor.xbmcvfs, 'File', _TrackVFS):
                info = embed_extractor.get_sub('https://cdn.example/ep8.vtt', 'eng', sub_tag='59226_8_vfs')

            self.assertIsNotNone(info)
            self.assertTrue(info['path'].startswith('special://temp/TemporarySubs.59226_8_vfs.'))
            # First rename must target the special://temp/ URI so COverrideFile::Rename updates both cache keys
            self.assertEqual(len(rename_pairs), 1)
            self.assertTrue(rename_pairs[0][0].startswith('special://temp/'))
            self.assertEqual(rename_pairs[0][1], info['path'])
            # Visibility fallback also synced via special://temp/ URI when xbmcvfs.exists returned False
            self.assertEqual(len(vfs_writes), 1)
            self.assertEqual(vfs_writes[0][0], info['path'])
            self.assertEqual(vfs_writes[0][1], 'w')

    def test_title_mismatch_demotes_unrelated_season_pack_and_subsource_filters_wrong_show(self):
        from resources.lib.subtitles import search as sub_search
        from resources.lib.subtitles.archive import find_file_in_archive_namelist
        from resources.lib.subtitles.services.subsource import SubSourceService

        meta = VideoMeta(
            title='Kaiju No. 8 Season 2 Episode 1',
            tvshow='Kaiju No. 8 Season 2',
            season='2',
            episode='1',
            is_tvshow=True,
            preferred_lang='en',
            languages=['English'],
        )
        wrong_pack = SubtitleResult(
            service_name='subsource',
            display_name='SubSource',
            name='The.Four.Seasons.2025.S02.WEB-DL.x264',
            lang='English',
            lang_code='en',
            download_url='https://example/1',
            season=2,
            rating=9.0,
        )
        right_pack = SubtitleResult(
            service_name='subsource',
            display_name='SubSource',
            name='Kaiju.No.8.S02.1080p.CR.WEB-DL',
            lang='English',
            lang_code='en',
            download_url='https://example/2',
            season=2,
            rating=5.0,
        )
        settings = {'subtitles.prefer_sdh': False, 'subtitles.prefer_forced': False}
        s_wrong = sub_search.score_result(wrong_pack, meta, settings)
        s_right = sub_search.score_result(right_pack, meta, settings)
        self.assertGreater(s_right, s_wrong)
        self.assertFalse(wrong_pack.auto_identified)
        self.assertEqual(wrong_pack.match_reason, 'Title Mismatch')
        self.assertTrue(right_pack.auto_identified)

        # SubSourceService.search skips 'The Four Seasons' and picks 'Kaiju No. 8'
        class _FakeResp:
            def __init__(self, status_code, payload):
                self.status_code = status_code
                self._payload = payload

            def json(self, default=None):
                return self._payload

        def _fake_get(url, params=None, headers=None, timeout=15):
            if '/movies/search' in url:
                return _FakeResp(200, {
                    'data': [
                        {'movieId': 111, 'title': 'The Four Seasons', 'season': 2},
                        {'movieId': 222, 'title': 'Kaiju No. 8', 'season': 2},
                    ]
                })
            self.assertEqual(params.get('movieId'), 222)
            return _FakeResp(200, {
                'success': True,
                'data': [{'releaseInfo': ['Kaiju.No.8.S02.1080p'], 'language': 'english', 'link': '/sub/99'}],
            })

        with patch('resources.lib.subtitles.services.subsource.client.get', side_effect=_fake_get):
            res = SubSourceService.search(meta, {'subtitles.subsource.apikey': 'k', 'subtitles.timeout': 10})
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].name, 'Kaiju.No.8.S02.1080p')

        # Archive namelist prefers full dialogue .srt over signs/forced track
        picked = find_file_in_archive_namelist(
            ['Kaiju.No.8.S02E01.Signs.Songs.ass', 'Kaiju.No.8.S02E01.English.srt'],
            episode_number='1',
            season_number='2',
        )
        self.assertEqual(picked, 'Kaiju.No.8.S02E01.English.srt')


if __name__ == '__main__':
    unittest.main()
