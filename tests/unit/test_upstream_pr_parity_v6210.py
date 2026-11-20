import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'plugin.video.otaku.rpdev'))

from resources.lib.ui import control, domains, source_utils, utils, part_filter
from resources.lib.pages import nyaa, animetosho, easynews
from resources.lib.WatchlistFlavor import AniList


class TestUpstreamPrParityV6210(unittest.TestCase):
    """Regression suite for Goldenfreddy0703/Otaku PRs #497, #501, #502, #503, #505, #506, #507."""

    def test_pr502_nyaa_season_query_never_emits_literal_none(self):
        """PR #502 / Issue #496: Nyaa season search matches 'Season' case-insensitively across N titles."""
        scraper = nyaa.Sources()
        captured_tasks = []

        def _capture_parallel(tasks, fn):
            captured_tasks.extend(tasks)
            return [[] for _ in tasks]

        with patch('resources.lib.ui.utils.parallel_process', side_effect=_capture_parallel):
            scraper.get_episode_sources('(Clevatess Season 2)|(Clevatess 2nd Season)', 60001, 1, 2, None, 'RELEASING')

        additional = [t for t in captured_tasks if t['name'] == 'additional']
        self.assertEqual(len(additional), 1)
        q4 = additional[0]['query']
        self.assertNotIn('None', q4)
        self.assertEqual(q4, '(Clevatess)|(Clevatess 2nd)')

    def test_pr505_animetosho_handles_missing_anidb_in_simkl_mapping(self):
        """PR #505: AnimeTosho skips AniDB lookup when Simkl mapping has no 'anidb' key."""
        scraper = animetosho.Sources()
        fake_meta = {'meta_ids': '{}', 'art': '{}'}
        with patch('resources.lib.ui.database.get_show_meta', return_value=fake_meta), \
             patch('resources.lib.ui.database.loads', return_value={}), \
             patch('resources.lib.indexers.simkl.SIMKLAPI.get_mapping_ids_from_simkl', return_value={'mal': 64505, 'simkl': 999}), \
             patch('resources.lib.ui.utils.parallel_process', return_value=[]), \
             patch.object(scraper, 'process_animetosho_movie', return_value=[]):
            ep_res = scraper.get_episode_sources('New Show', 64505, 1, 1, None, 'RELEASING')
            mov_res = scraper.get_movie_sources('New Movie', 64505)
        self.assertEqual(ep_res, [])
        self.assertEqual(mov_res, {'cached': [], 'uncached': []})
        self.assertIsNone(scraper.anidb_id)

    def test_pr507_animetosho_net_domain_migration_and_iec_byte_sizes(self):
        """PR #507: animetosho uses animetosho.net, migrates cached .org, and convert_to_bytes parses KiB/MiB/GiB."""
        domains._DOMAINS_CACHE = None
        with patch.object(control, 'getBool', return_value=False):
            self.assertEqual(domains.get_domain('animetosho'), 'https://animetosho.net/')
        with patch.object(control, 'getBool', side_effect=lambda k: k == 'provider.animetoshoalt'):
            alt = domains.get_domain('animetosho')
            self.assertTrue(alt.startswith('https://animetosho-net.translate.goog/'))

        migrated = domains._normalize_legacy_domains({'animetosho': 'https://animetosho.org/'})
        self.assertEqual(migrated['animetosho'], 'https://animetosho.net/')

        self.assertEqual(source_utils.convert_to_bytes(1.0, 'GiB'), 2**30)
        self.assertEqual(source_utils.convert_to_bytes(512.0, 'MiB'), 512 * 2**20)
        self.assertEqual(source_utils.convert_to_bytes(256.0, 'KiB'), 256 * 2**10)

        view = animetosho.Sources.parse_animetosho_view(
            {'name': '[SubsPlease] Show - 01 (1080p).mkv', 'hash': 'a' * 40, 'size': '1.25 GiB', 'seeders': 10},
            episode='01',
            cached=True,
        )
        self.assertEqual(view['byte_size'], 1.25 * 2**30)

    def test_pr506_anilist_resolves_unknown_mal_id_directly_via_graphql(self):
        """PR #506: AniList queries Media(idMal:) directly when show has no cached anilist_id."""
        flavor = AniList.AniListWLF.__new__(AniList.AniListWLF)
        flavor._NAME = 'anilist'
        flavor._URL = 'https://graphql.anilist.co'
        flavor.token = 'fake-token'

        mock_lookup_resp = MagicMock()
        mock_lookup_resp.json.return_value = {'data': {'Media': {'id': 185402}}}
        mock_save_resp = MagicMock(ok=True)

        with patch('resources.lib.ui.database.get_show', return_value={'mal_id': 64505, 'anilist_id': None}), \
             patch('resources.lib.ui.database.add_mapping_id') as mock_add_map, \
             patch('resources.lib.ui.database.clear_watchlist_cache'), \
             patch('resources.lib.ui.client.post', side_effect=[mock_lookup_resp, mock_save_resp]):
            ok = flavor.update_num_episodes(64505, 3)

        self.assertTrue(ok)
        mock_add_map.assert_called_once_with(64505, 'anilist_id', 185402)
        self.assertEqual(flavor._clean_anilist_id('https://anilist.co/anime/185402/'), 185402)
        self.assertEqual(flavor._clean_anilist_id(185402), 185402)

    def test_pr497_easynews_strips_colons_and_filters_old_part_posts(self):
        """PR #497 & #501: Easynews strips ':' from queries and drops Usenet posts older than part start_date."""
        scraper = easynews.Sources()
        searched_queries = []

        def _fake_search(q):
            searched_queries.append(q)
            return [
                # Old 2022 Part 1 post (before 2026-10-05 start_date)
                {'url_dl': 'https://en.test/old', 'name': 'Bleach.Thousand-Year.Blood.War.S01E06.1080p.mkv', 'rawSize': 500000000, 'ts': 1668000000},
                # New 2026 Part 4 post
                {'url_dl': 'https://en.test/new', 'name': 'Bleach.Thousand-Year.Blood.War.S01E06.1080p.mkv', 'rawSize': 600000000, 'ts': 1791500000},
            ]

        fake_show = {'kodi_meta': '{"start_date": "2026-10-05"}'}
        with patch('resources.lib.ui.control.easynews_enabled', return_value=True), \
             patch('resources.lib.ui.database.get_show', return_value=fake_show), \
             patch('resources.lib.ui.database.loads', return_value={'start_date': '2026-10-05'}), \
             patch('resources.lib.ui.part_filter.part_info', return_value=(4, 'kashintan', ['ketsubetsutan'])), \
             patch('resources.lib.debrid.easynews.Easynews.search', side_effect=_fake_search):
            res = scraper.get_sources(
                '(BLEACH: Thousand-Year Blood War - The Calamity)|(BLEACH: Sennen Kessen-hen - Kashin-tan)',
                59000, 6, 'RELEASING', 'episode', season=1, part=4
            )

        self.assertTrue(len(searched_queries) > 0)
        for q in searched_queries:
            self.assertNotIn(':', q, f"Colon found in Easynews query: {q!r}")
        self.assertEqual(len(res['cached']), 1)
        self.assertEqual(res['cached'][0]['hash'], 'https://en.test/new')

    def test_pr503_resolve_season_and_default_season_filter_relaxation(self):
        """PR #503: Bare trailing numbers ('Kaiju No. 8') resolve as 'default' and default season=1 does not drop S02."""
        with patch('resources.lib.ui.database.get_mappings', return_value={}), \
             patch('resources.lib.ui.utils.get_anizip_summary', return_value={}):
            season, source = utils.resolve_season(['Kaiju No. 8'], 52588)
            self.assertEqual(source, 'default')

            s2, src2 = utils.resolve_season(['Ao Ashi Season 2'], 61000)
            self.assertEqual((s2, src2), (2, 'title'))

        torrents = [
            {'name': '[SubsPlease] Ao Ashi S02E01 (1080p).mkv', 'hash': '1' * 40},
        ]
        with patch('resources.lib.ui.database.get_mappings', return_value={}):
            # When season=1 came from 'default', S02E01 must NOT be rejected
            kept_default = source_utils.filter_sources(
                'nyaa', torrents, 61000, season=1, episode=1, season_source='default'
            )
            self.assertEqual(len(kept_default), 1)

            # Torrentio is ID-based and skips season rejection
            kept_torrentio = source_utils.filter_sources(
                'torrentio', torrents, 61000, season=1, episode=1, season_source='mapping'
            )
            self.assertEqual(len(kept_torrentio), 1)

    def test_pr501_part_filter_drops_sibling_part_names_and_wrong_episode_titles(self):
        """PR #501 / Issue #498: part_filter drops releases naming sibling parts or wrong S01E06.<Title>."""
        sources = [
            {'release_title': '[Erai-raws] Bleach - Sennen Kessen Hen - Ketsubetsu Tan - 06 [1080p].mkv'},
            {'release_title': 'Bleach.Thousand-Year.Blood.War.S01E06.The.Fire.1080p.WEB-DL.mkv'},
            {'release_title': '[SubsPlease] Bleach - Sennen Kessen-hen - Kashin-tan - 06 (1080p).mkv'},
            {'release_title': 'Bleach.Thousand-Year.Blood.War.S01E06.The.End.1080p.WEB-DL.mkv'},
        ]
        with patch.object(part_filter, '_user_wants_chinese', return_value=True), \
             patch.object(part_filter, '_get_mappings_info', return_value=None), \
             patch.object(part_filter, 'part_info', return_value=(4, 'kashintan', ['ketsubetsutan', 'soukokutan'])), \
             patch.object(part_filter, 'episode_title_words', return_value={'end'}):
            kept = part_filter.filter_sources(sources, mal_id=59000, episode=6)

        kept_titles = [s['release_title'] for s in kept]
        self.assertEqual(len(kept_titles), 2)
        self.assertIn('[SubsPlease] Bleach - Sennen Kessen-hen - Kashin-tan - 06 (1080p).mkv', kept_titles)
        self.assertIn('Bleach.Thousand-Year.Blood.War.S01E06.The.End.1080p.WEB-DL.mkv', kept_titles)

    def test_live_kodi22_versioned_episode_rejection_and_arc_subtitle_s3_scoring(self):
        """Live Kodi 22 fixes: filter_sources drops '- 02v2'/'- 07v2' for ep 8, and score_title_candidate accepts exact arc-subtitle releases carrying '| S3'."""
        torrents = [
            {'name': '[Erai-raws] Bleach: Sennen Kessen Hen - Soukoku Tan - 02v2 [1080p]', 'hash': '2' * 40},
            {'name': '[Erai-raws] Bleach: Sennen Kessen Hen - Soukoku Tan - 07v2 [1080p]', 'hash': '7' * 40},
            {'name': '[Erai-raws] Bleach: Sennen Kessen Hen - Soukoku Tan - 08 [1080p]', 'hash': '8' * 40},
        ]
        with patch('resources.lib.ui.database.get_mappings', return_value={}):
            kept = source_utils.filter_sources('nyaa', torrents, 56784, season=3, episode=8)
        self.assertEqual([t['hash'] for t in kept], ['8' * 40])

        rel = 'Bleach: Sennen Kessen-hen - Soukoku-tan - 08 | Bleach: Thousand-Year Blood War - The Conflict | S3 [English Dub][1080p]'
        score = source_utils.score_title_candidate(
            'Bleach: Sennen Kessen-hen - Soukoku-tan',
            rel,
            aliases=['Bleach: Thousand-Year Blood War - The Conflict'],
        )
        self.assertGreaterEqual(score, 125)
        # Base titles without arc subtitles still reject mismatched sequel seasons
        self.assertEqual(source_utils.score_title_candidate('Monster', 'Monster S2 - 01 [1080p]'), 0)


if __name__ == '__main__':
    unittest.main()
