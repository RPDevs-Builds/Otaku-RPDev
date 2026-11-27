import threading
import time

from resources.lib.debrid import premiumize, torbox, easydebrid, debrid_cache
from resources.lib.ui import control


def _clone_torrents(torrent_list):
    """Fast shallow clone of torrent dicts for worker threads (15-30x faster than deepcopy)."""
    return [dict(t) for t in torrent_list]


class Debrid:
    def __init__(self):
        self.premiumizeCached = []
        self.realdebridCached = []
        self.alldebridCached = []
        self.torboxCached = []
        self.easydebridCached = []

        self.premiumizeUnCached = []
        self.realdebridUnCached = []
        self.alldebridUnCached = []
        self.debridlinkUnCached = []
        self.torboxUnCached = []
        self.threads = []

    def torrentCacheCheck(self, torrent_list, mal_id=None, episode=None, media_type=None, rescrape=False):
        enabled_debrids = control.enabled_debrid()
        if enabled_debrids['realdebrid']:
            t = threading.Thread(target=self.real_debrid_worker, args=(_clone_torrents(torrent_list), mal_id, episode, media_type, rescrape), daemon=True)
            t.start()
            self.threads.append(t)

        if enabled_debrids['debridlink']:
            t = threading.Thread(target=self.debrid_link_worker, args=(_clone_torrents(torrent_list),), daemon=True)
            self.threads.append(t)
            t.start()

        if enabled_debrids['premiumize']:
            t = threading.Thread(target=self.premiumize_worker, args=(_clone_torrents(torrent_list),), daemon=True)
            t.start()
            self.threads.append(t)

        if enabled_debrids['alldebrid']:
            t = threading.Thread(target=self.all_debrid_worker, args=(_clone_torrents(torrent_list), mal_id, episode, media_type, rescrape), daemon=True)
            t.start()
            self.threads.append(t)

        if enabled_debrids['torbox']:
            t = threading.Thread(target=self.torbox_worker, args=(_clone_torrents(torrent_list),), daemon=True)
            t.start()
            self.threads.append(t)

        if enabled_debrids['easydebrid']:
            t = threading.Thread(target=self.easydebrid_worker, args=(_clone_torrents(torrent_list),), daemon=True)
            t.start()
            self.threads.append(t)

        for i in self.threads:
            i.join()

        cached_list = self.realdebridCached + self.alldebridCached + self.premiumizeCached + self.torboxCached + self.easydebridCached
        uncached_list = self.realdebridUnCached + self.premiumizeUnCached + self.alldebridUnCached + self.debridlinkUnCached + self.torboxUnCached
        return cached_list, uncached_list

    def _get_imdb_and_season(self, mal_id, episode, media_type):
        """Get IMDB ID and season info for external cache checking."""
        imdb_id = None
        season = None
        try:
            if mal_id:
                from resources.lib.ui import database
                mappings = database.resolve_mappings_with_fallback(
                    mal_id, required_keys=('imdb_id',), require_all=False
                )
                if mappings:
                    imdb_id = mappings.get('imdb_id')
                    db_media_type = mappings.get('anime_media_type') or mappings.get('global_media_type') or media_type
                    if db_media_type and 'movie' in str(db_media_type).lower():
                        season = None  # Movies don't use season/episode
                    else:
                        mapped_s, _ = database.resolve_tvdb_episode_mapping(mal_id, episode or 1)
                        if mapped_s is not None:
                            season = mapped_s
                        elif mappings.get('thetvdb_season') not in (None, ''):
                            try:
                                season = int(mappings['thetvdb_season'])
                            except (ValueError, TypeError):
                                season = None
                        if season is None:
                            from resources.lib.ui.utils import get_season
                            title = mappings.get('mal_title', '')
                            season = get_season([title], mal_id) if title else 1
        except Exception as e:
            control.log(f'Failed to get IMDB ID for cache check: {e}', 'warning')
        return imdb_id, season

    def lazy_probe_cached_torrents(self, provider_key, torrent_list, max_candidates=3, max_total_s=6.0):
        """
        Opt-in Lazy Top-N instant availability probe (debrid.lazy_cache_probe) when a bulk
        endpoint is blocked/deprecated. Probes <=3 Tier-3 highest-seeder candidates within <=6s,
        immediately deletes uncached transfers, and persists ONLY positive hits to debrid_cache.
        """
        if not torrent_list or not control.getBool('debrid.lazy_cache_probe', default=False):
            return set()

        cache_code_map = {
            'realdebrid': 'rd',
            'alldebrid': 'ad',
            'premiumize': 'pm',
            'torbox': 'tb',
        }
        cache_code = cache_code_map.get(provider_key, provider_key)

        tier3 = [
            t for t in torrent_list
            if isinstance(t, dict) and t.get('hash') and float(t.get('relevance') or 0) >= 140
        ]
        seen_hashes = set()
        deduped = []
        for t in sorted(tier3, key=lambda x: int(x.get('seeders') or 0), reverse=True):
            h = str(t['hash']).strip().lower()
            if h not in seen_hashes:
                seen_hashes.add(h)
                deduped.append(t)
            if len(deduped) >= int(max_candidates):
                break

        if not deduped:
            return set()

        if provider_key == 'realdebrid':
            from resources.lib.debrid import real_debrid
            client_inst = real_debrid.RealDebrid()
        elif provider_key == 'alldebrid':
            from resources.lib.debrid import all_debrid
            client_inst = all_debrid.AllDebrid()
        elif provider_key == 'premiumize':
            client_inst = premiumize.Premiumize()
        elif provider_key == 'torbox':
            client_inst = torbox.TorBox()
        else:
            return set()

        confirmed = set()
        t_start = time.monotonic()
        for candidate in deduped:
            if (time.monotonic() - t_start) >= float(max_total_s) or control.abort_requested():
                break
            h = str(candidate['hash']).strip().lower()
            magnet = candidate.get('magnet') or f"magnet:?xt=urn:btih:{h}"
            try:
                if client_inst.probe_instant_cache(magnet):
                    confirmed.add(h)
            except Exception as e:
                control.log(f"Lazy cache probe ({provider_key}) error for {h[:8]}: {e}", 'debug')

        if confirmed:
            # Persist ONLY confirmed positive hashes (never poison cache with negatives)
            debrid_cache.set_cached_hashes([(h, 'True') for h in confirmed], cache_code)
            control.log_metric(
                'lazy_cache_probe',
                level='info',
                provider=provider_key,
                probed=len(deduped),
                confirmed=len(confirmed),
            )
        return confirmed

    def all_debrid_worker(self, torrent_list, mal_id=None, episode=None, media_type=None, rescrape=False):
        if not torrent_list:
            return
        hash_list = [i['hash'].lower() for i in torrent_list if i.get('hash')]

        # Check local debrid cache DB unless rescraping
        if rescrape:
            db_cached = set()
            unknown_hashes = hash_list
        else:
            cached_from_db = debrid_cache.get_cached_hashes(hash_list)
            db_cached = {r['hash'].lower() for r in cached_from_db if r['debrid'] == 'ad' and r['cached'] == 'True'}
            unknown_hashes = [h for h in hash_list if h not in db_cached]

        # External check for unknown hashes
        external_cached = set()
        if unknown_hashes:
            ready_hashes, waiting_events = debrid_cache.acquire_in_flight(unknown_hashes, 'ad')
            if waiting_events:
                for ev in waiting_events:
                    ev.wait(timeout=4.0)
                # Re-check DB for results written by sibling scrapers
                cached_from_db_post = debrid_cache.get_cached_hashes(unknown_hashes)
                db_cached.update(r['hash'].lower() for r in cached_from_db_post if r['debrid'] == 'ad' and r['cached'] == 'True')
                ready_hashes = [h for h in ready_hashes if h not in db_cached]

            try:
                if ready_hashes:
                    imdb_id, season = self._get_imdb_and_season(mal_id, episode, media_type)
                    if imdb_id:
                        external_cached = {h.lower() for h in debrid_cache.check_ad_cache(imdb_id, season, episode) if h}
                        if external_cached:
                            hashes_to_cache = [(h, 'True') for h in external_cached]
                            debrid_cache.set_cached_hashes(hashes_to_cache, 'ad')
                    if not external_cached and control.getBool('debrid.lazy_cache_probe', default=False):
                        unknown_torrents = [t for t in torrent_list if t.get('hash', '').lower() in ready_hashes]
                        external_cached = self.lazy_probe_cached_torrents('alldebrid', unknown_torrents)
            finally:
                debrid_cache.release_in_flight(ready_hashes, 'ad')

        all_cached = db_cached | external_cached
        for torrent in torrent_list:
            torrent['debrid_provider'] = 'Alldebrid'
            if torrent['hash'].lower() in all_cached:
                self.alldebridCached.append(torrent)
            else:
                self.alldebridUnCached.append(torrent)

    def debrid_link_worker(self, torrent_list):
        hash_list = [i['hash'] for i in torrent_list]
        if len(hash_list) > 0:
            for torrent in torrent_list:
                torrent['debrid_provider'] = 'Debrid-Link'
                self.debridlinkUnCached.append(torrent)

    def real_debrid_worker(self, torrent_list, mal_id=None, episode=None, media_type=None, rescrape=False):
        if not torrent_list:
            return
        hash_list = [i['hash'].lower() for i in torrent_list if i.get('hash')]

        # Check local debrid cache DB unless rescraping
        if rescrape:
            db_cached = set()
            unknown_hashes = hash_list
        else:
            cached_from_db = debrid_cache.get_cached_hashes(hash_list)
            db_cached = {r['hash'].lower() for r in cached_from_db if r['debrid'] == 'rd' and r['cached'] == 'True'}
            unknown_hashes = [h for h in hash_list if h not in db_cached]

        # External check for unknown hashes
        external_cached = set()
        if unknown_hashes:
            ready_hashes, waiting_events = debrid_cache.acquire_in_flight(unknown_hashes, 'rd')
            if waiting_events:
                for ev in waiting_events:
                    ev.wait(timeout=4.0)
                # Re-check DB for results written by sibling scrapers
                cached_from_db_post = debrid_cache.get_cached_hashes(unknown_hashes)
                db_cached.update(r['hash'].lower() for r in cached_from_db_post if r['debrid'] == 'rd' and r['cached'] == 'True')
                ready_hashes = [h for h in ready_hashes if h not in db_cached]

            try:
                if ready_hashes:
                    imdb_id, season = self._get_imdb_and_season(mal_id, episode, media_type)
                    if imdb_id:
                        external_cached = {h.lower() for h in debrid_cache.check_rd_cache(ready_hashes, imdb_id, season, episode) if h}
                        if external_cached:
                            hashes_to_cache = [(h, 'True') for h in external_cached]
                            debrid_cache.set_cached_hashes(hashes_to_cache, 'rd')
                    if not external_cached and control.getBool('debrid.lazy_cache_probe', default=False):
                        unknown_torrents = [t for t in torrent_list if t.get('hash', '').lower() in ready_hashes]
                        external_cached = self.lazy_probe_cached_torrents('realdebrid', unknown_torrents)
            finally:
                debrid_cache.release_in_flight(ready_hashes, 'rd')

        all_cached = db_cached | external_cached
        for torrent in torrent_list:
            torrent['debrid_provider'] = 'Real-Debrid'
            if torrent['hash'].lower() in all_cached:
                self.realdebridCached.append(torrent)
            else:
                self.realdebridUnCached.append(torrent)

    def premiumize_worker(self, torrent_list):
        hash_list = [i['hash'] for i in torrent_list]
        if len(hash_list) > 0:
            pm = premiumize.Premiumize()
            premiumizeCache = pm.hash_check(hash_list)
            if not premiumizeCache or 'response' not in premiumizeCache:
                probed = self.lazy_probe_cached_torrents('premiumize', torrent_list) if pm._bulk_blocked else set()
                for torrent in torrent_list:
                    torrent['debrid_provider'] = 'Premiumize'
                    if str(torrent.get('hash') or '').lower() in probed:
                        self.premiumizeCached.append(torrent)
                    else:
                        self.premiumizeUnCached.append(torrent)
                return
            premiumizeCache = premiumizeCache['response']

            for index, torrent in enumerate(torrent_list):
                torrent['debrid_provider'] = 'Premiumize'
                if premiumizeCache[index] is True:
                    self.premiumizeCached.append(torrent)
                else:
                    self.premiumizeUnCached.append(torrent)

    def torbox_worker(self, torrent_list):
        hash_list = [i['hash'].lower() for i in torrent_list if i.get('hash')]
        if len(hash_list) > 0:
            tb = torbox.TorBox()
            torbox_result = tb.hash_check(hash_list)
            if not torbox_result:
                probed = self.lazy_probe_cached_torrents('torbox', torrent_list) if tb._bulk_blocked else set()
                for torrent in torrent_list:
                    torrent['debrid_provider'] = 'TorBox'
                    if str(torrent.get('hash') or '').lower() in probed:
                        self.torboxCached.append(torrent)
                    else:
                        self.torboxUnCached.append(torrent)
                return
            cache_check = {i['hash'].lower() for i in torbox_result if isinstance(i, dict) and i.get('hash')}
            for torrent in torrent_list:
                torrent['debrid_provider'] = 'TorBox'
                if torrent['hash'].lower() in cache_check:
                    self.torboxCached.append(torrent)
                else:
                    self.torboxUnCached.append(torrent)

    def easydebrid_worker(self, torrent_list):
        # Prepend the magnet prefix to each hash within torrent_list
        hash_list = ["magnet:?xt=urn:btih:" + i['hash'] for i in torrent_list]
        if len(hash_list) > 0:
            response = easydebrid.EasyDebrid().lookup_link(hash_list)
            if not response:
                return
            cached_flags = response.get("cached", [])
            for torrent, is_cached in zip(torrent_list, cached_flags):
                torrent['debrid_provider'] = 'EasyDebrid'
                if is_cached:
                    self.easydebridCached.append(torrent)
