import unittest
from unittest.mock import MagicMock, patch

from resources.lib.ui import control, domains
from resources.lib.windows.resolver import Resolver
from resources.lib.windows.source_select import SourceSelect
from resources.lib.pages import animepahe, hianime
import conftest


class TestConcernsRemediationsV625(unittest.TestCase):

    def test_clean_art_dict_swig_type_safety(self):
        """Verify control.clean_art_dict coerces and filters all keys/values for Kodi C++ SWIG contracts."""
        raw_art = {
            'icon': 'https://example.com/icon.png',
            'poster': ['https://example.com/poster.jpg', 'https://example.com/poster2.jpg'],
            'thumb': ['https://example.com/thumb.jpg'],
            'fanart': [],
            'banner': None,
            'empty_str': '',
            'whitespace': '   ',
            'number': 12345,
            'nested_dict': {'large': 'https://example.com/nested.jpg'},
            'list_of_ints': [1, 2, 3],
            'list_empty_first': ['', 'valid.jpg'],
            100: 'https://example.com/numeric_key.jpg'
        }
        cleaned = control.clean_art_dict(raw_art)

        self.assertEqual(cleaned['icon'], 'https://example.com/icon.png')
        self.assertEqual(cleaned['poster'], 'https://example.com/poster.jpg')
        self.assertEqual(cleaned['thumb'], 'https://example.com/thumb.jpg')
        self.assertEqual(cleaned['100'], 'https://example.com/numeric_key.jpg')

        # Keys with None, empty string, whitespace-only, empty list, or non-string values should be omitted
        self.assertNotIn('fanart', cleaned)
        self.assertNotIn('banner', cleaned)
        self.assertNotIn('empty_str', cleaned)
        self.assertNotIn('whitespace', cleaned)
        self.assertNotIn('number', cleaned)
        self.assertNotIn('nested_dict', cleaned)
        self.assertNotIn('list_of_ints', cleaned)
        self.assertNotIn('list_empty_first', cleaned)

        # Non-dict inputs should return empty dict
        self.assertEqual(control.clean_art_dict(None), {})
        self.assertEqual(control.clean_art_dict([]), {})
        self.assertEqual(control.clean_art_dict('not a dict'), {})

    def test_resolver_build_art_dict_unwraps_lists_and_type_guards(self):
        """Verify Resolver._build_art_dict safely unwraps lists/tuples and guards non-dict image fields."""
        # Scenario 1: use_params=True with lists in params
        action_args = {
            'mal_id': 11737,
            'params': {
                'icon': ['https://example.com/icon.png'],
                'poster': ['https://example.com/poster.jpg'],
                'thumb': ['https://example.com/thumb.jpg'],
                'fanart': ['https://example.com/fanart.jpg'],
                'studio': ['Bones'],
                'image': {
                    'banner': ['https://example.com/banner.jpg'],
                    'clearart': ['https://example.com/clearart.png'],
                    'clearlogo': ['https://example.com/clearlogo.png']
                }
            }
        }
        res = Resolver('resolver.xml', conftest.ADDON_ROOT, actionArgs=action_args, source_select=False)
        art = res._build_art_dict(use_params=True)

        for k, v in art.items():
            self.assertIsInstance(v, str, f"Key {k} must be string, got {type(v)}")

        self.assertEqual(art['icon'], 'https://example.com/icon.png')
        self.assertEqual(art['tvshow.poster'], 'https://example.com/poster.jpg')
        self.assertEqual(art['thumb'], 'https://example.com/thumb.jpg')
        self.assertEqual(art['fanart'], 'https://example.com/fanart.jpg')
        self.assertEqual(art['studio'], 'Bones')

        # Scenario 2: use_params=False with lists in image (as returned by get_meta.py merge_artwork)
        res.image = {
            'icon': 'https://example.com/img_icon.png',
            'thumb': ['https://example.com/img_thumb.jpg'],
            'fanart': ['https://example.com/img_fanart.jpg'],
            'poster': ['https://example.com/img_poster.jpg'],
            'landscape': ['https://example.com/img_land.jpg'],
            'banner': ['https://example.com/img_banner.jpg'],
            'clearart': 'https://example.com/img_clearart.png',
            'clearlogo': 'https://example.com/img_clearlogo.png',
            'studio': 'Aniplex'
        }
        art_no_params = res._build_art_dict(use_params=False)

        for k, v in art_no_params.items():
            self.assertIsInstance(v, str, f"Key {k} must be string, got {type(v)}")

        self.assertEqual(art_no_params['thumb'], 'https://example.com/img_thumb.jpg')
        self.assertEqual(art_no_params['tvshow.poster'], 'https://example.com/img_poster.jpg')
        self.assertEqual(art_no_params['fanart'], 'https://example.com/img_fanart.jpg')
        self.assertEqual(art_no_params['studio'], 'Aniplex')

        # clean_art_dict on result must succeed and retain all fields
        clean = control.clean_art_dict(art_no_params)
        self.assertEqual(clean['thumb'], 'https://example.com/img_thumb.jpg')
        self.assertEqual(clean['tvshow.poster'], 'https://example.com/img_poster.jpg')

    @patch('resources.lib.windows.source_select.Manager')
    @patch('resources.lib.windows.source_select.Resolver')
    @patch('resources.lib.ui.control.context_menu', return_value=1)
    def test_source_select_download_action_position_before_close(self, mock_ctx, mock_resolver, mock_mgr):
        """Verify Download context action in SourceSelect extracts source before closing, preventing AttributeError."""
        action_args = {'mal_id': 11737, 'play': True}
        sources = [
            {'debrid_provider': 'Real-Debrid', 'release_title': 'Blue Exorcist 1', 'hash': 'abc1'},
            {'debrid_provider': 'Real-Debrid', 'release_title': 'Blue Exorcist 2', 'hash': 'abc2'}
        ]
        dialog = SourceSelect('source_select.xml', conftest.ADDON_ROOT, actionArgs=action_args, sources=sources)

        # Mock display list with selected position 1
        mock_list = MagicMock()
        mock_list.getSelectedPosition.return_value = 1
        dialog.display_list = mock_list
        dialog.displayed_sources = list(sources)

        mock_action = MagicMock()
        mock_action.getId.return_value = 117  # Context menu action

        mock_res_instance = MagicMock()
        mock_res_instance.doModal.return_value = {'link': 'http://example.com/download.mkv'}
        mock_resolver.return_value = mock_res_instance

        # Execute onAction - must not raise AttributeError: 'NoneType' object has no attribute 'getSelectedPosition'
        dialog.onAction(mock_action)

        # Verify resolver was invoked with source at position 1
        mock_res_instance.doModal.assert_called_once_with([sources[1]], {}, False)
        mock_mgr.return_value.download_file.assert_called_once_with('http://example.com/download.mkv')

    @patch('resources.lib.ui.domains.is_mirror_healthy', return_value=False)
    def test_animepahe_skips_search_when_cooling_down(self, mock_healthy):
        """Verify AnimePahe skips search when the domain is in failure cooldown."""
        scraper = animepahe.Sources()
        with patch.object(scraper, '_resolve_session_from_malsync', return_value=None):
            with patch('resources.lib.endpoints.malsync.get_title', return_value='Blue Exorcist'):
                results = scraper.get_sources(11737, 1)
                self.assertEqual(results, [])

    @patch('resources.lib.ui.domains.is_mirror_healthy', return_value=True)
    @patch('resources.lib.ui.domains.mark_mirror_failure')
    @patch('resources.lib.ui.database.get', return_value=None)
    def test_animepahe_marks_failure_when_search_returns_no_data(self, mock_db_get, mock_mark, mock_healthy):
        """Verify AnimePahe marks failure and cools down when search API returns no data."""
        scraper = animepahe.Sources()
        with patch.object(scraper, '_resolve_session_from_malsync', return_value=None):
            with patch('resources.lib.endpoints.malsync.get_title', return_value='Blue Exorcist'):
                results = scraper.get_sources(11737, 1)
                self.assertEqual(results, [])
                mock_mark.assert_called_with(scraper._BASE_URL)

    @patch('resources.lib.ui.database.get', return_value=None)
    def test_hianime_resolve_anime_id_fast_fails_on_dead_mirror(self, mock_db_get):
        """Verify HiAnime breaks immediately on keyword 1 when a mirror returns no response."""
        scraper = hianime.Sources()
        with patch.object(scraper, '_search_keywords', return_value=['keyword1', 'keyword2', 'keyword3']):
            with self.assertRaises(ConnectionError) as ctx:
                scraper._resolve_anime_id('https://hianime.dead/', 'Some Title', {}, 1234, {})
            self.assertIn("returned no response for search requests", str(ctx.exception))
            # Verify database.get was called exactly once, not 3 times
            self.assertEqual(mock_db_get.call_count, 1)

    @patch('resources.lib.pages.hianime.extract_megaplay_sources', return_value=None)
    @patch('resources.lib.ui.domains.get_healthy_mirrors', return_value=[
        'https://hianime.at/',
        'https://hianime.ba/',
        'https://hianime.gy/',
    ])
    @patch('resources.lib.ui.database.get_show', return_value={'kodi_meta': '{"name": "Blue Exorcist: The Movie"}'})
    def test_hianime_short_circuits_mirrors_after_clean_zero_source_embed(
        self, _mock_show, _mock_mirrors, mock_extract
    ):
        """C-17: Stop iterating identical mirrors once a healthy mirror resolves servers with 0 streams."""
        scraper = hianime.Sources()
        mock_servers = {
            'dub': [{
                'name': 'ZokoAnime',
                'url': 'https://zokoanime.video/stream/mal/11737/1/dub',
                'domain': 'zokoanime.video',
            }]
        }
        with patch.object(scraper, '_enabled_servers', return_value=['ryu']), \
             patch.object(scraper, '_resolve_anime_id', return_value='519') as mock_resolve_id, \
             patch.object(scraper, '_resolve_episode_id', return_value='100'), \
             patch.object(scraper, '_resolve_servers', return_value=mock_servers), \
             patch('resources.lib.ui.control.getInt', return_value=2):
            results = scraper.get_sources(11737, 1)

        self.assertEqual(results, [])
        self.assertEqual(mock_resolve_id.call_count, 1)
        self.assertEqual(mock_extract.call_count, 1)

    @patch('resources.lib.ui.domains.get_healthy_mirrors', return_value=[
        'https://hianime.at/',
        'https://hianime.ba/',
        'https://hianime.gy/',
    ])
    @patch('resources.lib.ui.database.get_show', return_value={'kodi_meta': '{"name": "Obscure OVA"}'})
    def test_hianime_short_circuits_mirrors_on_clean_no_catalog_match(self, _mock_show, _mock_mirrors):
        """C-17: Stop iterating identical mirrors when mirror 1 responds cleanly with no catalog match."""
        scraper = hianime.Sources()
        with patch.object(scraper, '_enabled_servers', return_value=['ryu']), \
             patch.object(scraper, '_resolve_anime_id', return_value=None) as mock_resolve_id:
            results = scraper.get_sources(99999, 1)

        self.assertEqual(results, [])
        self.assertEqual(mock_resolve_id.call_count, 1)

    @patch('resources.lib.ui.domains.mark_mirror_failure')
    @patch('resources.lib.ui.domains.get_healthy_mirrors', return_value=[
        'https://hianime.dead/',
        'https://hianime.live/',
    ])
    @patch('resources.lib.ui.database.get_show', return_value={'kodi_meta': '{"name": "Blood Lad"}'})
    def test_hianime_fails_over_on_dead_mirror_and_api_miss(self, _mock_show, _mock_mirrors, mock_mark_fail):
        """C-17: Dead mirrors (ConnectionError) still fail over to the next healthy mirror."""
        scraper = hianime.Sources()
        fake_source = {'provider': 'hianime', 'hash': 'https://cdn.test/master.m3u8', 'type': 'direct'}

        def _fake_resolve(mirror, *args, **kwargs):
            if 'dead' in mirror:
                raise ConnectionError("Mirror dead")
            return '1676'

        with patch.object(scraper, '_enabled_servers', return_value=['ryu']), \
             patch.object(scraper, '_resolve_anime_id', side_effect=_fake_resolve) as mock_resolve_id, \
             patch.object(scraper, '_resolve_episode_id', return_value='500'), \
             patch.object(scraper, '_resolve_servers', return_value={
                 'dub': [{'name': 'HD-1', 'url': 'https://megaplay.buzz/stream/1', 'domain': 'megaplay.buzz'}]
             }), \
             patch('resources.lib.pages.hianime.extract_megaplay_sources', return_value={'sources': [{'file': 'https://cdn.test/master.m3u8'}]}), \
             patch.object(scraper, '_extract_server_source', return_value=fake_source), \
             patch('resources.lib.ui.control.getInt', return_value=2):
            results = scraper.get_sources(11633, 4)

        self.assertEqual(results, [fake_source])
        self.assertEqual(mock_resolve_id.call_count, 2)
        mock_mark_fail.assert_called_once_with('https://hianime.dead/')

    def test_isolate_and_score_batch_torrents_with_bundled_ova_and_ranges(self):
        """C-18: Valid Blood Lad batch torrents (+ OVA, 1-10+OVA Complete, truncated '[', BD) pass relevance gate while standalone OVAs/derivatives stay <= 40."""
        from resources.lib.ui import source_utils

        valid_batches = [
            "[MK] Blood Lad + OVA [BD 1080p][Hi10][Dual-Audio]",
            "[CBM] Blood Lad 1-10+OVA Complete (Dual Audio) [BDRip-1080p-8bit-FLAC]",
            "[CBM] Blood Lad 1-10+OVA Complete (Dual Audio) [BDRip-1080p-8bit",
            "[AnimeKaizoku] Blood Lad 720p x264 BD Dual Audio [Demon Alpha]",
            "[HorribleSubs] Blood Lad: Complete (1-10) [720p]",
            "Blood Lad 720p Complete [1-10] + Blood Lad Special 720p Dual Audio",
            "Blood Lad 1-10+OVA Complete 720p [Dual-Audio] [English Subbed] Neroextreme_NTRG",
            "[Aries].Blood lad Complete",
            "Blood Lad [Dual Audio] [HEVC] [10-bit] [BDRip] [HD 1080p] [bluury]",
            "[CRUCiBLE] Blood Lad Season 1 (S01) + OVA (BD Remux 1080p FLAC H.264) [Dual Audio]",
            "Blood Lad [Season 1 + OVA] [USBD 1080p x265 HEVC AAC] [Dual Audio-EngSubs] (Batch)",
        ]
        for raw_title in valid_batches:
            score = source_utils.score_title_candidate("Blood Lad", raw_title, year="2013")
            self.assertGreaterEqual(
                score,
                110,
                f"Expected valid batch release to pass relevance gate (>=110), got {score} for {raw_title!r} (isolated={source_utils.isolate_show_title(raw_title)!r})",
            )

        negative_controls = [
            ("Blood Lad", "[Thomku] Blood Lad - OVA [x264 720p BD AAC].mp4", "2013"),
            ("Blood Lad", "[Kaitou]_Blood_Lad_OVA_-_EX_[BD_1080p][10bit][FLAC][2149EF43].mkv", "2013"),
            ("Blood Lad", "Blood Lad: Wagahai wa Neko de wa Nai", "2013"),
            ("Monster", "Re:Monster - 01 [1080p]", None),
            ("Monster", "Monster Musume - 01 [1080p]", None),
        ]
        for query, raw_title, year in negative_controls:
            score = source_utils.score_title_candidate(query, raw_title, year=year)
            self.assertLessEqual(
                score,
                40,
                f"Expected standalone OVA/derivative to stay <=40, got {score} for {raw_title!r}",
            )

    def test_zero_wait_survives_eof_when_isplaying_false_before_callback(self):
        """C-16 follow-up: keepAlive preserves otaku.preResolved_* on natural EOF even before onPlayBackEnded fires."""
        from resources.lib.ui.player import WatchlistPlayer

        control.playerWindow.setProperty('otaku.preResolved_url', 'https://cdn.example.com/ep9.m3u8')
        control.playerWindow.setProperty('otaku.preResolved_malId', '11633')
        control.playerWindow.setProperty('otaku.preResolved_episode', '9')
        control.playerWindow.setProperty('otaku.preResolved_data', '{"url": "https://cdn.example.com/ep9.m3u8"}')

        control.playList.clear()
        control.playList.add('plugin://plugin.video.otaku.rpdev/play/11633/8')
        control.playList.add('plugin://plugin.video.otaku.rpdev/play/11633/9')

        wp = WatchlistPlayer()
        wp.mal_id = 11633
        wp.episode = 8
        wp.path = 'plugin://plugin.video.otaku.rpdev/play/11633/8'
        wp.total_time = 1440
        wp._skip_processed = True
        wp.media_type = 'episode'
        # Simulate Kodi C++ flipping isPlaying() False on EOF BEFORE onPlayBackEnded() fires
        wp._playback_ended = False
        wp._user_stopped_or_errored = False

        with patch.object(wp, 'isPlaying', return_value=False), \
             patch.object(wp, 'getVideoInfoTag', return_value=MagicMock(getMediaType=lambda: 'episode')), \
             patch.object(wp, 'getTotalTime', return_value=1440), \
             patch.object(wp, '_run_unified_episode_monitor'), \
             patch.object(wp, 'process_ffprobe_chapter_skips'), \
             patch('resources.lib.ui.database.get_show', return_value=None), \
             patch('resources.lib.ui.player.control.getBool', return_value=False):
            wp.keepAlive()

        self.assertEqual(
            control.playerWindow.getProperty('otaku.preResolved_url'),
            'https://cdn.example.com/ep9.m3u8',
        )
        control.playList.clear()
        wp._clear_preresolved_properties()

    def test_prescrape_skips_movies_and_season_finales(self):
        """C-19: _trigger_background_prescrape skips non-existent Ep 2 of movies and Ep N+1 of season finales."""
        from resources.lib.ui.player import WatchlistPlayer

        wp = WatchlistPlayer()
        wp.mal_id = 11737
        wp.episode = 1
        wp.media_type = 'video'  # Not marked 'movie' by Kodi vtag
        wp.episodes = []
        control.playList.clear()

        movie_row = {'kodi_meta': '{"name": "Blue Exorcist: The Movie", "mediatype": "movie", "episodes": 1}'}
        with patch('resources.lib.ui.player.control.getBool', return_value=True), \
             patch('resources.lib.ui.player.database.get_show', return_value=movie_row), \
             patch('resources.lib.ui.player.threading.Thread') as mock_thread:
            wp._trigger_background_prescrape()
            mock_thread.assert_not_called()

        # Also skip season finale when next_ep > len(self.episodes)
        wp.mal_id = 11633
        wp.episode = 10
        wp.media_type = 'episode'
        wp.episodes = [{'number': i} for i in range(1, 11)]
        with patch('resources.lib.ui.player.control.getBool', return_value=True), \
             patch('resources.lib.ui.player.threading.Thread') as mock_thread:
            wp._trigger_background_prescrape()
            mock_thread.assert_not_called()


if __name__ == '__main__':
    unittest.main()
