import json
import re
import urllib.parse
from functools import partial

from resources.lib.debrid import Debrid
from resources.lib.ui import database, source_utils, control, client, utils, domains
from resources.lib.ui.BrowserBase import BrowserBase


class Sources(BrowserBase):
    _BASE_URL = domains.get_domain('piratebay', 'https://apibay.org')

    def __init__(self):
        self.media_type = None
        self.cached = []
        self.uncached = []
        self.sources = []
        self.rescrape = False

    @staticmethod
    def _parse_titles(query):
        """Extract individual titles from the '(Title1)|(Title2)' format."""
        titles = re.findall(r'\(([^)]+)\)', query)
        if not titles:
            titles = [p.strip() for p in query.split('|') if p.strip()]
        seen = set()
        unique = []
        for t in titles:
            t_stripped = t.strip()
            if t_stripped and t_stripped.lower() not in seen:
                seen.add(t_stripped.lower())
                unique.append(t_stripped)
        return unique

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
        titles = self._parse_titles(show)

        search_tasks = []
        for title in titles:
            # 1. Primary episode search: Title "01" (without "- " so Sphinx does not treat it as negation) or "S01E01"
            query1 = f'{title} {episode_zfill}'
            search_tasks.append({'query': query1, 'name': f'primary_ep:{title}'})

            query2 = f'{title} S{season_zfill}E{episode_zfill}'
            search_tasks.append({'query': query2, 'name': f'primary_season_ep:{title}'})

            # 2. Batch/Complete series search (only for finished shows)
            if status in ["FINISHED", "Finished Airing"]:
                query3 = f'{title} Batch'
                search_tasks.append({'query': query3, 'name': f'batch:{title}'})

        control.log(f"PirateBay: Running {len(search_tasks)} searches for episode {episode_zfill}")

        def run_search(task):
            try:
                raw_results = self._fetch_apibay_results(task['query'], cat='205,208')
                if not raw_results:
                    return []
                filtered = source_utils.filter_sources('piratebay', raw_results, mal_id, int(season_zfill), int(episode_zfill), part)
                control.log(f"PirateBay: {task['name']} search returned {len(filtered)} sources")
                return filtered
            except Exception as e:
                control.log(f"PirateBay: {task['name']} search failed: {e}", 'error')
                return []

        all_search_results = utils.parallel_process(search_tasks, run_search) if search_tasks else []

        seen_hashes = set()
        combined = []
        for torrents in all_search_results:
            for t in torrents:
                h = t.get('hash', '').lower()
                if h and h not in seen_hashes:
                    t['hash'] = h
                    seen_hashes.add(h)
                    combined.append(t)

        if not combined:
            return []

        cache_list, uncached_list_ = Debrid().torrentCacheCheck(combined, mal_id=mal_id, episode=episode_zfill, media_type=self.media_type, rescrape=self.rescrape)
        cache_list = sorted(cache_list, key=lambda k: k.get('seeders', 0), reverse=True)
        uncached_list = [i for i in uncached_list_ if i.get('seeders', 0) > 0]
        uncached_list = sorted(uncached_list, key=lambda k: k.get('seeders', 0), reverse=True)

        mapfunc = partial(self.parse_piratebay_view, episode=episode_zfill)
        piratebay_sources = utils.parallel_process(cache_list, mapfunc) if cache_list else []

        if uncached_list and control.getBool('show.uncached'):
            mapfunc2 = partial(self.parse_piratebay_view, episode=episode_zfill, cached=False)
            piratebay_sources += utils.parallel_process(uncached_list, mapfunc2)

        control.log(f"PirateBay: Episode search complete - returning {len(piratebay_sources)} total sources")
        return piratebay_sources

    def get_show_sources(self, show, mal_id, episode, season, part):
        season_zfill = str(season).zfill(2) if season else '01'
        episode_zfill = str(episode).zfill(2) if episode is not None else '01'
        titles = self._parse_titles(show)
        search_tasks = [{'query': title, 'name': f'show:{title}'} for title in titles]

        def run_search(task):
            try:
                raw_results = self._fetch_apibay_results(task['query'], cat='205,208')
                if not raw_results:
                    return []
                return source_utils.filter_sources('piratebay', raw_results, mal_id, int(season_zfill), int(episode_zfill), part)
            except Exception as e:
                control.log(f"PirateBay: {task['name']} search failed: {e}", 'error')
                return []

        all_search_results = utils.parallel_process(search_tasks, run_search) if search_tasks else []

        seen_hashes = set()
        combined = []
        for torrents in all_search_results:
            for t in torrents:
                h = t.get('hash', '').lower()
                if h and h not in seen_hashes:
                    t['hash'] = h
                    seen_hashes.add(h)
                    combined.append(t)

        if not combined:
            return []

        cache_list, uncached_list_ = Debrid().torrentCacheCheck(combined, mal_id=mal_id, episode=episode_zfill, media_type=self.media_type, rescrape=self.rescrape)
        cache_list = sorted(cache_list, key=lambda k: k.get('seeders', 0), reverse=True)
        uncached_list = [i for i in uncached_list_ if i.get('seeders', 0) > 0]
        uncached_list = sorted(uncached_list, key=lambda k: k.get('seeders', 0), reverse=True)

        mapfunc = partial(self.parse_piratebay_view, episode=episode_zfill)
        piratebay_sources = utils.parallel_process(cache_list, mapfunc) if cache_list else []

        if uncached_list and control.getBool('show.uncached'):
            mapfunc2 = partial(self.parse_piratebay_view, episode=episode_zfill, cached=False)
            piratebay_sources += utils.parallel_process(uncached_list, mapfunc2)

        return piratebay_sources

    def get_movie_sources(self, query, mal_id):
        control.log(f"PirateBay: Searching movie sources for '{query}'")
        titles = self._parse_titles(query)
        search_tasks = [{'query': title, 'name': f'movie:{title}'} for title in titles]

        def run_search(task):
            try:
                raw_results = self._fetch_apibay_results(task['query'], cat='201,207')
                if not raw_results:
                    return []
                return source_utils.filter_sources('piratebay', raw_results, mal_id)
            except Exception as e:
                control.log(f"PirateBay: {task['name']} search failed: {e}", 'error')
                return []

        all_search_results = utils.parallel_process(search_tasks, run_search) if search_tasks else []

        seen_hashes = set()
        combined = []
        for torrents in all_search_results:
            for t in torrents:
                h = t.get('hash', '').lower()
                if h and h not in seen_hashes:
                    t['hash'] = h
                    seen_hashes.add(h)
                    combined.append(t)

        if combined:
            cache_list, uncached_list_ = Debrid().torrentCacheCheck(combined, mal_id=mal_id, episode='1', media_type='movie', rescrape=self.rescrape)
            cache_list = sorted(cache_list, key=lambda k: k.get('seeders', 0), reverse=True)
            uncached_list = [i for i in uncached_list_ if i.get('seeders', 0) > 0]
            uncached_list = sorted(uncached_list, key=lambda k: k.get('seeders', 0), reverse=True)

            mapfunc = partial(self.parse_piratebay_view, episode='1')
            self.sources = utils.parallel_process(cache_list, mapfunc) if cache_list else []

            if uncached_list and control.getBool('show.uncached'):
                mapfunc2 = partial(self.parse_piratebay_view, episode='1', cached=False)
                self.sources += utils.parallel_process(uncached_list, mapfunc2)
        else:
            self.sources = []

        self.append_cache_uncached_noduplicates()
        return {'cached': self.cached, 'uncached': self.uncached}

    def process_piratebay_episodes(self, query, mal_id, episode, season, part):
        raw_results = self._fetch_apibay_results(query, cat='205,208')
        if not raw_results:
            return []

        filtered_list = source_utils.filter_sources('piratebay', raw_results, mal_id, int(season), int(episode), part)
        cache_list, uncached_list_ = Debrid().torrentCacheCheck(filtered_list, mal_id=mal_id, episode=episode, media_type=self.media_type, rescrape=self.rescrape)

        cache_list = sorted(cache_list, key=lambda k: k.get('seeders', 0), reverse=True)
        uncached_list = [i for i in uncached_list_ if i.get('seeders', 0) > 0]
        uncached_list = sorted(uncached_list, key=lambda k: k.get('seeders', 0), reverse=True)

        mapfunc = partial(self.parse_piratebay_view, episode=episode)
        piratebay_sources = utils.parallel_process(cache_list, mapfunc) if cache_list else []

        if uncached_list and control.getBool('show.uncached'):
            mapfunc2 = partial(self.parse_piratebay_view, episode=episode, cached=False)
            piratebay_sources += utils.parallel_process(uncached_list, mapfunc2)

        return piratebay_sources

    def process_piratebay_movie(self, query, mal_id):
        raw_results = self._fetch_apibay_results(query, cat='201,207')
        if not raw_results:
            return []

        filtered_list = source_utils.filter_sources('piratebay', raw_results, mal_id)
        cache_list, uncached_list_ = Debrid().torrentCacheCheck(filtered_list, mal_id=mal_id, episode='1', media_type='movie', rescrape=self.rescrape)

        cache_list = sorted(cache_list, key=lambda k: k.get('seeders', 0), reverse=True)
        uncached_list = [i for i in uncached_list_ if i.get('seeders', 0) > 0]
        uncached_list = sorted(uncached_list, key=lambda k: k.get('seeders', 0), reverse=True)

        mapfunc = partial(self.parse_piratebay_view, episode='1')
        piratebay_sources = utils.parallel_process(cache_list, mapfunc) if cache_list else []

        if uncached_list and control.getBool('show.uncached'):
            mapfunc2 = partial(self.parse_piratebay_view, episode='1', cached=False)
            piratebay_sources += utils.parallel_process(uncached_list, mapfunc2)

        return piratebay_sources

    def _fetch_apibay_results(self, query, cat='205,208'):
        clean_q = re.sub(r'[^A-Za-z0-9\s\.-]+', ' ', query).strip()
        url = f"{self._BASE_URL.rstrip('/')}/q.php?q={urllib.parse.quote_plus(clean_q)}&cat={cat}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json',
        }

        response = client.get(url, headers=headers, timeout=10)
        if not response:
            return []

        try:
            if hasattr(response, 'json'):
                data = response.json()
            elif isinstance(response, (dict, list)):
                data = response
            else:
                sentinel = object()
                data = control.loads_json(str(response), default=sentinel)
                if data is sentinel:
                    raise ValueError("Invalid JSON payload")
        except Exception as e:
            control.log(f"PirateBay: JSON decode error: {e}", 'warning')
            return []

        return self._parse_apibay_results(data)

    def _parse_apibay_results(self, data):
        if isinstance(data, str):
            data = control.loads_json(data, default=[])

        if not isinstance(data, list):
            return []

        results = []
        seen_hashes = set()

        for item in data:
            try:
                # Handle empty API response
                if not isinstance(item, dict):
                    continue
                if str(item.get('id', '')) == '0' or item.get('name') == 'No results returned':
                    continue

                info_hash = str(item.get('info_hash', '')).strip().lower()
                if not info_hash or len(info_hash) != 40 or info_hash in seen_hashes:
                    continue
                seen_hashes.add(info_hash)

                name = str(item.get('name', '')).strip()
                if not name:
                    continue

                seeders = int(item.get('seeders', 0)) if str(item.get('seeders', '')).isdigit() else 0
                leechers = int(item.get('leechers', 0)) if str(item.get('leechers', '')).isdigit() else 0

                try:
                    byte_size = int(item.get('size', 0))
                except (ValueError, TypeError):
                    byte_size = 0
                size_str = self._format_size(byte_size)

                magnet = f"magnet:?xt=urn:btih:{info_hash}&dn={urllib.parse.quote(name)}"

                results.append({
                    'name': name,
                    'hash': info_hash,
                    'magnet': magnet,
                    'size': size_str,
                    'byte_size': byte_size,
                    'seeders': seeders,
                    'leechers': leechers,
                    'downloads': 0,
                })
            except Exception as e:
                control.log(f"PirateBay: error parsing result: {e}", 'warning')
                continue

        return results

    @staticmethod
    def _format_size(filesize_bytes):
        try:
            size = int(filesize_bytes)
        except (ValueError, TypeError):
            return '0 B'
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f'{size:.2f} {unit}'
            size /= 1024
        return f'{size:.2f} PB'

    @staticmethod
    def parse_piratebay_view(res, episode, cached=True):
        source = {
            'release_title': res['name'],
            'hash': res['hash'],
            'type': 'torrent',
            'quality': source_utils.getQuality(res['name']),
            'debrid_provider': res.get('debrid_provider'),
            'provider': 'piratebay',
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
