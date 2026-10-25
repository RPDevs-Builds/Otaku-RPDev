"""
Optional ffprobe-based chapter metadata for resolved play URLs.

Kodi (and inputstream.ffmpegdirect) use FFmpeg libraries for demux/playback but
do not expose a Python API to list container chapters on Omega. Running ffprobe
against the same URL Kodi will play is the practical way to collect chapter
names/times before or during resolve.

See: https://github.com/xbmc/inputstream.ffmpegdirect (playback path, not metadata API)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.parse

from resources.lib.ui import control

_ffprobe_cached: str | None = False  # type: ignore[assignment]


def _xbmc_bin_dir() -> str:
    try:
        exe = getattr(sys, 'executable', '') or ''
        if exe and os.path.isfile(exe):
            return os.path.dirname(exe)
    except Exception:
        pass
    try:
        return control.xbmcvfs.translatePath('special://xbmc')
    except Exception:
        return ''


def find_ffprobe() -> str | None:
    """Return path to ffprobe if found, else None."""
    global _ffprobe_cached
    if _ffprobe_cached not in (False, None):
        return _ffprobe_cached or None

    candidates = []

    custom = (control.getStr('ffprobe.path') or '').strip().strip('"')
    if custom:
        candidates.append(custom)

    which = shutil.which('ffprobe')
    if which:
        candidates.append(which)
    if sys.platform == 'win32':
        w = shutil.which('ffprobe.exe')
        if w:
            candidates.append(w)

    base = _xbmc_bin_dir()
    if base:
        if sys.platform == 'win32':
            candidates.extend([
                os.path.join(base, 'ffprobe.exe'),
                os.path.join(base, 'ffmpeg', 'ffprobe.exe'),
                os.path.join(base, 'tools', 'ffmpeg', 'bin', 'ffprobe.exe'),
            ])
        else:
            candidates.extend([
                os.path.join(base, 'ffprobe'),
                os.path.join(base, 'ffmpeg', 'ffprobe'),
                os.path.join(base, 'tools', 'ffmpeg', 'bin', 'ffprobe'),
            ])

    for path in candidates:
        if path and os.path.isfile(path):
            _ffprobe_cached = path
            control.log(f'ffprobe: using {path}', 'debug')
            return path

    _ffprobe_cached = None
    return None


def _split_url_headers(play_url: str) -> tuple[str, dict[str, str]]:
    if '|' not in play_url:
        return play_url, {}
    url, hdrs = play_url.split('|', 1)
    headers = {}
    for pair in hdrs.split('&'):
        if '=' not in pair:
            continue
        k, v = pair.split('=', 1)
        headers[k] = urllib.parse.unquote_plus(v)
    return url, headers


def _headers_ffprobe_arg(headers: dict) -> str | None:
    if not headers:
        return None
    lines = []
    for key, value in headers.items():
        if value is None:
            continue
        k = str(key).strip()
        if not k:
            continue
        lines.append(f'{k}: {str(value).strip()}')
    if not lines:
        return None
    return '\r\n'.join(lines) + '\r\n'


def _should_probe_url(clean_url: str, content_type: str, is_local: bool) -> bool:
    ct = (content_type or '').lower()
    u = clean_url.lower()
    path_only = u.split('?')[0]

    if path_only.endswith(('.mkv', '.mp4', '.m4v', '.webm')):
        return True

    if 'm3u8' in u or '.mpd' in u or 'manifest' in u:
        return False
    if 'mpegurl' in ct or 'mp2t' in ct or 'dash' in ct or 'm3u8' in ct:
        return False
    if 'video/x-matroska' in ct or 'matroska' in ct:
        return True
    if 'video/mp4' in ct or 'video/quicktime' in ct:
        return True
    if 'application/octet-stream' in ct and '.mkv' in u:
        return True
    if ct.startswith('video/') and 'mpegurl' not in ct and 'mp2t' not in ct:
        return True
    if clean_url.startswith('file://'):
        return True
    if is_local and (u.startswith('special://') or u.startswith('smb://') or u.startswith('nfs://')):
        return True
    if sys.platform == 'win32' and len(clean_url) > 2 and clean_url[1] == ':' and '\\' in clean_url:
        return True
    if clean_url.startswith('/'):
        try:
            if os.path.isfile(control.xbmcvfs.translatePath(clean_url)):
                return True
        except Exception:
            pass
    return False


def probe_stream_chapters(ffprobe_path: str, play_url: str, timeout: int = 18) -> list[dict]:
    """
    Return chapter dicts: index, title, start (seconds float), end (seconds float).
    play_url may include Kodi-style '|Cookie=...&User-Agent=...' suffix.
    """
    clean_url, hdrs = _split_url_headers(play_url)
    if not clean_url:
        return []

    args = [
        ffprobe_path,
        '-v', 'error',
        '-hide_banner',
        '-print_format', 'json',
        '-show_chapters',
        '-probesize', '33554432',
        '-analyzeduration', '10000000',
    ]
    h = _headers_ffprobe_arg(hdrs)
    if h:
        args.extend(['-headers', h])
    args.extend(['-i', clean_url])

    creationflags = 0
    startupinfo = None
    if sys.platform == 'win32':
        creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
    except subprocess.TimeoutExpired:
        control.log('ffprobe: chapter probe timed out', 'warning')
        return []
    except OSError as e:
        control.log(f'ffprobe: failed to run ({e})', 'warning')
        return []

    if proc.returncode != 0:
        err = (proc.stderr or '').strip()[:500]
        if err:
            control.log(f'ffprobe: exit {proc.returncode} — {err}', 'debug')
        return []

    try:
        data = json.loads(proc.stdout or '{}')
    except json.JSONDecodeError:
        return []

    out = []
    for i, ch in enumerate(data.get('chapters') or []):
        tags = ch.get('tags') or {}
        title = tags.get('title') or tags.get('TITLE') or f'Chapter {i + 1}'
        try:
            start = float(ch.get('start_time', 0))
        except (TypeError, ValueError):
            start = 0.0
        try:
            end = float(ch.get('end_time', start))
        except (TypeError, ValueError):
            end = start
        out.append({
            'index': i,
            'title': str(title).strip(),
            'start': start,
            'end': end,
        })
    return out


def _read_ebml_vint(data: bytes, offset: int) -> tuple[int, int, int]:
    """Read an EBML variable length integer (VINT). Returns (vint_value, vint_length, next_offset)."""
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
    """Read an EBML Element ID without masking the leading length bits."""
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


def probe_mkv_chapters_ebml(play_url: str, timeout: int = 8) -> list[dict]:
    """Pure-Python Matroska EBML chapter reader using HTTP Range requests or local file reads."""
    clean_url, hdrs = _split_url_headers(play_url)
    if not clean_url:
        return []

    def fetch_bytes(start: int, length: int) -> bytes:
        if clean_url.startswith(('http://', 'https://')):
            import urllib.request
            req_headers = dict(hdrs)
            req_headers['Range'] = f'bytes={start}-{start + length - 1}'
            if 'User-Agent' not in req_headers:
                req_headers['User-Agent'] = 'Mozilla/5.0'
            req = urllib.request.Request(clean_url, headers=req_headers)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read()
            except Exception:
                return b''
        else:
            try:
                local_path = control.xbmcvfs.translatePath(clean_url)
                if os.path.isfile(local_path):
                    with open(local_path, 'rb') as f:
                        f.seek(start)
                        return f.read(length)
            except Exception:
                pass
            return b''

    # 1. Fetch initial 256 KB
    buf = fetch_bytes(0, 262144)
    if len(buf) < 16 or not buf.startswith(b'\x1a\x45\xdf\xa3'):
        return []

    # Parse EBML header to find Segment
    pos = 0
    seg_data_pos = None
    while pos < len(buf):
        eid, elen, pos = _read_ebml_id(buf, pos)
        if elen == 0:
            break
        esize, slen, pos = _read_ebml_vint(buf, pos)
        if slen == 0:
            break
        if eid == 0x18538067:  # Segment
            seg_data_pos = pos
            break
        else:
            pos += esize

    if seg_data_pos is None or seg_data_pos >= len(buf):
        return []

    # Look for Chapters (0x1043A770) or SeekHead (0x114D9B74)
    chapters_data = None
    seek_target_offset = None
    pos = seg_data_pos

    while pos < len(buf) - 8:
        eid, elen, pos = _read_ebml_id(buf, pos)
        if elen == 0:
            break
        esize, slen, pos = _read_ebml_vint(buf, pos)
        if slen == 0:
            break
        data_end = pos + esize

        if eid == 0x1043A770:  # Chapters
            if data_end <= len(buf):
                chapters_data = buf[pos:data_end]
            else:
                chapters_data = fetch_bytes(pos, esize)
            break
        elif eid == 0x114D9B74:  # SeekHead
            # Scan Seek elements (0x4DBB)
            sh_pos = pos
            sh_end = min(data_end, len(buf))
            while sh_pos < sh_end - 4:
                seid, selen, sh_pos = _read_ebml_id(buf, sh_pos)
                if selen == 0:
                    break
                sesize, sslen, sh_pos = _read_ebml_vint(buf, sh_pos)
                if sslen == 0:
                    break
                send = sh_pos + sesize
                if seid == 0x4DBB:  # Seek
                    cur_seek_id = None
                    cur_seek_pos = None
                    sk_pos = sh_pos
                    while sk_pos < send:
                        keid, kelen, sk_pos = _read_ebml_id(buf, sk_pos)
                        if kelen == 0:
                            break
                        kesize, kslen, sk_pos = _read_ebml_vint(buf, sk_pos)
                        if kslen == 0:
                            break
                        kend = sk_pos + kesize
                        if keid == 0x53AB and kend <= len(buf):  # SeekID
                            cur_seek_id = buf[sk_pos:kend]
                        elif keid == 0x53AC and kend <= len(buf):  # SeekPosition
                            cur_seek_pos = int.from_bytes(buf[sk_pos:kend], 'big')
                        sk_pos = kend
                    if cur_seek_id == b'\x10\x43\xa7\x70' and cur_seek_pos is not None:
                        seek_target_offset = seg_data_pos + cur_seek_pos
                sh_pos = send
            pos = data_end
        elif eid == 0x1F43B675:  # First Cluster (stop scanning header)
            break
        else:
            pos = data_end

    if not chapters_data and seek_target_offset is not None:
        raw_ch = fetch_bytes(seek_target_offset, 65536)
        if raw_ch:
            cid, clen, cpos = _read_ebml_id(raw_ch, 0)
            if cid == 0x1043A770:
                csize, cslen, cpos = _read_ebml_vint(raw_ch, cpos)
                if cpos + csize <= len(raw_ch):
                    chapters_data = raw_ch[cpos:cpos + csize]
                else:
                    chapters_data = fetch_bytes(seek_target_offset + cpos, csize)

    if not chapters_data:
        return []

    # Parse EditionEntry (0x45B9) -> ChapterAtom (0xB6)
    chapters = []
    cpos = 0
    atom_idx = 0
    while cpos < len(chapters_data) - 4:
        eid, elen, cpos = _read_ebml_id(chapters_data, cpos)
        if elen == 0:
            break
        esize, slen, cpos = _read_ebml_vint(chapters_data, cpos)
        if slen == 0:
            break
        eend = cpos + esize
        if eid == 0x45B9:  # EditionEntry
            ed_pos = cpos
            while ed_pos < eend:
                aeid, aelen, ed_pos = _read_ebml_id(chapters_data, ed_pos)
                if aelen == 0:
                    break
                aesize, aslen, ed_pos = _read_ebml_vint(chapters_data, ed_pos)
                if aslen == 0:
                    break
                aend = ed_pos + aesize
                if aeid == 0xB6:  # ChapterAtom
                    atom_pos = ed_pos
                    c_start = None
                    c_end = None
                    c_title = None
                    while atom_pos < aend:
                        feid, felen, atom_pos = _read_ebml_id(chapters_data, atom_pos)
                        if felen == 0:
                            break
                        fesize, fslen, atom_pos = _read_ebml_vint(chapters_data, atom_pos)
                        if fslen == 0:
                            break
                        fend = atom_pos + fesize
                        if feid == 0x91 and fend <= len(chapters_data):  # ChapterTimeStart (ns)
                            c_start = int.from_bytes(chapters_data[atom_pos:fend], 'big') / 1_000_000_000.0
                        elif feid == 0x92 and fend <= len(chapters_data):  # ChapterTimeEnd (ns)
                            c_end = int.from_bytes(chapters_data[atom_pos:fend], 'big') / 1_000_000_000.0
                        elif feid == 0x80:  # ChapterDisplay
                            cd_pos = atom_pos
                            while cd_pos < fend:
                                deid, delen, cd_pos = _read_ebml_id(chapters_data, cd_pos)
                                if delen == 0:
                                    break
                                desize, dslen, cd_pos = _read_ebml_vint(chapters_data, cd_pos)
                                if dslen == 0:
                                    break
                                dend = cd_pos + desize
                                if deid == 0x85 and dend <= len(chapters_data):  # ChapString
                                    try:
                                        c_title = chapters_data[cd_pos:dend].decode('utf-8', errors='ignore').strip()
                                    except Exception:
                                        c_title = None
                                cd_pos = dend
                        atom_pos = fend
                    if c_start is not None:
                        chapters.append({
                            'index': atom_idx,
                            'title': c_title or f'Chapter {atom_idx + 1}',
                            'start': float(c_start),
                            'end': float(c_end) if c_end is not None else float(c_start)
                        })
                        atom_idx += 1
                ed_pos = aend
        cpos = eend

    chapters.sort(key=lambda x: x['start'])
    for i in range(len(chapters)):
        if chapters[i]['end'] <= chapters[i]['start'] and i + 1 < len(chapters):
            if chapters[i + 1]['start'] > chapters[i]['start']:
                chapters[i]['end'] = chapters[i + 1]['start']
    return chapters


def attach_to_linkinfo(linkinfo: dict | None) -> None:
    """
    Mutates linkinfo to add 'chapters' (list, possibly empty).
    Uses ffprobe if available, or pure-Python Matroska EBML reader as fallback.
    """
    if not linkinfo or not isinstance(linkinfo, dict):
        return

    linkinfo['chapters'] = []

    if not control.getBool('ffprobe.chapters.enable'):
        return

    play_url = linkinfo.get('url') or linkinfo.get('link')
    if not play_url:
        return

    headers = linkinfo.get('headers') or {}
    content_type = ''
    if isinstance(headers, dict):
        content_type = headers.get('Content-Type') or headers.get('content-type') or ''

    is_local = bool(linkinfo.get('local'))
    if not _should_probe_url(_split_url_headers(str(play_url))[0], content_type, is_local):
        return

    chapters = []
    exe = find_ffprobe()
    if exe:
        chapters = probe_stream_chapters(exe, str(play_url))

    if not chapters and ('.mkv' in str(play_url).lower() or 'matroska' in content_type.lower() or 'octet-stream' in content_type.lower()):
        try:
            chapters = probe_mkv_chapters_ebml(str(play_url))
        except Exception as e:
            control.log(f'ebml chapters probe error: {e}', 'warning')

    if chapters:
        linkinfo['chapters'] = chapters
        control.log(f'chapters: found {len(chapters)} chapter(s)', 'info')
