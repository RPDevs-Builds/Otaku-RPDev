# -*- coding: utf-8 -*-
import json
import os
import random
import time

from resources.lib.ui import control, database, utils
from resources.lib.ui.router import Route, multi_route


def add_last_watched(items):
    mal_id = control.getSetting("addon.last_watched")
    if not mal_id:
        return items
    try:
        show_row = database.get_show(mal_id)
        if not show_row:
            return items
        kodi_meta = database.loads(show_row['kodi_meta'])

        # Get extended artwork from shows_meta table
        show_meta = database.get_show_meta(mal_id)
        art = {}
        if show_meta and show_meta.get('art'):
            art = database.loads(show_meta['art'])

        title = kodi_meta.get('title_userPreferred', '')
        episodes = kodi_meta.get('episodes', 0)

        # Lookup last watched episode from watch_history or kodi_meta
        last_ep = None
        if control.pathExists(control.watch_history_json):
            try:
                with open(control.watch_history_json, 'r', encoding='utf-8') as f:
                    hdata = json.load(f)
                    for entry in hdata.get('history', []):
                        emid = str(entry.get('UniqueIDs', {}).get('mal_id') or entry.get('mal_id') or '')
                        if emid == str(mal_id):
                            last_ep = entry.get('last_watched_episode')
                            break
            except Exception:
                pass

        if last_ep is None and kodi_meta.get('eps_watched'):
            try:
                last_ep = int(kodi_meta['eps_watched'])
            except (ValueError, TypeError):
                pass

        if last_ep is not None:
            if episodes and episodes > 1:
                badge = f" [COLOR dodgerblue]Ep {last_ep}/{episodes}[/COLOR]"
            else:
                badge = f" [COLOR dodgerblue]Ep {last_ep}[/COLOR]"
        else:
            badge = ""

        last_watched = "%s: [I]%s[/I]%s" % (control.lang(30000), title, badge)
        info = {
            'UniqueIDs': {
                'mal_id': mal_id,
                **database.get_unique_ids(mal_id, 'mal_id')
            },
            'title': f"{title}{badge}",
            'plot': kodi_meta.get('plot', ''),
            'mpaa': kodi_meta.get('mpaa', ''),
            'duration': kodi_meta.get('duration', 0),
            'genre': kodi_meta.get('genre', []),
            'studio': kodi_meta.get('studio', []),
            'status': kodi_meta.get('status', ''),
            'mediatype': 'movie' if episodes == 1 else 'tvshow',
            'rating': kodi_meta.get('rating', {}),
            'cast': kodi_meta.get('cast', []),
            'country': kodi_meta.get('country', []),
            'trailer': kodi_meta.get('trailer', ''),
            'year': kodi_meta.get('year', ''),
            'premiered': kodi_meta.get('premiered', ''),
            'episodes': episodes,
        }

        # Simple movie detection: if episodes == 1, treat as movie
        if episodes == 1:
            url = f'play_movie/{mal_id}/'
        else:
            click_action = control.getInt('interface.watchhistory.click')  # 0: open list, 1: play next, 2: resume last
            target_ep = last_ep if last_ep else 1
            next_ep = (last_ep + 1) if (last_ep is not None and (not episodes or last_ep < episodes)) else (last_ep or 1)
            if click_action == 1:
                url = f'play/{mal_id}/{next_ep}'
            elif click_action == 2:
                url = f'play/{mal_id}/{target_ep}'
            else:
                url = f'animes/{mal_id}/'

        # Merge artwork from shows_meta into kodi_meta for the tuple
        artwork_meta = dict(kodi_meta)
        artwork_meta['poster'] = art.get('poster') or kodi_meta.get('poster', '')
        artwork_meta['fanart'] = art.get('fanart', '')
        artwork_meta['thumb'] = art.get('thumb', '')
        artwork_meta['banner'] = art.get('banner', '')
        artwork_meta['clearlogo'] = art.get('clearlogo', '')
        artwork_meta['clearart'] = art.get('clearart', '')
        artwork_meta['landscape'] = art.get('landscape', '')
        artwork_meta['last_watched_episode'] = last_ep

        # Return tuple with special marker for last_watched items
        items.append(('LAST_WATCHED_ITEM', last_watched, url, artwork_meta.get('poster', ''), info, artwork_meta))

    except Exception as e:
        control.log(f"Error adding last watched: {e}", level='warning')

    return items


def add_watch_history(items):
    try:
        # Load watch history from JSON file
        if not control.pathExists(control.watch_history_json):
            return items

        with open(control.watch_history_json, 'r', encoding='utf-8') as f:
            history_data = json.load(f)

        # Get the most recent entries (limit to last 10 for menu)
        recent_history = history_data.get('history', [])[:10]

        if recent_history:
            # Add a "Watch History" menu item with dynamic artwork from most recent anime
            history_title = control.lang(30068)
            most_recent = recent_history[0]
            art = {
                'poster': most_recent.get('poster', ''),
                'fanart': most_recent.get('fanart', ''),
                'landscape': most_recent.get('landscape') or most_recent.get('thumb', ''),
                'banner': most_recent.get('banner', ''),
                'clearart': most_recent.get('clearart', ''),
                'clearlogo': most_recent.get('clearlogo', ''),
            }
            icon = art['poster'] if art.get('poster') else 'watch_history.png'
            history_info = {
                'title': history_title,
                'plot': f"Recently watched: {most_recent.get('title', '')}",
                'mediatype': 'tvshow',
            }

            items.append((history_title, 'watch_history/', icon, history_info, art))

    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass

    return items


def save_to_watch_history(mal_id, episode=None, total_episodes=None):
    """Save an anime to watch history with episode and timestamp tracking"""
    try:
        # Load existing history or create new
        if control.pathExists(control.watch_history_json):
            with open(control.watch_history_json, 'r', encoding='utf-8') as f:
                history_data = json.load(f)
        else:
            history_data = {'history': []}

        # Find existing entry to preserve fields if needed
        existing_entry = None
        for h in history_data.get('history', []):
            if str(h.get('UniqueIDs', {}).get('mal_id')) == str(mal_id):
                existing_entry = h
                break

        # Get anime metadata
        anime_data = database.get_show(mal_id)
        if not anime_data:
            return

        kodi_meta = database.loads(anime_data['kodi_meta'])

        # Get extended artwork from shows_meta table
        show_meta = database.get_show_meta(mal_id)
        art = {}
        if show_meta and show_meta.get('art'):
            art = database.loads(show_meta['art'])

        eps_count = int(total_episodes) if total_episodes else kodi_meta.get('episodes', 0)
        watched_ep = int(episode) if episode is not None else (existing_entry.get('last_watched_episode') if existing_entry else None)

        # Create history entry with the same info as add_last_watched
        history_entry = {
            'UniqueIDs': {
                'mal_id': mal_id,
                **database.get_unique_ids(mal_id, 'mal_id')
            },
            'title': kodi_meta.get('title_userPreferred', ''),
            'plot': kodi_meta.get('plot', ''),
            'mpaa': kodi_meta.get('mpaa', ''),
            'duration': kodi_meta.get('duration', 0),
            'genre': kodi_meta.get('genre', []),
            'studio': kodi_meta.get('studio', []),
            'status': kodi_meta.get('status', ''),
            'mediatype': 'tvshow',
            'rating': kodi_meta.get('rating', {}),
            'cast': kodi_meta.get('cast', []),
            'country': kodi_meta.get('country', []),
            'trailer': kodi_meta.get('trailer', ''),
            'year': kodi_meta.get('year', ''),
            'premiered': kodi_meta.get('premiered', ''),
            'episodes': eps_count,
            'last_watched_episode': watched_ep,
            'last_watched_at': int(time.time()),
            # Artwork - use art dict from shows_meta, fallback to kodi_meta
            'poster': art.get('poster') or kodi_meta.get('poster', ''),
            'tvshow.poster': art.get('poster') or kodi_meta.get('poster', ''),
            'icon': art.get('poster') or kodi_meta.get('poster', ''),
            'thumb': art.get('thumb', ''),
            'fanart': art.get('fanart', ''),
            'landscape': art.get('landscape', ''),
            'banner': art.get('banner', ''),
            'clearart': art.get('clearart', ''),
            'clearlogo': art.get('clearlogo', '')
        }

        # Remove any existing entry for this anime to avoid duplicates
        history_data['history'] = [h for h in history_data['history'] if str(h.get('UniqueIDs', {}).get('mal_id')) != str(mal_id)]

        # Add new entry at the beginning
        history_data['history'].insert(0, history_entry)

        # Cap history to 100 entries to maintain instant loading
        history_data['history'] = history_data['history'][:100]

        # Save back to file
        with open(control.watch_history_json, 'w', encoding='utf-8') as f:
            json.dump(history_data, f, ensure_ascii=False, indent=2)

    except Exception as e:
        control.log(f"Error saving to watch history: {str(e)}", "error")


@multi_route('watch_history/', 'watch_history')
def WATCH_HISTORY(payload, params):
    """Display watch history as an instant springboard into recently watched anime."""
    try:
        if not control.pathExists(control.watch_history_json):
            control.draw_items([], 'tvshows')
            return

        with open(control.watch_history_json, 'r', encoding='utf-8') as f:
            history_data = json.load(f)

        from resources.lib.ui import divide_flavors
        show_dub_badge = control.getBool('divflavors.showdub')
        mal_dub = divide_flavors._get_mal_dub() if show_dub_badge else {}

        history_items = []
        for entry in history_data.get('history', []):
            try:
                # Get the mal_id safely
                mal_id = entry.get('UniqueIDs', {}).get('mal_id') or entry.get('mal_id')
                if not mal_id:
                    continue

                # Format title and badges
                title = entry.get('title', '')
                episodes = entry.get('episodes', 0)
                last_ep = entry.get('last_watched_episode')
                if last_ep is None:
                    show_data = database.get_show(mal_id)
                    if show_data:
                        try:
                            s_meta = database.loads(show_data['kodi_meta'])
                            last_ep = s_meta.get('eps_watched')
                        except Exception:
                            pass

                display_title = title
                if show_dub_badge and mal_dub.get(str(mal_id)):
                    display_title = f"{display_title} [COLOR blue](Dub)[/COLOR]"

                if last_ep is not None:
                    if episodes and episodes > 1:
                        display_title = f"{display_title} [COLOR dodgerblue]Ep {last_ep}/{episodes}[/COLOR]"
                    else:
                        display_title = f"{display_title} [COLOR dodgerblue]Ep {last_ep}[/COLOR]"

                plot = entry.get('plot', '')
                if last_ep is not None:
                    ep_str = f"Episode {last_ep}" + (f" of {episodes}" if episodes and episodes > 1 else "")
                    plot = f"[B]Last Watched:[/B] {ep_str}\n\n{plot}"

                info = {
                    'UniqueIDs': entry.get('UniqueIDs', {}),
                    'title': display_title,
                    'plot': plot,
                    'mpaa': entry.get('mpaa', ''),
                    'duration': entry.get('duration', 0),
                    'genre': entry.get('genre', []),
                    'studio': entry.get('studio', []),
                    'status': entry.get('status', ''),
                    'mediatype': 'movie' if episodes == 1 else 'tvshow',
                    'rating': entry.get('rating', {}),
                    'cast': entry.get('cast', []),
                    'country': entry.get('country', []),
                    'trailer': entry.get('trailer', ''),
                    'year': entry.get('year', ''),
                    'premiered': entry.get('premiered', ''),
                    'episodes': episodes,
                }

                # Handle fanart (may be a list)
                fanart = entry.get('fanart', '')
                if isinstance(fanart, list) and fanart:
                    fanart = random.choice(fanart)
                elif isinstance(fanart, list):
                    fanart = ''

                # Handle banner with fallback to poster
                banner = entry.get('banner', '')
                if isinstance(banner, list) and banner:
                    banner = random.choice(banner)
                elif isinstance(banner, list):
                    banner = ''
                if not banner:
                    banner = entry.get('poster', '')

                # Context menu & springboard URLs
                cm = []
                if episodes == 1:
                    base_url = f'play_movie/{mal_id}/'
                    is_folder = False
                    is_playable = True
                    cm.append(('Play Movie', f'PlayMedia(plugin://{control.ADDON_ID}/play_movie/{mal_id}/)'))
                else:
                    click_action = control.getInt('interface.watchhistory.click')  # 0: open list, 1: play next, 2: resume last
                    target_ep = last_ep if last_ep else 1
                    next_ep = (last_ep + 1) if (last_ep is not None and (not episodes or last_ep < episodes)) else (last_ep or 1)

                    if click_action == 1:
                        base_url = f'play/{mal_id}/{next_ep}'
                        is_folder = False
                        is_playable = True
                    elif click_action == 2:
                        base_url = f'play/{mal_id}/{target_ep}'
                        is_folder = False
                        is_playable = True
                    else:
                        base_url = f'watchlist_to_ep/{mal_id}/{target_ep}' if last_ep is not None else f'animes/{mal_id}/'
                        is_folder = True
                        is_playable = False

                    if last_ep is not None:
                        cm.append((f'Play Next Episode (Ep {next_ep})', f'PlayMedia(plugin://{control.ADDON_ID}/play/{mal_id}/{next_ep})'))
                        cm.append((f'Resume Episode {last_ep}', f'PlayMedia(plugin://{control.ADDON_ID}/play/{mal_id}/{last_ep})'))
                    else:
                        cm.append(('Play Episode 1', f'PlayMedia(plugin://{control.ADDON_ID}/play/{mal_id}/1)'))

                    cm.append(('Browse Episodes', f'Container.Update(plugin://{control.ADDON_ID}/watchlist_to_ep/{mal_id}/{target_ep})'))

                cm.append(('Remove from Watch History', f'RunPlugin(plugin://{control.ADDON_ID}/remove_watch_history/{mal_id})'))

                landscape = ''
                if entry.get('thumb'):
                    thumb = entry['thumb']
                    landscape = random.choice(thumb) if isinstance(thumb, list) and thumb else (thumb if not isinstance(thumb, list) else '')

                clearart = ''
                if entry.get('clearart'):
                    ca = entry['clearart']
                    clearart = random.choice(ca) if isinstance(ca, list) and ca else (ca if not isinstance(ca, list) else '')

                clearlogo = ''
                if entry.get('clearlogo'):
                    cl = entry['clearlogo']
                    clearlogo = random.choice(cl) if isinstance(cl, list) and cl else (cl if not isinstance(cl, list) else '')

                poster = entry.get('poster', '') or entry.get('image', '')
                image = entry.get('image', '') or poster

                parsed_item = utils.allocate_item(
                    display_title,
                    base_url,
                    is_folder,
                    is_playable,
                    cm,
                    image=image,
                    info=info,
                    fanart=fanart,
                    poster=poster,
                    landscape=landscape,
                    banner=banner,
                    clearart=clearart,
                    clearlogo=clearlogo
                )
                if parsed_item:
                    history_items.append(parsed_item)

            except Exception as e:
                control.log(f"Error processing history entry: {str(e)}", "error")
                continue

        control.draw_items(history_items, 'tvshows')

    except Exception as e:
        control.log(f"Error loading watch history: {str(e)}", "error")
        control.draw_items([], 'tvshows')


@Route('clear_watch_history')
def CLEAR_WATCH_HISTORY(payload, params):
    silent = False

    if not silent:
        confirm = control.yesno_dialog(control.ADDON_NAME, control.lang(30091))
    if confirm == 0:
        return

    if os.path.exists(control.watch_history_json):
        os.remove(control.watch_history_json)
    control.refresh()
    if not silent:
        control.notify(f'{control.ADDON_NAME}: Watch History', 'Watch History Successfully Cleared', sound=False)


@Route('clear_last_watched')
def CLEAR_LAST_WATCHED(payload, params):
    control.setSetting("addon.last_watched", "")
    control.notify(control.ADDON_NAME, "Cleared Last Watched")
    control.refresh()


@Route('remove_watch_history/*')
def REMOVE_WATCH_HISTORY(payload, params):
    mal_id = payload.strip('/')
    try:
        if control.pathExists(control.watch_history_json):
            with open(control.watch_history_json, 'r', encoding='utf-8') as f:
                history_data = json.load(f)
            history_data['history'] = [
                h for h in history_data.get('history', [])
                if str(h.get('UniqueIDs', {}).get('mal_id') or h.get('mal_id')) != str(mal_id)
            ]
            with open(control.watch_history_json, 'w', encoding='utf-8') as f:
                json.dump(history_data, f, ensure_ascii=False, indent=2)
            control.refresh()
            control.notify(f'{control.ADDON_NAME}: Watch History', 'Removed from Watch History', sound=False)
    except Exception as e:
        control.log(f"Error removing from watch history: {str(e)}", "error")
