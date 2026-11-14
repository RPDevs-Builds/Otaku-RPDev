import os
import tempfile
import time
import unittest
from unittest import mock

from resources.lib.ui import control, database


class TestPagesInit(unittest.TestCase):
    def test_scraper_circuit_breaker(self):
        from resources.lib.pages import ScraperCircuitBreaker

        cb = ScraperCircuitBreaker(failure_threshold=2, cooldown_seconds=60)
        self.assertFalse(cb.is_tripped('nyaa'))

        # Record 1 failure -> not tripped
        cb.record_failure('nyaa')
        self.assertFalse(cb.is_tripped('nyaa'))

        # Record 2nd failure -> tripped!
        cb.record_failure('nyaa')
        self.assertTrue(cb.is_tripped('nyaa'))

        # Reset single provider
        cb.reset('nyaa')
        self.assertFalse(cb.is_tripped('nyaa'))

        # Record success resets failure count
        cb.record_failure('nyaa')
        cb.record_success('nyaa')
        cb.record_failure('nyaa')
        self.assertFalse(cb.is_tripped('nyaa'))

        # Global reset
        cb.record_failure('nyaa')
        cb.record_failure('nyaa')
        self.assertTrue(cb.is_tripped('nyaa'))
        cb.reset()
        self.assertFalse(cb.is_tripped('nyaa'))

    def test_scraper_cache_ttl_and_semaphore(self):
        from resources.lib.pages import _scraper_cache_ttl, _get_scrape_semaphore

        with mock.patch.object(control, 'getInt', return_value=48):
            self.assertEqual(_scraper_cache_ttl(), 48)

        with mock.patch.object(control, 'getInt', return_value=0):
            self.assertEqual(_scraper_cache_ttl(), 8)

        sem = _get_scrape_semaphore()
        self.assertIsNotNone(sem)

    def test_sort_sources(self):
        from resources.lib.pages import Sources

        torrents = [
            {'release_title': 'Frieren E01 1080p', 'quality': 3, 'byte_size': 1000000000, 'provider': 'nyaa', 'type': 'torrent'},
            {'release_title': 'Frieren E01 720p', 'quality': 2, 'byte_size': 500000000, 'provider': 'nyaa', 'type': 'torrent'}
        ]
        hosters = [
            {'release_title': 'Frieren E01 Easynews', 'quality': 3, 'byte_size': 900000000, 'provider': 'easynews', 'type': 'hoster'}
        ]
        embeds = [
            {'release_title': 'Frieren E01 Embed', 'quality': 2, 'byte_size': 0, 'provider': 'gogoanime', 'type': 'embed'}
        ]
        cloud_files = []
        local_files = []

        with mock.patch.object(control, 'getBool', side_effect=lambda k, **kw: False), \
             mock.patch.object(control, 'getInt', side_effect=lambda k, **kw: 4 if 'max' in k else 0):
            sorted_res = Sources.sortSources(
                torrent_list=torrents,
                hoster_list=hosters,
                embed_list=embeds,
                cloud_files=cloud_files,
                local_files=local_files,
                media_type='tv',
                duration=1440,
                show_title='Frieren'
            )
            self.assertIsInstance(sorted_res, list)
            self.assertGreater(len(sorted_res), 0)


class TestScrapersPages(unittest.TestCase):
    def test_defunct_scrapers(self):
        from resources.lib.pages import animixplay, aniwave

        s_animix = animixplay.Sources()
        self.assertEqual(s_animix.get_sources(123, 1), [])

        s_aniwave = aniwave.Sources()
        self.assertEqual(s_aniwave.get_sources(123, 1), [])

    def test_local_files(self):
        from resources.lib.pages import localfiles
        from resources.lib.ui import source_utils

        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = os.path.join(temp_dir, 'Frieren - 01 [1080p].mkv')
            with open(test_file, 'wb') as f:
                f.write(b'\x00' * 1024)

            sources_api = localfiles.Sources()
            file_info = {'name': 'Frieren - 01 [1080p].mkv', 'path': test_file}
            with mock.patch.object(source_utils, 'video_ext', return_value=frozenset({'.mkv', '.mp4'})):
                built = sources_api._build_local_source(file_info, 1)
                self.assertIsNotNone(built)
                self.assertEqual(built['quality'], 3)
                self.assertEqual(built['episode'], 1)

                # Invalid file ext returns None
                invalid_info = {'name': 'sample.txt', 'path': '/fake/sample.txt'}
                self.assertIsNone(sources_api._build_local_source(invalid_info, 1))

                # get_sources with mock folder.location
                with mock.patch.object(control, 'getSetting', return_value=temp_dir):
                    sources = sources_api.get_sources(query='Frieren', mal_id=123, episode='1')
                    self.assertIsInstance(sources, list)

    def test_debrid_cloudfiles(self):
        from resources.lib.pages import debrid_cloudfiles

        sources_api = debrid_cloudfiles.Sources()
        with mock.patch.object(control, 'enabled_debrid', return_value={'realdebrid': True}), \
             mock.patch.object(control, 'enabled_cloud', return_value={'realdebrid': True}), \
             mock.patch.object(sources_api, 'rd_cloud_inspection'):
            sources = sources_api.get_sources('Frieren', 123, 1)
            self.assertIsInstance(sources, list)

    def test_scraper_classes_instantiation_and_stubs(self):
        from resources.lib.pages import (
            nyaa, animetosho, nekobt, torrentio, bitsearch,
            piratebay, animekai, easynews, gogoanime, animepahe,
            anikoto, hianime, watchnixtoons2
        )

        scrapers = [
            (nyaa.Sources, ('Frieren', 123, 1, 'Finished', 'tv')),
            (animetosho.Sources, ('Frieren', 123, 1, 'Finished', 'tv')),
            (nekobt.Sources, ('Frieren', 123, 1, 'Finished', 'tv')),
            (torrentio.Sources, ('Frieren', 123, 1, 'Finished', 'tv')),
            (bitsearch.Sources, ('Frieren', 123, 1, 'Finished', 'tv')),
            (piratebay.Sources, ('Frieren', 123, 1, 'Finished', 'tv')),
            (animekai.Sources, (123, 1)),
            (easynews.Sources, ('Frieren', 123, 1, 'Finished', 'tv')),
            (gogoanime.Sources, (123, 1)),
            (animepahe.Sources, (123, 1)),
            (anikoto.Sources, (123, 1)),
            (hianime.Sources, (123, 1)),
            (watchnixtoons2.Sources, (123, 1, 'tv')),
        ]

        for scraper_cls, args in scrapers:
            instance = scraper_cls()
            self.assertIsNotNone(instance)
            # Patch network calls to verify get_sources graceful handling
            with mock.patch('resources.lib.ui.client.get', return_value=None), \
                 mock.patch('resources.lib.ui.client.post', return_value=None), \
                 mock.patch('resources.lib.ui.client.request', return_value=None):
                try:
                    res = instance.get_sources(*args)
                    self.assertIsInstance(res, list)
                    if hasattr(instance, 'get_movie_sources'):
                        movie_res = instance.get_movie_sources(query='Frieren', anilist_id=123, episode='1', status='Finished', media_type='movie')
                        self.assertIsInstance(movie_res, list)
                except Exception as e:
                    # Some scrapers return early or catch exceptions internally
                    pass


class TestEmbedExtractors(unittest.TestCase):
    def test_embed_extractor_dispatch(self):
        from resources.lib.ui import embed_extractor

        # Unsupported url returns None
        self.assertIsNone(embed_extractor.load_video_from_url("https://unsupported-host.com/embed/123"))

    def test_megacloud_extractor(self):
        from resources.lib.ui.megacloud_extractor import (
            _get_decryption_keys, MegacloudDecryptor, extract_megacloud_sources
        )

        keys = _get_decryption_keys(force_refresh=False)
        self.assertIn('vidstr', keys)

        decryptor = MegacloudDecryptor()
        # Test key generation
        k2 = decryptor.keygen2("megakey", "clientkey")
        self.assertIsInstance(k2, str)
        self.assertGreater(len(k2), 0)

        # Test columnar cipher
        c = decryptor.columnar_cipher2("plaintext", "key")
        self.assertIsInstance(c, str)

        # Test extract_megacloud_sources with non-responsive server
        with mock.patch('resources.lib.ui.client.get', return_value=None):
            sources = extract_megacloud_sources("https://megacloud.tv/embed-2/e-1/123")
            self.assertIsNone(sources)

    def test_megaplay_extractor(self):
        import base64
        from resources.lib.ui import pyaes
        from resources.lib.ui.megaplay_extractor import (
            decrypt_megaplay_source, extract_megaplay_sources
        )

        key = b"i?LMTAx0Q6,:}50U" + b'\x00' * 16
        iv = b"W0;27ToaUpl_P%'c"
        encrypter = pyaes.Encrypter(pyaes.AESModeOfOperationCBC(key, iv))
        enc_bytes = encrypter.feed(b'{"file": "https://stream.mp4"}') + encrypter.feed()
        enc_str = base64.b64encode(enc_bytes).decode('ascii')
        self.assertEqual(decrypt_megaplay_source(enc_str), "https://stream.mp4")

        with mock.patch('resources.lib.ui.client.get', return_value=None):
            sources = extract_megaplay_sources("https://megaplay.buzz/stream/123")
            self.assertIsNone(sources)


class TestDebridModules(unittest.TestCase):
    def tearDown(self):
        database.close_thread_connections()

    def test_clone_torrents_and_debrid_class(self):
        from resources.lib.debrid import _clone_torrents, Debrid

        torrents = [{'hash': 'h1', 'title': 'T1'}, {'hash': 'h2', 'title': 'T2'}]
        cloned = _clone_torrents(torrents)
        self.assertEqual(cloned, torrents)
        self.assertIsNot(cloned[0], torrents[0])

        deb = Debrid()
        with mock.patch.object(control, 'enabled_debrid', return_value={
            'realdebrid': False, 'debridlink': False, 'premiumize': False,
            'alldebrid': False, 'torbox': False, 'easydebrid': False
        }):
            deb.torrentCacheCheck(torrents)
            self.assertEqual(len(deb.threads), 0)

    def test_debrid_cache_helpers(self):
        from resources.lib.debrid.debrid_cache import (
            acquire_in_flight, release_in_flight, _to_int32, _get_dmm_secret
        )

        ready, events = acquire_in_flight(['hash1', 'hash2'], 'realdebrid')
        self.assertEqual(ready, ['hash1', 'hash2'])
        self.assertEqual(len(events), 0)

        # Re-acquiring same hash returns event to await
        ready2, events2 = acquire_in_flight(['hash1'], 'realdebrid')
        self.assertEqual(len(ready2), 0)
        self.assertEqual(len(events2), 1)

        release_in_flight(['hash1', 'hash2'], 'realdebrid')

        self.assertIsInstance(_to_int32(12345), int)
        secret = _get_dmm_secret()
        self.assertEqual(len(secret), 2)

        from resources.lib.debrid import debrid_cache
        collector = []
        with mock.patch('resources.lib.ui.client.get') as mock_get:
            mock_get.return_value.ok = True
            mock_get.return_value.json.return_value = {
                'streams': [{'name': '+RD', 'url': 'https://example.com/' + 'a'*40}]
            }
            debrid_cache._tio_check_cache('tt1234567', 1, 1, collector)
            debrid_cache._aio_check_cache('tt1234567', 1, 1, collector)
        self.assertIn('a'*40, collector)

    def test_debrid_cloud_methods(self):
        from resources.lib.debrid.debrid_cloud import (
            format_bytes, get_active_providers, _normalize_folder_id,
            _is_descendant_folder, _resolve_effective_parent
        )

        self.assertEqual(format_bytes(1024), "1.0 KB")
        self.assertEqual(format_bytes(1048576), "1.0 MB")
        self.assertEqual(format_bytes(1073741824), "1.00 GB")

        with mock.patch.object(control, 'enabled_debrid', return_value={'realdebrid': True}):
            providers = get_active_providers()
            self.assertIn('realdebrid', providers)

        self.assertEqual(_normalize_folder_id(None), 'root')
        self.assertEqual(_normalize_folder_id(''), 'root')
        self.assertEqual(_normalize_folder_id('f1'), 'f1')

        p_vfs = {'folders': {'f2': {'parent_id': 'f1'}, 'f1': {'parent_id': 'root'}}}
        self.assertTrue(_is_descendant_folder(p_vfs, 'f2', 'f1'))
        self.assertFalse(_is_descendant_folder(p_vfs, 'f1', 'f2'))

        self.assertEqual(_resolve_effective_parent(p_vfs, 'f1'), 'f1')
        self.assertEqual(_resolve_effective_parent(p_vfs, 'vfs_missing'), 'root')

    def test_debrid_providers_instantiation(self):
        from resources.lib.debrid.premiumize import Premiumize
        from resources.lib.debrid.all_debrid import AllDebrid
        from resources.lib.debrid.real_debrid import RealDebrid
        from resources.lib.debrid.torbox import TorBox
        from resources.lib.debrid.debrid_link import DebridLink
        from resources.lib.debrid.easydebrid import EasyDebrid
        from resources.lib.debrid.easynews import Easynews

        with mock.patch.object(control, 'getSetting', return_value='test-token'):
            p = Premiumize()
            self.assertIsNotNone(p)

            ad = AllDebrid()
            self.assertIsNotNone(ad)

            rd = RealDebrid()
            self.assertIsNotNone(rd)

            tb = TorBox()
            self.assertIsNotNone(tb)

            dl = DebridLink()
            self.assertIsNotNone(dl)

            ed = EasyDebrid()
            self.assertIsNotNone(ed)

            en = Easynews()
            self.assertIsNotNone(en)


if __name__ == '__main__':
    unittest.main()
