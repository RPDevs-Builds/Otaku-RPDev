# -*- coding: utf-8 -*-
"""Settings Manager for Otaku.

Provides core settings management facilities:
1. Canonical schema inspection and default value extraction from resources/settings.xml.
2. Robust login/credential identification across Debrid, Watchlists, and Subtitle services.
3. Scoped settings export and import (All Settings, Logins Only, Settings Only) with JSON and legacy XML support.
4. Per-category settings reset to addon defaults.
5. Non-destructive global settings reset to defaults preserving all login credentials.
6. Full factory wipe (Wipe Addon Data) resetting all settings, logins, and databases.
"""

import json
import os
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime

from resources.lib.ui import control


# ═══════════════════════════════════════════════════════════════════════════
#  Credential & Login Setting IDs Registry (53 Keys)
# ═══════════════════════════════════════════════════════════════════════════

LOGIN_SETTING_IDS = {
    # Subtitles
    'subtitles.opensubtitles.username',
    'subtitles.opensubtitles.password',
    'subtitles.subdl.apikey',
    'subtitles.subsource.apikey',

    # Debrid - Real-Debrid
    'realdebrid.username',
    'realdebrid.auth.status',
    'realdebrid.token',
    'realdebrid.secret',
    'realdebrid.client_id',
    'realdebrid.refresh',

    # Debrid - Premiumize
    'premiumize.username',
    'premiumize.auth.status',
    'premiumize.token',

    # Debrid - AllDebrid
    'alldebrid.username',
    'alldebrid.auth.status',
    'alldebrid.token',

    # Debrid - Debrid-Link
    'debridlink.username',
    'debridlink.auth.status',
    'debridlink.token',
    'debridlink.refresh',

    # Debrid - TorBox
    'torbox.username',
    'torbox.auth.status',
    'torbox.token',

    # Debrid - EasyDebrid
    'easydebrid.username',
    'easydebrid.auth.status',
    'easydebrid.token',

    # Debrid - Easynews
    'easynews.user',
    'easynews.password',
    'easynews.auth.status',

    # Watchlists - AniList
    'anilist.username',
    'anilist.password',
    'anilist.authvar',
    'anilist.token',
    'anilist.refresh',
    'anilist.userid',

    # Watchlists - Kitsu
    'kitsu.username',
    'kitsu.password',
    'kitsu.authvar',
    'kitsu.token',
    'kitsu.refresh',
    'kitsu.userid',

    # Watchlists - MyAnimeList (MAL)
    'mal.username',
    'mal.password',
    'mal.authvar',
    'mal.token',
    'mal.refresh',
    'mal.userid',

    # Watchlists - Simkl
    'simkl.username',
    'simkl.password',
    'simkl.authvar',
    'simkl.token',
    'simkl.refresh',
    'simkl.userid',
}

_LOGIN_PREFIXES = (
    'realdebrid.',
    'premiumize.',
    'alldebrid.',
    'debridlink.',
    'torbox.',
    'easydebrid.',
    'easynews.',
    'anilist.',
    'kitsu.',
    'mal.',
    'simkl.',
    'subtitles.opensubtitles.',
    'subtitles.subdl.',
    'subtitles.subsource.',
)

_LOGIN_KEYWORDS = (
    'username',
    'user',
    'password',
    'pass',
    'token',
    'secret',
    'client_id',
    'refresh',
    'authvar',
    'userid',
    'apikey',
    'auth.status',
)

SETTINGS_XML_PATH = os.path.join(control.ADDON_PATH, 'resources', 'settings.xml')


def is_login_setting(setting_id: str) -> bool:
    """Return True if setting_id represents an authentication credential, token, or secret."""
    if not setting_id:
        return False
    sid = setting_id.strip()
    if sid in LOGIN_SETTING_IDS:
        return True
    low = sid.lower()
    if any(low.startswith(p) for p in _LOGIN_PREFIXES):
        if any(kw in low for kw in _LOGIN_KEYWORDS):
            return True
    return False


def get_canonical_settings() -> dict:
    """Parse resources/settings.xml and return schema metadata for all stored settings.

    Returns:
        dict: mapping of setting_id -> dict with keys:
            'id': str
            'type': str ('boolean', 'integer', 'number', 'string', 'path', 'list[string]', etc.)
            'default': str, bool, int, or float
            'category': str (category id from XML)
            'label': str (string ID or raw label)
    """
    settings_map = {}
    if not os.path.exists(SETTINGS_XML_PATH):
        control.log(f"get_canonical_settings: settings.xml not found at {SETTINGS_XML_PATH}", 'error')
        return settings_map

    try:
        tree = ET.parse(SETTINGS_XML_PATH)
        root = tree.getroot()
    except Exception as e:
        control.log(f"get_canonical_settings: XML parse error: {e}", 'error')
        return settings_map

    for cat in root.findall('.//category'):
        cat_id = cat.get('id', '')
        for s in cat.findall('.//setting'):
            stype = s.get('type', 'string')
            if stype == 'action':
                continue
            sid = s.get('id')
            if not sid:
                continue

            def_elem = s.find('default')
            raw_default = def_elem.text if def_elem is not None else s.get('default', '')
            if raw_default is None:
                raw_default = ''

            # Coerce default to typed Python object
            if stype == 'boolean':
                typed_default = str(raw_default).strip().lower() == 'true'
            elif stype == 'integer':
                try:
                    typed_default = int(raw_default)
                except (ValueError, TypeError):
                    typed_default = 0
            elif stype == 'number':
                try:
                    typed_default = float(raw_default)
                except (ValueError, TypeError):
                    typed_default = 0.0
            else:
                typed_default = str(raw_default)

            settings_map[sid] = {
                'id': sid,
                'type': stype,
                'default': typed_default,
                'raw_default': str(raw_default),
                'category': cat_id,
                'label': s.get('label', ''),
            }

    return settings_map


def get_active_settings(scope: str = 'all') -> dict:
    """Read live settings from Kodi C++ runtime filtered by scope.

    Args:
        scope (str): 'all', 'logins', or 'settings'.

    Returns:
        dict: mapping of setting_id -> current live value.
    """
    scope = (scope or 'all').lower()
    canonical = get_canonical_settings()
    active = {}

    for sid, meta in canonical.items():
        is_login = is_login_setting(sid)
        if scope == 'logins' and not is_login:
            continue
        if scope == 'settings' and is_login:
            continue

        stype = meta['type']
        try:
            if stype == 'boolean':
                val = control.getBool(sid, default=meta['default'])
            elif stype == 'integer':
                val = control.getInt(sid, default=meta['default'])
            elif stype == 'number':
                val = control.getNumber(sid, default=meta['default'])
            elif 'list' in stype.lower():
                val = control.getStringList(sid)
            else:
                val = control.getSetting(sid)
        except Exception:
            val = control.getSetting(sid)

        active[sid] = val

    return active


def set_typed_setting(sid: str, value, stype: str = None):
    """Set setting into Kodi C++ runtime and property cache using appropriate type."""
    if not sid:
        return

    if stype is None:
        canonical = get_canonical_settings()
        meta = canonical.get(sid)
        stype = meta['type'] if meta else 'string'

    try:
        if stype == 'boolean':
            b_val = value if isinstance(value, bool) else str(value).strip().lower() in ('true', '1', 'yes')
            control.setBool(sid, b_val)
        elif stype == 'integer':
            try:
                i_val = int(value)
            except (ValueError, TypeError):
                i_val = 0
            control.setInt(sid, i_val)
        elif stype == 'number':
            try:
                n_val = float(value)
            except (ValueError, TypeError):
                n_val = 0.0
            control.setNumber(sid, n_val)
        else:
            s_val = str(value if value is not None else '')
            control.setString(sid, s_val)
    except Exception as e:
        control.log(f"set_typed_setting: failed to set '{sid}' to '{value}': {e}", 'warning')


def export_settings(scope: str, dest_dir: str) -> tuple[bool, str, int]:
    """Serialize filtered settings to a timestamped JSON backup file.

    Args:
        scope (str): 'all', 'logins', or 'settings'.
        dest_dir (str): Directory where backup file should be written.

    Returns:
        tuple[bool, str, int]: (success, backup_filepath, settings_count).
    """
    scope = (scope or 'all').lower()
    if scope not in ('all', 'logins', 'settings'):
        scope = 'all'

    if not dest_dir or not os.path.isdir(dest_dir):
        control.log(f"export_settings: Invalid destination directory: {dest_dir}", 'error')
        return False, "", 0

    active_data = get_active_settings(scope=scope)
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"otaku_backup_{scope}_{timestamp_str}.json"
    dest_path = os.path.join(dest_dir, filename)

    payload = {
        'otaku_backup_version': 1,
        'scope': scope,
        'timestamp': datetime.now().isoformat(),
        'addon_version': control.ADDON_VERSION,
        'settings_count': len(active_data),
        'settings': active_data,
    }

    try:
        with open(dest_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=4, ensure_ascii=False)
        control.log(f"export_settings: Exported {len(active_data)} settings to {dest_path}", 'info')
        return True, dest_path, len(active_data)
    except Exception as e:
        control.log(f"export_settings: Failed writing backup to {dest_path}: {e}", 'error')
        return False, "", 0


def import_settings(scope: str, filepath: str) -> tuple[bool, int]:
    """Parse backup file (JSON or legacy Kodi settings.xml) and apply settings to live runtime.

    Args:
        scope (str): 'all', 'logins', or 'settings'.
        filepath (str): Full path to backup file (.json or .xml).

    Returns:
        tuple[bool, int]: (success, imported_count).
    """
    scope = (scope or 'all').lower()
    if scope not in ('all', 'logins', 'settings'):
        scope = 'all'

    if not filepath or not os.path.isfile(filepath):
        control.log(f"import_settings: File does not exist: {filepath}", 'error')
        return False, 0

    canonical = get_canonical_settings()
    imported_map = {}

    try:
        if filepath.endswith('.json'):
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                # If wrapped in backup schema
                imported_map = data.get('settings', data)
        elif filepath.endswith('.xml'):
            tree = ET.parse(filepath)
            root = tree.getroot()
            for s in root.findall('.//setting'):
                sid = s.get('id')
                if sid:
                    imported_map[sid] = s.text or ''
        else:
            control.log(f"import_settings: Unsupported file format for: {filepath}", 'error')
            return False, 0
    except Exception as e:
        control.log(f"import_settings: Error parsing {filepath}: {e}", 'error')
        return False, 0

    applied_count = 0
    for sid, val in imported_map.items():
        is_login = is_login_setting(sid)
        if scope == 'logins' and not is_login:
            continue
        if scope == 'settings' and is_login:
            continue

        meta = canonical.get(sid)
        stype = meta['type'] if meta else 'string'
        set_typed_setting(sid, val, stype)
        applied_count += 1

    control.clearSettingsCache()
    control.log(f"import_settings: Successfully applied {applied_count} settings from {filepath}", 'info')
    return True, applied_count


def reset_category_settings(category_id: str) -> int:
    """Reset all settings in a specific category to canonical defaults from settings.xml.

    Args:
        category_id (str): Target category name or ID (case-insensitive).

    Returns:
        int: Number of settings reset.
    """
    if not category_id:
        return 0

    norm_target = category_id.strip().lower().replace('_', ' ')
    canonical = get_canonical_settings()
    reset_count = 0

    for sid, meta in canonical.items():
        cat = meta['category'].strip().lower().replace('_', ' ')
        if cat == norm_target or meta['category'].strip().lower() == category_id.strip().lower():
            set_typed_setting(sid, meta['default'], meta['type'])
            reset_count += 1

    control.clearSettingsCache()
    control.log(f"reset_category_settings: Reset {reset_count} settings in category '{category_id}' to defaults", 'info')
    return reset_count


def reset_settings_to_defaults(preserve_logins: bool = True) -> int:
    """Reset all settings across all categories to canonical defaults.

    Args:
        preserve_logins (bool): If True, skips all 53 login/credential/token settings.

    Returns:
        int: Number of settings reset.
    """
    canonical = get_canonical_settings()
    reset_count = 0

    for sid, meta in canonical.items():
        if preserve_logins and is_login_setting(sid):
            continue

        set_typed_setting(sid, meta['default'], meta['type'])
        reset_count += 1

    control.clearSettingsCache()
    control.log(
        f"reset_settings_to_defaults: Reset {reset_count} settings to defaults (preserve_logins={preserve_logins})",
        'info'
    )
    return reset_count


def wipe_addon_data(silent: bool = False) -> bool:
    """True factory reset: resets all settings + logins, deletes and recreates empty DBs, resets setup wizard.

    Args:
        silent (bool): If True, skips interactive confirmation prompt.

    Returns:
        bool: True if wipe completed successfully.
    """
    if not silent:
        confirm = control.yesno_dialog(
            control.ADDON_NAME,
            control.lang(30090) or (
                "[COLOR red]WARNING[/COLOR]\n"
                "This will completely clear your addon settings, databases, and caches.\n"
                "Are you sure you want to do this?"
            )
        )
        if not confirm:
            return False

    control.log("wipe_addon_data: Commencing full factory reset...", 'info')

    # 1. Close all active database handles
    try:
        from resources.lib.ui import database
        database.close_all_connections()
        database._tables_ready.clear()
    except Exception as e:
        control.log(f"wipe_addon_data: Warning closing db connections: {e}", 'warning')

    # 2. Reset all settings (including logins) to canonical defaults
    canonical = get_canonical_settings()
    for sid, meta in canonical.items():
        set_typed_setting(sid, meta['default'], meta['type'])

    # 3. Explicitly blank out all login settings
    for sid in LOGIN_SETTING_IDS:
        set_typed_setting(sid, '', 'string')

    # 5. Delete SQLite databases and user JSON caches in dataPath
    if os.path.exists(control.dataPath):
        for item in os.listdir(control.dataPath):
            item_path = os.path.join(control.dataPath, item)
            try:
                if os.path.isfile(item_path):
                    # Delete DBs, WAL files, JSON files, XML files
                    if item.endswith(('.db', '.db-wal', '.db-shm', '.json', '.xml', '.txt')):
                        os.remove(item_path)
                elif os.path.isdir(item_path):
                    # Delete subdirectories (e.g. temporary caches)
                    shutil.rmtree(item_path)
            except Exception as e:
                control.log(f"wipe_addon_data: Warning removing {item_path}: {e}", 'warning')

    # 6. Rebuild clean empty SQLite database schemas
    try:
        from resources.lib.ui.database_sync import SyncDatabase
        db_sync = SyncDatabase.__new__(SyncDatabase)
        db_sync.activites = None
        db_sync.last_meta_update = SyncDatabase.SCHEMA_VERSION
        db_sync._create_all_tables()
        db_sync.set_base_activites()
    except Exception as e:
        control.log(f"wipe_addon_data: Error rebuilding clean database schema: {e}", 'warning')

    # 7. Explicitly enforce factory install state
    control.setBool('first_time', True)
    control.setString('version', '')
    control.setString('changelog.version', '')
    control.setString('addon.last_watched', '')

    # 8. Evict and flush in-memory caches
    control.clearSettingsCache()
    control.refresh()

    if not silent:
        control.ok_dialog(
            control.ADDON_NAME,
            "Addon data wiped successfully.\nOtaku has been reset to factory defaults as if it was just installed."
        )

    control.log("wipe_addon_data: Full factory reset complete.", 'info')
    return True
