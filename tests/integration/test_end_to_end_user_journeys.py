# -*- coding: utf-8 -*-
"""
test_end_to_end_user_journeys.py - Offline End-to-End Integration Journeys
==========================================================================
Exercises complete cross-subsystem user journeys end-to-end without network egress:
1. Browse directory generation -> sort methods -> pinned Next Page & Filter rows -> setDateTime
2. Arc-subtitled sequel scrape (AnimeTosho alt failover + Nyaa) -> pre-Debrid sequel alias filter
   -> single-batch Debrid check -> part_filter -> sortSources 4-tier relevance gating
3. Resolver -> Kodi 22 external VTT validation & origin fallback + unique sub_tag -> WatchlistPlayer
4. Season-pack reuse cache hit & invalidation on playback startup failure
5. Context menu command dispatch -> plugin router execution
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_TEST_DIR, '..' if os.path.basename(_TEST_DIR) in ('unit', 'integration', 'lint') else '.'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
_TESTS_DIR = os.path.join(_REPO_ROOT, 'tests')
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import conftest  # noqa: F401
import xbmcplugin
from kodi_profile import KodiProfile
from resources.lib import pages
from resources.lib.pages import animetosho
from resources.lib.ui import control, database, embed_extractor, part_filter, player, source_utils


class TestEndToEndUserJourneys(unittest.TestCase):
    """Cross-subsystem offline integration journeys verifying real end-user workflows."""

    def setUp(self):
        self._saved = dict(conftest._settings_store)
        xbmcplugin.reset()

    def tearDown(self):
        conftest._settings_store.clear()
        conftest._settings_store.update(self._saved)
        database.close_thread_connections()

    def test_journey_1_directory_listing_sort_methods_and_pinning(self):
        """End-to-end directory drawing sets UNSORTED default, labelMask='%L', setDateTime, and SpecialSort pinning."""
        with KodiProfile('22'):
            items = [
                {'name': '[Filter...]', 'url': 'multipage_filter/popular', 'isfolder': False, 'isplayable': False, 'image': {'icon': 'filter.png'}, 'info': {'title': '[Filter...]'}, 'cm': None},
                {
                    'name': "Frieren: Beyond Journey's End",
                    'url': 'animes/52991/',
                    'isfolder': True,
                    'isplayable': False,
                    'image': {'poster': 'https://img.test/frieren.jpg', 'fanart': 'https://img.test/fan.jpg'},
                    'info': {'title': "Frieren: Beyond Journey's End", 'mediatype': 'tvshow', 'premiered': '2023-09-29', 'episodes': 28, 'year': 2023},
                    'cm': None,
                },
                {'name': 'Next Page >>>', 'url': 'popular?page=2', 'isfolder': True, 'isplayable': False, 'image': {'icon': 'next.png'}, 'info': {'title': 'Next Page >>>'}, 'cm': None},
            ]
            control.draw_items(items, 'tvshows')
            self.assertEqual(len(xbmcplugin.directory_items), 3)
            self.assertIsNotNone(xbmcplugin.end_of_directory_args)
            # xbmcplugin.directory_items stores (handle, url, listitem, isFolder) tuples
            lis = [entry[2] for entry in xbmcplugin.directory_items]
            by_label = {li.getLabel(): li for li in lis}
            self.assertEqual(by_label['[Filter...]'].getProperty('SpecialSort'), 'top')
            self.assertEqual(by_label['Next Page >>>'].getProperty('SpecialSort'), 'bottom')
            frieren_li = by_label["Frieren: Beyond Journey's End"]
            self.assertEqual(frieren_li.getDateTime(), '2023-09-29T00:00:00')
            self.assertEqual(frieren_li.getVideoInfoTag().getEpisode(), 28)

    def test_journey_2_sequel_scrape_failover_filter_debrid_and_sort(self):
        """Full torrent funnel: AnimeTosho alt-proxy 403 -> direct failover -> sequel alias filter -> single Debrid check -> part_filter -> sortSources."""
        tosho_html = (
            '<div id="content">'
            '<div class="home_list_entry">'
            '<div class="link"><a href="/view/1">[Yameii] Blue Exorcist - S04E01 [English Dub] [1080p]</a></div>'
            '<a href="magnet:?xt=urn:btih:' + ('a' * 40) + '">Magnet</a>'
            '<div class="size">820 MiB</div><span title="Seeders: 35">35</span>'
            '</div>'
            '<div class="home_list_entry">'
            '<div class="link"><a href="/view/2">[Bad] Blue Exorcist - S01E01 [English Dub] [1080p]</a></div>'
            '<a href="magnet:?xt=urn:btih:' + ('b' * 40) + '">Magnet</a>'
            '<div class="size">800 MiB</div><span title="Seeders: 90">90</span>'
            '</div>'
            '</div>'
        )
        control.setBool('provider.animetoshoalt', True)
        control.setBool('show.uncached', False)
        control.setInt('general.source', 2)  # Dub / Dual-Audio
        control.setInt('general.minResolution', 0)
        control.setInt('general.maxResolution', 4)
        control.setInt('general.fileFilter', 0)

        def _fake_get(url, params=None, **kw):
            if 'translate.goog' in url:
                return MagicMock(status_code=403, text='<html>Blocked</html>')
            return MagicMock(status_code=200, text=tosho_html)

        scraper = animetosho.Sources()
        with patch('resources.lib.ui.client.get', side_effect=_fake_get), \
             patch('resources.lib.ui.database.get_show_meta', return_value=None), \
             patch('resources.lib.ui.database.get_mappings', return_value={'anidb_id': 18561}), \
             patch('resources.lib.pages.animetosho.Debrid') as mock_debrid:
            mock_debrid.return_value.torrentCacheCheck.side_effect = lambda fl, **kw: (fl, [])
            scraped = scraper.get_sources(
                '(Ao no Exorcist: Yuki no Hate-hen)|(Blue Exorcist: Beyond the Snow Saga)',
                58516, 1, 'FINISHED', 'tv', season=4,
            )

        # Failover occurred to direct animetosho.net and single batched Debrid check retained only S04E01
        self.assertEqual(scraper._active_base_url, 'https://animetosho.net/')
        mock_debrid.return_value.torrentCacheCheck.assert_called_once()
        self.assertEqual(len(scraped['cached']), 1)
        self.assertIn('S04E01', scraped['cached'][0]['release_title'])

        # Run part_filter + sortSources end-to-end
        post_part = part_filter.filter_sources(scraped['cached'], mal_id=58516, episode=1, season=4)
        with patch('resources.lib.ui.database.get_show', return_value=None), \
             patch('resources.lib.ui.database.get_show_meta', return_value=None), \
             patch('resources.lib.ui.database.get_anilist_enrichment_batch', return_value={}):
            final = pages.Sources.sortSources(
                post_part, [], [], [], [], 'episode', 24,
                mal_id=58516,
                show_title='(Ao no Exorcist: Yuki no Hate-hen)|(Blue Exorcist: Beyond the Snow Saga)',
                season=4,
            )
        self.assertEqual(len(final), 1)
        self.assertIn('S04E01', final[0]['release_title'])

    def test_journey_3_external_vtt_proxy_fallback_and_kodi22_player_sub_matching(self):
        """End-to-end subtitle pipeline: expired proxy JSON -> origin VTT fallback -> Kodi 22 BCP 47 selection."""
        written = {}

        def _fake_write(path, content):
            written['path'] = path
            written['content'] = content
            return True

        def _fake_get(url, headers=None, **kw):
            if 'proxy.test' in url:
                return MagicMock(text='{"error": "expired"}')
            return MagicMock(text='  \ufeffWEBVTT\n\n00:01.020 --> 00:05.000\nLine 1\n')

        with KodiProfile('22'), \
             patch('resources.lib.ui.client.get', side_effect=_fake_get), \
             patch('resources.lib.ui.control.atomic_write_text', side_effect=_fake_write):
            entry = embed_extractor.get_sub(
                'https://proxy.test/fetch?url=https%3A%2F%2Forigin.test%2Feng.vtt',
                'eng',
                source_url='https://origin.test/eng.vtt',
                sub_index=0,
                sub_tag='58516_1_12345',
            )
            self.assertIsNotNone(entry)
            self.assertEqual(entry['path'], 'special://temp/TemporarySubs.58516_1_12345.0.eng.vtt')
            self.assertTrue(written['content'].startswith('WEBVTT'))

            # Verify Kodi 22 2-letter BCP 47 stream matches preferred 'eng'
            picked = player.select_subtitle_stream(
                [{'index': 0, 'language': 'ja', 'name': 'Japanese'}, {'index': 1, 'language': 'en', 'name': 'English'}],
                target_mode='dialog',
                preferred_lang='eng',
            )
            self.assertEqual(picked, 1)

    def test_journey_4_season_pack_cache_roundtrip_and_invalidation(self):
        """End-to-end season pack cache store, retrieval for subsequent episodes, and clear_season_pack invalidation."""
        pack_source = {
            'release_title': '[Judas] Wistoria (Season 02) [1080p][Dual-Audio] (Batch)',
            'hash': 'c' * 40,
            'type': 'torrent',
            'debrid_provider': 'premiumize',
            'provider': 'nyaa',
            'cached': True,
            'is_pack': True,
        }
        database.set_season_pack(59983, 2, pack_source)
        reused = database.get_season_pack(59983, 2)
        self.assertIsNotNone(reused)
        self.assertEqual(reused.get('hash'), 'c' * 40)

        database.clear_season_pack(59983, 2)
        self.assertIsNone(database.get_season_pack(59983, 2))


if __name__ == '__main__':
    unittest.main()
