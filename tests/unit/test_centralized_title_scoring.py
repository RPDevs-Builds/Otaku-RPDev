# Standardized Otaku Test Bootstrap
import os
import sys

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_TEST_DIR, '..' if os.path.basename(_TEST_DIR) in ('unit', 'integration', 'lint') else '.'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
_TESTS_DIR = os.path.join(_REPO_ROOT, 'tests')
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import conftest  # Centralized Kodi mock harness  # noqa: F401

import unittest
from unittest.mock import patch

from resources.lib.ui import control, database, source_utils
from resources.lib.pages import Sources


class TestCentralizedTitleScoring(unittest.TestCase):
    """Hermetic unit tests for centralized title isolation, scoring, fuzzy matching, and source filtering."""

    def test_isolate_show_title_fansub_and_scene_formats(self):
        """Verify release title isolation strips release groups, codecs, resolutions, and episode titles."""
        cases = [
            ('[ASW] Monster - 01 [BD 1080p].mkv', 'Monster'),
            ('[SubsPlease] Re:Monster - 01 (1080p) [ABCD1234].mkv', 'Re:Monster'),
            ('[Judas] Monster Musume no Iru Nichijou - 01 [1080p].mkv', 'Monster Musume no Iru Nichijou'),
            ('[Erai-raws] Monster Hunter Stories - 01 [720p].mp4', 'Monster Hunter Stories'),
            ('[HorribleSubs] Pocket Monsters (2019) - 01 [720p].mkv', 'Pocket Monsters'),
            ('Attack on Titan - 05 - The Roar of the Monster.mkv', 'Attack on Titan'),
            ('Show Name - S01E05 - The Monster Within.mkv', 'Show Name'),
            ('[Coalgirls] K - 01 [1080p].mkv', 'K'),
            ('[Erai-raws] K-On! - 01 [720p].mkv', 'K-On!'),
            ('[Commie] Another - 01 [BD 720p AAC].mkv', 'Another'),
            ('Another World - 01.mkv', 'Another World'),
            ('[Exiled-Destiny] Air - 01 (1080p).mkv', 'Air'),
            ('[SubsPlease] Fairy Tail - 01 (1080p).mkv', 'Fairy Tail'),
            ('Avatar - The Last Airbender - 01.mkv', 'Avatar - The Last Airbender'),
            ('Monster.S01E01.1080p.BluRay.x264.mkv', 'Monster'),
            ('Re.Monster.S01E01.1080p.WEB-DL.mkv', 'Re Monster'),
            ('Monster - 01v2 [1080p].mkv', 'Monster'),
            ('Monster Ep 01 [1080p].mkv', 'Monster'),
            ('Monster Episode 1 [1080p].mkv', 'Monster'),
            ('[Judas] Monster (Season 1) [1080p]', 'Monster'),
            ('Bleach - 001 [1080p].mkv', 'Bleach'),
            ('Bleach: Thousand-Year Blood War - 01.mkv', 'Bleach: Thousand-Year Blood War'),
            ('Steins;Gate - 01 [1080p].mkv', 'Steins;Gate'),
            ('Fullmetal Alchemist: Brotherhood - 01 [1080p].mkv', 'Fullmetal Alchemist: Brotherhood'),
            ('Monster 01 (1080p).mkv', 'Monster'),
            ('[Beatrice-Raws] Monster 01 [BDRip 1920x1080 HEVC TrueHD].mkv', 'Monster'),
            ('Monster - E01 [1080p].mkv', 'Monster'),
            ('Monster.E01.1080p.mkv', 'Monster'),
            ('Monster.01.1080p.mkv', 'Monster'),
            ('Monster.S01E01.mkv', 'Monster'),
            ('Monster 01 [1080p].mkv', 'Monster'),
        ]
        for raw, expected in cases:
            isolated = source_utils.isolate_show_title(raw)
            self.assertEqual(isolated, expected, f"Failed isolating show title from '{raw}'")

    def test_clean_title_for_matching(self):
        """Verify clean_title_for_matching cleans punctuation and normalizes characters."""
        self.assertEqual(source_utils.clean_title_for_matching('[ASW] Monster - 01 [1080p].mkv'), 'monster')
        self.assertEqual(source_utils.clean_title_for_matching('[SubsPlease] Re:Monster - 01.mkv'), 're monster')
        self.assertEqual(source_utils.clean_title_for_matching('Steins;Gate - 01 [1080p].mkv'), 'steins gate')
        self.assertEqual(source_utils.clean_title_for_matching(''), '')
        self.assertEqual(source_utils.clean_title_for_matching(None), '')

    def test_get_fuzzy_match_monster_precision(self):
        """get_fuzzy_match('Monster', [...]) must exclusively match 'Monster' and strictly reject derivatives."""
        filenames = [
            '[ASW] Monster - 01 [BD 1080p].mkv',
            '[SubsPlease] Re:Monster - 01 (1080p).mkv',
            '[Judas] Monster Musume no Iru Nichijou - 01 [1080p].mkv',
            '[Erai-raws] Monster Hunter Stories - 01 [720p].mp4',
            '[HorribleSubs] Pocket Monsters (2019) - 01 [720p].mkv',
            'Attack on Titan - 05 - The Roar of the Monster.mkv',
            'Show Name - S01E05 - The Monster Within.mkv',
        ]
        matches = source_utils.get_fuzzy_match('Monster', filenames)
        self.assertEqual(matches, [0], f"Expected only index 0 for 'Monster', got {matches}")

    def test_get_fuzzy_match_short_queries_disambiguation(self):
        """Verify disambiguation behavior across notorious short-named anime."""
        # K vs K-On! vs Kill la Kill
        k_files = [
            '[Coalgirls] K - 01 [1080p].mkv',
            '[Erai-raws] K-On! - 01 [720p].mkv',
            '[Commie] Kill la Kill - 01.mkv'
        ]
        self.assertEqual(source_utils.get_fuzzy_match('K', k_files), [0])

        # Air vs Fairy Tail vs Avatar
        air_files = [
            '[Exiled-Destiny] Air - 01 (1080p).mkv',
            '[SubsPlease] Fairy Tail - 01 (1080p).mkv',
            'Avatar - The Last Airbender - 01.mkv'
        ]
        self.assertEqual(source_utils.get_fuzzy_match('Air', air_files), [0])

        # Another vs Another World
        another_files = [
            '[Commie] Another - 01 [BD 720p AAC].mkv',
            'Another World - 01.mkv'
        ]
        self.assertEqual(source_utils.get_fuzzy_match('Another', another_files), [0])

        # Re:Monster must match Re:Monster and reject Monster
        remonster_files = [
            '[ASW] Monster - 01 [BD 1080p].mkv',
            '[SubsPlease] Re:Monster - 01 (1080p).mkv',
        ]
        self.assertEqual(source_utils.get_fuzzy_match('Re:Monster', remonster_files), [1])

    def test_score_title_candidate_exact_and_alias_matches(self):
        """Exact canonical and alias matches must score >= 140."""
        self.assertGreaterEqual(source_utils.score_title_candidate('Monster', 'Monster'), 140)
        self.assertGreaterEqual(source_utils.score_title_candidate('Monster', '[ASW] Monster - 01 [BD 1080p].mkv'), 140)
        self.assertGreaterEqual(source_utils.score_title_candidate('Monster', 'Monster 01 (1080p).mkv'), 140)
        self.assertGreaterEqual(source_utils.score_title_candidate('Monster', '[Beatrice-Raws] Monster 01 [BDRip 1920x1080 HEVC TrueHD].mkv'), 140)
        self.assertGreaterEqual(source_utils.score_title_candidate('Monster', 'Monster - E01 [1080p].mkv'), 140)
        self.assertGreaterEqual(source_utils.score_title_candidate('Monster', 'Monster.E01.1080p.mkv'), 140)
        self.assertGreaterEqual(source_utils.score_title_candidate('Monster', 'Monster.01.1080p.mkv'), 140)
        self.assertGreaterEqual(source_utils.score_title_candidate('Monster', 'Monster.S01E01.mkv'), 140)
        self.assertGreaterEqual(source_utils.score_title_candidate('Steins;Gate', 'Steins Gate - 01.mkv'), 140)
        self.assertGreaterEqual(source_utils.score_title_candidate('Monster', 'Monster', year='2004'), 140)
        self.assertGreaterEqual(
            source_utils.score_title_candidate('Attack on Titan', 'Shingeki no Kyojin', aliases=['Shingeki no Kyojin']),
            140
        )
        self.assertGreaterEqual(
            source_utils.score_title_candidate('Fullmetal Alchemist: Brotherhood', 'Hagane no Renkinjutsushi', aliases=['Hagane no Renkinjutsushi']),
            140
        )

    def test_score_title_candidate_descriptors(self):
        """Matches with valid release descriptors ((Dub), (Sub), (TV), (Movie)) must score >= 110."""
        descriptors = ['Monster (Dub)', 'Monster (Sub)', 'Monster (TV)', 'Monster (Movie)', 'Monster Dual Audio']
        for cand in descriptors:
            score = source_utils.score_title_candidate('Monster', cand)
            self.assertGreaterEqual(score, 110, f"Expected descriptor score >= 110 for '{cand}', got {score}")

    def test_score_title_candidate_descriptor_bearing_aliases(self):
        """Aliases containing approved descriptors (e.g. (TV), (Movie)) must score >= 115."""
        # Forest of Piano with alias Piano no Mori (TV)
        score1 = source_utils.score_title_candidate(
            'Forest of Piano',
            'Piano no Mori (TV)',
            aliases=['Piano no Mori (TV)'],
            year='2018'
        )
        self.assertGreaterEqual(score1, 115, f"Expected >= 115 for descriptor-bearing alias, got {score1}")

        # Forest of Piano with clean candidate matching descriptor-bearing alias
        score1_clean = source_utils.score_title_candidate(
            'Forest of Piano',
            '[ASW] Piano no Mori - 01 [1080p].mkv',
            aliases=['Piano no Mori (TV)'],
            year='2018'
        )
        self.assertGreaterEqual(score1_clean, 115, f"Expected >= 115 for clean candidate matching descriptor alias, got {score1_clean}")

        # Piano no Mori with alias Forest of Piano (Movie)
        score2 = source_utils.score_title_candidate(
            'Piano no Mori',
            'Forest of Piano (Movie)',
            aliases=['Forest of Piano (Movie)'],
            year='2007'
        )
        self.assertGreaterEqual(score2, 115, f"Expected >= 115 for descriptor-bearing alias, got {score2}")

        score2_clean = source_utils.score_title_candidate(
            'Piano no Mori',
            '[Coalgirls] Forest of Piano [Movie 1080p].mkv',
            aliases=['Forest of Piano (Movie)'],
            year='2007'
        )
        self.assertGreaterEqual(score2_clean, 115, f"Expected >= 115 for clean candidate matching descriptor alias, got {score2_clean}")

    def test_score_title_candidate_derivative_rejection(self):
        """Derivative titles and episode title collisions must score <= 40 or 0."""
        derivatives = [
            'Re:Monster',
            'Re:Monster - 01.mkv',
            '[SubsPlease] Re:Monster - 01 (1080p).mkv',
            'Monster Musume',
            'Monster Musume no Iru Nichijou',
            'Monster Musume no Iru Nichijou - 01.mkv',
            'Monster Hunter Stories',
            'Pocket Monsters',
            'Attack on Titan - 05 - The Roar of the Monster.mkv',
            'Show Name - S01E05 - The Monster Within.mkv',
            'Monster: Dark Continent',
        ]
        for cand in derivatives:
            score = source_utils.score_title_candidate('Monster', cand)
            self.assertLessEqual(score, 40, f"Expected derivative score <= 40 for '{cand}', got {score}")

        # Symmetrical derivative check: query has Re:, candidate does not
        self.assertLessEqual(source_utils.score_title_candidate('Re:Monster', 'Monster'), 40)
        self.assertGreaterEqual(source_utils.score_title_candidate('Re:Monster', 'Re:Monster'), 140)

    def test_filter_sources_drops_derivative_torrents(self):
        """filter_sources with show_title specified must reject derivative torrents sharing episode numbers."""
        torrents = [
            {'name': '[ASW] Monster - 01 [BD 1080p].mkv', 'hash': 'hash_true_monster'},
            {'name': '[Beatrice-Raws] Monster 01 [BDRip 1920x1080 HEVC TrueHD].mkv', 'hash': 'hash_beatrice_monster'},
            {'name': 'Monster.S01E01.mkv', 'hash': 'hash_scene_monster'},
            {'name': '[SubsPlease] Re:Monster - 01 (1080p).mkv', 'hash': 'hash_remonster'},
            {'name': '[Judas] Monster Musume no Iru Nichijou - 01.mkv', 'hash': 'hash_musume'},
            {'name': '[Erai-raws] Monster Hunter Stories - 01.mp4', 'hash': 'hash_hunter'},
            {'name': 'Attack on Titan - 05 - The Roar of the Monster.mkv', 'hash': 'hash_aot_collision'},
        ]
        with patch('resources.lib.ui.database.get_mappings', return_value={}):
            filtered = source_utils.filter_sources('nyaa', torrents, mal_id=19, episode=1, show_title='Monster')

        accepted_hashes = {f['hash'] for f in filtered}
        self.assertEqual(accepted_hashes, {'hash_true_monster', 'hash_beatrice_monster', 'hash_scene_monster'})
        for f in filtered:
            self.assertGreaterEqual(f.get('relevance', 0), 140)

    def test_filter_sources_backward_compatibility_when_show_title_none(self):
        """filter_sources without show_title should maintain existing behavior."""
        torrents = [
            {'name': '[ASW] Monster - 01 [BD 1080p].mkv', 'hash': 'hash1'},
            {'name': '[SubsPlease] Re:Monster - 01 (1080p).mkv', 'hash': 'hash2'},
        ]
        with patch('resources.lib.ui.database.get_mappings', return_value={}):
            filtered = source_utils.filter_sources('nyaa', torrents, mal_id=19, episode=1)

        self.assertEqual(len(filtered), 2)

    def test_sort_sources_prioritizes_relevance_over_resolution(self):
        """sortSources must place genuine anime releases at rank 1 ahead of higher-resolution derivative releases."""
        sources = [
            {
                'release_title': '[SubsPlease] Re:Monster - 01 [1080p].mkv',
                'quality': 3,
                'type': 'torrent',
                'provider': 'nyaa',
                'size': '1.4 GB',
                'seeders': 100,
                'relevance': 0,
            },
            {
                'release_title': '[ASW] Monster - 01 [720p].mkv',
                'quality': 2,
                'type': 'torrent',
                'provider': 'nyaa',
                'size': '600 MB',
                'seeders': 20,
                'relevance': 150,
            }
        ]
        control.setSetting('general.fileFilter', '0')
        control.settings.setInt('general.minResolution', 0)
        control.settings.setInt('general.maxResolution', 10)

        sorted_sources = Sources.sortSources(
            torrent_list=sources,
            hoster_list=[],
            embed_list=[],
            cloud_files=[],
            local_files=[],
            media_type='show',
            duration=24,
            show_title='Monster'
        )

        self.assertTrue(len(sorted_sources) >= 1)
        self.assertEqual(sorted_sources[0]['release_title'], '[ASW] Monster - 01 [720p].mkv')


if __name__ == '__main__':
    unittest.main()
