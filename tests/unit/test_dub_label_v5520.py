import datetime
import unittest
from unittest.mock import patch, MagicMock

from resources.lib import endpoints
from resources.lib.endpoints import animeschedule
from resources.lib.ui import control


class TestDubLabel(unittest.TestCase):
    def setUp(self):
        control.clearSettingsCache()

    def test_only_unreleased_dub_shown(self):
        now = datetime.datetime.now()
        fut = (now + datetime.timedelta(days=1)).strftime('%Y-%m-%d %H:%M')
        past = (now - datetime.timedelta(days=1)).strftime('%Y-%m-%d %H:%M')
        data = [{'season': 0, 'episode': 8, 'release_time': fut},
                {'season': 0, 'episode': 7, 'release_time': past}]
        self.assertEqual(endpoints.get_second_label({'episode': 8, 'season': 2}, data), f'Dub {fut}')
        self.assertIsNone(endpoints.get_second_label({'episode': 7, 'season': 2}, data))

    def test_add_to_list_converts_offset_and_is_not_shared(self):
        a = []
        animeschedule.add_to_list(a, 8, '2026-10-28T09:30-04:00')
        expected = datetime.datetime(2026, 10, 28, 9, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=-4)))
        expected = str(expected.astimezone().replace(tzinfo=None))[:16]
        self.assertEqual(a[0]['release_time'], expected)
        self.assertFalse(hasattr(animeschedule, 'dub_list'))

    def test_label2_set_for_dub_code(self):
        liz = MagicMock()
        with patch('resources.lib.ui.control.xbmcgui.ListItem', return_value=liz), \
             patch('resources.lib.ui.control.set_videotags'), \
             patch('resources.lib.ui.control.addon_url', return_value='u'):
            try:
                control.xbmc_add_dir('Ep', 'x', {'fanart': '', 'icon': ''}, {'code': 'Dub 2026-10-28 09:30'}, None, True, False, True)
            except Exception:
                pass
        liz.setLabel2.assert_called_with('Dub 2026-10-28 09:30')


if __name__ == '__main__':
    unittest.main()
