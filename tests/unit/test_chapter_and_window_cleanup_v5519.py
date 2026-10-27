import unittest
from unittest.mock import MagicMock, patch

from resources.lib.ui import control, source_utils
from resources.lib.ui.player import WatchlistPlayer
from resources.lib.windows.base_window import BaseWindow


class TestChapterAndWindowCleanupV5519(unittest.TestCase):
    def setUp(self):
        control.clearSettingsCache()

    def tearDown(self):
        control.cleanup()

    # ── Group 1: Chapter Matching & Scoring Engine ──────────────────────────

    def test_prologue_and_cold_open_not_matched_as_intro(self):
        """Verify prologue and cold open chapters are never treated as opening theme songs."""
        self.assertFalse(source_utils.chapter_title_matches_intro('Prologue'))
        self.assertFalse(source_utils.chapter_title_matches_intro('prologue'))
        self.assertFalse(source_utils.chapter_title_matches_intro('序章'))
        self.assertFalse(source_utils.chapter_title_matches_intro('Cold Open'))
        self.assertFalse(source_utils.chapter_title_matches_intro('Story Scene'))

        # Legitimate opening markers must still match
        self.assertTrue(source_utils.chapter_title_matches_intro('Opening'))
        self.assertTrue(source_utils.chapter_title_matches_intro('opening'))
        self.assertTrue(source_utils.chapter_title_matches_intro('OP'))
        self.assertTrue(source_utils.chapter_title_matches_intro('op1'))
        self.assertTrue(source_utils.chapter_title_matches_intro('ncop'))
        self.assertTrue(source_utils.chapter_title_matches_intro('オープニング'))
        self.assertTrue(source_utils.chapter_title_matches_intro('TV-Size OP'))
        self.assertTrue(source_utils.chapter_title_matches_intro('Intro'))

    def test_score_intro_chapter_durations_and_confidence(self):
        """Verify score_intro_chapter prefers explicit OP markers and standard ~90s OP duration."""
        # Explicit OP with standard 90s length
        score_op_90 = source_utils.score_intro_chapter('Opening', 90.0)
        # Generic intro with standard 90s length
        score_intro_90 = source_utils.score_intro_chapter('Intro', 90.0)
        # Non-matching chapter
        score_prologue = source_utils.score_intro_chapter('Prologue', 90.0)

        self.assertGreater(score_op_90, score_intro_90)
        self.assertEqual(score_prologue, 0)
        self.assertGreaterEqual(score_op_90, 120)  # 100 base + 30 duration bonus

    def test_tanya_chapters_prefers_opening_over_prologue(self):
        """
        Verify that for Tanya S2E7 chapters:
        ['Prologue', 'Opening', 'Episode', 'Ending', 'Preview'],
        Opening (104-194s) is chosen as the intro instead of Prologue (0-104s).
        """
        p = WatchlistPlayer()
        p.skipintro_aniskip_enable = True
        p.skipoutro_aniskip_enable = True
        p.skipintro_offset = -3
        p.skipoutro_offset = -3
        p.total_time = 1420

        p.ffprobe_chapters = [
            {'title': 'Prologue', 'start': 0.0, 'end': 104.0},
            {'title': 'Opening', 'start': 104.0, 'end': 194.0},
            {'title': 'Episode', 'start': 194.0, 'end': 1297.0},
            {'title': 'Ending', 'start': 1297.0, 'end': 1387.0},
            {'title': 'Preview', 'start': 1387.0, 'end': 1420.0},
        ]

        with patch('resources.lib.ui.control.getBool', return_value=True):
            p.process_ffprobe_chapter_skips()

        self.assertTrue(p.skipintro_aniskip)
        # Intro must be Opening (104 - 3 = 101s to 194 - 3 = 191s), NOT Prologue (0 to 104s)
        self.assertEqual(p.skipintro_start, 101)
        self.assertEqual(p.skipintro_end, 191)

        # Outro must be Ending (1297 - 3 = 1294s to 1387 - 3 = 1384s)
        self.assertTrue(p.skipoutro_aniskip)
        self.assertEqual(p.skipoutro_start, 1294)
        self.assertEqual(p.skipoutro_end, 1384)

    # ── Group 2: Auto-Skip Logging & Execution ──────────────────────────────

    def test_auto_skip_logs_at_info_level(self):
        """Verify auto-skip logs intro seek events at INFO level for user visibility."""
        p = WatchlistPlayer()
        p.skipintro_aniskip_enable = True
        p.skipintro_aniskip_auto = True
        p.skipintro_aniskip = True
        p.skipintro_start = 100
        p.skipintro_end = 190
        p.total_time = 1400
        p.current_time = 100
        p.updated = True
        p.skipoutro_aniskip = True
        p.skipoutro_start = 0  # outro handled

        def fake_seek(target):
            p._playback_stopped = True

        with patch.object(p, 'seekTime', side_effect=fake_seek) as mock_seek, \
             patch.object(p, 'getTime', return_value=100), \
             patch.object(p, 'getTotalTime', return_value=1400), \
             patch('resources.lib.ui.control.log') as mock_log, \
             patch.object(p, 'isPlaying', return_value=True), \
             patch('xbmc.getCondVisibility', return_value=False), \
             patch('xbmc.sleep'):
            p._run_unified_episode_monitor()

            mock_seek.assert_called_with(190)
            mock_log.assert_any_call('Auto-skipped intro: 100-190', 'info')

    # ── Group 3: WindowXMLDialog Cleanup & Leak Prevention ──────────────────

    def test_base_window_tracking_and_cleanup_all(self):
        """Verify BaseWindow tracks active instances and cleans them up cleanly."""
        win = BaseWindow('test.xml', control.ADDON_PATH, actionArgs={'item_type': 'skip_intro'})
        self.assertIn(win, BaseWindow._active_windows)

        BaseWindow.cleanup_all()
        self.assertEqual(len(BaseWindow._active_windows), 0)

    def test_source_select_breaks_close_callback_cycle(self):
        """Verify SourceSelect.resolve_item pops actionArgs['close'] in finally block."""
        from resources.lib.windows.source_select import SourceSelect
        mock_args = {'mal_id': 123, 'close': 'dummy'}
        win = SourceSelect('source_select.xml', control.ADDON_PATH, actionArgs=mock_args, sources=[])
        win.position = 0
        win.displayed_sources = [{'release_title': 'Test Episode', 'debrid_provider': 'Real-Debrid'}]

        with patch('resources.lib.windows.source_select.Resolver') as mock_resolver:
            mock_inst = MagicMock()
            mock_inst.doModal.return_value = None
            mock_resolver.return_value = mock_inst

            win.resolve_item()

            # 'close' callback must be popped from actionArgs to avoid cyclic leak
            self.assertNotIn('close', win.actionArgs)
            mock_inst.close.assert_called()


if __name__ == '__main__':
    unittest.main()
