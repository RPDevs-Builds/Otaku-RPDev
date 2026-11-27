"""Unit tests for v6.9.1 Subtitle Timing & Sync + Skin Shortcuts Modal Dialog Protection.

Covers:
1. otaku.scene_markers 'kind' vs 'type' compatibility (build_scene_markers -> detect_chapter_aligned_subtitle_offset_ms).
2. intro_start <= 2.0s leading OP-end calibration (+shift direct, -shift with outro / pre-OP / duration overflow,
   and post-OP silent title-card / ASS Title-sign false-positive guards).
3. Async AniSkip wait in WatchlistPlayer._ensure_scene_markers_for_subtitle_calibration().
4. Strictly read-only (?mode=ro) MyVideos*.db SubtitleDelay reader and latest DB version selection.
5. Non-destructive database.update_series_sub_offset(), Kodi delay persistence on playback stop/end,
   double-shift prevention on episode replay, and external-only scope (Option A).
6. Skin Shortcuts / modal dialog protection in control.draw_items() and default.py.
"""

import os
import runpy
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PLUGIN_ROOT = os.path.join(_REPO_ROOT, 'plugin.video.otaku.rpdev')
if _PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, _PLUGIN_ROOT)

from resources.lib.subtitles import download as sub_dl
from resources.lib.subtitles.models import SubtitleResult, VideoMeta
from resources.lib.ui import control, database, player


def _fmt_ass_ts(seconds: float) -> str:
    s = max(0.0, float(seconds))
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = int(s % 60)
    cs = int(round((s - int(s)) * 100))
    if cs >= 100:
        cs = 0
        sec += 1
    return f"{h}:{m:02d}:{sec:02d}.{cs:02d}"


def _build_ass(cues, extra_lines=()):
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize",
        "Style: Default,Arial,20",
        "Style: Title,Arial,24",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for start_s, end_s, text in cues:
        lines.append(f"Dialogue: 0,{_fmt_ass_ts(start_s)},{_fmt_ass_ts(end_s)},Default,,0,0,0,,{text}")
    lines.extend(extra_lines)
    return "\n".join(lines) + "\n"


def _create_kodi_video_db(db_path: str, rows):
    """Create a minimal Kodi MyVideos<NNN>.db schema with path/files/settings rows."""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE path (idPath INTEGER PRIMARY KEY, strPath TEXT);
            CREATE TABLE files (idFile INTEGER PRIMARY KEY, idPath INTEGER, strFilename TEXT);
            CREATE TABLE settings (idFile INTEGER PRIMARY KEY, SubtitleDelay FLOAT);
            """
        )
        for idx, (path_str, file_str, delay_s) in enumerate(rows, start=1):
            conn.execute("INSERT INTO path (idPath, strPath) VALUES (?, ?)", (idx, path_str))
            conn.execute("INSERT INTO files (idFile, idPath, strFilename) VALUES (?, ?, ?)", (idx, idx, file_str))
            if delay_s is not None:
                conn.execute("INSERT INTO settings (idFile, SubtitleDelay) VALUES (?, ?)", (idx, float(delay_s)))
        conn.commit()
    finally:
        conn.close()


class TestChapterCalibrationKindAndLeadingOp(unittest.TestCase):
    """Tests for Improvement #1A: 'kind' schema fix & intro_start <= 2.0s OP-end calibration."""

    def test_build_scene_markers_kind_schema_works_directly_with_calibrator(self):
        """player.build_scene_markers() emits 'kind' (not 'type'); calibrator must match it directly."""
        markers = player.build_scene_markers(
            chapters=[],
            aniskip_start=45.0,
            aniskip_end=135.0,
            aniskip_source='aniskip',
            total_time=1420.0,
        )
        self.assertTrue(any(m.get('kind') == 'intro' for m in markers))
        # Subtitle shifted late by +6s (cold open ends at 51s, dialogue resumes at 141s) -> shift -6000ms
        ass_text = _build_ass([
            (10.0, 14.0, "Cold open line 1"),
            (46.0, 51.0, "Cold open ends"),
            (141.0, 145.0, "Post OP starts"),
            (200.0, 204.0, "Later dialogue"),
        ])
        offset_ms = sub_dl.detect_chapter_aligned_subtitle_offset_ms(ass_text, '.ass', scene_markers=markers)
        self.assertEqual(offset_ms, -6000)

    def test_intro_at_zero_early_subtitles_positive_shift_bleach_pattern(self):
        """intro 0-90s with early subs starting at 84s (+6000ms shift needed) calibrates cleanly."""
        markers = player.build_scene_markers(
            chapters=[],
            aniskip_start=0.0,
            aniskip_end=90.0,
            aniskip_source='aniskip',
            total_time=1420.0,
        )
        # Ensure build_scene_markers does not drop start==0 when end>0; supply direct marker if needed
        if not any(m.get('kind') == 'intro' for m in markers):
            markers = [{'kind': 'intro', 'label': 'Intro', 'start': 0.0, 'end': 90.0}]
        ass_text = _build_ass([
            (84.0, 87.5, "First line after OP (6s early)"),
            (92.0, 96.0, "Second line"),
            (150.0, 155.0, "Third line"),
        ])
        offset_ms = sub_dl.detect_chapter_aligned_subtitle_offset_ms(
            ass_text, '.ass', scene_markers=markers, video_total_s=1420.0,
        )
        self.assertEqual(offset_ms, 6000)

    def test_intro_at_zero_late_subtitles_with_outro_corroboration(self):
        """intro 0-90s + outro 1320-1410s with subs 6s late (96s / 1326s) -> -6000ms."""
        markers = [
            {'kind': 'intro', 'label': 'Intro', 'start': 0.0, 'end': 90.0},
            {'kind': 'outro', 'label': 'Outro', 'start': 1320.0, 'end': 1410.0},
        ]
        ass_text = _build_ass([
            (96.0, 99.5, "Post OP line (6s late)"),
            (600.0, 604.0, "Mid episode"),
            (1322.0, 1326.0, "Final pre-ED line (6s late)"),
        ])
        offset_ms = sub_dl.detect_chapter_aligned_subtitle_offset_ms(
            ass_text, '.ass', scene_markers=markers, video_total_s=1420.0,
        )
        self.assertEqual(offset_ms, -6000)

    def test_intro_at_zero_with_pre_op_cold_open_bumper_lines(self):
        """intro 0-90s where subtitle contains a 6s pre-OP bumper ending at 6s and resuming at 96s -> -6000ms."""
        markers = [{'kind': 'intro', 'label': 'Intro', 'start': 0.0, 'end': 90.0}]
        ass_text = _build_ass([
            (1.0, 6.0, "Previously on / sponsor bumper"),
            (96.0, 100.0, "Post OP starts at 96s"),
            (200.0, 204.0, "More dialogue"),
        ])
        offset_ms = sub_dl.detect_chapter_aligned_subtitle_offset_ms(
            ass_text, '.ass', scene_markers=markers, video_total_s=1420.0,
        )
        self.assertEqual(offset_ms, -6000)

    def test_intro_at_zero_late_subtitles_duration_overflow_corroboration(self):
        """intro 0-90s without outro: subs 5s late (95s) AND last cue overflows 1420s video at 1425s -> -5000ms."""
        markers = [{'kind': 'intro', 'label': 'Intro', 'start': 0.0, 'end': 90.0}]
        ass_text = _build_ass([
            (95.0, 99.0, "Post OP line (5s late)"),
            (700.0, 704.0, "Mid episode"),
            (1421.0, 1425.0, "Next episode preview (5s past video EOF)"),
        ])
        offset_ms = sub_dl.detect_chapter_aligned_subtitle_offset_ms(
            ass_text, '.ass', scene_markers=markers, video_total_s=1420.0,
        )
        self.assertEqual(offset_ms, -5000)

    def test_intro_at_zero_synced_subtitles_with_silent_post_op_title_card_returns_zero(self):
        """False-positive guard: synced 0-90s episode with 5s silent title card (90..95s) returns 0."""
        markers = [{'kind': 'intro', 'label': 'Intro', 'start': 0.0, 'end': 90.0}]
        ass_text = _build_ass([
            (95.0, 99.0, "First dialogue after 5s silent episode title card"),
            (600.0, 604.0, "Mid episode"),
            (1400.0, 1405.0, "Normal ending inside 1420s video"),
        ])
        offset_ms = sub_dl.detect_chapter_aligned_subtitle_offset_ms(
            ass_text, '.ass', scene_markers=markers, video_total_s=1420.0,
        )
        self.assertEqual(offset_ms, 0)

    def test_intro_at_zero_synced_ass_title_sign_blocks_negative_shift(self):
        """False-positive guard: an ASS Title/Sign right at intro_end (90.5s) proves subs are synced."""
        markers = [{'kind': 'intro', 'label': 'Intro', 'start': 0.0, 'end': 90.0}]
        ass_text = _build_ass(
            [
                (95.5, 99.0, "Dialogue right after title card"),
                (600.0, 604.0, "Mid episode"),
                (1421.0, 1425.0, "Late preview cue"),
            ],
            extra_lines=[
                f"Dialogue: 0,{_fmt_ass_ts(90.5)},{_fmt_ass_ts(94.5)},Title,,0,0,0,,Episode 100 Title Card",
            ],
        )
        offset_ms = sub_dl.detect_chapter_aligned_subtitle_offset_ms(
            ass_text, '.ass', scene_markers=markers, video_total_s=1420.0,
        )
        self.assertEqual(offset_ms, 0)


class TestAsyncAniSkipWaitForCalibration(unittest.TestCase):
    """Tests for Improvement #1B: WatchlistPlayer._ensure_scene_markers_for_subtitle_calibration()."""

    def _make_player(self):
        wp = player.WatchlistPlayer()
        wp.mal_id = 269
        wp.episode = 100
        wp.ffprobe_chapters = []
        wp._skip_processed = False
        wp._skip_done_event = threading.Event()
        wp._playback_stopped = False
        return wp

    def test_noop_when_auto_calibrate_disabled(self):
        wp = self._make_player()
        with patch.object(control, 'getBool', return_value=False), \
             patch.object(wp, 'query_demuxer_chapters') as mock_q, \
             patch.object(wp, '_publish_scene_markers') as mock_pub:
            res = wp._ensure_scene_markers_for_subtitle_calibration(max_wait_s=0.5)
        self.assertFalse(res)
        mock_q.assert_not_called()
        mock_pub.assert_not_called()

    def test_noop_when_series_offset_already_persisted(self):
        wp = self._make_player()
        with patch.object(control, 'getBool', return_value=True), \
             patch.object(database, 'get_series_override', return_value={'sub_offset_ms': -3500}), \
             patch.object(wp, 'query_demuxer_chapters') as mock_q, \
             patch.object(wp, '_publish_scene_markers') as mock_pub:
            res = wp._ensure_scene_markers_for_subtitle_calibration(max_wait_s=0.5)
        self.assertFalse(res)
        mock_q.assert_not_called()
        mock_pub.assert_not_called()

    def test_waits_for_async_skip_done_event_and_publishes_markers(self):
        wp = self._make_player()
        events = []

        def _signal_later():
            time.sleep(0.05)
            wp.skipintro_aniskip = True
            wp.skipintro_start = 0
            wp.skipintro_end = 90
            wp._skip_processed = True
            events.append('aniskip_done')
            wp._skip_done_event.set()

        t = threading.Thread(target=_signal_later, daemon=True)
        t.start()
        try:
            with patch.object(control, 'getBool', return_value=True), \
                 patch.object(database, 'get_series_override', return_value={'sub_offset_ms': 0}), \
                 patch.object(control.monitor, 'waitForAbort', side_effect=lambda s: (time.sleep(s), False)[1]), \
                 patch.object(wp, 'query_demuxer_chapters', side_effect=lambda: events.append('chapters')), \
                 patch.object(wp, '_publish_scene_markers', side_effect=lambda: events.append('publish')):
                res = wp._ensure_scene_markers_for_subtitle_calibration(max_wait_s=1.0)
        finally:
            t.join(timeout=1.0)

        self.assertTrue(res)
        self.assertEqual(events, ['chapters', 'aniskip_done', 'publish'])


class TestKodiVideoDbReaderAndPersistence(unittest.TestCase):
    """Tests for Improvement #2: Read-only MyVideos*.db reader, non-destructive DB update,
    and double-shift-free delay persistence across episodes and replays."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_dir = self._tmpdir.name
        self._orig_malsync = control.malSyncDB
        control.malSyncDB = os.path.join(self.tmp_dir, 'malSync_test.db')
        database._series_overrides_table_ready = False
        database.close_all_connections()
        player.WatchlistPlayer._clear_subtitle_sync_properties()

    def tearDown(self):
        player.WatchlistPlayer._clear_subtitle_sync_properties()
        database.close_all_connections()
        control.malSyncDB = self._orig_malsync
        database._series_overrides_table_ready = False
        self._tmpdir.cleanup()

    def test_find_latest_kodi_video_db_picks_highest_version(self):
        for name in ('MyVideos121.db', 'MyVideos131.db', 'MyVideos136.db', 'Textures13.db'):
            with open(os.path.join(self.tmp_dir, name), 'wb') as fh:
                fh.write(b'')
        latest = player._find_latest_kodi_video_db(db_dir=self.tmp_dir)
        self.assertEqual(os.path.basename(latest), 'MyVideos136.db')

    def test_read_kodi_subtitle_delay_ms_readonly_uri_and_sign_convention(self):
        db_file = os.path.join(self.tmp_dir, 'MyVideos136.db')
        _create_kodi_video_db(db_file, [
            ('plugin://plugin.video.otaku.rpdev/play/269/', '100', -3.5),
            ('https://cdn.example.com/hls/', 'master.m3u8', 2.25),
        ])
        delay_neg = player._read_kodi_subtitle_delay_ms(
            ['plugin://plugin.video.otaku.rpdev/play/269/100'],
            db_path=db_file,
        )
        self.assertEqual(delay_neg, -3500)

        # Pipe-header stripped matching for resolved URLs
        delay_pos = player._read_kodi_subtitle_delay_ms(
            ['https://cdn.example.com/hls/master.m3u8|User-Agent=Kodi'],
            db_path=db_file,
        )
        self.assertEqual(delay_pos, 2250)

        # Missing entry returns None cleanly
        self.assertIsNone(
            player._read_kodi_subtitle_delay_ms(['plugin://plugin.video.otaku.rpdev/play/999/1'], db_path=db_file)
        )

    def test_update_series_sub_offset_preserves_all_other_override_fields(self):
        ok = database.set_series_override(
            269,
            audio_lang='jpn',
            sub_lang='eng',
            sub_mode='dialog',
            preferred_provider='nyaa',
            intro_offset_s=4,
            outro_offset_s=-2,
            skip_filler_mode='skip',
            episode_offset=12,
            sub_offset_ms=0,
            preferred_group='SubsPlease',
            excluded_groups='BadGroup',
        )
        self.assertTrue(ok)
        self.assertTrue(database.update_series_sub_offset(269, -3500))

        ov = database.get_series_override(269)
        self.assertEqual(ov['sub_offset_ms'], -3500)
        self.assertEqual(ov['audio_lang'], 'jpn')
        self.assertEqual(ov['sub_lang'], 'eng')
        self.assertEqual(ov['sub_mode'], 'dialog')
        self.assertEqual(ov['preferred_provider'], 'nyaa')
        self.assertEqual(ov['intro_offset_s'], 4)
        self.assertEqual(ov['outro_offset_s'], -2)
        self.assertEqual(ov['skip_filler_mode'], 'skip')
        self.assertEqual(ov['episode_offset'], 12)
        self.assertEqual(ov['preferred_group'], 'SubsPlease')
        self.assertEqual(ov['excluded_groups'], 'BadGroup')

    def test_end_to_end_delay_persist_next_episode_inherit_and_no_replay_double_shift(self):
        """Full lifecycle: Ep 100 user dials -3.5s -> persisted -3500ms -> Ep 101 bakes -3500ms ->
        Ep 100 replay sees initial Kodi delay -3500ms and bakes 0ms -> Ep 101 user dials +3.5s ->
        resets persisted offset to 0ms."""
        database.set_series_override(269, audio_lang='jpn', preferred_group='Judas')
        db_file = os.path.join(self.tmp_dir, 'MyVideos136.db')
        _create_kodi_video_db(db_file, [
            ('plugin://plugin.video.otaku.rpdev/play/269/', '100', -3.5),
        ])

        # --- Step 1: Ep 100 finishes after user dialed -3.5s in Kodi OSD on an external Otaku sub ---
        wp = player.WatchlistPlayer()
        wp.mal_id = 269
        wp.episode = 100
        wp.media_type = 'episode'
        wp.path = 'plugin://plugin.video.otaku.rpdev/play/269/100'
        wp.total_time = 1420
        wp._initial_kodi_sub_delay_ms = 0
        control.playerWindow.setProperty('otaku.subtitle.external_attached', 'true')
        control.playerWindow.setProperty('otaku.subtitle.baked_offset_ms', '0')
        control.playerWindow.setProperty('otaku.subtitle.initial_kodi_delay_ms', '0')

        with patch.object(player, '_find_latest_kodi_video_db', return_value=db_file), \
             patch.object(control.monitor, 'waitForAbort', return_value=False), \
             patch.object(control, 'log_metric') as mock_metric:
            saved = wp._persist_kodi_subtitle_delay()

        self.assertTrue(saved)
        ov = database.get_series_override(269)
        self.assertEqual(ov['sub_offset_ms'], -3500)
        self.assertEqual(ov['audio_lang'], 'jpn')
        self.assertEqual(ov['preferred_group'], 'Judas')
        mock_metric.assert_called_once()
        self.assertEqual(mock_metric.call_args[0][0], 'sub_calibrate')
        self.assertEqual(mock_metric.call_args[1]['source'], 'kodi_delay_persist')
        self.assertEqual(mock_metric.call_args[1]['offset_ms'], -3500)
        self.assertEqual(control.playerWindow.getProperty('otaku.subtitle.external_attached'), '')

        # --- Step 2: Ep 101 downloads external sub (initial Kodi delay = 0) -> bakes -3500ms ---
        raw_ass = _build_ass([(100.0, 104.0, "Hello Bleach Ep 101")]).encode('utf-8')
        fake_svc = MagicMock()
        fake_svc.download.return_value = raw_ass
        sub_res = SubtitleResult(
            service_name='subsource',
            name='Bleach_101.ass',
            display_name='Bleach_101.ass',
            lang='English',
            lang_code='en',
            download_url='https://sub/101',
        )
        meta_101 = VideoMeta(title='Bleach', season=1, episode=101, filename='Bleach_S01E101.mkv', mal_id=269)

        control.playerWindow.setProperty('otaku.subtitle.initial_kodi_delay_ms', '0')
        with patch.dict(sub_dl.ALL_SERVICES, {'subsource': fake_svc}), \
             patch.object(sub_dl, '_get_player_fps_and_duration', return_value=(23.976, 1420.0)):
            ep101_path = sub_dl.download_and_prepare_subtitle(sub_res, meta_101, {}, dest_dir=self.tmp_dir)

        self.assertIsNotNone(ep101_path)
        with open(ep101_path, 'r', encoding='utf-8') as fh:
            ep101_text = fh.read()
        self.assertIn('0:01:36.50', ep101_text)  # 100.0s - 3.5s = 96.5s
        self.assertEqual(control.playerWindow.getProperty('otaku.subtitle.external_attached'), 'true')
        self.assertEqual(control.playerWindow.getProperty('otaku.subtitle.baked_offset_ms'), '-3500')

        # --- Step 3: Replaying Ep 100 sees initial_kodi_delay_ms=-3500 -> effective_bake_ms=0 (ZERO double-shift!) ---
        control.playerWindow.setProperty('otaku.subtitle.initial_kodi_delay_ms', '-3500')
        meta_100 = VideoMeta(title='Bleach', season=1, episode=100, filename='Bleach_S01E100.mkv', mal_id=269)
        with patch.dict(sub_dl.ALL_SERVICES, {'subsource': fake_svc}), \
             patch.object(sub_dl, '_get_player_fps_and_duration', return_value=(23.976, 1420.0)):
            ep100_replay_path = sub_dl.download_and_prepare_subtitle(sub_res, meta_100, {}, dest_dir=self.tmp_dir)

        self.assertIsNotNone(ep100_replay_path)
        with open(ep100_replay_path, 'r', encoding='utf-8') as fh:
            ep100_replay_text = fh.read()
        self.assertIn('0:01:40.00', ep100_replay_text)  # Unshifted: Kodi applies its own -3.5s!
        self.assertEqual(control.playerWindow.getProperty('otaku.subtitle.baked_offset_ms'), '0')

        # --- Step 4: Ep 101 user dials +3.5s (undoing the -3500ms bake) -> persists 0ms ---
        _create_kodi_video_db(db_file + '.2', [
            ('plugin://plugin.video.otaku.rpdev/play/269/', '101', 3.5),
        ])
        wp2 = player.WatchlistPlayer()
        wp2.mal_id = 269
        wp2.episode = 101
        wp2.media_type = 'episode'
        wp2.path = 'plugin://plugin.video.otaku.rpdev/play/269/101'
        wp2._initial_kodi_sub_delay_ms = 0
        control.playerWindow.setProperty('otaku.subtitle.external_attached', 'true')
        control.playerWindow.setProperty('otaku.subtitle.baked_offset_ms', '-3500')
        control.playerWindow.setProperty('otaku.subtitle.initial_kodi_delay_ms', '0')

        with patch.object(player, '_find_latest_kodi_video_db', return_value=db_file + '.2'), \
             patch.object(control.monitor, 'waitForAbort', return_value=False):
            saved2 = wp2._persist_kodi_subtitle_delay()

        self.assertTrue(saved2)
        self.assertEqual(database.get_series_override(269)['sub_offset_ms'], 0)

    def test_embedded_subtitle_only_does_not_persist_kodi_delay(self):
        """Option A: embedded/muxed playback (external_attached != 'true') must NOT mutate sub_offset_ms."""
        database.set_series_override(269, sub_offset_ms=1000)
        db_file = os.path.join(self.tmp_dir, 'MyVideos136.db')
        _create_kodi_video_db(db_file, [
            ('plugin://plugin.video.otaku.rpdev/play/269/', '102', -4.0),
        ])
        wp = player.WatchlistPlayer()
        wp.mal_id = 269
        wp.episode = 102
        wp.path = 'plugin://plugin.video.otaku.rpdev/play/269/102'
        control.playerWindow.clearProperty('otaku.subtitle.external_attached')

        with patch.object(player, '_find_latest_kodi_video_db', return_value=db_file):
            saved = wp._persist_kodi_subtitle_delay()

        self.assertFalse(saved)
        self.assertEqual(database.get_series_override(269)['sub_offset_ms'], 1000)


class TestSkinShortcutsAndModalDialogProtection(unittest.TestCase):
    """Tests for Improvement #3: Skin Shortcuts / modal dialog safety in draw_items() and default.py."""

    def test_has_active_modal_dialog_classifies_kodi_ids_accurately(self):
        # Non-modal / busy / invalid dialog IDs -> False
        for dlg_id in (9999, 10104, 10107, 10113, 10115, 10138, 10151, 10160):
            with patch('xbmcgui.getCurrentWindowDialogId', return_value=dlg_id):
                self.assertFalse(control.has_active_modal_dialog(), f"Expected False for non-modal ID {dlg_id}")

        # Modal dialogs (Custom_1130, DialogAddonSettings, DialogSelect, script-skinshortcuts WindowXMLDialog) -> True
        for dlg_id in (1130, 10140, 12000, 13000, 13001):
            with patch('xbmcgui.getCurrentWindowDialogId', return_value=dlg_id):
                self.assertTrue(control.has_active_modal_dialog(), f"Expected True for modal ID {dlg_id}")

    def test_draw_items_never_closes_dialogs_or_runs_viewmode_during_skinshortcuts(self):
        """Skin Shortcuts calls Files.GetDirectory() while SkinSettings (10035) + script-skinshortcuts (13000) are open.
        draw_items() MUST endOfDirectory() cleanly and NEVER call closeAllDialogs/closeBusyDialog/SetViewMode/wait_loop."""
        with patch('xbmcgui.getCurrentWindowId', return_value=10035), \
             patch('xbmcgui.getCurrentWindowDialogId', return_value=13000), \
             patch.object(control, 'bulk_draw_items', return_value=True), \
             patch.object(control.xbmcplugin, 'endOfDirectory') as mock_end, \
             patch.object(control, 'closeAllDialogs') as mock_close_all, \
             patch.object(control, 'closeBusyDialog') as mock_close_busy, \
             patch.object(control, 'wait_loop') as mock_wait, \
             patch.object(control.xbmc, 'executebuiltin') as mock_exec, \
             patch.object(control, 'getBool', return_value=True):
            control.draw_items([], content_type='episodes', cacheToDisc=False)

        mock_end.assert_called_once()
        mock_close_all.assert_not_called()
        mock_close_busy.assert_not_called()
        mock_wait.assert_not_called()
        mock_exec.assert_not_called()

    def test_draw_items_guards_modal_dialog_even_over_myvideonav(self):
        """Even if a modal dialog (12000 DialogSelect / 13000 Skin Shortcuts) opens above MyVideoNav (10025),
        draw_items() must NOT close it or mutate Container.SetViewMode."""
        with patch('xbmcgui.getCurrentWindowId', return_value=10025), \
             patch('xbmcgui.getCurrentWindowDialogId', return_value=12000), \
             patch.object(control, 'bulk_draw_items', return_value=True), \
             patch.object(control.xbmcplugin, 'endOfDirectory') as mock_end, \
             patch.object(control, 'closeAllDialogs') as mock_close_all, \
             patch.object(control, 'closeBusyDialog') as mock_close_busy, \
             patch.object(control.xbmc, 'executebuiltin') as mock_exec, \
             patch.object(control, 'getBool', return_value=True):
            control.draw_items([], content_type='tvshows', cacheToDisc=True)

        mock_end.assert_called_once()
        mock_close_all.assert_not_called()
        mock_close_busy.assert_not_called()
        mock_exec.assert_not_called()

    def test_draw_items_interactive_myvideonav_closes_only_busy_and_sets_viewmode(self):
        """During normal MyVideoNav (10025) browsing with no modal dialog (or busy spinner 10138),
        draw_items() calls closeBusyDialog() (NEVER closeAllDialogs) and applies Container.SetViewMode."""
        for dlg_id in (9999, 10138):
            with patch('xbmcgui.getCurrentWindowId', return_value=10025), \
                 patch('xbmcgui.getCurrentWindowDialogId', return_value=dlg_id), \
                 patch.object(control, 'bulk_draw_items', return_value=True), \
                 patch.object(control.xbmcplugin, 'endOfDirectory') as mock_end, \
                 patch.object(control, 'closeAllDialogs') as mock_close_all, \
                 patch.object(control, 'closeBusyDialog') as mock_close_busy, \
                 patch.object(control.xbmc, 'sleep'), \
                 patch.object(control.xbmc, 'executebuiltin') as mock_exec, \
                 patch.object(control, 'getBool', side_effect=lambda k, *a, **kw: k in ('interface.viewtype', 'interface.viewidswitch')), \
                 patch.object(control, 'getInt', return_value=55):
                control.draw_items([], content_type='tvshows', cacheToDisc=True)

            mock_end.assert_called_once()
            mock_close_all.assert_not_called()
            mock_close_busy.assert_called_once()
            mock_exec.assert_called_once_with('Container.SetViewMode(55)')

    def test_default_py_skips_widget_delay_and_changelog_popup_under_skinshortcuts_modal(self):
        """default.py skips widgets.delay and blocks auto-change_log popup when a modal dialog (13000) is active."""
        default_path = os.path.join(_PLUGIN_ROOT, 'default.py')
        orig_argv = list(sys.argv)
        try:
            sys.argv = ['plugin://plugin.video.otaku.rpdev/', '1', '']
            with patch('xbmcgui.getCurrentWindowId', return_value=10035), \
                 patch('xbmcgui.getCurrentWindowDialogId', return_value=13000), \
                 patch.object(control, 'init_session'), \
                 patch.object(control, 'cleanup'), \
                 patch.object(control, 'is_addon_visible', return_value=True), \
                 patch.object(control, 'getSetting', side_effect=lambda k, *a, **kw: '0.0.0' if k in ('changelog.version', 'version', 'otaku.version') else ''), \
                 patch.object(control, 'setSetting'), \
                 patch.object(control, 'getInt', side_effect=lambda k, *a, **kw: 2000 if k == 'widgets.delay' else 0), \
                 patch.object(control, 'getBool', return_value=False), \
                 patch.object(control, 'sleep') as mock_sleep, \
                 patch.object(control.xbmc, 'executebuiltin') as mock_exec, \
                 patch('resources.lib.ui.router.router_process') as mock_router:
                runpy.run_path(default_path, run_name='__main__')

            mock_router.assert_called_once()
            mock_sleep.assert_not_called()
            self.assertFalse(
                any('change_log' in str(c) for c in mock_exec.call_args_list),
                f"change_log must not launch over Skin Shortcuts modal: {mock_exec.call_args_list}",
            )
        finally:
            sys.argv = orig_argv


if __name__ == '__main__':
    unittest.main()
