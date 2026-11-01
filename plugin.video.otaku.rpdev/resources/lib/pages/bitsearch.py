import html
import re
import urllib.parse
from functools import partial
from bs4 import BeautifulSoup

from resources.lib.debrid import Debrid
from resources.lib.ui import database, source_utils, control, client, utils, domains
from resources.lib.ui.BrowserBase import BrowserBase


class Sources(BrowserBase):
    _BASE_URL = domains.get_domain('bitsearch', 'https://bitsearch.to')

    def __init__(self):
        self.media_type = None
        self.cached = []
        self.uncached = []
        self.sources = []
        self.rescrape = False

    def get_sources(self, query, mal_id, episode, status, media_type, season=None, part=None, rescrape=False):
        query = self._clean_title(query).replace('-', ' ')
        self.media_type = media_type
        self.rescrape = rescrape

        if media_type == 'movie':
            return self.get_movie_sources(query, mal_id)

        episode_sources = self.get_episode_sources(query, mal_id, episode, season, part, status)
        show_sources = self.get_show_sources(query, mal_id, episode, season, part)
        self.sources = episode_sources + show_sources

        # Remove duplicate sources
        self.append_cache_uncached_noduplicates()
        return {'cached': self.cached, 'uncached': self.uncached}

    def get_episode_sources(self, show, mal_id, episode, season, part, status):
        season_zfill = str(season).zfill(2) if season else '01'
        episode_zfill = str(episode).zfill(2) if episode is not None else '01'

        search_tasks = []

        # 1. Primary episode search: Show "- 01" or "S01E01"
        query1 = f'{show} "- {episode_zfill}"'
        search_tasks.append({'query': query1, 'name': 'primary_hyphen'})

        query2 = f'{show} "S{season_zfill}E{episode_zfill}"'
        search_tasks.append({'query': query2, 'name': 'primary_season_ep'})

        # 2. Batch/Complete series search (only for finished shows)
        if status in ["FINISHED", "Finished Airing"]:
            query3 = f'{show} "Batch"'
            search_tasks.append({'query': query3, 'name': 'batch'})

        control.log(f"Bitsearch: Running {len(search_tasks)} searches for episode {episode_zfill}")

        def run_search(task):
            try:
                sources = self.process_bitsearch_episodes(task['query'], mal_id, episode_zfill, season_zfill, part)
                control.log(f"Bitsearch: {task['name']} search returned {len(sources)} sources")
                return sources
            except Exception as e:
                control.log(f"Bitsearch: {task['name']} search failed: {e}", 'error')
                return []

        all_search_results = utils.parallel_process(search_tasks, run_search)

        bitsearch_sources = []
        for sources in all_search_results:
            bitsearch_sources.extend(sources)

        control.log(f"Bitsearch: Episode search complete - returning {len(bitsearch_sources)} total sources")
        return bitsearch_sources

    def get_show_sources(self, show, mal_id, episode, season, part):
        season_zfill = str(season).zfill(2) if season else '01'
        episode_zfill = str(episode).zfill(2) if episode is not None else '01'

        try:
            return self.process_bitsearch_episodes(show, mal_id, episode_zfill, season_zfill, part)
        except Exception as e:
            control.log(f"Bitsearch: Show search failed: {e}", 'error')
            return []

    def get_movie_sources(self, query, mal_id):
        control.log(f"Bitsearch: Searching movie sources for '{query}'")
        try:
            self.sources = self.process_bitsearch_movie(query, mal_id)
        except Exception as e:
            control.log(f"Bitsearch: Movie search failed: {e}", 'error')
            self.sources = []

        self.append_cache_uncached_noduplicates()
        return {'cached': self.cached, 'uncached': self.uncached}

    def process_bitsearch_episodes(self, query, mal_id, episode, season, part):
        raw_results = self._fetch_search_results(query)
        if not raw_results:
            return []

        filtered_list = source_utils.filter_sources('bitsearch', raw_results, mal_id, int(season), int(episode), part)
        cache_list, uncached_list_ = Debrid().torrentCacheCheck(filtered_list, mal_id=mal_id, episode=episode, media_type=self.media_type, rescrape=self.rescrape)

        cache_list = sorted(cache_list, key=lambda k: k.get('seeders', 0), reverse=True)
        uncached_list = [i for i in uncached_list_ if i.get('seeders', 0) > 0]
        uncached_list = sorted(uncached_list, key=lambda k: k.get('seeders', 0), reverse=True)

        mapfunc = partial(self.parse_bitsearch_view, episode=episode)
        bitsearch_sources = utils.parallel_process(cache_list, mapfunc) if cache_list else []

        if uncached_list and control.getBool('show.uncached'):
            mapfunc2 = partial(self.parse_bitsearch_view, episode=episode, cached=False)
            bitsearch_sources += utils.parallel_process(uncached_list, mapfunc2)

        return bitsearch_sources

    def process_bitsearch_movie(self, query, mal_id):
        raw_results = self._fetch_search_results(query)
        if not raw_results:
            return []

        filtered_list = source_utils.filter_sources('bitsearch', raw_results, mal_id)
        cache_list, uncached_list_ = Debrid().torrentCacheCheck(filtered_list, mal_id=mal_id, episode='1', media_type='movie', rescrape=self.rescrape)

        cache_list = sorted(cache_list, key=lambda k: k.get('seeders', 0), reverse=True)
        uncached_list = [i for i in uncached_list_ if i.get('seeders', 0) > 0]
        uncached_list = sorted(uncached_list, key=lambda k: k.get('seeders', 0), reverse=True)

        mapfunc = partial(self.parse_bitsearch_view, episode='1')
        bitsearch_sources = utils.parallel_process(cache_list, mapfunc) if cache_list else []

        if uncached_list and control.getBool('show.uncached'):
            mapfunc2 = partial(self.parse_bitsearch_view, episode='1', cached=False)
            bitsearch_sources += utils.parallel_process(uncached_list, mapfunc2)

        return bitsearch_sources

    def _fetch_search_results(self, query):
        clean_q = re.sub(r'[^A-Za-z0-9\s\.-]+', ' ', query).strip()
        url = f"{self._BASE_URL}/search?q={urllib.parse.quote_plus(clean_q)}&sort=size"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }

        response = client.get(url, headers=headers, timeout=10)
        if not response or getattr(response, 'status_code', None) != 200:
            return []

        html_text = response.text if hasattr(response, 'text') else str(response)
        return self._parse_html_results(html_text)

    def _parse_html_results(self, html_text):
        if not html_text or 'magnet:?' not in html_text:
            return []

        soup = BeautifulSoup(html_text, 'html.parser')
        cards = soup.find_all('div', class_='torrent-result-card')
        results = []
        seen_hashes = set()

        # Fallback if cards not found by class: search all magnet link elements
        if not cards:
            mag_tags = soup.find_all('a', href=lambda h: h and 'magnet:?' in h)
            for mag_tag in mag_tags:
                card = mag_tag.find_parent('div')
                if card and card not in cards:
                    cards.append(card)

        for card in cards:
            try:
                mag_tag = card.find('a', href=lambda h: h and 'magnet:?' in h)
                if not mag_tag:
                    continue

                full_mag = html.unescape(mag_tag['href'])
                hash_match = re.search(r'btih:([a-fA-F0-9]{40})', full_mag, re.I)
                if not hash_match:
                    continue

                info_hash = hash_match.group(1).lower()
                if info_hash in seen_hashes:
                    continue
                seen_hashes.add(info_hash)

                # Title resolution
                title_tag = card.find('h3') or card.find('h2') or card.find('h4') or card.find('h5')
                if title_tag:
                    name = title_tag.get_text(strip=True)
                else:
                    dn_match = re.search(r'dn=([^&]+)', full_mag)
                    if dn_match:
                        name = urllib.parse.unquote(dn_match.group(1))
                    else:
                        name = 'Unknown'
                name = re.sub(r'^\[Bitsearch\.to\]\s*', '', name, flags=re.I).strip()

                card_text = card.get_text(' ', strip=True)

                # Size resolution
                size_match = re.search(r'([\d.]+\s*(?:GB|MB|KB|B))', card_text)
                size_str = size_match.group(1) if size_match else '0 B'

                # Byte size conversion
                byte_size = 0
                sz_parts = re.match(r'([\d.]+)\s*(\w+)', size_str)
                if sz_parts:
                    try:
                        byte_size = source_utils.convert_to_bytes(float(sz_parts.group(1)), sz_parts.group(2))
                    except (ValueError, KeyError):
                        byte_size = 0

                # Swarm metrics
                seed_match = re.search(r'(\d+)\s*seeders', card_text, re.I)
                seeders = int(seed_match.group(1)) if seed_match else 0

                leech_match = re.search(r'(\d+)\s*leechers', card_text, re.I)
                leechers = int(leech_match.group(1)) if leech_match else 0

                dl_match = re.search(r'(\d+)\s*downloads', card_text, re.I)
                downloads = int(dl_match.group(1)) if dl_match else 0

                results.append({
                    'name': name,
                    'hash': info_hash,
                    'magnet': full_mag,
                    'size': size_str,
                    'byte_size': byte_size,
                    'seeders': seeders,
                    'leechers': leechers,
                    'downloads': downloads,
                })
            except Exception as e:
                control.log(f"Bitsearch: error parsing card: {e}", 'warning')
                continue

        return results

    @staticmethod
    def parse_bitsearch_view(res, episode, cached=True):
        source = {
            'release_title': res['name'],
            'hash': res['hash'],
            'type': 'torrent',
            'quality': source_utils.getQuality(res['name']),
            'debrid_provider': res.get('debrid_provider'),
            'provider': 'bitsearch',
            'episode_re': episode,
            'size': res['size'],
            'byte_size': res.get('byte_size', 0),
            'info': source_utils.getInfo(res['name']),
            'lang': source_utils.getAudio_lang(res['name']),
            'channel': source_utils.getAudio_channel(res['name']),
            'sub': source_utils.getSubtitle_lang(res['name']),
            'cached': cached,
            'seeders': res.get('seeders', 0),
        }

        if not cached:
            source['magnet'] = res.get('magnet', '')
            source['type'] += ' (uncached)'

        return source

    def append_cache_uncached_noduplicates(self):
        unique = {}
        for source in self.sources:
            key = (source.get('hash'), source.get('debrid_provider'))
            if not key[0]:
                continue
            if key in unique:
                current = unique[key]
                if source.get('seeders', -1) > current.get('seeders', -1):
                    unique[key] = source
                elif (source.get('seeders', -1) == current.get('seeders', -1)
                      and source.get('byte_size', 0) > current.get('byte_size', 0)):
                    unique[key] = source
            else:
                unique[key] = source

        self.cached = []
        self.uncached = []
        for source in unique.values():
            if source.get('cached'):
                self.cached.append(source)
            else:
                self.uncached.append(source)
