"""test_subtitles.py - Unit tests for intelligent subtitle selection and scoring.
"""

import unittest
from unittest.mock import MagicMock, patch

from resources.lib.ui.player import (
    score_subtitle_stream,
    select_subtitle_stream,
    WatchlistPlayer,
    SIGNS_SUBTITLE_KEYWORDS,
    DIALOG_SUBTITLE_KEYWORDS,
)


class TestSubtitleScoring(unittest.TestCase):
    """Test suite for score_subtitle_stream and select_subtitle_stream heuristics."""

    def setUp(self):
        # Typical dual-audio Matroska stream layout
        self.dual_audio_streams = [
            {
                "index": 0,
                "language": "eng",
                "name": "Signs & Songs",
                "isdefault": True,
                "isforced": False,
                "isimpaired": False,
            },
            {
                "index": 1,
                "language": "eng",
                "name": "English",
                "isdefault": False,
                "isforced": False,
                "isimpaired": False,
            },
        ]

    def test_signs_and_dialog_keywords_defined(self):
        """Ensure core keywords are present for detection."""
        self.assertIn("signs", SIGNS_SUBTITLE_KEYWORDS)
        self.assertIn("songs", SIGNS_SUBTITLE_KEYWORDS)
        self.assertIn("s&s", SIGNS_SUBTITLE_KEYWORDS)
        self.assertIn("forced", SIGNS_SUBTITLE_KEYWORDS)

        self.assertIn("dialogue", DIALOG_SUBTITLE_KEYWORDS)
        self.assertIn("dialog", DIALOG_SUBTITLE_KEYWORDS)
        self.assertIn("full", DIALOG_SUBTITLE_KEYWORDS)
        self.assertIn("main", DIALOG_SUBTITLE_KEYWORDS)

    def test_dialog_mode_avoids_isdefault_trap(self):
        """
        Verify that in 'dialog' mode, a clean English track (Track 1) beats
        Track 0 ('Signs & Songs') even though Track 0 is flagged isdefault=True.
        """
        score_0 = score_subtitle_stream(self.dual_audio_streams[0], target_mode="dialog", preferred_lang="eng")
        score_1 = score_subtitle_stream(self.dual_audio_streams[1], target_mode="dialog", preferred_lang="eng")

        self.assertGreater(score_1, score_0)
        selected = select_subtitle_stream(self.dual_audio_streams, target_mode="dialog", preferred_lang="eng")
        self.assertEqual(selected, 1)

    def test_signs_mode_selects_signs_track(self):
        """Verify that in 'signs' mode, Track 0 ('Signs & Songs') is selected."""
        score_0 = score_subtitle_stream(self.dual_audio_streams[0], target_mode="signs", preferred_lang="eng")
        score_1 = score_subtitle_stream(self.dual_audio_streams[1], target_mode="signs", preferred_lang="eng")

        self.assertGreater(score_0, score_1)
        selected = select_subtitle_stream(self.dual_audio_streams, target_mode="signs", preferred_lang="eng")
        self.assertEqual(selected, 0)

    def test_explicit_dialog_name_prioritization(self):
        """Verify explicit 'Full Dialogue' beats neutral 'English' and deprioritizes SDH."""
        streams = [
            {"index": 0, "language": "eng", "name": "Signs", "isdefault": False, "isforced": True},
            {"index": 1, "language": "eng", "name": "English", "isdefault": False, "isforced": False},
            {"index": 2, "language": "eng", "name": "Full Dialogue", "isdefault": False, "isforced": False},
            {"index": 3, "language": "eng", "name": "English [SDH]", "isdefault": False, "isimpaired": True},
        ]

        selected = select_subtitle_stream(streams, target_mode="dialog", preferred_lang="eng")
        self.assertEqual(selected, 2)

    def test_custom_keyword_matching(self):
        """Verify custom keyword mode rewards matching streams."""
        streams = [
            {"index": 0, "language": "eng", "name": "[Commie] English", "isdefault": True},
            {"index": 1, "language": "eng", "name": "[Erai-raws] English", "isdefault": False},
        ]

        selected = select_subtitle_stream(streams, target_mode="custom", preferred_lang="eng", custom_keyword="Erai-raws")
        self.assertEqual(selected, 1)

        selected_commie = select_subtitle_stream(streams, target_mode="custom", preferred_lang="eng", custom_keyword="commie")
        self.assertEqual(selected_commie, 0)

    def test_language_preference_priority(self):
        """Verify matching language stream is chosen over non-matching language stream."""
        streams = [
            {"index": 0, "language": "spa", "name": "Español Completo", "isdefault": True},
            {"index": 1, "language": "eng", "name": "English Full", "isdefault": False},
        ]

        selected = select_subtitle_stream(streams, target_mode="dialog", preferred_lang="eng")
        self.assertEqual(selected, 1)

    def test_empty_and_single_stream_safety(self):
        """Verify safe handling of empty lists and single tracks."""
        self.assertIsNone(select_subtitle_stream([]))

        single = [{"index": 0, "language": "eng", "name": "", "isdefault": True}]
        self.assertEqual(select_subtitle_stream(single, target_mode="dialog", preferred_lang="eng"), 0)


class TestWatchlistPlayerAudioSubtitles(unittest.TestCase):
    """Test setup_audio_and_subtitles integration on WatchlistPlayer."""

    def setUp(self):
        self.player = WatchlistPlayer()
        self.player.setAudioStream = MagicMock()
        self.player.setSubtitleStream = MagicMock()
        self.player.showSubtitles = MagicMock()

    @patch("resources.lib.ui.control.getBool")
    @patch("resources.lib.ui.control.getInt")
    @patch("resources.lib.ui.control.jsonrpc")
    def test_dialog_mode_with_english_dub_and_dubsubtitles_true(self, mock_jsonrpc, mock_getInt, mock_getBool):
        """
        User Preference Test:
        - Audio: English (Dub)
        - Subtitles: Dialog (1)
        - general.dubsubtitles: True
        Otaku MUST select Track 1 (English Full Dialogue) and showSubtitles(True).
        """
        mock_jsonrpc.return_value = {
            "result": {
                "audiostreams": [
                    {"index": 0, "language": "jpn", "name": "Japanese 2.0", "isdefault": False},
                    {"index": 1, "language": "eng", "name": "English 5.1", "isdefault": True},
                ],
                "subtitles": [
                    {"index": 0, "language": "eng", "name": "Signs & Songs", "isdefault": True, "isforced": False},
                    {"index": 1, "language": "eng", "name": "English", "isdefault": False, "isforced": False},
                ],
            }
        }

        # Settings
        mock_getBool.side_effect = lambda setting: {
            "general.kodi_language": False,
            "general.subtitles.keyword": True,
            "general.subtitles.type": True,
            "general.dubsubtitles": True,
        }.get(setting, False)

        self.player.preferred_audio = 1  # 'eng'
        self.player.preferred_subtitle_setting = 1  # 'eng'
        self.player.preferred_subtitle_type = 0  # 'isdefault'
        self.player.preferred_subtitle_keyword = 1  # Option 1: 'Dialog'

        self.player.setup_audio_and_subtitles()

        # Should set English audio (index 1)
        self.player.setAudioStream.assert_called_with(1)
        # Should select Full Dialogue (index 1), NOT Signs & Songs (index 0)
        self.player.setSubtitleStream.assert_called_with(1)
        # Should show subtitles because general.dubsubtitles is True
        self.player.showSubtitles.assert_called_with(True)

    @patch("resources.lib.ui.control.getBool")
    @patch("resources.lib.ui.control.getInt")
    @patch("resources.lib.ui.control.jsonrpc")
    def test_smart_pair_mode_with_english_audio(self, mock_jsonrpc, mock_getInt, mock_getBool):
        """
        Smart Pair Test on English Dub:
        - Audio: English
        - Subtitles Keyword: 4 (Smart Pair)
        - general.dubsubtitles: True
        Otaku MUST select Track 0 (Signs & Songs) for English audio.
        """
        mock_jsonrpc.return_value = {
            "result": {
                "audiostreams": [
                    {"index": 0, "language": "eng", "name": "English 2.0", "isdefault": True},
                ],
                "subtitles": [
                    {"index": 0, "language": "eng", "name": "Signs & Songs", "isdefault": True, "isforced": False},
                    {"index": 1, "language": "eng", "name": "English", "isdefault": False, "isforced": False},
                ],
            }
        }

        mock_getBool.side_effect = lambda setting: {
            "general.kodi_language": False,
            "general.subtitles.keyword": True,
            "general.subtitles.type": True,
            "general.dubsubtitles": True,
        }.get(setting, False)

        self.player.preferred_audio = 1  # 'eng'
        self.player.preferred_subtitle_setting = 1  # 'eng'
        self.player.preferred_subtitle_type = 0
        self.player.preferred_subtitle_keyword = 4  # Option 4: 'Smart Pair'

        self.player.setup_audio_and_subtitles()

        self.player.setSubtitleStream.assert_called_with(0)
        self.player.showSubtitles.assert_called_with(True)

    @patch("resources.lib.ui.control.getBool")
    @patch("resources.lib.ui.control.getInt")
    @patch("resources.lib.ui.control.jsonrpc")
    def test_smart_pair_mode_with_japanese_audio(self, mock_jsonrpc, mock_getInt, mock_getBool):
        """
        Smart Pair Test on Japanese Audio:
        - Audio: Japanese
        - Subtitles Keyword: 4 (Smart Pair)
        Otaku MUST select Track 1 (Full Dialogue) for Japanese audio.
        """
        mock_jsonrpc.return_value = {
            "result": {
                "audiostreams": [
                    {"index": 0, "language": "jpn", "name": "Japanese 2.0", "isdefault": True},
                ],
                "subtitles": [
                    {"index": 0, "language": "eng", "name": "Signs & Songs", "isdefault": True, "isforced": False},
                    {"index": 1, "language": "eng", "name": "English", "isdefault": False, "isforced": False},
                ],
            }
        }

        mock_getBool.side_effect = lambda setting: {
            "general.kodi_language": False,
            "general.subtitles.keyword": True,
            "general.subtitles.type": True,
            "general.dubsubtitles": False,
        }.get(setting, False)

        self.player.preferred_audio = 0  # 'jpn'
        self.player.preferred_subtitle_setting = 1  # 'eng'
        self.player.preferred_subtitle_type = 0
        self.player.preferred_subtitle_keyword = 4  # Option 4: 'Smart Pair'

        self.player.setup_audio_and_subtitles()

        self.player.setSubtitleStream.assert_called_with(1)
        self.player.showSubtitles.assert_called_with(True)

    @patch("resources.lib.ui.control.getBool")
    @patch("resources.lib.ui.control.getInt")
    @patch("resources.lib.ui.control.jsonrpc")
    def test_dubsubtitles_disabled_hides_subtitles(self, mock_jsonrpc, mock_getInt, mock_getBool):
        """Verify that when general.dubsubtitles is False, showSubtitles(False) is called on English Dub."""
        mock_jsonrpc.return_value = {
            "result": {
                "audiostreams": [
                    {"index": 0, "language": "eng", "name": "English", "isdefault": True},
                ],
                "subtitles": [
                    {"index": 0, "language": "eng", "name": "English", "isdefault": True},
                ],
            }
        }

        mock_getBool.side_effect = lambda setting: {
            "general.kodi_language": False,
            "general.subtitles.keyword": True,
            "general.subtitles.type": True,
            "general.dubsubtitles": False,  # OFF
        }.get(setting, False)

        self.player.preferred_audio = 1
        self.player.preferred_subtitle_setting = 1
        self.player.preferred_subtitle_type = 0
        self.player.preferred_subtitle_keyword = 1

        self.player.setup_audio_and_subtitles()

        self.player.showSubtitles.assert_called_with(False)


if __name__ == "__main__":
    unittest.main()
