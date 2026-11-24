# -*- coding: utf-8 -*-
from urllib.parse import unquote

from resources.lib.ui import control, database, multipage, utils
from resources.lib.ui.BrowserBase import BrowserBase
from resources.lib.ui.router import Route, multi_route

_MAL_OTAKU_APIS = frozenset(('mal', 'otaku'))

# search_<api>/ URL prefix, internal type id, (mal_pair, anilist_pair)
_SEARCH_ROUTE_META = (
    ('search_anime/', 'anime', ('', '')),
    ('search_tv_show/', 'tv_show', ('tv', 'TV')),
    ('search_movie/', 'movie', ('movie', 'MOVIE')),
    ('search_tv_short/', 'tv_short', ('tv_special', 'TV_SHORT')),
    ('search_special/', 'special', ('special', 'SPECIAL')),
    ('search_ova/', 'ova', ('ova', 'OVA')),
    ('search_ona/', 'ona', ('ona', 'ONA')),
    ('search_music/', 'music', ('music', 'MUSIC')),
)


def get_search_config():
    search_types = [row[0] for row in _SEARCH_ROUTE_META]
    types = {row[0]: row[1] for row in _SEARCH_ROUTE_META}
    mappings = {row[0]: row[2] for row in _SEARCH_ROUTE_META}
    formats = {'search_history_%s' % row[1]: row[1] for row in _SEARCH_ROUTE_META}
    return search_types, types, mappings, formats


_SEARCH_HISTORY_ROUTE_NAMES = tuple('search_history_%s' % row[1] for row in _SEARCH_ROUTE_META)
# Kodi router wildcard routes: ``search_anime/*`` matches URLs under ``search_anime/…``
_SEARCH_WILDCARD_ROUTES = tuple(row[0][:-1] + '/*' for row in _SEARCH_ROUTE_META)

_CLEAR_SEARCH_HISTORY_ROUTES = (
    'clear_search_history',
    'clear_search_history_anime',
    'clear_search_history_movie',
    'clear_search_history_tv_show',
    'clear_search_history_tv_short',
    'clear_search_history_special',
    'clear_search_history_ova',
    'clear_search_history_ona',
    'clear_search_history_music',
)
_CLEAR_SEARCH_HISTORY_MAP = {'clear_search_history': 'all'}
_CLEAR_SEARCH_HISTORY_MAP.update(
    {'clear_search_history_%s' % row[1]: row[1] for row in _SEARCH_ROUTE_META}
)


@multi_route(*_SEARCH_HISTORY_ROUTE_NAMES)
def SEARCH_HISTORY(payload, params):
    from resources.lib import Main
    _, _, _, formats = get_search_config()

    if Main.plugin_url in formats:
        format = formats[Main.plugin_url]
        control.setSetting('format', format)
    else:
        format = control.getSetting('format')

    history = database.getSearchHistory(format)
    view_type = 'addons' if control.getBool('interface.content_type') else ''
    if control.getInt('searchhistory') == 0:
        control.draw_items(utils.search_history(history, format), view_type)
    else:
        SEARCH(payload, params)


@Route('remove_search_item/*')
def REMOVE_SEARCH_ITEM(payload, params):
    search_types, types, _, _ = get_search_config()
    found = False
    for search_type in search_types:
        if payload.startswith(search_type):
            search_item = payload.split(search_type, 1)[1]
            if search_item:
                format = (params.get('format') if params else None) or types.get(search_type) or control.getSetting('format') or 'anime'
                decoded_item = unquote(search_item)
                database.remove_search(table=format, value=decoded_item)
                found = True
    if not found:
        control.notify(control.ADDON_NAME, "Failed to remove search item", time=3000)
    control.refresh()
    control.exit_code()


@Route('edit_search_item/*')
def EDIT_SEARCH_ITEM(payload, params):
    search_types, types, _, _ = get_search_config()
    found = False
    for search_type in search_types:
        if payload.startswith(search_type):
            search_item = payload.split(search_type, 1)[1]
            if search_item:
                format = (params.get('format') if params else None) or types.get(search_type) or control.getSetting('format') or 'anime'
                decoded_item = unquote(search_item)
                query = control.keyboard(control.lang(30018), decoded_item)
                if query and query != decoded_item:
                    database.remove_search(table=format, value=decoded_item)
                    database.addSearchHistory(query, format)
                found = True
    if not found:
        control.notify(control.ADDON_NAME, "Failed to edit search item", time=3000)
    control.refresh()
    control.exit_code()


def _extract_item_mal_id(item):
    if not isinstance(item, dict):
        return ''
    uids = ((item.get('info') or {}).get('UniqueIDs') or {}) if isinstance(item.get('info'), dict) else {}
    if isinstance(uids, dict) and uids.get('mal_id'):
        return str(uids['mal_id'])
    url = str(item.get('url') or '').strip('/')
    parts = url.split('/')
    if len(parts) >= 2 and parts[0] in ('animes', 'play_movie') and parts[1].isdigit():
        return parts[1]
    return ''


def _merge_offline_search_hits(items, query, media_format='', limit=15):
    """Merge unique offline mappings.db title/alias matches on page 1 before trailing pagination rows."""
    live_items = list(items or [])
    if not live_items:
        return utils.allocate_offline_mapping_items(
            database.search_mappings_by_title(query, limit=25, media_format=media_format)
        )
    offline_rows = database.search_mappings_by_title(query, limit=limit, media_format=media_format)
    if not offline_rows:
        return live_items

    body_items = []
    paging_items = []
    seen_ids = set()
    for it in live_items:
        if multipage.is_next_page_item(it):
            paging_items.append(it)
            continue
        body_items.append(it)
        mid = _extract_item_mal_id(it)
        if mid:
            seen_ids.add(mid)

    missing_rows = [r for r in offline_rows if r.get('mal_id') and str(r['mal_id']) not in seen_ids]
    if not missing_rows:
        return live_items
    body_items.extend(utils.allocate_offline_mapping_items(missing_rows))
    body_items.extend(paging_items)
    return body_items


@multi_route(*_SEARCH_WILDCARD_ROUTES)
def SEARCH(payload, params):
    from resources.lib import Main
    _, types, mappings, _ = get_search_config()

    type = None
    format = None

    for key in types:
        if Main.plugin_url.startswith(key):
            type = types[key]
            break

    for key in mappings:
        if Main.plugin_url.startswith(key):
            format = mappings[key][0] if control.getStr('browser.api') in _MAL_OTAKU_APIS else mappings[key][1]
            break

    query = unquote(payload) if payload else payload
    try:
        page = int(params.get('page', 1) or 1)
    except (ValueError, TypeError):
        page = 1
    if not query:
        query = control.keyboard(control.lang(30018))
        if not query:
            return control.draw_items([], 'tvshows')
        if control.getInt('searchhistory') == 0:
            database.addSearchHistory(query, type)
    prefix = Main.plugin_url.split('/', 1)[0]
    try:
        items = Main.BROWSER.get_search(query, page, format, prefix)
    except Exception:
        items = []
    if page == 1:
        items = _merge_offline_search_hits(items, query, format)
    control.draw_items(items, 'tvshows')
    control.schedule_next_page_prefetch(
        items,
        lambda q=query, p=page + 1, fmt=format, pr=prefix: Main.BROWSER.get_search(q, p, fmt, pr))


@Route('browse_year_season')
def BROWSE_YEAR_MENU(payload, params):
    """List release years backed by offline mappings.db index (0 HTTP calls)."""
    years = database.get_mapping_years(limit=75)
    view_type = 'addons' if control.getBool('interface.content_type') else ''
    items = [
        utils.allocate_item(
            f"{row['year']} ({row['count']})",
            f"browse_year/{row['year']}",
            True,
            False,
            [],
            'trending.png',
            {'plot': f"Browse {row['count']} offline catalog entries from {row['year']}"},
        )
        for row in years
    ]
    control.draw_items(items, view_type)


_BROWSE_YEAR_FMT_OPTIONS = (
    ('tv', 'TV Shows'),
    ('movie', 'Movies'),
    ('ova', 'OVAs'),
    ('ona', 'ONAs'),
    ('special', 'Specials'),
)
_BROWSE_YEAR_FMT_LABELS = dict(_BROWSE_YEAR_FMT_OPTIONS)


@Route('browse_year/*')
def BROWSE_YEAR_SEASON(payload, params):
    """Browse offline mappings.db catalog by release year, seasonal cour, and optional media format."""
    parts = [p for p in str(payload or '').strip('/').split('/') if p]
    if not parts or not parts[0].isdigit():
        control.draw_items([], 'tvshows')
        return
    year_int = int(parts[0])
    season_tok = parts[1].strip().upper() if len(parts) > 1 else ''
    media_fmt = str((params or {}).get('format', '') or '').strip().lower()
    if media_fmt not in _BROWSE_YEAR_FMT_LABELS:
        media_fmt = ''
    fmt_qs = f"?format={media_fmt}" if media_fmt else ""

    if not season_tok:
        summary = database.get_mapping_season_counts(year_int, media_format=media_fmt)
        total = summary.get('total', 0)
        all_total = summary.get('all_total', total)
        fmt_tag = f" {_BROWSE_YEAR_FMT_LABELS[media_fmt]}" if media_fmt else ""
        view_type = 'addons' if control.getBool('interface.content_type') else ''
        menu_items = [
            utils.allocate_item(
                f"All {year_int}{fmt_tag} Releases ({total})",
                f"browse_year/{year_int}/ALL{fmt_qs}",
                True,
                False,
                [],
                'trending.png',
                {'plot': f"All {total}{fmt_tag} catalog releases from {year_int} ordered by score"},
            )
        ]
        for seas_u, cnt in summary.get('seasons', []):
            menu_items.append(
                utils.allocate_item(
                    f"{seas_u.title()} {year_int}{fmt_tag} ({cnt})",
                    f"browse_year/{year_int}/{seas_u}{fmt_qs}",
                    True,
                    False,
                    [],
                    'airing_anime.png',
                    {'plot': f"{cnt}{fmt_tag} {seas_u.title()} {year_int} releases ordered by score"},
                )
            )
        if media_fmt:
            menu_items.append(
                utils.allocate_item(
                    f"[Show All Formats ({all_total})]",
                    f"browse_year/{year_int}",
                    True,
                    False,
                    [],
                    'genres_&_tags.png',
                    {'plot': f"Clear {_BROWSE_YEAR_FMT_LABELS[media_fmt]} filter for {year_int}"},
                )
            )
        for fk, flabel, fcnt in summary.get('formats', []):
            if fk == media_fmt:
                continue
            menu_items.append(
                utils.allocate_item(
                    f"[Format: {flabel} ({fcnt})]",
                    f"browse_year/{year_int}?format={fk}",
                    True,
                    False,
                    [],
                    'genres_&_tags.png',
                    {'plot': f"Filter {year_int} catalog to {flabel} only ({fcnt} entries)"},
                )
            )
        control.draw_items(menu_items, view_type)
        return

    try:
        page = max(1, int((params or {}).get('page', 1) or 1))
    except (ValueError, TypeError):
        page = 1
    rows, has_next = database.browse_mappings_by_year_season(
        year_int,
        anime_season='' if season_tok == 'ALL' else season_tok,
        media_format=media_fmt,
        page=page,
        per_page=40,
    )
    items = []
    if page == 1:
        if media_fmt:
            items.append(
                utils.allocate_item(
                    f"[COLOR skyblue][Clear Format: {_BROWSE_YEAR_FMT_LABELS[media_fmt]}][/COLOR]",
                    f"browse_year/{year_int}/{season_tok}",
                    True,
                    False,
                    [],
                    'genres_&_tags.png',
                    {'plot': f"Show all formats for {season_tok.title()} {year_int}"},
                )
            )
        elif rows:
            items.append(
                utils.allocate_item(
                    "[COLOR skyblue][Filter Format: All / TV / Movie / OVA / ONA...][/COLOR]",
                    f"browse_year_filter/{year_int}/{season_tok}",
                    False,
                    False,
                    [],
                    'genres_&_tags.png',
                    {'plot': f"Filter {season_tok.title()} {year_int} releases by format"},
                )
            )
    items.extend(utils.allocate_offline_mapping_items(rows))
    base_url = f"browse_year/{year_int}/{season_tok}" + fmt_qs
    items.extend(BrowserBase.handle_paging(has_next, base_url, page))
    control.draw_items(items, 'tvshows')


@Route('browse_year_filter/*')
def BROWSE_YEAR_FILTER(payload, params):
    """Open format picker for offline Year/Season browsing and update container."""
    parts = [p for p in str(payload or '').strip('/').split('/') if p]
    if not parts or not parts[0].isdigit():
        return
    year_int = int(parts[0])
    season_tok = parts[1].strip().upper() if len(parts) > 1 else 'ALL'
    options = ['All Formats'] + [label for _k, label in _BROWSE_YEAR_FMT_OPTIONS]
    choice = control.select_dialog(f"{control.ADDON_NAME}: Filter {season_tok.title()} {year_int}", options)
    if choice < 0:
        return
    target = f"browse_year/{year_int}/{season_tok}"
    if choice > 0:
        fmt_key = _BROWSE_YEAR_FMT_OPTIONS[choice - 1][0]
        target = f"{target}?format={fmt_key}"
    control.execute(f"Container.Update({control.addon_url(target)})")


@Route('search')
def SEARCH_MENU(payload, params):
    from resources.lib import Main
    SEARCH_ITEMS = Main.get_menu_items('search')

    view_type = 'addons' if control.getBool('interface.content_type') else ''
    control.draw_items([utils.allocate_item(name, url, True, False, [], image, info) for name, url, image, info in SEARCH_ITEMS], view_type)


@multi_route(*_CLEAR_SEARCH_HISTORY_ROUTES)
def CLEAR_SEARCH_HISTORY(payload, params):
    from resources.lib import Main
    clean_url = (Main.plugin_url or '').split('?')[0].rstrip('/')
    format = _CLEAR_SEARCH_HISTORY_MAP.get(clean_url, 'all')

    if format == 'all':
        database.clearSearchHistory()
    else:
        database.clearSearchCatagory(format)

    control.refresh()
