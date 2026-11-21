"""
Regression tests for C-34 (Zero-Wait resolve_silent() candidate pruning & cache persistence)
and C-35 (WatchlistFlavorAuth modal disposal & inactivity auto-close timer).
"""

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

import gc
import threading
import time
import unittest
import weakref
from unittest.mock import MagicMock, patch

import xbmcgui

from resources.lib.ui import control, database, domains
from resources.lib.windows import resolver
from tests.kodi_profile import KodiProfile


class TestC34ResolveSilentPruning(unittest.TestCase):

    def setUp(self):
        database._bump_mem_generation()
        database.clear_episode_sources()
        domains.clear_mirror_failures()

    def tearDown(self):
        database._bump_mem_generation()
        database.clear_episode_sources()
        domains.clear_mirror_failures()

    def test_prunes_failed_lead_embed_promotes_fallback_and_persists_cache(self):
        """C-34: Failing lead embed candidate is pruned, mirror marked unhealthy, and fallback promoted in cache."""
        gogo_embed = {
            'type': 'embed',
            'provider': 'gogo',
            'hash': 'https://gogoanime.me/embed/ep2',
            'release_title': 'Ushio to Tora Ep 2 [gogo]',
        }
        cleo_torrent = {
            'type': 'torrent',
            'provider': 'nyaa',
            'debrid_provider': 'Premiumize',
            'hash': '0123456789abcdef0123456789abcdef01234567',
            'filename': '[Cleo]Ushio_to_Tora_-_02.mkv',
            'episode_re': '02',
            'release_title': '[Cleo]Ushio_to_Tora_-_02',
        }
        hianime_direct = {
            'type': 'direct',
            'provider': 'hianime',
            'hash': 'https://cdn.hianime.to/ep2.m3u8',
            'release_title': 'HiAnime Ep 2',
        }
        sources = [gogo_embed, cleo_torrent, hianime_direct]
        database.set_episode_sources(29854, 2, list(sources))

        mock_pm = MagicMock()
        mock_pm.resolve_single_magnet.return_value = 'https://cdn.example/cleo.mkv'

        with patch('resources.lib.ui.embed_extractor.load_video_from_url', return_value=None), \
             patch('resources.lib.debrid.premiumize.Premiumize', return_value=mock_pm), \
             patch.object(resolver.Resolver, 'prefetch_play_link', return_value={'url': 'https://cdn.example/cleo.mkv', 'headers': {'User-Agent': 'Kodi'}}):
            res = resolver.resolve_silent(sources, 2, mal_id=29854)

        self.assertIsNotNone(res)
        self.assertEqual(res['url'], 'https://cdn.example/cleo.mkv')
        self.assertEqual(res['source']['provider'], 'nyaa')
        self.assertEqual(len(sources), 2)
        self.assertEqual(sources[0]['provider'], 'nyaa')

        cached = database.get_episode_sources(29854, 2)
        self.assertIsNotNone(cached)
        self.assertEqual(len(cached), 2)
        self.assertEqual(cached[0]['provider'], 'nyaa')
        self.assertFalse(domains.is_mirror_healthy('https://gogoanime.me/'))

    def test_prunes_top_three_failures_and_preserves_remaining_tail(self):
        """C-34: When top 3 candidates fail, surviving tail candidates move to head and persist in cache."""
        s0 = {'type': 'embed', 'provider': 'gogo', 'hash': 'https://gogoanime.me/e1'}
        s1 = {'type': 'direct', 'provider': 'vidstream', 'hash': 'https://vidstream.example/e1.mp4'}
        s2 = {'type': 'embed', 'provider': 'mp4upload', 'hash': 'https://mp4upload.example/e1'}
        s3 = {'type': 'torrent', 'provider': 'nyaa', 'debrid_provider': 'Premiumize', 'hash': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'release_title': 'Fallback'}
        sources = [s0, s1, s2, s3]
        database.set_episode_sources(29854, 3, list(sources))

        def _embed_side_effect(url):
            if 'mp4upload' in url:
                raise RuntimeError("dead embed")
            return None

        with patch('resources.lib.ui.embed_extractor.load_video_from_url', side_effect=_embed_side_effect), \
             patch.object(resolver.Resolver, 'prefetch_play_link', return_value=None):
            res = resolver.resolve_silent(sources, 3, mal_id=29854)

        self.assertIsNone(res)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]['provider'], 'nyaa')

        cached = database.get_episode_sources(29854, 3)
        self.assertIsNotNone(cached)
        self.assertEqual(len(cached), 1)
        self.assertEqual(cached[0]['provider'], 'nyaa')

    def test_clears_episode_cache_when_all_candidates_fail(self):
        """C-34: When every candidate fails, sources empties and cached episode sources are cleared."""
        sources = [
            {'type': 'embed', 'provider': 'gogo', 'hash': 'https://gogoanime.me/ep4'},
            {'type': 'direct', 'provider': 'badhost', 'hash': 'https://badhost.example/ep4.mp4'},
        ]
        database.set_episode_sources(29854, 4, list(sources))

        with patch('resources.lib.ui.embed_extractor.load_video_from_url', return_value=None), \
             patch.object(resolver.Resolver, 'prefetch_play_link', return_value=None):
            res = resolver.resolve_silent(sources, 4, mal_id=29854)

        self.assertIsNone(res)
        self.assertEqual(sources, [])
        self.assertIsNone(database.get_episode_sources(29854, 4))

    def test_handles_empty_tuple_and_none_ids_safely(self):
        """C-34: Empty inputs, tuple inputs, and None mal_id/episode do not crash or touch episode DB cache."""
        self.assertIsNone(resolver.resolve_silent([], 1, mal_id=29854))
        self.assertIsNone(resolver.resolve_silent(None, 1, mal_id=29854))

        s0_fail = {'type': 'embed', 'provider': 'gogo', 'hash': 'https://gogoanime.me/ep5'}
        s1_ok = {'type': 'direct', 'provider': 'goodcdn', 'hash': 'https://goodcdn.example/ep5.mkv'}

        with patch('resources.lib.ui.embed_extractor.load_video_from_url', return_value=None), \
             patch.object(resolver.Resolver, 'prefetch_play_link', return_value={'url': 'https://goodcdn.example/ep5.mkv', 'headers': {}}), \
             patch.object(database, 'set_episode_sources') as mock_set, \
             patch.object(database, 'clear_episode_sources') as mock_clear:
            res = resolver.resolve_silent((s0_fail, s1_ok), None, mal_id=None)

        self.assertIsNotNone(res)
        self.assertEqual(res['url'], 'https://goodcdn.example/ep5.mkv')
        mock_set.assert_not_called()
        mock_clear.assert_not_called()

    def test_episode_zero_isolation_preserves_other_episodes(self):
        """C-34: episode=0 (OVA/prologue) cache updates and clears never wipe episode>=1 for the same mal_id."""
        ep1_sources = [{'type': 'direct', 'provider': 'ok', 'hash': 'https://ok.example/1.mp4'}]
        ep0_bad = {'type': 'direct', 'provider': 'bad', 'hash': 'https://bad.example/0.mp4'}
        ep0_good = {'type': 'direct', 'provider': 'good', 'hash': 'https://good.example/0.mp4'}

        database.set_episode_sources(2001, 1, list(ep1_sources))
        database.set_episode_sources(2001, 0, [ep0_bad, ep0_good])
        self.assertEqual(database.get_episode_sources(2001, 0), [ep0_bad, ep0_good])

        # Partial pruning on episode=0 updates only episode 0
        ep0_pair = [ep0_bad, ep0_good]
        with patch.object(
            resolver.Resolver,
            'prefetch_play_link',
            side_effect=[None, {'url': 'https://good.example/0.mp4', 'headers': {}}],
        ):
            res = resolver.resolve_silent(ep0_pair, 0, mal_id=2001)

        self.assertIsNotNone(res)
        self.assertEqual(res['url'], 'https://good.example/0.mp4')
        self.assertEqual(database.get_episode_sources(2001, 0), [ep0_good])
        self.assertEqual(database.get_episode_sources(2001, 1), ep1_sources)

        # All candidates failing on episode=0 clears ONLY episode 0 and keeps episode 1 intact
        with patch.object(resolver.Resolver, 'prefetch_play_link', return_value=None):
            res_fail = resolver.resolve_silent([ep0_bad], 0, mal_id=2001)

        self.assertIsNone(res_fail)
        self.assertIsNone(database.get_episode_sources(2001, 0))
        self.assertEqual(database.get_episode_sources(2001, 1), ep1_sources)

    def test_mal_id_zero_isolation_and_empty_string_safety(self):
        """C-34: mal_id=0 and empty/None IDs never drop writes or wipe unrelated shows' caches."""
        other_show = [{'type': 'direct', 'provider': 'ok', 'hash': 'https://ok.example/other.mp4'}]
        another_show = [{'type': 'direct', 'provider': 'ok', 'hash': 'https://ok.example/another.mp4'}]
        zero_bad = {'type': 'direct', 'provider': 'bad', 'hash': 'https://bad.example/0.mp4'}
        zero_good = {'type': 'direct', 'provider': 'good', 'hash': 'https://good.example/0.mp4'}

        database.set_episode_sources(2002, 1, list(other_show))
        database.set_episode_sources(2003, 1, list(another_show))
        database.set_episode_sources(0, 1, [zero_bad, zero_good])
        self.assertEqual(database.get_episode_sources(0, 1), [zero_bad, zero_good])

        # Partial pruning on mal_id=0 persists under (0, 1) without affecting other shows
        zero_pair = [zero_bad, zero_good]
        with patch.object(
            resolver.Resolver,
            'prefetch_play_link',
            side_effect=[None, {'url': 'https://good.example/0.mp4', 'headers': {}}],
        ):
            res = resolver.resolve_silent(zero_pair, 1, mal_id=0)

        self.assertIsNotNone(res)
        self.assertEqual(database.get_episode_sources(0, 1), [zero_good])
        self.assertEqual(database.get_episode_sources(2002, 1), other_show)

        # Full failure on mal_id=0 clears only (0, 1), leaving (2002, 1) intact
        with patch.object(resolver.Resolver, 'prefetch_play_link', return_value=None):
            res_fail = resolver.resolve_silent([zero_bad], 1, mal_id=0)

        self.assertIsNone(res_fail)
        self.assertIsNone(database.get_episode_sources(0, 1))
        self.assertEqual(database.get_episode_sources(2002, 1), other_show)

        # Empty/missing ID combinations in clear_episode_sources must not trigger global wipes
        database.clear_episode_sources('', 1)
        database.clear_episode_sources(None, 1)
        database.clear_episode_sources(2002, '')
        self.assertEqual(database.get_episode_sources(2002, 1), other_show)

        # Backwards-compatible show-level clear (episode=None) removes only that show
        database.clear_episode_sources(2002)
        self.assertIsNone(database.get_episode_sources(2002, 1))
        self.assertEqual(database.get_episode_sources(2003, 1), another_show)


class TestC35WlfAuthDisposalAndIdleTimeout(unittest.TestCase):

    def test_get_auth_dialog_disposes_modal_on_success_and_exception(self):
        """C-35: get_auth_dialog() closes and releases WatchlistFlavorAuth on both success and exception."""
        from resources.lib import WatchlistIntegration
        from resources.lib.windows import wlf_auth

        created_refs = []
        close_counts = []

        class _FakeAuthSuccess:
            def __init__(self, xml_file, location, flavor=None):
                self.flavor = flavor
                self.closed = False
                created_refs.append(weakref.ref(self))

            def doModal(self):
                return True

            def close(self):
                self.closed = True
                close_counts.append('closed')

        with patch.object(wlf_auth, 'WatchlistFlavorAuth', _FakeAuthSuccess), \
             patch.object(WatchlistIntegration.WatchlistFlavor, 'login_request', return_value='logged_in') as mock_login:
            res = WatchlistIntegration.get_auth_dialog('mal')

        gc.collect()
        self.assertEqual(res, 'logged_in')
        mock_login.assert_called_once_with('mal')
        self.assertEqual(len(close_counts), 1)
        self.assertIsNone(created_refs[0]())

        created_refs.clear()
        close_counts.clear()

        class _FakeAuthCrash:
            def __init__(self, xml_file, location, flavor=None):
                created_refs.append(weakref.ref(self))

            def doModal(self):
                raise RuntimeError("modal failure")

            def close(self):
                close_counts.append('closed_on_err')

        with patch.object(wlf_auth, 'WatchlistFlavorAuth', _FakeAuthCrash):
            with self.assertRaises(RuntimeError):
                WatchlistIntegration.get_auth_dialog('anilist')

        gc.collect()
        self.assertEqual(close_counts, ['closed_on_err'])
        self.assertIsNone(created_refs[0]())

    def test_wlf_auth_default_idle_timeout_and_auto_close_under_kodi22(self):
        """C-35: WatchlistFlavorAuth defaults to 300s idle timeout and auto-closes unattended dialogs."""
        from resources.lib.windows.wlf_auth import WatchlistFlavorAuth

        with KodiProfile('22', strict_skin_controls=True):
            default_dlg = WatchlistFlavorAuth('wlf_auth_mal.xml', control.ADDON_PATH, flavor='mal')
            self.assertEqual(default_dlg.idle_timeout, 300.0)
            default_dlg.close()

            modal_done = threading.Event()
            dlg = WatchlistFlavorAuth('wlf_auth_mal.xml', control.ADDON_PATH, flavor='mal', idle_timeout=0.05)

            def _fake_do_modal(win_self):
                modal_done.wait(timeout=2.0)

            def _fake_close(win_self):
                modal_done.set()

            with patch.object(xbmcgui.WindowXMLDialog, 'doModal', _fake_do_modal), \
                 patch.object(xbmcgui.WindowXMLDialog, 'close', _fake_close):
                auth = dlg.doModal()

            self.assertFalse(auth)
            self.assertTrue(dlg._win_closed)
            self.assertIsNone(dlg._idle_thread)

    def test_wlf_auth_activity_resets_idle_timer_and_abort_closes_promptly(self):
        """C-35: User input resets idle timeout and Kodi abortRequested closes the dialog immediately."""
        from resources.lib.windows.wlf_auth import WatchlistFlavorAuth

        with KodiProfile('22', strict_skin_controls=True):
            # 1) Activity reset keeps dialog alive past initial timeout, then Cancel (1003) closes cleanly
            modal_done = threading.Event()
            dlg = WatchlistFlavorAuth('wlf_auth_mal.xml', control.ADDON_PATH, flavor='mal', idle_timeout=0.12)

            def _fake_do_modal(win_self):
                modal_done.wait(timeout=2.0)

            def _fake_close(win_self):
                modal_done.set()

            def _driver():
                time.sleep(0.05)
                act = MagicMock()
                act.getId.return_value = 4  # ACTION_MOVE_DOWN (non-closing)
                dlg.onAction(act)
                time.sleep(0.08)
                # Still open after 0.13s because onAction reset the 0.12s timer
                self.assertFalse(dlg._win_closed)
                dlg.onClick(1003)

            with patch.object(xbmcgui.WindowXMLDialog, 'doModal', _fake_do_modal), \
                 patch.object(xbmcgui.WindowXMLDialog, 'close', _fake_close):
                t = threading.Thread(target=_driver, daemon=True)
                t.start()
                auth = dlg.doModal()
                t.join(timeout=1.0)

            self.assertFalse(auth)
            self.assertTrue(dlg._win_closed)
            self.assertIsNone(dlg._idle_thread)

            # 2) abortRequested closes even with 300s idle timeout without waiting
            abort_done = threading.Event()
            dlg_abort = WatchlistFlavorAuth('wlf_auth_mal.xml', control.ADDON_PATH, flavor='mal', idle_timeout=300)

            def _abort_do_modal(win_self):
                abort_done.wait(timeout=2.0)

            def _abort_close(win_self):
                abort_done.set()

            with patch.object(xbmcgui.WindowXMLDialog, 'doModal', _abort_do_modal), \
                 patch.object(xbmcgui.WindowXMLDialog, 'close', _abort_close), \
                 patch.object(control.monitor, 'abortRequested', return_value=True):
                t0 = time.monotonic()
                auth_abort = dlg_abort.doModal()
                elapsed = time.monotonic() - t0

            self.assertFalse(auth_abort)
            self.assertTrue(dlg_abort._win_closed)
            self.assertIsNone(dlg_abort._idle_thread)
            self.assertLess(elapsed, 1.5)


if __name__ == '__main__':
    unittest.main()
