# -*- coding: utf-8 -*-
"""plugin.video.otaku.rpdev/service.py - Backwards-Compatible Facade for otaku_service.

As of v6.7.0, Kodi's `xbmc.service` background daemon runs inside companion add-on
`service.otaku.rpdev`. This module remains as a thin re-export facade for internal
plugin callers (`routes/tools.py`, `routes/playback.py`, `ui/player.py`,
`ui/database_sync.py`, `WatchlistIntegration.py`) and existing tests, and retains
plugin-local UI/addon.xml helpers (`getChangeLog`, `getInstructions`,
`toggle_reuselanguageinvoker`).
"""

import os
import sys

import xbmc  # noqa: F401
import xbmcaddon
import xbmcvfs

from resources.lib.ui import control, client, database_sync  # noqa: F401


def _ensure_otaku_service_on_path():
    """Ensure service.otaku.rpdev/resources/lib is importable even outside Kodi's xbmc.python.module loader."""
    candidates = []
    try:
        svc_path = xbmcaddon.Addon('service.otaku.rpdev').getAddonInfo('path')
        if svc_path:
            translated = xbmcvfs.translatePath(svc_path)
            if translated:
                candidates.append(os.path.join(translated, 'resources', 'lib'))
    except Exception:
        pass
    repo_sibling = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'service.otaku.rpdev',
        'resources',
        'lib',
    )
    candidates.append(repo_sibling)
    for lib_dir in candidates:
        if lib_dir and os.path.isdir(lib_dir) and lib_dir not in sys.path:
            sys.path.insert(0, lib_dir)


_ensure_otaku_service_on_path()

from otaku_service.sync import (  # noqa: E402, F401
    MAPPINGS_XZ_URL,
    MAPPINGS_MANIFEST_URL,
    MAPPINGS_FALLBACK_URL,
    METADATA_XZ_URL,
    _MAPPINGS_SYNC_LOCK,
    _decompress_mappings_payload,
    _fetch_mappings_manifest_sha256,
    update_metadata_db,
    update_mappings_db,
    _maybe_sync_daily_mappings,
    _mappings_has_dub_data,
    update_dub_json,
)
from otaku_service.daemon import (  # noqa: E402, F401
    _MENU_SETTINGS,
    refresh_apis,
    update_calendars,
    cleanup_cache_databases,
    sync_watchlist,
    prefetch_watchlist,
    prefetch_calendar,
    version_check,
    _get_settings_schema_entries,
    load_settings,
    _get_menu_settings_snapshot,
    Monitor,
    MultipageWorker,
    _shutdown_cleanup,
    _run_periodic_maintenance_tick,
    _check_plugin_hot_update,
)


def getChangeLog():
    changelog_path = os.path.join(control.ADDON_PATH, 'changelog.txt')
    news_path = os.path.join(control.ADDON_PATH, 'news.txt')

    try:
        with open(changelog_path, encoding='utf-8') as changelog_file:
            changelog_text = changelog_file.read()
    except OSError:
        changelog_text = ''

    try:
        with open(news_path, encoding='utf-8') as news_file:
            news_text = news_file.read()
    except OSError:
        news_text = ''

    heading = '[B]%s -  v%s - ChangeLog & News[/B]' % (control.ADDON_NAME, control.ADDON_VERSION)
    from resources.lib.windows.textviewer import TextViewerXML
    windows = None
    try:
        windows = TextViewerXML('textviewer.xml', control.ADDON_PATH, heading=heading, changelog_text=changelog_text, news_text=news_text)
        windows.run()
    finally:
        if windows is not None:
            try:
                windows.close()
            except Exception:
                pass
            del windows


def getInstructions():
    instructions_path = os.path.join(control.ADDON_PATH, 'Instructions.txt')

    try:
        with open(instructions_path, encoding='utf-8') as instructions_file:
            instructions_text = instructions_file.read()
    except OSError:
        instructions_text = ''

    heading = '[B]%s -  v%s - Instructions[/B]' % (control.ADDON_NAME, control.ADDON_VERSION)
    from resources.lib.windows.textviewer import TextViewerXML
    windows = None
    try:
        windows = TextViewerXML('textviewer_1.xml', control.ADDON_PATH, heading=heading, instructions_text=instructions_text)
        windows.run()
    finally:
        if windows is not None:
            try:
                windows.close()
            except Exception:
                pass
            del windows


def toggle_reuselanguageinvoker(forced_state=None):
    def _store_and_reload(output):
        AddonXml = "".join(output)
        control.atomic_write_text(file_path, AddonXml)
        if not forced_state:
            control.ok_dialog(control.ADDON_NAME, 'Language Invoker option has been changed, reloading kodi profile')
            control.execute('LoadProfile({})'.format(control.xbmc.getInfoLabel("system.profilename")))
    file_path = os.path.join(control.ADDON_PATH, "addon.xml")
    try:
        with open(file_path, encoding='utf-8') as addon_xml:
            file_lines = addon_xml.readlines()
    except OSError:
        return
    for i in range(len(file_lines)):
        line_string = file_lines[i]
        if "reuselanguageinvoker" in file_lines[i]:
            cur_value = "true" if "true" in line_string else ("false" if "false" in line_string else "")
            if (forced_state == 'Enabled' and cur_value == "false") or (forced_state is None and cur_value == "false"):
                file_lines[i] = file_lines[i].replace("false", "true")
                control.setSetting("reuselanguageinvoker.status", "Enabled")
                _store_and_reload(file_lines)
            elif (forced_state == 'Disabled' and cur_value == "true") or (forced_state is None and cur_value == "true"):
                file_lines[i] = file_lines[i].replace("true", "false")
                control.setSetting("reuselanguageinvoker.status", "Disabled")
                _store_and_reload(file_lines)
            break
