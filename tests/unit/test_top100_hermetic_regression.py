"""
test_top100_hermetic_regression.py - Automated 5-Gate Hermetic Regression Test Suite
=====================================================================================
Operates 100% offline using tests/conftest.py socket interception.
Verifies provider search, candidate scoring, fuzzy matching, and source filtering
against the Top 100 anime dataset and comprehensive 18-genre dataset to guarantee
zero false-positive contamination for short-titled and derivative-named anime.

Gates:
- Gate 1 (test_fuzzy_match_short_titles_and_derivatives):
  Asserts get_fuzzy_match("Monster", ...) exclusively matches "Monster" releases
  and strictly rejects "Re:Monster", "Monster Musume", "Monster Hunter Stories",
  "Pocket Monsters", and episode titles like "The Monster Within".
  Also tests short titles: "Nana", "Bleach", "K", "C", "Air", "FLCL", "Another".
- Gate 2 (test_filter_sources_title_discrimination):
  Asserts filter_sources filters out torrents for "Re:Monster" and episode titles
  with "monster" when show_title="Monster".
- Gate 3 (test_scraper_candidate_scoring_top100):
  Asserts score_title_candidate scores exact canonical/alias matches >= 140,
  descriptor tags >= 110, and derivative/unrelated titles <= 40 across the dataset.
- Gate 4 (test_individual_scrapers_mocked):
  Mocks provider search responses for all 7 scrapers (hianime, gogoanime, animepahe,
  anikoto, watchnixtoons2, animetosho, nyaa) with both matching and derivative
  candidates, verifying that exact canonical matches are selected and derivative
  candidates like "Re:Monster" are strictly excluded.
- Gate 5 (test_comprehensive_parametric_matrix):
  Parametrically iterates through the unified comprehensive dataset to verify candidate
  scoring, fuzzy matching, and zero false-positive contamination in < 5.0 seconds.
"""

import json
import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_TEST_DIR, '..' if os.path.basename(_TEST_DIR) in ('unit', 'integration', 'lint') else '.'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
_TESTS_DIR = os.path.join(_REPO_ROOT, 'tests')
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import conftest  # Centralized Kodi mock harness & socket blocker  # noqa: F401

from resources.lib.ui import control, database, source_utils
from resources.lib.pages import Sources
from resources.lib.pages.hianime import Sources as HiAnimeSources
from resources.lib.pages.gogoanime import Sources as GogoanimeSources
from resources.lib.pages.animepahe import Sources as AnimePaheSources
from resources.lib.pages.watchnixtoons2 import Sources as WNT2Sources
from resources.lib.pages.nyaa import Sources as NyaaSources
from resources.lib.pages.animetosho import Sources as AnimeToshoSources
from resources.lib.pages.anikoto import Sources as AnikotoSources


class TestTop100HermeticRegression(unittest.TestCase):
    """Automated 5-Gate Hermetic Regression Test Suite."""

    @classmethod
    def setUpClass(cls):
        cls.fixtures_dir = os.path.abspath(os.path.join(_TEST_DIR, '..', 'fixtures'))
        cls.top_100_path = os.path.join(cls.fixtures_dir, 'top_100_anime_dataset.json')
        cls.comp_path = os.path.join(cls.fixtures_dir, 'comprehensive_anime_dataset.json')

        with open(cls.top_100_path, 'r', encoding='utf-8') as f:
            cls.top_100_dataset = json.load(f)

        with open(cls.comp_path, 'r', encoding='utf-8') as f:
            cls.comp_dataset = json.load(f)

    def setUp(self):
        control.clearSettingsCache()
        control.settings.setInt('general.source', 0)

    def tearDown(self):
        control.clearSettingsCache()
        control.settings.setInt('general.source', 0)
        control.cleanup()

    # ═════════════════════════════════════════════════════════════════════════
    #  GATE 1: Fuzzy Matching & Short-Title Disambiguation
    # ═════════════════════════════════════════════════════════════════════════

    def test_fuzzy_match_short_titles_and_derivatives(self):
        """
        Gate 1: Assert get_fuzzy_match exclusively matches target releases and strictly
        rejects derivative titles, other series, and episode titles containing the query word.
        """
        # 1. Monster
        monster_files = [
            '[ASW] Monster - 01 [BD 1080p].mkv',
            '[SubsPlease] Re:Monster - 01 (1080p).mkv',
            '[Judas] Monster Musume no Iru Nichijou - 01 [1080p].mkv',
            '[Erai-raws] Monster Hunter Stories - 01 [720p].mp4',
            '[HorribleSubs] Pocket Monsters (2019) - 01 [720p].mkv',
            'Show Name - S01E05 - The Monster Within.mkv',
            'Attack on Titan - 05 - The Roar of the Monster.mkv',
        ]
        matches = source_utils.get_fuzzy_match('Monster', monster_files)
        self.assertEqual(matches, [0], f"Expected exclusively index 0 for 'Monster', got {matches}")

        # 2. Nana
        nana_files = [
            '[Commie] Nana - 01 [720p].mkv',
            '[SubsPlease] Munou na Nana - 01 (1080p).mkv',
            '[Erai-raws] Nanatsu no Taizai - 01 [720p].mp4',
            'Nana (Live Action) 2005.mkv',
        ]
        self.assertEqual(source_utils.get_fuzzy_match('Nana', nana_files), [0])

        # 3. Bleach
        bleach_files = [
            '[AnimeRG] Bleach - 001 [720p].mkv',
            '[SubsPlease] Bleach: Thousand-Year Blood War - 01 (1080p).mkv',
            '[Erai-raws] Burn the Witch - 01 [1080p].mkv',
            'Show - 01 - The Bleach Incident.mkv',
        ]
        self.assertEqual(source_utils.get_fuzzy_match('Bleach', bleach_files), [0])

        # 4. K
        k_files = [
            '[Coalgirls] K - 01 [1080p].mkv',
            '[Erai-raws] K-On! - 01 [720p].mkv',
            '[Commie] Kill la Kill - 01.mkv',
            '[MSubs] Special A - 01.mkv',
        ]
        self.assertEqual(source_utils.get_fuzzy_match('K', k_files), [0])

        # 5. C
        c_files = [
            '[Commie] C - 01 [720p].mkv',
            '[Erai-raws] Code Geass - 01 [1080p].mkv',
            'Generic Anime S01E01 AVC AAC.mkv',
        ]
        self.assertEqual(source_utils.get_fuzzy_match('C', c_files), [0])

        # 6. Air
        air_files = [
            '[Exiled-Destiny] Air - 01 (1080p).mkv',
            '[SubsPlease] Fairy Tail - 01 (1080p).mkv',
            'Avatar - The Last Airbender - 01.mkv',
            '[AnimeRG] Air Gear - 01 [720p].mkv',
        ]
        self.assertEqual(source_utils.get_fuzzy_match('Air', air_files), [0])

        # 7. FLCL
        flcl_files = [
            '[Coalgirls] FLCL - 01 [1080p].mkv',
            '[SubsPlease] FLCL Progressive - 01 (1080p).mkv',
            '[Erai-raws] FLCL Alternative - 01 [1080p].mkv',
        ]
        self.assertEqual(source_utils.get_fuzzy_match('FLCL', flcl_files), [0])

        # 8. Another
        another_files = [
            '[Commie] Another - 01 [BD 720p AAC].mkv',
            'Another World - 01.mkv',
            'Another Century - 01.mkv',
        ]
        self.assertEqual(source_utils.get_fuzzy_match('Another', another_files), [0])

        # 9. Symmetrical Re: prefix verification (Re:Monster must match Re:Monster and reject Monster)
        remonster_files = [
            '[ASW] Monster - 01 [BD 1080p].mkv',
            '[SubsPlease] Re:Monster - 01 (1080p).mkv',
        ]
        self.assertEqual(source_utils.get_fuzzy_match('Re:Monster', remonster_files), [1])

    # ═════════════════════════════════════════════════════════════════════════
    #  GATE 2: Title Discrimination in Source Filtering
    # ═════════════════════════════════════════════════════════════════════════

    def test_filter_sources_title_discrimination(self):
        """
        Gate 2: Assert filter_sources filters out torrents for 'Re:Monster' and episode
        titles with 'monster' when show_title='Monster'.
        """
        torrents = [
            {'name': '[ASW] Monster - 01 [BD 1080p].mkv', 'hash': 'hash_monster_bd'},
            {'name': 'Monster.S01E01.1080p.BluRay.x264.mkv', 'hash': 'hash_monster_scene'},
            {'name': '[SubsPlease] Re:Monster - 01 (1080p).mkv', 'hash': 'hash_remonster'},
            {'name': '[Judas] Monster Musume no Iru Nichijou - 01 [1080p].mkv', 'hash': 'hash_musume'},
            {'name': '[Erai-raws] Monster Hunter Stories - 01 [720p].mp4', 'hash': 'hash_hunter'},
            {'name': 'Show Name - S01E01 - The Monster Within.mkv', 'hash': 'hash_episode_trap'},
            {'name': 'Attack on Titan - 01 - The Roar of the Monster.mkv', 'hash': 'hash_aot_trap'},
        ]

        with patch('resources.lib.ui.database.get_mappings', return_value={}):
            # Test nyaa provider
            filtered_nyaa = source_utils.filter_sources(
                'nyaa', torrents, mal_id=19, episode=1, show_title='Monster',
                aliases=["Naoki Urasawa's Monster"]
            )
            # Test animetosho provider
            filtered_tosho = source_utils.filter_sources(
                'animetosho', torrents, mal_id=19, episode=1, show_title='Monster'
            )

        for filtered in [filtered_nyaa, filtered_tosho]:
            accepted_hashes = {f['hash'] for f in filtered}
            self.assertEqual(accepted_hashes, {'hash_monster_bd', 'hash_monster_scene'})
            for item in filtered:
                self.assertGreaterEqual(item.get('relevance', 0), 140)

        # Discard derivative torrents for another short title: 'Nana'
        nana_torrents = [
            {'name': '[Commie] Nana - 01 [720p].mkv', 'hash': 'hash_nana'},
            {'name': '[SubsPlease] Munou na Nana - 01 (1080p).mkv', 'hash': 'hash_munou_nana'},
            {'name': '[Erai-raws] Nanatsu no Taizai - 01 [720p].mp4', 'hash': 'hash_nanatsu'},
        ]
        with patch('resources.lib.ui.database.get_mappings', return_value={}):
            filtered_nana = source_utils.filter_sources(
                'nyaa', nana_torrents, mal_id=877, episode=1, show_title='Nana'
            )
        self.assertEqual({f['hash'] for f in filtered_nana}, {'hash_nana'})

    # ═════════════════════════════════════════════════════════════════════════
    #  GATE 3: Centralized Candidate Scoring Across Top 100 Dataset
    # ═════════════════════════════════════════════════════════════════════════

    def test_scraper_candidate_scoring_top100(self):
        """
        Gate 3: Assert score_title_candidate scores exact canonical/alias matches >= 140,
        descriptor tags >= 110, and derivative/unrelated titles <= 40 across Top 100.
        """
        self.assertGreaterEqual(len(self.top_100_dataset), 100)

        for entry in self.top_100_dataset:
            title = entry['title']
            aliases = entry.get('aliases', [])
            distractors = entry.get('distractors', [])
            year = str(entry.get('year', ''))

            # 1. Exact canonical title match >= 140
            score_exact = source_utils.score_title_candidate(title, title, aliases=aliases, year=year)
            self.assertGreaterEqual(
                score_exact, 140,
                f"Failed canonical match for '{title}' (score: {score_exact})"
            )

            # 2. Alias matches >= 140
            for alias in aliases:
                score_alias = source_utils.score_title_candidate(title, alias, aliases=aliases, year=year)
                self.assertGreaterEqual(
                    score_alias, 140,
                    f"Failed alias match '{alias}' for '{title}' (score: {score_alias})"
                )

            # 3. Approved release descriptors ((Dub), (Sub)) >= 110
            for desc in ['(Dub)', '(Sub)']:
                cand = f"{title} {desc}"
                score_desc = source_utils.score_title_candidate(title, cand, aliases=aliases, year=year)
                self.assertGreaterEqual(
                    score_desc, 110,
                    f"Failed descriptor match '{cand}' for '{title}' (score: {score_desc})"
                )

            # 4. Derivative and adversarial distractors <= 40
            for dist in distractors:
                score_dist = source_utils.score_title_candidate(title, dist, aliases=aliases, year=year)
                self.assertLessEqual(
                    score_dist, 40,
                    f"Distractor '{dist}' for '{title}' improperly scored {score_dist} (> 40)"
                )

    # ═════════════════════════════════════════════════════════════════════════
    #  GATE 4: Individual Scrapers Mocked Verification (7 Scrapers)
    # ═════════════════════════════════════════════════════════════════════════

    def test_individual_scrapers_mocked(self):
        """
        Gate 4: Mock provider search responses for all 7 scrapers with both matching
        and derivative candidates, verifying that exact canonical matches are selected
        and derivative candidates like 'Re:Monster' are strictly excluded.
        """
        # 1. HiAnime (hianime.py)
        hianime = HiAnimeSources()
        hianime_html = '''
        <div class="flw-item">
            <a class="film-poster-ahref" href="/re-monster-19123"></a>
            <h3 class="film-name"><a href="/re-monster-19123">Re:Monster</a></h3>
        </div>
        <div class="flw-item">
            <a class="film-poster-ahref" href="/monster-1234"></a>
            <h3 class="film-name"><a href="/monster-1234">Monster</a></h3>
        </div>
        '''
        with patch('resources.lib.ui.database.get', return_value=hianime_html):
            anime_id = hianime._resolve_anime_id('https://mirror.test/', 'Monster', None, 19, {})
            self.assertEqual(anime_id, '1234')

        # When only derivative candidate exists in HiAnime
        hianime_deriv_only = '''
        <div class="flw-item">
            <a class="film-poster-ahref" href="/re-monster-19123"></a>
            <h3 class="film-name"><a href="/re-monster-19123">Re:Monster</a></h3>
        </div>
        '''
        with patch('resources.lib.ui.database.get', return_value=hianime_deriv_only):
            anime_id_none = hianime._resolve_anime_id('https://mirror.test/', 'Monster', None, 19, {})
            self.assertIsNone(anime_id_none)

        # 2. Gogoanime (gogoanime.py)
        gogo = GogoanimeSources()
        gogo_show_data = {'kodi_meta': '{"name": "Monster", "ename": "Monster", "year": 2004}'}
        gogo_search_html = '''
        <div class="last_episodes">
            <ul class="items">
                <li><p class="name"><a href="/category/re-monster" title="Re:Monster">Re:Monster</a></p></li>
                <li><p class="name"><a href="/category/monster" title="Monster">Monster</a></p></li>
                <li><p class="name"><a href="/category/monster-dub" title="Monster (Dub)">Monster (Dub)</a></p></li>
                <li><p class="name"><a href="/category/monster-musume" title="Monster Musume">Monster Musume</a></p></li>
            </ul>
        </div>
        '''
        with patch('resources.lib.ui.database.get_show', return_value=gogo_show_data), \
             patch('resources.lib.ui.database.get', return_value=gogo_search_html), \
             patch('resources.lib.ui.control.getInt', side_effect=lambda key, default=0: 0 if key == 'general.source' else default), \
             patch.object(gogo, '_process_gogo', return_value=[{'release_title': 'source'}]) as mock_gogo:
            gogo.get_sources(19, 1)
            called_slugs = [call[0][0] for call in mock_gogo.call_args_list]
            self.assertIn('monster', called_slugs)
            self.assertIn('monster-dub', called_slugs)
            self.assertNotIn('re-monster', called_slugs)
            self.assertNotIn('monster-musume', called_slugs)

        # 3. AnimePahe (animepahe.py)
        animepahe = AnimePaheSources()
        ap_show_data = {'kodi_meta': '{"name": "Monster"}'}
        ap_sitems = json.dumps({
            "data": [
                {"title": "Re:Monster", "session": "session_re", "year": 2024},
                {"title": "Monster", "session": "session_monster", "year": 2004}
            ]
        })
        with patch('resources.lib.ui.database.get_show', return_value=ap_show_data), \
             patch('resources.lib.endpoints.malsync.get_title', return_value='Monster'), \
             patch.object(animepahe, '_resolve_session_from_malsync', return_value=None), \
             patch('resources.lib.ui.database.get', return_value=ap_sitems), \
             patch.object(animepahe, '_process_ap', return_value=[{'release_title': 'ap_src'}]) as mock_ap:
            res = animepahe.get_sources(19, 1)
            self.assertEqual(len(res), 1)
            mock_ap.assert_called_once_with('session_monster', title='Monster', episode=1)

        # 4. Anikoto (anikoto.py)
        anikoto = AnikotoSources()
        self.assertGreaterEqual(anikoto._score_candidate('Monster', 'Monster'), 140)
        self.assertLessEqual(anikoto._score_candidate('Monster', 'Re:Monster'), 40)
        with patch('resources.lib.ui.database.get_show', return_value={'kodi_meta': '{"name": "Monster"}'}), \
             patch.object(anikoto, '_build_source', return_value={'release_title': 'src'}) as mock_anikoto:
            anikoto.get_sources(19, 1)
            for call in mock_anikoto.call_args_list:
                embed_url = call[0][0]
                self.assertIn('/stream/mal/19/1/', embed_url)

        # 5. WatchNixtoons2 (watchnixtoons2.py)
        wnt2 = WNT2Sources()
        self.assertTrue(wnt2._titles_match('Monster', 'Monster (Dubbed)'))
        self.assertFalse(wnt2._titles_match('Monster', 'Re:Monster Subbed'))
        self.assertFalse(wnt2._titles_match('Monster', 'Monster Musume Subbed'))
        series_results = [
            {'title': 'Re:Monster Subbed', 'url': 'https://wco.test/re'},
            {'title': 'Monster (Dubbed)', 'url': 'https://wco.test/m-dub'},
            {'title': 'Monster Musume Subbed', 'url': 'https://wco.test/musume'},
        ]
        variants = wnt2._get_series_variants(series_results, query='Monster')
        variant_titles = [v['title'] for v in variants]
        self.assertIn('Monster (Dubbed)', variant_titles)
        self.assertNotIn('Re:Monster Subbed', variant_titles)
        self.assertNotIn('Monster Musume Subbed', variant_titles)

        # 6. AnimeTosho (animetosho.py)
        animetosho = AnimeToshoSources()
        tosho_torrents = [
            {'name': 'Monster - 01.mkv', 'hash': 'hash_monster'},
            {'name': 'Re:Monster - 01.mkv', 'hash': 'hash_remonster'},
        ]
        res_tosho = source_utils.filter_sources('animetosho', tosho_torrents, 19, season=1, episode=1, show_title='Monster')
        self.assertEqual([r['hash'] for r in res_tosho], ['hash_monster'])

        # 7. Nyaa (nyaa.py)
        nyaa = NyaaSources()
        nyaa_html = '''
        <div class="table-responsive">
            <table>
                <tr class="default">
                    <td><a href="/c/1_2">Anime</a></td>
                    <td><a href="/view/1" title="[ASW] Monster - 01 [BD 1080p].mkv">[ASW] Monster - 01 [BD 1080p].mkv</a></td>
                    <td><a href="magnet:?xt=urn:btih:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"></a></td>
                    <td class="text-center">500 MiB</td>
                    <td class="text-center"></td>
                    <td class="text-center">50</td>
                    <td class="text-center">5</td>
                    <td class="text-center">100</td>
                </tr>
                <tr class="default">
                    <td><a href="/c/1_2">Anime</a></td>
                    <td><a href="/view/2" title="[SubsPlease] Re:Monster - 01 (1080p).mkv">[SubsPlease] Re:Monster - 01 (1080p).mkv</a></td>
                    <td><a href="magnet:?xt=urn:btih:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"></a></td>
                    <td class="text-center">500 MiB</td>
                    <td class="text-center"></td>
                    <td class="text-center">150</td>
                    <td class="text-center">1</td>
                    <td class="text-center">300</td>
                </tr>
            </table>
        </div>
        '''
        mock_resp = MagicMock(text=nyaa_html)
        with patch('resources.lib.ui.client.get', return_value=mock_resp), \
             patch('resources.lib.ui.database.get_mappings', return_value={}):
            nyaa_filtered = nyaa._fetch_and_filter_episodes(
                'https://nyaa.test/', {}, mal_id=19, episode_zfill='01', season_zfill='01', part=None, show_title='Monster'
            )
            nyaa_hashes = [f['hash'].lower() for f in nyaa_filtered]
            self.assertEqual(nyaa_hashes, ['aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'])

    # ═════════════════════════════════════════════════════════════════════════
    #  GATE 5: Comprehensive Parametric Matrix Execution
    # ═════════════════════════════════════════════════════════════════════════

    def test_comprehensive_parametric_matrix(self):
        """
        Gate 5: Parametrically iterate through the unified comprehensive dataset
        to verify candidate scoring, fuzzy matching, and zero false-positive contamination.
        Assert execution duration < 5.0 seconds.
        """
        self.assertGreaterEqual(len(self.comp_dataset), 500)

        start_time = time.time()
        score_failures = []
        fuzzy_failures = []

        for item in self.comp_dataset:
            title = item['title']
            aliases = item.get('aliases', [])
            distractors = item.get('distractors', [])
            year = str(item.get('year', ''))

            # 1. Canonical self-score >= 140
            s_self = source_utils.score_title_candidate(title, title, aliases=aliases, year=year)
            if s_self < 140:
                score_failures.append((title, 'self', s_self))

            # 2. Release descriptor >= 110
            s_desc = source_utils.score_title_candidate(title, f"{title} (Dub)", aliases=aliases, year=year)
            if s_desc < 110:
                score_failures.append((title, 'descriptor', s_desc))

            # 3. All defined aliases >= 115
            for alias in aliases:
                s_alias = source_utils.score_title_candidate(title, alias, aliases=aliases, year=year)
                if s_alias < 115:
                    score_failures.append((title, f"alias:{alias}", s_alias))

            # 4. All adversarial distractors <= 40
            for dist in distractors:
                s_dist = source_utils.score_title_candidate(title, dist, aliases=aliases, year=year)
                if s_dist > 40:
                    score_failures.append((title, dist, s_dist))

            # 5. Fuzzy match disambiguation: exclusively returns index 0 and 0 distractors
            filenames = [f"[ASW] {title} - 01 [1080p].mkv"] + [
                (f"[SubsPlease] {d}" if d.endswith('.mkv') else f"[SubsPlease] {d} - 01 (1080p).mkv")
                for d in distractors
            ]
            matches = source_utils.get_fuzzy_match(title, filenames)
            if 0 not in matches:
                fuzzy_failures.append((title, 'exact match index 0 missing', matches))
            bad_matches = [idx for idx in matches if idx != 0]
            if bad_matches:
                fuzzy_failures.append((title, 'distractor contaminated matches', bad_matches))

        elapsed = time.time() - start_time

        self.assertEqual(score_failures, [], f"Candidate scoring failures detected: {score_failures[:5]}")
        self.assertEqual(fuzzy_failures, [], f"Fuzzy matching false-positive contamination detected: {fuzzy_failures[:5]}")
        self.assertLess(elapsed, 5.0, f"Parametric matrix took {elapsed:.2f}s, expected < 5.0s")


if __name__ == '__main__':
    unittest.main()
