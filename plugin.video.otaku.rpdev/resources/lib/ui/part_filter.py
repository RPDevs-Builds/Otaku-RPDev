# -*- coding: utf-8 -*-
"""
part_filter.py - Multi-Part Anime Franchise & Hardsub Release Filter
=====================================================================
Filters torrent, hoster, embed, and cloud sources to prevent episode collisions
in multi-cour/multi-part franchises (e.g., Bleach TYBW, Attack on Titan,
Mushoku Tensei, Gintama) using mappings.db global offsets and drops unremovable
Chinese hardcoded subtitle releases when Chinese is not the user's preferred language.
Ported and enhanced from upstream Goldenfreddy0703/Otaku PR #501.
"""

import os
import re
import sqlite3
from resources.lib.ui import control

_CHINESE_TAGS = (
    '[chs]', '[cht]', '[gb]', '[big5]', '简体', '繁体', 'gb_mp4', 'big5_mp4', '[b-global]',
    'chs&jpn', 'cht&jpn', 'chs_jpn', 'cht_jpn', 'gb&jpn', 'big5&jpn'
)

# Roman numerals mapping for parts
_ROMAN_PARTS = {
    'i': 1, 'ii': 2, 'iii': 3, 'iv': 4, 'v': 5,
    '1': 1, '2': 2, '3': 3, '4': 4, '5': 5
}


def _get_mappings_info(mal_id):
    """Query mappings.db for anime franchise metadata."""
    if not mal_id:
        return None

    db_path = getattr(control, 'mappingDB', None)
    if not db_path or not os.path.exists(db_path):
        return None

    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT thetvdb_season, thetvdb_part, anime_media_episodes, global_media_episodes, mal_title "
            "FROM anime WHERE mal_id = ?",
            (int(mal_id),)
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None

        season, part, a_eps, g_eps, title = row
        return {
            'thetvdb_season': season,
            'thetvdb_part': part,
            'anime_media_episodes': a_eps or '',
            'global_media_episodes': g_eps or '',
            'mal_title': title or ''
        }
    except Exception as e:
        control.log(f"part_filter: Error reading mappings.db: {e}", 'warning')
        return None


def _parse_range(range_str):
    """Parse 'start - end' into (start, end) integers."""
    if not range_str or '-' not in range_str:
        return None, None
    parts = range_str.split('-')
    try:
        start = int(parts[0].strip())
        end = int(parts[1].strip())
        return start, end
    except (ValueError, IndexError):
        return None, None


def _has_chinese_hardsub(title_lower):
    """Check if title contains Chinese hardcoded subtitle tags."""
    for tag in _CHINESE_TAGS:
        if tag in title_lower:
            return True
    return False


def _user_wants_chinese():
    """Check if the user has Chinese subtitles configured in Kodi or Otaku."""
    try:
        # Check Otaku preferred subtitle language (e.g. 'chi', 'chinese', 'zho')
        pref_lang = control.getSetting('general.subtitles')
        if pref_lang and pref_lang.lower() in ('chi', 'chinese', 'zho', 'zh'):
            return True

        # Check Kodi subtitle language setting
        kodi_sub = control.kodi_get_setting('subtitles.languages') or ''
        if any(c in kodi_sub.lower() for c in ('chi', 'chinese', 'zh')):
            return True
    except Exception:
        pass
    return False


def _extract_part_from_title(title_lower):
    """Extract explicit 'Part X' or 'Cour X' from title string."""
    m = re.search(r'\b(?:part|cour)\s*([0-9]+|[ivx]+)\b', title_lower)
    if m:
        val = m.group(1).lower()
        return _ROMAN_PARTS.get(val)
    return None


def _extract_batch_range(title_lower):
    """Extract ascending batch episode range like (01-12), [01-24], etc."""
    m = re.search(r'[\(\[\s]([0-9]{1,4})\s*[-~–]\s*([0-9]{1,4})[\)\]\s]', title_lower)
    if m:
        try:
            start, end = int(m.group(1)), int(m.group(2))
            if start < end:
                return start, end
        except ValueError:
            pass
    return None, None


def filter_sources(sources, mal_id=None, episode=1, season=None, part=None):
    """
    Filter a list of source dictionaries based on franchise part metadata and subtitle language.

    :param sources: list of source dicts
    :param mal_id: MyAnimeList ID
    :param episode: requested episode number (int or str)
    :param season: optional TVDB season
    :param part: optional part number
    :return: filtered list of source dicts
    """
    if not sources:
        return []

    try:
        ep_num = int(episode)
    except (ValueError, TypeError):
        ep_num = 1

    allow_chinese = _user_wants_chinese()
    mapping_info = _get_mappings_info(mal_id) if mal_id else None

    # Calculate part and global episode offset if mapping info is available
    target_part = part
    global_ep = ep_num
    offset = 0

    if mapping_info:
        if target_part is None:
            target_part = mapping_info.get('thetvdb_part')

        a_start, _ = _parse_range(mapping_info.get('anime_media_episodes'))
        g_start, _ = _parse_range(mapping_info.get('global_media_episodes'))

        if a_start is not None and g_start is not None and g_start > a_start:
            offset = g_start - a_start
            global_ep = ep_num + offset

    filtered = []
    dropped_chinese = 0
    dropped_part_mismatch = 0
    dropped_batch_mismatch = 0

    for src in sources:
        title = src.get('name') or src.get('release_title') or src.get('title') or ''
        title_lower = title.lower()

        # 1. Chinese Hardsub Filter
        if not allow_chinese and _has_chinese_hardsub(title_lower):
            dropped_chinese += 1
            continue

        # 2. Multi-Part Franchise Filter
        if target_part is not None:
            found_part = _extract_part_from_title(title_lower)
            if found_part is not None and found_part != target_part:
                # Release explicitly declares a different part (e.g. Part 1 when watching Part 2)
                dropped_part_mismatch += 1
                continue

        # 3. Batch episode range check for multi-part anime
        if offset > 0:
            batch_start, batch_end = _extract_batch_range(title_lower)
            if batch_start is not None and batch_end is not None:
                found_part = _extract_part_from_title(title_lower)
                if found_part == target_part:
                    # Batch explicitly declared for this part, so verify ep_num
                    if not (batch_start <= ep_num <= batch_end):
                        dropped_batch_mismatch += 1
                        continue
                else:
                    # General/season/franchise batch, so verify global_ep
                    if not (batch_start <= global_ep <= batch_end):
                        dropped_batch_mismatch += 1
                        continue

        filtered.append(src)

    if dropped_chinese or dropped_part_mismatch or dropped_batch_mismatch:
        control.log(
            f"part_filter: Dropped {dropped_chinese} Chinese hardsubs, "
            f"{dropped_part_mismatch} part mismatches, {dropped_batch_mismatch} batch mismatches "
            f"(retained {len(filtered)}/{len(sources)} sources for mal_id={mal_id}, ep={ep_num})",
            'info'
        )

    return filtered
