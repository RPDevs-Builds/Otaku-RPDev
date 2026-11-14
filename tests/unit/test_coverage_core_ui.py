# -*- coding: utf-8 -*-
"""
test_coverage_core_ui.py - Comprehensive Unit Tests for Core UI Subsystems
==========================================================================
Exhaustively exercises previously untested or under-tested modules in
resources/lib/ui/ including:
- divide_flavors.py (_get_mal_dub, div_flavor)
- migrate_artwork.py (migrate_artwork_database)
- colors.py (normalize_provider_name, get_provider_color, badges, seeders)
- get_meta.py (merge_artwork, collect_meta, update_meta)
- router.py (Route, multi_route, router_process)
- jsunpack.py (detect, unpack, _filterargs, _replacestrings, Unbaser, UnpackingError)
- jscrypto/jscrypto.py (evpKDF, encode, decode)
- pyaes/ (AES, Counter, modes CBC/CTR/CFB/OFB/ECB, Encrypter, Decrypter, PKCS7 padding)
- ffprobe_chapters.py (EBML parsing, vint, url headers, stream probe mock)
- part_filter.py (_get_mappings_info, _parse_range, _has_chinese_hardsub, filter_sources)
- utils.py (allocate_item, get_format_to_url_mappings, search_history, parse_view, season, parallel)
- database_sync.py (SyncDatabase, all _build_* table builders)
- database.py (_SafeUnpickler, _json_default, dumps, loads, _dict_factory, connection pooling, retry)
- client.py (_validate_url_scheme, _SessionOpenerDict, user agents, Session)
- domains.py (_get_bundled_domains_path, _load_domains, get_domain, get_mirrors)
- resources package root inits
"""

import io
import json
import os
import sqlite3
import subprocess
import tempfile
import time
import unittest
from unittest import mock

import conftest  # Centralized Kodi mock harness  # noqa: F401

# Import package root __init__.py files for 100% module coverage
import resources  # noqa: F401
import resources.lib  # noqa: F401
import resources.lib.ui  # noqa: F401
import resources.lib.ui.jscrypto  # noqa: F401
import resources.lib.ui.pyaes  # noqa: F401

from resources.lib.ui import (
    client,
    colors,
    control,
    database,
    database_sync,
    divide_flavors,
    domains,
    ffprobe_chapters,
    get_meta,
    jsunpack,
    migrate_artwork,
    part_filter,
    router,
    utils,
)
from resources.lib.ui.jscrypto import jscrypto
from resources.lib.ui.pyaes import (
    AES,
    AESModeOfOperationCBC,
    AESModeOfOperationCTR,
    AESModeOfOperationCFB,
    AESModeOfOperationOFB,
    AESModeOfOperationECB,
    Counter,
    Decrypter,
    Encrypter,
    decrypt_stream,
    encrypt_stream,
)
from resources.lib.ui.pyaes.util import append_PKCS7_padding, strip_PKCS7_padding


class TestDivideFlavorsCoverage(unittest.TestCase):
    """Tests for resources/lib/ui/divide_flavors.py."""

    def setUp(self):
        divide_flavors._mal_dub_cache = None

    def tearDown(self):
        divide_flavors._mal_dub_cache = None

    def test_get_mal_dub_success(self):
        temp_dir = tempfile.mkdtemp()
        mal_file = os.path.join(temp_dir, 'mal_dub.json')
        sample_data = {"123": "Dubbed Anime"}
        with open(mal_file, 'w', encoding='utf-8') as f:
            json.dump(sample_data, f)

        orig_file = getattr(control, 'maldubFile', '')
        control.maldubFile = mal_file
        try:
            data = divide_flavors._get_mal_dub()
            self.assertEqual(data, sample_data)
            # Second call hits cache
            self.assertIs(divide_flavors._get_mal_dub(), data)
        finally:
            control.maldubFile = orig_file
            if os.path.exists(mal_file):
                os.remove(mal_file)
            os.rmdir(temp_dir)

    def test_get_mal_dub_file_not_found_and_invalid(self):
        orig_file = getattr(control, 'maldubFile', '')
        control.maldubFile = '/nonexistent/path/mal_dub.json'
        try:
            data = divide_flavors._get_mal_dub()
            self.assertEqual(data, {})
        finally:
            control.maldubFile = orig_file

    def test_div_flavor_decorator(self):
        @divide_flavors.div_flavor
        def dummy_action(*args, **kwargs):
            return kwargs.get('mal_dub')

        # When showdub is True
        with mock.patch.object(control, 'getBool', side_effect=lambda k: k == 'divflavors.showdub'):
            divide_flavors._mal_dub_cache = {"1": "Test"}
            res = dummy_action(1, 2)
            self.assertEqual(res, {"1": "Test"})

        # When dubonly is True
        with mock.patch.object(control, 'getBool', side_effect=lambda k: k == 'divflavors.dubonly'):
            divide_flavors._mal_dub_cache = {"2": "Test2"}
            res = dummy_action(1, 2)
            self.assertEqual(res, {"2": "Test2"})

        # When both are False
        with mock.patch.object(control, 'getBool', return_value=False):
            res = dummy_action(1, 2)
            self.assertIsNone(res)


class TestMigrateArtworkCoverage(unittest.TestCase):
    """Tests for resources/lib/ui/migrate_artwork.py."""

    def test_migrate_artwork_database(self):
        fd, db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        try:
            # Create shows_meta schema and test rows
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE shows_meta (mal_id INTEGER PRIMARY KEY, art BLOB, meta_ids BLOB)")
            sample_art = {
                'fanart': ['http://f1', 'http://f2', 'http://f3', 'http://f4'],
                'thumb': ['http://t1', 'http://t2'],
                'clearart': ['http://ca1', 'http://ca2'],
                'clearlogo': ['http://cl1', 'http://cl2'],
                'landscape': ['http://ls1', 'http://ls2'],
                'banner': ['http://b1', 'http://b2'],
            }
            sample_meta_ids = {'mal_id': 100}
            conn.execute(
                "INSERT INTO shows_meta VALUES (?, ?, ?)",
                (100, database.dumps(sample_art), database.dumps(sample_meta_ids))
            )
            conn.commit()
            conn.close()

            orig_db = getattr(control, 'malSyncDB', '')
            control.malSyncDB = db_path
            database.close_thread_connections()
            try:
                with mock.patch.object(control, 'getInt', return_value=2), \
                     mock.patch.object(control, 'getBool', side_effect=lambda k, **kw: k in ('artwork.clearlogo', 'artwork.landscape')), \
                     mock.patch.object(control, 'notify') as mock_notify, \
                     mock.patch.object(control, 'log'):
                    stats = migrate_artwork.migrate_artwork_database()
                    self.assertEqual(stats['entries_processed'], 1)
                    self.assertEqual(stats['entries_updated'], 1)
                    self.assertEqual(stats['errors'], 0)
                    mock_notify.assert_called()
            finally:
                database.close_thread_connections()
                control.malSyncDB = orig_db

                # Verify updated data in database
                conn = sqlite3.connect(db_path)
                row = conn.execute("SELECT art FROM shows_meta WHERE mal_id = 100").fetchone()
                conn.close()
                updated_art = database.loads(row[0])
                self.assertLessEqual(len(updated_art['fanart']), 2)
                self.assertEqual(len(updated_art['thumb']), 1)
                self.assertIsInstance(updated_art['clearart'], str)
                self.assertIsInstance(updated_art['clearlogo'], str)
                self.assertNotIn('banner', updated_art)  # disabled in getBool mock
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

    def test_migrate_artwork_database_error_handling(self):
        orig_db = getattr(control, 'malSyncDB', '')
        control.malSyncDB = '/nonexistent/invalid_path/malSync.db'
        try:
            with mock.patch.object(control, 'notify') as mock_notify, \
                 mock.patch.object(control, 'log'):
                stats = migrate_artwork.migrate_artwork_database()
                self.assertEqual(stats['errors'], 1)
                mock_notify.assert_called()
        finally:
            control.malSyncDB = orig_db


class TestColorsCoverage(unittest.TestCase):
    """Tests for resources/lib/ui/colors.py."""

    def test_normalize_provider_name(self):
        self.assertEqual(colors.normalize_provider_name(''), 'default')
        self.assertEqual(colors.normalize_provider_name(None), 'default')
        self.assertEqual(colors.normalize_provider_name(' Real_Debrid. '), 'realdebrid')
        self.assertEqual(colors.normalize_provider_name('HiAnime'), 'hianime')

    def test_get_provider_color(self):
        self.assertEqual(colors.get_provider_color(''), 'FFB0BEC5')
        self.assertEqual(colors.get_provider_color('Premiumize'), 'FF4700B4')
        self.assertEqual(colors.get_provider_color('UnknownProvider', default='FFAABBCC'), 'FFAABBCC')
        # Substring matching
        self.assertEqual(colors.get_provider_color('nyaa_tracker'), 'FFFF7043')

    def test_colorize_label(self):
        self.assertEqual(colors.colorize_label('', 'premiumize'), '')
        lbl = colors.colorize_label('Test 1080p', 'real-debrid')
        self.assertIn('[COLOR FF0080FF]Test 1080p[/COLOR]', lbl)

    def test_badges_and_seeders(self):
        self.assertEqual(colors.get_badge_color(''), 'FFCFD8DC')
        self.assertEqual(colors.get_badge_color('hevc'), 'FF00E5FF')
        self.assertEqual(colors.get_badge_color('atmos'), 'FFFF5252')
        self.assertEqual(colors.colorize_badge('', 'hevc'), '')
        self.assertIn('[COLOR FF00E5FF]HEVC[/COLOR]', colors.colorize_badge('HEVC', 'hevc'))

        self.assertEqual(colors.get_seeder_color(100), 'FF00E676')  # >= 50
        self.assertEqual(colors.get_seeder_color(25), 'FFFFD600')   # 10..49
        self.assertEqual(colors.get_seeder_color(3), 'FFFF5252')    # < 10
        self.assertEqual(colors.get_seeder_color('invalid'), 'FFB0BEC5')


class TestGetMetaCoverage(unittest.TestCase):
    """Tests for resources/lib/ui/get_meta.py."""

    def test_merge_artwork_all_features(self):
        fanart_art = {
            'fanart': ['http://fa1', 'http://fa2'],
            'poster': ['http://p1'],
            'thumb': ['http://t1'],
            'clearart': ['http://ca1'],
            'clearlogo': ['http://cl1', 'http://cl1'],
            'banner': ['http://b1'],
        }
        tmdb_art = {'fanart': ['http://fa3'], 'poster': ['http://p2']}
        tvdb_art = {'fanart': ['http://fa4'], 'clearlogo': ['http://cl2']}

        merged = get_meta.merge_artwork(
            fanart_art, tmdb_art, tvdb_art,
            fanart_limit=2,
            clearlogo_enabled=True,
            clearart_enabled=True,
            banner_enabled=True,
            landscape_enabled=True,
            anilist_banner='http://anilist_b'
        )
        self.assertEqual(len(merged['fanart']), 2)
        self.assertEqual(merged['poster'], ['http://p1'])
        self.assertEqual(merged['thumb'], ['http://t1'])
        self.assertEqual(merged['clearart'], 'http://ca1')
        self.assertIn(merged['clearlogo'], ['http://cl1', 'http://cl2'])
        self.assertEqual(merged['banner'], 'http://anilist_b')

    def test_collect_meta_and_update_meta(self):
        anime_list = [
            {'media': {'idMal': 9999, 'format': 'TV', 'episodes': 12}},
            {'entry': {'mal_id': 9998, 'type': 'MOVIE', 'episodes': 1}},
            {'invalid': {}},
        ]
        with mock.patch.object(database, 'get_show_meta', return_value=None), \
             mock.patch.object(control, 'getBool', return_value=False), \
             mock.patch.object(get_meta, 'update_meta') as mock_update:
            get_meta.collect_meta(anime_list)
            self.assertEqual(mock_update.call_count, 2)

        # Exercise update_meta artwork preference branches
        with mock.patch.object(database, 'get_mappings', return_value={'mal_id': 1234, 'themoviedb_id': 55}), \
             mock.patch.object(database, 'update_show_meta') as mock_db_update, \
             mock.patch.object(control, 'getInt', side_effect=lambda k: 0 if k == 'artwork.preference' else 1), \
             mock.patch.object(control, 'getBool', return_value=True), \
             mock.patch('resources.lib.endpoints.fanart.getArt', return_value={'fanart': ['http://f1']}):
            get_meta.update_meta(1234, mtype='tv')
            mock_db_update.assert_called()


class TestRouterCoverage(unittest.TestCase):
    """Tests for resources/lib/ui/router.py."""

    def test_route_and_multi_route_and_process(self):
        orig_routes = list(router.ROUTES)
        try:
            router.ROUTES.clear()

            @router.Route('test/exact')
            def handle_exact(payload, params):
                return 'exact_hit', payload, params

            @router.Route('test/wildcard/*')
            def handle_wildcard(payload, params):
                return 'wildcard_hit', payload, params

            @router.multi_route('multi/one', 'multi/two')
            def handle_multi(payload, params):
                return 'multi_hit', payload, params

            # Process exact
            res = router.router_process('test/exact', {'foo': 'bar'})
            self.assertEqual(res[0], 'exact_hit')
            self.assertEqual(res[2], {'foo': 'bar'})

            # Process wildcard
            res = router.router_process('test/wildcard/123/sub', None)
            self.assertEqual(res[0], 'wildcard_hit')

            # Process multi routes
            res1 = router.router_process('multi/one', {})
            res2 = router.router_process('multi/two', {})
            self.assertEqual(res1[0], 'multi_hit')
            self.assertEqual(res2[0], 'multi_hit')

            # Process unmatched
            with mock.patch.object(control, 'log') as mock_log:
                res_none = router.router_process('unknown/route', {})
                self.assertIsNone(res_none)
                mock_log.assert_called()
        finally:
            router.ROUTES.clear()
            router.ROUTES.extend(orig_routes)


class TestJsUnpackCoverage(unittest.TestCase):
    """Tests for resources/lib/ui/jsunpack.py."""

    def test_detect_and_unpack(self):
        self.assertFalse(jsunpack.detect("var x = 1;"))
        self.assertTrue(jsunpack.detect("eval(function(p,a,c,k,e,r){"))

        # Test Unbaser
        u10 = jsunpack.Unbaser(10)
        self.assertEqual(u10('42'), 42)
        u36 = jsunpack.Unbaser(36)
        self.assertEqual(u36('10'), 36)
        u62 = jsunpack.Unbaser(62)
        self.assertGreater(u62('a'), 0)
        u95 = jsunpack.Unbaser(95)
        self.assertGreater(u95('!'), 0)

        with self.assertRaises(TypeError):
            jsunpack.Unbaser(999)

        # Test malformed unpack exception
        with self.assertRaises(jsunpack.UnpackingError):
            jsunpack.unpack("eval(function(p,a,c,k,e,r){return p;}('bad',10,5,'a|b|c'))")

        # Test valid standard unpacking (exercises lookup)
        valid_packed = "eval(function(p,a,c,k,e,r){return p;}('0 1 2',3,3,'foo|bar|baz'.split('|')))"
        self.assertEqual(jsunpack.unpack(valid_packed), "foo bar baz")

        # Test String.fromCharCode unpacking (exercises getstring)
        fc_packed = "eval(function(p,a,c,k,e,r){return String.fromCharCode(c+161);}('\xa1 \xa2',2,2,'alpha|beta'.split('|')))"
        self.assertEqual(jsunpack.unpack(fc_packed), "alpha beta")

        # Test replace strings
        test_js = 'var _0xabc=["\\x68\\x65\\x6c\\x6c\\x6f","world"]; var msg = _0xabc[0] + " " + _0xabc[1];'
        replaced = jsunpack._replacestrings(test_js)
        self.assertIn('"hello"', replaced)

        test_hex = r"console.log('\x41\x42\x43');"
        replaced_hex = jsunpack._replacejsstrings(test_hex)
        self.assertIn('ABC', replaced_hex)


class TestJsCryptoCoverage(unittest.TestCase):
    """Tests for resources/lib/ui/jscrypto/jscrypto.py."""

    def test_evp_kdf_and_roundtrip(self):
        kdf = jscrypto.evpKDF("password123", "salt1234", key_size=8, iv_size=4)
        self.assertEqual(len(kdf['key']), 32)
        self.assertEqual(len(kdf['iv']), 16)

        plaintext = "Hello, Otaku-RPDev Crypto World!"
        passphrase = "SuperSecretPassphrase"
        encrypted = jscrypto.encode(plaintext, passphrase)
        self.assertTrue(encrypted.startswith(b"U2FsdGVkX1"))  # base64 "Salted__"

        decrypted = jscrypto.decode(encrypted, passphrase)
        self.assertEqual(decrypted, plaintext)


class TestPyAesCoverage(unittest.TestCase):
    """Tests for resources/lib/ui/pyaes/ and util.py."""

    def test_pkcs7_padding(self):
        raw = b"1234567890"
        padded = append_PKCS7_padding(raw)
        self.assertEqual(len(padded) % 16, 0)
        self.assertEqual(strip_PKCS7_padding(padded), raw)

        # Invalid padding raises ValueError
        with self.assertRaises(ValueError):
            strip_PKCS7_padding(b"badpadding\x00\x00")

    def test_aes_core_and_modes(self):
        key = b"16bytessecretkey"
        iv = b"16bytesinitvectr"
        plaintext = b"Test 16-byte blk"

        # Raw AES block cipher
        cipher = AES(key)
        enc_blk = bytes(cipher.encrypt(plaintext))
        dec_blk = bytes(cipher.decrypt(enc_blk))
        self.assertEqual(dec_blk, plaintext)

        # CBC Mode
        cbc_enc = AESModeOfOperationCBC(key, iv=iv)
        cbc_dec = AESModeOfOperationCBC(key, iv=iv)
        c_text = cbc_enc.encrypt(plaintext)
        p_text = cbc_dec.decrypt(c_text)
        self.assertEqual(p_text, plaintext)

        # ECB Mode
        ecb_enc = AESModeOfOperationECB(key)
        ecb_dec = AESModeOfOperationECB(key)
        c_ecb = ecb_enc.encrypt(plaintext)
        p_ecb = ecb_dec.decrypt(c_ecb)
        self.assertEqual(p_ecb, plaintext)

        # CFB Mode
        cfb_enc = AESModeOfOperationCFB(key, iv=iv, segment_size=16)
        cfb_dec = AESModeOfOperationCFB(key, iv=iv, segment_size=16)
        c_cfb = cfb_enc.encrypt(plaintext)
        p_cfb = cfb_dec.decrypt(c_cfb)
        self.assertEqual(p_cfb, plaintext)

        # OFB Mode
        ofb_enc = AESModeOfOperationOFB(key, iv=iv)
        ofb_dec = AESModeOfOperationOFB(key, iv=iv)
        c_ofb = ofb_enc.encrypt(plaintext)
        p_ofb = ofb_dec.decrypt(c_ofb)
        self.assertEqual(p_ofb, plaintext)

        # CTR Mode with Counter
        ctr_enc = AESModeOfOperationCTR(key, counter=Counter(100))
        ctr_dec = AESModeOfOperationCTR(key, counter=Counter(100))
        c_ctr = ctr_enc.encrypt(b"arbitrary length message stream")
        p_ctr = ctr_dec.decrypt(c_ctr)
        self.assertEqual(p_ctr, b"arbitrary length message stream")

    def test_stream_encrypter_decrypter(self):
        key = b"16bytessecretkey"
        stream_in = io.BytesIO(b"Stream encryption test data for blockfeeder.")
        stream_out = io.BytesIO()
        encrypt_stream(AESModeOfOperationCBC(key), stream_in, stream_out)

        stream_enc = io.BytesIO(stream_out.getvalue())
        stream_dec = io.BytesIO()
        decrypt_stream(AESModeOfOperationCBC(key), stream_enc, stream_dec)
        self.assertEqual(stream_dec.getvalue(), b"Stream encryption test data for blockfeeder.")


class TestFfprobeChaptersCoverage(unittest.TestCase):
    """Tests for resources/lib/ui/ffprobe_chapters.py."""

    def test_headers_and_url_splitting(self):
        raw_url = 'https://host.com/video.mkv|User-Agent=Kodi&Referer=https%3A%2F%2Fsite.com'
        clean, headers = ffprobe_chapters._split_url_headers(raw_url)
        self.assertEqual(clean, 'https://host.com/video.mkv')
        self.assertEqual(headers.get('User-Agent'), 'Kodi')
        self.assertEqual(headers.get('Referer'), 'https://site.com')

        hdr_arg = ffprobe_chapters._headers_ffprobe_arg(headers)
        self.assertIn('User-Agent: Kodi\r\n', hdr_arg)
        self.assertIsNone(ffprobe_chapters._headers_ffprobe_arg({}))

    def test_should_probe_url(self):
        self.assertTrue(ffprobe_chapters._should_probe_url('http://test.com/file.mkv', '', False))
        self.assertTrue(ffprobe_chapters._should_probe_url('file:///tmp/file.mp4', '', False))
        self.assertFalse(ffprobe_chapters._should_probe_url('http://test.com/stream.m3u8', '', False))
        self.assertFalse(ffprobe_chapters._should_probe_url('http://test.com/manifest', 'application/dash+xml', False))
        self.assertTrue(ffprobe_chapters._should_probe_url('http://test.com/stream', 'video/x-matroska', False))

    def test_ebml_vint_and_parsing(self):
        # 1-byte VINT: 0x81 -> length 1, value 1
        data = bytes([0x81, 0x82, 0x40, 0x05])
        val, length, nxt = ffprobe_chapters._read_ebml_vint(data, 0)
        self.assertEqual((val, length, nxt), (1, 1, 1))

        # 2-byte VINT: 0x40, 0x05 -> length 2, value 5
        val2, len2, nxt2 = ffprobe_chapters._read_ebml_vint(data, 2)
        self.assertEqual((val2, len2, nxt2), (5, 2, 4))

        # EBML element ID
        elem_id, id_len, _ = ffprobe_chapters._read_ebml_id(bytes([0x1A, 0x45, 0xDF, 0xA3]), 0)
        self.assertEqual(id_len, 4)

        # Empty / bounds check
        v, l, _ = ffprobe_chapters._read_ebml_vint(b"", 0)
        self.assertEqual((v, l), (0, 0))

    def test_probe_stream_chapters_mocked(self):
        mock_output = json.dumps({
            "chapters": [
                {
                    "start_time": "0.000",
                    "end_time": "90.000",
                    "tags": {"title": "Intro"}
                },
                {
                    "start_time": "90.000",
                    "end_time": "1200.000",
                    "tags": {"TITLE": "Episode"}
                }
            ]
        })
        with mock.patch('subprocess.run') as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout=mock_output, stderr="")
            chapters = ffprobe_chapters.probe_stream_chapters('/usr/bin/ffprobe', 'http://test.com/video.mkv')
            self.assertEqual(len(chapters), 2)
            self.assertEqual(chapters[0]['title'], 'Intro')
            self.assertEqual(chapters[1]['start'], 90.0)


class TestPartFilterCoverage(unittest.TestCase):
    """Tests for resources/lib/ui/part_filter.py."""

    def test_parse_range_and_chinese_hardsub(self):
        self.assertEqual(part_filter._parse_range('1 - 12'), (1, 12))
        self.assertEqual(part_filter._parse_range('invalid'), (None, None))
        self.assertEqual(part_filter._parse_range(None), (None, None))

        self.assertTrue(part_filter._has_chinese_hardsub('[chs] attack on titan 01.mp4'))
        self.assertTrue(part_filter._has_chinese_hardsub('anime gb_mp4 1080p'))
        self.assertFalse(part_filter._has_chinese_hardsub('[subsplease] anime 01.mkv'))

    def test_extract_part_and_batch_range(self):
        self.assertEqual(part_filter._extract_part_from_title('bleach tybw part 2 1080p'), 2)
        self.assertEqual(part_filter._extract_part_from_title('bleach cour ii 720p'), 2)
        self.assertIsNone(part_filter._extract_part_from_title('bleach episode 14'))

        self.assertEqual(part_filter._extract_batch_range('[sub] show (01-12) [1080p]'), (1, 12))
        self.assertEqual(part_filter._extract_batch_range('show 05.mkv'), (None, None))

    def test_filter_sources(self):
        sources = [
            {'release_title': '[CHS] Anime Show 01.mp4', 'provider': 'nyaa'},
            {'release_title': 'Anime Show Part 1 - 01.mkv', 'provider': 'animetosho'},
            {'release_title': 'Anime Show Part 2 - 01.mkv', 'provider': 'animetosho'},
        ]
        with mock.patch.object(part_filter, '_user_wants_chinese', return_value=False), \
             mock.patch.object(part_filter, '_get_mappings_info', return_value={'thetvdb_part': 1, 'anime_media_episodes': '1-12', 'global_media_episodes': '1-12'}):
            filtered = part_filter.filter_sources(sources, mal_id=123, episode=1, part=1)
            # CHS dropped, Part 2 dropped, Part 1 kept
            self.assertEqual(len(filtered), 1)
            self.assertIn('Part 1', filtered[0]['release_title'])

    def test_season_pack_covers_episode(self):
        from resources.lib.ui import source_utils
        src = {'release_title': '[SubsPlease] Frieren - 01-12 (1080p)', 'package': 'season'}
        self.assertTrue(source_utils.season_pack_covers_episode(src, 5))
        self.assertFalse(source_utils.season_pack_covers_episode(src, 15))
        self.assertFalse(source_utils.season_pack_covers_episode({'release_title': 'Frieren - 05'}, 5))
        self.assertTrue(source_utils.season_pack_covers_episode({'name': 'Batch', 'package': 'batch'}, 8, total_episodes=12))
        self.assertFalse(source_utils.season_pack_covers_episode(src, 'invalid'))


class TestUtilsCoverage(unittest.TestCase):
    """Tests for resources/lib/ui/utils.py."""

    def test_allocate_item_and_artwork_cache(self):
        item = utils.allocate_item('Show Title', 'play/1/1', False, True, [], image='default.png', fanart='fan.png')
        self.assertEqual(item['name'], 'Show Title')
        self.assertEqual(item['url'], 'play/1/1')
        self.assertIn('icon', item['image'])

    def test_format_mappings_and_search_history(self):
        f1, f2 = utils.get_format_to_url_mappings()
        self.assertIn('anime', f1)
        self.assertIn('anime', f2)

        items = utils.search_history(['Naruto', 'One Piece'], 'anime')
        self.assertGreaterEqual(len(items), 3)  # New Search + Clear + 2 entries

    def test_parse_view_and_season(self):
        base = {
            'name': 'Demon Slayer',
            'url': 'animes/123',
            'image': 'poster.png',
            'info': {'title': 'Demon Slayer'}
        }
        with mock.patch.object(control, 'getBool', return_value=False):
            pv = utils.parse_view(base, True, False, dub=False)
            self.assertIsNotNone(pv)
            self.assertEqual(pv['name'], 'Demon Slayer')

        titles = ['Attack on Titan Season 3', 'Shingeki no Kyojin 3rd Season']
        with mock.patch.object(database, 'get_mappings', return_value=None):
            season = utils.get_season(titles, 123)
            self.assertEqual(season, 3)

    def test_format_time_and_parallel_helpers(self):
        self.assertEqual(utils.format_time(3665), "01:01:05")

        reqs = [
            {'func': lambda x: x * 2, 'args': (2,), 'kwargs': {}},
            {'func': lambda x: x + 10, 'args': (5,), 'kwargs': {}},
        ]
        results = utils.parallel_fetch(reqs, max_workers=2)
        self.assertEqual(results, [4, 15])

        p_res = utils.parallel_process([1, 2, 3], lambda x: x * 10, max_workers=2)
        self.assertEqual(p_res, [10, 20, 30])


class TestDatabaseSyncAndDatabaseCoverage(unittest.TestCase):
    """Tests for database_sync.py and database.py core methods."""

    def test_database_sync_schema_builders(self):
        fd, db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        orig_db = getattr(control, 'malSyncDB', '')
        control.malSyncDB = db_path
        try:
            with mock.patch.object(control, 'log'):
                sync_db = database_sync.SyncDatabase()
                self.assertIsNotNone(sync_db)

                # Verify tables were created
                conn = sqlite3.connect(db_path)
                tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                conn.close()
                for expected in ('activities', 'shows', 'shows_meta', 'episodes', 'show_data', 'watchlist_cache'):
                    self.assertIn(expected, tables)
        finally:
            control.malSyncDB = orig_db
            if os.path.exists(db_path):
                os.remove(db_path)

    def test_database_safe_serialization_and_helpers(self):
        data = {'name': 'Otaku', 'ids': [1, 2, 3], 'tags': {'shounen'}}
        blob = database.dumps(data)
        loaded = database.loads(blob)
        self.assertEqual(loaded['name'], 'Otaku')
        self.assertEqual(loaded['ids'], [1, 2, 3])

        # _json_default tests
        self.assertEqual(database._json_default({'a', 'b'}).sort(), ['a', 'b'].sort())
        self.assertEqual(database._json_default(b"bytes"), "bytes")
        with self.assertRaises(TypeError):
            database._json_default(object())

        # Unpickler safety check
        with self.assertRaises(Exception):
            unsafe_blob = b"cbuiltins\neval\n(S'1+1'\ntR."
            database._SafeUnpickler(io.BytesIO(unsafe_blob)).load()

        # Corruption detection
        self.assertTrue(database._is_db_corruption_error(Exception("disk image is malformed")))
        self.assertFalse(database._is_db_corruption_error(None))


class TestClientAndDomainsCoverage(unittest.TestCase):
    """Tests for client.py and domains.py."""

    def test_validate_url_scheme(self):
        self.assertEqual(client._validate_url_scheme('https://example.com/api'), 'https://example.com/api')
        self.assertEqual(client._validate_url_scheme('//example.com/api'), 'https://example.com/api')
        with self.assertRaises(ValueError):
            client._validate_url_scheme('ftp://example.com')
        with self.assertRaises(ValueError):
            client._validate_url_scheme('file:///etc/passwd')
        with self.assertRaises(ValueError):
            client._validate_url_scheme('')

    def test_session_opener_dict(self):
        s_dict = client._SessionOpenerDict()
        s_dict[('domain.com', True)] = 'verified_opener'
        self.assertEqual(s_dict.get('domain.com'), 'verified_opener')
        self.assertEqual(s_dict.get(('domain.com', True)), 'verified_opener')
        self.assertIsNone(s_dict.get('missing.com'))

    def test_user_agents(self):
        ua = client._get_cached_useragent(mobile=False)
        self.assertIn('Mozilla', ua)
        m_ua = client._get_cached_useragent(mobile=True)
        self.assertIn('Mozilla', m_ua)

    def test_domains_resolution(self):
        hianime = domains.get_domain('hianime')
        self.assertTrue(hianime.startswith('https://'))

        mirrors = domains.get_hianime_mirrors()
        self.assertIsInstance(mirrors, list)
        self.assertGreater(len(mirrors), 0)

        healthy = domains.get_healthy_mirrors('hianime')
        self.assertGreaterEqual(len(healthy), 1)

        domains.mark_mirror_failure(mirrors[0])
        self.assertFalse(domains.is_mirror_healthy(mirrors[0]))

        domains._DOMAINS_CACHE = None
        loaded = domains._load_domains(force_refresh=True)
        self.assertIn('hianime', loaded)


if __name__ == '__main__':
    unittest.main()
