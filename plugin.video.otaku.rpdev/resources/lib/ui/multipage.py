# -*- coding: utf-8 -*-
"""multipage.py - Pure Multipage Sorting, Filtering & Windowing Engine
===================================================================
Stateless algorithms for multipage window management:
- Settings retrieval with defensive bounds clamping.
- Normalized sort key extraction (Date, Episode, Rating, Default).
- Token-based case-insensitive text filtering with BBCode tag stripping.
- Multi-page list deduplication and merging with 1,000 item ceiling.
- Stable multi-dimensional sorting with missing/unrated bottom-placement.
- Safe pagination slicing.
"""

import re
from resources.lib.ui import control


def strip_bbcode(text):
    """Strip Kodi formatting tags like [COLOR red]...[/COLOR], [B], [I]."""
    if not text:
        return ''
    return re.sub(
        r'\[/?(?:color\b[^\]]*|b|i|light|cr|uppercase|lowercase|capitalize)\]',
        '',
        str(text),
        flags=re.IGNORECASE
    )


def is_action_item(item):
    """True if item is a multipage control action ([Filter...], [Clear Filter])."""
    if not isinstance(item, dict):
        return False
    raw_name = str(item.get('name') or '').strip()
    name = strip_bbcode(raw_name).strip()
    url = str(item.get('url') or '')
    if name.startswith('[Filter') or name.startswith('[Clear') or raw_name.startswith('[Filter') or raw_name.startswith('[Clear'):
        return True
    if 'multipage_filter' in url or 'multipage_clear_filter' in url:
        return True
    if '30712' in name or '30713' in name:
        return True
    return False


def is_next_page_item(item):
    """True if item is a Next Page pagination row."""
    if not isinstance(item, dict):
        return False
    name = strip_bbcode(item.get('name') or '').strip().lower()
    if name.startswith('next page'):
        return True
    img = item.get('image')
    if isinstance(img, dict):
        icon = img.get('icon') or ''
    elif isinstance(img, str):
        icon = img
    else:
        icon = ''
    norm = icon.replace('\\', '/').lower()
    return norm.endswith('/next.png') or norm.endswith('next.png')


def extract_item_id(item):
    """Extract canonical unique identity for deduplication."""
    if not isinstance(item, dict):
        return None
    info = item.get('info') or {}
    unique_ids = info.get('UniqueIDs') or {}
    if isinstance(unique_ids, dict):
        for id_key in ('mal_id', 'anilist_id', 'kodi', 'imdb', 'tmdb'):
            val = unique_ids.get(id_key)
            if val is not None and str(val).strip():
                return (id_key, str(val).strip())
    url = item.get('url')
    if url:
        return ('url', str(url))
    name = item.get('name')
    if name:
        return ('name', str(name))
    return None


def get_multipage_settings():
    """Reads the 5 multipage settings via control.getInt() and control.getBool(),
    with safe defaults and bounds clamping.
    """
    precache_pages = control.getInt('multipage.precache.pages')
    if precache_pages < 1 or precache_pages > 20:
        precache_pages = 20

    sort_by = control.getInt('multipage.sort.by')
    if sort_by not in (0, 1, 2, 3):
        sort_by = 0

    sort_order = control.getInt('multipage.sort.order')
    if sort_order not in (0, 1):
        sort_order = 0

    display_mode = control.getInt('multipage.display.mode')
    if display_mode not in (0, 1):
        display_mode = 0

    show_filter_item = control.getBool('multipage.show.filter.item')
    if show_filter_item is None:
        show_filter_item = True

    return {
        'precache_pages': precache_pages,
        'sort_by': sort_by,
        'sort_order': sort_order,
        'display_mode': display_mode,
        'show_filter_item': show_filter_item,
    }


def extract_sort_key(item, sort_by):
    """Extract normalized sort key from item dictionary based on sort_by mode.

    Modes:
        0 = Default (returns 0)
        1 = Date (normalized YYYY-MM-DD or year string, '' on missing)
        2 = Episode (integer total episode count, 0 on missing)
        3 = Rating (float score, 0.0 on missing)
    """
    if not isinstance(item, dict):
        return 0 if sort_by == 0 else ('' if sort_by == 1 else (0 if sort_by == 2 else 0.0))

    if sort_by == 0:
        return 0

    info = item.get('info') or {}

    if sort_by == 1:
        # Date
        raw_date = (
            info.get('premiered') or info.get('aired') or info.get('year') or
            item.get('premiered') or item.get('aired') or item.get('year')
        )
        if not raw_date:
            return ''
        if isinstance(raw_date, int):
            return str(raw_date) if raw_date > 0 else ''
        date_str = str(raw_date).strip().replace('/', '-')
        m = re.match(r'(\d{4}(?:-\d{2}(?:-\d{2})?)?)', date_str)
        return m.group(1) if m else (date_str if any(c.isdigit() for c in date_str) else '')

    elif sort_by == 2:
        # Episode
        raw_ep = (
            info.get('episode') or info.get('episodes') or info.get('total_episodes') or
            item.get('episode') or item.get('episodes')
        )
        if raw_ep is None:
            return 0
        try:
            ep_val = int(raw_ep)
            return ep_val if ep_val > 0 else 0
        except (ValueError, TypeError):
            m = re.search(r'\d+', str(raw_ep))
            return int(m.group()) if m else 0

    elif sort_by == 3:
        # Rating
        raw_rating = (
            info.get('rating') or info.get('score') or info.get('averageScore') or
            item.get('rating') or item.get('score')
        )
        if isinstance(raw_rating, dict):
            raw_rating = raw_rating.get('score') or raw_rating.get('rating') or raw_rating.get('average')
        if raw_rating is None:
            return 0.0
        try:
            score = float(raw_rating)
            return score if score > 0.0 else 0.0
        except (ValueError, TypeError):
            m = re.search(r'\d+(?:\.\d+)?', str(raw_rating))
            return float(m.group()) if m else 0.0

    return 0


def filter_window_by_text(items, query):
    """Case-insensitive token-based matching across name, title, and plot.

    Strips BBCode tags for clean matching.
    Preserves control/action items ([Filter...], [Clear Filter]).
    Discards pagination rows when query is present.
    """
    if not items:
        return []
    if not query or not str(query).strip():
        return list(items)

    tokens = str(query).strip().lower().split()
    matched = []
    for item in items:
        if is_action_item(item):
            matched.append(item)
            continue
        if is_next_page_item(item):
            continue

        info = item.get('info') or {}
        name = strip_bbcode(item.get('name') or '')
        title = strip_bbcode(info.get('title') or '')
        plot = strip_bbcode(info.get('plot') or '')
        searchable = f"{name} {title} {plot}".lower()

        if all(token in searchable for token in tokens):
            matched.append(item)

    return matched


def merge_window(existing_items, new_items, max_items=1000):
    """Merges new items into existing list, deduplicating by ID,
    stripping intermediate Next Page rows, and capping at max_items.
    """
    existing_items = existing_items or []
    new_items = new_items or []

    seen_ids = set()
    merged = []
    content_count = 0

    # Process existing items (strip any Next Page row)
    for it in existing_items:
        if is_next_page_item(it):
            continue
        if is_action_item(it):
            merged.append(it)
            continue
        item_id = extract_item_id(it)
        if item_id:
            seen_ids.add(item_id)
        merged.append(it)
        content_count += 1
        if content_count >= max_items:
            break

    # Process new items if capacity remains
    tail_next_page = None
    if content_count < max_items:
        for it in new_items:
            if is_next_page_item(it):
                tail_next_page = it
                continue
            if is_action_item(it):
                continue
            item_id = extract_item_id(it)
            if item_id and item_id in seen_ids:
                continue
            if item_id:
                seen_ids.add(item_id)
            merged.append(it)
            content_count += 1
            if content_count >= max_items:
                tail_next_page = None
                break
    else:
        tail_next_page = None

    if tail_next_page and content_count < max_items:
        merged.append(tail_next_page)

    return merged


def sort_window(items, sort_by, sort_order):
    """Sorts content items preserving header action buttons and footer pagination.

    In both Ascending and Descending modes, zero/missing values (e.g. unrated anime
    or missing release dates) sort to the bottom.
    """
    if not items or sort_by == 0:
        return list(items or [])

    headers = []
    footers = []
    content = []

    for it in items:
        if is_action_item(it):
            headers.append(it)
        elif is_next_page_item(it):
            footers.append(it)
        else:
            content.append(it)

    valid = []
    missing = []

    for it in content:
        val = extract_sort_key(it, sort_by)
        is_missing = False
        if sort_by == 1:
            # Date: missing if empty string
            is_missing = not val or str(val).strip() == '' or str(val).strip() == '0'
        elif sort_by == 2:
            # Episode: missing if <= 0
            is_missing = not val or val <= 0
        elif sort_by == 3:
            # Rating: missing if <= 0.0
            is_missing = not val or float(val) <= 0.0

        if is_missing:
            missing.append(it)
        else:
            valid.append((val, it))

    if sort_order == 0:
        # Descending (highest values first)
        valid.sort(key=lambda x: x[0], reverse=True)
    else:
        # Ascending (lowest values first)
        valid.sort(key=lambda x: x[0], reverse=False)

    sorted_content = [x[1] for x in valid] + missing
    return headers + sorted_content + footers


def slice_page(items, page=1, per_page=20):
    """Safe list pagination slicing."""
    if not items:
        return []
    try:
        p = int(page)
    except (ValueError, TypeError):
        p = 1
    if p < 1:
        p = 1

    try:
        pp = int(per_page)
    except (ValueError, TypeError):
        pp = 20
    if pp < 1:
        pp = 20

    start = (p - 1) * pp
    if start >= len(items):
        return []
    end = start + pp
    return items[start:end]
