from resources.lib.ui import control
from resources.lib.WatchlistFlavor import AniList, Kitsu, MyAnimeList, Simkl  # noQA
from resources.lib.WatchlistFlavor.WatchlistFlavorBase import WatchlistFlavorBase


class WatchlistFlavor:
    # Unified status mapping: maps a unified status key to each flavor's native status string.
    _STATUS_MAP = {
        'watching':      {'anilist': 'CURRENT',   'mal': 'watching',      'kitsu': 'current',   'simkl': 'watching'},
        'completed':     {'anilist': 'COMPLETED', 'mal': 'completed',     'kitsu': 'completed', 'simkl': 'completed'},
        'on_hold':       {'anilist': 'PAUSED',    'mal': 'on_hold',       'kitsu': 'on_hold',   'simkl': 'hold'},
        'dropped':       {'anilist': 'DROPPED',   'mal': 'dropped',       'kitsu': 'dropped',   'simkl': 'dropped'},
        'plan_to_watch': {'anilist': 'PLANNING',  'mal': 'plan_to_watch', 'kitsu': 'planned',   'simkl': 'plantowatch'},
        'rewatching':    {'anilist': 'REPEATING', 'mal': 'watching',      'kitsu': 'current',   'simkl': 'watching'},
    }

    def __init__(self):
        raise Exception("Static Class should not be created")

    @staticmethod
    def get_enabled_watchlists():
        return [WatchlistFlavor.__instance_flavor(x) for x in control.enabled_watchlists()]

    @staticmethod
    def get_all_update_flavors():
        """Get all enabled and logged-in watchlist flavor instances for simultaneous updating."""
        if not control.getBool('watchlist.update.enabled'):
            return []
        enabled = control.enabled_watchlists()
        return [WatchlistFlavor.__instance_flavor(name) for name in enabled]

    @staticmethod
    def get_first_enabled_flavor():
        """Get the first enabled watchlist flavor (for data lookups like eps_watched)."""
        enabled = control.enabled_watchlists()
        if enabled:
            return WatchlistFlavor.__instance_flavor(enabled[0])
        return None

    @staticmethod
    def get_merged_watchlist_eps_watched(mal_id):
        """Resolve eps_watched across all enabled watchlists using the configured conflict policy:
          0 = highest_progress (default: max episode count across trackers)
          1 = primary_wins (first enabled tracker wins)
          2 = latest_updated (tracker with highest updated_at timestamp wins, tie-broken by max episode)
        """
        policy = control.getInt('watchlist.sync.conflict_policy', default=0)
        candidates = []
        for idx, flavor in enumerate(WatchlistFlavor.get_enabled_watchlists()):
            try:
                data = flavor.get_watchlist_anime_entry(mal_id)
                if not data:
                    continue
                ew = data.get('eps_watched')
                if ew is None or ew == '':
                    continue
                ew_int = int(ew)
                updated_at = str(data.get('updated_at') or data.get('last_updated') or '')
                candidates.append((idx, ew_int, updated_at, flavor.flavor_name))
            except Exception as e:
                control.log(f'get_merged_watchlist_eps_watched ({flavor.flavor_name}): {e}', 'debug')
        if not candidates:
            return None
        if policy == 1:
            # primary_wins: first enabled tracker with an entry
            return candidates[0][1]
        if policy == 2:
            # latest_updated: highest ISO/epoch updated_at string, tie-broken by highest progress
            candidates.sort(key=lambda item: (item[2], item[1]), reverse=True)
            return candidates[0][1]
        # Default (0 = highest_progress)
        return max(item[1] for item in candidates)

    @staticmethod
    def compute_watchlist_drift():
        """Compare cached watchlist entries across all enabled services and return a list of drift items."""
        from resources.lib.ui import database
        from resources.lib.ui.database_sync import SyncDatabase
        enabled = control.enabled_watchlists()
        if len(enabled) < 2:
            return []
        by_mal = {}
        try:
            SyncDatabase._build_watchlist_cache()
            with database.SQL(control.malSyncDB) as cur:
                cur.execute(
                    'SELECT service, status, mal_id, data, last_updated '
                    'FROM watchlist_cache WHERE mal_id IS NOT NULL AND mal_id > 0'
                )
                for row in cur.fetchall() or []:
                    svc = row.get('service')
                    if svc not in enabled:
                        continue
                    mid = int(row['mal_id'])
                    payload = database.loads(row.get('data'))
                    if not isinstance(payload, dict):
                        payload = {}
                    title = (
                        payload.get('media', {}).get('title', {}).get('english')
                        or payload.get('media', {}).get('title', {}).get('romaji')
                        or payload.get('node', {}).get('alternative_titles', {}).get('en')
                        or payload.get('node', {}).get('title')
                        or payload.get('anime', {}).get('attributes', {}).get('canonicalTitle')
                        or payload.get('show', {}).get('title')
                        or f'MAL #{mid}'
                    )
                    ew = (
                        payload.get('progress')
                        if payload.get('progress') is not None
                        else (
                            payload.get('list_status', {}).get('num_episodes_watched')
                            if payload.get('list_status', {}).get('num_episodes_watched') is not None
                            else (
                                payload.get('watched_episodes_count')
                                if payload.get('watched_episodes_count') is not None
                                else payload.get('entry', {}).get('attributes', {}).get('progress')
                            )
                        )
                    )
                    updated_at = str(
                        payload.get('updatedAt')
                        or payload.get('list_status', {}).get('updated_at')
                        or payload.get('last_watched_at')
                        or payload.get('entry', {}).get('attributes', {}).get('updatedAt')
                        or row.get('last_updated')
                        or ''
                    )
                    entry = by_mal.setdefault(mid, {'mal_id': mid, 'title': title, 'trackers': {}})
                    entry['trackers'][svc] = {
                        'episodes_watched': int(ew or 0),
                        'status': str(row.get('status') or ''),
                        'updated_at': updated_at,
                    }
        except Exception as e:
            control.log(f"compute_watchlist_drift error: {e}", 'warning')
            return []

        drifts = []
        policy = control.getInt('watchlist.sync.conflict_policy', default=0)
        for mid, info in sorted(by_mal.items()):
            trackers = info['trackers']
            if len(trackers) < 2:
                continue
            eps_set = {v['episodes_watched'] for v in trackers.values()}
            if len(eps_set) > 1:
                if policy == 1:
                    primary = next((s for s in enabled if s in trackers), list(trackers.keys())[0])
                    target_ep = trackers[primary]['episodes_watched']
                elif policy == 2:
                    best_svc = max(trackers.keys(), key=lambda s: (trackers[s]['updated_at'], trackers[s]['episodes_watched']))
                    target_ep = trackers[best_svc]['episodes_watched']
                else:
                    target_ep = max(eps_set)
                drifts.append({
                    'mal_id': mid,
                    'title': info['title'],
                    'trackers': trackers,
                    'target_episode': target_ep,
                })
        return drifts

    @staticmethod
    def count_watchlist_drift_mutations(drifts=None):
        """Return dry-run count of tracker updates required to reconcile all detected drifts."""
        items = drifts if drifts is not None else WatchlistFlavor.compute_watchlist_drift()
        planned = 0
        for item in items:
            target_ep = int(item.get('target_episode') or 0)
            for _, tdata in item.get('trackers', {}).items():
                if int(tdata.get('episodes_watched') or 0) != target_ep:
                    planned += 1
        return planned

    @staticmethod
    def reconcile_watchlist_drift(drifts=None, dry_run=False):
        """Reconcile episode progress drift across enabled trackers using the active conflict policy."""
        from resources.lib.ui import database
        items = drifts if drifts is not None else WatchlistFlavor.compute_watchlist_drift()
        if dry_run:
            return WatchlistFlavor.count_watchlist_drift_mutations(items)
        reconciled = 0
        for item in items:
            mid = item['mal_id']
            target_ep = int(item['target_episode'])
            for svc, tdata in item.get('trackers', {}).items():
                if int(tdata.get('episodes_watched') or 0) != target_ep:
                    ok = WatchlistFlavor.watchlist_update_episode_for_flavor(svc, mid, target_ep)
                    if ok:
                        reconciled += 1
                    else:
                        database.enqueue_scrobble_retry(svc, 'update_episode', mid, episode=target_ep, error='drift_reconcile_failed')
        return reconciled

    @staticmethod
    def process_scrobble_retry_queue(limit=25):
        """Drain due items from scrobble_retry_queue and return count of succeeded retries."""
        from resources.lib.ui import database
        due = database.get_due_scrobble_retries(limit=limit)
        succeeded = 0
        for row in due:
            if control.abort_requested():
                break
            svc = row.get('service')
            action = row.get('action')
            mid = row.get('mal_id')
            ep = int(row.get('episode') or 0)
            status = row.get('status') or ''
            score = int(row.get('score') or 0)
            ok = False
            exc_err = None
            try:
                if action == 'update_episode':
                    ok = bool(WatchlistFlavor.watchlist_update_episode_for_flavor(svc, mid, ep))
                elif action == 'set_status':
                    ok = bool(WatchlistFlavor.watchlist_set_status_for_flavor(svc, mid, status))
                elif action == 'set_score':
                    ok = bool(WatchlistFlavor.watchlist_set_score_for_flavor(svc, mid, score))
            except Exception as e:
                ok = False
                exc_err = str(e)
            if ok:
                database.remove_scrobble_retry(svc, action, mid)
                succeeded += 1
            elif int(row.get('attempts') or 0) >= 5:
                database.remove_scrobble_retry(svc, action, mid)
            else:
                database.enqueue_scrobble_retry(
                    svc,
                    action,
                    mid,
                    episode=ep,
                    status=status,
                    score=score,
                    error=exc_err or row.get('last_error') or 'retry_failed',
                )
        return succeeded

    @staticmethod
    def get_flavor_by_name(name):
        """Get a specific watchlist flavor instance by name."""
        if WatchlistFlavor.__is_flavor_valid(name) and name in control.enabled_watchlists():
            return WatchlistFlavor.__instance_flavor(name)
        return None

    @staticmethod
    def watchlist_request(name):
        return WatchlistFlavor.__instance_flavor(name).watchlist()

    @staticmethod
    def watchlist_status_request(name, status, next_up, offset=0, page=1, cache_only=False):
        return WatchlistFlavor.__instance_flavor(name).get_watchlist_status(status, next_up, offset, page, cache_only)

    @staticmethod
    def get_next_up(offset=0, page=1):
        """Get Next Up episodes from the configured watchlist flavor."""
        enabled = control.enabled_watchlists()
        if not enabled:
            return []

        # Determine which flavor to use based on setting
        # 0=Auto (first enabled), 1=AniList, 2=Kitsu, 3=MAL, 4=Simkl
        flavor_map = {1: 'anilist', 2: 'kitsu', 3: 'mal', 4: 'simkl'}
        nextup_pref = control.getInt('nextup.flavor')
        if nextup_pref and nextup_pref in flavor_map:
            preferred = flavor_map[nextup_pref]
            # Only use the preferred flavor if it's actually enabled
            if preferred in enabled:
                flavor_name = preferred
            else:
                flavor_name = enabled[0]
        else:
            flavor_name = enabled[0]

        watching_status = WatchlistFlavor._STATUS_MAP['watching'].get(flavor_name, 'watching')
        flavor = WatchlistFlavor.__instance_flavor(flavor_name)
        return flavor.get_watchlist_status(watching_status, next_up=True, offset=offset, page=page)

    @staticmethod
    def login_request(flavor):
        if not WatchlistFlavor.__is_flavor_valid(flavor):
            raise Exception("Invalid flavor %s" % flavor)
        flavor_class = WatchlistFlavor.__instance_flavor(flavor)
        res = flavor_class.login()
        if res is None or res is False:
            return None
        return WatchlistFlavor.__set_login(flavor, res)

    @staticmethod
    def logout_request(flavor):
        control.setSetting('%s.userid' % flavor, '')
        control.setSetting('%s.authvar' % flavor, '')
        control.setSetting('%s.token' % flavor, '')
        control.setSetting('%s.refresh' % flavor, '')
        control.setSetting('%s.username' % flavor, '')
        control.setSetting('%s.password' % flavor, '')
        control.setInt('%s.expiry' % flavor, 0)
        control.setInt('%s.sort' % flavor, 0)
        control.setInt('%s.order' % flavor, 0)
        control.setSetting('%s.titles' % flavor, '')
        control.setBool('%s.enabled' % flavor, False)
        return control.refresh()

    @staticmethod
    def __get_flavor_class(name):
        for flav in WatchlistFlavorBase.__subclasses__():
            if flav.name() == name:
                return flav

    @staticmethod
    def __is_flavor_valid(name):
        return WatchlistFlavor.__get_flavor_class(name) is not None

    @staticmethod
    def __instance_flavor(name):
        user_id = control.getSetting(f'{name}.userid')
        auth_var = control.getSetting(f'{name}.authvar')
        token = control.getSetting(f'{name}.token')
        refresh = control.getSetting(f'{name}.refresh')
        username = control.getSetting(f'{name}.username')
        password = control.getSetting(f'{name}.password')
        sort = control.getInt(f'{name}.sort')
        order = control.getInt(f'{name}.order')

        flavor_class = WatchlistFlavor.__get_flavor_class(name)
        return flavor_class(auth_var, username, password, user_id, token, refresh, sort, order)

    @staticmethod
    def __set_login(flavor, res):
        if not res:
            return control.ok_dialog('Login', 'Authorization failed or invalid credentials')
        else:
            control.setBool('watchlist.update.enabled', True)
            control.setBool('%s.enabled' % flavor, True)
        for _id, value in list(res.items()):
            setting_name = '%s.%s' % (flavor, _id)
            if _id == 'expiry':
                control.setInt(setting_name, int(value))
            else:
                control.setSetting(setting_name, str(value))
        control.refresh()
        return control.ok_dialog('Login', 'Success')

    # ==================== All-Watchlist Update Methods ====================

    @staticmethod
    def watchlist_update_all_episodes(mal_id, episode, up_to=False):
        """Update episode progress on ALL enabled watchlists simultaneously.
        Handles per-flavor completion detection based on each service's total episode count.
        Returns True if any watchlist was marked as completed."""
        from resources.lib.ui import database

        # Get show info for completion detection fallback
        show = database.get_show(mal_id)
        kodi_episodes = None
        finished_airing = False
        if show:
            kodi_meta = database.loads(show['kodi_meta'])
            kodi_episodes = kodi_meta.get('episodes')
            status = kodi_meta.get('status')
            finished_airing = status in ['Finished Airing', 'FINISHED']

        # Update local eps_watched in kodi_meta so watch indicators refresh immediately
        if show:
            kodi_meta['eps_watched'] = episode
            database.update_kodi_meta(mal_id, kodi_meta)

        flavors = WatchlistFlavor.get_all_update_flavors()
        any_completed = False

        for flavor in flavors:
            try:
                updated = flavor.update_num_episodes(mal_id, episode, up_to=up_to)
                if not updated:
                    control.log(f'Failed to update episode {episode} on {flavor.flavor_name} (returned False); queuing retry', 'warning')
                    database.enqueue_scrobble_retry(flavor.flavor_name, 'update_episode', mal_id, episode=int(episode or 0), error='update_returned_false')
                    continue
                database.remove_scrobble_retry(flavor.flavor_name, 'update_episode', mal_id)
                control.log(f'Updated episode {episode} on {flavor.flavor_name}')

                # Per-flavor completion detection using each service's own total episode count
                entry = flavor.get_watchlist_anime_entry(mal_id)
                total = entry.get('total_episodes') if entry else None
                current_status = entry.get('status') if entry else None

                # DEBUG: Log what each API returns for total_episodes
                # control.print(f'[DEBUG] {flavor.flavor_name}: API total_episodes={total}, kodi_meta fallback={kodi_episodes}, entry={entry}')

                if total is None:
                    total = kodi_episodes  # Fallback to kodi_meta

                if total and int(episode) >= int(total) and finished_airing:
                    mapped = WatchlistFlavor._STATUS_MAP['completed'].get(flavor.flavor_name, 'completed')
                    flavor.update_list_status(mal_id, mapped)
                    any_completed = True
                    control.log(f'Auto-completed {flavor.flavor_name} (ep {episode}/{total})')
                else:
                    mapped = WatchlistFlavor._STATUS_MAP['watching'].get(flavor.flavor_name, 'watching')
                    if current_status not in (mapped, 'REPEATING'):
                        flavor.update_list_status(mal_id, mapped)
                        control.log(f'Set watching on {flavor.flavor_name} (ep {episode}/{total})')

            except Exception as e:
                control.log(f'Failed to update on {flavor.flavor_name}: {e}; queuing retry', 'warning')
                database.enqueue_scrobble_retry(flavor.flavor_name, 'update_episode', mal_id, episode=int(episode or 0), error=str(e))

        return any_completed

    @staticmethod
    def watchlist_set_all_status(mal_id, status):
        """Set status on ALL enabled watchlists using unified status mapping."""
        flavors = WatchlistFlavor.get_all_update_flavors()
        results = {}
        for flavor in flavors:
            mapped_status = WatchlistFlavor._STATUS_MAP.get(status, {}).get(flavor.flavor_name, status)
            try:
                result = flavor.update_list_status(mal_id, mapped_status)
                results[flavor.flavor_name] = result
                control.log(f'Set status {mapped_status} on {flavor.flavor_name}: {result}')
            except Exception as e:
                control.log(f'Failed to set status on {flavor.flavor_name}: {e}', 'warning')
                results[flavor.flavor_name] = False
        return results

    @staticmethod
    def watchlist_set_all_score(mal_id, score):
        """Set score on ALL enabled watchlists."""
        flavors = WatchlistFlavor.get_all_update_flavors()
        results = {}
        for flavor in flavors:
            try:
                result = flavor.update_score(mal_id, score)
                results[flavor.flavor_name] = result
                control.log(f'Set score {score} on {flavor.flavor_name}: {result}')
            except Exception as e:
                control.log(f'Failed to set score on {flavor.flavor_name}: {e}', 'warning')
                results[flavor.flavor_name] = False
        return results

    @staticmethod
    def watchlist_delete_all_anime(mal_id):
        """Delete anime from ALL enabled watchlists."""
        flavors = WatchlistFlavor.get_all_update_flavors()
        results = {}
        for flavor in flavors:
            try:
                result = flavor.delete_anime(mal_id)
                results[flavor.flavor_name] = result
                control.log(f'Deleted from {flavor.flavor_name}: {result}')
            except Exception as e:
                control.log(f'Failed to delete from {flavor.flavor_name}: {e}', 'warning')
                results[flavor.flavor_name] = False
        return results

    @staticmethod
    def watchlist_sync_all():
        """Run save_completed on ALL enabled watchlists and merge results."""
        import json
        flavors = WatchlistFlavor.get_all_update_flavors()
        merged_completed = {}
        synced = []
        for flavor in flavors:
            try:
                completed = flavor.save_completed()
                if completed:
                    merged_completed.update(completed)
                synced.append(flavor.flavor_name)
                control.log(f'Synced completed for {flavor.flavor_name} ({len(completed) if completed else 0} entries)')
            except Exception as e:
                control.log(f'Failed to sync completed for {flavor.flavor_name}: {e}', 'warning')

        # Write merged completed data from all flavors once (only when non-empty to prevent wiping on transient errors)
        if merged_completed:
            control.atomic_write_json(control.completed_json, merged_completed)
            control.log(f'Wrote {len(merged_completed)} total completed entries to completed.json')
        return synced

    # ==================== Single-Flavor Methods (for Watchlist Manager) ====================

    @staticmethod
    def watchlist_anime_entry_request(mal_id):
        """Get watchlist anime entry from first available enabled flavor."""
        flavor = WatchlistFlavor.get_first_enabled_flavor()
        if flavor:
            return flavor.get_watchlist_anime_entry(mal_id)
        return {}

    @staticmethod
    def context_statuses_for_flavor(flavor_name):
        """Get action statuses for a specific flavor (used by Watchlist Manager)."""
        flavor = WatchlistFlavor.get_flavor_by_name(flavor_name)
        if flavor:
            return flavor.action_statuses()
        return []

    @staticmethod
    def watchlist_update_episode_for_flavor(flavor_name, mal_id, episode):
        """Update episode on a specific flavor only."""
        flavor = WatchlistFlavor.get_flavor_by_name(flavor_name)
        if flavor:
            return flavor.update_num_episodes(mal_id, episode)
        return False

    @staticmethod
    def watchlist_set_status_for_flavor(flavor_name, mal_id, status):
        """Set status on a specific flavor only."""
        flavor = WatchlistFlavor.get_flavor_by_name(flavor_name)
        if flavor:
            return flavor.update_list_status(mal_id, status)
        return False

    @staticmethod
    def watchlist_set_score_for_flavor(flavor_name, mal_id, score):
        """Set score on a specific flavor only."""
        flavor = WatchlistFlavor.get_flavor_by_name(flavor_name)
        if flavor:
            return flavor.update_score(mal_id, score)
        return False

    @staticmethod
    def watchlist_delete_anime_for_flavor(flavor_name, mal_id):
        """Delete anime from a specific flavor only."""
        flavor = WatchlistFlavor.get_flavor_by_name(flavor_name)
        if flavor:
            return flavor.delete_anime(mal_id)
        return False
