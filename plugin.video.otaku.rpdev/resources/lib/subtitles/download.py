"""download.py - Subtitle Downloader, Archive Extractor & Storage Manager
========================================================================
"""

# -*- coding: utf-8 -*-

import os
import re
import time
from typing import Optional, Dict, Any
from resources.lib.ui import control, embed_extractor
from resources.lib.subtitles.models import SubtitleResult, VideoMeta
from resources.lib.subtitles.services import ALL_SERVICES
from resources.lib.subtitles.archive import extract_subtitle_from_archive, ArchiveEpisodeMismatchError
from resources.lib.subtitles.encoding import fix_subtitle_encoding

SUBTITLE_TEMP_DIR = os.path.join(control.dataPath, 'temp', 'subtitles')


def sanitize_filename(name: str) -> str:
    """Strip illegal filesystem characters from a subtitle filename."""
    clean = re.sub(r'[\\/*?:"<>|]', '_', name)
    clean = re.sub(r'\s+', '_', clean)
    return clean.strip('_')


def purge_temp_subtitles():
    """Wipes all cached temporary subtitles from addon temp directory."""
    try:
        if os.path.exists(SUBTITLE_TEMP_DIR):
            for fname in os.listdir(SUBTITLE_TEMP_DIR):
                fpath = os.path.join(SUBTITLE_TEMP_DIR, fname)
                try:
                    if os.path.isfile(fpath):
                        os.remove(fpath)
                except Exception:
                    pass
    except Exception as e:
        control.log(f"Failed to purge temp subtitles: {e}", 'warning')


def download_and_prepare_subtitle(result: SubtitleResult, meta: VideoMeta, settings: Dict[str, Any]) -> Optional[str]:
    """
    Downloads, extracts from archive if needed, transcodes to UTF-8,
    and writes to isolated addon temp directory.
    Returns the absolute path of the local subtitle file, or None on failure.
    """
    service_cls = ALL_SERVICES.get(result.service_name)
    if not service_cls:
        control.log(f"Unknown subtitle provider: {result.service_name}", 'warning')
        return None

    # Ensure temp dir exists
    if not os.path.exists(SUBTITLE_TEMP_DIR):
        os.makedirs(SUBTITLE_TEMP_DIR, exist_ok=True)

    try:
        raw_bytes = service_cls.download(result, settings)
        if not raw_bytes:
            control.log(f"Provider {result.service_name} returned empty download content", 'warning')
            return None

        # Extract from archive if compressed (.zip / .gz) with strict episode matching
        sub_content, inner_filename = extract_subtitle_from_archive(
            raw_bytes,
            filename=result.name,
            episode_number=meta.episode,
            season_number=meta.season,
        )

        # Transcode encoding to UTF-8
        use_chardet = settings.get('subtitles.use_chardet', True)
        utf8_text, detected_enc = fix_subtitle_encoding(sub_content, use_chardet=use_chardet)

        # Validate & normalize against Kodi 22 CDVDFactorySubtitle::CreateParser() contract
        normalized_text, detected_ext, reject_reason = embed_extractor._validate_and_normalize_sub_content(
            utf8_text,
            inner_filename or result.name or result.download_url,
            source_url=result.download_url,
        )
        if not normalized_text:
            control.log(
                f"Native Subtitles: Rejected invalid subtitle payload from {result.service_name} "
                f"({result.name}): {reject_reason}",
                'warning',
            )
            return None

        # Determine target extension (.ass, .ssa, .vtt, .srt)
        ext = detected_ext or '.srt'
        if not ext.startswith('.'):
            ext = f'.{ext}'

        # Construct sanitized filename with unique per-download sub_tag nonce
        # to avoid Kodi 22 special://temp/ g_directoryCache stale-file collisions
        base_name = meta.filename_without_ext or sanitize_filename(result.name) or 'subtitle'
        lang_code = result.lang_code or 'en'
        sub_nonce = int(time.time() * 1000)
        target_filename = f"{sanitize_filename(base_name)}.{lang_code}.{sub_nonce}{ext}"
        dest_path = os.path.join(SUBTITLE_TEMP_DIR, target_filename)

        if control.atomic_write_text(dest_path, normalized_text) is False:
            control.log(f"Native Subtitles: Failed to atomically write {dest_path}", 'error')
            return None

        control.log(f"Native Subtitles: Downloaded and prepared {dest_path} (enc={detected_enc})", 'info')
        return dest_path

    except ArchiveEpisodeMismatchError as e:
        control.log(f"Native Subtitles: Skipped {result.name} - {e}", 'warning')
        return None
    except Exception as e:
        control.log(f"Native Subtitles: Download/preparation error for {result.name}: {e}", 'error')
        return None
