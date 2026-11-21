#!/usr/bin/env python3
"""
scripts/audit_onn_logs.py - Strictly Read-Only ONN 4K Pro Log Auditor
=====================================================================
Reads incremental Kodi log bytes from the ONN 4K Pro HTTP tail endpoint
(HTTP GET http://10.13.0.16:8081/tail?offset=<N>) or a local log file
(--input) using the cursor recorded in docs/CONCERNS.md.

Strictly read-only:
  - Uses HTTP GET only (urllib.request.Request(..., method='GET')).
  - Never executes subprocess, SSH, ADB, or mutating HTTP requests.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = 'http://10.13.0.16:8081/tail'
DEFAULT_CONCERNS = 'docs/CONCERNS.md'

CURSOR_RE = re.compile(r'\*\*Next review offset\*\*\s*\|\s*\*\*(\d+)\*\*')
CURSOR_FALLBACK_RE = re.compile(r'Next review offset\*{0,2}\s*[:|]\s*\*{0,2}(\d+)')

NOISE_RE = re.compile(
    r'plugin\.video\.umbrella|service\.upnext|/fake/|Control [0-9]+ in window 10025'
    r'|ParseChildManifest|JSONRPC: Empty batch|OutputPicture - timeout|ActiveAE',
    re.IGNORECASE,
)
ERROR_RE = re.compile(r'error <general>|Traceback|PythonToCpp|EXCEPTION|\bERROR\b', re.IGNORECASE)
WARNING_RE = re.compile(r'warning <general>|\bWARNING\b', re.IGNORECASE)
OTAKU_RE = re.compile(r'otaku\.rpdev|OTAKU RPDEV', re.IGNORECASE)

ZERO_WAIT_RE = re.compile(
    r'Zero-Wait Pre-Resolved Stream Hit|Zero-Wait direct stream pre-resolved|resolve_silent',
    re.IGNORECASE,
)
SUBTITLE_RE = re.compile(
    r'CDVDSubtitlesLibass|OpenStream - Unable to create subtitle parser'
    r'|OnDownloadComplete|Signs-only sidecar|Subtitle Service:',
    re.IGNORECASE,
)
ADDON_VERSION_RE = re.compile(
    r"((?:plugin\.video|context|service\.subtitles)\.otaku\.rpdev)\s+v?(\d+\.\d+\.\d+)"
)

CONCERN_PATTERNS = {
    'C-06': re.compile(r'CHANGE_LOG.*(?:exit_code|directory|error)|exit_code.*CHANGE_LOG', re.IGNORECASE),
    'C-14': re.compile(r'Unable to create subtitle parser', re.IGNORECASE),
    'C-34': re.compile(r'resolve_silent.*(?:pruned|failed|error)|Zero-Wait.*failed', re.IGNORECASE),
    'C-35': re.compile(r'WatchlistFlavorAuth|wlf_auth_|Closing unattended|window 12600', re.IGNORECASE),
}


def read_concerns_offset(concerns_path):
    """Extract the integer Next review offset cursor from docs/CONCERNS.md."""
    with open(concerns_path, 'r', encoding='utf-8') as f:
        text = f.read()
    m = CURSOR_RE.search(text) or CURSOR_FALLBACK_RE.search(text)
    if not m:
        raise ValueError(f"Could not find 'Next review offset' cursor in {concerns_path}")
    return int(m.group(1))


def fetch_log_from_url(url, offset, timeout=10.0):
    """Fetch log tail strictly via HTTP GET with explicit timeout."""
    offset = int(offset)
    if offset < 0:
        raise ValueError(f"Offset must be >= 0, got {offset}")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in ('http', 'https') or not parsed.netloc:
        raise ValueError(f"Unsupported or invalid audit URL: {url!r}")
    sep = '&' if '?' in url else '?'
    full_url = f"{url}{sep}offset={offset}"
    req = urllib.request.Request(full_url, method='GET')
    with urllib.request.urlopen(req, timeout=float(timeout)) as resp:
        raw_bytes = resp.read()
        seek_hdr = resp.headers.get('X-Seek-Offset') if resp.headers else None
        x_seek = int(seek_hdr) if seek_hdr is not None and str(seek_hdr).strip().isdigit() else None
    return raw_bytes, x_seek


def fetch_log_from_file(input_path, offset=0):
    """Read a local log fixture or capture starting from byte offset."""
    offset = int(offset)
    if offset < 0:
        raise ValueError(f"Offset must be >= 0, got {offset}")
    with open(input_path, 'rb') as f:
        data = f.read()
    if offset > 0:
        data = data[offset:] if offset < len(data) else b''
    return data, None


def analyze_log_text(text, requested_offset=0, x_seek_offset=None, raw_bytes_len=None):
    """Classify Otaku-RPDev log signals, non-Otaku noise, rotations, and open concerns."""
    requested_offset = int(requested_offset)
    if requested_offset < 0:
        raise ValueError(f"Offset must be >= 0, got {requested_offset}")
    if raw_bytes_len is None:
        raw_bytes_len = len(text.encode('utf-8', errors='replace'))

    stripped_head = text.lstrip()
    rotated = stripped_head.startswith('Starting Kodi (') or (
        x_seek_offset is not None and x_seek_offset < requested_offset
    )
    if rotated and x_seek_offset is not None:
        next_offset = x_seek_offset + raw_bytes_len
    elif rotated:
        next_offset = raw_bytes_len
    else:
        next_offset = requested_offset + raw_bytes_len

    otaku_errors = []
    otaku_warnings = []
    noise_filtered = []
    zero_wait_hits = []
    subtitle_events = []
    clean_settings_lines = []
    addon_versions = {}
    concerns_hits = {cid: [] for cid in CONCERN_PATTERNS}

    lines = text.splitlines()
    for line in lines:
        ver_match = ADDON_VERSION_RE.search(line)
        if ver_match:
            addon_versions[ver_match.group(1)] = ver_match.group(2)

        if 'clean_settings' in line and OTAKU_RE.search(line):
            clean_settings_lines.append(line.strip())

        is_noise = bool(NOISE_RE.search(line))
        is_otaku = bool(OTAKU_RE.search(line))

        if is_noise and (ERROR_RE.search(line) or WARNING_RE.search(line)):
            noise_filtered.append(line.strip())
        else:
            if ERROR_RE.search(line) and (is_otaku or 'PythonToCpp' in line or 'Traceback' in line):
                otaku_errors.append(line.strip())
            elif WARNING_RE.search(line) and is_otaku:
                otaku_warnings.append(line.strip())

        if ZERO_WAIT_RE.search(line):
            zero_wait_hits.append(line.strip())
        if SUBTITLE_RE.search(line):
            subtitle_events.append(line.strip())

        for cid, pattern in CONCERN_PATTERNS.items():
            if pattern.search(line):
                concerns_hits[cid].append(line.strip())

    return {
        'status': 'ok',
        'requested_offset': int(requested_offset),
        'x_seek_offset': x_seek_offset,
        'bytes_read': raw_bytes_len,
        'next_offset': next_offset,
        'rotated': rotated,
        'total_lines': len(lines),
        'addon_versions': addon_versions,
        'counts': {
            'otaku_errors': len(otaku_errors),
            'otaku_warnings': len(otaku_warnings),
            'non_otaku_noise_filtered': len(noise_filtered),
            'zero_wait': len(zero_wait_hits),
            'subtitles': len(subtitle_events),
            'clean_settings': len(clean_settings_lines),
            'concerns': {cid: len(hits) for cid, hits in concerns_hits.items()},
        },
        'samples': {
            'otaku_errors': otaku_errors[:10],
            'otaku_warnings': otaku_warnings[:10],
            'zero_wait': zero_wait_hits[:10],
            'subtitles': subtitle_events[:10],
            'clean_settings': clean_settings_lines[:5],
            'concerns': {cid: hits[:5] for cid, hits in concerns_hits.items() if hits},
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description='Strictly read-only ONN 4K Pro Kodi log auditor')
    parser.add_argument('--concerns', default=DEFAULT_CONCERNS, help='Path to docs/CONCERNS.md cursor file')
    parser.add_argument('--offset', type=int, default=None, help='Override starting byte offset')
    parser.add_argument('--url', default=DEFAULT_URL, help='Read-only HTTP tail URL')
    parser.add_argument('--input', dest='input_path', default=None, help='Local log file for offline auditing')
    parser.add_argument('--timeout', type=float, default=10.0, help='HTTP GET timeout in seconds')
    parser.add_argument(
        '--json',
        dest='json_target',
        nargs='?',
        const='-',
        default=None,
        help="Write JSON report ('-' or omitted value prints to stdout)",
    )
    args = parser.parse_args(argv)

    offset = int(args.offset) if args.offset is not None else 0

    try:
        if args.offset is not None:
            offset = int(args.offset)
        elif args.input_path and args.concerns == DEFAULT_CONCERNS and not os.path.exists(args.concerns):
            offset = 0
        else:
            offset = read_concerns_offset(args.concerns)

        if offset < 0:
            raise ValueError(f"Offset must be >= 0, got {offset}")

        if args.input_path:
            # When auditing a local fixture file with --concerns cursor > file size, read from 0 unless --offset was explicit
            file_offset = int(args.offset) if args.offset is not None else 0
            raw_bytes, x_seek = fetch_log_from_file(args.input_path, offset=file_offset)
            effective_offset = file_offset if args.offset is not None else offset
        else:
            raw_bytes, x_seek = fetch_log_from_url(args.url, offset=offset, timeout=args.timeout)
            effective_offset = offset
    except (OSError, urllib.error.URLError, ValueError) as exc:
        err_payload = {'status': 'error', 'error': str(exc), 'requested_offset': offset}
        if args.json_target == '-':
            print(json.dumps(err_payload, indent=2))
        elif args.json_target:
            os.makedirs(os.path.dirname(os.path.abspath(args.json_target)), exist_ok=True)
            with open(args.json_target, 'w', encoding='utf-8') as jf:
                json.dump(err_payload, jf, indent=2)
        else:
            print(f"ERROR: Failed to read ONN logs: {exc}", file=sys.stderr)
        return 1

    text = raw_bytes.decode('utf-8', errors='replace')
    report = analyze_log_text(
        text,
        requested_offset=effective_offset,
        x_seek_offset=x_seek,
        raw_bytes_len=len(raw_bytes),
    )

    if args.json_target == '-':
        print(json.dumps(report, indent=2))
    elif args.json_target:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_target)), exist_ok=True)
        with open(args.json_target, 'w', encoding='utf-8') as jf:
            json.dump(report, jf, indent=2)
    else:
        c = report['counts']
        print(
            f"ONN Log Audit: lines={report['total_lines']} bytes={report['bytes_read']} "
            f"rotated={report['rotated']} next_offset={report['next_offset']}"
        )
        print(
            f"  otaku_errors={c['otaku_errors']} otaku_warnings={c['otaku_warnings']} "
            f"noise_filtered={c['non_otaku_noise_filtered']} zero_wait={c['zero_wait']} subtitles={c['subtitles']}"
        )
    return 0


if __name__ == '__main__':
    sys.exit(main())
