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

_RE_PART_OR_COUR = re.compile(r'\b(?:part|cour)\s*([0-9]+|[ivx]+)\b', re.IGNORECASE)
_RE_BATCH_RANGE = re.compile(r'[\(\[\s]([0-9]{1,4})\s*[-~–]\s*([0-9]{1,4})[\)\]\s]')
_EP_TITLE = re.compile(r'(?i)s\d{1,2}[ ._-]?e\d{1,4}[ ._-]+(.+)')
_TITLE_END = re.compile(
    r'(?i)[\[(]|\b(?:\d{3,4}p|4k|uhd|web|webrip|web-dl|bluray|bdrip|bd|hdtv|x26[45]|h\.?26[45]|'
    r'hevc|avc|av1|aac|ddp?|flac|multi|dual|repack|proper|amzn|cr|dsnp|nf|jc|10bit|subbed|dubbed)\b'
)
_SMALL_WORDS = {'the', 'and', 'for', 'part', 'episode', 'final'}
_SERIES_TYPES = ('TV', 'ONA', 'UNKNOWN', None)


def _flat(text):
    return re.sub(r'[^a-z0-9]', '', (text or '').lower())


def _is_part(row):
    return str(row.get('thetvdb_season')) != '0' and row.get('anime_media_type') in _SERIES_TYPES


def part_info(mal_id):
    """Return (this part's number, its flat subtitle name, flat names of sibling parts) from mappings.db."""
    if not mal_id:
        return None, '', []
    siblings = []
    title = ''
    try:
        from resources.lib.ui import database
        with database.SQL(control.mappingDB, is_readonly=True) as cur:
            cur.execute('SELECT mal_title, thetvdb_id FROM anime WHERE mal_id=?', (mal_id,))
            row = cur.fetchone()
            title = (row or {}).get('mal_title') or ''
            tvdb_id = (row or {}).get('thetvdb_id')
            by_id = {}
            if tvdb_id:
                cur.execute(
                    "SELECT mal_id, mal_title, thetvdb_season, anime_media_type FROM anime WHERE thetvdb_id=?",
                    (tvdb_id,)
                )
                for sr in cur.fetchall() or []:
                    if _is_part(sr) and sr.get('mal_id'):
                        by_id[sr['mal_id']] = sr
            base = title.split(' - ')[0]
            if base:
                cur.execute(
                    "SELECT mal_id, mal_title, thetvdb_season, anime_media_type FROM anime "
                    "WHERE mal_title=? OR mal_title LIKE ?",
                    (base, base + ' - %')
                )
                for sr in cur.fetchall() or []:
                    if _is_part(sr) and sr.get('mal_id'):
                        by_id[sr['mal_id']] = sr
            siblings = list(by_id.values())
    except Exception as e:
        control.log(f'part_filter: mappings part_info failed: {e}', 'debug')
        return None, '', []
    if not siblings:
        return None, '', []

    siblings.sort(key=lambda r: r['mal_id'])
    ids = [r['mal_id'] for r in siblings]
    try:
        mal_int = int(mal_id)
    except (ValueError, TypeError):
        mal_int = mal_id
    number = ids.index(mal_int) + 1 if mal_int in ids and len(ids) > 1 else None

    def _name(t):
        return _flat(t.split(' - ', 1)[1]) if ' - ' in (t or '') else ''

    own = _name(title)
    others = [
        n for n in (_name(r['mal_title']) for r in siblings if r['mal_id'] != mal_int)
        if len(n) >= 5 and n != own
    ]
    return number, own, others


def _words(text):
    return {w for w in re.findall(r'[a-z]{3,}', (text or '').lower()) if w not in _SMALL_WORDS}


def episode_title_words(mal_id, episode):
    """Return significant words of the episode's own title from Otaku's episode DB."""
    if not mal_id or episode is None:
        return set()
    try:
        from resources.lib.ui import database
        row = database.get_episode(mal_id, episode)
        meta = database.loads(row['kodi_meta']) if row and row.get('kodi_meta') else {}
        title = (meta.get('info') or {}).get('title') or meta.get('title') or ''
    except Exception:
        return set()
    if re.search(r'(?i)(?:^|\s)(?:episode|ep)\s*\d+\s*$', title):
        return set()
    return _words(title)


def release_episode_words(name):
    """Return significant words of the episode title a release names after S01E06.<Title>."""
    m = _EP_TITLE.search(name or '')
    if not m:
        return set()
    rest = re.sub(r'[._]', ' ', m.group(1))
    cut = _TITLE_END.search(rest)
    return _words(rest[:cut.start()] if cut else rest)


def part_queries(titles, episode, number):
    """Generate part-specific search queries for text providers (e.g. Easynews)."""
    ep = str(episode).zfill(2) if episode is not None else '01'
    out = []
    for t in (titles or []):
        clean = re.sub(r'\s+', ' ', (t or '').replace(':', ' ')).strip()
        if ' - ' in clean:
            series, part_name = clean.split(' - ', 1)
            show = t.split(':', 1)[0].strip() if ':' in t else series
            out.append(f'{show} {part_name} {ep}')
            if number:
                out.append(f'{series} Part {number} {ep}')
    return out


def _get_mappings_info(mal_id):
    """Query mappings.db for anime franchise metadata using connection pool."""
    if not mal_id:
        return None

    try:
        from resources.lib.ui import database
        mapping = database.get_mappings(int(mal_id), 'mal_id')
        if not mapping:
            return None

        return {
            'thetvdb_season': mapping.get('thetvdb_season'),
            'thetvdb_part': mapping.get('thetvdb_part'),
            'anime_media_episodes': mapping.get('anime_media_episodes') or '',
            'global_media_episodes': mapping.get('global_media_episodes') or '',
            'mal_title': mapping.get('mal_title') or ''
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
        from resources.lib.subtitles.languages import get_preferred_subtitle_language
        pref_code = get_preferred_subtitle_language()
        if pref_code in ('zh', 'chi', 'zho'):
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
    m = _RE_PART_OR_COUR.search(title_lower)
    if m:
        val = m.group(1).lower()
        return _ROMAN_PARTS.get(val)
    return None


def _extract_batch_range(title_lower):
    """Extract ascending batch episode range like (01-12), [01-24], etc."""
    m = _RE_BATCH_RANGE.search(title_lower)
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
    sib_number, own_part_name, other_part_names = part_info(mal_id) if mal_id else (None, '', [])
    own_ep_words = episode_title_words(mal_id, ep_num) if mal_id else set()

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

    if target_part is None and sib_number is not None:
        target_part = sib_number

    try:
        target_part = int(target_part) if target_part is not None else None
    except (ValueError, TypeError):
        target_part = None

    filtered = []
    dropped_chinese = 0
    dropped_part_mismatch = 0
    dropped_batch_mismatch = 0

    for src in sources:
        title = src.get('name') or src.get('release_title') or src.get('title') or ''
        title_lower = title.lower()
        flat_title = _flat(title_lower)

        # 1. Chinese Hardsub Filter
        if not allow_chinese and _has_chinese_hardsub(title_lower):
            dropped_chinese += 1
            continue

        # 2. Multi-Part Sibling Subtitle & Part Number Filter
        if other_part_names and any(o in flat_title for o in other_part_names) and not (own_part_name and own_part_name in flat_title):
            dropped_part_mismatch += 1
            continue

        if target_part is not None:
            found_part = _extract_part_from_title(title_lower)
            if found_part is not None and found_part != target_part:
                # Release explicitly declares a different part (e.g. Part 1 when watching Part 2)
                dropped_part_mismatch += 1
                continue

        # 2b. Episode title mismatch after SxxExx.<Title>
        if own_ep_words:
            rel_ep_words = release_episode_words(title)
            if rel_ep_words and not (rel_ep_words & own_ep_words):
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
