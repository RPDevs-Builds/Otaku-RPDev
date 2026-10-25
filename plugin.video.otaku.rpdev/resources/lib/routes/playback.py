# -*- coding: utf-8 -*-
import ast
import json
import re
import time

from resources.lib import MetaBrowser
from resources.lib.routes.history import save_to_watch_history
from resources.lib.ui import control, database, utils
from resources.lib.ui.router import Route, multi_route

_BROWSER_ROUTE_SUFFIXES = ('tv_show', 'movie', 'tv_short', 'special', 'ova', 'ona', 'music')


def _browser_list_route_paths(prefix):
    return (prefix,) + tuple('%s_%s' % (prefix, s) for s in _BROWSER_ROUTE_SUFFIXES)


def _wildcard_browser_paths(prefix):
    """Paths like ``marked_as_watched/*``, ``marked_as_watched_tv_show/*``, …"""
    return tuple('%s/*' % p for p in _browser_list_route_paths(prefix))


@Route('play/*')
def PLAY(payload, params):
    parts = [p for p in payload.strip('/').split('/') if p]
    mal_id = parts[0] if parts else ''
    episode = parts[1] if len(parts) > 1 else '1'
    source_select = bool(params.get('source_select'))
    rescrape = bool(params.get('rescrape'))
    last_played = control.getSetting('last_played_source')
    last_watched = control.getSetting('last_watched_series')
    resume = params.get('resume')
    if rating := params.get('rating'):
        params['rating'] = ast.literal_eval(rating)
    params['path'] = f"{control.addon_url(f'play/{payload}')}"

    # Populate params with episode metadata from database if not already present
    # This ensures metadata is available even when playing from Information dialog
    if not params.get('tvshowtitle'):
        episode_data = database.get_episode(mal_id, episode)
        if not episode_data:
            MetaBrowser.get_anime_init(mal_id)
            episode_data = database.get_episode(mal_id, episode)
        if episode_data:
            params = database.loads(episode_data['kodi_meta'])
        else:
            # Fallback: build minimal params from show database
            # This ensures metadata is available even for episodes not yet indexed
            show_meta = database.get_show(mal_id)
            if show_meta:
                kodi_meta = database.loads(show_meta['kodi_meta'])
                show_art = database.get_show_meta(mal_id)
                art = database.loads(show_art['art']) if show_art and show_art.get('art') else {}
                params = {
                    'info': {
                        'title': f"{kodi_meta.get('title_userPreferred', '')} - Episode {episode}",
                        'tvshowtitle': kodi_meta.get('title_userPreferred', ''),
                        'episode': int(episode),
                        'plot': kodi_meta.get('plot', ''),
                        'mediatype': 'episode',
                        'UniqueIDs': {'mal_id': str(mal_id), **database.get_unique_ids(mal_id, 'mal_id')},
                    },
                    'image': {
                        'poster': art.get('poster') or kodi_meta.get('poster', ''),
                        'fanart': art.get('fanart', ''),
                        'icon': art.get('poster') or kodi_meta.get('poster', ''),
                        'thumb': art.get('thumb', ''),
                    },
                    'path': params.get('path', ''),
                }

    if resume:
        resume = float(resume)
        context = control.context_menu([f'Resume from {utils.format_time(resume)}', 'Play from beginning'])
        if context == -1:
            return control.exit_code()
        elif context == 1:
            resume = None

    # Guard against premature scraping of unaired episodes
    episode_info = params.get('info', {})
    aired_str = episode_info.get('aired')
    if aired_str and not rescrape and not source_select:
        try:
            from datetime import date
            aired_date = date.fromisoformat(aired_str[:10])
            today = date.today()
            if aired_date > today:
                diff_days = (aired_date - today).days
                day_str = "tomorrow" if diff_days == 1 else f"in {diff_days} days ({aired_date.strftime('%a, %b %d')})"
                confirmed = control.yesno_dialog(
                    control.ADDON_NAME,
                    f"Episode {episode} is not scheduled to air until {day_str}.\n\nSearch for early releases or raw leaks anyway?"
                )
                if not confirmed:
                    return control.exit_code()
        except Exception:
            pass

    sources = MetaBrowser.get_sources(mal_id, episode, 'show', rescrape, source_select)
    if sources:
        _mock_args = {"mal_id": mal_id, "episode": episode, 'play': True, 'resume': resume, 'context': rescrape or source_select, 'params': params}

        # SmartPlay Enabled
        if control.getBool('general.smartplay'):
            # Check if the same series is already being watched
            if last_watched == mal_id:
                # If the same series is being watched, check if the last played source is available
                if last_played == "None" or source_select or rescrape:
                    from resources.lib.windows.source_select import SourceSelect
                    if control.getInt('general.dialog') in (5, 6):
                        SourceSelect('source_select_alt.xml', control.ADDON_PATH, actionArgs=_mock_args, sources=sources, rescrape=rescrape).doModal()
                    else:
                        SourceSelect('source_select.xml', control.ADDON_PATH, actionArgs=_mock_args, sources=sources, rescrape=rescrape).doModal()
                else:
                    # If the last played source is available, resolve it directly
                    from resources.lib.windows.resolver import Resolver
                    if control.getInt('general.dialog') in (5, 6):
                        Resolver('resolver_alt.xml', control.ADDON_PATH, actionArgs=_mock_args).doModal(sources, {}, False)
                    else:
                        Resolver('resolver.xml', control.ADDON_PATH, actionArgs=_mock_args).doModal(sources, {}, False)
            else:
                # If a different series is being watched, prompt for source selection and update last watched Series
                control.setSetting('last_watched_series', mal_id)
                from resources.lib.windows.source_select import SourceSelect
                if control.getInt('general.dialog') in (5, 6):
                    SourceSelect('source_select_alt.xml', control.ADDON_PATH, actionArgs=_mock_args, sources=sources, rescrape=rescrape).doModal()
                else:
                    SourceSelect('source_select.xml', control.ADDON_PATH, actionArgs=_mock_args, sources=sources, rescrape=rescrape).doModal()
        # SmartPlay Disabled
        else:
            if control.getInt('general.playstyle.episode') == 1 or source_select or rescrape:
                from resources.lib.windows.source_select import SourceSelect
                if control.getInt('general.dialog') in (5, 6):
                    SourceSelect('source_select_alt.xml', control.ADDON_PATH, actionArgs=_mock_args, sources=sources, rescrape=rescrape).doModal()
                else:
                    SourceSelect('source_select.xml', control.ADDON_PATH, actionArgs=_mock_args, sources=sources, rescrape=rescrape).doModal()
            else:
                from resources.lib.windows.resolver import Resolver
                if control.getInt('general.dialog') in (5, 6):
                    Resolver('resolver_alt.xml', control.ADDON_PATH, actionArgs=_mock_args).doModal(sources, {}, False)
                else:
                    Resolver('resolver.xml', control.ADDON_PATH, actionArgs=_mock_args).doModal(sources, {}, False)
    else:
        control.playList.clear()
    control.exit_code()


@Route('play_movie/*')
def PLAY_MOVIE(payload, params):
    parts = [p for p in payload.strip('/').split('/') if p]
    mal_id = parts[0] if parts else ''
    eps_watched = parts[1] if len(parts) > 1 else '0'
    source_select = bool(params.get('source_select'))
    rescrape = bool(params.get('rescrape'))
    resume = params.get('resume')
    params['path'] = f"{control.addon_url(f'play_movie/{payload}')}"

    # Populate params with movie metadata from database if not already present
    # This ensures metadata is available even when playing from Information dialog
    if not params.get('name'):
        from resources.lib.OtakuBrowser import OtakuBrowser
        OtakuBrowser().get_anime_data(mal_id)
        anime_meta = database.get_show_meta(mal_id)
        anime_data = database.get_show(mal_id)
        kodi_meta = database.loads(anime_data['kodi_meta'])

        params = {
            **kodi_meta,
            'info': kodi_meta,  # video info tags
            'image': {  # art fields for UI
                k: (v[0] if isinstance(v, list) else v)
                for k, v in database.loads(anime_meta['art']).items()
            }
        }

    if resume:
        resume = float(resume)
        context = control.context_menu([f'Resume from {utils.format_time(resume)}', 'Play from beginning'])
        if context == -1:
            return
        elif context == 1:
            resume = None

    sources = MetaBrowser.get_sources(mal_id, 1, 'movie', rescrape, source_select)
    if sources:
        _mock_args = {'mal_id': mal_id, 'play': True, 'resume': resume, 'context': rescrape or source_select, 'params': params}
        if control.getInt('general.playstyle.movie') == 1 or source_select or rescrape:
            from resources.lib.windows.source_select import SourceSelect
            if control.getInt('general.dialog') in (5, 6):
                SourceSelect('source_select_alt.xml', control.ADDON_PATH, actionArgs=_mock_args, sources=sources, rescrape=rescrape).doModal()
            else:
                SourceSelect('source_select.xml', control.ADDON_PATH, actionArgs=_mock_args, sources=sources, rescrape=rescrape).doModal()
        else:
            from resources.lib.windows.resolver import Resolver
            if control.getInt('general.dialog') in (5, 6):
                Resolver('resolver_alt.xml', control.ADDON_PATH, actionArgs=_mock_args).doModal(sources, {}, False)
            else:
                Resolver('resolver.xml', control.ADDON_PATH, actionArgs=_mock_args).doModal(sources, {}, False)
    else:
        control.playList.clear()
    control.exit_code()


@Route('tmdb_helper')
def TMDB_HELPER(payload, params):
    # --- Extract all relevant parameters from params and actionArgs ---
    from resources.lib.OtakuBrowser import OtakuBrowser
    from resources.lib.endpoints import tmdb

    action_args = params.pop('actionArgs', {})
    if isinstance(action_args, str):
        action_args = ast.literal_eval(action_args)
    # Now it's safe to use .get
    item_type = action_args.get('item_type')

    # Extract parameters from action_args
    item_type = action_args.get('item_type')
    tmdb_id = action_args.get('tmdb_id')
    tvdb_id = action_args.get('tvdb_id')
    imdb_id = action_args.get('imdb_id')
    trakt_id = action_args.get('trakt_id')
    season = action_args.get('season')
    episode = action_args.get('episode')

    # Extract source_select from params (default to False)
    source_select = params.pop('source_select', 'false') == 'true'
    params.update({'source_select': source_select})

    # Convert season and episode to int if present
    season_number = int(season) if season is not None else None
    episode_number = int(episode) if episode is not None else None

    # Grab Playstyle settings
    smartplay = control.getBool('general.smartplay')
    playstyle_movie = control.getInt('general.playstyle.movie')
    playstyle_episode = control.getInt('general.playstyle.episode')

    # Disable SmartPlay temporarily
    if smartplay:
        control.setBool('general.smartplay', False)

    # Parms cleanup
    parms = {}

    # Now all parameters are available: item_type, tmdb_id, title_url, season_number, episode_number, source_select
    control.log("Item Type: " + str(item_type))
    control.log("TMDB ID: " + str(tmdb_id))
    control.log("TVDB ID: " + str(tvdb_id))
    control.log("IMDB ID: " + str(imdb_id))
    control.log("Trakt ID: " + str(trakt_id))
    control.log("Season Number: " + str(season_number))
    control.log("Episode Number: " + str(episode_number))
    control.log("Source Select: " + str(source_select))

    if item_type == 'movie':
        mal_id = None
        id_sources = [
            ('themoviedb_id', tmdb_id),
            ('thetvdb_id', tvdb_id),
            ('imdb_id', imdb_id),
            ('trakt_id', trakt_id)
        ]

        for key, value in id_sources:
            if value:
                anime_ids = database.get_mappings(value, key)
                if anime_ids and anime_ids.get('mal_id'):
                    mal_id = anime_ids['mal_id']
                    break

        if mal_id:
            OtakuBrowser().get_anime_data(mal_id)

            if source_select:
                control.setInt('general.playstyle.movie', 1)
            else:
                control.setInt('general.playstyle.movie', 0)

            PLAY_MOVIE(f"{mal_id}/", parms)
            control.sleep(3000)
            control.setInt('general.playstyle.movie', playstyle_movie)
            control.setBool('general.smartplay', smartplay)
            return
        else:
            control.sleep(3000)
            control.setInt('general.playstyle.movie', playstyle_movie)
            control.setBool('general.smartplay', smartplay)
            control.notify(control.ADDON_NAME, 'No MAL ID found from this movie')
            return

    else:
        mal_ids = set()
        id_sources = [
            ('themoviedb_id', tmdb_id),
            ('thetvdb_id', tvdb_id),
            ('imdb_id', imdb_id),
            ('trakt_id', trakt_id)
        ]

        for key, value in id_sources:
            if value:
                mappings = database.get_mal_ids(value, key)  # Now returns a list
                for anime_ids in mappings:
                    if anime_ids and 'mal_id' in anime_ids and anime_ids['mal_id']:
                        if isinstance(anime_ids['mal_id'], list):
                            mal_ids.update(anime_ids['mal_id'])
                        else:
                            mal_ids.add(anime_ids['mal_id'])

        if mal_ids:
            episode_titles = tmdb.get_episode_titles(tmdb_id, season_number, episode_number)
            match = find_episode_by_title(mal_ids, episode_titles)
            if match:
                mal_id = match['mal_id']
                episode_num = match['episode_number']
                matched_title = match['matched_title']
                control.log(f"Matched MAL ID: {mal_id} for Episode {episode_num} titled '{matched_title}'")
                OtakuBrowser().get_anime_data(mal_id)
                MetaBrowser.get_anime_init(mal_id)

                if source_select:
                    control.setInt('general.playstyle.episode', 1)
                else:
                    control.setInt('general.playstyle.episode', 0)

                PLAY(f"{mal_id}/{episode_num}", parms)
                control.sleep(3000)
                control.setInt('general.playstyle.episode', playstyle_episode)
                control.setBool('general.smartplay', smartplay)
                return
            else:
                control.sleep(3000)
                control.setInt('general.playstyle.episode', playstyle_episode)
                control.setBool('general.smartplay', smartplay)
                control.notify(control.ADDON_NAME, 'No MAL ID found from this episode')
                return


def remove_punctuation(s):
    return re.sub(r'[^\w\s]', '', s)


def find_episode_by_title(mal_ids, episode_titles):
    from resources.lib.indexers.jikanmoe import JikanAPI
    from resources.lib.ui.source_utils import get_fuzzy_match, clean_text
    # Split titles on '|' and clean each part
    split_titles = []
    for t in episode_titles:
        if t:
            split_titles.extend([x.strip() for x in t.split('|') if x.strip()])
    # Use shared clean_text for normalization (removes punctuation, preserves spaces)
    cleaned_titles = [clean_text(t) for t in split_titles]
    jikan_api = JikanAPI()
    requests_made = 0
    last_request_time = time.time()
    for mal_id in mal_ids:
        # Rate limit: max 3 requests every 4 seconds, space each request by at least 1.33 seconds
        if requests_made == 3:
            elapsed = time.time() - last_request_time
            if elapsed < 4.0:
                time.sleep(4.0 - elapsed)
            requests_made = 0
            last_request_time = time.time()
        # Space each request by at least 1.33 seconds
        if requests_made > 0:
            time.sleep(1.33)
        # Retry logic for HTTP 429
        retries = 0
        max_retries = 3
        backoff = 2
        while retries <= max_retries:
            try:
                episodes = jikan_api.get_episode_meta(mal_id)
                requests_made += 1
                break
            except Exception as e:
                if hasattr(e, 'response') and getattr(e.response, 'status_code', None) == 429:
                    control.log(f"Jikan API rate limited (429) for mal_id {mal_id}, retrying in {backoff} seconds...")
                    time.sleep(backoff)
                    retries += 1
                    backoff *= 2
                else:
                    control.log(f"Jikan API error for mal_id {mal_id}: {e}")
                    episodes = []
                    break
        else:
            control.log(f"Jikan API failed for mal_id {mal_id} after {max_retries} retries.")
            episodes = []
        # Prepare candidate episode titles from Jikan
        episode_candidates = []
        episode_meta_map = []
        for ep in episodes:
            candidates = [
                ep.get('title', ''),
                ep.get('title_romanji', '')
            ]
            for candidate in candidates:
                if candidate:
                    episode_candidates.append(candidate)
                    episode_meta_map.append((candidate, ep))
        # Use shared clean_text for normalization
        cleaned_candidates = [clean_text(c) for c in episode_candidates]
        # Run fuzzy matching for each cleaned title variant individually
        best_idx = None
        for cleaned_query in cleaned_titles:
            match_indices = get_fuzzy_match(cleaned_query, cleaned_candidates)
            if match_indices:
                # get_fuzzy_match returns sorted indices by best match first
                idx = match_indices[0]
                if best_idx is None or idx < best_idx:
                    best_idx = idx
        if best_idx is not None:
            best_candidate, best_ep = episode_meta_map[best_idx]
            control.log(f"FUZZY MATCH FOUND: Jikan '{best_candidate}' matched TMDB title (fuzzy).")
            info = {
                'mal_id': mal_id,
                'episode_number': best_ep.get('mal_id'),
                'matched_title': best_candidate,
            }
            return info
        else:
            # Fallback to direct match if fuzzy fails
            for idx, candidate in enumerate(cleaned_candidates):
                if candidate in cleaned_titles:
                    orig_candidate, ep = episode_meta_map[idx]
                    control.log(f"DIRECT MATCH FOUND: Jikan '{orig_candidate}' matched TMDB title.")
                    info = {
                        'mal_id': mal_id,
                        'episode_number': ep.get('mal_id'),
                        'matched_title': orig_candidate,
                    }
                    return info
            control.log("No fuzzy or direct match for Jikan episode titles against TMDB titles.")
    return None  # No match found


@multi_route(*_wildcard_browser_paths('marked_as_watched'))
def MARKED_AS_WATCHED(payload, params):
    from resources.lib.WatchlistIntegration import watchlist_update_episode
    import service

    parts = [p for p in payload.strip('/').split('/') if p]
    if len(parts) >= 2:
        mal_id, episode = parts[0], parts[1]
    elif parts:
        mal_id, episode = parts[0], 1
    else:
        mal_id, episode = "", 1

    any_completed = watchlist_update_episode(mal_id, episode)
    if any_completed:
        control.sleep(3000)
        service.sync_watchlist(True)

    # Synchronize Watch History
    if mal_id:
        try:
            ep_int = int(episode) if str(episode).isdigit() else 1
            save_to_watch_history(mal_id, ep_int)
        except Exception as e:
            control.log(f"Error saving to watch history: {e}", "warning")

    # Invalidate cached eps_watched in kodi_meta so UI repaints playcounts
    show = database.get_show(mal_id)
    if show:
        try:
            kodi_meta = database.loads(show['kodi_meta'])
            ep_int = int(episode) if str(episode).isdigit() else 1
            kodi_meta['eps_watched'] = max(int(kodi_meta.get('eps_watched') or 0), ep_int)
            database.update_kodi_meta(mal_id, kodi_meta)
        except Exception as e:
            control.log(f"Error updating kodi_meta: {e}", "warning")

    # Build notification showing updated watchlists
    enabled = control.enabled_watchlists()
    flavor_labels = {'anilist': 'AniList', 'kitsu': 'Kitsu', 'mal': 'MAL', 'simkl': 'Simkl'}
    updated_names = ', '.join([flavor_labels.get(f, f.capitalize()) for f in enabled]) if enabled else 'No Watchlist'

    if len(parts) >= 2:
        control.notify(control.ADDON_NAME, f'Episode #{episode} was Marked as Watched in {updated_names}')
        control.execute(f'ActivateWindow(Videos,plugin://{control.ADDON_ID}/watchlist_to_ep/{mal_id}/{episode})')
    else:
        title = ''
        if show:
            kodi_meta = database.loads(show['kodi_meta'])
            title = kodi_meta.get('title_userPreferred', '')
        control.notify(control.ADDON_NAME, f'{title} was Marked as Watched in {updated_names}')
        control.execute('Container.Refresh')
    control.exit_code()


@multi_route(*_wildcard_browser_paths('marked_as_unwatched'))
def MARKED_AS_UNWATCHED(payload, params):
    from resources.lib.WatchlistIntegration import watchlist_update_episode
    import service

    parts = [p for p in payload.strip('/').split('/') if p]
    if len(parts) >= 2:
        mal_id, ep_str = parts[0], parts[1]
    elif parts:
        mal_id, ep_str = parts[0], '1'
    else:
        return

    try:
        current_ep = int(ep_str)
        target_ep = max(0, current_ep - 1)
    except (ValueError, TypeError):
        current_ep = 1
        target_ep = 0

    any_completed = watchlist_update_episode(mal_id, target_ep)
    if any_completed:
        control.sleep(1000)
        service.sync_watchlist(True)

    # Invalidate cached eps_watched in kodi_meta so UI repaints playcounts
    show = database.get_show(mal_id)
    if show:
        try:
            kodi_meta = database.loads(show['kodi_meta'])
            kodi_meta['eps_watched'] = target_ep
            database.update_kodi_meta(mal_id, kodi_meta)
        except Exception as e:
            control.log(f"Error updating kodi_meta: {e}", "warning")

    # If target_ep is 0, remove anime from watch history; otherwise update to target_ep
    if target_ep == 0:
        try:
            if control.pathExists(control.watch_history_json):
                with open(control.watch_history_json, 'r', encoding='utf-8') as f:
                    history_data = json.load(f)
                history_data['history'] = [
                    h for h in history_data.get('history', [])
                    if str(h.get('UniqueIDs', {}).get('mal_id') or h.get('mal_id')) != str(mal_id)
                ]
                control.atomic_write_json(control.watch_history_json, history_data)
        except Exception as e:
            control.log(f"Error updating watch history on unwatch: {e}", "warning")
    else:
        try:
            save_to_watch_history(mal_id, target_ep)
        except Exception as e:
            control.log(f"Error saving to watch history: {e}", "warning")

    enabled = control.enabled_watchlists()
    flavor_labels = {'anilist': 'AniList', 'kitsu': 'Kitsu', 'mal': 'MAL', 'simkl': 'Simkl'}
    updated_names = ', '.join([flavor_labels.get(f, f.capitalize()) for f in enabled]) if enabled else 'Local History'

    if len(parts) >= 2:
        control.notify(control.ADDON_NAME, f'Episode #{current_ep} Marked as Unwatched in {updated_names}')
    else:
        title = ''
        if show:
            try:
                title = database.loads(show['kodi_meta']).get('title_userPreferred', '')
            except Exception:
                title = ''
        control.notify(control.ADDON_NAME, f'{title} Marked as Unwatched in {updated_names}')

    control.execute('Container.Refresh')
    control.exit_code()


@multi_route(*_wildcard_browser_paths('mark_previous_watched'))
def MARK_PREVIOUS_WATCHED(payload, params):
    from resources.lib.WatchlistIntegration import watchlist_update_episode
    import service

    parts = [p for p in payload.strip('/').split('/') if p]
    if len(parts) >= 2:
        mal_id, ep_str = parts[0], parts[1]
    else:
        return
    try:
        target_ep = int(ep_str)
    except (ValueError, TypeError):
        return

    # User confirmation dialog
    show = database.get_show(mal_id)
    title = ''
    if show:
        try:
            kodi_meta = database.loads(show['kodi_meta'])
            title = kodi_meta.get('title_userPreferred', '')
        except Exception:
            title = ''
    anime_label = f" for '{title}'" if title else ""
    confirmed = control.yesno_dialog(
        "Mark Episodes as Watched",
        f"Mark episodes 1 to {target_ep}{anime_label} as watched in your WatchLists and Watch History?"
    )
    if not confirmed:
        return

    # Update watchlist for target_ep (MAL/AniList/Simkl/Kitsu sets progress to target_ep)
    any_completed = watchlist_update_episode(mal_id, target_ep)
    if any_completed:
        control.sleep(3000)
        service.sync_watchlist(True)

    # Save to watch history for target_ep
    try:
        save_to_watch_history(mal_id, target_ep)
    except Exception as e:
        control.log(f"Error saving to watch history: {e}", "warning")

    # Invalidate cached eps_watched in kodi_meta so UI repaints playcounts
    if show:
        try:
            kodi_meta = database.loads(show['kodi_meta'])
            kodi_meta['eps_watched'] = target_ep
            database.update_kodi_meta(mal_id, kodi_meta)
        except Exception as e:
            control.log(f"Error updating kodi_meta: {e}", "warning")

    # Build notification showing updated watchlists
    enabled = control.enabled_watchlists()
    flavor_labels = {'anilist': 'AniList', 'kitsu': 'Kitsu', 'mal': 'MAL', 'simkl': 'Simkl'}
    updated_names = ', '.join([flavor_labels.get(f, f.capitalize()) for f in enabled]) if enabled else 'Local History'
    control.notify(control.ADDON_NAME, f"Episodes 1 to {target_ep} Marked as Watched in {updated_names}")
    control.execute("Container.Refresh")


@Route('playback_options/*')
def PLAYBACK_OPTIONS(payload, params):
    import xbmcgui
    from urllib.parse import urlencode

    # Parse the payload to get mal_id and episode
    if payload and '/' in payload:
        mal_id, episode = payload.split('/', 1)
    else:
        control.log('Invalid payload format', 'error')
        return control.exit_code()

    # Get show information from database to build params
    show = database.get_show(mal_id)
    if show:
        kodi_meta = database.loads(show['kodi_meta'])

        # Build params similar to what get_video_info would return
        episode_params = {
            'mal_id': mal_id,
            'episode': episode,
            'title': kodi_meta.get('title_userPreferred', ''),
            'mediatype': 'episode',
            'tvshowtitle': kodi_meta.get('title_userPreferred', ''),
            'plot': kodi_meta.get('plot', ''),
            'year': str(kodi_meta.get('year', '')),
            'premiered': kodi_meta.get('premiered', ''),
            'season': str(kodi_meta.get('season', 1)),
            'aired': kodi_meta.get('aired', ''),
            'rating': kodi_meta.get('rating', {}),
            'resume': params.get('resume', ''),
            # Artwork
            'poster': kodi_meta.get('poster', ''),
            'tvshow.poster': kodi_meta.get('poster', ''),
            'icon': kodi_meta.get('poster', ''),
            'thumb': kodi_meta.get('thumb', ''),
            'fanart': kodi_meta.get('fanart', ''),
            'landscape': kodi_meta.get('landscape', ''),
            'banner': kodi_meta.get('banner', ''),
            'clearart': kodi_meta.get('clearart', ''),
            'clearlogo': kodi_meta.get('clearlogo', '')
        }
    else:
        # Fallback params if show not found in database
        episode_params = {
            'mal_id': mal_id,
            'episode': episode,
            'title': '',
            'mediatype': 'episode',
            'tvshowtitle': '',
            'plot': '',
            'year': '',
            'premiered': '',
            'season': '1',
            'aired': '',
            'rating': {},
            'resume': params.get('resume', ''),
            # Artwork
            'poster': '',
            'tvshow.poster': '',
            'icon': '',
            'thumb': '',
            'fanart': '',
            'landscape': '',
            'banner': '',
            'clearart': '',
            'clearlogo': ''
        }

    # Ask the user which playback option they want to use
    # Here the button labels are:
    # Button 0: "Cancel"   | Button 1: "Rescrape" | Button 2: "Source Select"
    yesnocustom = control.yesnocustom_dialog(
        control.ADDON_NAME + " - Playback Options",
        "Please choose a playback option:",
        "Cancel", "Source Select", "Rescrape",
        defaultbutton=xbmcgui.DLG_YESNO_YES_BTN
    )

    if yesnocustom == 0:
        # Redirect to play route with source_select parameter
        query_params = urlencode({'source_select': 'true', **episode_params})
        control.playList.clear()
        control.execute(f'RunPlugin(plugin://{control.ADDON_ID}/play/{mal_id}/{episode}?{query_params})')

    elif yesnocustom == 1:
        # Redirect to play route with rescrape parameter
        query_params = urlencode({'rescrape': 'true', **episode_params})
        control.playList.clear()
        control.execute(f'RunPlugin(plugin://{control.ADDON_ID}/play/{mal_id}/{episode}?{query_params})')

    elif yesnocustom == 2:
        # User cancelled, exit without doing anything
        pass

    control.exit_code()
