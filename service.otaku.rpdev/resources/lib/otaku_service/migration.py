# -*- coding: utf-8 -*-
"""Self-contained pre-prune settings migration from plugin.video.otaku.rpdev to service.otaku.rpdev.

Invariants:
  - ZERO imports from plugin.video.otaku.rpdev (runs safely before parent upgrade finishes).
  - Supports both Kodi v2 (<setting id="k">val</setting>) and legacy v1 (<setting id="k" value="val"/>).
  - Idempotent: guarded by `service.migrated_from_plugin_v1` boolean setting in service.otaku.rpdev.
  - Parses raw XML with ElementTree because Kodi 22 CAddonSettings drops removed IDs from the
    parent add-on's runtime API immediately upon schema update even while the XML tags remain on disk.
"""

import os
import xml.etree.ElementTree as ET

import xbmc
import xbmcaddon
import xbmcvfs

from otaku_service import metrics

SERVICE_ADDON_ID = 'service.otaku.rpdev'
SUBTITLE_ADDON_ID = 'service.subtitles.otaku.rpdev'
PLUGIN_ADDON_ID = 'plugin.video.otaku.rpdev'
MIGRATION_MARKER_ID = 'service.migrated_from_plugin_v1'
SUBTITLE_MIGRATION_MARKER_ID = 'subtitles.migrated_from_plugin_v1'

# Canonical map of all 30 non-action value settings owned by service.otaku.rpdev:
# setting_id -> (kodi_type, canonical_default_str)
SERVICE_SETTING_SPECS = {
    # Category 1: Cache & Database
    'general.kodi.cache': ('boolean', 'true'),
    'cache.scrapers.ttl': ('integer', '8'),
    'cache.torrents.ttl': ('integer', '24'),
    'cache.metadata.ttl': ('integer', '24'),
    'cache.calendar.ttl': ('integer', '24'),
    'db.sqlite.cache_size_mb': ('integer', '16'),
    'db.sqlite.mmap_size_mb': ('integer', '32'),
    'db.sqlite.synchronous': ('string', '1'),
    'db.sqlite.temp_store_ram': ('boolean', 'true'),
    # Category 2: Service, Storage & Maintenance
    'general.memory_watermark_mb': ('integer', '900'),
    'general.standby_throttling': ('boolean', 'true'),
    'download.location': ('path', ''),
    'dub.etag': ('string', ''),
    'mappings.etag': ('string', ''),
    'mappings.last_modified': ('string', ''),
    'update.time.1': ('integer', '0'),
    'update.time.7': ('integer', '0'),
    'update.time.30': ('integer', '0'),
    'clean.memory': ('boolean', 'false'),
    'service.migrated_from_plugin_v1': ('boolean', 'false'),
    # Category 3: Solvers, Network & Debug
    'fs_enable': ('boolean', 'false'),
    'fs_url': ('string', 'http://localhost:8191/v1'),
    'fs_timeout': ('integer', '60'),
    'ms_enable': ('boolean', 'false'),
    'ms_url': ('string', 'http://localhost:4000/'),
    'ipv6.status': ('string', 'Enabled'),
    'http2.status': ('string', 'Enabled'),
    'webpdb.enabled': ('boolean', 'false'),
    'webpdb.port': ('integer', '5566'),
    'webpdb.mode': ('integer', '0'),
}

# Canonical map of all 24 non-action value settings owned by service.subtitles.otaku.rpdev:
# setting_id -> (kodi_type, canonical_default_str)
SUBTITLE_SETTING_SPECS = {
    # Category 1: SubtitleService
    'subtitles.enabled': ('boolean', 'true'),
    'subtitles.auto_search': ('boolean', 'true'),
    'subtitles.auto_download': ('boolean', 'true'),
    'subtitles.prefer_sdh': ('boolean', 'false'),
    'subtitles.prefer_forced': ('boolean', 'false'),
    'subtitles.strip_sdh_tags': ('boolean', 'false'),
    'subtitles.auto_calibrate_chapters': ('boolean', 'false'),
    'subtitles.use_chardet': ('boolean', 'true'),
    'subtitles.timeout': ('integer', '15'),
    'subtitles.results_limit': ('integer', '20'),
    'subtitles.migrated_from_plugin_v1': ('boolean', 'false'),
    # Category 2: SubtitleProviders
    'subtitles.provider.opensubtitles': ('boolean', 'true'),
    'subtitles.opensubtitles.username': ('string', ''),
    'subtitles.opensubtitles.password': ('string', ''),
    'subtitles.provider.subdl': ('boolean', 'true'),
    'subtitles.subdl.apikey': ('string', ''),
    'subtitles.provider.subsource': ('boolean', 'true'),
    'subtitles.subsource.apikey': ('string', ''),
    'subtitles.provider.podnadpisi': ('boolean', 'true'),
    'subtitles.provider.bsplayer': ('boolean', 'true'),
    'subtitles.provider.addic7ed': ('boolean', 'true'),
    'subtitles.provider.jimaku': ('boolean', 'true'),
    'subtitles.jimaku.apikey': ('string', ''),
    'subtitles.provider.animetosho': ('boolean', 'true'),
}


def _log(msg, level=xbmc.LOGINFO):
    try:
        xbmc.log(f'OTAKU RPDEV SERVICE (0): {msg}', level)
    except Exception:
        pass


def _extract_raw_value(elem):
    """Extract raw string value supporting both Kodi v2 text and legacy v1 value attribute."""
    if elem.text is not None and elem.text != '':
        return elem.text
    if 'value' in elem.attrib:
        return elem.attrib.get('value', '')
    return ''


def _write_typed(svc_settings, setting_id, setting_type, raw_val):
    """Coerce raw_val to setting_type and write safely via Kodi Settings API."""
    text = str(raw_val if raw_val is not None else '').strip()
    if setting_type == 'boolean':
        svc_settings.setBool(setting_id, text.lower() == 'true')
        return True
    if setting_type == 'integer':
        try:
            int_val = int(float(text))
        except (ValueError, TypeError):
            return False
        svc_settings.setInt(setting_id, int_val)
        return True
    if setting_type == 'number':
        try:
            num_val = float(text)
        except (ValueError, TypeError):
            return False
        svc_settings.setNumber(setting_id, num_val)
        return True
    # string / path / folder / file / addon
    svc_settings.setString(setting_id, str(raw_val if raw_val is not None else ''))
    return True


def migrate_service_settings(plugin_settings_xml=None, service_addon=None):
    """Copy non-default moved settings from plugin.video.otaku.rpdev/settings.xml into service.otaku.rpdev.

    Returns the number of migrated settings (0 if already migrated, fresh install, or on error).
    """
    try:
        addon = service_addon if service_addon is not None else xbmcaddon.Addon(SERVICE_ADDON_ID)
        svc_settings = addon.getSettings()
    except Exception as e:
        _log(f'migration: Unable to open {SERVICE_ADDON_ID} settings: {e}', xbmc.LOGWARNING)
        return 0

    try:
        if svc_settings.getBool(MIGRATION_MARKER_ID):
            return 0
    except Exception:
        pass

    if not plugin_settings_xml:
        try:
            profile_dir = xbmcvfs.translatePath(f'special://profile/addon_data/{PLUGIN_ADDON_ID}/')
            plugin_settings_xml = os.path.join(profile_dir, 'settings.xml')
        except Exception as e:
            _log(f'migration: Failed to resolve plugin profile path: {e}', xbmc.LOGWARNING)
            return 0

    if not plugin_settings_xml or not os.path.exists(plugin_settings_xml):
        try:
            svc_settings.setBool(MIGRATION_MARKER_ID, True)
        except Exception:
            pass
        _log('migration: Fresh install (no plugin settings.xml); marked migrated')
        return 0

    try:
        tree = ET.parse(plugin_settings_xml)
        root = tree.getroot()
    except Exception as e:
        _log(f'migration: Failed to parse {plugin_settings_xml}: {e}', xbmc.LOGWARNING)
        return 0

    migrated = 0
    for elem in root.iter('setting'):
        sid = (elem.get('id') or '').strip()
        if not sid or sid == MIGRATION_MARKER_ID or sid not in SERVICE_SETTING_SPECS:
            continue
        if str(elem.get('default') or '').strip().lower() == 'true':
            continue
        raw_val = _extract_raw_value(elem)
        stype, default_val = SERVICE_SETTING_SPECS[sid]
        if raw_val == '' and default_val == '':
            continue
        if stype == 'boolean' and raw_val.strip() == '':
            continue
        if stype in ('integer', 'number') and raw_val.strip() == '':
            continue
        try:
            if _write_typed(svc_settings, sid, stype, raw_val):
                migrated += 1
        except Exception as e:
            _log(f'migration: Failed migrating {sid}: {e}', xbmc.LOGWARNING)

    try:
        svc_settings.setBool(MIGRATION_MARKER_ID, True)
    except Exception as e:
        _log(f'migration: Failed setting {MIGRATION_MARKER_ID}: {e}', xbmc.LOGWARNING)

    _log(metrics.format_metric_line('service_settings_migrated', count=migrated))
    return migrated


def _subtitle_addon_supports_settings_split(subtitle_addon_path=None, subtitle_addon=None):
    """Verify on disk that service.subtitles.otaku.rpdev (v1.1.0+) declares subtitles.migrated_from_plugin_v1.

    Prevents Kodi 22 Invalid setting type errors during an in-progress upgrade when v1.0.3 is still on disk.
    """
    sub_path = subtitle_addon_path
    if not sub_path and subtitle_addon is not None:
        try:
            raw_path = subtitle_addon.getAddonInfo('path')
            if raw_path:
                sub_path = xbmcvfs.translatePath(raw_path)
        except Exception:
            sub_path = None
    if not sub_path:
        try:
            raw_path = xbmcaddon.Addon(SUBTITLE_ADDON_ID).getAddonInfo('path')
            if raw_path:
                sub_path = xbmcvfs.translatePath(raw_path)
        except Exception:
            sub_path = None
    if not sub_path:
        try:
            sub_path = xbmcvfs.translatePath(f'special://home/addons/{SUBTITLE_ADDON_ID}/')
        except Exception:
            sub_path = None

    if not sub_path:
        return False
    settings_xml = os.path.join(sub_path, 'resources', 'settings.xml')
    if not os.path.isfile(settings_xml):
        return False
    try:
        root = ET.parse(settings_xml).getroot()
        return any((e.get('id') or '').strip() == SUBTITLE_MIGRATION_MARKER_ID for e in root.iter('setting'))
    except Exception:
        return False


def migrate_subtitle_settings(plugin_settings_xml=None, subtitle_addon=None, subtitle_addon_path=None):
    """Copy non-default moved subtitle settings from plugin.video.otaku.rpdev/settings.xml into service.subtitles.otaku.rpdev.

    Guardrail 1: Checks on disk that service.subtitles.otaku.rpdev/resources/settings.xml declares
    `subtitles.migrated_from_plugin_v1` (v1.1.0+) BEFORE touching its CAddonSettings API. If v1.0.3
    is still on disk or the add-on is absent, returns 0 without setting the marker so clean_settings.py
    continues protecting SUBTITLE_SETTING_IDS until migration succeeds.
    """
    try:
        addon = subtitle_addon if subtitle_addon is not None else xbmcaddon.Addon(SUBTITLE_ADDON_ID)
    except Exception as e:
        _log(f'migration: Unable to open {SUBTITLE_ADDON_ID}: {e}', xbmc.LOGWARNING)
        return 0

    if not _subtitle_addon_supports_settings_split(subtitle_addon_path=subtitle_addon_path, subtitle_addon=addon):
        _log(
            f'migration: {SUBTITLE_ADDON_ID} v1.1.0+ schema not ready on disk; deferring subtitle settings migration',
            xbmc.LOGWARNING,
        )
        return 0

    try:
        sub_settings = addon.getSettings()
    except Exception as e:
        _log(f'migration: Unable to open {SUBTITLE_ADDON_ID} settings: {e}', xbmc.LOGWARNING)
        return 0

    try:
        if sub_settings.getBool(SUBTITLE_MIGRATION_MARKER_ID):
            return 0
    except Exception:
        pass

    if not plugin_settings_xml:
        try:
            profile_dir = xbmcvfs.translatePath(f'special://profile/addon_data/{PLUGIN_ADDON_ID}/')
            plugin_settings_xml = os.path.join(profile_dir, 'settings.xml')
        except Exception as e:
            _log(f'migration: Failed to resolve plugin profile path for subtitle migration: {e}', xbmc.LOGWARNING)
            return 0

    if not plugin_settings_xml or not os.path.exists(plugin_settings_xml):
        try:
            sub_settings.setBool(SUBTITLE_MIGRATION_MARKER_ID, True)
        except Exception:
            pass
        _log('migration: Fresh install (no plugin settings.xml); marked subtitle settings migrated')
        return 0

    try:
        tree = ET.parse(plugin_settings_xml)
        root = tree.getroot()
    except Exception as e:
        _log(f'migration: Failed to parse {plugin_settings_xml} for subtitle migration: {e}', xbmc.LOGWARNING)
        return 0

    migrated = 0
    for elem in root.iter('setting'):
        sid = (elem.get('id') or '').strip()
        if not sid or sid == SUBTITLE_MIGRATION_MARKER_ID or sid not in SUBTITLE_SETTING_SPECS:
            continue
        if str(elem.get('default') or '').strip().lower() == 'true':
            continue
        raw_val = _extract_raw_value(elem)
        stype, default_val = SUBTITLE_SETTING_SPECS[sid]
        if raw_val == '' and default_val == '':
            continue
        if stype == 'boolean' and raw_val.strip() == '':
            continue
        if stype in ('integer', 'number') and raw_val.strip() == '':
            continue
        try:
            if _write_typed(sub_settings, sid, stype, raw_val):
                migrated += 1
        except Exception as e:
            _log(f'migration: Failed migrating subtitle setting {sid}: {e}', xbmc.LOGWARNING)

    try:
        sub_settings.setBool(SUBTITLE_MIGRATION_MARKER_ID, True)
    except Exception as e:
        _log(f'migration: Failed setting {SUBTITLE_MIGRATION_MARKER_ID}: {e}', xbmc.LOGWARNING)

    _log(metrics.format_metric_line('subtitle_settings_migrated', count=migrated))
    return migrated
