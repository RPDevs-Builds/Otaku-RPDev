"""archive.py - Subtitle Archive Extractor (.zip, .gz) with Strict Episode Matching
================================================================================
"""

# -*- coding: utf-8 -*-

import io
import gzip
import zipfile
import re
from typing import Optional, Tuple, List


SUBTITLE_EXTENSIONS = ('.srt', '.ass', '.ssa', '.vtt', '.sub')


class ArchiveEpisodeMismatchError(Exception):
    """Raised when target episode is absent from an extracted subtitle archive."""
    pass


def find_file_in_archive_namelist(namelist: List[str], episode_number: str = '', season_number: str = '') -> Optional[str]:
    """
    Search a list of file paths in an archive for the best matching subtitle file.
    Enforces strict episode isolation when episode_number is provided.
    """
    sub_files = [f for f in namelist if f.lower().endswith(SUBTITLE_EXTENSIONS)]
    if not sub_files:
        return None

    if not episode_number:
        # Movie or single-file release: pick the first subtitle file
        return sub_files[0]

    try:
        ep_int = int(episode_number)
    except (ValueError, TypeError):
        ep_int = None

    if ep_int is None:
        return sub_files[0]

    # Build regex patterns for episode matching
    ep_patterns = [
        re.compile(rf'[._\s\-\[x]s?\d{{1,2}}e0*{ep_int}[._\s\-\]]', re.IGNORECASE),
        re.compile(rf'[._\s\-\[]\d{{1,2}}x0*{ep_int}[._\s\-\]]', re.IGNORECASE),
        re.compile(rf'[._\s\-\[]e0*{ep_int}[._\s\-\]]', re.IGNORECASE),
        re.compile(rf'[._\s\-\[]ep0*{ep_int}[._\s\-\]]', re.IGNORECASE),
        re.compile(rf'[\s\-_]0*{ep_int}[\s\-_\.]', re.IGNORECASE),
        re.compile(rf'\[0*{ep_int}\]', re.IGNORECASE),
        re.compile(rf'#0*{ep_int}\b', re.IGNORECASE),
    ]

    # Try strict season + episode matching first if season is known
    if season_number:
        try:
            s_int = int(season_number)
            strict_se_patterns = [
                re.compile(rf'[._\s\-\[]s0*{s_int}e0*{ep_int}[._\s\-\]]', re.IGNORECASE),
                re.compile(rf'[._\s\-\[]0*{s_int}x0*{ep_int}[._\s\-\]]', re.IGNORECASE),
            ]
            for pat in strict_se_patterns:
                for f in sub_files:
                    basename = f.split('/')[-1]
                    if pat.search(basename):
                        return f
        except (ValueError, TypeError):
            pass

    # Try general episode patterns
    for pat in ep_patterns:
        for f in sub_files:
            basename = f.split('/')[-1]
            if pat.search(basename):
                return f

    # If episode was specified but no pattern matched, DO NOT fall back to arbitrary first file
    return None


def extract_subtitle_from_archive(raw_bytes: bytes, filename: str = '', episode_number: str = '', season_number: str = '') -> Tuple[bytes, str]:
    """
    Extracts subtitle file content from raw archive bytes (.zip or .gz).
    Returns (extracted_bytes, inner_filename).
    Raises ArchiveEpisodeMismatchError if requested episode is missing.
    """
    # 1. Try ZIP
    if raw_bytes[:4] in (b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08'):
        try:
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                namelist = zf.namelist()
                matched_name = find_file_in_archive_namelist(namelist, episode_number=episode_number, season_number=season_number)
                if not matched_name:
                    if episode_number:
                        raise ArchiveEpisodeMismatchError(f"Episode {episode_number} not found in zip archive containing {len(namelist)} files")
                    # Fallback to first subtitle file
                    sub_files = [f for f in namelist if f.lower().endswith(SUBTITLE_EXTENSIONS)]
                    if sub_files:
                        matched_name = sub_files[0]
                    else:
                        raise ValueError("No subtitle files (.srt, .ass, etc.) found in zip archive")

                content = zf.read(matched_name)
                inner_name = matched_name.split('/')[-1]
                return content, inner_name
        except zipfile.BadZipFile:
            pass

    # 2. Try GZIP
    if raw_bytes[:2] == b'\x1f\x8b':
        try:
            decompressed = gzip.decompress(raw_bytes)
            # Gzip might contain a tar archive or raw subtitle text
            if decompressed[:4] in (b'PK\x03\x04', b'PK\x05\x06'):
                return extract_subtitle_from_archive(decompressed, filename, episode_number, season_number)
            # Raw subtitle text compressed via gzip
            inner_name = filename or 'subtitle.srt'
            if inner_name.lower().endswith('.gz'):
                inner_name = inner_name[:-3]
            return decompressed, inner_name
        except Exception:
            pass

    # 3. Raw uncompressed subtitle content
    inner_name = filename or 'subtitle.srt'
    return raw_bytes, inner_name
