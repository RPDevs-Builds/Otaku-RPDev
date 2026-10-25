import unittest
from unittest.mock import MagicMock, patch

import tests.conftest  # noqa: F401
from resources.lib.ui import control
from resources.lib.AnimeSchedule import AnimeScheduleCalendar


class TestResilienceAndUIV5416(unittest.TestCase):

    def test_sensitive_settings_does_not_contain_trakt_token(self):
        """Verify trakt.token is removed from _SENSITIVE_SETTING_KEYS to prevent Kodi C++ exceptions."""
        self.assertNotIn('trakt.token', control._SENSITIVE_SETTING_KEYS)
        self.assertIn('realdebrid.token', control._SENSITIVE_SETTING_KEYS)
        self.assertIn('mal.token', control._SENSITIVE_SETTING_KEYS)

    def test_sanitize_log_redaction_works_cleanly(self):
        """Verify sanitize_log scrubs bearer tokens and sensitive keys cleanly."""
        msg = "Authorization: Bearer secret_token_12345"
        sanitized = control.sanitize_log(msg)
        self.assertIn("Authorization: Bearer [REDACTED]", sanitized)
        self.assertNotIn("secret_token_12345", sanitized)

    def test_set_info_studio_normalization_list(self):
        """Verify set_videotags assigns only the primary animation studio to setStudios and stores full list in Studios property."""
        li = MagicMock()
        vinfo = MagicMock()
        li.getVideoInfoTag.return_value = vinfo

        info = {
            'title': 'Test Show',
            'studio': ['REVOROOT', 'Pony Canyon', 'SB Creative']
        }
        control.set_videotags(li, info)

        vinfo.setStudios.assert_called_once_with(['REVOROOT'])
        li.setProperty.assert_any_call('Studios', 'REVOROOT / Pony Canyon / SB Creative')

    def test_set_info_studio_normalization_string(self):
        """Verify set_videotags normalizes slash-delimited studio strings to primary studio."""
        li = MagicMock()
        vinfo = MagicMock()
        li.getVideoInfoTag.return_value = vinfo

        info = {
            'title': 'Test Show',
            'studio': 'WIT STUDIO / CloverWorks / Toho'
        }
        control.set_videotags(li, info)

        vinfo.setStudios.assert_called_once_with(['WIT STUDIO'])
        li.setProperty.assert_any_call('Studios', 'WIT STUDIO / CloverWorks / Toho')

    @patch('resources.lib.AnimeSchedule.client.get')
    def test_animeschedule_season_passes_auth_header(self, mock_get):
        """Verify _fetch_season_anime passes Authorization Bearer token."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'anime': []}
        mock_get.return_value = mock_resp

        scheduler = AnimeScheduleCalendar()
        scheduler.token = 'test_as_token_abc'

        scheduler._fetch_season_anime(2024, 'fall', 1)

        self.assertTrue(mock_get.called)
        _, kwargs = mock_get.call_args
        self.assertIn('headers', kwargs)
        self.assertEqual(kwargs['headers'].get('Authorization'), 'Bearer test_as_token_abc')

    @patch('resources.lib.AnimeSchedule.client.get')
    def test_animeschedule_route_search_passes_auth_header(self, mock_get):
        """Verify _search_anime_by_route passes Authorization Bearer token."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'title': 'Dandadan', 'websites': {'mal': 'myanimelist.net/anime/57334/Dandadan'}}
        mock_get.return_value = mock_resp

        scheduler = AnimeScheduleCalendar()
        scheduler.token = 'test_as_token_abc'

        res = scheduler._search_anime_by_route('dandadan')

        self.assertIsNotNone(res)
        self.assertTrue(mock_get.called)
        _, kwargs = mock_get.call_args
        self.assertIn('headers', kwargs)
        self.assertEqual(kwargs['headers'].get('Authorization'), 'Bearer test_as_token_abc')

    @patch('resources.lib.AnimeSchedule.client.get')
    def test_animeschedule_get_anime_by_mal_id_passes_auth_header(self, mock_get):
        """Verify get_anime_by_mal_id passes Authorization Bearer token."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'anime': []}
        mock_get.return_value = mock_resp

        scheduler = AnimeScheduleCalendar()
        scheduler.token = 'test_as_token_abc'

        scheduler.get_anime_by_mal_id(57334)

        self.assertTrue(mock_get.called)
        _, kwargs = mock_get.call_args
        self.assertIn('headers', kwargs)
        self.assertEqual(kwargs['headers'].get('Authorization'), 'Bearer test_as_token_abc')

    def test_playing_next_duration_clamp(self):
        """Verify PlayingNext clamps duration to max(1, duration) when total_time equals or precedes currentTime."""
        from resources.lib.windows.playing_next import PlayingNext

        with patch('xbmc.Player') as mock_player:
            player_inst = MagicMock()
            player_inst.getTotalTime.return_value = 100
            player_inst.getTime.return_value = 100  # remainder 0
            player_inst.getPlayingFile.return_value = "video.mkv"
            mock_player.return_value = player_inst

            pn = PlayingNext('playing_next.xml', '/mock/path', actionArgs={'skipoutro_end': 0})
            self.assertGreaterEqual(pn.duration, 1)

    def test_source_select_negative_position_safety(self):
        """Verify source_select handles position = -1 safely without IndexError."""
        from resources.lib.windows.source_select import SourceSelect

        ss = SourceSelect.__new__(SourceSelect)
        ss.displayed_sources = []
        ss.position = -1
        ss.display_list = MagicMock()
        ss.display_list.getSelectedPosition.return_value = -1

        # Must not raise IndexError
        action = MagicMock()
        action.getId.return_value = 7
        ss.getFocusId = MagicMock(return_value=1000)
        ss.resolve_item = MagicMock()

        ss.onAction(action)
        ss.resolve_item.assert_not_called()

    def test_textviewer_select_keys(self):
        """Verify textviewer dismisses on remote SELECT/ENTER keys (action IDs 7 and 100)."""
        from resources.lib.windows.textviewer import TextViewerXML

        tv = TextViewerXML.__new__(TextViewerXML)
        tv.close = MagicMock()
        tv.actioned = None

        action_enter = MagicMock()
        action_enter.getId.return_value = 7
        tv.onAction(action_enter)
        self.assertTrue(tv.actioned)
        tv.close.assert_called_once()

        tv.actioned = None
        tv.close.reset_mock()
        action_select = MagicMock()
        action_select.getId.return_value = 100
        tv.onAction(action_select)
        self.assertTrue(tv.actioned)
        tv.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
