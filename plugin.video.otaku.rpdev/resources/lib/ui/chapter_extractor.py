"""
Pure-Python container chapter and skip time extraction for Otaku.

Zero external binaries: parses Matroska/WebM EBML and MP4/MOV ISO BMFF container
chapters over seekable HTTP Range requests or local files without requiring ffprobe.
"""

from __future__ import annotations

import collections
import io
import os
import struct
import sys
import urllib.parse
import urllib.request
from typing import Any, BinaryIO

from resources.lib.ui import client, control


class RangeNotSupportedError(Exception):
    """Raised when the remote HTTP server does not support partial range requests."""


class DownloadBudgetExceededError(Exception):
    """Raised when chapter probing downloads more bytes than the safety budget."""


def parse_kodi_url(kodi_url: str) -> tuple[str, dict[str, str]]:
    """
    Split Kodi-style pipe-delimited headers from a stream URL.

    Example:
        https://example.com/v.mkv|User-Agent=Kodi&Referer=https%3A%2F%2Fsite.com
        -> ('https://example.com/v.mkv', {'User-Agent': 'Kodi', 'Referer': 'https://site.com'})
    """
    if not kodi_url:
        return '', {}
    if '|' not in kodi_url:
        return kodi_url, {'User-Agent': 'Mozilla/5.0'}

    url, raw_headers = kodi_url.split('|', 1)
    headers: dict[str, str] = {}
    for pair in raw_headers.split('&'):
        if '=' not in pair:
            continue
        k, v = pair.split('=', 1)
        k_clean = k.strip()
        if k_clean:
            headers[k_clean] = urllib.parse.unquote_plus(v.strip())

    if 'User-Agent' not in headers:
        headers['User-Agent'] = 'Mozilla/5.0'

    return url.strip(), headers


class HttpRangeFile(io.RawIOBase):
    """
    Seekable file-like stream backed by HTTP Range: bytes=start-end requests.

    Features:
    - 64 KB chunking with in-memory LRU caching.
    - Strict download budget guard (default 2 MB) to prevent runaway memory/bandwidth usage.
    - Fast failure if remote host does not support 206 Partial Content.
    """

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 8.0,
        chunk_size: int = 65536,
        max_budget: int = 2 * 1024 * 1024,
    ):
        super().__init__()
        self.url = url
        self.headers = dict(headers or {})
        self.timeout = float(timeout)
        self.chunk_size = int(chunk_size)
        self.max_budget = int(max_budget)

        self.bytes_downloaded: int = 0
        self.pos: int = 0
        self.total_size: int | None = None
        self.chunk_cache: dict[int, bytes] = {}
        self.cache_keys: collections.deque = collections.deque(maxlen=32)
        self._closed: bool = False

        self._init_range_probe()

    def _get_ssl_context(self) -> Any:
        try:
            return client._get_ssl_context()
        except Exception:
            import ssl
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx

    def _init_range_probe(self) -> None:
        """Issue initial Range: bytes=0-0 request to verify 206 Partial Content and total size."""
        probe_headers = dict(self.headers)
        probe_headers['Range'] = 'bytes=0-0'

        req = urllib.request.Request(self.url, headers=probe_headers)
        ctx = self._get_ssl_context()

        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout, context=ctx)
        except urllib.error.HTTPError as e:
            raise RangeNotSupportedError(f"HTTP error during range probe: {e.code}") from e
        except Exception as e:
            raise RangeNotSupportedError(f"Connection failed during range probe: {e}") from e

        with resp:
            status = getattr(resp, 'status', getattr(resp, 'code', 0))
            if status != 206:
                raise RangeNotSupportedError(f"Server returned status {status}, Range requests not supported")

            first_byte = resp.read()
            self.bytes_downloaded += len(first_byte)

            # Extract total size from Content-Range: bytes 0-0/12345678
            cr = resp.headers.get('Content-Range', '')
            total = None
            if '/' in cr:
                total_part = cr.split('/')[-1].strip()
                if total_part.isdigit():
                    total = int(total_part)

            if total is None:
                cl = resp.headers.get('Content-Length', '')
                if cl.isdigit() and int(cl) > 1:
                    total = int(cl)

            if total is None or total <= 0:
                raise RangeNotSupportedError("Server did not report total Content-Range file size")

            self.total_size = total

            # Cache the first chunk if single byte returned
            if first_byte and self.chunk_size > 1:
                # We can store first byte or leave for full chunk 0 fetch
                pass

    def _fetch_chunk(self, chunk_index: int) -> bytes:
        if chunk_index in self.chunk_cache:
            return self.chunk_cache[chunk_index]

        start_byte = chunk_index * self.chunk_size
        if self.total_size is not None and start_byte >= self.total_size:
            return b''

        end_byte = start_byte + self.chunk_size - 1
        if self.total_size is not None and end_byte >= self.total_size:
            end_byte = self.total_size - 1

        if start_byte > end_byte:
            return b''

        needed_bytes = end_byte - start_byte + 1
        if self.bytes_downloaded + needed_bytes > self.max_budget:
            raise DownloadBudgetExceededError(
                f"Chapter probe exceeded download budget of {self.max_budget} bytes"
            )

        chunk_headers = dict(self.headers)
        chunk_headers['Range'] = f'bytes={start_byte}-{end_byte}'
        req = urllib.request.Request(self.url, headers=chunk_headers)
        ctx = self._get_ssl_context()

        with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as resp:
            data = resp.read()
            self.bytes_downloaded += len(data)
            self.chunk_cache[chunk_index] = data
            self.cache_keys.append(chunk_index)

            # Evict LRU chunks when cache exceeds 32 items
            if len(self.chunk_cache) > 32:
                valid_keys = set(self.cache_keys)
                to_remove = [k for k in self.chunk_cache if k not in valid_keys]
                for k in to_remove:
                    del self.chunk_cache[k]

            return data

    def readable(self) -> bool:
        return not self._closed

    def seekable(self) -> bool:
        return not self._closed

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        if self._closed:
            raise ValueError("I/O operation on closed file")

        if whence == os.SEEK_SET:
            new_pos = offset
        elif whence == os.SEEK_CUR:
            new_pos = self.pos + offset
        elif whence == os.SEEK_END:
            if self.total_size is None:
                raise OSError("Cannot seek from SEEK_END without known file size")
            new_pos = self.total_size + offset
        else:
            raise ValueError(f"Invalid whence: {whence}")

        if new_pos < 0:
            raise OSError("Negative seek position")

        self.pos = new_pos
        return self.pos

    def read(self, size: int = -1) -> bytes:
        if self._closed:
            raise ValueError("I/O operation on closed file")

        if self.total_size is not None and self.pos >= self.total_size:
            return b''

        if size < 0:
            if self.total_size is not None:
                size = self.total_size - self.pos
            else:
                size = self.max_budget

        if size == 0:
            return b''

        result = bytearray()
        remaining = size

        while remaining > 0:
            if self.total_size is not None and self.pos >= self.total_size:
                break

            chunk_idx = self.pos // self.chunk_size
            offset_in_chunk = self.pos % self.chunk_size
            chunk = self._fetch_chunk(chunk_idx)
            if not chunk or offset_in_chunk >= len(chunk):
                break

            avail = len(chunk) - offset_in_chunk
            to_read = min(remaining, avail)
            result.extend(chunk[offset_in_chunk:offset_in_chunk + to_read])
            self.pos += to_read
            remaining -= to_read

        return bytes(result)

    def close(self) -> None:
        self._closed = True
        self.chunk_cache.clear()
        super().close()


# ── EBML MKV / WebM Parser ───────────────────────────────────────────────────


def _read_ebml_vint_stream(stream: BinaryIO) -> tuple[int, int]:
    """Read an EBML variable-length integer (VINT) from a seekable stream. Returns (value, length)."""
    b1 = stream.read(1)
    if not b1:
        return 0, 0
    first = b1[0]
    if first == 0:
        return 0, 0

    mask = 0x80
    length = 1
    while not (first & mask):
        mask >>= 1
        length += 1
        if length > 8:
            return 0, 0

    rest = stream.read(length - 1)
    if len(rest) != length - 1:
        return 0, 0

    raw_val = int.from_bytes(b1 + rest, 'big')
    val = raw_val & ((1 << (7 * length)) - 1)
    return val, length


def _read_ebml_id_stream(stream: BinaryIO) -> tuple[int, int]:
    """Read an EBML Element ID from a seekable stream without masking length bits. Returns (id, length)."""
    b1 = stream.read(1)
    if not b1:
        return 0, 0
    first = b1[0]
    if first == 0:
        return 0, 0

    mask = 0x80
    length = 1
    while not (first & mask):
        mask >>= 1
        length += 1
        if length > 4:
            return 0, 0

    rest = stream.read(length - 1)
    if len(rest) != length - 1:
        return 0, 0

    val = int.from_bytes(b1 + rest, 'big')
    return val, length


def _read_ebml_vint(data: bytes, offset: int) -> tuple[int, int, int]:
    """Read an EBML VINT from a byte buffer. Returns (val, length, next_offset)."""
    if offset >= len(data):
        return 0, 0, offset
    first = data[offset]
    if first == 0:
        return 0, 0, offset
    mask = 0x80
    length = 1
    while not (first & mask):
        mask >>= 1
        length += 1
        if length > 8:
            return 0, 0, offset
    if offset + length > len(data):
        return 0, 0, offset
    raw_val = int.from_bytes(data[offset:offset + length], 'big')
    val = raw_val & ((1 << (7 * length)) - 1)
    return val, length, offset + length


def _read_ebml_id(data: bytes, offset: int) -> tuple[int, int, int]:
    """Read an EBML Element ID from a byte buffer. Returns (id, length, next_offset)."""
    if offset >= len(data):
        return 0, 0, offset
    first = data[offset]
    if first == 0:
        return 0, 0, offset
    mask = 0x80
    length = 1
    while not (first & mask):
        mask >>= 1
        length += 1
        if length > 4:
            return 0, 0, offset
    if offset + length > len(data):
        return 0, 0, offset
    val = int.from_bytes(data[offset:offset + length], 'big')
    return val, length, offset + length


def parse_mkv_chapters(stream: BinaryIO) -> list[dict]:
    """
    Parse Matroska/WebM EBML chapters from a seekable stream.

    Walks EBML header -> Segment -> SeekHead / Chapters element.
    If SeekHead points to Chapters, seeks directly to target offset.
    """
    stream.seek(0)
    magic = stream.read(4)
    if magic != b'\x1a\x45\xdf\xa3':
        return []

    # Read EBML Header element
    stream.seek(0)
    eid, elen = _read_ebml_id_stream(stream)
    if elen == 0 or eid != 0x1A45DFA3:
        return []
    esize, slen = _read_ebml_vint_stream(stream)
    if slen == 0:
        return []

    stream.seek(stream.tell() + esize)

    # Next element must be Segment (0x18538067)
    seg_id, seg_len = _read_ebml_id_stream(stream)
    if seg_len == 0 or seg_id != 0x18538067:
        return []
    _seg_size, seg_slen = _read_ebml_vint_stream(stream)
    if seg_slen == 0:
        return []

    seg_data_pos = stream.tell()
    chapters_bytes: bytes | None = None
    seek_target_offset: int | None = None

    # Scan top-level Segment elements
    while True:
        eid, elen = _read_ebml_id_stream(stream)
        if elen == 0:
            break
        esize, slen = _read_ebml_vint_stream(stream)
        if slen == 0:
            break

        data_pos = stream.tell()
        data_end = data_pos + esize

        if eid == 0x1043A770:  # Chapters
            read_size = min(esize, 2 * 1024 * 1024)
            chapters_bytes = stream.read(read_size)
            break
        elif eid == 0x114D9B74:  # SeekHead
            sh_size = min(esize, 65536)
            sh_buf = stream.read(sh_size)
            sh_pos = 0
            while sh_pos < len(sh_buf) - 4:
                seid, selen, sh_pos = _read_ebml_id(sh_buf, sh_pos)
                if selen == 0:
                    break
                sesize, sslen, sh_pos = _read_ebml_vint(sh_buf, sh_pos)
                if sslen == 0:
                    break
                send = sh_pos + sesize
                if seid == 0x4DBB:  # Seek
                    cur_seek_id = None
                    cur_seek_pos = None
                    sk_pos = sh_pos
                    while sk_pos < send:
                        keid, kelen, sk_pos = _read_ebml_id(sh_buf, sk_pos)
                        if kelen == 0:
                            break
                        kesize, kslen, sk_pos = _read_ebml_vint(sh_buf, sk_pos)
                        if kslen == 0:
                            break
                        kend = sk_pos + kesize
                        if keid == 0x53AB and kend <= len(sh_buf):  # SeekID
                            cur_seek_id = sh_buf[sk_pos:kend]
                        elif keid == 0x53AC and kend <= len(sh_buf):  # SeekPosition
                            cur_seek_pos = int.from_bytes(sh_buf[sk_pos:kend], 'big')
                        sk_pos = kend
                    if cur_seek_id == b'\x10\x43\xa7\x70' and cur_seek_pos is not None:
                        seek_target_offset = seg_data_pos + cur_seek_pos
                sh_pos = send
            stream.seek(data_end)
        elif eid == 0x1F43B675:  # First Cluster (stop scanning header)
            break
        else:
            stream.seek(data_end)

    if not chapters_bytes and seek_target_offset is not None:
        stream.seek(seek_target_offset)
        cid, _clen = _read_ebml_id_stream(stream)
        if cid == 0x1043A770:
            csize, cslen = _read_ebml_vint_stream(stream)
            if cslen > 0:
                chapters_bytes = stream.read(min(csize, 2 * 1024 * 1024))

    if not chapters_bytes:
        return []

    # Parse EditionEntry (0x45B9) -> ChapterAtom (0xB6)
    chapters = []
    cpos = 0
    atom_idx = 1
    while cpos < len(chapters_bytes) - 4:
        eid, elen, cpos = _read_ebml_id(chapters_bytes, cpos)
        if elen == 0:
            break
        esize, slen, cpos = _read_ebml_vint(chapters_bytes, cpos)
        if slen == 0:
            break
        eend = cpos + esize
        if eid == 0x45B9:  # EditionEntry
            ed_pos = cpos
            while ed_pos < eend:
                aeid, aelen, ed_pos = _read_ebml_id(chapters_bytes, ed_pos)
                if aelen == 0:
                    break
                aesize, aslen, ed_pos = _read_ebml_vint(chapters_bytes, ed_pos)
                if aslen == 0:
                    break
                aend = ed_pos + aesize
                if aeid == 0xB6:  # ChapterAtom
                    atom_pos = ed_pos
                    c_start = None
                    c_end = None
                    c_title = None
                    while atom_pos < aend:
                        feid, felen, atom_pos = _read_ebml_id(chapters_bytes, atom_pos)
                        if felen == 0:
                            break
                        fesize, fslen, atom_pos = _read_ebml_vint(chapters_bytes, atom_pos)
                        if fslen == 0:
                            break
                        fend = atom_pos + fesize
                        if feid == 0x91 and fend <= len(chapters_bytes):  # ChapterTimeStart (ns)
                            c_start = int.from_bytes(chapters_bytes[atom_pos:fend], 'big') / 1_000_000_000.0
                        elif feid == 0x92 and fend <= len(chapters_bytes):  # ChapterTimeEnd (ns)
                            c_end = int.from_bytes(chapters_bytes[atom_pos:fend], 'big') / 1_000_000_000.0
                        elif feid == 0x80:  # ChapterDisplay
                            cd_pos = atom_pos
                            while cd_pos < fend:
                                deid, delen, cd_pos = _read_ebml_id(chapters_bytes, cd_pos)
                                if delen == 0:
                                    break
                                desize, dslen, cd_pos = _read_ebml_vint(chapters_bytes, cd_pos)
                                if dslen == 0:
                                    break
                                dend = cd_pos + desize
                                if deid == 0x85 and dend <= len(chapters_bytes):  # ChapString
                                    try:
                                        c_title = chapters_bytes[cd_pos:dend].decode('utf-8', errors='ignore').strip()
                                    except Exception:
                                        c_title = None
                                cd_pos = dend
                        atom_pos = fend

                    if c_start is not None:
                        chapters.append({
                            'index': atom_idx,
                            'title': c_title or f'Chapter {atom_idx}',
                            'start_time': float(c_start),
                            'end_time': float(c_end) if c_end is not None else None,
                            'start': float(c_start),
                            'end': float(c_end) if c_end is not None else float(c_start),
                        })
                        atom_idx += 1
                ed_pos = aend
        cpos = eend

    chapters.sort(key=lambda x: x['start_time'])
    for i in range(len(chapters)):
        if (chapters[i]['end_time'] is None or chapters[i]['end'] <= chapters[i]['start']) and i + 1 < len(chapters):
            if chapters[i + 1]['start_time'] > chapters[i]['start_time']:
                next_start = chapters[i + 1]['start_time']
                chapters[i]['end_time'] = next_start
                chapters[i]['end'] = next_start

    return chapters


# ── MP4 / M4V / MOV ISO BMFF Parser ─────────────────────────────────────────


def _find_box(data: bytes, target_type: bytes) -> bytes | None:
    """Find the payload of the first child box matching target_type in data."""
    pos = 0
    while pos + 8 <= len(data):
        bsize = struct.unpack('>I', data[pos:pos + 4])[0]
        btype = data[pos + 4:pos + 8]
        bhdr = 8
        if bsize == 1:
            if pos + 16 > len(data):
                break
            bsize = struct.unpack('>Q', data[pos + 8:pos + 16])[0]
            bhdr = 16
        elif bsize == 0:
            bsize = len(data) - pos

        if bsize < bhdr or pos + bsize > len(data):
            break

        if btype == target_type:
            return data[pos + bhdr:pos + bsize]
        pos += bsize
    return None


def _find_all_boxes(data: bytes, target_type: bytes) -> list[bytes]:
    """Find all child box payloads matching target_type in data."""
    out = []
    pos = 0
    while pos + 8 <= len(data):
        bsize = struct.unpack('>I', data[pos:pos + 4])[0]
        btype = data[pos + 4:pos + 8]
        bhdr = 8
        if bsize == 1:
            if pos + 16 > len(data):
                break
            bsize = struct.unpack('>Q', data[pos + 8:pos + 16])[0]
            bhdr = 16
        elif bsize == 0:
            bsize = len(data) - pos

        if bsize < bhdr or pos + bsize > len(data):
            break

        if btype == target_type:
            out.append(data[pos + bhdr:pos + bsize])
        pos += bsize
    return out


def _parse_nero_chpl(chpl_data: bytes) -> list[dict]:
    """Parse Nero-style chapter box (moov.udta.chpl)."""
    if len(chpl_data) < 6:
        return []

    version = chpl_data[0]
    if version == 1:
        if len(chpl_data) < 9:
            return []
        count = struct.unpack('>I', chpl_data[5:9])[0]
        pos = 9
    else:
        count = chpl_data[5]
        pos = 6
        if count == 0 and len(chpl_data) >= 8:
            c32 = struct.unpack('>I', chpl_data[4:8])[0]
            if 0 < c32 < 1000:
                count = c32
                pos = 8

    chapters = []
    idx = 1
    while pos + 9 <= len(chpl_data) and len(chapters) < count:
        start_100ns = struct.unpack('>Q', chpl_data[pos:pos + 8])[0]
        pos += 8
        title_len = chpl_data[pos]
        pos += 1
        if pos + title_len > len(chpl_data):
            break
        title = chpl_data[pos:pos + title_len].decode('utf-8', errors='replace').strip()
        pos += title_len
        start_sec = start_100ns / 10_000_000.0

        chapters.append({
            'index': idx,
            'title': title or f'Chapter {idx}',
            'start_time': start_sec,
            'end_time': None,
            'start': start_sec,
            'end': start_sec,
        })
        idx += 1

    for i in range(len(chapters)):
        if i + 1 < len(chapters):
            next_start = chapters[i + 1]['start_time']
            chapters[i]['end_time'] = next_start
            chapters[i]['end'] = next_start

    return chapters


def _parse_quicktime_chapter_track(moov_data: bytes, stream: BinaryIO) -> list[dict]:
    """Parse QuickTime/Apple timed text chapter track referenced by tref.chap."""
    traks = _find_all_boxes(moov_data, b'trak')
    if not traks:
        return []

    # 1. Locate track referenced in tref.chap
    chap_track_id = None
    for trak in traks:
        tref = _find_box(trak, b'tref')
        if tref:
            chap_box = _find_box(tref, b'chap')
            if chap_box and len(chap_box) >= 4:
                chap_track_id = struct.unpack('>I', chap_box[:4])[0]
                break

    if chap_track_id is None:
        return []

    # 2. Find target track with matching track_id in tkhd
    target_trak = None
    for trak in traks:
        tkhd = _find_box(trak, b'tkhd')
        if tkhd and len(tkhd) >= 16:
            ver = tkhd[0]
            if ver == 1 and len(tkhd) < 24:
                continue
            tid = struct.unpack('>I', tkhd[20:24] if ver == 1 else tkhd[12:16])[0]
            if tid == chap_track_id:
                target_trak = trak
                break

    if target_trak is None:
        return []

    # 3. Read timescale from mdia.mdhd
    mdia = _find_box(target_trak, b'mdia')
    if not mdia:
        return []
    mdhd = _find_box(mdia, b'mdhd')
    if not mdhd or len(mdhd) < 20:
        return []

    ver = mdhd[0]
    if ver == 1:
        if len(mdhd) < 32:
            return []
        timescale = struct.unpack('>I', mdhd[20:24])[0]
    else:
        timescale = struct.unpack('>I', mdhd[12:16])[0]

    if timescale <= 0:
        return []

    minf = _find_box(mdia, b'minf')
    if not minf:
        return []
    stbl = _find_box(minf, b'stbl')
    if not stbl:
        return []

    # 4. Read sample durations from stts
    stts = _find_box(stbl, b'stts')
    durations = []
    if stts and len(stts) >= 8:
        entry_count = struct.unpack('>I', stts[4:8])[0]
        spos = 8
        for _ in range(entry_count):
            if spos + 8 > len(stts):
                break
            scount, sdelta = struct.unpack('>II', stts[spos:spos + 8])
            durations.extend([sdelta] * scount)
            spos += 8

    # 5. Read chunk offsets from stco (32-bit) or co64 (64-bit)
    stco = _find_box(stbl, b'stco')
    co64 = _find_box(stbl, b'co64')
    chunk_offsets = []

    if stco and len(stco) >= 8:
        count = struct.unpack('>I', stco[4:8])[0]
        cpos = 8
        for _ in range(count):
            if cpos + 4 > len(stco):
                break
            chunk_offsets.append(struct.unpack('>I', stco[cpos:cpos + 4])[0])
            cpos += 4
    elif co64 and len(co64) >= 8:
        count = struct.unpack('>I', co64[4:8])[0]
        cpos = 8
        for _ in range(count):
            if cpos + 8 > len(co64):
                break
            chunk_offsets.append(struct.unpack('>Q', co64[cpos:cpos + 8])[0])
            cpos += 8

    if not chunk_offsets:
        return []

    # 6. Read sample titles by seeking to chunk offsets
    chapters = []
    cur_time_units = 0
    for idx, offset in enumerate(chunk_offsets, start=1):
        dur = durations[idx - 1] if idx - 1 < len(durations) else 0
        start_sec = cur_time_units / float(timescale)
        end_sec = (cur_time_units + dur) / float(timescale) if dur > 0 else None
        cur_time_units += dur

        title = ''
        try:
            stream.seek(offset)
            tlen_bytes = stream.read(2)
            if len(tlen_bytes) == 2:
                tlen = struct.unpack('>H', tlen_bytes)[0]
                text_bytes = stream.read(tlen)
                title = text_bytes.decode('utf-8', errors='replace').strip()
        except Exception:
            title = ''

        chapters.append({
            'index': idx,
            'title': title or f'Chapter {idx}',
            'start_time': start_sec,
            'end_time': end_sec,
            'start': start_sec,
            'end': end_sec if end_sec is not None else start_sec,
        })

    for i in range(len(chapters)):
        if chapters[i]['end_time'] is None and i + 1 < len(chapters):
            next_start = chapters[i + 1]['start_time']
            chapters[i]['end_time'] = next_start
            chapters[i]['end'] = next_start

    return chapters


def parse_mp4_chapters(stream: BinaryIO) -> list[dict]:
    """
    Parse ISO BMFF MP4/M4V/MOV chapters from a seekable stream.

    Walks top-level boxes, skips mdat without downloading contents,
    and inspects moov for Nero udta.chpl and QuickTime tref.chap tracks.
    """
    stream.seek(0)
    magic = stream.read(8)
    if len(magic) < 8 or magic[4:8] != b'ftyp':
        return []

    stream.seek(0)
    while True:
        hdr = stream.read(8)
        if len(hdr) < 8:
            break
        size, btype = struct.unpack('>I4s', hdr)
        hdr_size = 8
        if size == 1:
            large_hdr = stream.read(8)
            if len(large_hdr) < 8:
                break
            size = struct.unpack('>Q', large_hdr)[0]
            hdr_size = 16
        elif size == 0:
            if hasattr(stream, 'total_size') and getattr(stream, 'total_size', None) is not None:
                size = stream.total_size - (stream.tell() - hdr_size)
            else:
                break

        box_start = stream.tell() - hdr_size
        box_end = box_start + size if size > 0 else None

        if btype == b'moov':
            payload_size = size - hdr_size if size > 0 else 2 * 1024 * 1024
            payload_size = min(payload_size, 2 * 1024 * 1024)
            moov_data = stream.read(payload_size)

            # Try Nero udta.chpl first
            udta = _find_box(moov_data, b'udta')
            if udta:
                chpl = _find_box(udta, b'chpl')
                if chpl:
                    nero = _parse_nero_chpl(chpl)
                    if nero:
                        return nero

            # Try QuickTime timed text track
            qt = _parse_quicktime_chapter_track(moov_data, stream)
            if qt:
                return qt

            break
        else:
            if box_end is not None:
                stream.seek(box_end)
            else:
                break

    return []


# ── Public API ───────────────────────────────────────────────────────────────


def open_stream(kodi_url: str, timeout: float = 8.0) -> BinaryIO | None:
    """Open a seekable stream for a Kodi play URL (remote HTTP with headers or local file)."""
    if not kodi_url:
        return None

    clean_url, hdrs = parse_kodi_url(kodi_url)
    if clean_url.startswith(('http://', 'https://')):
        try:
            return HttpRangeFile(clean_url, headers=hdrs, timeout=timeout)
        except Exception as e:
            control.log(f"chapter_extractor: HttpRangeFile open failed: {e}", 'debug')
            return None
    else:
        try:
            local_path = clean_url
            if local_path.startswith('file://'):
                local_path = local_path[7:]
                if sys.platform == 'win32' and local_path.startswith('/'):
                    local_path = local_path.lstrip('/')
            local_path = control.xbmcvfs.translatePath(local_path)
            if os.path.isfile(local_path):
                return open(local_path, 'rb')
        except Exception as e:
            control.log(f"chapter_extractor: local file open failed: {e}", 'debug')
            return None

    return None


def get_remote_chapters(kodi_url: str, timeout: int = 8) -> list[dict]:
    """
    Extract container chapters from a remote stream or local file using pure Python.

    Returns a list of normalized dictionaries sorted by start_time:
    [
        {
            "index": 1,
            "title": "Opening",
            "start_time": 0.0,
            "end_time": 90.5,
            "start": 0.0,
            "end": 90.5,
        },
        ...
    ]
    Fails fast and returns [] on unsupported hosts, budget limits, or parse errors.
    """
    if not kodi_url:
        return []

    stream = open_stream(kodi_url, timeout=float(timeout))
    if stream is None:
        return []

    try:
        # Check container format
        stream.seek(0)
        magic = stream.read(8)
        if len(magic) < 4:
            return []

        if magic.startswith(b'\x1a\x45\xdf\xa3'):
            return parse_mkv_chapters(stream)
        elif len(magic) >= 8 and magic[4:8] == b'ftyp':
            return parse_mp4_chapters(stream)
        else:
            return []
    except (RangeNotSupportedError, DownloadBudgetExceededError) as e:
        control.log(f"chapter_extractor: fast fail ({e})", 'debug')
        return []
    except Exception as e:
        control.log(f"chapter_extractor: parse exception ({e})", 'warning')
        return []
    finally:
        try:
            stream.close()
        except Exception:
            pass
