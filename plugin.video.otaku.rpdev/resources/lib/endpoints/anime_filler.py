import re

from bs4 import BeautifulSoup
from resources.lib.ui import client, control

url = "https://www.animefillerlist.com/shows"


def get_data(anime_eng_title):
    filler_list = []
    if anime_eng_title:
        anime_url = re.sub(r'\W+', '-', anime_eng_title).strip('-').lower()
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
