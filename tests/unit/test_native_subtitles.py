"""test_native_subtitles.py - Comprehensive Unit Tests for Native Subtitles Engine
=================================================================================
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

# -*- coding: utf-8 -*-

import os
import io
import json
import zipfile
import gzip
import unittest
from unittest.mock import patch, MagicMock

from resources.lib.subtitles.models import VideoMeta, SubtitleResult
from resources.lib.subtitles import languages
from resources.lib.subtitles import encoding
from resources.lib.subtitles import archive
from resources.lib.subtitles import search
from resources.lib.subtitles import download
from resources.lib.subtitles import meta as sub_meta
from resources.lib.ui import control
from resources.lib.subtitles.services import ALL_SERVICES
from resources.lib.subtitles.services.opensubtitles import OpenSubtitlesService
from resources.lib.subtitles.services.subdl import SubDLService
from resources.lib.subtitles.services.subsource import SubSourceService
from resources.lib.subtitles.services.podnadpisi import PodnadpisiService
from resources.lib.subtitles.services.bsplayer import BSPlayerService
from resources.lib.subtitles.services.addic7ed import Addic7edService
from resources.lib import subtitles


class TestSubtitleModels(unittest.TestCase):
    def test_video_meta_initialization(self):
        meta = VideoMeta(
            title="His Butler, Friendly",
            tvshow="Black Butler: Emerald Witch Arc",
            original_title="Kuroshitsuji: Midori no Majo-hen",
            season=5,
            episode=3,
            year=2024,
            imdb_id="tt1316554",
            filename="Black Butler Emerald Witch Arc - S05E03.mkv",
            preferred_lang="eng"
        )
        self.assertEqual(meta.tvshow, "Black Butler: Emerald Witch Arc")
        self.assertEqual(meta.season, "5")
        self.assertEqual(meta.episode, "3")
        self.assertEqual(meta.imdb_id, "tt1316554")
        self.assertEqual(meta.imdb_id_int, "1316554")
        self.assertTrue(meta.is_tvshow)
        self.assertFalse(meta.is_movie)
        self.assertEqual(meta.filename_without_ext, "Black Butler Emerald Witch Arc - S05E03")

    def test_video_meta_imdb_normalization(self):
        meta1 = VideoMeta(imdb_id="1316554")
        self.assertEqual(meta1.imdb_id, "tt1316554")
        self.assertEqual(meta1.imdb_id_int, "1316554")

        meta2 = VideoMeta(imdb_id="")
        self.assertEqual(meta2.imdb_id, "")
        self.assertEqual(meta2.imdb_id_int, "")

    def test_subtitle_result_to_dict(self):
        sub = SubtitleResult(
            service_name="opensubtitles",
            display_name="OpenSubtitles",
            name="Black.Butler.S05E03.1080p.srt",
            lang="English",
            lang_code="en",
            download_url="https://api.opensubtitles.com/api/v1/download",
            impaired=True,
            season=5,
            episode=3
        )
        d = sub.to_dict()
        self.assertEqual(d['service_name'], 'opensubtitles')
        self.assertEqual(d['impaired'], 'true')
        self.assertEqual(d['lang_code'], 'en')


class TestSubtitleLanguages(unittest.TestCase):
    def test_iso_conversions(self):
        self.assertEqual(languages.to_iso639_1("English"), "en")
        self.assertEqual(languages.to_iso639_1("eng"), "en")
        self.assertEqual(languages.to_iso639_1("Spanish"), "es")
        self.assertEqual(languages.to_iso639_1("Japanese"), "ja")

        self.assertEqual(languages.to_iso639_2("English"), "eng")
        self.assertEqual(languages.to_iso639_2("en"), "eng")

        self.assertEqual(languages.to_english_name("en"), "English")
        self.assertEqual(languages.to_english_name("spa"), "Spanish")

    def test_map_languages(self):
        langs = ["English", "Spanish", "English", "eng"]
        codes = languages.map_languages_to_iso639_1(langs)
        self.assertEqual(codes, ["en", "es"])

    def test_is_language_match(self):
        self.assertTrue(languages.is_language_match("en", "English"))
        self.assertTrue(languages.is_language_match("Spanish", "spa"))
        self.assertTrue(languages.is_language_match("es", "spa"))
        self.assertFalse(languages.is_language_match("es", "eng"))
        self.assertTrue(languages.is_language_match("none", "none"))
        self.assertFalse(languages.is_language_match("none", "en"))
        self.assertFalse(languages.is_language_match("", "en"))

    @patch('resources.lib.ui.control.getInt')
    def test_get_preferred_subtitle_language(self, mock_get_int):
        mock_get_int.return_value = 0
        self.assertEqual(languages.get_preferred_subtitle_language(), "none")

        mock_get_int.return_value = 1
        self.assertEqual(languages.get_preferred_subtitle_language(), "en")

        mock_get_int.return_value = 3
        self.assertEqual(languages.get_preferred_subtitle_language(), "es")



class TestSubtitleEncoding(unittest.TestCase):
    def test_utf8_detection_and_transcoding(self):
        text = "1\n00:00:01,000 --> 00:00:04,000\nHello, world!\n"
        raw = text.encode('utf-8')
        decoded, enc = encoding.fix_subtitle_encoding(raw)
        self.assertEqual(decoded, text)
        self.assertEqual(enc, 'utf-8')

    def test_bom_stripping(self):
        text = "1\n00:00:01,000 --> 00:00:04,000\nTest with BOM\n"
        raw = b'\xef\xbb\xbf' + text.encode('utf-8')
        decoded, enc = encoding.fix_subtitle_encoding(raw)
        self.assertEqual(decoded, text)
        self.assertFalse(decoded.startswith('\ufeff'))

    def test_cp1252_fallback(self):
        text = "Café résumé — dialogue"
        raw = text.encode('cp1252')
        decoded, enc = encoding.fix_subtitle_encoding(raw, use_chardet=False)
        self.assertIn("Café", decoded)


class TestArchiveExtractionStrictness(unittest.TestCase):
    def test_zip_exact_episode_extraction(self):
        # Create a mock zip with multiple episodes
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr("Black.Butler.S05E01.eng.ass", "Dialogue: Ep 1")
            zf.writestr("Black.Butler.S05E03.eng.ass", "Dialogue: Ep 3 Sullivan Foot")
            zf.writestr("Black.Butler.S05E05.eng.ass", "Dialogue: Ep 5 Emerald Castle")
        zip_bytes = buf.getvalue()

        # Request Ep 3
        extracted, inner_name = archive.extract_subtitle_from_archive(
            zip_bytes,
            filename="pack.zip",
            episode_number="3",
            season_number="5"
        )
        self.assertEqual(extracted.decode('utf-8'), "Dialogue: Ep 3 Sullivan Foot")
        self.assertEqual(inner_name, "Black.Butler.S05E03.eng.ass")

    def test_zip_raises_on_missing_episode(self):
        # Create zip that only has Ep 1 and Ep 5
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr("Black.Butler.S05E01.eng.ass", "Dialogue: Ep 1")
            zf.writestr("Black.Butler.S05E05.eng.ass", "Dialogue: Ep 5")
        zip_bytes = buf.getvalue()

        # Request Ep 3 -> should raise ArchiveEpisodeMismatchError instead of grabbing Ep 1 or 5
        with self.assertRaises(archive.ArchiveEpisodeMismatchError):
            archive.extract_subtitle_from_archive(
                zip_bytes,
                filename="pack.zip",
                episode_number="3",
                season_number="5"
            )

    def test_gzip_extraction(self):
        raw_text = "Dialogue: Gzip subtitle"
        compressed = gzip.compress(raw_text.encode('utf-8'))
        extracted, inner_name = archive.extract_subtitle_from_archive(
            compressed,
            filename="test.srt.gz"
        )
        self.assertEqual(extracted.decode('utf-8'), raw_text)
        self.assertEqual(inner_name, "test.srt")


class TestSubtitleSearchRanking(unittest.TestCase):
    def setUp(self):
        self.meta = VideoMeta(
            tvshow="Black Butler",
            season=5,
            episode=3,
            preferred_lang="en"
        )
        self.settings = {
            'subtitles.prefer_sdh': False,
            'subtitles.prefer_forced': False,
        }

    def test_exact_episode_beats_season_pack(self):
        exact_sub = SubtitleResult(
            service_name="subdl",
            display_name="SubDL",
            name="Black.Butler.S05E03.1080p.srt",
            lang="English",
            lang_code="en",
            season=5,
            episode=3
        )
        season_pack = SubtitleResult(
            service_name="subdl",
            display_name="SubDL",
            name="Black.Butler.S05.Complete.srt",
            lang="English",
            lang_code="en",
            season=5,
            episode=None
        )

        score_exact = search.score_result(exact_sub, self.meta, self.settings)
        score_pack = search.score_result(season_pack, self.meta, self.settings)

        self.assertGreater(score_exact, score_pack)
        self.assertGreater(exact_sub.score, season_pack.score)

    def test_mismatched_episode_penalized(self):
        wrong_sub = SubtitleResult(
            service_name="subdl",
            display_name="SubDL",
            name="Black.Butler.S05E05.srt",
            lang="English",
            lang_code="en",
            season=5,
            episode=5
        )
        score_wrong = search.score_result(wrong_sub, self.meta, self.settings)
        self.assertLess(score_wrong, 0.5)

    def test_sdh_preference_toggle(self):
        sdh_sub = SubtitleResult(
            service_name="opensubtitles",
            display_name="OpenSubtitles",
            name="Show.S05E03.SDH.srt",
            lang="English",
            lang_code="en",
            impaired=True,
            season=5,
            episode=3
        )
        # When prefer_sdh = True
        score_pref = search.score_result(sdh_sub, self.meta, {'subtitles.prefer_sdh': True, 'subtitles.prefer_forced': False})
        # When prefer_sdh = False
        score_no_pref = search.score_result(sdh_sub, self.meta, {'subtitles.prefer_sdh': False, 'subtitles.prefer_forced': False})
        self.assertGreater(score_pref, score_no_pref)

    def test_search_all_services_returns_empty_when_lang_none(self):
        meta_none = VideoMeta(
            tvshow="Black Butler",
            season=5,
            episode=3,
            preferred_lang="none"
        )
        results = search.search_all_services(meta_none, {})
        self.assertEqual(results, [])

    @patch('resources.lib.subtitles.search.ALL_SERVICES')
    def test_search_all_services_filters_non_preferred_languages(self, mock_services):
        mock_service = MagicMock()
        mock_service.search.return_value = [
            SubtitleResult(service_name="mock", display_name="Mock", name="es.srt", lang="Spanish", lang_code="es", season=5, episode=3),
            SubtitleResult(service_name="mock", display_name="Mock", name="en.srt", lang="English", lang_code="en", season=5, episode=3),
            SubtitleResult(service_name="mock", display_name="Mock", name="fr.srt", lang="French", lang_code="fr", season=5, episode=3),
        ]
        mock_services.items.return_value = [('mock', mock_service)]

        meta_es = VideoMeta(tvshow="Black Butler", season=5, episode=3, preferred_lang="es")
        results = search.search_all_services(meta_es, {'subtitles.provider.mock': True})

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "es.srt")
        self.assertEqual(results[0].lang_code, "es")



class TestProviderImplementations(unittest.TestCase):
    @patch('resources.lib.ui.client.get')
    def test_subdl_search(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'subtitles': [
                {
                    'release_name': 'Black.Butler.S05E03.HDTV.srt',
                    'url': '/subtitle/12345.zip',
                    'language': 'en',
                    'hi': False,
                    'season': 5,
                    'episode': 3,
                }
            ]
        }
        mock_get.return_value = mock_resp

        meta = VideoMeta(tvshow="Black Butler", season=5, episode=3)
        settings = {'subtitles.subdl.apikey': 'test_key', 'subtitles.timeout': 10}
        results = SubDLService.search(meta, settings)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, 'Black.Butler.S05E03.HDTV.srt')
        self.assertEqual(results[0].service_name, 'subdl')
        self.assertEqual(results[0].season, 5)
        self.assertEqual(results[0].episode, 3)

    @patch('resources.lib.ui.client.get')
    def test_podnadpisi_search(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'data': [
                {
                    'publish_id': 'abc1234',
                    'custom_releases': ['Black.Butler.S05E03.720p'],
                    'language': 'en',
                    'flags': []
                }
            ]
        }
        mock_get.return_value = mock_resp

        meta = VideoMeta(tvshow="Black Butler", season=5, episode=3)
        settings = {'subtitles.timeout': 10}
        results = PodnadpisiService.search(meta, settings)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].service_name, 'podnadpisi')
        self.assertIn('abc1234', results[0].download_url)


class TestNativeSubtitlesIntegration(unittest.TestCase):
    def test_settings_retrieval(self):
        settings = subtitles.get_subtitles_settings()
        self.assertIn('subtitles.enabled', settings)
        self.assertIn('subtitles.auto_search', settings)
        self.assertIn('subtitles.auto_download', settings)
        self.assertIn('subtitles.provider.opensubtitles', settings)
        self.assertIn('subtitles.provider.subdl', settings)

    @patch('resources.lib.subtitles.search_subtitles')
    @patch('resources.lib.subtitles.download_subtitle')
    @patch('xbmc.Player')
    def test_auto_download_subtitles_flow(self, mock_player_cls, mock_download, mock_search):
        mock_player = MagicMock()
        mock_player.isPlaying.return_value = True
        mock_player_cls.return_value = mock_player

        cand = SubtitleResult(
            service_name="subdl",
            display_name="SubDL",
            name="Black.Butler.S05E03.srt",
            lang="English",
            lang_code="en"
        )
        mock_search.return_value = [cand]
        mock_download.return_value = "/mock/temp/subtitles/Black_Butler_S05E03.en.srt"

        meta = VideoMeta(tvshow="Black Butler", season=5, episode=3)
        settings = {
            'subtitles.enabled': True,
            'subtitles.auto_search': True,
            'subtitles.auto_download': True,
        }

        success = subtitles.auto_download_subtitles(meta=meta, settings=settings)
        self.assertTrue(success)
        mock_player.setSubtitles.assert_called_once_with("/mock/temp/subtitles/Black_Butler_S05E03.en.srt")
        mock_player.showSubtitles.assert_called_once_with(True)

    def test_auto_download_skips_when_lang_none(self):
        meta_none = VideoMeta(tvshow="Black Butler", season=5, episode=3, preferred_lang="none")
        success = subtitles.auto_download_subtitles(meta=meta_none, settings={'subtitles.enabled': True})
        self.assertFalse(success)

    @patch('resources.lib.subtitles.search_subtitles')
    @patch('resources.lib.subtitles.download_subtitle')
    def test_auto_download_skips_candidate_with_different_language(self, mock_download, mock_search):
        cand_fr = SubtitleResult(
            service_name="subdl",
            display_name="SubDL",
            name="Black.Butler.S05E03.fr.srt",
            lang="French",
            lang_code="fr"
        )
        mock_search.return_value = [cand_fr]
        meta_es = VideoMeta(tvshow="Black Butler", season=5, episode=3, preferred_lang="es")
        settings = {'subtitles.enabled': True, 'subtitles.auto_search': True, 'subtitles.auto_download': True}

        success = subtitles.auto_download_subtitles(meta=meta_es, settings=settings)
        self.assertFalse(success)
        mock_download.assert_not_called()

    @patch('resources.lib.ui.control.getInt')
    def test_get_meta_from_dict_preferred_language(self, mock_get_int):
        # 0 = "none"
        mock_get_int.return_value = 0
        video_info = {'title': 'Attack on Titan', 'season': 1, 'episode': 1}
        meta_0 = sub_meta.get_meta_from_dict(video_info)
        self.assertEqual(meta_0.preferred_lang, "none")
        self.assertEqual(meta_0.languages, [])

        # 3 = "Spanish"
        mock_get_int.return_value = 3
        meta_3 = sub_meta.get_meta_from_dict(video_info)
        self.assertEqual(meta_3.preferred_lang, "es")
        self.assertEqual(meta_3.languages, ["Spanish"])



if __name__ == '__main__':
    unittest.main()