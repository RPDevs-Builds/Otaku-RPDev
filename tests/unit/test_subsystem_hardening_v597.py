import unittest
from unittest.mock import patch, MagicMock
import json
import urllib.parse


class TestSubsystemHardeningV597(unittest.TestCase):

    # ── Pillar 1: Client Float Timeout & Safe JSON ────────────────────────

    def test_client_float_timeout(self):
        from resources.lib.ui import client
        import urllib.request
        mock_opener = MagicMock()
        mock_opener.open.return_value = MagicMock(read=lambda: b'ok', info=lambda: MagicMock())
        with patch('urllib.request.build_opener', return_value=mock_opener):
            # Test sub-second float timeout
            client.request('https://httpbin.org/get', timeout=0.5)
            self.assertTrue(mock_opener.open.called)
            args, kwargs = mock_opener.open.call_args
            self.assertEqual(kwargs.get('timeout'), 0.5)

    def test_response_safe_json_with_default(self):
        from resources.lib.ui.client import Response
        # HTML error page payload
        html_content = b'<html><body>502 Bad Gateway</body></html>'
        r = Response(html_content, status_code=502)

        # Default fallback should return given default
        self.assertEqual(r.json(default={}), {})
        self.assertIsNone(r.json(default=None))

        # Without default, it raises ValueError
        with self.assertRaises(ValueError):
            r.json()

    def test_response_valid_json(self):
        from resources.lib.ui.client import Response
        json_content = b'{"status": "ok", "count": 42}'
        r = Response(json_content, status_code=200)
        self.assertEqual(r.json(), {"status": "ok", "count": 42})
        self.assertEqual(r.json(default={}), {"status": "ok", "count": 42})

    # ── Pillar 2: EasyDebrid 429 Backoff ──────────────────────────────────

    def test_easydebrid_backoff_on_429(self):
        from resources.lib.debrid.easydebrid import EasyDebrid
        ed = EasyDebrid()
        ed.token = 'test_token'

        mock_resp_429 = MagicMock(status_code=429, headers={'Retry-After': '1'})
        mock_resp_200 = MagicMock(status_code=200, ok=True)
        mock_resp_200.json.return_value = {'id': 'user_123', 'paid_until': 2000000000}

        with patch('resources.lib.ui.client.get', side_effect=[mock_resp_429, mock_resp_200]) as mock_get, \
             patch('time.sleep') as mock_sleep, \
             patch('resources.lib.ui.control.ok_dialog'):
            res = ed.status()
            self.assertTrue(res)
            self.assertEqual(mock_get.call_count, 2)
            self.assertTrue(mock_sleep.called)

    def test_easydebrid_safe_json_status(self):
        from resources.lib.debrid.easydebrid import EasyDebrid
        ed = EasyDebrid()
        ed.token = 'test_token'

        # Response with invalid JSON (HTML)
        mock_resp = MagicMock(status_code=502, ok=False)
        mock_resp.json.return_value = {}

        with patch.object(ed, '_request_with_backoff', return_value=mock_resp):
            res = ed.status()
            self.assertFalse(res)

    # ── Pillar 3: Easynews Auth Pipe Header & Retry ───────────────────────

    def test_easynews_unrestrict_link_appends_auth_pipe(self):
        from resources.lib.debrid.easynews import Easynews
        en = Easynews()
        en.username = 'testuser'
        en.password = 'testpass'

        farm_url = 'https://auto-farm.easynews.com/video/download.mp4'
        mock_result = (b'streamdata', '200', {}, {}, '', farm_url)

        with patch('resources.lib.ui.client.request', return_value=mock_result):
            res = en.unrestrict_link('https://members.easynews.com/dl/item')
            self.assertIsNotNone(res)
            self.assertTrue(res.startswith(farm_url))
            self.assertIn('|Authorization=', res)
            parsed_auth = urllib.parse.unquote(res.split('|Authorization=')[1])
            self.assertTrue(parsed_auth.startswith('Basic '))

    def test_easynews_unrestrict_link_retries_transient_error(self):
        from resources.lib.debrid.easynews import Easynews
        en = Easynews()
        en.username = 'testuser'
        en.password = 'testpass'

        farm_url = 'https://auto-farm.easynews.com/video/download.mp4'
        fail_result = (b'', '502', {}, {}, '', '')
        succ_result = (b'streamdata', '200', {}, {}, '', farm_url)

        with patch('resources.lib.ui.client.request', side_effect=[fail_result, succ_result]) as mock_req:
            res = en.unrestrict_link('https://members.easynews.com/dl/item')
            self.assertIsNotNone(res)
            self.assertEqual(mock_req.call_count, 2)

    # ── Pillar 4: Non-Destructive Database Migration ─────────────────────

    def test_database_sync_migrate_preserves_tables(self):
        from resources.lib.ui import database_sync

        sync = database_sync.SyncDatabase.__new__(database_sync.SyncDatabase)
        sync.last_meta_update = '1.0.14'
        sync.activites = {'otaku_version': '1.0.13'}

        # Mock SQL execution
        executed_statements = []
        class MockCursor:
            connection = MagicMock()
            def execute(self, sql, *args):
                executed_statements.append(sql)
            def fetchone(self):
                return {'name': 'watchlist_cache'}
            def fetchall(self):
                return [{'name': 'service'}, {'name': 'status'}, {'name': 'item_order'}]

        with patch.object(database_sync, 'SQL') as mock_sql, \
             patch.object(sync, '_create_all_tables'), \
             patch.object(sync, 'refresh_activites'), \
             patch.object(database_sync.SyncDatabase, '_build_watchlist_view'):
            mock_sql.return_value.__enter__.return_value = MockCursor()
            sync._migrate_database()

            # Confirm no DROP TABLE was executed during migration
            drop_statements = [s for s in executed_statements if 'DROP TABLE' in s]
            self.assertEqual(drop_statements, [])
            # Confirm activities version was updated
            replace_statements = [s for s in executed_statements if 'INSERT OR REPLACE INTO activities' in s]
            self.assertTrue(len(replace_statements) > 0)

    # ── Pillar 5: AnimeFiller Caching ─────────────────────────────────────

    def test_anime_filler_caching(self):
        from resources.lib.endpoints import anime_filler
        from resources.lib.ui import database

        with patch.object(database, 'get') as mock_db_get:
            mock_db_get.return_value = ['1', '2', '3']
            res = anime_filler.get_data('Naruto Shippuden')
            self.assertEqual(res, ['1', '2', '3'])
            mock_db_get.assert_called_once_with(anime_filler._fetch_filler_data, 168, 'Naruto Shippuden')

    # ── Pillar 6: Modal Dialog Cleanup & Abort Check ──────────────────────

    def test_still_watching_try_finally_del(self):
        from resources.lib.ui.player import WatchlistPlayer
        player = WatchlistPlayer()
        player.stillwatching_count = 2

        mock_dlg = MagicMock()
        mock_dlg.doModal.return_value = True

        with patch('resources.lib.ui.control.playerWindow.getProperty', return_value='2'), \
             patch('resources.lib.windows.still_watching.StillWatchingXML', return_value=mock_dlg):
            res = player._check_still_watching()
            self.assertTrue(res)

    def test_playing_next_waitForAbort(self):
        from resources.lib.windows.playing_next import PlayingNext
        from resources.lib.ui import control

        with patch('xbmc.Player') as mock_player_cls, \
             patch.object(control.monitor, 'waitForAbort', return_value=True) as mock_abort:
            p = mock_player_cls.return_value
            p.getPlayingFile.return_value = 'video.mkv'
            p.getTotalTime.return_value = 100
            p.getTime.return_value = 90

            pn = PlayingNext.__new__(PlayingNext)
            pn.player = p
            pn.playing_file = 'video.mkv'
            pn.closed = False
            pn.actioned = False
            pn.duration = 10
            pn.total_time = 100
            pn.default_action = 0
            pn.getControl = MagicMock()
            pn.close = MagicMock()

            pn.background_tasks()
            # Loop should exit immediately when waitForAbort returns True
            self.assertTrue(mock_abort.called)
            pn.close.assert_called()


if __name__ == '__main__':
    unittest.main()
