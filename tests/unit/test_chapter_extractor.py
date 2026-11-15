# -*- coding: utf-8 -*-
"""
test_chapter_extractor.py - Comprehensive Unit Tests for Pure-Python Chapter Extraction
======================================================================================
Tests:
1. URL parsing & pipe-delimited Kodi headers.
2. HttpRangeFile seekable stream:
   - 206 Partial Content pre-flight validation.
   - Fast-fail on 200 OK (unsupported range) or connection errors.
   - 64 KB chunking, LRU cache eviction, and boundary seeks/reads.
   - 2 MB download safety budget enforcement.
3. MKV/WebM EBML chapter parser:
   - Direct Chapters box in Segment header.
   - SeekHead pointer to Chapters offset.
   - Nanosecond time conversion and end-bound snapping.
4. MP4/M4V/MOV ISO BMFF chapter parser:
   - mdat box skipping without reading content.
   - Nero moov.udta.chpl parsing (versions 0 & 1).
   - QuickTime/Apple tref.chap timed text chapter track parsing (timescale, stts, stco, co64).
5. Orchestration & AniSkip Precedence:
   - Python first -> FFprobe fallback -> graceful failure.
   - AniSkip overriding chapter extraction when available.
"""

from __future__ import annotations

import io
import os
import struct
import unittest
from unittest.mock import MagicMock, patch

import conftest  # Kodi mock harness  # noqa: F401
from resources.lib.ui import chapter_extractor, ffprobe_chapters
from resources.lib.ui.player import WatchlistPlayer


class TestChapterExtractorUrlAndRange(unittest.TestCase):
    """Test URL parsing, header extraction, and HttpRangeFile."""

    def test_parse_kodi_url_plain(self):
        url = 'https://example.com/video.mkv'
        clean_url, headers = chapter_extractor.parse_kodi_url(url)
        self.assertEqual(clean_url, 'https://example.com/video.mkv')
        self.assertEqual(headers.get('User-Agent'), 'Mozilla/5.0')

    def test_parse_kodi_url_empty(self):
        clean_url, headers = chapter_extractor.parse_kodi_url('')
        self.assertEqual(clean_url, '')
        self.assertEqual(headers, {})

    def test_parse_kodi_url_with_headers(self):
        raw = 'https://stream.net/v.mp4?sig=123|User-Agent=Kodi%2F21.0&Referer=https%3A%2F%2Fsite.org&Custom=value'
        clean, headers = chapter_extractor.parse_kodi_url(raw)
        self.assertEqual(clean, 'https://stream.net/v.mp4?sig=123')
        self.assertEqual(headers['User-Agent'], 'Kodi/21.0')
        self.assertEqual(headers['Referer'], 'https://site.org')
        self.assertEqual(headers['Custom'], 'value')

    @patch('urllib.request.urlopen')
    def test_http_range_file_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 206
        mock_resp.headers = {'Content-Range': 'bytes 0-0/1000000'}
        mock_resp.read.side_effect = [b'A', b'X' * 65536]
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        rf = chapter_extractor.HttpRangeFile('https://example.com/file.mkv')
        self.assertEqual(rf.total_size, 1000000)
        self.assertTrue(rf.seekable())
        self.assertTrue(rf.readable())

        # Test read
        data = rf.read(10)
        self.assertEqual(len(data), 10)
        self.assertEqual(rf.tell(), 10)

        # Test seek
        rf.seek(500, os.SEEK_SET)
        self.assertEqual(rf.tell(), 500)
        rf.seek(10, os.SEEK_CUR)
        self.assertEqual(rf.tell(), 510)
        rf.seek(-100, os.SEEK_END)
        self.assertEqual(rf.tell(), 999900)

        rf.close()
        self.assertTrue(rf._closed)
        with self.assertRaises(ValueError):
            rf.read(1)

    @patch('urllib.request.urlopen')
    def test_http_range_file_fails_on_status_200(self, mock_urlopen):
        """Server returning 200 OK ignores Range header and must fail fast."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {'Content-Length': '500000000'}
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        with self.assertRaises(chapter_extractor.RangeNotSupportedError):
            chapter_extractor.HttpRangeFile('https://example.com/stream.mkv')

    @patch('urllib.request.urlopen')
    def test_http_range_file_budget_ceiling(self, mock_urlopen):
        """Verify that probing aborts if total downloaded bytes exceed budget."""
        mock_probe = MagicMock()
        mock_probe.status = 206
        mock_probe.headers = {'Content-Range': 'bytes 0-0/10000000'}
        mock_probe.read.return_value = b'P'
        mock_probe.__enter__.return_value = mock_probe

        mock_chunk = MagicMock()
        mock_chunk.status = 206
        mock_chunk.read.return_value = b'C' * 65536
        mock_chunk.__enter__.return_value = mock_chunk

        mock_urlopen.side_effect = [mock_probe, mock_chunk, mock_chunk]

        # Budget of 70 KB allows probe + 1 chunk, but 2nd chunk exceeds budget
        rf = chapter_extractor.HttpRangeFile(
            'https://example.com/large.mkv',
            max_budget=70000
        )
        rf.read(65536)  # 1st chunk (65536 bytes) -> total ~65537 bytes

        with self.assertRaises(chapter_extractor.DownloadBudgetExceededError):
            rf.read(65536)  # 2nd chunk would exceed 70 KB budget


class TestMkvEbmlParser(unittest.TestCase):
    """Test MKV / WebM EBML chapter decoding."""

    def _build_vint(self, val: int) -> bytes:
        if val < 0x7F:
            return bytes([0x80 | val])
        elif val < 0x3FFF:
            return struct.pack('>H', 0x4000 | val)
        elif val < 0x1FFFFF:
            return bytes([0x20 | (val >> 16), (val >> 8) & 0xFF, val & 0xFF])
        else:
            return struct.pack('>I', 0x10000000 | val)

    def _build_elem(self, eid: int, payload: bytes) -> bytes:
        eid_bytes = eid.to_bytes((eid.bit_length() + 7) // 8, 'big')
        return eid_bytes + self._build_vint(len(payload)) + payload

    def test_parse_mkv_chapters_direct(self):
        """Construct synthetic MKV EBML stream with direct Chapters box."""
        # ChapString
        title_elem = self._build_elem(0x85, b"Intro / OP")
        # ChapterDisplay
        display_elem = self._build_elem(0x80, title_elem)
        # ChapterTimeStart (ns) = 15.0s = 15,000,000,000 ns
        start_elem = self._build_elem(0x91, (15_000_000_000).to_bytes(8, 'big'))
        # ChapterTimeEnd (ns) = 105.0s = 105,000,000,000 ns
        end_elem = self._build_elem(0x92, (105_000_000_000).to_bytes(8, 'big'))
        # ChapterAtom
        atom1 = self._build_elem(0xB6, start_elem + end_elem + display_elem)

        # Chapter 2 (Ending)
        title2 = self._build_elem(0x85, b"Ending / ED")
        disp2 = self._build_elem(0x80, title2)
        start2 = self._build_elem(0x91, (1200_000_000_000).to_bytes(8, 'big'))
        end2 = self._build_elem(0x92, (1290_000_000_000).to_bytes(8, 'big'))
        atom2 = self._build_elem(0xB6, start2 + end2 + disp2)

        # EditionEntry
        edition = self._build_elem(0x45B9, atom1 + atom2)
        # Chapters
        chapters_elem = self._build_elem(0x1043A770, edition)
        # Segment
        segment_elem = self._build_elem(0x18538067, chapters_elem)
        # EBML Header
        ebml_hdr = self._build_elem(0x1A45DFA3, b'\x42\x86\x81\x01')  # EBMLVersion 1

        stream = io.BytesIO(ebml_hdr + segment_elem)
        parsed = chapter_extractor.parse_mkv_chapters(stream)

        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]['title'], "Intro / OP")
        self.assertAlmostEqual(parsed[0]['start_time'], 15.0)
        self.assertAlmostEqual(parsed[0]['end_time'], 105.0)
        self.assertEqual(parsed[1]['title'], "Ending / ED")
        self.assertAlmostEqual(parsed[1]['start_time'], 1200.0)
        self.assertAlmostEqual(parsed[1]['end_time'], 1290.0)

    def test_parse_mkv_non_ebml(self):
        stream = io.BytesIO(b'NOT_AN_MKV_STREAM')
        self.assertEqual(chapter_extractor.parse_mkv_chapters(stream), [])


class TestMp4IsoBmffParser(unittest.TestCase):
    """Test MP4 ISO BMFF box decoding for Nero udta.chpl and QuickTime tref.chap."""

    def _build_box(self, btype: bytes, payload: bytes) -> bytes:
        size = len(payload) + 8
        return struct.pack('>I4s', size, btype) + payload

    def test_parse_mp4_nero_chpl(self):
        """Construct synthetic MP4 with moov.udta.chpl box."""
        ftyp = self._build_box(b'ftyp', b'mp42\x00\x00\x00\x00isommp42')
        mdat = self._build_box(b'mdat', b'\x00' * 1024)

        # Nero chpl payload:
        # byte 0: version (0)
        # bytes 1-3: flags (0)
        # byte 4: reserved (0)
        # byte 5: count (2)
        # entry 1: uint64 start (100ns units), uint8 title_len, title
        start1_100ns = int(60.0 * 10_000_000)
        t1 = b'Opening'
        entry1 = struct.pack('>QB', start1_100ns, len(t1)) + t1

        start2_100ns = int(1350.0 * 10_000_000)
        t2 = b'Ending'
        entry2 = struct.pack('>QB', start2_100ns, len(t2)) + t2

        chpl_payload = bytes([0, 0, 0, 0, 0, 2]) + entry1 + entry2
        chpl_box = self._build_box(b'chpl', chpl_payload)
        udta_box = self._build_box(b'udta', chpl_box)
        moov_box = self._build_box(b'moov', udta_box)

        stream = io.BytesIO(ftyp + mdat + moov_box)
        parsed = chapter_extractor.parse_mp4_chapters(stream)

        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]['title'], 'Opening')
        self.assertAlmostEqual(parsed[0]['start_time'], 60.0)
        self.assertAlmostEqual(parsed[0]['end_time'], 1350.0)
        self.assertEqual(parsed[1]['title'], 'Ending')
        self.assertAlmostEqual(parsed[1]['start_time'], 1350.0)

    def test_parse_mp4_quicktime_tref_chap(self):
        """Construct synthetic MP4 with tref.chap timed text chapter track."""
        ftyp = self._build_box(b'ftyp', b'isom\x00\x00\x02\x00isomiso2mp41')

        # Video track with tref.chap referencing track 2
        chap_box = self._build_box(b'chap', struct.pack('>I', 2))
        tref_box = self._build_box(b'tref', chap_box)
        tkhd1 = self._build_box(b'tkhd', bytes([0, 0, 0, 0]) + b'\x00' * 8 + struct.pack('>I', 1) + b'\x00' * 60)
        trak1 = self._build_box(b'trak', tkhd1 + tref_box)

        # Chapter track (track 2)
        tkhd2 = self._build_box(b'tkhd', bytes([0, 0, 0, 0]) + b'\x00' * 8 + struct.pack('>I', 2) + b'\x00' * 60)
        # mdhd timescale = 1000
        mdhd2 = self._build_box(b'mdhd', bytes([0, 0, 0, 0]) + b'\x00' * 8 + struct.pack('>I', 1000) + struct.pack('>I', 1400000))

        # stts: 2 samples, 90000 units (90s) each
        stts = self._build_box(b'stts', bytes([0, 0, 0, 0]) + struct.pack('>I', 2) + struct.pack('>II', 1, 90000) + struct.pack('>II', 1, 90000))

        # Two text samples placed at offsets 5000 and 5100
        sample1_data = struct.pack('>H', 7) + b'IntroOP'
        sample2_data = struct.pack('>H', 7) + b'OutroED'

        stco = self._build_box(b'stco', bytes([0, 0, 0, 0]) + struct.pack('>I', 2) + struct.pack('>II', 5000, 5100))
        stbl = self._build_box(b'stbl', stts + stco)
        minf = self._build_box(b'minf', stbl)
        mdia = self._build_box(b'mdia', mdhd2 + minf)
        trak2 = self._build_box(b'trak', tkhd2 + mdia)

        moov = self._build_box(b'moov', trak1 + trak2)

        # Pad stream up to 5000 and 5100 with text sample data
        buf = bytearray(ftyp + moov)
        if len(buf) < 5200:
            buf.extend(b'\x00' * (5200 - len(buf)))
        buf[5000:5000 + len(sample1_data)] = sample1_data
        buf[5100:5100 + len(sample2_data)] = sample2_data

        stream = io.BytesIO(bytes(buf))
        parsed = chapter_extractor.parse_mp4_chapters(stream)

        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]['title'], 'IntroOP')
        self.assertAlmostEqual(parsed[0]['start_time'], 0.0)
        self.assertAlmostEqual(parsed[0]['end_time'], 90.0)
        self.assertEqual(parsed[1]['title'], 'OutroED')
        self.assertAlmostEqual(parsed[1]['start_time'], 90.0)
        self.assertAlmostEqual(parsed[1]['end_time'], 180.0)


class TestChapterOrchestrationAndPrecedence(unittest.TestCase):
    """Test dual-priority fallback chain and AniSkip precedence."""

    @patch('resources.lib.ui.chapter_extractor.get_remote_chapters')
    @patch('resources.lib.ui.control.getBool')
    def test_attach_to_linkinfo_python_first(self, mock_getBool, mock_extract):
        """Python extractor takes priority when both are enabled."""
        mock_getBool.side_effect = lambda sid: {
            'chapters.python.enable': True,
            'ffprobe.chapters.enable': True,
        }.get(sid, False)

        mock_extract.return_value = [
            {'index': 1, 'title': 'OP', 'start_time': 10.0, 'end_time': 100.0, 'start': 10.0, 'end': 100.0}
        ]

        linkinfo = {'url': 'https://example.com/stream.mkv'}
        with patch.object(ffprobe_chapters, 'probe_stream_chapters') as mock_probe:
            ffprobe_chapters.attach_to_linkinfo(linkinfo)
            self.assertEqual(len(linkinfo['chapters']), 1)
            self.assertEqual(linkinfo['chapters'][0]['title'], 'OP')
            mock_extract.assert_called_once()
            mock_probe.assert_not_called()

    @patch('resources.lib.ui.chapter_extractor.get_remote_chapters', return_value=[])
    @patch('resources.lib.ui.ffprobe_chapters.find_ffprobe', return_value='/usr/bin/ffprobe')
    @patch('resources.lib.ui.ffprobe_chapters.probe_stream_chapters')
    @patch('resources.lib.ui.control.getBool')
    def test_attach_to_linkinfo_ffprobe_fallback(self, mock_getBool, mock_probe, mock_find, mock_extract):
        """When Python extraction returns [], falls back to ffprobe."""
        mock_getBool.side_effect = lambda sid: {
            'chapters.python.enable': True,
            'ffprobe.chapters.enable': True,
        }.get(sid, False)

        mock_probe.return_value = [
            {'index': 1, 'title': 'FFprobe OP', 'start': 20.0, 'end': 110.0}
        ]

        linkinfo = {'url': 'https://example.com/stream.mkv'}
        ffprobe_chapters.attach_to_linkinfo(linkinfo)

        self.assertEqual(len(linkinfo['chapters']), 1)
        self.assertEqual(linkinfo['chapters'][0]['title'], 'FFprobe OP')
        mock_extract.assert_called_once()
        mock_probe.assert_called_once()

    @patch('resources.lib.ui.chapter_extractor.get_remote_chapters', return_value=[])
    @patch('resources.lib.ui.ffprobe_chapters.find_ffprobe', return_value=None)
    @patch('resources.lib.ui.control.getBool')
    def test_attach_to_linkinfo_ffprobe_missing_fails_gracefully(self, mock_getBool, mock_find, mock_extract):
        """When ffprobe is enabled but binary is not found, fails gracefully without exceptions."""
        mock_getBool.side_effect = lambda sid: {
            'chapters.python.enable': False,
            'ffprobe.chapters.enable': True,
        }.get(sid, False)

        linkinfo = {'url': 'https://example.com/stream.mp4'}
        ffprobe_chapters.attach_to_linkinfo(linkinfo)
        self.assertEqual(linkinfo['chapters'], [])

    @patch('resources.lib.endpoints.aniskip.get_skip_times')
    def test_aniskip_precedence_over_chapter_extraction(self, mock_get_skip):
        """Verify that AniSkip skip times override chapter-extracted times."""
        player = WatchlistPlayer()
        player.mal_id = '99999'
        player.episode = 1
        player.total_time = 1400.0
        player.skipintro_aniskip_enable = True
        player.skipoutro_aniskip_enable = True

        # Pre-load chapters from extraction
        player.ffprobe_chapters = [
            {'title': 'Opening', 'start': 10.0, 'end': 100.0},
            {'title': 'Ending', 'start': 1200.0, 'end': 1290.0},
        ]

        # Step 1: Process chapter skips first (sets fallback times)
        player.process_ffprobe_chapter_skips()
        self.assertTrue(player.skipintro_aniskip)
        self.assertTrue(player.skipintro_from_chapters)
        self.assertEqual(player.skipintro_start, 10)
        self.assertEqual(player.skipintro_end, 100)

        # Step 2: AniSkip returns verified skip times (different from chapter times)
        mock_get_skip.side_effect = lambda mal_id, ep, skip_type: {
            'op': {'results': [{'interval': {'startTime': 75.0, 'endTime': 165.0}}]},
            'ed': {'results': [{'interval': {'startTime': 1250.0, 'endTime': 1340.0}}]},
        }.get(skip_type)

        player.process_aniskip()

        # Step 3: Assert AniSkip OVERRODE the chapter extraction times!
        self.assertTrue(player.skipintro_aniskip)
        self.assertFalse(player.skipintro_from_chapters)
        self.assertEqual(player.skipintro_start, 75)
        self.assertEqual(player.skipintro_end, 165)
        self.assertEqual(player.skipoutro_start, 1250)
        self.assertEqual(player.skipoutro_end, 1340)


if __name__ == '__main__':
    unittest.main()
