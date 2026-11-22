
from datetime import date
from functools import partial
import re
from resources.lib import endpoints
from resources.lib.ui import database, control, utils


def _pick_art_str(val):
    """Unwrap artwork string from a str or non-empty list/tuple so Kodi art dicts never strip it."""
    if isinstance(val, str) and val.strip():
        return val
    if isinstance(val, (list, tuple)):
        for entry in val:
            if isinstance(entry, str) and entry.strip():
                return entry
    return ''


def _apply_spoiler_shield(parsed):
    """Replace episode screenshot thumb/icon with show fanart or poster string."""
    shield_mode = control.getInt('interface.spoilers.shield_mode')
    img_dict = parsed.get('image') if isinstance(parsed.get('image'), dict) else {}
    primary = _pick_art_str(img_dict.get('fanart')) if shield_mode == 0 else _pick_art_str(img_dict.get('poster'))
    secondary = _pick_art_str(img_dict.get('poster')) if shield_mode == 0 else _pick_art_str(img_dict.get('fanart'))
    shield_art = primary or secondary or getattr(control, 'OTAKU_FANART', '') or ''
    if shield_art:
        if isinstance(parsed.get('image'), dict):
            parsed['image']['thumb'] = shield_art
            parsed['image']['icon'] = shield_art
        else:
            parsed['image'] = shield_art


def _apply_filler_badge(parsed, filler_val):
    """Append colored [FILLER], [RECAP], or [MIXED] badge to episode title when interface.filler.badges is enabled."""
    if not filler_val or not control.getBool('interface.filler.badges', default=False):
        return
    clean_f = re.sub(r'\[/?COLOR[^\]]*\]|\[/?B\]', '', str(filler_val)).strip().lower()
    badge = ''
    if 'recap' in clean_f:
        badge = '[COLOR orange][RECAP][/COLOR]'
    elif 'mixed' in clean_f or 'canon/filler' in clean_f:
        badge = '[COLOR yellow][MIXED][/COLOR]'
    elif 'filler' in clean_f:
        badge = '[COLOR red][FILLER][/COLOR]'
    if badge and badge not in str(parsed.get('name', '')):
        parsed['name'] = f"{parsed['name']} {badge}".strip()
        if isinstance(parsed.get('info'), dict):
            parsed['info']['title'] = parsed['name']


def get_show_filler_data(mal_id, kodi_meta=None):
    """Fetch filler map {ep_num: tag} from offline filler_ranges with legacy AnimeFillerList fallback."""
    from resources.lib.endpoints import anime_filler
    meta = kodi_meta if isinstance(kodi_meta, dict) else {}
    return anime_filler.get_filler_map(
        mal_id=mal_id,
        anime_eng_title=meta.get('ename') or meta.get('title_english') or '',
        total_episodes=meta.get('episodes'),
        status=meta.get('status'),
    )


def lookup_filler_tag(filler_data, episode):
    """Safely look up filler tag from dict {ep_num: tag} or legacy 0-indexed list."""
    if not filler_data:
        return ''
    try:
        ep_num = int(episode)
    except (TypeError, ValueError):
        return ''
    if ep_num <= 0:
        return ''
    if isinstance(filler_data, dict):
        return str(filler_data.get(ep_num) or filler_data.get(str(ep_num)) or '')
    if isinstance(filler_data, (list, tuple)) and ep_num <= len(filler_data):
        return str(filler_data[ep_num - 1] or '')
    return ''


def parse_episodes(res, eps_watched, dub_data=None, offline_filler=None):
    parsed = database.loads(res['kodi_meta'])
    if eps_watched and int(eps_watched) >= res['number']:
        parsed['info']['playcount'] = 1
    if control.getBool('interface.cleantitles') and parsed['info'].get('playcount') != 1:
        parsed['name'] = f'Episode {res["number"]}'
        parsed['info']['title'] = f'Episode {res["number"]}'
        parsed['info']['plot'] = None
    if control.getBool('interface.spoilers.hide_thumbs') and parsed['info'].get('playcount') != 1:
        _apply_spoiler_shield(parsed)
    filler_val = res.get('filler') or ''
    if not filler_val and offline_filler:
        filler_val = lookup_filler_tag(offline_filler, res.get('number'))
    code = endpoints.get_second_label(parsed['info'], dub_data, filler_val)
    parsed['info']['code'] = code
    _apply_filler_badge(parsed, filler_val)
    if control.getBool('interface.aired.show_countdown', default=True):
        aired_str = parsed['info'].get('aired')
        if aired_str:
            try:
                aired_date = date.fromisoformat(aired_str[:10])
                today = date.today()
                if aired_date > today:
                    diff_days = (aired_date - today).days
                    if diff_days == 1:
                        air_badge = "[COLOR gray](Airs Tomorrow)[/COLOR]"
                    else:
                        weekday_name = aired_date.strftime("%a")
                        air_badge = f"[COLOR gray](Airs {weekday_name} in {diff_days}d)[/COLOR]"
                    parsed['name'] = f"{parsed['name']} {air_badge}"
                    parsed['info']['title'] = parsed['name']
                    parsed['info']['unaired'] = True
                    parsed['info']['aired_date'] = aired_str
            except (ValueError, TypeError, Exception):
                pass
    return parsed


def process_episodes(episodes, eps_watched, dub_data=None, mal_id=None):
    offline_filler = None
    if episodes:
        mid = mal_id or episodes[0].get('mal_id')
        if mid and any(not ep.get('filler') for ep in episodes):
            offline_filler = database.get_mapping_filler_map(mid) or None
    mapfunc = partial(parse_episodes, eps_watched=eps_watched, dub_data=dub_data, offline_filler=offline_filler)
    # Parallelize episode parsing for faster processing
    all_results = utils.parallel_process(episodes, mapfunc)
    return all_results


def process_dub(mal_id, ename):
    update_time = date.today().isoformat()
    if not (show_data := database.get_show_data(mal_id)) or show_data['last_updated'] != update_time:
        if control.getInt('jz.dub.api') == 0:
            from resources.lib.endpoints import teamup
            dub_data = teamup.get_dub_data(mal_id, ename)
            data = {"dub_data": dub_data}
            database.update_show_data(mal_id, data, update_time)
        else:
            from resources.lib.endpoints import animeschedule
            dub_data = animeschedule.get_dub_time(mal_id)
            data = {"dub_data": dub_data}
            database.update_show_data(mal_id, data, update_time)
    else:
        dub_data = database.loads(show_data['data'])['dub_data']
    return dub_data


def get_diff(episodes_0):
    import datetime
    update_time = datetime.date.today().isoformat()
    try:
        last_updated = datetime.datetime.strptime(episodes_0.get('last_updated'), "%Y-%m-%d")
    except Exception:
        import time
        control.log('Unsupported strptime using fromtimestamp', 'warning')
        last_updated = datetime.datetime.fromtimestamp(time.mktime(time.strptime(episodes_0.get('last_updated'), '%Y-%m-%d')))
    diff = (datetime.datetime.today() - last_updated).days
    return update_time, diff


def should_hide_unaired_episode(aired_date_str):
    """
    Check if an episode should be hidden based on aired date and interface.aired_episodes setting.
    Returns True if episode is unaired and should be hidden, False otherwise.
    """
    import datetime
    if not control.getBool('interface.aired_episodes'):
        return False

    if not aired_date_str:
        return False

    try:
        # Parse the aired date with fallback for compatibility
        try:
            aired_date = datetime.datetime.strptime(aired_date_str[:10], '%Y-%m-%d')
        except Exception:
            import time
            aired_date = datetime.datetime.fromtimestamp(time.mktime(time.strptime(aired_date_str[:10], '%Y-%m-%d')))

        today = datetime.datetime.now()
        return aired_date > today
    except (ValueError, TypeError, AttributeError, Exception):
        # If date parsing fails, show the episode anyway
        return False


def update_database(mal_id, update_time, res, url, image, info, season, episode, episodes, title, fanart, poster, clearart, clearlogo, dub_data, filler, anidb_ep_id=None):
    code = endpoints.get_second_label(info, dub_data)
    if not code and control.getBool('jz.filler'):
        filler = code = control.colorstr(filler, color="red") if filler == 'Filler' else filler
    info['code'] = code
    landscape = None
    banner = None

    parsed = utils.allocate_item(title, f"play/{url}", False, True, [], image, info, fanart, poster, landscape, banner, clearart, clearlogo)
    kodi_meta = database.dumps(parsed)
    if not episodes or len(episodes) <= episode or kodi_meta != episodes[episode - 1]['kodi_meta']:
        database.update_episode(mal_id, season, episode, update_time, kodi_meta, filler, anidb_ep_id)

    if control.getBool('interface.cleantitles') and info.get('playcount') != 1:
        parsed['info']['title'] = f'Episode {episode}'
        parsed['info']['plot'] = None

    if control.getBool('interface.spoilers.hide_thumbs') and info.get('playcount') != 1:
        _apply_spoiler_shield(parsed)

    _apply_filler_badge(parsed, filler)

    if control.getBool('interface.aired.show_countdown', default=True):
        aired_str = info.get('aired')
        if aired_str:
            try:
                aired_date = date.fromisoformat(aired_str[:10])
                today = date.today()
                if aired_date > today:
                    diff_days = (aired_date - today).days
                    if diff_days == 1:
                        air_badge = "[COLOR gray](Airs Tomorrow)[/COLOR]"
                    else:
                        weekday_name = aired_date.strftime("%a")
                        air_badge = f"[COLOR gray](Airs {weekday_name} in {diff_days}d)[/COLOR]"
                    parsed['name'] = f"{parsed['name']} {air_badge}"
                    parsed['info']['title'] = parsed['name']
                    parsed['info']['unaired'] = True
                    parsed['info']['aired_date'] = aired_str
            except (ValueError, TypeError, Exception):
                pass

    return parsed
