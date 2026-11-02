import time
import unittest
from unittest.mock import patch, MagicMock


class TestMilestoneV6Hardening(unittest.TestCase):

    # ── Pillar A: Resume Point & Bookmark Sync Tests ───────────────────────

    @patch('resources.lib.ui.control.jsonrpc')
    @patch('resources.lib.ui.control.clean_memory')
    @patch('resources.lib.ui.control.closeAllDialogs')
    def test_resume_saving_without_context(self, mock_close, mock_clean, mock_jsonrpc):
        from resources.lib.ui.player import WatchlistPlayer

        p = WatchlistPlayer()
        p.path = 'plugin://plugin.video.otaku.rpdev/play/123/1'
        p.context = False  # Standard directory/widget playback
        p.total_time = 1400
        p.current_time = 700  # 50% watched

        p.onPlayBackStopped()

        self.assertTrue(mock_jsonrpc.called)
        call_args = mock_jsonrpc.call_args[0][0]
        self.assertEqual(call_args['method'], 'Files.SetFileDetails')
        self.assertEqual(call_args['params']['resume']['position'], 700)
        self.assertEqual(call_args['params']['resume']['total'], 1400)

    @patch('resources.lib.ui.control.jsonrpc')
    @patch('resources.lib.ui.control.clean_memory')
    @patch('resources.lib.ui.control.closeAllDialogs')
    def test_resume_clearing_at_90_percent(self, mock_close, mock_clean, mock_jsonrpc):
        from resources.lib.ui.player import WatchlistPlayer

        p = WatchlistPlayer()
        p.path = 'plugin://plugin.video.otaku.rpdev/play/123/1'
        p.context = False
        p.total_time = 1000
        p.current_time = 950  # 95% watched

        p.onPlayBackStopped()

        self.assertTrue(mock_jsonrpc.called)
        call_args = mock_jsonrpc.call_args[0][0]
        self.assertEqual(call_args['method'], 'Files.SetFileDetails')
        self.assertEqual(call_args['params']['resume']['position'], 0)  # Cleared!

    @patch('resources.lib.ui.control.jsonrpc')
    @patch('resources.lib.ui.control.clean_memory')
    @patch('resources.lib.ui.control.closeAllDialogs')
    def test_resume_clearing_on_playback_ended(self, mock_close, mock_clean, mock_jsonrpc):
        from resources.lib.ui.player import WatchlistPlayer

        p = WatchlistPlayer()
        p.path = 'plugin://plugin.video.otaku.rpdev/play/123/1'
        p.total_time = 1200

        p.onPlayBackEnded()

        self.assertTrue(mock_jsonrpc.called)
        call_args = mock_jsonrpc.call_args[0][0]
        self.assertEqual(call_args['method'], 'Files.SetFileDetails')
        self.assertEqual(call_args['params']['resume']['position'], 0)

    # ── Pillar B: AniList GraphQL 50-Item Chunking Tests ───────────────────

    @patch('resources.lib.ui.client.request')
    def test_anilist_by_mal_ids_chunking(self, mock_request):
        from resources.lib.endpoints.anilist import Anilist

        # Mock AniList response returning media with matching idMal
        def fake_request(url, post=None, jpost=False):
            vars_ = post.get('variables', {})
            mal_ids = vars_.get('malIds', [])
            self.assertLessEqual(len(mal_ids), 50, "AniList chunk exceeded 50 items!")
            media = [{'id': mid * 10, 'idMal': mid, 'title': {'romaji': f'Anime {mid}'}} for mid in mal_ids]
            import json
            return json.dumps({
                'data': {
                    'Page': {
                        'pageInfo': {'hasNextPage': False, 'total': len(media)},
                        'media': media
                    }
                }
            })

        mock_request.side_effect = fake_request

        # 125 MAL IDs -> should result in 3 chunks: [50, 50, 25]
        ids = list(range(1, 126))
        al = Anilist()
        results = al.get_anilist_by_mal_ids(ids)

        self.assertEqual(len(results), 125)
        self.assertEqual(mock_request.call_count, 3)

    @patch('resources.lib.ui.client.post')
    def test_anilist_ratings_batch_chunking(self, mock_post):
        from resources.lib.endpoints.anilist import Anilist

        def fake_post(url, json_data=None):
            vars_ = json_data.get('variables', {})
            mal_ids = vars_.get('malIds', [])
            self.assertLessEqual(len(mal_ids), 50, "AniList ratings chunk exceeded 50 items!")
            media = [{'id': mid * 10, 'idMal': mid, 'averageScore': 85, 'meanScore': 83} for mid in mal_ids]
            m = MagicMock()
            m.ok = True
            m.json.return_value = {
                'data': {
                    'Page': {
                        'pageInfo': {'hasNextPage': False, 'total': len(media)},
                        'media': media
                    }
                }
            }
            return m

        mock_post.side_effect = fake_post

        ids = list(range(1, 115))  # 114 IDs -> 3 chunks: [50, 50, 14]
        al = Anilist()
        ratings = al.get_anilist_ratings_batch(ids)

        self.assertEqual(len(ratings), 114)
        self.assertEqual(mock_post.call_count, 3)
        self.assertEqual(ratings[1]['anilist_score'], 85)

    # ── Pillar C: Defensive Context Menu URL Extraction Tests ──────────────

    def test_context_menu_safe_extraction(self):
        import sys
        import os

        # Add context addon path
        context_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'context.otaku.rpdev'))
        if context_dir not in sys.path:
            sys.path.insert(0, context_dir)

        import default as context_default

        plugin = 'plugin://plugin.video.otaku.rpdev'

        # Standard path
        self.assertEqual(context_default._extract_subpath(f'{plugin}/animes/1234', plugin), '/animes/1234')

        # External skin widget path without plugin prefix
        self.assertEqual(context_default._extract_subpath('special://home/addons/custom_path/1234', plugin), '/1234')

        # Empty or None path
        self.assertEqual(context_default._extract_subpath('', plugin, default='/fallback'), '/fallback')
        self.assertEqual(context_default._extract_subpath(None, plugin, default='/fallback'), '/fallback')

        # Watch target extraction
        self.assertEqual(context_default._extract_watch_target('special://skin/widget/1234/5', plugin), '/1234/5')
        self.assertEqual(context_default._extract_watch_target('', plugin), '/1/1')

    # ── Pillar D: Window Property RAM Cache Bounds & Generational GC Tests ──

    def test_ram_cache_size_guard_and_generational_gc(self):
        from resources.lib.ui import database, control

        # Small payload: stored in window property
        small_payload = "{'anime': 'Naruto'}"
        database._mem_set('test_small', small_payload, 1)
        self.assertIsNotNone(database._mem_get('test_small'))

        # Large payload (>64KB): skipped by _mem_set
        large_payload = 'x' * 70000
        database._mem_set('test_large', large_payload, 1)
        # Should bypass window property
        prefix = database._get_mem_prefix()
        self.assertFalse(bool(control.homeWindow.getProperty(prefix + 'test_large')))

        # Generational bump cleans previous generation properties
        k1 = 'test_gen_key_1'
        database._mem_set(k1, "{'ep': 1}", 1)
        self.assertIsNotNone(database._mem_get(k1))

        # Bump generation
        database._bump_mem_generation()
        # Old key should be expired/purged in new generation
        self.assertIsNone(database._mem_get(k1))

    # ── Pillar E: Proactive OAuth Token Refresh Tests ──────────────────────

    @patch('resources.lib.WatchlistFlavor.MyAnimeList.MyAnimeListWLF.refresh_token')
    def test_mal_proactive_token_refresh(self, mock_refresh):
        from resources.lib.WatchlistFlavor.MyAnimeList import MyAnimeListWLF
        from resources.lib.ui import control

        wlf = MyAnimeListWLF()
        # Set expiry to 100 seconds in the future (< 300s threshold)
        control.setInt('mal.expiry', int(time.time()) + 100)
        control.setSetting('mal.token', 'old_mal_token')

        def set_new_token():
            control.setSetting('mal.token', 'refreshed_mal_token')

        mock_refresh.side_effect = set_new_token

        headers = wlf._MyAnimeListWLF__headers()
        self.assertTrue(mock_refresh.called)
        self.assertEqual(headers.get('Authorization'), 'Bearer refreshed_mal_token')

    @patch('resources.lib.WatchlistFlavor.Kitsu.KitsuWLF.refresh_token')
    def test_kitsu_proactive_token_refresh(self, mock_refresh):
        from resources.lib.WatchlistFlavor.Kitsu import KitsuWLF
        from resources.lib.ui import control

        wlf = KitsuWLF()
        control.setInt('kitsu.expiry', int(time.time()) + 100)
        control.setSetting('kitsu.token', 'old_kitsu_token')

        def set_new_token():
            control.setSetting('kitsu.token', 'refreshed_kitsu_token')

        mock_refresh.side_effect = set_new_token

        headers = wlf._KitsuWLF__headers()
        self.assertTrue(mock_refresh.called)
        self.assertEqual(headers.get('Authorization'), 'Bearer refreshed_kitsu_token')

    # ── Pillar F: Universal Debrid 429 Rate-Limit Backoff Tests ───────────

    @patch('resources.lib.ui.client.get')
    def test_alldebrid_429_backoff(self, mock_get):
        from resources.lib.debrid.all_debrid import AllDebrid

        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {'Retry-After': '1'}

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.ok = True
        resp_200.json.return_value = {'data': {'magnets': [{'id': '101'}]}}

        mock_get.side_effect = [resp_429, resp_200]

        ad = AllDebrid()
        res = ad._request_with_backoff('get', 'https://api.alldebrid.com/v4.1/test')

        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(res.status_code, 200)

    @patch('resources.lib.ui.client.get')
    def test_premiumize_429_backoff(self, mock_get):
        from resources.lib.debrid.premiumize import Premiumize

        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {'Retry-After': '1'}

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.ok = True
        resp_200.json.return_value = {'status': 'success'}

        mock_get.side_effect = [resp_429, resp_200]

        prem = Premiumize()
        res = prem._request_with_backoff('get', 'https://www.premiumize.me/api/test')

        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(res.status_code, 200)

    @patch('resources.lib.ui.client.post')
    def test_debridlink_429_backoff(self, mock_post):
        from resources.lib.debrid.debrid_link import DebridLink

        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {'Retry-After': '1'}

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.ok = True
        resp_200.json.return_value = {'value': {'id': 'dl_123'}}

        mock_post.side_effect = [resp_429, resp_200]

        dl = DebridLink()
        res = dl._request_with_backoff('post', 'https://debrid-link.fr/api/v2/test')

        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(res.status_code, 200)


if __name__ == '__main__':
    unittest.main()
