import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'plugin.video.otaku.rpdev'))

from resources.lib import pages
from resources.lib.pages import animepahe
from resources.lib.ui import control, domains, embed_extractor, player, source_utils


class TestReview10FixesV6211(unittest.TestCase):
    """Regression tests for ONN Review #10 findings (C-11, C-20, C-01)."""

    def test_c11_onplaybackended_preserves_temp_subs_during_playlist_transition(self):
        """C-11: onPlayBackEnded skips del_subs() when a next playlist item is queued."""
        wp = player.WatchlistPlayer.__new__(player.WatchlistPlayer)
        wp.total_time = 0
        wp._playback_stopped = False
        wp._playback_ended = False
        wp.path = ''

        with patch.object(player.playList, 'size', return_value=2), \
             patch.object(player.playList, 'getposition', return_value=0), \
             patch.object(embed_extractor, 'del_subs') as mock_del, \
             patch.object(control, 'closeAllDialogs'), \
             patch.object(control, 'clean_memory'):
            wp.onPlayBackEnded()
        mock_del.assert_not_called()

        with patch.object(player.playList, 'size', return_value=1), \
             patch.object(player.playList, 'getposition', return_value=0), \
             patch.object(embed_extractor, 'del_subs') as mock_del, \
             patch.object(control, 'closeAllDialogs'), \
             patch.object(control, 'clean_memory'):
            wp.onPlayBackEnded()
        mock_del.assert_called_once()

    def test_c11_get_sub_tags_filename_rejects_html_and_normalizes_vtt(self):
        """C-11: get_sub uses episode sub_tag, drops HTML error pages, and strips BOM / adds WEBVTT header."""
        written = {}

        def _capture_write(path, content):
            written['path'] = path
            written['content'] = content

        html_resp = MagicMock(text='<!DOCTYPE html><html><body>502 Bad Gateway</body></html>')
        with patch('resources.lib.ui.client.get', return_value=html_resp):
            self.assertIsNone(embed_extractor.get_sub('https://cdn.test/eng.vtt', 'eng', sub_tag='53889_2'))

        bom_vtt = MagicMock(text='\ufeff00:00:01.000 --> 00:00:03.000\nHello world\n')
        with patch('resources.lib.ui.client.get', return_value=bom_vtt), \
             patch('resources.lib.ui.control.atomic_write_text', side_effect=_capture_write):
            entry = embed_extractor.get_sub('https://cdn.test/eng.vtt', 'eng', sub_index=0, sub_tag='53889_2')

        self.assertIsNotNone(entry)
        self.assertEqual(entry['path'], 'special://temp/TemporarySubs.53889_2.0.eng.vtt')
        self.assertTrue(written['content'].startswith('WEBVTT\n\n'))
        self.assertIn('Hello world', written['content'])

    def test_c20_arc_subtitled_sequel_torrents_pass_relevance_gate(self):
        """C-20: Blue Exorcist S03 / Season 3 Dual-Audio torrents pass relevance_gate for MAL 53889 (season=3)."""
        torrents = [
            {'release_title': '[TMB] Blue Exorcist S03 [BD 1080p AV1][Dual Audio]', 'type': 'torrent', 'quality': 3, 'lang': 1, 'info': ['DUAL-AUDIO'], 'size': '4 GB', 'byte_size': 4 * 2**30, 'cached': True, 'seeders': 20},
            {'release_title': 'Blue Exorcist: Shimane Illuminati Saga (Season 3) [Web][1080p][Dual Audio]', 'type': 'torrent', 'quality': 3, 'lang': 1, 'info': ['DUAL-AUDIO'], 'size': '4 GB', 'byte_size': 4 * 2**30, 'cached': True, 'seeders': 15},
            {'release_title': 'Blue Exorcist S01E01 [Dual Audio] [1080p]', 'type': 'torrent', 'quality': 3, 'lang': 1, 'info': ['DUAL-AUDIO'], 'size': '1 GB', 'byte_size': 1 * 2**30, 'cached': True, 'seeders': 50},
        ]
        embeds = [
            {'release_title': 'Blue Exorcist: Shimane Illuminati Saga', 'type': 'embed', 'quality': 3, 'lang': 3, 'info': [], 'provider': 'hianime', 'relevance': 170},
        ]
        with patch.object(control, 'getInt', side_effect=lambda k, *a, **kw: {'general.minResolution': 0, 'general.maxResolution': 4, 'general.fileFilter': 0, 'general.source': 2}.get(k, 0)), \
             patch.object(control, 'getBool', return_value=False), \
             patch('resources.lib.ui.database.get_show', return_value=None), \
             patch('resources.lib.ui.database.get_show_meta', return_value=None), \
             patch('resources.lib.ui.database.get_anilist_enrichment_batch', return_value={}):
            res = pages.Sources.sortSources(
                torrents, [], embeds, [], [], 'episode', 24,
                mal_id=53889,
                show_title='(Ao no Exorcist: Shimane Illuminati-hen)|(Blue Exorcist: Shimane Illuminati Saga)',
                season=3,
            )
        titles = [s['release_title'] for s in res]
        self.assertIn('[TMB] Blue Exorcist S03 [BD 1080p AV1][Dual Audio]', titles)
        self.assertIn('Blue Exorcist: Shimane Illuminati Saga (Season 3) [Web][1080p][Dual Audio]', titles)
        self.assertNotIn('Blue Exorcist S01E01 [Dual Audio] [1080p]', titles)

    def test_c01_animepahe_marks_one_hour_cooldown_on_empty_search(self):
        """C-01: AnimePahe marks failing mirror with 3600s cooldown on empty search API response."""
        scraper = animepahe.Sources()
        with patch('resources.lib.ui.domains.is_mirror_healthy', return_value=True), \
             patch('resources.lib.ui.domains.mark_mirror_failure') as mock_mark, \
             patch.object(scraper, '_get_request', return_value=''):
            res = scraper._process_ap('Blue Exorcist: Shimane Illuminati Saga', '1', 53889)
        self.assertEqual(res, [])
        mock_mark.assert_called_once()
        self.assertEqual(mock_mark.call_args.kwargs.get('cooldown'), 3600)


if __name__ == '__main__':
    unittest.main()
