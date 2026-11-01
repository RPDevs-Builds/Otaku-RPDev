"""encoding.py - Subtitle Character Encoding Detection and UTF-8 Transcoder
========================================================================
"""

# -*- coding: utf-8 -*-

import re
from typing import Optional, Tuple

try:
    import chardet
    HAS_CHARDET = True
except ImportError:
    try:
        from chardet import chardet
        HAS_CHARDET = True
    except ImportError:
        HAS_CHARDET = False


FALLBACK_ENCODINGS = [
    'utf-8',
    'utf-8-sig',
    'cp1252',
    'latin-1',
    'iso-8859-1',
    'iso-8859-15',
    'shift_jis',
    'euc-jp',
    'gbk',
    'gb18030',
    'big5',
    'euc-kr',
    'windows-1256',
    'windows-1251',
]


def detect_encoding(raw_bytes: bytes, use_chardet: bool = True) -> str:
    """Detect the encoding of subtitle byte content."""
    if not raw_bytes:
        return 'utf-8'

    # Check BOM markers first
    if raw_bytes.startswith(b'\xef\xbb\xbf'):
        return 'utf-8-sig'
    if raw_bytes.startswith(b'\xff\xfe'):
        return 'utf-16-le'
    if raw_bytes.startswith(b'\xfe\xff'):
        return 'utf-16-be'

    # Try pure UTF-8 first (fastest)
    try:
        raw_bytes.decode('utf-8')
        return 'utf-8'
    except UnicodeDecodeError:
        pass

    # Use chardet if available and enabled
    if use_chardet and HAS_CHARDET:
        try:
            detected = chardet.detect(raw_bytes[:65536])
            enc = detected.get('encoding')
            confidence = detected.get('confidence', 0.0)
            if enc and confidence >= 0.5:
                return enc.lower()
        except Exception:
            pass

    # Probe fallback encodings
    for enc in FALLBACK_ENCODINGS:
        try:
            raw_bytes.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue

    return 'utf-8'


def fix_subtitle_encoding(raw_bytes: bytes, use_chardet: bool = True) -> Tuple[str, str]:
    """
    Decodes raw subtitle bytes to a clean UTF-8 unicode string.
    Returns (decoded_text, detected_encoding).
    """
    encoding = detect_encoding(raw_bytes, use_chardet=use_chardet)

    try:
        text = raw_bytes.decode(encoding, errors='replace')
    except (UnicodeDecodeError, LookupError):
        text = raw_bytes.decode('latin-1', errors='replace')
        encoding = 'latin-1'

    # Strip BOM if present in decoded string
    if text.startswith('\ufeff'):
        text = text[1:]

    # Normalize line endings to standard Unix \n
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    return text, encoding
