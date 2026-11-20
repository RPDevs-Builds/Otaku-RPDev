import re
import threading

from functools import partial
from bs4 import BeautifulSoup, SoupStrainer
from resources.lib.debrid import Debrid
from resources.lib.ui import database, source_utils, control, client, utils, domains
from resources.lib.ui.BrowserBase import BrowserBase


class Sources(BrowserBase):
    _DIRECT_URL = 'https://nyaa.si/'
    _ALT_URL = 'https://nyaa-si.translate.goog/?_x_tr_sl=es&_x_tr_tl=en&_x_tr_hl=en'
    _BASE_URL = domains.get_domain('nyaa', _DIRECT_URL)

    def __init__(self):
        self._BASE_URL = domains.get_domain('nyaa', self._BASE_URL) or self._DIRECT_URL
        self._host_lock = threading.Lock()
        self._active_base_url = self._BASE_URL
        self._fallback_base_url = self._DIRECT_URL if 'translate.goog' in self._BASE_URL else self._ALT_URL
        self._fallback_logged = False
        self._both_failed_logged = False
        self.media_type = None
        self.cached = []
        self.uncached = []
        self.sources = []
        self.rescrape = False
        self.filter_kwargs = {}
        self.absolute_episode = None

    def _fetch_html(self, params, url_override=None):
        """Fetch Nyaa search HTML with automatic direct <-> alt proxy fallback and diagnostics."""
        with self._host_lock:
            primary_base = url_override or self._active_base_url
            fallback_base = self._fallback_base_url

        def _try_host(base_url):
            resp = client.get(base_url, params=params)
            if not resp:
                return None, 'no_response'
            status = getattr(resp, 'status_code', 200)
            html = getattr(resp, 'text', '') or ''
            if isinstance(status, int) and status >= 400:
                return None, f'http_{status}'
            if 'table-responsive' not in html and 'No results found' not in html and 'nyaa' not in html.lower():
                return None, f'unexpected_html(len={len(html)})'
            return html, 'ok'

        html, primary_reason = _try_host(primary_base)
        if html is not None:
            return html

        if not url_override and fallback_base and fallback_base != primary_base:
            with self._host_lock:
                should_log = not self._fallback_logged
                if should_log:
                    self._fallback_logged = True
            if should_log:
                control.log(
                    f"Nyaa: primary host {primary_base} failed ({primary_reason}); trying fallback {fallback_base}",
                    'warning',
                )
            fb_html, fb_reason = _try_host(fallback_base)
            if fb_html is not None:
                with self._host_lock:
                    if self._active_base_url == primary_base:
                        self._active_base_url = fallback_base
                        self._fallback_base_url = primary_base
                        control.log(f"Nyaa: switched active host to {fallback_base}", 'info')
                return fb_html
            with self._host_lock:
                should_log_both = not self._both_failed_logged
                if should_log_both:
                    self._both_failed_logged = True
            if should_log_both:
                control.log(
                    f"Nyaa: both primary ({primary_reason}) and fallback ({fb_reason}) hosts failed",
                    'warning',
                )
        return None

    def get_sources(self, query, mal_id, episode, status, media_type, season=None, part=None, rescrape=False, hints=None):
        query = self._clean_title(query).replace('-', ' ')
        self.show = query
        self.media_type = media_type
        self.rescrape = rescrape
        self.filter_kwargs = source_utils.filter_kwargs(hints)
        self.absolute_episode = (hints or {}).get('absolute_episode')
        if media_type == 'movie':
            return self.get_movie_sources(query, mal_id)

        self.sources = self.get_episode_sources(query, mal_id, episode, season, part, status, include_show_pack=True)

        if not self.sources and ':' in query:
            q1, q2 = query.split('|', 2)
            q1 = q1[1:-1].split(':')[0]
            q2 = q2[1:-1].split(':')[0]
            query2 = '({0})|({1})'.format(q1, q2)
            self.sources = self.get_episode_sources(query2, mal_id, episode, season, part, status, include_show_pack=True)

        # remove any duplicate sources
        self.append_cache_uncached_noduplicates()
        return {'cached': self.cached, 'uncached': self.uncached}

    def get_episode_sources(self, show, mal_id, episode, season, part, status, include_show_pack=False):
        season_zfill = str(season).zfill(2) if season else '01'
        episode_zfill = str(episode).zfill(2) if episode is not None else '01'

        # Build all search queries
        search_tasks = []

        # Primary episode search
        query1 = f'{show} "- {episode_zfill}"|"S{season_zfill}E{episode_zfill}"'
        if self.absolute_episode:
            query1 += f'|"- {str(self.absolute_episode).zfill(2)}"'
        search_tasks.append({
            'query': query1,
            'params': {'f': '0', 'c': '1_0', 'q': query1.replace(' ', '+'), 's': 'downloads', 'o': 'desc'},
            'name': 'primary'
        })

        # Batch/Complete series search (only for finished shows)
        if status in ["FINISHED", "Finished Airing"]:
            query2 = '%s "Batch"|"Complete Series"' % show
            show_data = database.get_show(mal_id)
            episodes = 0
            if show_data and show_data.get('kodi_meta'):
                try:
                    episodes = database.loads(show_data['kodi_meta']).get('episodes', 0)
                except Exception:
                    episodes = 0
            if episodes:
                episodes_zfill = str(episodes).zfill(2)
                query2 += f'|"01-{episodes_zfill}"|"01~{episodes_zfill}"|"01 - {episodes_zfill}"|"01 ~ {episodes_zfill}"|"E{episodes_zfill}"|"Episode {episodes_zfill}"'
            if season_zfill:
                query2 += f'|"S{season_zfill}"|"Season {season_zfill}"'
            if episode_zfill and season_zfill:
                query2 += f'|"{season_zfill}-{episode_zfill}"|"{season_zfill}~{episode_zfill}"|"{season_zfill} - {episode_zfill}"|"{season_zfill} ~ {episode_zfill}"'
                query2 += f'|"S{season_zfill}E{episode_zfill}"'
            query2 += f'|"- {episode_zfill}"'

            search_tasks.append({
                'query': query2,
                'params': {'f': '0', 'c': '1_0', 'q': query2.replace(' ', '+'), 's': 'seeders', 'o': 'desc'},
                'name': 'batch'
            })

        # Season search
        query4 = show
        if 'season' in show.lower():
            matches = [re.match(r'\(?.+?(?=season)', title.strip(), re.IGNORECASE) for title in show.split('|')]
            cleaned = []
            for m in matches:
                if m:
                    part_str = m.group(0).strip()
                    if part_str.startswith('(') and not part_str.endswith(')'):
                        part_str += ')'
                    if part_str and part_str != '()':
                        cleaned.append(part_str)
            if cleaned:
                query4 = '|'.join(cleaned)

        search_tasks.append({
            'query': query4,
            'params': {'f': '0', 'c': '1_0', 'q': query4.replace(' ', '+')},
            'name': 'additional'
        })

        # C-23: For arc-subtitled sequels (season >= 2 with ':' or ' - '), also search
        # franchise base + SxxExx / Sxx / Season N in parallel so English Dub/Dual-Audio
        # releases omitting the MAL arc subtitle are found on the first pass.
        try:
            season_int = int(season) if season is not None and str(season).isdigit() else 1
        except (ValueError, TypeError):
            season_int = 1
        if season_int >= 2 and (':' in show or ' - ' in show):
            base_titles = []
            for raw_part in show.split('|'):
                cleaned_p = raw_part.strip('() ')
                base = None
                if ':' in cleaned_p:
                    base = cleaned_p.split(':', 1)[0].strip()
                elif ' - ' in cleaned_p:
                    base = cleaned_p.split(' - ', 1)[0].strip()
                if base and len(base) >= 3 and base not in base_titles:
                    base_titles.append(base)
            if base_titles:
                base_expr = '|'.join(f'({b})' for b in base_titles)
                query5 = f'{base_expr} "S{season_zfill}E{episode_zfill}"|"S{season_zfill}"|"Season {season_int}"|"Season {season_zfill}"'
                search_tasks.append({
                    'query': query5,
                    'params': {'f': '0', 'c': '1_0', 'q': query5.replace(' ', '+'), 's': 'downloads', 'o': 'desc'},
                    'name': 'sequel_season_base'
                })

        if include_show_pack:
            search_tasks.append({
                'query': show,
                'params': {'f': '0', 'c': '1_0', 'q': show.replace(' ', '+'), 's': 'downloads', 'o': 'desc'},
                'name': 'show_pack',
                'is_show_pack': True,
            })

        # Execute all searches in parallel
        control.log(f"Nyaa: Running {len(search_tasks)} searches in parallel for episode {episode_zfill}")

        def run_search(task):
            try:
                filtered = self._fetch_and_filter_episodes(None, task['params'], mal_id, episode_zfill, season_zfill, part, show_title=show)
                is_pack = bool(task.get('is_show_pack'))
                for item in filtered:
                    item['_is_show_pack'] = is_pack
                control.log(f"Nyaa: {task['name']} search returned {len(filtered)} filtered torrents")
                return filtered
            except Exception as e:
                control.log(f"Nyaa: {task['name']} search failed: {str(e)}", 'warning')
                return []

        all_search_results = utils.parallel_process(search_tasks, run_search)

        # Deduplicate candidate torrents across parallel tasks before calling Debrid().torrentCacheCheck once
        seen_hashes = {}
        combined = []
        for torrents in all_search_results:
            for t in torrents:
                h = t.get('hash', '').lower()
                if not h:
                    continue
                if h not in seen_hashes:
                    t['hash'] = h
                    seen_hashes[h] = t
                    combined.append(t)
                elif not t.get('_is_show_pack') and seen_hashes[h].get('_is_show_pack'):
                    seen_hashes[h]['_is_show_pack'] = False

        if not combined:
            return []

        cache_list, uncashed_list_ = Debrid().torrentCacheCheck(combined, mal_id=mal_id, episode=episode_zfill, media_type=self.media_type, rescrape=self.rescrape)
        cache_list = sorted(cache_list, key=lambda k: k['downloads'], reverse=True)

        uncashed_list = [i for i in uncashed_list_ if i['seeders'] > 0]
        uncashed_list = sorted(uncashed_list, key=lambda k: k['seeders'], reverse=True)

        def _parse_entry(item, cached=True):
            return self.parse_nyaa_view(item, episode=episode_zfill, cached=cached, is_show_pack=bool(item.get('_is_show_pack')))

        nyaa_sources = utils.parallel_process(cache_list, partial(_parse_entry, cached=True)) if cache_list else []
        if control.getBool('show.uncached') and uncashed_list:
            nyaa_sources += utils.parallel_process(uncashed_list, partial(_parse_entry, cached=False))

        control.log(f"Nyaa: Episode search complete - returning {len(nyaa_sources)} total sources")
        return nyaa_sources

    def get_show_sources(self, show, mal_id, episode, season, part):
        control.log(f"Nyaa: Searching show/batch sources for '{show}'")
        season_zfill = str(season).zfill(2) if season else '01'
        episode_zfill = str(episode).zfill(2) if episode is not None else '01'
        query = show

        params = {
            'f': '0',
            'c': '1_0',
            'q': query.replace(' ', '+'),
            's': 'downloads',
            'o': 'desc'
        }

        nyaa_sources = self.process_nyaa_episodes(self._BASE_URL, params, mal_id, episode_zfill, season_zfill, part, show_title=show, is_show_pack=True)
        control.log(f"Nyaa: Show search complete - found {len(nyaa_sources)} sources")
        return nyaa_sources

    def get_movie_sources(self, query, mal_id):
        control.log(f"Nyaa: Searching movie sources for '{query}'")
        params = {
            'f': '0',
            'c': '1_2',
            'q': query.replace(' ', '+'),
            's': 'downloads',
            'o': 'desc'
        }

        self.sources = self.process_nyaa_movie(self._BASE_URL, params, mal_id)

        # make sure no duplicate sources
        self.append_cache_uncached_noduplicates()
        return {'cached': self.cached, 'uncached': self.uncached}

    def _fetch_and_filter_episodes(self, url, params, mal_id, episode_zfill, season_zfill, part, show_title=None):
        html = self._fetch_html(params, url_override=url)
        if html:
            mlink = SoupStrainer('div', {'class': 'table-responsive'})
            soup = BeautifulSoup(html, "html.parser", parse_only=mlink)
            rex = r'(magnet:)+[^"]*'
            list_ = []
            for i in soup.find_all('tr', class_=['danger', 'default', 'success']):
                magnet_tag = i.find('a', {'href': re.compile(rex)})
                if not magnet_tag:
                    continue
                title_links = i.find_all('a', {'class': None})
                if len(title_links) < 2:
                    continue
                tds = i.find_all('td', {'class': 'text-center'})
                if len(tds) < 3:
                    continue
                magnet_href = magnet_tag.get('href', '')
                hashes = re.findall(r'btih:(.*?)(?:&|$)', magnet_href)
                if not hashes:
                    continue
                name = title_links[1].get('title') or title_links[1].text.strip()
                if not name:
                    continue
                list_.append({
                    'magnet': magnet_href,
                    'name': name,
                    'size': tds[1].text.replace('i', ''),
                    'downloads': int(tds[-1].text),
                    'seeders': int(tds[-3].text),
                    'hash': hashes[0].lower()
                })

            target_show = show_title or getattr(self, 'show', None)
            aliases = None
            if target_show and '|' in target_show:
                parts = [p.strip('() ') for p in target_show.split('|') if p.strip('() ')]
                if parts:
                    target_show = parts[0]
                    if len(parts) > 1:
                        aliases = parts[1:]

            if target_show:
                return source_utils.filter_sources(
                    'nyaa', list_, mal_id, int(season_zfill), int(episode_zfill), part,
                    show_title=target_show, aliases=aliases, **self.filter_kwargs
                )
            return source_utils.filter_sources(
                'nyaa', list_, mal_id, int(season_zfill), int(episode_zfill), part,
                **self.filter_kwargs
            )
        return []

    def process_nyaa_episodes(self, url, params, mal_id, episode_zfill, season_zfill, part, show_title=None, is_show_pack=False):
        filtered_list = self._fetch_and_filter_episodes(url, params, mal_id, episode_zfill, season_zfill, part, show_title=show_title)
        if filtered_list:
            cache_list, uncashed_list_ = Debrid().torrentCacheCheck(filtered_list, mal_id=mal_id, episode=episode_zfill, media_type=self.media_type, rescrape=self.rescrape)
            cache_list = sorted(cache_list, key=lambda k: k['downloads'], reverse=True)

            uncashed_list = [i for i in uncashed_list_ if i['seeders'] > 0]
            uncashed_list = sorted(uncashed_list, key=lambda k: k['seeders'], reverse=True)

            # Parse sources in parallel for faster processing
            mapfunc = partial(self.parse_nyaa_view, episode=episode_zfill, is_show_pack=is_show_pack)
            all_results = utils.parallel_process(cache_list, mapfunc) if cache_list else []
            if control.getBool('show.uncached') and uncashed_list:
                mapfunc2 = partial(self.parse_nyaa_view, episode=episode_zfill, cached=False, is_show_pack=is_show_pack)
                all_results += utils.parallel_process(uncashed_list, mapfunc2)
            return all_results
        return []

    def process_nyaa_movie(self, url, params, mal_id):
        res = self._fetch_html(params, url_override=None if url == self._BASE_URL else url)
        if res:
            results = BeautifulSoup(res, 'html.parser')
            rex = r'(magnet:)+[^"]*'
            search_results = [
                (i.find_all('a', {'href': re.compile(rex)})[0].get('href'),
                 i.find_all('a', {'class': None})[1].get('title'),
                 i.find_all('td', {'class': 'text-center'})[1].text,
                 i.find_all('td', {'class': 'text-center'})[-1].text,
                 i.find_all('td', {'class': 'text-center'})[-3].text
                 ) for i in results.find_all('tr', class_=['danger', 'default', 'success'])
                if i.find_all('a', {'href': re.compile(rex)})
            ]

            list_ = [
                {
                    'magnet': magnet,
                    'name': name,
                    'size': size.replace('i', ''),
                    'downloads': int(downloads),
                    'seeders': int(seeders)
                } for magnet, name, size, downloads, seeders in search_results
            ]

            for idx, torrent in enumerate(list_):
                torrent['hash'] = re.findall(r'btih:(.*?)(?:&|$)', torrent['magnet'])[0].lower()

            filtered_list = source_utils.filter_sources('nyaa', list_, mal_id)

            cache_list, uncashed_list_ = Debrid().torrentCacheCheck(filtered_list, mal_id=mal_id, episode='1', media_type='movie', rescrape=self.rescrape)
            cache_list = sorted(cache_list, key=lambda k: k['downloads'], reverse=True)

            uncashed_list = [i for i in uncashed_list_ if i['seeders'] > 0]
            uncashed_list = sorted(uncashed_list, key=lambda k: k['seeders'], reverse=True)

            # Parse sources in parallel for faster processing
            mapfunc = partial(self.parse_nyaa_view, episode=1)
            all_results = utils.parallel_process(cache_list, mapfunc) if cache_list else []
            if control.getBool('show.uncached') and uncashed_list:
                mapfunc2 = partial(self.parse_nyaa_view, episode=1, cached=False)
                all_results += utils.parallel_process(uncashed_list, mapfunc2)
            return all_results
        return []

    @staticmethod
    def parse_nyaa_view(res, episode, cached=True, is_show_pack=False):
        source = {
            'release_title': res['name'],
            'hash': res['hash'],
            'type': 'torrent',
            'quality': source_utils.getQuality(res['name']),
            'debrid_provider': res.get('debrid_provider'),
            'provider': 'nyaa',
            'episode_re': episode,
            'size': res['size'],
            'byte_size': 0,
            'info': source_utils.get_release_info(res),
            'lang': source_utils.getAudio_lang(res['name']),
            'channel': source_utils.getAudio_channel(res['name']),
            'sub': source_utils.getSubtitle_lang(res['name']),
            'cached': cached,
            'seeders': res['seeders']
        }

        match = re.match(r'([\d.]+)\s*(\w+)', res['size'])
        if match:
            try:
                source['byte_size'] = source_utils.convert_to_bytes(float(match.group(1)), match.group(2))
            except (ValueError, KeyError):
                pass
        if not cached:
            source['magnet'] = res['magnet']
            source['type'] += ' (uncached)'

        source_utils.is_season_pack(source, is_show_pack=is_show_pack)

        return source

    def append_cache_uncached_noduplicates(self):
        # Keep one source per (hash, debrid_provider) so multiple providers can show for the same torrent
        unique = {}
        for source in self.sources:
            key = (source.get('hash'), source.get('debrid_provider'))
            if not key[0]:
                continue
            if key in unique:
                current = unique[key]
                # Compare seeders first; if equal, compare byte_size
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
            if source['cached']:
                self.cached.append(source)
            else:
                self.uncached.append(source)
