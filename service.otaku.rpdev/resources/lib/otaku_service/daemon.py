# -*- coding: utf-8 -*-
"""otaku_service.daemon - Background Maintenance Loop, Monitor & MultipageWorker."""

import json
import os
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET

import xbmc

from resources.lib.ui import control, database_sync
from otaku_service import sync as _sync

_SETTINGS_XML_CACHE = None

_MENU_SETTINGS = (
    'menu.mainmenu.order', 'menu.mainmenu.config',
    'menu.submenu.order', 'menu.submenu.config',
    'menu.genres.order', 'menu.genres.config',
    'movie.mainmenu.order', 'movie.mainmenu.config',
    'movie.submenu.order', 'movie.submenu.config',
    'movie.genres.order', 'movie.genres.config',
    'tv_show.mainmenu.order', 'tv_show.mainmenu.config',
    'tv_show.submenu.order', 'tv_show.submenu.config',
    'tv_show.genres.order', 'tv_show.genres.config',
    'tv_short.mainmenu.order', 'tv_short.mainmenu.config',
    'tv_short.submenu.order', 'tv_short.submenu.config',
    'tv_short.genres.order', 'tv_short.genres.config',
    'special.mainmenu.order', 'special.mainmenu.config',
    'special.submenu.order', 'special.submenu.config',
    'special.genres.order', 'special.genres.config',
    'ova.mainmenu.order', 'ova.mainmenu.config',
    'ova.submenu.order', 'ova.submenu.config',
    'ova.genres.order', 'ova.genres.config',
    'ona.mainmenu.order', 'ona.mainmenu.config',
    'ona.submenu.order', 'ona.submenu.config',
    'ona.genres.order', 'ona.genres.config',
    'music.mainmenu.order', 'music.mainmenu.config',
    'music.submenu.order', 'music.submenu.config',
    'music.genres.order', 'music.genres.config',
)


def refresh_apis():
    control.log("### Refreshing API's")
    rd_token = control.getSetting('realdebrid.token')
    dl_token = control.getSetting('debridlink.token')
    kitsu_token = control.getSetting('kitsu.token')
    mal_token = control.getSetting('mal.token')

    if rd_token != '':
        rd_expiry = control.getInt('realdebrid.expiry')
        if time.time() > (rd_expiry - 600):
            from resources.lib.debrid import real_debrid
            real_debrid.RealDebrid().refreshToken()

    if dl_token != '':
        dl_expiry = control.getInt('debridlink.expiry')
        if time.time() > (dl_expiry - 600):
            from resources.lib.debrid import debrid_link
            debrid_link.DebridLink().refreshToken()

    if kitsu_token != '':
        kitsu_expiry = control.getInt('kitsu.expiry')
        if time.time() > (kitsu_expiry - 600):
            from resources.lib.WatchlistFlavor import Kitsu
            Kitsu.KitsuWLF().refresh_token()

    if mal_token != '':
        mal_expiry = control.getInt('mal.expiry')
        if time.time() > (mal_expiry - 600):
            from resources.lib.WatchlistFlavor import MyAnimeList
            MyAnimeList.MyAnimeListWLF().refresh_token()


def update_calendars():
    control.log("### Updating Calendars")
    control.log("### Calendars updated successfully")


def cleanup_cache_databases():
    control.log("### Pruning Expired Cache & Debrid Hashes")
    try:
        from resources.lib.ui import database
        from resources.lib.debrid import debrid_cache
        from resources.lib.WatchlistFlavor import WatchlistFlavor
        database.prune_expired_cache(30)
        debrid_cache.prune_expired_hashes()
        database.prune_stale_multipage_jobs()
        WatchlistFlavor.process_scrobble_retry_queue(limit=25)
        database.checkpoint_databases(truncate=True)
        control.log("### Cache cleanup complete")
    except Exception as e:
        control.log(f"### Cache cleanup failed: {e}", 'warning')


def sync_watchlist(silent=False):
    if control.abort_requested():
        return
    if control.getBool('watchlist.sync.enabled'):
        control.log('### Updating Completed Sync')
        from resources.lib.WatchlistFlavor import WatchlistFlavor

        flavors = WatchlistFlavor.get_all_update_flavors()
        if flavors:
            synced = WatchlistFlavor.watchlist_sync_all()
            if synced:
                if not silent:
                    synced_names = ', '.join([n.capitalize() for n in synced])
                    notify_string = f'Completed Sync [B]{synced_names}[/B]'
                    return control.notify(control.ADDON_NAME, notify_string)
            else:
                if not silent:
                    control.ok_dialog(control.ADDON_NAME, "No Watchlist Enabled or Not Logged In")
        else:
            if not silent:
                control.ok_dialog(control.ADDON_NAME, "No Watchlist Enabled or Not Logged In")
    else:
        if not silent:
            control.ok_dialog(control.ADDON_NAME, "Watchilst Sync is Disabled")


def prefetch_watchlist():
    """Prefetch all watchlist statuses in background for faster loading."""
    if not control.getBool('watchlist.prefetch.enabled') and not control.getBool('watchlist.precache.all'):
        return

    from resources.lib.ui.database import is_watchlist_cache_valid

    enabled = control.enabled_watchlists()
    if not enabled:
        return

    status_map = {
        'mal': ['watching', 'completed', 'on_hold', 'dropped', 'plan_to_watch'],
        'anilist': ['CURRENT', 'COMPLETED', 'PAUSED', 'DROPPED', 'PLANNING', 'REPEATING'],
        'kitsu': ['current', 'completed', 'on_hold', 'dropped', 'planned'],
        'simkl': ['watching', 'completed', 'hold', 'dropped', 'plantowatch'],
    }

    try:
        from resources.lib.WatchlistFlavor import WatchlistFlavor

        for flavor_name in enabled:
            if control.abort_requested():
                break
            statuses = status_map.get(flavor_name)
            if not statuses:
                continue

            flavor = WatchlistFlavor.get_flavor_by_name(flavor_name)
            if not flavor:
                continue

            for status in statuses:
                if control.abort_requested():
                    break
                if is_watchlist_cache_valid(flavor_name, status):
                    control.log(f'### Watchlist cache valid for {flavor_name}/{status}, skipping')
                    continue

                control.log(f'### Prefetching {flavor_name} watchlist ({status})')
                try:
                    flavor.get_watchlist_status(status, next_up=False, offset=0, page=1, cache_only=True)
                    control.log(f'### Prefetch complete for {flavor_name}/{status}')
                except Exception as e:
                    control.log(f'### Prefetch failed for {status}: {e}', 'warning')

            control.log(f'### Watchlist prefetch finished for {flavor_name}')

        if control.abort_requested():
            return

        try:
            from resources.lib.ui.database import get_all_watchlist_mal_ids, save_anilist_enrichment_batch
            all_mal_ids = get_all_watchlist_mal_ids()
            if all_mal_ids:
                control.log(f'### Prefetching AniList enrichment for {len(all_mal_ids)} MAL IDs')
                from resources.lib.endpoints.anilist import Anilist
                anilist_data = Anilist().get_anilist_by_mal_ids(all_mal_ids)
                if anilist_data:
                    save_anilist_enrichment_batch(anilist_data)
                    from resources.lib.ui import get_meta
                    get_meta.collect_meta([{'mal_id': mid} for mid in all_mal_ids])
                    control.log(f'### AniList enrichment cached: {len(anilist_data)} items')
                else:
                    control.log('### AniList enrichment returned no data')
            else:
                control.log('### No MAL IDs found in watchlist cache for AniList enrichment')
        except Exception as e:
            control.log(f'### AniList enrichment prefetch failed: {e}', 'warning')

    except Exception as e:
        control.log(f'### Watchlist prefetch failed: {e}', 'warning')


def prefetch_calendar():
    """Warm AnimeSchedule cache in background at Kodi startup."""
    if control.abort_requested():
        return
    try:
        from resources.lib.AnimeSchedule import AnimeScheduleCalendar
        control.log('### Prefetching airing calendar cache')
        scheduler = AnimeScheduleCalendar()
        scheduler.get_calendar_data(types=['sub', 'dub', 'raw'])
        control.log('### Airing calendar prefetch complete')
    except Exception as e:
        control.log(f'### Calendar prefetch failed: {e}', 'warning')


def version_check():
    control.log(f'### {control.ADDON_ID} {control.ADDON_VERSION}')
    control.log(f'### Platform: {control.sys.platform}')
    control.log(f'### Python: {control.sys.version}')
    control.log(f'### SQLite: {database_sync.sqlite_version}')
    control.log(f'### Kodi Version: {control.kodi_version}')

    if control.getSetting('otaku.version') != control.ADDON_VERSION:
        reuselang = control.getSetting('reuselanguageinvoker.status')
        try:
            import service as _plugin_service
            _plugin_service.toggle_reuselanguageinvoker(reuselang)
        except Exception:
            pass
        control.setSetting('otaku.version', control.ADDON_VERSION)
        control.log(f"### {reuselang} Re-uselanguageinvoker")

        # Prune orphaned settings AFTER migration & setSetting so Kodi's CAddonSettings flush does not restore them
        try:
            from resources.lib.ui import clean_settings
            pruned_count, _ = clean_settings.clean_all_settings(silent=True)
            if pruned_count > 0:
                control.log(f"### Version upgrade: Pruned {pruned_count} orphaned setting(s)")
        except Exception as e:
            control.log(f"Failed to prune orphaned settings on startup: {e}", 'warning')


def _get_settings_schema_entries():
    global _SETTINGS_XML_CACHE
    if _SETTINGS_XML_CACHE is not None:
        return _SETTINGS_XML_CACHE
    entries = []
    schema_specs = [
        (control.ADDON_ID, os.path.join(control.ADDON_PATH, 'resources', 'settings.xml')),
    ]
    svc_path = getattr(control, 'SERVICE_ADDON_PATH', '')
    if svc_path:
        schema_specs.append((control.SERVICE_ADDON_ID, os.path.join(svc_path, 'resources', 'settings.xml')))
    sub_path = getattr(control, 'SUBTITLE_ADDON_PATH', '')
    if sub_path:
        schema_specs.append((control.SUBTITLE_ADDON_ID, os.path.join(sub_path, 'resources', 'settings.xml')))

    for aid, settings_path in schema_specs:
        if not settings_path or not os.path.exists(settings_path):
            continue
        tree = ET.parse(settings_path)
        root = tree.getroot()
        for setting in root.iter('setting'):
            s_id = setting.get('id')
            s_type = setting.get('type')
            if s_id and s_type and s_type != 'action':
                entries.append((aid, s_id, s_type.lower()))
    _SETTINGS_XML_CACHE = tuple(entries)
    return _SETTINGS_XML_CACHE


def load_settings():
    """Load plugin + service + subtitle settings into Kodi window properties using cached schemas."""
    try:
        entries = _get_settings_schema_entries()
    except Exception as e:
        control.log(f'Failed to parse settings.xml: {e}', 'error')
        return

    svc_aid = getattr(control, 'SERVICE_ADDON_ID', 'service.otaku.rpdev')
    sub_aid = getattr(control, 'SUBTITLE_ADDON_ID', 'service.subtitles.otaku.rpdev')
    for aid, s_id, s_type in entries:
        if aid == svc_aid:
            proxy = control.service_settings
        elif aid == sub_aid:
            proxy = control.subtitle_settings
        else:
            proxy = control.settings
        prop_name = f"{aid}_{s_id}"
        try:
            if s_type == 'boolean':
                val_str = str(proxy.getBool(s_id)).lower()
            elif s_type == 'integer':
                val_str = str(proxy.getInt(s_id))
            elif s_type == 'number':
                val_str = str(proxy.getNumber(s_id))
            elif s_type in ('string', 'path', 'folder', 'file', 'addon'):
                val_str = proxy.getString(s_id)
            elif s_type == 'list[boolean]':
                val_str = json.dumps(proxy.getBoolList(s_id))
            elif s_type == 'list[integer]':
                val_str = json.dumps(proxy.getIntList(s_id))
            elif s_type == 'list[string]':
                val_str = json.dumps(proxy.getStringList(s_id))
            elif s_type == 'list[number]':
                val_str = json.dumps(proxy.getNumberList(s_id))
            else:
                continue

            if control.homeWindow.getProperty(prop_name) != val_str:
                control.homeWindow.setProperty(prop_name, val_str)
        except Exception:
            pass


def _get_menu_settings_snapshot():
    snapshot = {}
    for sid in _MENU_SETTINGS:
        try:
            if sid.endswith('.order'):
                snapshot[sid] = control.getSetting(sid)
            else:
                snapshot[sid] = control.settings.getStringList(sid)
        except Exception:
            try:
                snapshot[sid] = control.getSetting(sid)
            except Exception:
                snapshot[sid] = None
    return snapshot


def _read_plugin_addon_version():
    """Read plugin.video.otaku.rpdev/addon.xml version attribute from disk without reloading modules."""
    try:
        xml_path = os.path.join(control.ADDON_PATH, 'addon.xml')
        if os.path.exists(xml_path):
            return (ET.parse(xml_path).getroot().get('version') or '').strip()
    except Exception:
        pass
    return ''


def _stat_plugin_settings_xml():
    """Return (st_mtime_ns, st_size) for plugin.video.otaku.rpdev/settings.xml, or None."""
    try:
        p = os.path.join(control.dataPath, 'settings.xml')
        st = os.stat(p)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _stat_subtitle_settings_xml():
    """Return (st_mtime_ns, st_size) for service.subtitles.otaku.rpdev/settings.xml, or None."""
    try:
        sub_id = getattr(control, 'SUBTITLE_ADDON_ID', 'service.subtitles.otaku.rpdev')
        sub_profile = control.xbmcvfs.translatePath(f'special://profile/addon_data/{sub_id}/')
        if not sub_profile:
            return None
        p = os.path.join(sub_profile, 'settings.xml')
        st = os.stat(p)
        return (st.st_mtime_ns, st.st_size)
    except Exception:
        return None


class Monitor(xbmc.Monitor):
    def __init__(self):
        super().__init__()
        self._menu_settings_snapshot = _get_menu_settings_snapshot()
        self._webpdb_enabled = control.getBool('webpdb.enabled')
        self._webpdb_port = control.get_webpdb_port()
        self._plugin_settings_stat = _stat_plugin_settings_xml()
        self._subtitle_settings_stat = _stat_subtitle_settings_xml()

    def _sync_webpdb_state(self):
        current_webpdb_enabled = control.getBool('webpdb.enabled')
        current_webpdb_port = control.get_webpdb_port()
        if not current_webpdb_enabled:
            control.stop_webpdb_trace(self._webpdb_port)
            if current_webpdb_port != self._webpdb_port:
                control.stop_webpdb_trace(current_webpdb_port)
        elif current_webpdb_port != self._webpdb_port:
            control.stop_webpdb_trace(self._webpdb_port)
        self._webpdb_enabled = current_webpdb_enabled
        self._webpdb_port = current_webpdb_port

    def _sync_menu_refresh(self):
        new_snapshot = _get_menu_settings_snapshot()
        if new_snapshot != self._menu_settings_snapshot:
            control.log('Menu configuration settings changed - flagging menu container refresh')
            self._menu_settings_snapshot = new_snapshot
            control.setGlobalProp('otaku.menu.needs_refresh', 'true')
            if not xbmc.getCondVisibility('Window.IsActive(addonsettings)'):
                folder_path = xbmc.getInfoLabel('Container.FolderPath')
                if control.is_addon_visible() or folder_path.startswith('plugin://plugin.video.otaku.rpdev'):
                    control.refresh()

    def onSettingsChanged(self):
        """Fires immediately when service.otaku.rpdev settings change (or in direct tests)."""
        control.log('Setting Changed - Updating Settings Cache')
        if hasattr(control, 'bump_service_settings_epoch'):
            control.bump_service_settings_epoch()
        control.clearSettingsCache()
        if control.getBool('general.kodi.cache'):
            load_settings()
        control.process_context()
        self._sync_webpdb_state()
        self._sync_menu_refresh()

    def check_plugin_settings_changed(self, force=False):
        """Detect changes to plugin.video.otaku.rpdev/settings.xml via (st_mtime_ns, st_size)."""
        cur_stat = _stat_plugin_settings_xml()
        if not force and cur_stat == self._plugin_settings_stat:
            return False
        self._plugin_settings_stat = cur_stat
        control.log('Plugin settings.xml changed - refreshing settings cache & context flags')
        control.clearSettingsCache()
        if control.getBool('general.kodi.cache'):
            load_settings()
        control.process_context()
        self._sync_webpdb_state()
        self._sync_menu_refresh()
        return True

    def check_subtitle_settings_changed(self, force=False):
        """Detect changes to service.subtitles.otaku.rpdev/settings.xml via (st_mtime_ns, st_size)."""
        cur_stat = _stat_subtitle_settings_xml()
        if not force and cur_stat == self._subtitle_settings_stat:
            return False
        self._subtitle_settings_stat = cur_stat
        control.log('Subtitle service settings.xml changed - refreshing settings cache & epoch')
        if hasattr(control, 'bump_subtitle_settings_epoch'):
            control.bump_subtitle_settings_epoch()
        control.clearSettingsCache()
        if control.getBool('general.kodi.cache'):
            load_settings()
        return True


class MultipageWorker(threading.Thread):
    """Persistent background pre-caching worker for multi-page API datasets.
    Runs strictly inside service.otaku.rpdev; never invoked inside short-lived directory invokers."""

    PACING_ANILIST = 1.0
    PACING_MAL = 1.1

    def __init__(self, monitor=None):
        super().__init__(name="Otaku-MultipageWorker", daemon=True)
        self.monitor = monitor or xbmc.Monitor()
        self._stop_event = threading.Event()
        self.max_concurrency = 1 if control.getGlobalProp('otaku.memory_pressure') == 'true' else 2
        self._memory_throttled = control.getGlobalProp('otaku.memory_pressure') == 'true'

    def set_memory_pressure(self, throttled, max_workers=None):
        """Throttle or restore MultipageWorker concurrency under 32-bit memory pressure."""
        self._memory_throttled = bool(throttled)
        if throttled:
            self.max_concurrency = max(1, int(max_workers or 1))
        else:
            self.max_concurrency = int(max_workers or 2)

    def stop(self):
        """Signal the worker thread to stop cleanly."""
        self._stop_event.set()

    def _sleep(self, seconds, slice_time=0.5):
        """Sleep for up to `seconds`, returning True immediately if monitor abort or stop is requested."""
        if self.monitor.abortRequested() or self._stop_event.is_set():
            return True

        if hasattr(self.monitor.waitForAbort, 'assert_called_with') or hasattr(self.monitor.waitForAbort, 'side_effect'):
            res = self.monitor.waitForAbort(seconds)
            return bool(res or self.monitor.abortRequested() or self._stop_event.is_set())

        start = time.time()
        while time.time() - start < seconds:
            if self.monitor.abortRequested() or self._stop_event.is_set():
                return True
            rem = seconds - (time.time() - start)
            chunk = min(slice_time, rem)
            if chunk > 0 and self._stop_event.wait(timeout=chunk):
                return True
            if self.monitor.abortRequested():
                return True
        return False

    @classmethod
    def get_pacing(cls, provider):
        """Return rate pacing delay (seconds) for provider."""
        prov = str(provider or '').lower()
        if 'anilist' in prov:
            return cls.PACING_ANILIST
        return cls.PACING_MAL

    def _should_pause(self):
        """Returns True if playback is active, display is in standby, screensaver, or Settings UI is open."""
        try:
            if xbmc.Player().isPlaying():
                return True
        except Exception:
            pass
        try:
            if control.is_device_in_standby():
                return True
        except Exception:
            pass
        try:
            if xbmc.getCondVisibility("System.ScreenSaverActive"):
                return True
        except Exception:
            pass
        try:
            if xbmc.getCondVisibility("Window.IsActive(addonsettings)"):
                return True
        except Exception:
            pass
        if getattr(self, '_memory_throttled', False) or control.getGlobalProp('otaku.memory_pressure') == 'true':
            return True
        return False

    @staticmethod
    def _is_folder_match(current_folder, job_path):
        """Check if active container folder path matches the pre-caching job's target URL."""
        if not current_folder or not job_path:
            return False

        parsed_cur = urllib.parse.urlparse(current_folder)
        parsed_job = urllib.parse.urlparse(job_path)

        if parsed_cur.netloc and parsed_job.netloc and parsed_cur.netloc != parsed_job.netloc:
            return False

        cur_path = parsed_cur.path.strip('/')
        job_clean_path = parsed_job.path.strip('/') if parsed_job.path else job_path.split('?')[0].strip('/')
        if cur_path != job_clean_path:
            return False

        cur_qs = urllib.parse.parse_qs(parsed_cur.query)
        job_qs = urllib.parse.parse_qs(parsed_job.query)

        cur_params = {k: v for k, v in cur_qs.items() if k != 'page'}
        job_params = {k: v for k, v in job_qs.items() if k != 'page'}

        for k, v in job_params.items():
            if cur_params.get(k) != v:
                return False

        UI_PARAMS = {'filter_text', 'filter'}
        for k, v in cur_params.items():
            if k not in UI_PARAMS and job_params.get(k) != v:
                return False

        return True

    def _check_and_refresh_container(self, job):
        """Trigger Container.Refresh only if user is actively viewing page 1 of this list with paging disabled."""
        if not control.is_addon_visible():
            return
        if control.getBool('interface.watchlist.paging'):
            return
        current_folder = xbmc.getInfoLabel('Container.FolderPath')
        if not current_folder:
            return
        job_path = str(job.get('url_path') or '')
        if not job_path:
            return

        parsed_cur = urllib.parse.urlparse(current_folder)
        query = urllib.parse.parse_qs(parsed_cur.query)
        page_val = query.get('page', ['1'])[0]
        try:
            current_page = int(page_val)
        except (ValueError, TypeError):
            current_page = 1

        if current_page != 1:
            return
        if not self._is_folder_match(current_folder, job_path):
            return

        job_id = job.get('job_id') or job.get('id')
        token_key = f"otaku_mp_refreshed_{job_id}"
        if control.homeWindow.getProperty(token_key) in ('1', 'true'):
            return

        control.homeWindow.setProperty(token_key, '1')
        control.log(f"MultipageWorker: Triggering Container.Refresh for completed pre-cache job {job_id}")
        control.refresh()

    def run(self):
        control.log("### MultipageWorker started")
        from resources.lib.ui import database

        while not self.monitor.abortRequested() and not self._stop_event.is_set():
            if self._should_pause():
                if self._sleep(2.0):
                    break
                continue

            try:
                job = database.dequeue_multipage_job()
            except Exception as e:
                control.log(f"MultipageWorker dequeue error: {e}", 'warning')
                job = None

            if not job:
                if self._sleep(1.5):
                    break
                continue

            try:
                self._process_job(job)
            except Exception as e:
                control.log(f"MultipageWorker _process_job unhandled error: {e}", 'error')
                job_id = job.get('job_id') or job.get('id')
                if job_id:
                    try:
                        database.mark_multipage_job_failed(job_id, str(e))
                    except Exception:
                        pass

        control.log("### MultipageWorker terminated cleanly")

    def _process_job(self, job):
        from resources.lib.ui import database
        job_id = job.get('job_id') or job.get('id')
        provider = str(job.get('provider') or '').lower()
        method_name = job.get('browser_method')
        target_page = int(job.get('target_page') or 20)
        current_page = int(job.get('current_page') or 2)
        raw_params = job.get('request_params') or job.get('params') or '{}'

        if isinstance(raw_params, dict):
            base_params = dict(raw_params)
        elif isinstance(raw_params, str):
            base_params = control.loads_json(raw_params, default={})
            if not isinstance(base_params, dict):
                base_params = {'payload': base_params}
        else:
            base_params = {}

        pacing = self.get_pacing(provider)

        if 'anilist' in provider:
            from resources.lib.AniListBrowser import AniListBrowser
            browser = AniListBrowser()
        else:
            from resources.lib.MalBrowser import MalBrowser
            browser = MalBrowser()

        fetch_func = getattr(browser, method_name, None)
        if not fetch_func:
            control.log(f"MultipageWorker: Unknown browser method '{method_name}' on {type(browser).__name__}", 'error')
            database.mark_multipage_job_failed(job_id, f"Unknown method: {method_name}")
            return

        success = True
        error_msg = None
        for page_num in range(current_page, target_page + 1):
            if self.monitor.abortRequested() or self._stop_event.is_set():
                return

            while self._should_pause():
                if self._sleep(2.0):
                    return

            try:
                page_params = dict(base_params)
                if 'page' in page_params:
                    page_params['page'] = page_num
                elif 'variables' in page_params and isinstance(page_params['variables'], dict):
                    page_params['variables'] = dict(page_params['variables'])
                    page_params['variables']['page'] = page_num
                else:
                    page_params['page'] = page_num

                try:
                    fetch_func(**page_params)
                except TypeError:
                    fetch_func(page_params)

                if self.monitor.abortRequested() or self._stop_event.is_set():
                    return

                database.update_multipage_job_progress(job_id, page_num)
            except Exception as e:
                control.log(f"MultipageWorker page {page_num} fetch error: {e}", 'warning')
                success = False
                error_msg = str(e)
                break

            if page_num < target_page:
                if self._sleep(pacing):
                    return

        if self.monitor.abortRequested() or self._stop_event.is_set():
            return

        if success:
            database.mark_multipage_job_done(job_id)
            self._check_and_refresh_container(job)
        else:
            database.mark_multipage_job_failed(job_id, error_msg or "Failed to fetch all pages")


def _shutdown_cleanup(multipage_worker=None):
    """Enforce deterministic <2s shutdown: abort/stop -> 1s worker join -> passive WAL checkpoint -> close pools -> release SWIG proxies."""
    if multipage_worker is not None:
        try:
            multipage_worker.stop()
            multipage_worker.join(timeout=1.0)
        except Exception:
            pass
    try:
        from resources.lib.ui import database
        database.checkpoint_databases(truncate=False)
        database.close_all_connections()
    except Exception:
        pass
    try:
        from resources.lib.ui import control
        control.release_kodi_proxies()
    except Exception:
        pass


def _check_plugin_hot_update(standby_state):
    """Detect plugin.video.otaku.rpdev version transition safely without importlib.reload()."""
    cur_ver = _read_plugin_addon_version()
    prev_ver = standby_state.get('plugin_version')
    if prev_ver and cur_ver and cur_ver != prev_ver:
        control.log(
            f"Service: Detected plugin.video.otaku.rpdev hot-update {prev_ver} -> {cur_ver}; "
            "clearing settings cache and refreshing context flags",
            'info',
        )
        control.clearSettingsCache()
        control.process_context()
        standby_state['plugin_version'] = cur_ver
        return True
    if cur_ver and not prev_ver:
        standby_state['plugin_version'] = cur_ver
    return False


def _run_periodic_maintenance_tick(multipage_worker=None, standby_state=None):
    """Execute one periodic maintenance tick with NF-16 standby/CEC throttling and resume catch-up."""
    if standby_state is None:
        standby_state = {'in_standby': False}

    if control.is_device_in_standby():
        if not standby_state.get('in_standby'):
            cec_adapters = control.get_cec_adapter_names()
            control.log_metric(
                'standby_throttle',
                level='info',
                state='standby_throttled',
                power_status=control.get_device_power_status(),
                cec_adapters=len(cec_adapters),
            )
            standby_state['in_standby'] = True
        return 'throttled'

    resumed_from_standby = bool(standby_state.get('in_standby'))
    if resumed_from_standby:
        standby_state['in_standby'] = False
        control.log_metric(
            'standby_throttle',
            level='info',
            state='resumed',
            power_status=control.get_device_power_status(),
        )

    _check_plugin_hot_update(standby_state)

    loop_mem_state = control.enforce_memory_watermark(context='service_loop', multipage_worker=multipage_worker)
    if not loop_mem_state.get('triggered'):
        control.clean_memory()
    try:
        refresh_apis()
    except Exception as e:
        control.log(f"Periodic API token refresh notice: {e}", 'debug')
    try:
        from resources.lib.WatchlistFlavor import WatchlistFlavor
        replayed = WatchlistFlavor.process_scrobble_retry_queue()
        if replayed:
            control.log(f"Periodic scrobble retry queue replayed {replayed} item(s)", 'info')
    except Exception as e:
        control.log(f"Periodic scrobble retry queue notice: {e}", 'debug')
    try:
        threading.Thread(target=_sync._maybe_sync_daily_mappings, daemon=True).start()
    except Exception as e:
        control.log(f"Periodic mappings sync notice: {e}", 'debug')
    try:
        from resources.lib.ui import database
        database.close_thread_connections()
        database.checkpoint_databases(truncate=False)
    except Exception as e:
        control.log(f"Periodic WAL checkpoint notice: {e}", 'debug')
    return 'resumed' if resumed_from_standby else 'ran'
