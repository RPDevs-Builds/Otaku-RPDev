import re
import base64
import threading

from functools import partial
from bs4 import BeautifulSoup
from resources.lib.ui.BrowserBase import BrowserBase
from resources.lib.ui import database, source_utils, client, control, utils, domains
from resources.lib.debrid import Debrid
from resources.lib.endpoints import anidb


class Sources(BrowserBase):
    _DIRECT_URL = 'https://animetosho.net/'
    _ALT_URL = 'https://animetosho-net.translate.goog/?_x_tr_sl=es&_x_tr_tl=en&_x_tr_hl=en'
    _BASE_URL = domains.get_domain('animetosho', _DIRECT_URL)

    def __init__(self):
        self._BASE_URL = domains.get_domain('animetosho', self._BASE_URL) or self._DIRECT_URL
        self._host_lock = threading.Lock()
        self._active_base_url = self._BASE_URL
        self._fallback_base_url = self._DIRECT_URL if 'translate.goog' in self._BASE_URL else self._ALT_URL
        self._fallback_logged = False
        self._both_failed_logged = False
        self.sources = []
        self.cached = []
        self.uncached = []
        self.anidb_id = None
        self.anidb_ep_id = None
        self.paging = control.getInt('animetosho.paging')
        self.rescrape = False
        self.filter_kwargs = {}
        self.absolute_episode = None

    def _fetch_search_content(self, params):
        """Fetch AnimeTosho search page with automatic direct <-> alt proxy fallback and diagnostics."""
        with self._host_lock:
            primary_base = self._active_base_url
            fallback_base = self._fallback_base_url

        def _try_host(base_url):
            url = domains.join_url(base_url, 'search')
            resp = client.get(url, params=params)
            if not resp:
                return None, 'no_response'
            status = getattr(resp, 'status_code', 200)
            html = getattr(resp, 'text', '') or ''
            if isinstance(status, int) and status >= 400:
                return None, f'http_{status}'
            soup = BeautifulSoup(html, "html.parser")
            content_div = soup.find('div', id='content')
            if not content_div:
                return None, f'missing_content(len={len(html)})'
            return content_div, 'ok'

        content_div, primary_reason = _try_host(primary_base)
        if content_div is not None:
            return content_div

        if fallback_base and fallback_base != primary_base:
            with self._host_lock:
                should_log = not self._fallback_logged
                if should_log:
                    self._fallback_logged = True
            if should_log:
                control.log(
                    f"AnimeTosho: primary host {primary_base} failed ({primary_reason}); trying fallback {fallback_base}",
                    'warning',
                )
            fb_div, fb_reason = _try_host(fallback_base)
            if fb_div is not None:
                with self._host_lock:
                    if self._active_base_url == primary_base:
                        self._active_base_url = fallback_base
                        self._fallback_base_url = primary_base
                        control.log(f"AnimeTosho: switched active host to {fallback_base}", 'info')
                return fb_div
            with self._host_lock:
                should_log_both = not self._both_failed_logged
                if should_log_both:
                    self._both_failed_logged = True
            if should_log_both:
                control.log(
                    f"AnimeTosho: both primary ({primary_reason}) and fallback ({fb_reason}) hosts failed",
                    'warning',
                )
        return None

    def get_sources(self, show, mal_id, episode, status, media_type, season=None, part=None, rescrape=False, hints=None):
        self.show = show
        self.rescrape = rescrape
        self.filter_kwargs = source_utils.filter_kwargs(hints)
        self.absolute_episode = (hints or {}).get('absolute_episode')
        control.log(f"Animetosho: Starting search for '{show}' episode {episode}")
        if media_type == "movie":
            return self.get_movie_sources(show, mal_id)

        self.sources = self.get_episode_sources(show, mal_id, episode, season, part, status, include_show_pack=True)
        control.log(f"Animetosho: Found {len(self.sources)} total episode+show sources")

        self.append_cache_uncached_noduplicates()
        control.log(f"Animetosho: Returning {len(self.cached)} cached + {len(self.uncached)} uncached = {len(self.cached) + len(self.uncached)} total sources")
        return {'cached': self.cached, 'uncached': self.uncached}

    def _resolve_anidb_id(self, mal_id):
        """Resolve AniDB ID from show_meta, mappings.db, or live AniZip/Simkl overlay."""
        show_meta = database.get_show_meta(mal_id)
        meta_ids = None
        if show_meta:
            meta_ids = database.loads(show_meta['meta_ids'])
            self.anidb_id = meta_ids.get('anidb_id')
        if not self.anidb_id:
            mp = database.resolve_mappings_with_fallback(mal_id, required_keys=('anidb_id',))
            if mp and mp.get('anidb_id'):
                self.anidb_id = mp['anidb_id']
                if show_meta and isinstance(meta_ids, dict):
                    meta_ids['anidb_id'] = self.anidb_id
                    database.update_show_meta(mal_id, meta_ids, database.loads(show_meta['art']))

    def get_episode_sources(self, show, mal_id, episode, season, part, status, include_show_pack=False):
        self._resolve_anidb_id(mal_id)

        season_zfill = str(season).zfill(2) if season else '01'
        episode_zfill = str(episode).zfill(2) if episode is not None else '01'

        # Build all search queries upfront
        search_tasks = []

        # Primary episode search
        query = f'{show} "- {episode_zfill}"|"S{season_zfill}E{episode_zfill}"'
        if self.absolute_episode:
            query += f'|"- {str(self.absolute_episode).zfill(2)}"'
        params1 = {
            'q': self._sphinx_clean(query),
            'qx': 1,
            's': 'downloads',
            'o': 'desc'
        }
        if self.anidb_id:
            params1['aids'] = self.anidb_id
        search_tasks.append({'params': params1, 'name': 'primary'})

        # Batch/complete series search for finished shows
        if status in ["FINISHED", "Finished Airing"]:
            batch_terms = ["Batch", "Complete Series"]
            show_data = database.get_show(mal_id)
            if show_data and show_data.get('kodi_meta'):
                try:
                    episodes_info = database.loads(show_data['kodi_meta']).get('episodes')
                except Exception:
                    episodes_info = None
            else:
                episodes_info = None
            episode_formats = []
            if episodes_info:
                episodes_zfill = str(episodes_info).zfill(2)
                episode_formats = [f'01-{episodes_zfill}', f'01~{episodes_zfill}', f'01 - {episodes_zfill}', f'01 ~ {episodes_zfill}']
            batch_query = f'{show} ("' + '"|"'.join(batch_terms + episode_formats) + '")'
            params2 = {
                'q': self._sphinx_clean(batch_query),
                'qx': 1,
                's': 'seeders',
                'o': 'desc'
            }
            if self.anidb_id:
                params2['aids'] = self.anidb_id
            search_tasks.append({'params': params2, 'name': 'batch'})

        # C-23: AniDB ID-only search catches season-numbered Dub/Dual-Audio releases
        # (e.g. "Blue Exorcist S04") that omit the MAL arc subtitle.
        if self.anidb_id:
            search_tasks.append({'params': {'aids': self.anidb_id}, 'name': 'anidb_id'})

        # Season variation search
        if 'season' in show.lower():
            show_variations = re.split(r'season\s*\d+', show.lower())
            cleaned_variations = [self._sphinx_clean(var.strip() + ')') for var in show_variations if var.strip()]
            params4 = {
                'q': '|'.join(cleaned_variations),
                'qx': 1
            }
            if self.anidb_id:
                params4['aids'] = self.anidb_id
            search_tasks.append({'params': params4, 'name': 'season_variation'})

        if include_show_pack:
            show_params = {
                'q': self._sphinx_clean(self._clean_title(show)),
                'qx': 1,
                's': 'seeders',
                'o': 'desc'
            }
            if self.anidb_id:
                show_params['aids'] = self.anidb_id
            search_tasks.append({'params': show_params, 'name': 'show_pack', 'is_show_pack': True})

        # Execute all searches in parallel and deduplicate before a single Debrid cache check (C-24/C-25)
        control.log(f"AnimeTosho: Running {len(search_tasks)} searches in parallel for episode {episode_zfill}")

        def run_search(task):
            try:
                filtered = self._fetch_and_filter_episodes(
                    task['params'],
                    mal_id,
                    episode_zfill,
                    season_zfill,
                    part,
                    show=show,
                )
                is_pack = bool(task.get('is_show_pack'))
                for item in filtered:
                    item['_is_show_pack'] = is_pack
                control.log(f"AnimeTosho: {task['name']} search returned {len(filtered)} filtered torrents")
                return filtered
            except Exception as e:
                control.log(f"AnimeTosho: {task['name']} search failed: {str(e)}", 'warning')
                return []

        all_search_results = utils.parallel_process(search_tasks, run_search)

        seen_hashes = {}
        combined = []
        for torrents in all_search_results:
            for t in torrents:
                h = (t.get('hash') or '').lower()
                if not h:
                    continue
                if h not in seen_hashes:
                    t['hash'] = h
                    seen_hashes[h] = t
                    combined.append(t)
                elif not t.get('_is_show_pack') and seen_hashes[h].get('_is_show_pack'):
                    # Prefer episode-specific flag when the same hash matched both episode and show_pack queries
                    seen_hashes[h]['_is_show_pack'] = False

        if not combined:
            control.log("AnimeTosho: Episode search complete - returning 0 total sources")
            return []

        cache_list, uncashed_list_ = Debrid().torrentCacheCheck(
            combined, mal_id=mal_id, episode=episode_zfill, media_type='episode', rescrape=self.rescrape
        )
        cache_list = sorted(cache_list, key=lambda k: k['downloads'], reverse=True)
        uncashed_list = sorted([i for i in uncashed_list_ if i['seeders'] != 0], key=lambda k: k['seeders'], reverse=True)

        def _parse_entry(item, cached=True):
            return self.parse_animetosho_view(
                item, episode=episode_zfill, cached=cached, is_show_pack=bool(item.get('_is_show_pack'))
            )

        animetosho_sources = utils.parallel_process(cache_list, partial(_parse_entry, cached=True)) if cache_list else []
        if control.getBool('show.uncached') and uncashed_list:
            animetosho_sources += utils.parallel_process(uncashed_list, partial(_parse_entry, cached=False))

        control.log(f"AnimeTosho: Episode search complete - returning {len(animetosho_sources)} total sources")
        return animetosho_sources

    def get_show_sources(self, show, mal_id, episode, season, part):
        season_zfill = str(season).zfill(2) if season else '01'
        episode_zfill = str(episode).zfill(2) if episode is not None else '01'

        # anidb_id is already set by get_episode_sources
        query = self._clean_title(show)
        params = {
            'q': self._sphinx_clean(query),
            'qx': 1,
            's': 'seeders',
            'o': 'desc'
        }
        if self.anidb_id:
            params['aids'] = self.anidb_id

        search_url = domains.join_url(self._BASE_URL, 'search')
        animetosho_sources = self.process_animetosho_episodes(search_url, params, mal_id, episode_zfill, season_zfill, part, show=show, is_show_pack=True)
        return animetosho_sources

    def get_movie_sources(self, show, mal_id):
        self._resolve_anidb_id(mal_id)

        query = self._clean_title(show)
        params = {
            'q': self._sphinx_clean(query),
            'qx': 1,
            's': 'seeders',
            'o': 'desc'
        }
        if self.anidb_id:
            params['aids'] = self.anidb_id

        search_url = domains.join_url(self._BASE_URL, 'search')
        self.sources = self.process_animetosho_movie(search_url, params, mal_id)
        self.append_cache_uncached_noduplicates()
        return {'cached': self.cached, 'uncached': self.uncached}

    @staticmethod
    def _extract_hash(magnet):
        if not magnet:
            return ''
        m = re.search(r'btih:([A-Za-z0-9]+)', magnet)
        if not m:
            return ''
        raw_hash = m.group(1)
        if len(raw_hash) == 40:
            return raw_hash.lower()
        if len(raw_hash) == 32:
            try:
                return base64.b16encode(base64.b32decode(raw_hash.upper())).decode('ascii').lower()
            except (ValueError, AttributeError) as e:
                control.log(f"animetosho base32 hash conversion error: {e}", 'debug')
        return ''

    def _parse_content_entries(self, content_div):
        soup_all = content_div.find_all('div', class_='home_list_entry')
        rex = r'(magnet:)+[^"]*'
        list_ = []
        for entry in soup_all:
            link_div = entry.find('div', class_='link')
            if not link_div or not link_div.a:
                continue
            name = link_div.a.text.strip()

            mag_tag = entry.find('a', {'href': re.compile(rex)})
            magnet = mag_tag.get('href') if mag_tag else ''

            dllink_tag = entry.find('a', class_='dllink')
            torrent = dllink_tag.get('href') if dllink_tag else ''

            if not magnet and not torrent:
                continue

            size_div = entry.find('div', class_='size')
            size = size_div.text.strip().replace('iB', 'B') if size_div else 'NA'

            list_item = {
                'name': name,
                'magnet': magnet,
                'size': size,
                'downloads': 0,
                'torrent': torrent
            }
            try:
                seeder_span = entry.find('span', {'title': re.compile(r'Seeders')})
                list_item['seeders'] = int(re.match(r'Seeders: (\d+)', seeder_span.get('title')).group(1)) if seeder_span else -1
            except (AttributeError, TypeError, ValueError):
                list_item['seeders'] = -1

            list_item['hash'] = self._extract_hash(list_item['magnet'])
            if not list_item['hash']:
                continue

            list_.append(list_item)
        return list_

    def _fetch_and_filter_episodes(self, params, mal_id, episode, season, part, show=None):
        content_div = self._fetch_search_content(params)
        if content_div is None:
            return []
        list_ = self._parse_content_entries(content_div)
        if not list_:
            return []

        target_show = show or getattr(self, 'show', None)
        aliases = None
        if target_show and '|' in target_show:
            parts = [p.strip('() ') for p in target_show.split('|') if p.strip('() ')]
            if parts:
                target_show = parts[0]
                if len(parts) > 1:
                    aliases = parts[1:]

        if target_show:
            return source_utils.filter_sources(
                'animetosho', list_, mal_id, int(season), int(episode), part,
                anidb_id=self.anidb_id, show_title=target_show, aliases=aliases,
                **self.filter_kwargs
            )
        return source_utils.filter_sources(
            'animetosho', list_, mal_id, int(season), int(episode), part,
            anidb_id=self.anidb_id, **self.filter_kwargs
        )

    def process_animetosho_episodes(self, url, params, mal_id, episode, season, part, show=None, is_show_pack=False):
        filtered_list = self._fetch_and_filter_episodes(params, mal_id, episode, season, part, show=show)
        if not filtered_list:
            return []
        cache_list, uncashed_list_ = Debrid().torrentCacheCheck(filtered_list, mal_id=mal_id, episode=episode, media_type='episode', rescrape=self.rescrape)
        cache_list = sorted(cache_list, key=lambda k: k['downloads'], reverse=True)

        uncashed_list = [i for i in uncashed_list_ if i['seeders'] != 0]
        uncashed_list = sorted(uncashed_list, key=lambda k: k['seeders'], reverse=True)

        # Parse sources in parallel for faster processing
        mapfunc = partial(self.parse_animetosho_view, episode=episode, is_show_pack=is_show_pack)
        all_results = utils.parallel_process(cache_list, mapfunc) if cache_list else []
        if control.getBool('show.uncached') and uncashed_list:
            mapfunc2 = partial(self.parse_animetosho_view, episode=episode, cached=False, is_show_pack=is_show_pack)
            all_results += utils.parallel_process(uncashed_list, mapfunc2)
        return all_results

    def process_animetosho_movie(self, url, params, mal_id):
        content_div = self._fetch_search_content(params)
        if content_div is None:
            return []
        list_ = self._parse_content_entries(content_div)
        if not list_:
            return []

        # For movies we don't filter by season/episode
        filtered_list = source_utils.filter_sources('animetosho', list_, mal_id)
        cache_list, uncashed_list_ = Debrid().torrentCacheCheck(filtered_list, mal_id=mal_id, episode='1', media_type='movie', rescrape=self.rescrape)
        cache_list = sorted(cache_list, key=lambda k: k['downloads'], reverse=True)
        uncashed_list = sorted([i for i in uncashed_list_ if i['seeders'] != 0], key=lambda k: k['seeders'], reverse=True)

        # Parse sources in parallel for faster processing
        mapfunc = partial(self.parse_animetosho_view, episode="1")
        all_results = utils.parallel_process(cache_list, mapfunc) if cache_list else []
        if control.getBool('show.uncached') and uncashed_list:
            mapfunc2 = partial(self.parse_animetosho_view, episode="1", cached=False)
            all_results += utils.parallel_process(uncashed_list, mapfunc2)
        return all_results

    @staticmethod
    def parse_animetosho_view(res, episode, cached=True, is_show_pack=False):
        source = {
            'release_title': res['name'],
            'hash': res['hash'],
            'type': 'torrent',
            'quality': source_utils.getQuality(res['name']),
            'debrid_provider': res.get('debrid_provider'),
            'provider': 'animetosho',
            'episode_re': episode,
            'size': res['size'],
            'info': source_utils.get_release_info(res),
            'byte_size': 0,
            'lang': source_utils.getAudio_lang(res['name']),
            'channel': source_utils.getAudio_channel(res['name']),
            'sub': source_utils.getSubtitle_lang(res['name']),
            'cached': cached,
            'seeders': res['seeders'],
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
