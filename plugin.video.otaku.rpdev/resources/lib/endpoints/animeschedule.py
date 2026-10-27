import datetime
import re

from bs4 import BeautifulSoup
from resources.lib.ui import client, control, database

base_url = "https://animeschedule.net/api/v3"


def get_route(mal_id):
    params = {
        "mal-ids": mal_id
    }
    response = client.get(f"{base_url}/anime", params=params)
    if response:
        data = control.safe_json(response, default={})
        anime_list = data.get('anime', [])
        if anime_list:
            return anime_list[0].get('route', '')
    return ''


def get_dub_time(mal_id):
    dub_list = []
    show = database.get_show(mal_id)
    if not show:
        return dub_list
    route = show.get('anime_schedule_route')
    if not route:
        route = get_route(mal_id)
        if route and show.get('kodi_meta'):
            database.update_show(mal_id, show['kodi_meta'], route)
    if not route:
        return dub_list
    response = client.get(f'https://animeschedule.net/anime/{route}')
    if response and getattr(response, 'text', None):
        try:
            soup = BeautifulSoup(response.text, 'html.parser')
            soup_all = soup.find_all('div', class_='release-time-wrapper')
            for wrapper in soup_all:
                if 'dub:' in wrapper.text.lower():
                    span = wrapper.find('span')
                    time_elem = wrapper.find('time')
                    if not span or not time_elem:
                        continue
                    dub_text = span.text
                    date_time = time_elem.get('datetime')
                    if not date_time:
                        continue

                    if '-' in dub_text:
                        match = re.match(r'Episodes (\d+)-(\d+)', dub_text)
                        if match:
                            ep_begin = int(match.group(1))
                            ep_end = int(match.group(2))
                            for ep_number in range(ep_begin, ep_end + 1):
                                add_to_list(dub_list, ep_number, date_time)
                    else:
                        match = re.match(r'Episode (\d+)', dub_text)
                        if match:
                            ep_number = int(match.group(1))
                            add_to_list(dub_list, ep_number, date_time)
                    return dub_list
        except Exception as e:
            control.log(f"get_dub_time parse error for mal_id={mal_id}: {e}", 'debug')
    return dub_list


def add_to_list(dub_list, ep_number, date_time):
    try:
        parsed = datetime.datetime.fromisoformat(date_time)
        if parsed.tzinfo is not None:
            # Page times carry an explicit UTC offset; convert to the device's local time
            parsed = parsed.astimezone().replace(tzinfo=None)
        dub_time = str(parsed)[:16]
        dub_list.append({"season": 0, "episode": ep_number, "release_time": dub_time})
    except (ValueError, TypeError, OverflowError, OSError) as e:
        control.log(f"animeschedule date parse error: {e}", 'debug')
