import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from resources.lib.pages import (
    nyaa, animetosho, nekobt, torrentio, debrid_cloudfiles, easynews,
    animepahe, anikoto, animixplay, hianime, watchnixtoons2, localfiles
)
from resources.lib.ui import control, database, source_utils
from resources.lib.windows.get_sources_window import GetSources
from resources.lib.windows import sort_select


# (python_module, database.get cache key) — provider ids = dict keys below (insertion order)
_TORRENT_MODULES = {
    'nyaa': (nyaa, 'nyaa'),
    'animetosho': (animetosho, 'animetosho'),
    'nekobt': (nekobt, 'nekobt'),
    'torrentio': (torrentio, 'torrentio'),
}

# (module, cache_key, enabled_fn, merge_mode) — provider ids = dict keys below
# merge_mode: 'torrent_full' (cached+uncached → torrent lists) | 'cached_only' (cached only → hosterSources)
_HOSTER_MODULES = {
    'easynews': (easynews, 'easynews', control.easynews_enabled, 'cached_only'),
}

# (provider_id, module, database.get key, skip window prefix or None, pass_media_type)
# skip prefix drives _apply_embed_skip (aniwave / hianime / animekai)
_EMBED_MODULES = (
    ('animepahe', animepahe, 'animepahe', None, False),
    ('animix', animixplay, 'animix', None, False),
    # ('aniwave', aniwave, 'aniwave', 'aniwave', False),
    ('hianime', hianime, 'hianime', 'hianime', False),
    # ('animekai', animekai, 'animekai', 'animekai', False),
    ('anikoto', anikoto, 'anikoto', 'anikoto', False),
    ('watchnixtoons2', watchnixtoons2, 'watchnixtoons2', None, True),
)


class ScraperCircuitBreaker:
    """In-memory circuit breaker that temporarily pauses failing scrapers to prevent UI freezes."""
    def __init__(self, failure_threshold=3, cooldown_seconds=300):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._failures = {}
        self._cooldown_until = {}
        self._lock = threading.Lock()

    def is_tripped(self, provider: str) -> bool:
        with self._lock:
            now = time.time()
            cooldown = self._cooldown_until.get(provider, 0)
            if now < cooldown:
                return True
            if cooldown != 0:
                del self._cooldown_until[provider]
                self._failures[provider] = 0
            return False

    def record_success(self, provider: str):
        with self._lock:
            self._failures.pop(provider, None)
            self._cooldown_until.pop(provider, None)

    def record_failure(self, provider: str):
        with self._lock:
            count = self._failures.get(provider, 0) + 1
            self._failures[provider] = count
            if count >= self.failure_threshold:
                self._cooldown_until[provider] = time.time() + self.cooldown_seconds
                control.log(f"CircuitBreaker: Provider '{provider}' tripped for {self.cooldown_seconds}s ({count} consecutive errors)", 'warning')

    def reset(self, provider: str = None):
        with self._lock:
            if provider:
                self._failures.pop(provider, None)
                self._cooldown_until.pop(provider, None)
            else:
                self._failures.clear()
                self._cooldown_until.clear()


circuit_breaker = ScraperCircuitBreaker()


def getSourcesHelper(actionArgs):
    sources_window = None
    try:
        if control.getInt('general.dialog') in (5, 6):
            sources_window = Sources('get_sources_alt.xml', control.ADDON_PATH, actionArgs=actionArgs)
        else:
            sources_window = Sources('get_sources.xml', control.ADDON_PATH, actionArgs=actionArgs)
        return sources_window.doModal()
    finally:
        if sources_window:
            try:
                sources_window.close()
            except Exception:
                pass
            del sources_window


class Sources(GetSources):
    _scrape_semaphore = threading.Semaphore(control.max_threads)

    def __init__(self, xml_file, location, actionArgs=None):
        super(Sources, self).__init__(xml_file, location, actionArgs=actionArgs)
        self.torrentProviders = [row[0] for row in _TORRENT_MODULES.items()]
        self.embedProviders = [row[0] for row in _EMBED_MODULES]
        self.hosterProviders = [row[0] for row in _HOSTER_MODULES.items()]
        self.CloudProviders = ['Cloud Inspection']
        self.localProviders = ['Local Inspection']
        self.remainingProviders = (
            self.embedProviders + self.torrentProviders + self.hosterProviders + self.localProviders + self.CloudProviders
        )

        self.torrents_qual_len = [0, 0, 0, 0, 0]
        self.hosters_qual_len = [0, 0, 0, 0, 0]
        self.embeds_qual_len = [0, 0, 0, 0, 0]
        self.return_data = []
        self.progress = 1
        self.threads = []

        self.torrentSources = []
        self.torrentCacheSources = []
        self.torrentUnCacheSources = []
        self.hosterSources = []
        self.embedSources = []
        self.cloud_files = []
        self.local_files = []
        self._results_lock = threading.Lock()

    @classmethod
    def _start_worker(cls, fn):
        def _throttled_fn():
            with cls._scrape_semaphore:
                fn()
        t = threading.Thread(target=_throttled_fn, daemon=True)
        t.start()
        return t

    def getSources(self, args):
        query = args['query']
        mal_id = args['mal_id']
        episode = args['episode']
        status = args['status']
        media_type = args['media_type']
        duration = args['duration']
        rescrape = args['rescrape']
        season = args.get('season')
        part = args.get('part')

        self.setProperty('process_started', 'true')

        for prefix in ('hianime', 'aniwave', 'animekai', 'anikoto'):
            for key in ('skipintro.start', 'skipintro.end', 'skipoutro.start', 'skipoutro.end'):
                control.setInt(f'{prefix}.{key}', -1)

        enabled_debrids = control.enabled_debrid()
        enabled_clouds = control.enabled_cloud()
        common_debrids = [
            service for service, is_enabled in enabled_debrids.items()
            if is_enabled and enabled_clouds.get(service, False)
        ]

        debrid_on = any(enabled_debrids.values())
        t_args = (query, mal_id, episode, status, media_type, rescrape, season, part)

        if rescrape:
            circuit_breaker.reset()

        for provider in self.torrentProviders:
            if debrid_on and control.getBool(f'provider.{provider}'):
                if not rescrape and circuit_breaker.is_tripped(provider):
                    control.log(f"CircuitBreaker: Skipping '{provider}' (circuit open)", 'info')
                    with self._results_lock:
                        if provider in self.remainingProviders:
                            self.remainingProviders.remove(provider)
                    continue
                self.threads.append(self._start_worker(partial(self._torrent_sources_worker, provider, *t_args)))
            else:
                with self._results_lock:
                    if provider in self.remainingProviders:
                        self.remainingProviders.remove(provider)

        for hoster in self.hosterProviders:
            spec = _HOSTER_MODULES.get(hoster)
            if spec and spec[2]():
                if not rescrape and circuit_breaker.is_tripped(hoster):
                    control.log(f"CircuitBreaker: Skipping '{hoster}' (circuit open)", 'info')
                    with self._results_lock:
                        if hoster in self.remainingProviders:
                            self.remainingProviders.remove(hoster)
                    continue
                self.threads.append(self._start_worker(partial(self._hoster_sources_worker, hoster, *t_args)))
            else:
                with self._results_lock:
                    if hoster in self.remainingProviders:
                        self.remainingProviders.remove(hoster)

        if common_debrids:
            self.threads.append(self._start_worker(partial(self.user_cloud_inspection, query, mal_id, episode, season)))
        else:
            with self._results_lock:
                if 'Cloud Inspection' in self.remainingProviders:
                    self.remainingProviders.remove('Cloud Inspection')

        if control.getBool('provider.localfiles'):
            self.threads.append(self._start_worker(partial(self.user_local_inspection, query, mal_id, episode, season)))
        else:
            with self._results_lock:
                if 'Local Inspection' in self.remainingProviders:
                    self.remainingProviders.remove('Local Inspection')

        for pid, mod, cache_key, skip_prefix, needs_media_type in _EMBED_MODULES:
            if control.getBool(f'provider.{pid}'):
                if not rescrape and circuit_breaker.is_tripped(pid):
                    control.log(f"CircuitBreaker: Skipping '{pid}' (circuit open)", 'info')
                    with self._results_lock:
                        if pid in self.remainingProviders:
                            self.remainingProviders.remove(pid)
                    continue
                self.threads.append(self._start_worker(partial(
                    self._embed_sources_worker,
                    pid, mod, cache_key, skip_prefix, needs_media_type,
                    mal_id, episode, media_type, rescrape,
                )))
            else:
                with self._results_lock:
                    if pid in self.remainingProviders:
                        self.remainingProviders.remove(pid)

        timeout = 60 if rescrape else control.getInt('general.timeout')
        start_time = time.perf_counter()
        runtime = 0

        try:
            while runtime < timeout:
                if not self.silent:
                    self.updateProgress()
                    self.update_properties("4K: %s | 1080: %s | 720: %s | SD: %s| EQ: %s" % (
                        control.colorstr(self.torrents_qual_len[0] + self.hosters_qual_len[0] + self.embeds_qual_len[0]),
                        control.colorstr(self.torrents_qual_len[1] + self.hosters_qual_len[1] + self.embeds_qual_len[1]),
                        control.colorstr(self.torrents_qual_len[2] + self.hosters_qual_len[2] + self.embeds_qual_len[2]),
                        control.colorstr(self.torrents_qual_len[3] + self.hosters_qual_len[3] + self.embeds_qual_len[3]),
                        control.colorstr(self.torrents_qual_len[4] + self.hosters_qual_len[4] + self.embeds_qual_len[4])
                    ))
                control.sleep(100)

                if (
                    self.canceled
                    or not self.remainingProviders
                    or (control.getBool('general.terminate.oncloud') and len(self.cloud_files) > 0)
                    or (control.getBool('general.terminate.onlocal') and len(self.local_files) > 0)
                ):
                    break

                runtime = time.perf_counter() - start_time
                self.progress = runtime / timeout * 100

            if len(self.torrentSources) + len(self.hosterSources) + len(self.embedSources) + len(self.cloud_files) + len(self.local_files) == 0:
                self.return_data = []
            else:
                self.return_data = self.sortSources(self.torrentSources, self.hosterSources, self.embedSources, self.cloud_files, self.local_files, media_type, duration)
        except Exception as e:
            control.log(f"Error in getSources: {e}", 'error')
            self.return_data = []
        finally:
            self.close()
        return self.return_data

    def _torrent_sources_worker(self, provider, query, mal_id, episode, status, media_type, rescrape, season, part):
        if self.canceled:
            return
        try:
            mod, cache_key = _TORRENT_MODULES[provider]
            get_sources = mod.Sources().get_sources
            call_args = (query, mal_id, episode, status, media_type, season, part)
            if rescrape:
                all_sources = get_sources(*call_args, rescrape=True)
            else:
                all_sources = database.get(get_sources, 8, *call_args, key=cache_key)
            if self.canceled:
                return
            if not all_sources:
                all_sources = {'cached': [], 'uncached': []}
            if all_sources.get('cached') or all_sources.get('uncached'):
                circuit_breaker.record_success(provider)
            with self._results_lock:
                self.torrentUnCacheSources += all_sources.get('uncached', [])
                self.torrentCacheSources += all_sources.get('cached', [])
                self.torrentSources += all_sources.get('cached', []) + all_sources.get('uncached', [])
        except Exception as e:
            circuit_breaker.record_failure(provider)
            control.log(f"Error in torrent worker '{provider}': {e}", 'error')
        finally:
            with self._results_lock:
                if provider in self.remainingProviders:
                    self.remainingProviders.remove(provider)

    def _hoster_sources_worker(self, hoster, query, mal_id, episode, status, media_type, rescrape, season, part):
        if self.canceled:
            return
        try:
            mod, cache_key, _, merge_mode = _HOSTER_MODULES[hoster]
            get_sources = mod.Sources().get_sources
            call_args = (query, mal_id, episode, status, media_type, season, part)
            if rescrape:
                all_sources = get_sources(*call_args)
            else:
                all_sources = database.get(get_sources, 8, *call_args, key=cache_key)
            if self.canceled:
                return
            if not all_sources:
                all_sources = {'cached': [], 'uncached': []}
            if all_sources.get('cached') or all_sources.get('uncached'):
                circuit_breaker.record_success(hoster)
            with self._results_lock:
                if merge_mode == 'cached_only':
                    self.hosterSources += all_sources.get('cached', [])
                else:
                    self.torrentUnCacheSources += all_sources.get('uncached', [])
                    self.torrentCacheSources += all_sources.get('cached', [])
                    self.torrentSources += all_sources.get('cached', []) + all_sources.get('uncached', [])
        except Exception as e:
            circuit_breaker.record_failure(hoster)
            control.log(f"Error in hoster worker '{hoster}': {e}", 'error')
        finally:
            with self._results_lock:
                if hoster in self.remainingProviders:
                    self.remainingProviders.remove(hoster)

    def _embed_sources_worker(self, pid, mod, cache_key, skip_prefix, needs_media_type, mal_id, episode, media_type, rescrape):
        if self.canceled:
            return
        try:
            get_sources = mod.Sources().get_sources
            if needs_media_type:
                if rescrape:
                    src = get_sources(mal_id, episode, media_type)
                else:
                    src = database.get(get_sources, 8, mal_id, episode, media_type, key=cache_key)
            else:
                if rescrape:
                    src = get_sources(mal_id, episode)
                else:
                    src = database.get(get_sources, 8, mal_id, episode, key=cache_key)
            if self.canceled:
                return
            if not src:
                src = []
            else:
                circuit_breaker.record_success(pid)
            with self._results_lock:
                self.embedSources += src
            if skip_prefix:
                self._apply_embed_skip(skip_prefix, src)
        except Exception as e:
            circuit_breaker.record_failure(pid)
            control.log(f"Error in embed worker '{pid}': {e}", 'error')
        finally:
            with self._results_lock:
                if pid in self.remainingProviders:
                    self.remainingProviders.remove(pid)

    def user_local_inspection(self, query, mal_id, episode, season):
        if self.canceled:
            return
        try:
            res = localfiles.Sources().get_sources(query, mal_id, episode, season)
            if self.canceled:
                return
            if res:
                with self._results_lock:
                    self.local_files += res
        except Exception as e:
            control.log(f"Error in local inspection worker: {e}", 'error')
        finally:
            with self._results_lock:
                if 'Local Inspection' in self.remainingProviders:
                    self.remainingProviders.remove('Local Inspection')

    def user_cloud_inspection(self, query, mal_id, episode, season):
        if self.canceled:
            return
        try:
            res = debrid_cloudfiles.Sources().get_sources(query, mal_id, episode, season)
            if self.canceled:
                return
            if res:
                with self._results_lock:
                    self.cloud_files += res
        except Exception as e:
            control.log(f"Error in cloud inspection worker: {e}", 'error')
        finally:
            with self._results_lock:
                if 'Cloud Inspection' in self.remainingProviders:
                    self.remainingProviders.remove('Cloud Inspection')

    def _apply_embed_skip(self, prefix, sources):
        for x in sources:
            sk = x.get('skip')
            if not sk:
                continue
            intro = sk.get('intro')
            if intro and intro.get('start'):
                control.setInt(f'{prefix}.skipintro.start', int(intro['start']))
                control.setInt(f'{prefix}.skipintro.end', int(intro['end']))
            outro = sk.get('outro')
            if outro and outro.get('start'):
                control.setInt(f'{prefix}.skipoutro.start', int(outro['start']))
                control.setInt(f'{prefix}.skipoutro.end', int(outro['end']))

    @staticmethod
    def sortSources(torrent_list, hoster_list, embed_list, cloud_files, local_files, media_type, duration):
        all_list = torrent_list + hoster_list + embed_list + cloud_files + local_files
        sortedList = [x for x in all_list if control.getInt('general.minResolution') <= x['quality'] <= control.getInt('general.maxResolution')]

        combined = torrent_list + hoster_list

        # Filter by size
        filter_option = control.getInt('general.fileFilter')

        def _get_size_in_gb(item):
            size_gb = None
            byte_size = item.get('byte_size')
            if byte_size and isinstance(byte_size, (int, float)) and byte_size > 0:
                size_gb = byte_size / (1024.0 ** 3)
            else:
                raw_size = item.get('size')
                if raw_size and isinstance(raw_size, str):
                    raw_size = raw_size.strip()
                    if raw_size.upper() not in ('NA', 'N/A', 'UNKNOWN', 'NONE', ''):
                        match = re.search(r'([\d.]+)\s*([KMGTP]?B)', raw_size, re.IGNORECASE)
                        if match:
                            try:
                                num = float(match.group(1))
                                unit = match.group(2).upper()
                                if unit == 'TB':
                                    size_gb = num * 1024.0
                                elif unit == 'GB':
                                    size_gb = num
                                elif unit == 'MB':
                                    size_gb = num / 1024.0
                                elif unit == 'KB':
                                    size_gb = num / (1024.0 ** 2)
                                elif unit == 'B':
                                    size_gb = num / (1024.0 ** 3)
                                else:
                                    size_gb = num
                            except (ValueError, TypeError):
                                size_gb = None
            if size_gb is not None and media_type != 'movie' and source_utils.is_season_pack(item):
                ep_range = source_utils.extract_episode_range(item.get('release_title') or '')
                ep_count = max(1, ep_range[1] - ep_range[0] + 1) if ep_range else 12
                size_gb = size_gb / ep_count
            return size_gb

        if filter_option == 1:
            # web speed limit
            webspeed = control.getInt('general.webspeed')
            try:
                dur_val = float(duration) if duration else 0
            except (ValueError, TypeError):
                dur_val = 0
            len_in_sec = dur_val * 60

            if len_in_sec > 0:
                _combined = combined
                combined = []
                for i in _combined:
                    size_gb = _get_size_in_gb(i)
                    if size_gb is not None:
                        if ((size_gb * 8000) / len_in_sec) <= webspeed:
                            combined.append(i)
                    else:
                        combined.append(i)

        elif filter_option == 2:
            # hard limit
            if media_type == 'movie':
                max_GB = float(control.getInt('general.movie.maxGB'))
                min_GB = control.getNumber('general.movie.minGB')
            else:
                max_GB = float(control.getInt('general.episode.maxGB'))
                min_GB = control.getNumber('general.episode.minGB')

            _combined = combined
            combined = []
            for i in _combined:
                size_gb = _get_size_in_gb(i)
                if size_gb is not None:
                    if min_GB <= size_gb <= max_GB:
                        combined.append(i)
                else:
                    combined.append(i)

        # Filter by release title
        if control.getBool('general.release_title_filter.enabled'):
            release_title_filter1 = control.getSetting('general.release_title_filter.value1')
            release_title_filter2 = control.getSetting('general.release_title_filter.value2')
            release_title_filter3 = control.getSetting('general.release_title_filter.value3')
            release_title_filter4 = control.getSetting('general.release_title_filter.value4')
            release_title_filter5 = control.getSetting('general.release_title_filter.value5')

            # Get the new settings
            exclude_filter1 = control.getBool('general.release_title_filter.exclude1')
            exclude_filter2 = control.getBool('general.release_title_filter.exclude2')
            exclude_filter3 = control.getBool('general.release_title_filter.exclude3')
            exclude_filter4 = control.getBool('general.release_title_filter.exclude4')
            exclude_filter5 = control.getBool('general.release_title_filter.exclude5')

            _combined = combined
            release_title_logic = control.getInt('general.release_title_filter.logic')
            if release_title_logic == 0:
                # AND filter (case-insensitive)
                combined = [
                    i for i in _combined
                    if (not exclude_filter1 or release_title_filter1.lower() not in i['release_title'].lower())
                    and (not exclude_filter2 or release_title_filter2.lower() not in i['release_title'].lower())
                    and (not exclude_filter3 or release_title_filter3.lower() not in i['release_title'].lower())
                    and (not exclude_filter4 or release_title_filter4.lower() not in i['release_title'].lower())
                    and (not exclude_filter5 or release_title_filter5.lower() not in i['release_title'].lower())
                ]
            if release_title_logic == 1:
                # OR filter (case-insensitive)
                combined = [
                    i for i in _combined
                    if (release_title_filter1 != "" and (exclude_filter1 ^ (release_title_filter1.lower() in i['release_title'].lower())))
                    or (release_title_filter2 != "" and (exclude_filter2 ^ (release_title_filter2.lower() in i['release_title'].lower())))
                    or (release_title_filter3 != "" and (exclude_filter3 ^ (release_title_filter3.lower() in i['release_title'].lower())))
                    or (release_title_filter4 != "" and (exclude_filter4 ^ (release_title_filter4.lower() in i['release_title'].lower())))
                    or (release_title_filter5 != "" and (exclude_filter5 ^ (release_title_filter5.lower() in i['release_title'].lower())))
                ]

        sortedList = [x for x in sortedList if x in combined or x in embed_list or x in cloud_files or x in local_files]

        # Apply general.filters (comprehensive filtering like Seren)
        filter_list = control.getStringList("general.filters")
        if filter_list:
            current_filters = set(filter_list)
            # Special HDR/DV handling (like Seren does for HYBRID sources)
            disable_dv = "DV" in current_filters
            disable_hdr = "HDR" in current_filters
            filter_set = current_filters.difference({"HDR", "DV"})

            filtered = []
            for source in sortedList:
                s_info = source.get('info') or []
                # Skip if ANY filtered tag is in source info (set intersection)
                if filter_set & set(s_info):
                    continue
                # DV filter: exclude DV sources unless they're HYBRID
                if disable_dv and "DV" in s_info and "HYBRID" not in s_info:
                    continue
                # HDR filter: exclude HDR sources unless they're HYBRID
                if disable_hdr and "HDR" in s_info and "HYBRID" not in s_info:
                    continue
                # Hybrid filter: if both DV and HDR are disabled, exclude HYBRID too
                if disable_dv and disable_hdr and "HYBRID" in s_info:
                    continue
                filtered.append(source)
            sortedList = filtered

        # Filter by language source
        source = control.getInt("general.source")
        if source != 0:
            if source == 1:
                sortedList = [i for i in sortedList if i['lang'] in [0, 1, 2]]
            elif source == 2:
                sortedList = [i for i in sortedList if i['lang'] in [0, 1, 3]]

        # Sort sources (Seren-style composite keys; fresh sort_options.json)
        sortedList = sort_select.sort_sources_list(sortedList)

        return sortedList

    def updateProgress(self):
        t_counts, h_counts, e_counts = [0] * 5, [0] * 5, [0] * 5
        for s in self.torrentSources:
            q = s.get('quality', 0)
            if 0 <= q <= 4:
                t_counts[4 - q] += 1
        for s in self.hosterSources:
            q = s.get('quality', 0)
            if 0 <= q <= 4:
                h_counts[4 - q] += 1
        for s in self.embedSources:
            q = s.get('quality', 0)
            if 0 <= q <= 4:
                e_counts[4 - q] += 1
        self.torrents_qual_len = t_counts
        self.hosters_qual_len = h_counts
        self.embeds_qual_len = e_counts
