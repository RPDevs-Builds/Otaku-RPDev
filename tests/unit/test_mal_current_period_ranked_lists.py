"""Regression: ranked 'this season/year' MAL lists must not send end_date (Jikan matches aired.to)."""
import datetime
import unittest
from unittest.mock import patch

from resources.lib.MalBrowser import MalBrowser


def _item(mal_id, aired_from):
    return {'mal_id': mal_id, 'aired': {'from': aired_from}}


class TestCurrentPeriodRankedLists(unittest.TestCase):
    def setUp(self):
        with patch('resources.lib.ui.control.getInt', return_value=0):
            self.b = MalBrowser()
        self.b.perpage = 20

    def test_this_season_drops_end_date_and_sets_post_filter(self):
        captured = {}

        def fake_list(page, fmt, prefix, slug, extra, relax_on_empty=False, post_filter=None, **kw):
            captured.update(extra=extra, post_filter=post_filter)
            return []

        with patch.object(self.b, '_browse_mal_anime_list', side_effect=fake_list):
            self.b._ranked_mal_list(1, 'tv', 'p', 'trending_this_season', 'members', 'desc', 'this_season')
        self.assertIn('start_date', captured['extra'])
        self.assertNotIn('end_date', captured['extra'])
        self.assertIsNotNone(captured['post_filter'])

    def test_last_season_keeps_end_date(self):
        captured = {}

        def fake_list(page, fmt, prefix, slug, extra, relax_on_empty=False, post_filter=None, **kw):
            captured.update(extra=extra, post_filter=post_filter)
            return []

        with patch.object(self.b, '_browse_mal_anime_list', side_effect=fake_list):
            self.b._ranked_mal_list(1, 'tv', 'p', 'trending_last_season', 'members', 'desc', 'last_season')
        self.assertIn('end_date', captured['extra'])
        self.assertIsNone(captured['post_filter'])

    def test_post_filter_trims_future_starts(self):
        keep = MalBrowser._aired_from_not_after(datetime.date(2026, 12, 31))
        self.assertTrue(keep(_item(1, '2026-11-07T00:00:00+00:00')))
        self.assertTrue(keep(_item(2, None)))
        self.assertFalse(keep(_item(3, '2027-01-05T00:00:00+00:00')))
        res = {'data': [_item(1, '2026-10-02'), _item(3, '2027-01-05')], 'pagination': {}}
        out = MalBrowser._apply_post_filter(res, keep)
        self.assertEqual([x['mal_id'] for x in out['data']], [1])
        self.assertEqual(len(res['data']), 2)  # cached object untouched


if __name__ == '__main__':
    unittest.main()
