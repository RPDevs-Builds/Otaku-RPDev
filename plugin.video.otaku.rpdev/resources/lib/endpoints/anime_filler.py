import re

from bs4 import BeautifulSoup
from resources.lib.ui import client, control, database

url = "https://www.animefillerlist.com/shows"


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
                            filler_list.append(span.text.strip())
        except Exception as e:
            control.log(f"anime_filler lookup error for {anime_eng_title}: {e}", 'debug')

    return filler_list


def get_data(anime_eng_title):
    if not anime_eng_title:
        return []
    # Cache filler list in SQLite / RAM for 7 days (168 hours)
    return database.get(_fetch_filler_data, 168, anime_eng_title)
