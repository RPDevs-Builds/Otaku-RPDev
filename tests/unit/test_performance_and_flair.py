import unittest
import time
from unittest.mock import patch, MagicMock

from resources.lib.ui import source_utils, part_filter, colors, domains
from resources.lib.debrid import debrid_cache


class TestPerformanceAndRegex(unittest.TestCase):
    def test_clean_title_unicode_and_symbols(self):
        self.assertEqual(source_utils.cleanTitle("Pokémon: Advanced"), "pokemon advanced")
        self.assertEqual(source_utils.cleanTitle("Yu Yu Hakusho & Movie"), "yu yu hakusho and movie")
        self.assertEqual(source_utils.cleanTitle("Attack on Titan: Season 4"), "attack on titan season 4")
        self.assertEqual(source_utils.cleanTitle("KonoSuba: God's Blessing - 01"), "konosuba gods blessing 01")

    def test_remove_patterns_and_cleanup_text(self):
        raw = "[SubsPlease] Frieren - Beyond Journey's End - 01 (1080p) [HEVC 10bit AAC] [7.1].mkv"
        cleaned = source_utils.clean_text(raw)
        self.assertNotIn("1080p", cleaned.lower())
        self.assertNotIn("hevc", cleaned.lower())
        self.assertNotIn("aac", cleaned.lower())

    def test_get_embedhost(self):
        self.assertEqual(source_utils.get_embedhost("https://megacloud.tv/embed-2/e-1?k=1"), "megacloud")
        self.assertEqual(source_utils.get_embedhost("https://rapid-cloud.co/embed-6/v-2"), "rapid-cloud")

    def test_is_season_pack(self):
        self.assertTrue(source_utils.is_season_pack({'release_title': '[Erai-raws] Bleach - S01 [Batch]'}))
        self.assertTrue(source_utils.is_season_pack({'release_title': '[Judas] One Piece (Episodes 01-130)'}))
        self.assertFalse(source_utils.is_season_pack({'release_title': '[SubsPlease] One Piece - 1080 (1080p).mkv'}))

    def test_filter_sources_hash_deduplication(self):
        torrents = [
            {'name': 'Show - 01 (1080p)', 'hash': 'abc1234567890abcdef1234567890abcdef1234', 'magnet': ''},
            {'name': 'Show - 01 [720p]', 'hash': 'abc1234567890abcdef1234567890abcdef1234', 'magnet': ''},
            {'name': 'Show - 01 [v2]', 'hash': 'def1234567890abcdef1234567890abcdef1234', 'magnet': ''},
        ]
        filtered = source_utils.filter_sources('animetosho', torrents, mal_id=1, season=1, episode=1)
        hashes = [t['hash'] for t in filtered]
        self.assertEqual(len(hashes), 2)
        self.assertEqual(hashes[0], 'abc1234567890abcdef1234567890abcdef1234')
        self.assertEqual(hashes[1], 'def1234567890abcdef1234567890abcdef1234')


class TestPartFilterOptimization(unittest.TestCase):
    @patch('resources.lib.ui.database.get_mappings')
    def test_get_mappings_info_uses_database_mappings(self, mock_get_mappings):
        mock_get_mappings.return_value = {
            'thetvdb_season': 2,
            'thetvdb_part': 1,
            'anime_media_episodes': '1-12',
            'global_media_episodes': '25-36',
            'mal_title': 'Jujutsu Kaisen Season 2'
        }
        res = part_filter._get_mappings_info(51009)
        self.assertIsNotNone(res)
        self.assertEqual(res['thetvdb_season'], 2)
        self.assertEqual(res['thetvdb_part'], 1)
        mock_get_mappings.assert_called_once_with(51009, 'mal_id')

    @patch('resources.lib.subtitles.languages.get_preferred_subtitle_language')
    def test_user_wants_chinese_detection(self, mock_lang):
        mock_lang.return_value = 'zh'
        self.assertTrue(part_filter._user_wants_chinese())

        mock_lang.return_value = 'en'
        with patch('resources.lib.ui.control.kodi_get_setting', return_value=''):
            self.assertFalse(part_filter._user_wants_chinese())


class TestColorsAndFlair(unittest.TestCase):
    def test_seeder_color_tiers(self):
        self.assertEqual(colors.get_seeder_color(100), 'FF00E676')  # Green (>=50)
        self.assertEqual(colors.get_seeder_color(50), 'FF00E676')   # Green (>=50)
        self.assertEqual(colors.get_seeder_color(25), 'FFFFD600')   # Yellow (10-49)
        self.assertEqual(colors.get_seeder_color(10), 'FFFFD600')   # Yellow (10-49)
        self.assertEqual(colors.get_seeder_color(5), 'FFFF5252')    # Red (<10)
        self.assertEqual(colors.get_seeder_color('na'), 'FFB0BEC5') # Fallback

    def test_badge_colors(self):
        self.assertEqual(colors.get_badge_color('hevc'), 'FF00E5FF')
        self.assertEqual(colors.get_badge_color('hdr'), 'FFFFD700')
        self.assertEqual(colors.get_badge_color('7.1'), 'FF76FF03')
        self.assertEqual(colors.colorize_badge('HEVC'), '[COLOR FF00E5FF]HEVC[/COLOR]')


class TestDebridInFlightDeduplication(unittest.TestCase):
    def test_acquire_and_release_in_flight(self):
        h1 = 'hash_alpha_1'
        h2 = 'hash_beta_2'

        # Thread 1 acquires h1 and h2
        ready1, events1 = debrid_cache.acquire_in_flight([h1, h2], 'rd')
        self.assertEqual(len(ready1), 2)
        self.assertEqual(len(events1), 0)

        # Thread 2 attempts to acquire same hashes concurrently
        ready2, events2 = debrid_cache.acquire_in_flight([h1, 'hash_gamma_3'], 'rd')
        self.assertEqual(ready2, ['hash_gamma_3'])
        self.assertEqual(len(events2), 1)

        # Thread 1 releases h1 and h2
        debrid_cache.release_in_flight([h1, h2], 'rd')
        # Waiting event should now be set
        self.assertTrue(events2[0].is_set())

        # Clean up Thread 2
        debrid_cache.release_in_flight(ready2, 'rd')


class TestDynamicMirrorHealth(unittest.TestCase):
    def test_mirror_failure_and_cooldown(self):
        mirror = "https://hianime.lu/"
        self.assertTrue(domains.is_mirror_healthy(mirror))

        domains.mark_mirror_failure(mirror)
        self.assertFalse(domains.is_mirror_healthy(mirror))

        # Check get_healthy_mirrors places failing mirror at end
        mirrors = domains.get_healthy_mirrors('hianime')
        self.assertNotIn(mirror, mirrors[:2])

        # Test cooldown expiration cleanup
        domains._FAILED_MIRRORS[mirror] = time.time() - 700
        self.assertTrue(domains.is_mirror_healthy(mirror))


if __name__ == '__main__':
    unittest.main()
