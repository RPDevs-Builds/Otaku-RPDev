import re

from bs4 import BeautifulSoup
from resources.lib.ui import client, control, database

url = "https://www.animefillerlist.com/shows"


def classify_filler_tag(raw_tag):
    """Normalize raw AnimeFillerList span text into 'Filler', 'Recap', 'Mixed Canon/Filler', or ''."""
    if not raw_tag:
        return ''
    low = str(raw_tag).strip().lower()
    if 'recap' in low:
        return 'Recap'
    if 'mostly filler' in low or low == 'filler':
        return 'Filler'
    if 'mixed' in low or 'canon/filler' in low:
        return 'Mixed Canon/Filler'
    return ''


def _fetch_filler_data(anime_eng_title):
    filler_list = []
    if anime_eng_title:
        anime_url = re.sub(r'\W+', '-', anime_eng_title).strip('-').lower()
        if not anime_url:
            return filler_list
        try:
            response = client.get(f'{url}/{anime_url}', timeout=10)
            if response and getattr(response, 'text', None):
                soup = BeautifulSoup(response.text, 'html.parser')
                table = soup.find('table', class_="EpisodeList")
                if table and table.tbody:
                    for row in table.tbody.find_all('tr'):
                        span = row.find('span')
                        if span and span.text:
                            raw_txt = span.text.strip()
                            filler_list.append(classify_filler_tag(raw_txt) or raw_txt)
        except Exception as e:
            control.log(f"anime_filler lookup error for {anime_eng_title}: {e}", 'debug')

    return filler_list


def get_data(anime_eng_title):
    if not anime_eng_title:
        return []
    # Cache filler list in SQLite / RAM for 7 days (168 hours)
    return database.get(_fetch_filler_data, 168, anime_eng_title)


def get_filler_map(mal_id=None, anime_eng_title='', total_episodes=None, status=None):
    """Return {ep_num: filler_tag} using offline mappings.db filler_ranges first, then AnimeFillerList HTTP fallback."""
    if mal_id:
        offline = database.get_mapping_filler_map(mal_id)
        if offline:
            return offline

    if not anime_eng_title:
        return {}
    try:
        ep_total = int(total_episodes) if total_episodes not in (None, '', 0, '0') else None
    except (TypeError, ValueError):
        ep_total = None
    is_finished = str(status or '') in ('FINISHED', 'Finished Airing')
    if ep_total is not None and ep_total <= 99 and is_finished:
        return {}

    rows = get_data(anime_eng_title) or []
    return {
        idx + 1: tag
        for idx, tag in enumerate(rows)
        if tag
    }
