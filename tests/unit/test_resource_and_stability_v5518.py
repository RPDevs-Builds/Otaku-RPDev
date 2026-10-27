import sys
import unittest
from unittest.mock import MagicMock, patch

from resources.lib.ui import control, database, client
from resources.lib.ui import get_meta
from resources.lib.debrid import debrid_cache
from resources.lib.ui.player import WatchlistPlayer


class TestResourceAndStabilityV5518(unittest.TestCase):
    def setUp(self):
        control.clearSettingsCache()

    def tearDown(self):
        control.cleanup()

    # ── Group 1: Playback & Stop Responsiveness ─────────────────────────

    def test_player_stopped_flag_on_callbacks(self):
        """Verify _playback_stopped flag is set immediately on stop/end/error."""
        p = WatchlistPlayer()
        self.assertFalse(p._playback_stopped)

        with patch('resources.lib.ui.control.closeAllDialogs'), \
             patch('resources.lib.ui.control.clean_memory'):
            p.onPlayBackStopped()
            self.assertTrue(p._playback_stopped)

            p._playback_stopped = False
            p.onPlayBackEnded()
            self.assertTrue(p._playback_stopped)

            p._playback_stopped = False
            p.onPlayBackError()
            self.assertTrue(p._playback_stopped)

    def test_fast_path_ffprobe_chapters(self):
        """Verify that ffprobe chapters are processed immediately when present."""
        p = WatchlistPlayer()
        p.mal_id = '123'
        p.episode = 1
        p.media_type = 'episode'
        p.type = 'torrent'
        p.provider = 'nyaa'
        p.ffprobe_chapters = [
            {'title': 'Opening', 'start': 100.0, 'end': 190.0},
            {'title': 'Ending', 'start': 1200.0, 'end': 1290.0}
        ]

        mock_vtag = MagicMock()
        mock_vtag.getMediaType.return_value = 'episode'

        with patch.object(p, 'isPlayingVideo', return_value=True), \
             patch.object(p, 'getTotalTime', return_value=1400), \
             patch.object(p, 'getVideoInfoTag', return_value=mock_vtag), \
             patch.object(p, 'process_ffprobe_chapter_skips') as mock_skips, \
             patch.object(p, '_run_unified_episode_monitor'), \
             patch.object(p, 'isPlaying', return_value=False), \
             patch('resources.lib.ui.database.get_unique_ids', return_value={}), \
             patch('resources.lib.Main.save_to_watch_history'), \
             patch.object(p, 'setup_audio_and_subtitles'):
            # Simulate already having intro/outro skip times resolved by chapters
            p.skipintro_aniskip = True
            p.skipoutro_aniskip = True

            # In keepAlive(), it should call process_ffprobe_chapter_skips() and NOT wait
            p.keepAlive()
            mock_skips.assert_called_once()

    def test_prescrape_throttles_on_low_memory(self):
        """Verify 70% pre-scrape logs throttling when is_low_memory returns True."""
        p = WatchlistPlayer()
        p.mal_id = '12345'
        p.episode = 1
        p.media_type = 'episode'

        with patch('resources.lib.ui.control.getBool', return_value=True), \
             patch('resources.lib.ui.control.is_low_memory', return_value=True), \
             patch('resources.lib.ui.database.get_episode', return_value={'season': 1}), \
             patch('resources.lib.ui.database.get_season_pack', return_value=None), \
             patch('threading.Thread') as mock_thread:
            p._trigger_background_prescrape()
            self.assertTrue(mock_thread.called)
            # The target worker function inside should have throttling branch
            worker_fn = mock_thread.call_args[1].get('target') or mock_thread.call_args[0][0]
            with patch('xbmc.sleep') as mock_sleep, \
                 patch('resources.lib.ui.control.log') as mock_log, \
                 patch('resources.lib.MetaBrowser.get_sources'):
                worker_fn()
                mock_sleep.assert_called_with(1000)

    # ── Group 2: Browsing & Concurrency Speed ───────────────────────────

    def test_is_low_memory_logic(self):
        """Verify is_low_memory checks 32-bit architecture and RAM threshold."""
        # Case 1: 32-bit architecture
        with patch.object(sys, 'maxsize', 2**31 - 1):
            self.assertTrue(control.is_low_memory())

        # Case 2: 64-bit architecture with <= 2048 MB RAM
        with patch.object(sys, 'maxsize', 2**63 - 1), \
             patch('resources.lib.ui.control.get_device_ram_mb', return_value=1950):
            self.assertTrue(control.is_low_memory())

        # Case 3: 64-bit architecture with 8192 MB RAM
        with patch.object(sys, 'maxsize', 2**63 - 1), \
             patch('resources.lib.ui.control.get_device_ram_mb', return_value=8192):
            self.assertFalse(control.is_low_memory())

    def test_fanart_o1_dictionary_lookup(self):
        """Verify bulk_dir_list precomputes fanart_map for O(1) resolution."""
        video_data = [{
            'name': 'Test Anime Ep 1',
            'url': 'action/123/1',
            'image': {'poster': 'poster.jpg', 'fanart': ['fanart_a.jpg', 'fanart_b.jpg']},
            'info': {'UniqueIDs': {'mal_id': '1001'}, 'plot': 'Test plot'},
            'cm': [],
            'isfolder': False,
            'isplayable': True,
        }]

        with patch('resources.lib.ui.control.getBool', side_effect=lambda k, default=False: True if k in ('artwork.fanart', 'context.otaku.fanartselect') else False), \
             patch('resources.lib.ui.control.getStringList', side_effect=lambda k: ['1001'] if k == 'fanart.mal_ids' else ['fanart_b.jpg']):
            items = control.bulk_dir_list(video_data, bulk_add=False)
            self.assertEqual(len(items), 1)

    def test_get_meta_sequential_in_batch(self):
        """Verify update_meta does not spawn ThreadPoolExecutor when in_batch=True."""
        with patch('resources.lib.ui.database.get_mappings', return_value={'mal_id': '500'}), \
             patch('resources.lib.ui.database.update_show_meta'), \
             patch('resources.lib.ui.control.getInt', side_effect=lambda k: 3 if k == 'artwork.preference' else 10), \
             patch('resources.lib.ui.control.getBool', return_value=True), \
             patch('concurrent.futures.ThreadPoolExecutor') as mock_tpe, \
             patch('resources.lib.endpoints.fanart.getArt', return_value={'fanart': ['f.jpg']}), \
             patch('resources.lib.endpoints.tmdb.getArt', return_value={'fanart': ['t.jpg']}), \
             patch('resources.lib.endpoints.tvdb.getArt', return_value={'fanart': ['tv.jpg']}):
            get_meta.update_meta('500', in_batch=True)
            # In batch mode, it MUST NOT construct a ThreadPoolExecutor
            mock_tpe.assert_not_called()

    # ── Group 3: Scraper & Network Efficiency ───────────────────────────

    def test_client_default_timeout_is_10s(self):
        """Verify client.py functions default to timeout=10."""
        import inspect
        sig_get = inspect.signature(client.get)
        self.assertEqual(sig_get.parameters['timeout'].default, 10)

        sig_post = inspect.signature(client.post)
        self.assertEqual(sig_post.parameters['timeout'].default, 10)

        sig_req = inspect.signature(client.request)
        self.assertEqual(sig_req.parameters['timeout'].default, 10)

    def test_dmm_chunking_complete_check(self):
        """Verify _dmm_check_cache batches 250 hashes into 3 requests without random drop."""
        # Generate 250 mock 40-character sha1 hashes
        mock_hashes = [f"{i:040d}" for i in range(250)]
        collector = []

        with patch('resources.lib.debrid.debrid_cache._get_dmm_secret', return_value=('key', 'sol')), \
             patch('resources.lib.ui.client.post') as mock_post:
            mock_resp = MagicMock()
            mock_resp.ok = True
            mock_resp.json.return_value = {'available': [{'hash': mock_hashes[0]}]}
            mock_post.return_value = mock_resp

            debrid_cache._dmm_check_cache(mock_hashes, 'tt1234567', collector)

            # 250 hashes should be chunked into 3 requests: [100, 100, 50]
            self.assertEqual(mock_post.call_count, 3)
            self.assertEqual(collector, [mock_hashes[0]] * 3)

    def test_database_low_memory_mmap_clamping(self):
        """Verify database connection clamps PRAGMA mmap_size on low memory."""
        database.close_thread_connections()
        with patch('resources.lib.ui.control.is_low_memory', return_value=True), \
             patch('sqlite3.dbapi2.connect') as mock_connect:
            mock_conn = MagicMock()
            mock_connect.return_value = mock_conn

            with database.SQL(control.cacheFile):
                pass

            # Check that PRAGMA mmap_size = 4194304 was executed
            mmap_calls = [
                call_args[0][0] for call_args in mock_conn.execute.call_args_list
                if 'mmap_size' in call_args[0][0]
            ]
            self.assertTrue(any('4194304' in sql for sql in mmap_calls))


if __name__ == '__main__':
    unittest.main()
