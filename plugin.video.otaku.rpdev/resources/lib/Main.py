# -*- coding: utf-8 -*-
"""
    Otaku Add-on

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

    Core menu registry, anime browser/genre dispatch, and modular route re-exports.
"""

import json
import sys
import random

from resources.lib import MetaBrowser
from resources.lib.ui import control, database, utils
from resources.lib.ui.router import Route, multi_route
from resources.lib.WatchlistIntegration import add_watchlist

BROWSER = MetaBrowser.BROWSER
plugin_url = control.get_plugin_url(sys.argv[0])

# --- Browser list routes (mal/otaku vs AniList format codes) ------------------
_MAL_OTAKU_APIS = frozenset(('mal', 'otaku'))

_BROWSER_ROUTE_SUFFIXES = ('tv_show', 'movie', 'tv_short', 'special', 'ova', 'ona', 'music')

_FORMAT_PAIR_BY_SUFFIX = {
    'tv_show': ('tv', 'TV'),
    'movie': ('movie', 'MOVIE'),
    'tv_short': ('tv_special', 'TV_SHORT'),
    'special': ('special', 'SPECIAL'),
    'ova': ('ova', 'OVA'),
    'ona': ('ona', 'ONA'),
    'music': ('music', 'MUSIC'),
}


def _browser_list_route_paths(prefix):
    return (prefix,) + tuple('%s_%s' % (prefix, s) for s in _BROWSER_ROUTE_SUFFIXES)


def _wildcard_browser_paths(prefix):
    """Paths like ``marked_as_watched/*``, ``marked_as_watched_tv_show/*``, …"""
    return tuple('%s/*' % p for p in _browser_list_route_paths(prefix))


_GENRES_WILDCARD_PREFIXES = (
    'genres', 'genres_tv_show', 'genres_movie', 'genres_tv_short',
    'genres_special', 'genres_ova', 'genres_ona', 'genres_music',
)


def _suffix_route_mapping(route_prefix):
    return {
        '%s_%s' % (route_prefix, suf): _FORMAT_PAIR_BY_SUFFIX[suf]
        for suf in _BROWSER_ROUTE_SUFFIXES
    }


def _resolve_browser_format(route_prefix):
    base_key = plugin_url.split('?', 1)[0]
    pair = _suffix_route_mapping(route_prefix).get(base_key)
    if not pair:
        return None
    return pair[0] if control.getStr('browser.api') in _MAL_OTAKU_APIS else pair[1]


def _draw_browser_page(browser_method, route_prefix, params):
    page = int(params.get('page', 1))
    fmt = _resolve_browser_format(route_prefix)
    prefix = plugin_url.split('?', 1)[0]
    method = getattr(BROWSER, browser_method)
    items = method(page, fmt, prefix)
    control.draw_items(items, 'tvshows')
    control.schedule_next_page_prefetch(
        items,
        lambda p=page + 1, f=fmt, pr=prefix, m=method: m(p, f, pr))


def _draw_genre_page(route_prefix, params):
    _draw_browser_page('get_genre_' + route_prefix[6:], route_prefix, params)


# --- Menu route definitions (compact tables: labels, paths, artwork) ----------
_CATEGORY_SUFFIX = {
    'movies': '_movie',
    'tv_shows': '_tv_show',
    'tv_shorts': '_tv_short',
    'specials': '_special',
    'ovas': '_ova',
    'onas': '_ona',
    'music': '_music',
}

_CATEGORY_ROWS = (
    (30002, 'airing_last_season', 'airing_anime.png'),
    (30003, 'airing_this_season', 'airing_anime.png'),
    (30004, 'airing_next_season', 'airing_anime.png'),
    (30012, 'trending', 'trending.png'),
    (30013, 'popular', 'popular.png'),
    (30014, 'voted', 'voted.png'),
    (30015, 'favourites', 'favourites.png'),
    (30016, 'top_100', 'top_100_anime.png'),
    (30017, 'genres', 'genres_&_tags.png'),
    (30018, 'search_history', 'search.png'),
)


def _category_format_menu(suffix):
    rows = []
    for lid, stem, icon in _CATEGORY_ROWS:
        rows.append((control.lang(lid), '%s%s' % (stem, suffix), icon, {}))
    return rows


def _stem_menu(stems, suffix, icon):
    out = []
    for lid, path_stem in stems:
        out.append((control.lang(lid), '%s%s' % (path_stem, suffix), icon, {}))
    return out


_TRENDING_STEMS = (
    (30020, 'trending_last_year'),
    (30021, 'trending_this_year'),
    (30022, 'trending_last_season'),
    (30023, 'trending_this_season'),
    (30024, 'all_time_trending'),
)

_POPULAR_STEMS = (
    (30025, 'popular_last_year'),
    (30026, 'popular_this_year'),
    (30027, 'popular_last_season'),
    (30028, 'popular_this_season'),
    (30029, 'all_time_popular'),
)

_VOTED_STEMS = (
    (30030, 'voted_last_year'),
    (30031, 'voted_this_year'),
    (30032, 'voted_last_season'),
    (30033, 'voted_this_season'),
    (30034, 'all_time_voted'),
)

_FAV_STEMS = (
    (30035, 'favourites_last_year'),
    (30036, 'favourites_this_year'),
    (30037, 'favourites_last_season'),
    (30038, 'favourites_this_season'),
    (30039, 'all_time_favourites'),
)

_FORMAT_SUFFIXES = (
    ('', ''),
    ('_movie', '_movie'),
    ('_tv_show', '_tv_show'),
    ('_tv_short', '_tv_short'),
    ('_special', '_special'),
    ('_ova', '_ova'),
    ('_ona', '_ona'),
    ('_music', '_music'),
)


def _genre_menu(menu_key, suffix):
    rows = [(control.lang(30040), '%s//' % menu_key, 'genre_multi.png', {})]
    for lid, stem, icon in _GENRE_ROWS:
        rows.append((control.lang(lid), '%s%s' % (stem, suffix), icon, {}))
    return rows


_GENRE_ROWS = (
    (30041, 'genre_action', 'genre_action.png'),
    (30042, 'genre_adventure', 'genre_adventure.png'),
    (30043, 'genre_comedy', 'genre_comedy.png'),
    (30044, 'genre_drama', 'genre_drama.png'),
    (30045, 'genre_ecchi', 'genre_ecchi.png'),
    (30046, 'genre_fantasy', 'genre_fantasy.png'),
    (30047, 'genre_hentai', 'genre_hentai.png'),
    (30048, 'genre_horror', 'genre_horror.png'),
    (30049, 'genre_shoujo', 'genre_shoujo.png'),
    (30050, 'genre_mecha', 'genre_mecha.png'),
    (30051, 'genre_music', 'genre_music.png'),
    (30052, 'genre_mystery', 'genre_mystery.png'),
    (30053, 'genre_psychological', 'genre_psychological.png'),
    (30054, 'genre_romance', 'genre_romance.png'),
    (30055, 'genre_sci_fi', 'genre_sci-fi.png'),
    (30056, 'genre_slice_of_life', 'genre_slice_of_life.png'),
    (30057, 'genre_sports', 'genre_sports.png'),
    (30058, 'genre_supernatural', 'genre_supernatural.png'),
    (30059, 'genre_thriller', 'genre_thriller.png'),
)

_GENRE_MENU_KEYS = (
    ('genres', ''),
    ('genres_movie', '_movie'),
    ('genres_tv_show', '_tv_show'),
    ('genres_tv_short', '_tv_short'),
    ('genres_special', '_special'),
    ('genres_ova', '_ova'),
    ('genres_ona', '_ona'),
    ('genres_music', '_music'),
)


def _main_menu():
    return [
        (control.lang(30001), "airing_calendar", 'airing_anime_calendar.png', {}),
        (control.lang(30002), "airing_last_season", 'airing_anime.png', {}),
        (control.lang(30003), "airing_this_season", 'airing_anime.png', {}),
        (control.lang(30004), "airing_next_season", 'airing_anime.png', {}),
        (control.lang(30005), "movies", 'movies.png', {}),
        (control.lang(30006), "tv_shows", 'tv_shows.png', {}),
        (control.lang(30007), "tv_shorts", 'tv_shorts.png', {}),
        (control.lang(30008), "specials", 'specials.png', {}),
        (control.lang(30009), "ovas", 'ovas.png', {}),
        (control.lang(30010), "onas", 'onas.png', {}),
        (control.lang(30011), "music", 'music.png', {}),
        (control.lang(30012), "trending", 'trending.png', {}),
        (control.lang(30013), "popular", 'popular.png', {}),
        (control.lang(30014), "voted", 'voted.png', {}),
        (control.lang(30015), "favourites", 'favourites.png', {}),
        (control.lang(30016), "top_100", 'top_100_anime.png', {}),
        (control.lang(30017), "genres", 'genres_&_tags.png', {}),
        (control.lang(30018), "search", 'search.png', {}),
        (control.lang(30019), "tools", 'tools.png', {}),
    ]


def _search_menu():
    kinds = ('anime', 'movie', 'tv_show', 'tv_short', 'special', 'ova', 'ona', 'music')
    lids = range(30060, 30068)
    return [(control.lang(lid), 'search_history_%s' % k, 'search.png', {}) for lid, k in zip(lids, kinds)]


def _tools_menu():
    tools = (
        (30069, 'setup_wizard', 'tools.png'),
        (30070, 'change_log', 'changelog.png'),
        (30071, 'settings', 'open_settings_menu.png'),
        (30072, 'clear_cache', 'clear_cache.png'),
        (30073, 'clear_search_history', 'clear_search_history.png'),
        (30074, 'clear_watch_history', 'clear_watch_history.png'),
        (30075, 'rebuild_database', 'rebuild_database.png'),
        (30076, 'wipe_addon_data', 'wipe_addon_data.png'),
        (30077, 'completed_sync', 'sync_completed.png'),
        (30078, 'download_manager', 'download_manager.png'),
        (30555, 'my_cloud', 'tools.png'),
        (30079, 'sort_select', 'sort_select.png'),
        (30080, 'clear_selected_fanart', 'wipe_addon_data.png'),
    )
    return [(control.lang(lid), path, icon, {}) for lid, path, icon in tools]


def _build_menu_registry():
    reg = {'main': _main_menu, 'search': _search_menu, 'tools': _tools_menu}

    for mk, suf in _CATEGORY_SUFFIX.items():
        reg[mk] = (lambda s=suf: _category_format_menu(s))

    for key_part, suf in _FORMAT_SUFFIXES:
        reg['trending%s' % key_part] = (
            lambda s=suf: _stem_menu(_TRENDING_STEMS, s, 'trending.png')
        )
        reg['popular%s' % key_part] = (
            lambda s=suf: _stem_menu(_POPULAR_STEMS, s, 'popular.png')
        )
        reg['voted%s' % key_part] = (
            lambda s=suf: _stem_menu(_VOTED_STEMS, s, 'voted.png')
        )
        reg['favourites%s' % key_part] = (
            lambda s=suf: _stem_menu(_FAV_STEMS, s, 'favourites.png')
        )

    for mkey, gsuf in _GENRE_MENU_KEYS:
        reg[mkey] = (lambda k=mkey, g=gsuf: _genre_menu(k, g))

    return reg


_MENU_REGISTRY = None


def get_menu_items(menu_type):
    global _MENU_REGISTRY
    if _MENU_REGISTRY is None:
        _MENU_REGISTRY = _build_menu_registry()
    builder = _MENU_REGISTRY.get(menu_type)
    return builder() if builder else []


def add_next_up(items):
    """Add Next Up menu item if enabled in watchlist settings."""
    if control.getBool('watchlist.update.enabled') and control.getBool('nextup.enabled'):
        items.append((control.lang(30451), "next_up", 'next_up.png', {}))
    return items


def draw_anime_reviews_listing(mal_id, page, path, eps_watched):
    """Build reviews listing via BROWSER (Jikan on mal/otaku, AniList on anilist)."""
    result = BROWSER.get_reviews_page(str(mal_id), int(page), path, eps_watched)
    if result is None:
        control.notify(control.ADDON_NAME, control.lang(30461))
        control.draw_items([], 'addons')
        return
    reviews = result.get('reviews') or []
    if not reviews:
        control.notify(control.ADDON_NAME, control.lang(30461))
        control.draw_items([], 'addons')
        return
    control.setGlobalProp('otaku.reviews.cache', json.dumps(reviews))
    control.setGlobalProp('otaku.reviews.mal_id', str(mal_id))
    control.setGlobalProp('otaku.reviews.page', str(page))
    items = result.get('items') or []
    control.draw_items(items, 'addons')
    next_p = int(page) + 1
    control.schedule_next_page_prefetch(
        items,
        lambda mid=str(mal_id), p=next_p, pt=path, ew=eps_watched: BROWSER.get_reviews_page(mid, p, pt, ew))


def open_anime_statistics(mal_id):
    data = BROWSER.get_statistics_payload(str(mal_id))
    if not data:
        control.notify(control.ADDON_NAME, control.lang(30463))
        return
    from resources.lib.windows.stats_window import StatsWindow
    window = StatsWindow('anime_statistics.xml', control.ADDON_PATH, stats=data, heading='[B]Anime Statistics[/B]')
    window.run()


@Route('animes/*')
def ANIMES_PAGE(payload, params):
    parts = [p for p in payload.strip('/').split('/') if p]
    mal_id = parts[0] if parts else ''
    anime_general, content = MetaBrowser.get_anime_init(mal_id)
    control.draw_items(anime_general, content)


def _extract_mal_id(payload):
    parts = [p for p in payload.strip('/').split('/') if p]
    if not parts:
        return ''
    if parts[0].isdigit():
        return parts[0]
    if len(parts) >= 2 and parts[1].isdigit():
        return parts[1]
    for p in parts:
        if p.isdigit():
            return p
    return parts[-1]


@Route('find_recommendations/*')
def FIND_RECOMMENDATIONS(payload, params):
    mal_id = _extract_mal_id(payload)
    page = int(params.get('page', 1))
    items = BROWSER.get_recommendations(mal_id, page)
    control.draw_items(items, 'tvshows')
    control.schedule_next_page_prefetch(
        items,
        lambda mid=mal_id, p=page + 1: BROWSER.get_recommendations(mid, p))


@Route('find_relations/*')
def FIND_RELATIONS(payload, params):
    mal_id = _extract_mal_id(payload)
    control.draw_items(BROWSER.get_relations(mal_id), 'tvshows')


@Route('watch_order/*')
def WATCH_ORDER(payload, params):
    mal_id = _extract_mal_id(payload)
    control.draw_items(BROWSER.get_watch_order(mal_id), 'tvshows')


@Route('anime_reviews/*')
def ANIME_REVIEWS(payload, params):
    parts = payload.strip('/').split('/')
    if len(parts) >= 3:
        path, mal_id, eps_watched = parts[-3], parts[-2], parts[-1]
    elif len(parts) == 2:
        path, mal_id = parts
        eps_watched = '0'
    else:
        control.notify(control.ADDON_NAME, control.lang(30461))
        control.draw_items([], 'addons')
        return
    page = int(params.get('page', 1))
    draw_anime_reviews_listing(mal_id, page, path, eps_watched)


@Route('view_review/*')
def VIEW_REVIEW(payload, params):
    parts = payload.strip('/').split('/')
    mal_id = parts[0]
    review_idx = int(parts[1])
    cached = control.getGlobalProp('otaku.reviews.cache')
    if not cached:
        page = int(control.getGlobalProp('otaku.reviews.page') or 1)
        reviews = BROWSER.refetch_reviews_page(mal_id, page)
        if reviews is None or not reviews:
            control.notify(control.ADDON_NAME, control.lang(30461))
            return
    else:
        reviews = json.loads(cached)
    if review_idx >= len(reviews):
        control.notify(control.ADDON_NAME, control.lang(30461))
        return
    review = reviews[review_idx]
    user = review.get('user', {})
    username = user.get('username', 'Anonymous')
    sraw = review.get('score', '?')
    score_show = sraw if (isinstance(sraw, str) and '/' in sraw) else f'{sraw}/10'
    tags = review.get('tags', [])
    tag_str = tags[0] if tags else ''
    date = (review.get('date') or '')[:10]
    is_preliminary = review.get('is_preliminary', False)
    is_spoiler = review.get('is_spoiler', False)
    reactions = review.get('reactions') or {}
    flags = []
    if is_preliminary:
        flags.append('Preliminary')
    if is_spoiler:
        flags.append('Spoiler')
    flag_str = f"  |  [{', '.join(flags)}]" if flags else ''
    header = f"By: {username}  |  Score: {score_show}  |  {tag_str}  |  {date}{flag_str}"
    reaction_line = f"Reactions - Nice: {reactions.get('nice', 0)} | Love it: {reactions.get('love_it', 0)} | Funny: {reactions.get('funny', 0)} | Informative: {reactions.get('informative', 0)} | Well Written: {reactions.get('well_written', 0)} | Creative: {reactions.get('creative', 0)}"
    separator = '-' * 60
    body = review.get('review', 'No review text available.')
    full_text = f"{header}\n{reaction_line}\n{separator}\n\n{body}"
    control.textviewer_dialog(f"Review by {username}", full_text)


@Route('anime_statistics/*')
def ANIME_STATISTICS(payload, params):
    mal_id = _extract_mal_id(payload)
    if not mal_id:
        control.notify(control.ADDON_NAME, control.lang(30463))
        return
    open_anime_statistics(mal_id)


@Route('airing_calendar')
def AIRING_CALENDAR(payload: str, params: dict):
    from resources.lib.AnimeSchedule import AnimeScheduleCalendar
    scheduler = AnimeScheduleCalendar()
    calendar_data = scheduler.get_calendar_data(types=['sub', 'dub', 'raw'])

    if calendar_data:
        formatted_calendar = scheduler.format_for_anichart(calendar_data)
        from resources.lib.windows.anichart import Anichart
        Anichart('anichart.xml', control.ADDON_PATH, calendar=formatted_calendar).doModal()
    else:
        control.notify(control.ADDON_NAME, 'Unable to load Airing Calendar data')
    control.exit_code()


@multi_route(*_browser_list_route_paths('airing_last_season'))
def AIRING_LAST_SEASON(payload, params):
    _draw_browser_page('get_airing_last_season', 'airing_last_season', params)


@multi_route(*_browser_list_route_paths('airing_this_season'))
def AIRING_THIS_SEASON(payload, params):
    _draw_browser_page('get_airing_this_season', 'airing_this_season', params)


@multi_route(*_browser_list_route_paths('airing_next_season'))
def AIRING_NEXT_SEASON(payload, params):
    _draw_browser_page('get_airing_next_season', 'airing_next_season', params)


@multi_route(*_browser_list_route_paths('trending_last_year'))
def TRENDING_LAST_YEAR(payload, params):
    _draw_browser_page('get_trending_last_year', 'trending_last_year', params)


@multi_route(*_browser_list_route_paths('trending_this_year'))
def TRENDING_THIS_YEAR(payload, params):
    _draw_browser_page('get_trending_this_year', 'trending_this_year', params)


@multi_route(*_browser_list_route_paths('trending_last_season'))
def TRENDING_LAST_SEASON(payload, params):
    _draw_browser_page('get_trending_last_season', 'trending_last_season', params)


@multi_route(*_browser_list_route_paths('trending_this_season'))
def TRENDING_THIS_SEASON(payload, params):
    _draw_browser_page('get_trending_this_season', 'trending_this_season', params)


@multi_route(*_browser_list_route_paths('all_time_trending'))
def ALL_TIME_TRENDING(payload, params):
    _draw_browser_page('get_all_time_trending', 'all_time_trending', params)


@multi_route(*_browser_list_route_paths('popular_last_year'))
def POPULAR_LAST_YEAR(payload, params):
    _draw_browser_page('get_popular_last_year', 'popular_last_year', params)


@multi_route(*_browser_list_route_paths('popular_this_year'))
def POPULAR_THIS_YEAR(payload, params):
    _draw_browser_page('get_popular_this_year', 'popular_this_year', params)


@multi_route(*_browser_list_route_paths('popular_last_season'))
def POPULAR_LAST_SEASON(payload, params):
    _draw_browser_page('get_popular_last_season', 'popular_last_season', params)


@multi_route(*_browser_list_route_paths('popular_this_season'))
def POPULAR_THIS_SEASON(payload, params):
    _draw_browser_page('get_popular_this_season', 'popular_this_season', params)


@multi_route(*_browser_list_route_paths('all_time_popular'))
def ALL_TIME_POPULAR(payload, params):
    _draw_browser_page('get_all_time_popular', 'all_time_popular', params)


@multi_route(*_browser_list_route_paths('voted_last_year'))
def VOTED_LAST_YEAR(payload, params):
    _draw_browser_page('get_voted_last_year', 'voted_last_year', params)


@multi_route(*_browser_list_route_paths('voted_this_year'))
def VOTED_THIS_YEAR(payload, params):
    _draw_browser_page('get_voted_this_year', 'voted_this_year', params)


@multi_route(*_browser_list_route_paths('voted_last_season'))
def VOTED_LAST_SEASON(payload, params):
    _draw_browser_page('get_voted_last_season', 'voted_last_season', params)


@multi_route(*_browser_list_route_paths('voted_this_season'))
def VOTED_THIS_SEASON(payload, params):
    _draw_browser_page('get_voted_this_season', 'voted_this_season', params)


@multi_route(*_browser_list_route_paths('all_time_voted'))
def ALL_TIME_VOTED(payload, params):
    _draw_browser_page('get_all_time_voted', 'all_time_voted', params)


@multi_route(*_browser_list_route_paths('favourites_last_year'))
def FAVOURITES_LAST_YEAR(payload, params):
    _draw_browser_page('get_favourites_last_year', 'favourites_last_year', params)


@multi_route(*_browser_list_route_paths('favourites_this_year'))
def FAVOURITES_THIS_YEAR(payload, params):
    _draw_browser_page('get_favourites_this_year', 'favourites_this_year', params)


@multi_route(*_browser_list_route_paths('favourites_last_season'))
def FAVOURITES_LAST_SEASON(payload, params):
    _draw_browser_page('get_favourites_last_season', 'favourites_last_season', params)


@multi_route(*_browser_list_route_paths('favourites_this_season'))
def FAVOURITES_THIS_SEASON(payload, params):
    _draw_browser_page('get_favourites_this_season', 'favourites_this_season', params)


@multi_route(*_browser_list_route_paths('all_time_favourites'))
def ALL_TIME_FAVOURITES(payload, params):
    _draw_browser_page('get_all_time_favourites', 'all_time_favourites', params)


@multi_route(*_browser_list_route_paths('top_100'))
def TOP_100(payload, params):
    _draw_browser_page('get_top_100', 'top_100', params)


@multi_route(*[p + '/*' for p in _GENRES_WILDCARD_PREFIXES])
def GENRES(payload, params):
    mapping = {
        'genres_tv_show//': ('tv', 'TV'),
        'genres_movie//': ('movie', 'MOVIE'),
        'genres_tv_short//': ('tv_special', 'TV_SHORT'),
        'genres_special//': ('special', 'SPECIAL'),
        'genres_ova//': ('ova', 'OVA'),
        'genres_ona//': ('ona', 'ONA'),
        'genres_music//': ('music', 'MUSIC')
    }
    parts = [p for p in payload.strip('/').split('/') if p]
    genres = parts[0] if parts else ''
    tags = parts[1] if len(parts) > 1 else ''
    page = int(params.get('page', 1))
    format = None
    base_key = plugin_url.split('/', 1)[0] + '//'
    if base_key in mapping:
        format = mapping[base_key][0] if control.getStr('browser.api') in _MAL_OTAKU_APIS else mapping[base_key][1]
    if genres or tags:
        prefix = plugin_url.split('/', 1)[0]
        items = BROWSER.genres_payload(genres, tags, page, format, prefix)
        control.draw_items(items, 'tvshows')
        control.schedule_next_page_prefetch(
            items,
            lambda g=genres, t=tags, p=page + 1, fmt=format, pr=prefix: BROWSER.genres_payload(g, t, p, fmt, pr))
    else:
        items = BROWSER.get_genres(page, format)
        control.draw_items(items, 'tvshows')
        control.schedule_next_page_prefetch(
            items,
            lambda p=page + 1, fmt=format: BROWSER.get_genres(p, fmt))


@Route('update_genre_settings')
def UPDATE_GENRE_SETTINGS(payload, params):
    try:
        selected_genres_mal, selected_genres_anilist, selected_tags = BROWSER.update_genre_settings()
    except ValueError:
        return  # Break the code if ValueError occurs

    settings = {
        'selected_genres_mal': selected_genres_mal,
        'selected_genres_anilist': selected_genres_anilist,
        'selected_tags': selected_tags
    }

    with open(control.genre_json, 'w') as f:
        json.dump(settings, f)


@multi_route(*_browser_list_route_paths('genre_action'))
def GENRE_ACTION(payload, params):
    _draw_genre_page('genre_action', params)


@multi_route(*_browser_list_route_paths('genre_adventure'))
def GENRE_ADVENTURE(payload, params):
    _draw_genre_page('genre_adventure', params)


@multi_route(*_browser_list_route_paths('genre_comedy'))
def GENRE_COMEDY(payload, params):
    _draw_genre_page('genre_comedy', params)


@multi_route(*_browser_list_route_paths('genre_drama'))
def GENRE_DRAMA(payload, params):
    _draw_genre_page('genre_drama', params)


@multi_route(*_browser_list_route_paths('genre_ecchi'))
def GENRE_ECCHI(payload, params):
    _draw_genre_page('genre_ecchi', params)


@multi_route(*_browser_list_route_paths('genre_fantasy'))
def GENRE_FANTASY(payload, params):
    _draw_genre_page('genre_fantasy', params)


@multi_route(*_browser_list_route_paths('genre_hentai'))
def GENRE_HENTAI(payload, params):
    _draw_genre_page('genre_hentai', params)


@multi_route(*_browser_list_route_paths('genre_horror'))
def GENRE_HORROR(payload, params):
    _draw_genre_page('genre_horror', params)


@multi_route(*_browser_list_route_paths('genre_shoujo'))
def GENRE_SHOUJO(payload, params):
    _draw_genre_page('genre_shoujo', params)


@multi_route(*_browser_list_route_paths('genre_mecha'))
def GENRE_MECHA(payload, params):
    _draw_genre_page('genre_mecha', params)


@multi_route(*_browser_list_route_paths('genre_music'))
def GENRE_MUSIC(payload, params):
    _draw_genre_page('genre_music', params)


@multi_route(*_browser_list_route_paths('genre_mystery'))
def GENRE_MYSTERY(payload, params):
    _draw_genre_page('genre_mystery', params)


@multi_route(*_browser_list_route_paths('genre_psychological'))
def GENRE_PSYCHOLOGICAL(payload, params):
    _draw_genre_page('genre_psychological', params)


@multi_route(*_browser_list_route_paths('genre_romance'))
def GENRE_ROMANCE(payload, params):
    _draw_genre_page('genre_romance', params)


@multi_route(*_browser_list_route_paths('genre_sci_fi'))
def GENRE_SCI_FI(payload, params):
    _draw_genre_page('genre_sci_fi', params)


@multi_route(*_browser_list_route_paths('genre_slice_of_life'))
def GENRE_SLICE_OF_LIFE(payload, params):
    _draw_genre_page('genre_slice_of_life', params)


@multi_route(*_browser_list_route_paths('genre_sports'))
def GENRE_SPORTS(payload, params):
    _draw_genre_page('genre_sports', params)


@multi_route(*_browser_list_route_paths('genre_supernatural'))
def GENRE_SUPERNATURAL(payload, params):
    _draw_genre_page('genre_supernatural', params)


@multi_route(*_browser_list_route_paths('genre_thriller'))
def GENRE_THRILLER(payload, params):
    _draw_genre_page('genre_thriller', params)


def _maybe_refresh_main_menu(log_msg):
    if control.getGlobalProp('otaku.menu.needs_refresh') == 'true':
        control.clearGlobalProp('otaku.menu.needs_refresh')
        control.log(log_msg)


def _collect_category_menu_items(menu_items_key, settings_key, extra_key_suffix):
    enabled_items = []
    enabled_items = add_watchlist(enabled_items)
    enabled_ids = control.getStringList(settings_key)
    if "last_watched%s" % extra_key_suffix in enabled_ids:
        enabled_items = add_last_watched(enabled_items)
    if "watch_history%s" % extra_key_suffix in enabled_ids:
        enabled_items = add_watch_history(enabled_items)
    if "next_up%s" % extra_key_suffix in enabled_ids:
        enabled_items = add_next_up(enabled_items)
    if "my_cloud%s" % extra_key_suffix in enabled_ids or (menu_items_key == 'main' and control.getBool('interface.menu.my_cloud', default=True) and "my_cloud" not in enabled_ids):
        enabled_items = add_my_cloud(enabled_items)
    for item in get_menu_items(menu_items_key):
        if item[1] in enabled_ids:
            enabled_items.append(item)
    seen = set()
    unique_items = []
    for itm in enabled_items:
        key = itm[2] if (len(itm) == 6 and itm[0] == 'LAST_WATCHED_ITEM') else itm[1]
        if key not in seen:
            seen.add(key)
            unique_items.append(itm)
    return unique_items


def _finalize_menu_list_items(menu_items):
    processed = []
    for item in menu_items:
        if len(item) == 6 and item[0] == 'LAST_WATCHED_ITEM':
            _, name, url, image, info, kodi_meta = item
            mal_id = info.get('UniqueIDs', {}).get('mal_id') or ''
            episodes = kodi_meta.get('episodes', 0)
            last_ep = kodi_meta.get('last_watched_episode')

            cm = []
            if episodes == 1:
                cm.append(('Play Movie', f'PlayMedia(plugin://{control.ADDON_ID}/play_movie/{mal_id}/)'))
            else:
                target_ep = last_ep if last_ep else 1
                next_ep = (last_ep + 1) if (last_ep is not None and (not episodes or last_ep < episodes)) else (last_ep or 1)
                cm.append((f'Play Next Episode ({next_ep})', f'PlayMedia(plugin://{control.ADDON_ID}/play/{mal_id}/{next_ep})'))
                if last_ep:
                    cm.append((f'Resume Episode ({target_ep})', f'PlayMedia(plugin://{control.ADDON_ID}/play/{mal_id}/{target_ep})'))
                cm.append(('Browse Episodes', f'ActivateWindow(Videos,plugin://{control.ADDON_ID}/animes/{mal_id}/)'))
            cm.append(('Clear Last Watched', f'RunPlugin(plugin://{control.ADDON_ID}/clear_last_watched)'))

            base = {
                'name': name,
                'url': url,
                'image': image,
                'poster': image,
                'fanart': kodi_meta.get('fanart', ''),
                'banner': image,
                'info': info
            }
            if kodi_meta.get('thumb'):
                thumb = kodi_meta['thumb']
                base['landscape'] = random.choice(thumb) if isinstance(thumb, list) else thumb
            if kodi_meta.get('clearart'):
                clearart = kodi_meta['clearart']
                base['clearart'] = random.choice(clearart) if isinstance(clearart, list) else clearart
            if kodi_meta.get('clearlogo'):
                clearlogo = kodi_meta['clearlogo']
                base['clearlogo'] = random.choice(clearlogo) if isinstance(clearlogo, list) else clearlogo
            click_action = control.getInt('interface.watchhistory.click')
            is_folder = episodes != 1 and click_action == 0
            is_playable = episodes == 1 or click_action in (1, 2)
            processed.append(utils.allocate_item(
                base['name'], base['url'], is_folder, is_playable, cm,
                base['image'], base['info'],
                fanart=base.get('fanart'),
                poster=base.get('poster'),
                landscape=base.get('landscape'),
                banner=base.get('banner'),
                clearart=base.get('clearart'),
                clearlogo=base.get('clearlogo')
            ))
        elif len(item) == 5:
            name, url, image, info, art = item
            fanart = art.get('fanart', '') if isinstance(art, dict) else ''
            poster = art.get('poster', '') if isinstance(art, dict) else ''
            landscape = art.get('landscape', '') if isinstance(art, dict) else ''
            banner = art.get('banner', '') if isinstance(art, dict) else ''
            clearart = art.get('clearart', '') if isinstance(art, dict) else ''
            clearlogo = art.get('clearlogo', '') if isinstance(art, dict) else ''
            processed.append(utils.allocate_item(name, url, True, False, [], image, info, fanart=fanart, poster=poster, landscape=landscape, banner=banner, clearart=clearart, clearlogo=clearlogo))
        else:
            name, url, image, info = item
            processed.append(utils.allocate_item(name, url, True, False, [], image, info))
    return processed


def _draw_category_main_menu(menu_items_key, settings_key, extra_key_suffix, refresh_log_msg):
    _maybe_refresh_main_menu(refresh_log_msg)
    enabled = _collect_category_menu_items(menu_items_key, settings_key, extra_key_suffix)
    processed = _finalize_menu_list_items(enabled)
    view_type = 'addons' if control.getBool('interface.content_type') else ''
    control.draw_items(processed, view_type)


def _draw_filtered_submenu(menu_items_key, settings_key):
    items = get_menu_items(menu_items_key)
    enabled_ids = control.getStringList(settings_key)
    enabled = [item for item in items if item[1] in enabled_ids]
    view_type = 'addons' if control.getBool('interface.content_type') else ''
    control.draw_items(
        [utils.allocate_item(name, url, True, False, [], image, info) for name, url, image, info in enabled],
        view_type,
    )


# --- UI route registration (main menu + filtered submenus) --------------------
# (url route, handler __name__, menu key, settings id, last_watched suffix, refresh log message)
_CATEGORY_MAIN_MENU_ROUTES = (
    ('', 'LIST_MENU', 'main', 'menu.mainmenu.config', '', 'Menu refresh flag detected - rebuilding menu items'),
    ('movies', 'MOVIES_MENU', 'movies', 'movie.mainmenu.config', '_movie', 'Movie menu refresh flag detected - rebuilding menu items'),
    ('tv_shows', 'TV_SHOWS_MENU', 'tv_shows', 'tv_show.mainmenu.config', '_tv_show', 'TV shows menu refresh flag detected - rebuilding menu items'),
    ('tv_shorts', 'TV_SHORTS_MENU', 'tv_shorts', 'tv_short.mainmenu.config', '_tv_short', 'TV shorts menu refresh flag detected - rebuilding menu items'),
    ('specials', 'SPECIALS_MENU', 'specials', 'special.mainmenu.config', '_special', 'Specials menu refresh flag detected - rebuilding menu items'),
    ('ovas', 'OVAS_MENU', 'ovas', 'ova.mainmenu.config', '_ova', 'OVAs menu refresh flag detected - rebuilding menu items'),
    ('onas', 'ONAS_MENU', 'onas', 'ona.mainmenu.config', '_ona', 'ONAs menu refresh flag detected - rebuilding menu items'),
    ('music', 'MUSIC_MENU', 'music', 'music.mainmenu.config', '_music', 'Music menu refresh flag detected - rebuilding menu items'),
)

_FILTERED_SUBMENU_ROUTES = (
    ('trending', 'TRENDING_MENU', 'trending', 'menu.submenu.config'),
    ('trending_movie', 'TRENDING_MOVIE_MENU', 'trending_movie', 'movie.submenu.config'),
    ('trending_tv_show', 'TRENDING_TV_SHOW_MENU', 'trending_tv_show', 'tv_show.submenu.config'),
    ('trending_tv_short', 'TRENDING_TV_SHORT_MENU', 'trending_tv_short', 'tv_short.submenu.config'),
    ('trending_special', 'TRENDING_SPECIAL_MENU', 'trending_special', 'special.submenu.config'),
    ('trending_ova', 'TRENDING_OVA_MENU', 'trending_ova', 'ova.submenu.config'),
    ('trending_ona', 'TRENDING_ONA_MENU', 'trending_ona', 'ona.submenu.config'),
    ('trending_music', 'TRENDING_MUSIC_MENU', 'trending_music', 'music.submenu.config'),
    ('popular', 'POPULAR_MENU', 'popular', 'menu.submenu.config'),
    ('popular_movie', 'POPULAR_MOVIE_MENU', 'popular_movie', 'movie.submenu.config'),
    ('popular_tv_show', 'POPULAR_TV_SHOW_MENU', 'popular_tv_show', 'tv_show.submenu.config'),
    ('popular_tv_short', 'POPULAR_TV_SHORT_MENU', 'popular_tv_short', 'tv_short.submenu.config'),
    ('popular_special', 'POPULAR_SPECIAL_MENU', 'popular_special', 'special.submenu.config'),
    ('popular_ova', 'POPULAR_OVA_MENU', 'popular_ova', 'ova.submenu.config'),
    ('popular_ona', 'POPULAR_ONA_MENU', 'popular_ona', 'ona.submenu.config'),
    ('popular_music', 'POPULAR_MUSIC_MENU', 'popular_music', 'music.submenu.config'),
    ('voted', 'VOTED_MENU', 'voted', 'menu.submenu.config'),
    ('voted_movie', 'VOTED_MOVIE_MENU', 'voted_movie', 'movie.submenu.config'),
    ('voted_tv_show', 'VOTED_TV_SHOW_MENU', 'voted_tv_show', 'tv_show.submenu.config'),
    ('voted_tv_short', 'VOTED_TV_SHORT_MENU', 'voted_tv_short', 'tv_short.submenu.config'),
    ('voted_special', 'VOTED_SPECIAL_MENU', 'voted_special', 'special.submenu.config'),
    ('voted_ova', 'VOTED_OVA_MENU', 'voted_ova', 'ova.submenu.config'),
    ('voted_ona', 'VOTED_ONA_MENU', 'voted_ona', 'ona.submenu.config'),
    ('voted_music', 'VOTED_MUSIC_MENU', 'voted_music', 'music.submenu.config'),
    ('favourites', 'FAVOURITES_MENU', 'favourites', 'menu.submenu.config'),
    ('favourites_movie', 'FAVOURITES_MOVIE_MENU', 'favourites_movie', 'movie.submenu.config'),
    ('favourites_tv_show', 'FAVOURITES_TV_SHOW_MENU', 'favourites_tv_show', 'tv_show.submenu.config'),
    ('favourites_tv_short', 'FAVOURITES_TV_SHORT_MENU', 'favourites_tv_short', 'tv_short.submenu.config'),
    ('favourites_special', 'FAVOURITES_SPECIAL_MENU', 'favourites_special', 'special.submenu.config'),
    ('favourites_ova', 'FAVOURITES_OVA_MENU', 'favourites_ova', 'ova.submenu.config'),
    ('favourites_ona', 'FAVOURITES_ONA_MENU', 'favourites_ona', 'ona.submenu.config'),
    ('favourites_music', 'FAVOURITES_MUSIC_MENU', 'favourites_music', 'music.submenu.config'),
    ('genres', 'GENRES_MENU', 'genres', 'menu.genres.config'),
    ('genres_movie', 'GENRE_MOVIE_MENU', 'genres_movie', 'movie.genres.config'),
    ('genres_tv_show', 'GENRE_TV_SHOW_MENU', 'genres_tv_show', 'tv_show.genres.config'),
    ('genres_tv_short', 'GENRE_TV_SHORT_MENU', 'genres_tv_short', 'tv_short.genres.config'),
    ('genres_special', 'GENRE_SPECIAL_MENU', 'genres_special', 'special.genres.config'),
    ('genres_ova', 'GENRE_OVA_MENU', 'genres_ova', 'ova.genres.config'),
    ('genres_ona', 'GENRE_ONA_MENU', 'genres_ona', 'ona.genres.config'),
    ('genres_music', 'GENRE_MUSIC_MENU', 'genres_music', 'music.genres.config'),
)


def _register_ui_menu_routes():
    """Wire LIST_MENU / submenus; exposes Main.LIST_MENU etc. for compatibility."""
    mod = sys.modules[__name__]
    for route, fname, mkey, cfg, suf, log in _CATEGORY_MAIN_MENU_ROUTES:
        def cat_handler(payload, params, mk=mkey, sk=cfg, sx=suf, lg=log):
            _draw_category_main_menu(mk, sk, sx, lg)
        cat_handler.__name__ = fname
        cat_handler.__qualname__ = fname
        setattr(mod, fname, cat_handler)
        Route(route)(cat_handler)

    for route, fname, mkey, cfg in _FILTERED_SUBMENU_ROUTES:
        def sub_handler(payload, params, mk=mkey, sk=cfg):
            _draw_filtered_submenu(mk, sk)
        sub_handler.__name__ = fname
        sub_handler.__qualname__ = fname
        setattr(mod, fname, sub_handler)
        Route(route)(sub_handler)


_register_ui_menu_routes()

# --- Re-export domain route modules for single-import-surface compatibility ---
from resources.lib.routes.cloud import *  # noqa: F401,F403,E402
from resources.lib.routes.cloud import _draw_cloud_directory  # noqa: F401,E402
from resources.lib.routes.history import *  # noqa: F401,F403,E402
from resources.lib.routes.playback import *  # noqa: F401,F403,E402
from resources.lib.routes.search import *  # noqa: F401,F403,E402
from resources.lib.routes.search import (  # noqa: F401,E402
    _SEARCH_ROUTE_META,
    _SEARCH_HISTORY_ROUTE_NAMES,
    _SEARCH_WILDCARD_ROUTES,
    _CLEAR_SEARCH_HISTORY_ROUTES,
    _CLEAR_SEARCH_HISTORY_MAP,
)
from resources.lib.routes.tools import *  # noqa: F401,F403,E402
from resources.lib.routes.tools import (  # noqa: F401,E402
    _get_advancedsettings_status,
    _update_network_status,
)
