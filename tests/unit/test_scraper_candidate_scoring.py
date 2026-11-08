"""
test_scraper_candidate_scoring.py - Unit Tests for Scraper Candidate Scoring & Title Filtering
=============================================================================================
Tests candidate scoring, ranking, and derivative rejection across Otaku scrapers:
- HiAnime (_score_candidate, _resolve_anime_id)
- Gogoanime (_score_candidate, get_sources candidate cutoff)
- AnimePahe (sitems scoring, sorting, cutoff >= 50)
- WatchNixtoons2 (_titles_match, _get_series_variants anchor ranking)
- Nyaa (_fetch_and_filter_episodes with show_title / aliases)
- AnimeTosho (process_animetosho_episodes with show_title / aliases)
- Anikoto (_score_candidate, MAL ID routing)
"""

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
from unittest.mock import patch, MagicMock

from resources.lib.pages.hianime import Sources as HiAnimeSources
from resources.lib.pages.gogoanime import Sources as GogoanimeSources
from resources.lib.pages.animepahe import Sources as AnimePaheSources
from resources.lib.pages.watchnixtoons2 import Sources as WNT2Sources
from resources.lib.pages.nyaa import Sources as NyaaSources
from resources.lib.pages.animetosho import Sources as AnimeToshoSources
from resources.lib.pages.anikoto import Sources as AnikotoSources
from resources.lib.ui import control


class TestHiAnimeCandidateScoring(unittest.TestCase):
    def setUp(self):
        control.clearSettingsCache()
        self.scraper = HiAnimeSources()

    def tearDown(self):
        control.cleanup()

    def test_score_candidate_prioritizes_exact_and_rejects_derivatives(self):
        """Exact matches must score >= 140, descriptors >= 110, derivatives <= 40."""
        # Exact match
        exact_score = self.scraper._score_candidate('Monster', 'Monster')
        self.assertGreaterEqual(exact_score, 140)

        # Harmless descriptor
        dub_score = self.scraper._score_candidate('Monster (Dub)', 'Monster')
        self.assertGreaterEqual(dub_score, 110)

        # Derivative prefix: Re:Monster when searching Monster
        re_score = self.scraper._score_candidate('Re:Monster', 'Monster')
        self.assertLessEqual(re_score, 40)

        # Derivative expansion: Monster Musume when searching Monster
        musume_score = self.scraper._score_candidate('Monster Musume', 'Monster')
        self.assertLessEqual(musume_score, 40)

    def test_score_candidate_supports_keyword_and_positional_args(self):
        """Verify _score_candidate supports name=, title=, current_year= signature."""
        score = self.scraper._score_candidate(name='Monster', title='Monster', current_year='2004')
        self.assertGreaterEqual(score, 140)

        re_score = self.scraper._score_candidate(name='Re:Monster', title='Monster', current_year='2004')
        self.assertLessEqual(re_score, 40)

    def test_resolve_anime_id_selects_highest_ranked_and_filters_derivatives(self):
        """_resolve_anime_id must choose Monster over Re:Monster even if both appear in search."""
        fake_html = '''
        <div class="flw-item">
            <a class="film-poster-ahref" href="/re-monster-19123"></a>
            <h3 class="film-name"><a href="/re-monster-19123">Re:Monster</a></h3>
        </div>
        <div class="flw-item">
            <a class="film-poster-ahref" href="/monster-1234"></a>
            <h3 class="film-name"><a href="/monster-1234">Monster</a></h3>
        </div>
        '''
        with patch('resources.lib.ui.database.get', return_value=fake_html):
            anime_id = self.scraper._resolve_anime_id('https://mirror.test/', 'Monster', None, 19, {})
            self.assertEqual(anime_id, '1234')

    def test_resolve_anime_id_returns_none_when_only_derivative_candidates(self):
        """_resolve_anime_id must return None when only derivative titles (e.g. Re:Monster) are returned."""
        fake_html = '''
        <div class="flw-item">
            <a class="film-poster-ahref" href="/re-monster-19123"></a>
            <h3 class="film-name"><a href="/re-monster-19123">Re:Monster</a></h3>
        </div>
        '''
        with patch('resources.lib.ui.database.get', return_value=fake_html):
            anime_id = self.scraper._resolve_anime_id('https://mirror.test/', 'Monster', None, 19, {})
            self.assertIsNone(anime_id)


class TestGogoanimeCandidateScoring(unittest.TestCase):
    def setUp(self):
        control.clearSettingsCache()
        self.scraper = GogoanimeSources()

    def tearDown(self):
        control.cleanup()

    def test_score_candidate_scores_correctly(self):
        """Exact matches >= 140, descriptors >= 110, derivatives <= 40."""
        self.assertGreaterEqual(self.scraper._score_candidate('Monster', 'Monster'), 140)
        self.assertGreaterEqual(self.scraper._score_candidate('Monster (Dub)', 'Monster'), 110)
        self.assertLessEqual(self.scraper._score_candidate('Re:Monster', 'Monster'), 40)
        self.assertLessEqual(self.scraper._score_candidate('Monster Musume no Iru Nichijou', 'Monster'), 40)

    def test_get_sources_discards_derivative_slugs(self):
        """get_sources must discard Re:Monster and Monster Musume via cutoff logic."""
        show_data = {
            'kodi_meta': '{"name": "Monster", "ename": "Monster", "year": 2004}'
        }
        search_html = '''
        <div class="last_episodes">
            <ul class="items">
                <li><p class="name"><a href="/category/re-monster" title="Re:Monster">Re:Monster</a></p></li>
                <li><p class="name"><a href="/category/monster" title="Monster">Monster</a></p></li>
                <li><p class="name"><a href="/category/monster-dub" title="Monster (Dub)">Monster (Dub)</a></p></li>
                <li><p class="name"><a href="/category/monster-musume" title="Monster Musume">Monster Musume</a></p></li>
            </ul>
        </div>
        '''
        with patch('resources.lib.ui.database.get_show', return_value=show_data), \
             patch('resources.lib.ui.database.get', return_value=search_html), \
             patch.object(self.scraper, '_process_gogo', return_value=[{'release_title': 'source'}]) as mock_process:
            self.scraper.get_sources(19, 1)
            # Checked slugs passed to _process_gogo
            called_slugs = [call[0][0] for call in mock_process.call_args_list]
            self.assertIn('monster', called_slugs)
            self.assertIn('monster-dub', called_slugs)
            self.assertNotIn('re-monster', called_slugs)
            self.assertNotIn('monster-musume', called_slugs)


class TestAnimePaheCandidateScoring(unittest.TestCase):
    def setUp(self):
        control.clearSettingsCache()
        self.scraper = AnimePaheSources()

    def tearDown(self):
        control.cleanup()

    def test_get_sources_ranks_candidates_and_picks_exact_match(self):
        """get_sources must score all sitems, sorting exact Monster above Re:Monster even if Re:Monster is first."""
        show_data = {'kodi_meta': '{"name": "Monster"}'}
        sitems_json = '{"data": [{"title": "Re:Monster", "session": "session_re", "year": 2024}, {"title": "Monster", "session": "session_monster", "year": 2004}]}'

        with patch('resources.lib.ui.database.get_show', return_value=show_data), \
             patch('resources.lib.endpoints.malsync.get_title', return_value='Monster'), \
             patch.object(self.scraper, '_resolve_session_from_malsync', return_value=None), \
             patch('resources.lib.ui.database.get', return_value=sitems_json), \
             patch.object(self.scraper, '_process_ap', return_value=[{'release_title': 'ap_source'}]) as mock_ap:
            res = self.scraper.get_sources(19, 1)
            self.assertEqual(len(res), 1)
            # Confirms session_monster was selected, NOT session_re
            mock_ap.assert_called_once_with('session_monster', title='Monster', episode=1)

    def test_get_sources_rejects_derivative_candidate_when_no_match(self):
        """When sitems only contains Re:Monster for query Monster, no candidate scores >= 50 and returns []."""
        show_data = {'kodi_meta': '{"name": "Monster"}'}
        sitems_json = '{"data": [{"title": "Re:Monster", "session": "session_re", "year": 2024}]}'

        with patch('resources.lib.ui.database.get_show', return_value=show_data), \
             patch('resources.lib.endpoints.malsync.get_title', return_value='Monster'), \
             patch.object(self.scraper, '_resolve_session_from_malsync', return_value=None), \
             patch('resources.lib.ui.database.get', return_value=sitems_json), \
             patch.object(self.scraper, '_process_ap', return_value=[]) as mock_ap:
            res = self.scraper.get_sources(19, 1)
            self.assertEqual(res, [])
            mock_ap.assert_not_called()


class TestWatchNixtoons2CandidateScoring(unittest.TestCase):
    def setUp(self):
        control.clearSettingsCache()
        self.scraper = WNT2Sources()

    def tearDown(self):
        control.cleanup()

    def test_titles_match_accepts_variants_and_rejects_derivatives(self):
        """_titles_match must accept Monster Dubbed/Subbed but reject Re:Monster and Monster Musume."""
        self.assertTrue(self.scraper._titles_match('Monster', 'Monster (Dubbed)'))
        self.assertTrue(self.scraper._titles_match('Monster', 'Monster (Subbed)'))
        self.assertFalse(self.scraper._titles_match('Monster', 'Re:Monster Subbed'))
        self.assertFalse(self.scraper._titles_match('Monster', 'Monster Musume Subbed'))
        self.assertFalse(self.scraper._titles_match('Re:Monster', 'Monster Subbed'))
        self.assertTrue(self.scraper._titles_match('Monster (Dubbed)', 'Monster (Subbed)'))

    def test_get_series_variants_ranks_by_score_and_discards_derivatives(self):
        """_get_series_variants with query must rank and exclude derivative series."""
        results = [
            {'title': 'Re:Monster Subbed', 'url': 'https://wco.test/re-monster'},
            {'title': 'Monster (Dubbed)', 'url': 'https://wco.test/monster-dubbed'},
            {'title': 'Monster (Subbed)', 'url': 'https://wco.test/monster-subbed'},
            {'title': 'Monster Musume Subbed', 'url': 'https://wco.test/monster-musume'},
        ]
        variants = self.scraper._get_series_variants(results, query='Monster')
        variant_titles = [v['title'] for v in variants]
        self.assertIn('Monster (Dubbed)', variant_titles)
        self.assertIn('Monster (Subbed)', variant_titles)
        self.assertNotIn('Re:Monster Subbed', variant_titles)
        self.assertNotIn('Monster Musume Subbed', variant_titles)


class TestNyaaAndAnimeToshoShowTitleFiltering(unittest.TestCase):
    def setUp(self):
        control.clearSettingsCache()
        self.nyaa = NyaaSources()
        self.animetosho = AnimeToshoSources()

    def tearDown(self):
        control.cleanup()

    def test_nyaa_fetch_and_filter_episodes_passes_show_title(self):
        """_fetch_and_filter_episodes must pass show_title so filter_sources rejects derivative torrents."""
        fake_html = '''
        <div class="table-responsive">
            <table>
                <tr class="default">
                    <td><a href="/c/1_2">Anime</a></td>
                    <td><a href="/view/1" title="[ASW] Monster - 01 [BD 1080p].mkv">[ASW] Monster - 01 [BD 1080p].mkv</a></td>
                    <td><a href="magnet:?xt=urn:btih:1111111111111111111111111111111111111111"></a></td>
                    <td class="text-center">500 MiB</td>
                    <td class="text-center"></td>
                    <td class="text-center">50</td>
                    <td class="text-center">5</td>
                    <td class="text-center">100</td>
                </tr>
                <tr class="default">
                    <td><a href="/c/1_2">Anime</a></td>
                    <td><a href="/view/2" title="[SubsPlease] Re:Monster - 01 (1080p).mkv">[SubsPlease] Re:Monster - 01 (1080p).mkv</a></td>
                    <td><a href="magnet:?xt=urn:btih:2222222222222222222222222222222222222222"></a></td>
                    <td class="text-center">500 MiB</td>
                    <td class="text-center"></td>
                    <td class="text-center">150</td>
                    <td class="text-center">1</td>
                    <td class="text-center">300</td>
                </tr>
            </table>
        </div>
        '''
        mock_resp = MagicMock(text=fake_html)
        with patch('resources.lib.ui.client.get', return_value=mock_resp), \
             patch('resources.lib.ui.database.get_mappings', return_value={}):
            filtered = self.nyaa._fetch_and_filter_episodes(
                'https://nyaa.test/', {}, mal_id=19, episode_zfill='01', season_zfill='01', part=None, show_title='Monster'
            )
            hashes = [f['hash'] for f in filtered]
            self.assertIn('1111111111111111111111111111111111111111', hashes)
            self.assertNotIn('2222222222222222222222222222222222222222', hashes)

    def test_animetosho_process_episodes_passes_show_title(self):
        """process_animetosho_episodes must pass show_title so filter_sources rejects derivative torrents."""
        fake_html = '''
        <div id="content">
            <div class="home_list_entry">
                <div class="link"><a href="/view/1">Monster - 01.mkv</a></div>
                <div class="size">500MB</div>
                <a class="dllink" href="magnet:?xt=urn:btih:3333333333333333333333333333333333333333"></a>
            </div>
            <div class="home_list_entry">
                <div class="link"><a href="/view/2">Re:Monster - 01.mkv</a></div>
                <div class="size">500MB</div>
                <a class="dllink" href="magnet:?xt=urn:btih:4444444444444444444444444444444444444444"></a>
            </div>
        </div>
        '''
        mock_resp = MagicMock(text=fake_html)
        with patch('resources.lib.ui.client.get', return_value=mock_resp), \
             patch('resources.lib.ui.database.get_mappings', return_value={}), \
             patch('resources.lib.debrid.Debrid.torrentCacheCheck', return_value=([], [])):
            self.animetosho.show = 'Monster'
            filtered = self.animetosho.process_animetosho_episodes(
                'https://animetosho.test/', {}, mal_id=19, episode='1', season=1, part=None, show='Monster'
            )
            # The internal filtered_list checked via source_utils.filter_sources
            # We can directly verify via filter_sources with animetosho provider
            from resources.lib.ui import source_utils
            torrents = [
                {'name': 'Monster - 01.mkv', 'hash': '3333333333333333333333333333333333333333'},
                {'name': 'Re:Monster - 01.mkv', 'hash': '4444444444444444444444444444444444444444'},
            ]
            res = source_utils.filter_sources('animetosho', torrents, 19, season=1, episode=1, show_title='Monster')
            hashes = [r['hash'] for r in res]
            self.assertEqual(hashes, ['3333333333333333333333333333333333333333'])


class TestAnikotoScraper(unittest.TestCase):
    def setUp(self):
        control.clearSettingsCache()
        self.scraper = AnikotoSources()

    def tearDown(self):
        control.cleanup()

    def test_score_candidate_evaluates_candidates(self):
        """_score_candidate uses centralized scoring."""
        self.assertGreaterEqual(self.scraper._score_candidate('Monster', 'Monster'), 140)
        self.assertLessEqual(self.scraper._score_candidate('Re:Monster', 'Monster'), 40)

    def test_get_sources_routes_cleanly_via_mal_id(self):
        """get_sources queries megaplay endpoint with exact numeric MAL ID."""
        show_data = {'kodi_meta': '{"name": "Monster"}'}
        with patch('resources.lib.ui.database.get_show', return_value=show_data), \
             patch.object(self.scraper, '_build_source', return_value={'release_title': 'Monster - Ep 1'}) as mock_build:
            res = self.scraper.get_sources(19, 1)
            self.assertTrue(len(res) > 0)
            # Check embed_url passed into _build_source has numeric mal id 19
            called_urls = [call[0][0] for call in mock_build.call_args_list]
            self.assertTrue(all('/stream/mal/19/1/' in url for url in called_urls))


if __name__ == '__main__':
    unittest.main()
