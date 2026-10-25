# -*- coding: utf-8 -*-
from urllib.parse import unquote

from resources.lib.ui import control, database, utils
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
    search_types, _, _, _ = get_search_config()
    format = control.getSetting('format')
    found = False
    for search_type in search_types:
        if payload.startswith(search_type):
            search_item = payload.split(search_type, 1)[1]
            if search_item:
                decoded_item = unquote(search_item)
                database.remove_search(table=format, value=decoded_item)
                found = True
    if not found:
        control.notify(control.ADDON_NAME, "Failed to remove search item", time=3000)
    control.exit_code()


@Route('edit_search_item/*')
def EDIT_SEARCH_ITEM(payload, params):
    search_types, _, _, _ = get_search_config()
    format = control.getSetting('format')
    found = False
    for search_type in search_types:
        if payload.startswith(search_type):
            search_item = payload.split(search_type, 1)[1]
            if search_item:
                decoded_item = unquote(search_item)
                query = control.keyboard(control.lang(30018), decoded_item)
                if query and query != decoded_item:
                    database.remove_search(table=format, value=decoded_item)
                    control.sleep(500)
                    database.addSearchHistory(query, format)
                found = True
    if not found:
        control.notify(control.ADDON_NAME, "Failed to edit search item", time=3000)
    control.refresh()
    control.exit_code()


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
    items = Main.BROWSER.get_search(query, page, format, prefix)
    control.draw_items(items, 'tvshows')
    control.schedule_next_page_prefetch(
        items,
        lambda q=query, p=page + 1, fmt=format, pr=prefix: Main.BROWSER.get_search(q, p, fmt, pr))


@Route('search')
def SEARCH_MENU(payload, params):
    from resources.lib import Main
    SEARCH_ITEMS = Main.get_menu_items('search')

    view_type = 'addons' if control.getBool('interface.content_type') else ''
    control.draw_items([utils.allocate_item(name, url, True, False, [], image, info) for name, url, image, info in SEARCH_ITEMS], view_type)


@multi_route(*_CLEAR_SEARCH_HISTORY_ROUTES)
def CLEAR_SEARCH_HISTORY(payload, params):
    from resources.lib import Main
    format = _CLEAR_SEARCH_HISTORY_MAP.get(Main.plugin_url)

    if format == 'all':
        database.clearSearchHistory()
    else:
        database.clearSearchCatagory(format)

    control.refresh()
