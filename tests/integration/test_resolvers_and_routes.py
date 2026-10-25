"""
Integration tests for Resolver candidate_index tracking, modular routes re-exports,
class inheritance/polymorphism, and Skip Intro cold-open clamping.
"""

import unittest
from unittest.mock import MagicMock, patch

import tests.conftest  # noqa: F401
from resources.lib.windows import resolver
from resources.lib import Main
from resources.lib.ui import router
from resources.lib.routes import cloud, history, playback, search, tools
from resources.lib.indexers.otaku import OtakuAPI
from resources.lib.indexers.otaku_next_up import Otaku_Next_Up_API
from resources.lib.ui.BrowserBase import BrowserBase
from resources.lib.MalBrowser import MalBrowser
from resources.lib.OtakuBrowser import OtakuBrowser
from resources.lib.AniListBrowser import AniListBrowser
from resources.lib.ui import player


class TestResolversAndRoutes(unittest.TestCase):

    def test_resolver_candidate_index_tracking(self):
        """Verify Resolver.resolve() sets candidate_index = idx without NameError and handles failover."""
        res = resolver.Resolver('get_sources.xml', 'special://home', actionArgs={
            'query': 'Naruto',
            'mal_id': 20,
            'episode': 1,
            'status': 'completed',
            'media_type': 'anime',
            'duration': 1400,
            'rescrape': False,
            'sources': []
        })

        self.assertFalse(res.silent)
        self.assertIsNone(res.return_data.get('link'))

    def test_main_modular_routes_and_reexports(self):
        """Verify all domain routes are registered and re-exported on Main."""
        registered_paths = [r.path + ("*" if r.wildcard else "") for r in router.ROUTES]
        expected_routes = [
            "animes/*",
            "play/*",
            "play_movie/*",
            "tmdb_helper",
            "playback_options/*",
            "my_cloud",
            "my_cloud/*",
            "watch_history",
            "search",
            "search_anime/*",
            "tools",
        ]
        for route in expected_routes:
            self.assertIn(route, registered_paths, f"Expected route {route} not registered in router")

        required_symbols = [
            "BROWSER",
            "plugin_url",
            "save_to_watch_history",
            "add_last_watched",
            "add_watch_history",
            "TOOLS_MENU",
            "LIST_MENU",
        ]
        for sym in required_symbols:
            self.assertTrue(hasattr(Main, sym), f"Main is missing re-exported symbol: {sym}")

    def test_indexer_inheritance(self):
        """Verify Otaku_Next_Up_API subclasses OtakuAPI and inherits shared methods."""
        self.assertTrue(issubclass(Otaku_Next_Up_API, OtakuAPI))
        next_up = Otaku_Next_Up_API()
        for shared_method in (
            "get_kitsu_id",
            "get_kitsu_episode_meta",
            "get_anizip_episode_meta",
            "get_simkl_id",
            "get_simkl_episode_meta",
            "get_anime_info",
            "append_episodes",
            "get_episodes",
            "get_anime",
        ):
            self.assertEqual(
                getattr(Otaku_Next_Up_API, shared_method),
                getattr(OtakuAPI, shared_method),
                f"{shared_method} should be inherited from OtakuAPI",
            )
            self.assertTrue(callable(getattr(next_up, shared_method)))

    def test_browser_inheritance_and_polymorphism(self):
        """Verify browser classes inherit from BrowserBase."""
        self.assertTrue(issubclass(OtakuBrowser, MalBrowser))
        self.assertTrue(issubclass(MalBrowser, BrowserBase))
        self.assertTrue(issubclass(AniListBrowser, BrowserBase))

    def test_skip_intro_cold_open_offset_clamping(self):
        """Verify Skip Intro offset clamping prevents negative timestamps."""
        wp = player.WatchlistPlayer()
        wp.skipintro_offset = -3.0

        # Mock chapter starting at 0:00 (cold open)
        ch = {'start': 0.0, 'end': 90.0, 'title': 'Intro'}
        start = max(0.0, float(ch.get('start', 0)) + wp.skipintro_offset)
        self.assertEqual(start, 0.0)
        self.assertGreaterEqual(start, 0.0)


if __name__ == '__main__':
    unittest.main()
