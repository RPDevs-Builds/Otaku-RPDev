"""
control.py - Otaku Addon Control & Settings Layer
==================================================
Central hub for addon-wide constants, settings access, GUI helpers,
directory listing, and Kodi integration utilities.

Architecture
------------
Constants    - Addon ID, paths, database files, Kodi objects
Settings     - Cached getters/setters (window property → in-memory → Kodi API)
Logging      - Unified log() helper with level mapping
Debrid/WL    - Helper functions for enabled services
GUI/Dialogs  - Dialog wrappers, notifications, keyboard input
VideoTags    - ListItem metadata builder (set_videotags)
Directory    - draw_items / bulk_dir_list / xbmc_add_dir
View Types   - Container view mode helpers
Context Menu - process_context() for dynamic context menu caching
Utilities    - Misc helpers (clipboard, color, refresh, abort)
"""

import random
import xbmc
import xbmcgui
import xbmcaddon
import xbmcplugin
import xbmcvfs
import os
import sys
import json
import shutil
import threading
import re

from concurrent.futures import ThreadPoolExecutor
from functools import partial
from urllib import parse


# ═══════════════════════════════════════════════════════════════════════════
#  Constants - Addon Identity & Paths
# ═══════════════════════════════════════════════════════════════════════════

_artwork_cache = {}


def _detect_max_threads() -> int:
    """Determine thread limit based on available physical memory and CPU count."""
    cpu = os.cpu_count() or 4
    ram_mb = None
    try:
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                if line.startswith('MemTotal:'):
                    ram_mb = int(line.split()[1]) // 1024
                    break
    except (OSError, ValueError, IndexError):
        pass

    if ram_mb is None:
        try:
            ram_mb = (os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')) // (1024 * 1024)
        except (AttributeError, ValueError, OSError):
            pass

    if ram_mb is not None and ram_mb <= 2048:
        # Low-spec Android TV / Fire TV stick (<= 2 GB RAM)
        return max(2, min(cpu, 4))
    elif ram_mb is not None and ram_mb <= 4096:
        # Mid-tier box (<= 4 GB RAM)
        return max(2, min(cpu, 6))
    else:
        # High-spec device or PC
        return max(2, min(cpu, 8))


max_threads = _detect_max_threads()

try:
    HANDLE = int(sys.argv[1])
except (IndexError, ValueError):
    print('No handle found, using default 0')
    HANDLE = 0

addonInfo = xbmcaddon.Addon().getAddonInfo
ADDON_ID = addonInfo('id')
ADDON = xbmcaddon.Addon(ADDON_ID)
settings = ADDON.getSettings()
language = ADDON.getLocalizedString
addonInfo = ADDON.getAddonInfo
ADDON_NAME = addonInfo('name')
ADDON_VERSION = addonInfo('version')
ADDON_ICON = addonInfo('icon')
OTAKU_FANART = addonInfo('fanart')
ADDON_PATH = ADDON.getAddonInfo('path')
ADDONS_PATH = xbmcvfs.translatePath('special://home/addons/')
pathExists = xbmcvfs.exists
dataPath = xbmcvfs.translatePath(addonInfo('profile'))
kodi_version = float(xbmcaddon.Addon('xbmc.addon').getAddonInfo('version')[:4])

_settings_cache = {}

CONTEXT_ADDON_ID = 'context.otaku.rpdev'
CONTEXT_ADDON = xbmcaddon.Addon(CONTEXT_ADDON_ID)
CONTEXT_ADDON_PATH = CONTEXT_ADDON.getAddonInfo('path')
infoDB = os.path.join(CONTEXT_ADDON_PATH, 'info.db')

# — External API endpoints —
# Jikan v4-schema-compatible MAL metadata provider. Centralized here so a
# future provider swap (e.g. Jikan -> Tenrai) is a one-line change instead
# of a multi-file find/replace.
MAL_API_BASE_URL = "https://api.tenrai.org/v1"

# — Database files —
cacheFile = os.path.join(dataPath, 'cache.db')
searchHistoryDB = os.path.join(dataPath, 'search.db')
malSyncDB = os.path.join(dataPath, 'malSync.db')
mappingDB = os.path.join(dataPath, 'mappings.db')

# — JSON data files —
maldubFile = os.path.join(dataPath, 'mal_dub.json')
downloads_json = os.path.join(dataPath, 'downloads.json')
completed_json = os.path.join(dataPath, 'completed.json')
genre_json = os.path.join(dataPath, 'genres.json')
sort_options_json = os.path.join(dataPath, 'sort_options.json')
watch_history_json = os.path.join(dataPath, 'watch_history.json')
embeds_json = os.path.join(dataPath, 'embeds.json')
animeschedule_calendar_json = os.path.join(dataPath, 'animeschedule_calendar.json')
mal_calendar_json = os.path.join(dataPath, 'mal_calendar.json')
simkl_calendar_json = os.path.join(dataPath, 'simkl_calendar.json')

# — Kodi system paths —
kodi_userdata_path = xbmcvfs.translatePath('special://userdata/')
kodi_advancedsettings_path = os.path.join(kodi_userdata_path, 'advancedsettings.xml')

# — Image / artwork paths —
IMAGES_PATH = os.path.join(ADDON_PATH, 'resources', 'images')
OTAKU_LOGO_PATH = os.path.join(ADDON_PATH, 'resources', 'images', 'trans-goku.png')
OTAKU_LOGO2_PATH = os.path.join(ADDON_PATH, 'resources', 'images', 'trans-goku-small.png')
OTAKU_LOGO3_PATH = os.path.join(ADDON_PATH, 'resources', 'images', 'trans-goku-large.png')
OTAKU_ICONS_PATH = os.path.join(CONTEXT_ADDON_PATH, 'resources', 'images', 'icons', ADDON.getSetting("interface.icons"))
OTAKU_GENRE_PATH = os.path.join(CONTEXT_ADDON_PATH, 'resources', 'images', 'genres')

# — Kodi GUI objects —
dialogWindow = xbmcgui.WindowDialog
homeWindow = xbmcgui.Window(10000)
menuItem = xbmcgui.ListItem
execute = xbmc.executebuiltin
get_region = xbmc.getRegion
trakt_gmt_format = '%Y-%m-%dT%H:%M:%S.000Z'
progressDialog = xbmcgui.DialogProgress()
playList = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
sleep = xbmc.sleep


# ═══════════════════════════════════════════════════════════════════════════
#  Logging
# ═══════════════════════════════════════════════════════════════════════════

def closeBusyDialog():
    if xbmc.getCondVisibility('Window.IsActive(busydialog)'):
        execute('Dialog.Close(busydialog)')
    if xbmc.getCondVisibility('Window.IsActive(busydialognocancel)'):
        execute('Dialog.Close(busydialognocancel)')


# Pre-compiled regex patterns for sensitive data sanitization
_RE_AUTH_BEARER = re.compile(r'(?i)(bearer\s+)([a-zA-Z0-9_\-\.]{8,})')
_RE_URL_PARAMS = re.compile(r'(?i)([\?&][a-zA-Z0-9_\-\.]*?(?:key|token|auth|secret|password)[a-zA-Z0-9_\-\.]*?=)([^&\s]+)')
_RE_JSON_FIELDS = re.compile(r'(?i)(["\']?[a-zA-Z0-9_\-\.]*?(?:key|token|auth|secret|password)[a-zA-Z0-9_\-\.]*?["\']?\s*[:=]\s*["\'])([^"\']{6,})(["\'])')
_RE_BASIC_AUTH = re.compile(r'(?i)(https?://[^:\s@]+:)([^@\s]+)(@)')

_SENSITIVE_SETTING_KEYS = (
    'realdebrid.token', 'alldebrid.token', 'premiumize.token', 'torbox.token',
    'debridlink.token', 'easydebrid.token', 'simkl.token',
    'mal.token', 'kitsu.token'
)


def sanitize_log(msg) -> str:
    """Scrub authentication tokens, passwords, and sensitive keys from log messages."""
    if not isinstance(msg, str):
        msg = str(msg)

    # Fast-path check: avoid regex passes if no sensitive keywords exist
    lower_msg = msg.lower()
    if not any(k in lower_msg for k in ('bearer', 'token', 'key', 'auth', 'secret', 'pass', 'http://', 'https://')):
        return msg

    msg = _RE_AUTH_BEARER.sub(r'\1[REDACTED]', msg)
    msg = _RE_URL_PARAMS.sub(r'\1[REDACTED]', msg)
    msg = _RE_JSON_FIELDS.sub(r'\1[REDACTED]\3', msg)
    msg = _RE_BASIC_AUTH.sub(r'\1[REDACTED]\3', msg)

    # Scrub active user tokens if configured in settings
    for key in _SENSITIVE_SETTING_KEYS:
        try:
            token = getSetting(key)
            if token and len(token) >= 6 and token in msg:
                msg = msg.replace(token, '[REDACTED]')
        except (TypeError, KeyError, ValueError):
            pass

    return msg


def log(msg, level="debug"):
    if level == 'info':
        level = xbmc.LOGINFO
    elif level == 'warning':
        level = xbmc.LOGWARNING
    elif level == 'error':
        level = xbmc.LOGERROR
    elif level == 'debug':
        level = xbmc.LOGDEBUG
    else:
        level = xbmc.LOGNONE
    sanitized = sanitize_log(msg)
    xbmc.log(f'{ADDON_NAME.upper()} ({HANDLE}): {sanitized}', level)


def bin(s):
    return s.encode('latin-1')


# ═══════════════════════════════════════════════════════════════════════════
#  Debrid & Watchlist Helpers
# ═══════════════════════════════════════════════════════════════════════════

def enabled_debrid():
    debrids = ['realdebrid', 'debridlink', 'alldebrid', 'premiumize', 'torbox', 'easydebrid']
    return {x: getSetting(f'{x}.token') != '' and getBool(f'{x}.enabled') for x in debrids}


def easynews_enabled():
    """Easynews: account toggle + provider toggle + HTTP Basic credentials (no pin OAuth)."""
    if not getBool('easynews.enabled'):
        return False
    if not getBool('provider.easynews'):
        return False
    return bool(getSetting('easynews.user') and getSetting('easynews.password'))


def enabled_cloud():
    clouds = ['realdebrid', 'alldebrid', 'premiumize', 'torbox']
    return {x: getSetting(f'{x}.token') != '' and getBool(f'{x}.cloudInspection') for x in clouds}


def enabled_watchlists():
    watchlists = ['anilist', 'kitsu', 'mal', 'simkl']
    return [x for x in watchlists if getSetting(f'{x}.token') != '' and getBool(f'{x}.enabled')]


def copy2clip(txt):
    platform = sys.platform
    if platform == 'win32':
        try:
            os.system('echo %s|clip' % txt)
            return True
        except (AttributeError, OSError):
            pass
    return False


def colorstr(text, color='deepskyblue'):
    return f"[COLOR {color}]{text}[/COLOR]"


def refresh():
    execute('Container.Refresh')


# ═══════════════════════════════════════════════════════════════════════════
#  Settings - Cached Getters & Setters
# ═══════════════════════════════════════════════════════════════════════════

def getSetting(key):
    """Get setting as string - first checks window property cache, then Kodi API"""
    cache = homeWindow.getProperty(f'{ADDON_ID}_{key}')
    if cache:
        return cache
    ck = f's_{key}'
    if ck in _settings_cache:
        return _settings_cache[ck]
    val = settings.getString(key)
    _settings_cache[ck] = val
    return val


def getBool(key, default=False):
    """Get setting as boolean - first checks window property cache, then Kodi API"""
    cache = homeWindow.getProperty(f'{ADDON_ID}_{key}')
    if cache:
        return cache == 'true'
    ck = f'b_{key}'
    if ck in _settings_cache:
        return _settings_cache[ck]
    try:
        val = settings.getBool(key)
    except Exception:
        val = default
    _settings_cache[ck] = val
    return val


def getInt(key, default=0):
    """Get setting as integer - first checks window property cache, then Kodi API"""
    cache = homeWindow.getProperty(f'{ADDON_ID}_{key}')
    if cache:
        try:
            return int(cache)
        except ValueError:
            pass
    ck = f'i_{key}'
    if ck in _settings_cache:
        return _settings_cache[ck]
    try:
        val = settings.getInt(key)
    except Exception:
        val = default
    _settings_cache[ck] = val
    return val


def getStr(key):
    """Get setting as string - first checks window property cache, then Kodi API"""
    cache = homeWindow.getProperty(f'{ADDON_ID}_{key}')
    if cache:
        return cache
    ck = f'gs_{key}'
    if ck in _settings_cache:
        return _settings_cache[ck]
    val = settings.getString(key)
    _settings_cache[ck] = val
    return val


def getNumber(key):
    """Get setting as float/number - first checks window property cache, then Kodi API"""
    cache = homeWindow.getProperty(f'{ADDON_ID}_{key}')
    if cache:
        try:
            return float(cache)
        except ValueError:
            pass
    ck = f'n_{key}'
    if ck in _settings_cache:
        return _settings_cache[ck]
    val = settings.getNumber(key)
    _settings_cache[ck] = val
    return val


def getStringList(settingid):
    """Get setting as list of strings - first checks window property cache, then Kodi API"""
    cache = homeWindow.getProperty(f'{ADDON_ID}_{settingid}')
    if cache:
        try:
            return json.loads(cache)
        except (ValueError, TypeError):
            pass
    return settings.getStringList(settingid)


def getBoolList(settingid):
    """Get setting as list of booleans - first checks window property cache, then Kodi API"""
    cache = homeWindow.getProperty(f'{ADDON_ID}_{settingid}')
    if cache:
        try:
            return json.loads(cache)
        except (ValueError, TypeError):
            pass
    return settings.getBoolList(settingid)


def getIntList(settingid):
    """Get setting as list of integers - first checks window property cache, then Kodi API"""
    cache = homeWindow.getProperty(f'{ADDON_ID}_{settingid}')
    if cache:
        try:
            return json.loads(cache)
        except (ValueError, TypeError):
            pass
    return settings.getIntList(settingid)


def getNumberList(settingid):
    """Get setting as list of numbers - first checks window property cache, then Kodi API"""
    cache = homeWindow.getProperty(f'{ADDON_ID}_{settingid}')
    if cache:
        try:
            return json.loads(cache)
        except (ValueError, TypeError):
            pass
    return settings.getNumberList(settingid)


def _evict_setting(settingid):
    """Evict all cached variants of a setting key."""
    for prefix in ('s_', 'gs_', 'b_', 'i_', 'n_'):
        _settings_cache.pop(f'{prefix}{settingid}', None)
    homeWindow.clearProperty(f'{ADDON_ID}_{settingid}')


def setSetting(settingid, value):
    """Set setting as string - kept for backward compatibility"""
    settings.setString(settingid, str(value))
    _evict_setting(settingid)


def setBool(settingid, value):
    """Set setting as boolean"""
    settings.setBool(settingid, value)
    _evict_setting(settingid)


def setInt(settingid, value):
    """Set setting as integer"""
    settings.setInt(settingid, value)
    _evict_setting(settingid)


def setStr(settingid, value):
    """Set setting as string"""
    settings.setString(settingid, value)
    _evict_setting(settingid)


def setNumber(settingid, value):
    """Set setting as float/number"""
    settings.setNumber(settingid, value)
    _evict_setting(settingid)


def setStringList(settingid, value):
    """Set setting as list of strings"""
    settings.setStringList(settingid, value)
    homeWindow.clearProperty(f'{ADDON_ID}_{settingid}')


def setBoolList(settingid, value):
    """Set setting as list of booleans"""
    settings.setBoolList(settingid, value)
    homeWindow.clearProperty(f'{ADDON_ID}_{settingid}')


def setIntList(settingid, value):
    """Set setting as list of integers"""
    settings.setIntList(settingid, value)
    homeWindow.clearProperty(f'{ADDON_ID}_{settingid}')


def setNumberList(settingid, value):
    """Set setting as list of numbers"""
    settings.setNumberList(settingid, value)
    homeWindow.clearProperty(f'{ADDON_ID}_{settingid}')


def clearSettingsCache():
    """Clear the in-memory settings cache (call after settings change)."""
    _settings_cache.clear()
    _artwork_cache.clear()


# ═══════════════════════════════════════════════════════════════════════════
#  Context Menu - Dynamic Property Caching
# ═══════════════════════════════════════════════════════════════════════════

def process_context():
    """Cache context menu settings into window properties for main, testing, and rpdev addons."""
    context_settings = [
        "context.otaku.findrecommendations",
        "context.otaku.findrelations",
        "context.otaku.getwatchorder",
        "context.otaku.viewreviews",
        "context.otaku.viewstatistics",
        "context.otaku.rescrape",
        "context.otaku.sourceselect",
        "context.otaku.logout",
        "context.otaku.deletefromdatabase",
        "context.otaku.watchlist",
        "context.otaku.markedaswatched",
        "context.otaku.markpreviouswatched",
        "context.otaku.fanartselect",
        "context.otaku.clearcache"
    ]
    for s_id in context_settings:
        try:
            val_str = str(settings.getBool(s_id)).lower()
            for prefix in ('context.otaku', 'context.otaku.testing', 'context.otaku.rpdev'):
                prop_id = s_id.replace('context.otaku', prefix)
                if homeWindow.getProperty(prop_id) != val_str:
                    homeWindow.setProperty(prop_id, val_str)
        except Exception:
            log(f'Failed to cache context setting: {s_id}', 'error')


# ═══════════════════════════════════════════════════════════════════════════
#  Window Properties & URL Helpers
# ═══════════════════════════════════════════════════════════════════════════

def setGlobalProp(property, value):
    homeWindow.setProperty(property, str(value))


def getGlobalProp(property):
    return homeWindow.getProperty(property)


def clearGlobalProp(property):
    homeWindow.clearProperty(property)


def lang(x):
    return language(x)


def addon_url(url):
    return f"plugin://{ADDON_ID}/{url}"


def get_plugin_url(url):
    addon_base = addon_url('')
    return url[len(addon_base):]


def get_plugin_params(param):
    return dict(parse.parse_qsl(param.replace('?', '')))


def get_payload_params(url):
    url_list = url.rsplit('?', 1)
    if len(url_list) == 1:
        url_list.append('')
    payload, params = url_list
    return get_plugin_url(payload), get_plugin_params(params)


def exit_code():
    if getSetting('reuselanguageinvoker.status') == 'Enabled':
        exit_(0)


def keyboard(title, text=''):
    keyboard_ = xbmc.Keyboard(text, title, False)
    keyboard_.doModal()
    if keyboard_.isConfirmed():
        return keyboard_.getText()
    return keyboard_.getText() if keyboard_.isConfirmed() else ""


# ═══════════════════════════════════════════════════════════════════════════
#  GUI - Dialogs & Notifications
# ═══════════════════════════════════════════════════════════════════════════

def wait_loop(step: int, timeout: int, path: str, path2: str = '', *, require_item_count=False):
    """
    :param step: Step wait time in ms
    :param timeout: max timeout time in ms
    :param path: path to match Container.FolderPath
    :param path2: path2 to match Container.FolderPath
    :param require_item_count: if True, also wait until Container.NumItems parses as int > 0
    """
    step = max(1, step)
    max_loop = max(1, int(timeout / step))
    for i in range(max_loop):
        xbmc.sleep(step)
        if xbmcgui.getCurrentWindowId() == 10025:
            kodi_path = xbmc.getInfoLabel('Container.FolderPath')
            paths_ok = path in kodi_path or (path2 and path2 in kodi_path)
            if paths_ok:
                if xbmc.getCondVisibility("Container.IsUpdating"):
                    continue
                if require_item_count:
                    try:
                        n = int(xbmc.getInfoLabel('Container.NumItems'))
                    except ValueError:
                        continue
                    if n <= 0:
                        continue
                break
    else:
        log(f"Waited ({step * max_loop}ms) for path {xbmc.getInfoLabel('Container.FolderPath')}")


def clean_memory():
    """Trigger Python garbage collection, close idle connections, and release heap via malloc_trim."""
    # 1. Clear excessive in-memory artwork cache
    global _artwork_cache
    if len(_artwork_cache) > 200:
        _artwork_cache.clear()

    try:
        from resources.lib.windows import base_window
        base_window.clear_artwork_cache()
    except (ImportError, AttributeError):
        pass

    # 2. Close thread-local SQLite connections for this thread
    try:
        from resources.lib.ui import database
        database.close_thread_connections()
    except (ImportError, AttributeError):
        pass

    # 3. Garbage collection
    try:
        import gc
        gc.collect()
    except Exception as e:
        log(f"gc.collect warning: {e}", 'debug')

    # 4. Release freed heap pages to OS (Android Bionic & Linux glibc)
    try:
        import ctypes
        for lib_name in ('libc.so', 'libc.so.6', None):
            try:
                libc = ctypes.CDLL(lib_name)
                trim_func = getattr(libc, 'malloc_trim', None)
                if trim_func:
                    trim_func(0)
                    break
            except (OSError, AttributeError):
                continue
    except Exception as e:
        log(f"malloc_trim warning: {e}", 'debug')


_RE_KODI_TAG = re.compile(r'\[/?(?:COLOR(?:\s+[^\]]+|=.*?)?|B|I|LIGHT|UPPERCASE|LOWERCASE|CAPITALIZE|CR)\]', re.IGNORECASE)
_RE_CONTROL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def sanitize_dialog_text(text, strip_formatting=False) -> str:
    """Sanitize strings passed to Kodi UI dialogs to prevent formatting spoofing and control char injection."""
    if text is None:
        return ''
    if not isinstance(text, str):
        text = str(text)
    # Strip dangerous non-printable control characters and null bytes
    text = _RE_CONTROL_CHARS.sub('', text)
    if strip_formatting:
        text = _RE_KODI_TAG.sub('', text)
    return text.strip()


def closeAllDialogs():
    execute('Dialog.Close(all,true)')


def ok_dialog(title, text):
    return xbmcgui.Dialog().ok(sanitize_dialog_text(title), sanitize_dialog_text(text))


def textviewer_dialog(title, text):
    xbmcgui.Dialog().textviewer(sanitize_dialog_text(title), sanitize_dialog_text(text))


def yesno_dialog(title, text, nolabel=None, yeslabel=None):
    return xbmcgui.Dialog().yesno(sanitize_dialog_text(title), sanitize_dialog_text(text), nolabel, yeslabel)


def yesnocustom_dialog(title, text, customlabel='', nolabel='', yeslabel='', autoclose=0, defaultbutton=0):
    return xbmcgui.Dialog().yesnocustom(
        sanitize_dialog_text(title),
        sanitize_dialog_text(text),
        sanitize_dialog_text(customlabel),
        sanitize_dialog_text(nolabel),
        sanitize_dialog_text(yeslabel),
        autoclose,
        defaultbutton
    )


def notify(title, text, icon=OTAKU_LOGO3_PATH, time=5000, sound=False):
    xbmcgui.Dialog().notification(sanitize_dialog_text(title), sanitize_dialog_text(text), icon, time, sound)


def input_dialog(title, input_='', option=0):
    return xbmcgui.Dialog().input(sanitize_dialog_text(title), input_, option)


def multiselect_dialog(title, dialog_list, preselect=None):
    clean_list = [sanitize_dialog_text(item) if isinstance(item, str) else item for item in dialog_list]
    return xbmcgui.Dialog().multiselect(sanitize_dialog_text(title), clean_list, preselect=preselect)


def select_dialog(title, dialog_list):
    clean_list = [sanitize_dialog_text(item) if isinstance(item, str) else item for item in dialog_list]
    return xbmcgui.Dialog().select(sanitize_dialog_text(title), clean_list)


def context_menu(context_list):
    return xbmcgui.Dialog().contextmenu(context_list)


def browse(type_, heading, shares, mask=''):
    return xbmcgui.Dialog().browse(type_, heading, shares, mask)


# ═══════════════════════════════════════════════════════════════════════════
#  VideoTags - ListItem Metadata Builder
# ═══════════════════════════════════════════════════════════════════════════

def set_videotags(li, info):
    vinfo: xbmc.InfoTagVideo = li.getVideoInfoTag()
    if title := info.get('title') or info.get('title_userPreferred'):
        vinfo.setTitle(title)
    if media_type := info.get('mediatype') or info.get('format'):
        vinfo.setMediaType(media_type)
    if tvshow_title := info.get('tvshowtitle'):
        vinfo.setTvShowTitle(tvshow_title)
    if plot := info.get('plot'):
        vinfo.setPlot(plot)
    if year := info.get('year'):
        vinfo.setYear(int(year))
    if premiered := info.get('premiered'):
        vinfo.setPremiered(premiered)
    if status := info.get('status'):
        vinfo.setTvShowStatus(status)
    if genre := info.get('genre'):
        vinfo.setGenres(genre)
    if mpaa := info.get('mpaa'):
        vinfo.setMpaa(mpaa)
    if rating := info.get('rating'):
        if isinstance(rating, dict):
            vinfo.setRating(rating.get('score', 0), rating.get('votes', 0))
        else:
            vinfo.setRating(0, 0)
    if season := info.get('season'):
        vinfo.setSeason(int(season))
    if episode := info.get('episode'):
        vinfo.setEpisode(int(episode))
    if aired := info.get('aired'):
        vinfo.setFirstAired(aired)
    if playcount := info.get('playcount'):
        vinfo.setPlaycount(playcount)
    if duration := info.get('duration'):
        vinfo.setDuration(duration)
    if code := info.get('code'):
        vinfo.setProductionCode(code)
    if studio := info.get('studio'):
        if isinstance(studio, list):
            primary_studio = [s.strip() for s in studio if s and isinstance(s, str) and s.strip()][:1]
            if primary_studio:
                vinfo.setStudios(primary_studio)
                li.setProperty('Studios', ' / '.join(str(s) for s in studio if s))
                li.setProperty('Studio', primary_studio[0])
        elif isinstance(studio, str) and studio:
            clean_studios = [s.strip() for s in studio.split(' / ') if s.strip()]
            if clean_studios:
                vinfo.setStudios(clean_studios[:1])
                li.setProperty('Studios', studio)
                li.setProperty('Studio', clean_studios[0])
    if cast := info.get('cast'):
        vinfo.setCast([
            xbmc.Actor(
                str(c.get('name') or ''),
                str(c.get('role') or ''),
                int(c.get('index') or 0),
                str(c.get('thumbnail') or '')
            )
            for c in cast if isinstance(c, dict)
        ])
    if country := info.get('country'):
        vinfo.setCountries(country)
    if originaltitle := info.get('OriginalTitle'):
        vinfo.setOriginalTitle(originaltitle)
    if trailer := info.get('trailer'):
        vinfo.setTrailer(trailer)

    if uniqueids := info.get('UniqueIDs'):
        uniqueids = {key: str(value) for key, value in uniqueids.items()}
        vinfo.setUniqueIDs(uniqueids)
        if 'imdb' in uniqueids:
            vinfo.setIMDBNumber(uniqueids['imdb'])
        for key, value in uniqueids.items():
            if value is not None:
                li.setProperty(key, str(value))

    if resume := info.get('resume'):
        vinfo.setResumePoint(float(resume), 1)


def jsonrpc(json_data):
    return json.loads(xbmc.executeJSONRPC(json.dumps(json_data)))


# ═══════════════════════════════════════════════════════════════════════════
#  Directory Listing - draw_items / bulk_dir_list / xbmc_add_dir
# ═══════════════════════════════════════════════════════════════════════════

def xbmc_add_dir(name, url, art, info, draw_cm, bulk_add, isfolder, isplayable, bulk_prefs=None):
    u = addon_url(url)
    liz = xbmcgui.ListItem(name, offscreen=True)
    if info:
        set_videotags(liz, info)
    if draw_cm:
        cm = [
            (
                x[0],
                x[1]
                if x[1].startswith(('RunPlugin(', 'PlayMedia(', 'Container.', 'ActivateWindow('))
                else f'RunPlugin(plugin://{ADDON_ID}/{x[1]}/{url})'
            )
            for x in draw_cm
        ]
        liz.addContextMenuItems(cm)
    # Check new artwork.fanart setting (inverted logic from old fanart_disable)
    if bulk_prefs is not None:
        artwork_fanart_enabled = bulk_prefs['artwork_fanart_enabled']
        fanart_select_enabled = bulk_prefs['fanart_select_enabled']
        artwork_clearlogo_enabled = bulk_prefs['artwork_clearlogo_enabled']
        artwork_studios_style = bulk_prefs.get('artwork_studios_style', 'coloured')
        fanart_mal_ids = bulk_prefs.get('fanart_mal_ids')
        fanart_selections = bulk_prefs.get('fanart_selections')
    else:
        artwork_fanart_enabled = getBool('artwork.fanart')
        fanart_select_enabled = getBool('context.otaku.fanartselect')
        artwork_clearlogo_enabled = getBool('artwork.clearlogo')
        artwork_studios_style = getSetting('artwork.studios') or 'coloured'
        fanart_mal_ids = None
        fanart_selections = None

    if not art.get('fanart') or not artwork_fanart_enabled:
        art['fanart'] = OTAKU_FANART
    else:
        if isinstance(art['fanart'], list):
            if fanart_select_enabled:
                if info.get('UniqueIDs', {}).get('mal_id'):
                    mal_id = str(info["UniqueIDs"]["mal_id"])

                    # Check cache first
                    cache_key = f"fanart_{mal_id}"
                    if cache_key in _artwork_cache:
                        art['fanart'] = _artwork_cache[cache_key]
                    else:
                        if fanart_mal_ids is not None:
                            mal_ids = fanart_mal_ids
                            fanart_selections_list = fanart_selections or []
                        else:
                            mal_ids = getStringList('fanart.mal_ids')
                            fanart_selections_list = getStringList('fanart.selections')

                        fanart_select = ''
                        try:
                            index = mal_ids.index(mal_id)
                            fanart_select = fanart_selections_list[index] if index < len(fanart_selections_list) else ''
                        except (ValueError, IndexError):
                            pass

                        selected = fanart_select if fanart_select else random.choice(art['fanart'])
                        _artwork_cache[cache_key] = selected
                        art['fanart'] = selected
                else:
                    art['fanart'] = OTAKU_FANART
            else:
                # Use cached random selection if available
                cache_key = f"fanart_{url}"
                if cache_key in _artwork_cache:
                    art['fanart'] = _artwork_cache[cache_key]
                else:
                    selected = random.choice(art['fanart'])
                    _artwork_cache[cache_key] = selected
                    art['fanart'] = selected
        # If fanart is already a string (pre-selected), use it directly

    # Check new artwork.clearlogo setting (inverted logic from old clearlogo_disable)
    if not artwork_clearlogo_enabled or not art.get('clearlogo'):
        art['clearlogo'] = OTAKU_ICONS_PATH
    # If clearlogo is already a string (pre-selected), use it directly
    # No need for random.choice() since get_meta.py pre-selects it

    # Resolve anime studio logo from resource.images.animestudio packages
    if artwork_studios_style and artwork_studios_style != 'none' and info:
        studio_val = info.get('studio')
        primary_studio_name = None
        if isinstance(studio_val, list):
            primary_studio_name = next((s.strip() for s in studio_val if s and isinstance(s, str) and s.strip()), None)
        elif isinstance(studio_val, str) and studio_val:
            parts = [s.strip() for s in studio_val.split(' / ') if s.strip()]
            if parts:
                primary_studio_name = parts[0]

        if primary_studio_name:
            studio_art = f"resource://resource.images.animestudio.{artwork_studios_style}/{primary_studio_name}.png"
            art['studio'] = studio_art
            art['tvshow.studio'] = studio_art
            liz.setProperty('StudioIcon', studio_art)
            liz.setProperty('StudioLogo', studio_art)
            liz.setProperty('Studio.Icon', studio_art)
            liz.setProperty('Studio.Logo', studio_art)
            liz.setProperty('Studio.1.Icon', studio_art)
            liz.setProperty('Studio.1.Logo', studio_art)
            liz.setProperty('Studio.1.Art', studio_art)

    if isplayable:
        if 'poster' in art and art['poster']:
            art['tvshow.poster'] = art.pop('poster')
        liz.setProperties({'Video': 'true', 'IsPlayable': 'true'})
    clean_art = {k: str(v) for k, v in art.items() if v and isinstance(v, str)}
    liz.setArt(clean_art)
    return u, liz, isfolder if bulk_add else xbmcplugin.addDirectoryItem(HANDLE, u, liz, isfolder)


def item_looks_like_next_page_row(item):
    """True when *item* is the standard Next page folder row (next.png artwork)."""
    if not isinstance(item, dict):
        return False
    icon = (item.get('image') or {}).get('icon') or ''
    norm = icon.replace('\\', '/').lower()
    return norm.endswith('/next.png') or norm.endswith('next.png')


def schedule_next_page_prefetch(items, prefetch_callable):
    """Warm ``database.get`` / API cache for the following page after the directory is shown."""
    if not items or not callable(prefetch_callable):
        return
    if not item_looks_like_next_page_row(items[-1]):
        return

    def _run():
        try:
            prefetch_callable()
        except Exception as e:
            log(f'prefetch next page: {e}', level='debug')

    threading.Thread(target=_run, daemon=True).start()


def bulk_draw_items(video_data):
    list_items = bulk_dir_list(video_data, True)
    return xbmcplugin.addDirectoryItems(HANDLE, list_items)


def draw_items(video_data, content_type='', cacheToDisc=True):
    bulk_draw_items(video_data)
    if content_type:
        xbmcplugin.setContent(HANDLE, content_type)
    if content_type == 'episodes':
        xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_NONE, "%H. %T", "%R | %P")
        xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_EPISODE, "%H. %T", "%R | %P")
        xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_VIDEO_RATING, "%R", "%L")
        xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_DATE, "%Y", "%L")
        xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_PLAYCOUNT, "%P", "%L")
    elif content_type in ('tvshows', 'movies', 'videos', 'seasons'):
        xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_NONE, "%L", "%R")
        xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE, "%L", "%R")
        xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_DATE, "%Y", "%R")
        xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_VIDEO_RATING, "%R", "%L")
        xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_EPISODE, "%E", "%L")
        xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_PLAYCOUNT, "%P", "%L")
    else:
        xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_NONE, "%L", "%R")
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=cacheToDisc)
    closeAllDialogs()
    if getBool('interface.viewtype'):
        xbmc.sleep(100)  # Delay so the directory is painted before changing view mode
        if getBool('interface.viewidswitch'):
            if content_type == '' or content_type == 'addons':
                xbmc.executebuiltin('Container.SetViewMode(%d)' % getInt('interface.addon.view.id'))
            elif content_type == 'tvshows':
                xbmc.executebuiltin('Container.SetViewMode(%d)' % getInt('interface.show.view.id'))
            elif content_type == 'episodes':
                xbmc.executebuiltin('Container.SetViewMode(%d)' % getInt('interface.episode.view.id'))
        else:
            if content_type == '' or content_type == 'addons':
                xbmc.executebuiltin('Container.SetViewMode(%d)' % get_view_type(getSetting('interface.addon.view')))
            elif content_type == 'tvshows':
                xbmc.executebuiltin('Container.SetViewMode(%d)' % get_view_type(getSetting('interface.show.view')))
            elif content_type == 'episodes':
                xbmc.executebuiltin('Container.SetViewMode(%d)' % get_view_type(getSetting('interface.episode.view')))

    if content_type == "episodes" and getBool('general.smart.scroll.enable'):
        if getBool('interface.viewtype'):
            xbmc.sleep(150)  # View mode change can repaint the list; let infolabels settle
        wait_loop(50, 4500, f"plugin://{ADDON_ID}/animes", f'plugin://{ADDON_ID}/watchlist_to_ep',
                  require_item_count=True)
        for _ in range(16):
            try:
                window = xbmcgui.getCurrentWindowId()
                if window != 10025:
                    xbmc.sleep(80)
                    continue
                current_window = xbmcgui.Window(window)
                active_id = current_window.getFocusId()
            except Exception:
                xbmc.sleep(80)
                continue
            if not active_id:
                xbmc.sleep(80)
                continue
            try:
                num_watched = int(xbmc.getInfoLabel("Container.TotalWatched"))
                total_ep = int(xbmc.getInfoLabel('Container.NumItems'))
                all_items = int(xbmc.getInfoLabel('Container.NumAllItems'))
            except ValueError:
                xbmc.sleep(80)
                continue
            if all_items <= 0:
                xbmc.sleep(80)
                continue
            offset = 1 if all_items > total_ep else 0
            target_index = num_watched + offset
            if not (0 < target_index < all_items):
                break
            xbmc.executebuiltin('Action(firstpage)')
            xbmc.sleep(50)
            xbmc.executebuiltin(f'Control.SetFocus({active_id}, {target_index})')
            break


def _dir_list_item_worker(item, bulk_add, bulk_prefs):
    return xbmc_add_dir(
        item['name'], item['url'], item['image'], item['info'], item['cm'],
        bulk_add, item['isfolder'], item['isplayable'], bulk_prefs,
    )


def bulk_dir_list(video_data, bulk_add=True):
    artwork_fanart_enabled = getBool('artwork.fanart')
    fanart_select_enabled = getBool('context.otaku.fanartselect')
    bulk_prefs = {
        'artwork_fanart_enabled': artwork_fanart_enabled,
        'fanart_select_enabled': fanart_select_enabled,
        'artwork_clearlogo_enabled': getBool('artwork.clearlogo'),
        'artwork_studios_style': getSetting('artwork.studios') or 'coloured',
    }
    if artwork_fanart_enabled and fanart_select_enabled:
        bulk_prefs['fanart_mal_ids'] = getStringList('fanart.mal_ids')
        bulk_prefs['fanart_selections'] = getStringList('fanart.selections')
    mapfunc = partial(_dir_list_item_worker, bulk_add=bulk_add, bulk_prefs=bulk_prefs)
    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        list_items = list(executor.map(mapfunc, filter(None, video_data)))
    return list_items


# ═══════════════════════════════════════════════════════════════════════════
#  View Types
# ═══════════════════════════════════════════════════════════════════════════

def get_view_type(viewtype):
    viewTypes = {
        'Default': 50,
        'Poster': 51,
        'Icon Wall': 52,
        'Shift': 53,
        'Info Wall': 54,
        'Wide List': 55,
        'Wall': 500,
        'Banner': 501,
        'Fanart': 502,
        'List': 0
    }
    return viewTypes[viewtype]


# ═══════════════════════════════════════════════════════════════════════════
#  Utilities
# ═══════════════════════════════════════════════════════════════════════════

def clear_settings(silent=False):
    from resources.lib.ui.database_sync import SyncDatabase
    if not silent:
        confirm = yesno_dialog(ADDON_NAME, lang(30090))
        if confirm == 0:
            return

    if os.path.exists(dataPath):
        shutil.rmtree(dataPath)

    os.mkdir(dataPath)
    refresh()

    if getSetting('version') != '0.5.43':
        SyncDatabase().re_build_database(True)


def exit_(code):
    sys.exit(code)


def is_addon_visible():
    return xbmc.getInfoLabel('Container.PluginName') == 'plugin.video.otaku.rpdev'


def abort_requested():
    monitor = xbmc.Monitor()
    abort_requested_ = monitor.abortRequested()
    del monitor
    return abort_requested_


def wait_for_abort(timeout=1.0):
    monitor = xbmc.Monitor()
    abort_requested_ = monitor.waitForAbort(timeout)
    del monitor
    return abort_requested_


def arc4(t, n):
    u = 0
    h = ''
    s = list(range(256))
    for e in range(256):
        x = t[e % len(t)]
        u = (u + s[e] + (x if isinstance(x, int) else ord(x))) % 256
        s[e], s[u] = s[u], s[e]

    e = u = 0
    for c in range(len(n)):
        e = (e + 1) % 256
        u = (u + s[e]) % 256
        s[e], s[u] = s[u], s[e]
        h += chr((n[c] if isinstance(n[c], int) else ord(n[c])) ^ s[(s[e] + s[u]) % 256])
    return h


def safe_call(func, *args, default=None, log_msg='', **kwargs):
    """Call func(*args, **kwargs), returning default on any exception.
    Optionally logs the error via control.log() if log_msg is provided."""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        if log_msg:
            log(f'{log_msg}: {e}', 'error')
        return default


def safe_json(response, default=None):
    """Safely parse a response as JSON, returning default on failure."""
    if default is None:
        default = {}
    if not response:
        return default
    try:
        return response.json()
    except (ValueError, AttributeError, TypeError):
        return default


def loads_json(text, default=None):
    """Safely parse a JSON string, returning `default` on error or empty string."""
    if not text:
        return default
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return default


def safe_next(iterable, default=None):
    """Safe wrapper around next() that returns default on StopIteration."""
    try:
        return next(iterable)
    except StopIteration:
        return default


def atomic_write_json(file_path: str, data: any, indent: int = 2) -> bool:
    """Atomically write JSON data to file_path via temporary swap."""
    parent_dir = os.path.dirname(os.path.abspath(file_path))
    if not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)
    tmp_path = f"{file_path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, file_path)
        return True
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError as rm_err:
                log(f"Failed to remove tmp file {tmp_path}: {rm_err}", 'debug')
        log(f"atomic_write_json failed for {file_path}: {e}", 'error')
        return False


def atomic_write_text(file_path: str, content: str, encoding: str = 'utf-8') -> bool:
    """Atomically write text content to file_path via temporary swap."""
    parent_dir = os.path.dirname(os.path.abspath(file_path))
    if not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)
    tmp_path = f"{file_path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp_path, 'w', encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, file_path)
        return True
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError as rm_err:
                log(f"Failed to remove tmp file {tmp_path}: {rm_err}", 'debug')
        log(f"atomic_write_text failed for {file_path}: {e}", 'error')
        return False


def atomic_write_bytes(file_path: str, content: bytes) -> bool:
    """Atomically write binary content to file_path via temporary swap."""
    parent_dir = os.path.dirname(os.path.abspath(file_path))
    if not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)
    tmp_path = f"{file_path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp_path, 'wb') as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, file_path)
        return True
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError as rm_err:
                log(f"Failed to remove tmp file {tmp_path}: {rm_err}", 'debug')
        log(f"atomic_write_bytes failed for {file_path}: {e}", 'error')
        return False


def print(string, *args):
    for i in list(args):
        string = f'{string} {i}'
    textviewer_dialog('print', f'{string}')
    del args, string


def timeIt(func):
    # Thanks to 123Venom
    def wrap(*args, **kwargs):
        import time
        started_at = time.perf_counter()
        result = func(*args, **kwargs)
        log(f">> {__name__}.{func.__name__} <<: {time.perf_counter() - started_at}")
        return result

    return wrap
