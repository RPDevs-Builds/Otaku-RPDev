# -*- coding: utf-8 -*-
"""service.otaku.rpdev/service.py - Sole Kodi xbmc.service Entrypoint for Otaku RPDev.

Startup order:
  1. Run self-contained pre-prune settings migration (ZERO plugin imports).
  2. Wait up to 30s (1s abort-responsive ticks) until plugin.video.otaku.rpdev (v6.7.0+)
     is present on disk without an xbmc.service extension and with SERVICE_ADDON_ID in
     control.py (plain-text disk inspection BEFORE touching sys.path / sys.modules).
  3. Run startup maintenance, start MultipageWorker, and enter standby-aware poll loop
     (5s active / 1s while addonsettings open / 60s standby; 900s periodic maintenance tick).
  4. Enforce <2s deterministic shutdown teardown (1s worker join + PASSIVE WAL checkpoint + pool close).
"""

import os
import sys
import threading
import time
import xml.etree.ElementTree as ET

import xbmc
import xbmcaddon
import xbmcvfs

PLUGIN_ADDON_ID = 'plugin.video.otaku.rpdev'
SERVICE_ADDON_ID = 'service.otaku.rpdev'
_SERVICE_LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', 'lib')
if _SERVICE_LIB_DIR not in sys.path:
    sys.path.insert(0, _SERVICE_LIB_DIR)

from otaku_service import migration  # noqa: E402


def _locate_otaku_plugin_path():
    """Return filesystem path of plugin.video.otaku.rpdev if installed, else None."""
    try:
        addon = xbmcaddon.Addon(PLUGIN_ADDON_ID)
        raw_path = addon.getAddonInfo('path')
        if raw_path:
            translated = xbmcvfs.translatePath(raw_path)
            if translated and os.path.isdir(translated):
                return translated
    except Exception:
        pass

    repo_sibling = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        PLUGIN_ADDON_ID,
    )
    if os.path.isdir(repo_sibling):
        return repo_sibling
    return None


def _plugin_supports_service_addon(plugin_path):
    """Plain-text on-disk readiness check BEFORE touching sys.path or importing resources.*.

    Returns True only when:
      - plugin.video.otaku.rpdev/addon.xml exists and does NOT declare xbmc.service
      - plugin.video.otaku.rpdev/resources/lib/ui/control.py contains SERVICE_ADDON_ID
    """
    if not plugin_path or not os.path.isdir(plugin_path):
        return False

    addon_xml = os.path.join(plugin_path, 'addon.xml')
    control_py = os.path.join(plugin_path, 'resources', 'lib', 'ui', 'control.py')
    if not os.path.isfile(addon_xml) or not os.path.isfile(control_py):
        return False

    try:
        root = ET.parse(addon_xml).getroot()
        for ext in root.findall('./extension'):
            if (ext.get('point') or '').strip() == 'xbmc.service':
                return False
    except Exception:
        return False

    try:
        with open(control_py, 'r', encoding='utf-8', errors='ignore') as cf:
            text = cf.read()
        return 'SERVICE_ADDON_ID' in text
    except OSError:
        return False


def _wait_for_compatible_plugin(monitor, max_wait_s=30.0):
    """Wait up to max_wait_s in 1.0s abort-responsive ticks for v6.7.0+ plugin on disk."""
    deadline = time.monotonic() + float(max_wait_s)
    while not monitor.abortRequested():
        path = _locate_otaku_plugin_path()
        if path and _plugin_supports_service_addon(path):
            if path not in sys.path:
                sys.path.insert(0, path)
            return path
        if time.monotonic() >= deadline:
            return None
        if monitor.waitForAbort(1.0):
            return None
    return None


def run_service_loop(monitor=None, max_wait_s=30.0):
    """Main xbmc.service execution entrypoint (testable without __main__ side effects)."""
    mon = monitor or xbmc.Monitor()

    # 1. Self-contained pre-prune settings migration (zero plugin imports)
    migration.migrate_service_settings()
    migration.migrate_subtitle_settings()

    # 2. Bounded readiness wait before adding plugin to sys.path
    plugin_path = _wait_for_compatible_plugin(mon, max_wait_s=max_wait_s)
    if not plugin_path:
        try:
            xbmc.log(
                f'OTAKU RPDEV SERVICE (0): {PLUGIN_ADDON_ID} (v6.7.0+) not ready or disabled; exiting cleanly',
                xbmc.LOGWARNING,
            )
        except Exception:
            pass
        return False

    from resources.lib.ui import control, database_sync, domains
    from otaku_service import daemon, sync

    control.log('##################  RUNNING MAINTENANCE  ######################')
    if control.getBool('general.kodi.cache'):
        daemon.load_settings()
    control.process_context()
    daemon.version_check()
    database_sync.SyncDatabase()
    daemon.refresh_apis()

    if control.getInt('update.time.30') == 0 or control.getInt('update.time.7') == 0:
        threading.Thread(target=sync._maybe_sync_daily_mappings, daemon=True).start()
        sync.update_dub_json(force=False)
        daemon.sync_watchlist(True)
        daemon.cleanup_cache_databases()
        control.setInt('update.time.7', int(time.time()))
        control.setInt('update.time.1', int(time.time()))
    else:
        now_ts = int(time.time())
        did_watchlist_sync = False
        if now_ts > control.getInt('update.time.30') + 86_400:
            threading.Thread(target=sync._maybe_sync_daily_mappings, daemon=True).start()
        if now_ts > control.getInt('update.time.7') + 604_800:
            sync.update_dub_json(force=False)
            daemon.sync_watchlist(True)
            did_watchlist_sync = True
            daemon.cleanup_cache_databases()
            control.setInt('update.time.7', now_ts)
        if now_ts > control.getInt('update.time.1') + 86_400:
            if not did_watchlist_sync:
                daemon.sync_watchlist(True)
            try:
                from resources.lib.ui import database
                database.prune_stale_multipage_jobs()
            except Exception:
                pass
            control.setInt('update.time.1', now_ts)

    mem_state = control.enforce_memory_watermark(context='service_startup')
    skip_startup_prefetch = bool(mem_state.get('triggered') or control.getGlobalProp('otaku.memory_pressure') == 'true')
    if not skip_startup_prefetch:
        threading.Thread(target=daemon.prefetch_watchlist, daemon=True).start()
        threading.Thread(target=daemon.prefetch_calendar, daemon=True).start()
    else:
        control.log("Service: Skipping background pre-caching due to 32-bit memory pressure", 'warning')

    threading.Thread(target=domains.refresh_domains, daemon=True).start()
    control.log('##################  MAINTENANCE COMPLETE ######################')

    svc_monitor = daemon.Monitor()
    multipage_worker = daemon.MultipageWorker(monitor=svc_monitor)
    if skip_startup_prefetch:
        multipage_worker.set_memory_pressure(True, max_workers=1)
    multipage_worker.start()

    standby_state = {
        'in_standby': False,
        'plugin_version': daemon._read_plugin_addon_version(),
    }
    last_maintenance_ts = time.monotonic()
    was_settings_open = False

    try:
        while not svc_monitor.abortRequested():
            in_standby = control.is_device_in_standby()
            settings_open = False
            if not in_standby:
                try:
                    settings_open = bool(xbmc.getCondVisibility('Window.IsActive(addonsettings)'))
                except Exception:
                    settings_open = False

            if was_settings_open and not settings_open:
                svc_monitor.check_plugin_settings_changed(force=False)
                svc_monitor.check_subtitle_settings_changed(force=False)
            was_settings_open = settings_open

            if not in_standby and not settings_open:
                svc_monitor.check_plugin_settings_changed(force=False)
                svc_monitor.check_subtitle_settings_changed(force=False)

            now_mono = time.monotonic()
            if (now_mono - last_maintenance_ts) >= 900.0:
                last_maintenance_ts = now_mono
                daemon._run_periodic_maintenance_tick(multipage_worker, standby_state)

            poll_s = 60.0 if in_standby else (1.0 if settings_open else 5.0)
            if svc_monitor.waitForAbort(poll_s):
                break
    finally:
        daemon._shutdown_cleanup(multipage_worker)

    return True


if __name__ == '__main__':
    run_service_loop()
