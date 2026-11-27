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
#  Credential & Login Setting IDs Registry (Sensitive Credentials + Account Settings)
# ═══════════════════════════════════════════════════════════════════════════

CREDENTIAL_SETTING_IDS = {
    # Subtitles
    'subtitles.opensubtitles.username',
    'subtitles.opensubtitles.password',
    'subtitles.subdl.apikey',
    'subtitles.subsource.apikey',
    'subtitles.jimaku.apikey',

    # Debrid - Real-Debrid
    'realdebrid.username',
    'realdebrid.auth.status',
    'realdebrid.token',
    'realdebrid.secret',
    'realdebrid.client_id',
    'realdebrid.refresh',
    'realdebrid.expiry',

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
    'debridlink.expiry',

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
    'kitsu.expiry',

    # Watchlists - MyAnimeList (MAL)
    'mal.username',
    'mal.password',
    'mal.authvar',
    'mal.token',
    'mal.refresh',
    'mal.userid',
    'mal.expiry',

    # Watchlists - Simkl
    'simkl.username',
    'simkl.password',
    'simkl.authvar',
    'simkl.token',
    'simkl.refresh',
    'simkl.userid',

    # Integration APIs - Anime-Skip
    'animeskip.apikey',
}

ACCOUNT_RELATED_SETTING_IDS = {
    # Debrid - Enablement & Preferences
    'realdebrid.enabled',
    'realdebrid.autodelete',
    'realdebrid.cloudInspection',
    'premiumize.enabled',
    'premiumize.addToCloud',
    'premiumize.autodelete',
    'premiumize.threshold',
    'premiumize.cloudInspection',
    'alldebrid.enabled',
    'alldebrid.autodelete',
    'alldebrid.cloudInspection',
    'debridlink.enabled',
    'debridlink.autodelete',
    'torbox.enabled',
    'torbox.autodelete',
    'torbox.cloudInspection',
    'easydebrid.enabled',
    'easynews.enabled',
    'easynews.moderation',
    'provider.easynews',

    # Watchlists - Enablement, Sync & Preferences
    'watchlist.update.enabled',
    'watchlist.sync.enabled',
    'watchlist.prefetch.enabled',
    'watchlist.update.percent',
    'nextup.flavor',
    'trakt.enabled',
    'anilist.enabled',
    'anilist.sort',
    'anilist.order',
    'anilist.titles',
    'kitsu.enabled',
    'kitsu.sort',
    'kitsu.order',
    'kitsu.titles',
    'mal.enabled',
    'mal.sort',
    'mal.order',
    'mal.titles',
    'simkl.enabled',
    'simkl.sort',
    'simkl.order',
    'simkl.titles',

    # Subtitles - Provider Toggles
    'subtitles.provider.opensubtitles',
    'subtitles.provider.subdl',
    'subtitles.provider.subsource',
    'subtitles.provider.podnadpisi',
    'subtitles.provider.bsplayer',
    'subtitles.provider.addic7ed',

    # Anime-Skip - Enablement & Skip Toggles
    'animeskip.enable',
    'skipintro.animeskip.enable',
    'skipoutro.animeskip.enable',
}

# Unified set of all login and account-related settings for scoped export/import
LOGIN_SETTING_IDS = CREDENTIAL_SETTING_IDS | ACCOUNT_RELATED_SETTING_IDS

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
    'subtitles.provider.',
    'animeskip.',
    'skipintro.animeskip.',
    'skipoutro.animeskip.',
    'watchlist.',
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
    'expiry',
    'enabled',
    'enable',
    'cloudinspection',
    'autodelete',
    'threshold',
    'moderation',
    'sort',
    'order',
    'titles',
)

_CREDENTIAL_KEYWORDS = (
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
    'expiry',
)

SETTINGS_XML_PATH = os.path.join(control.ADDON_PATH, 'resources', 'settings.xml')
SERVICE_SETTINGS_XML_PATH = os.path.join(
    getattr(control, 'SERVICE_ADDON_PATH', ''),
    'resources',
    'settings.xml',
) if getattr(control, 'SERVICE_ADDON_PATH', '') else ''


def is_login_setting(setting_id: str) -> bool:
    """Return True if setting_id represents an account credential, token, secret, or account configuration."""
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


def is_credential_setting(setting_id: str) -> bool:
    """Return True if setting_id represents a sensitive authentication secret, token, or password."""
    if not setting_id:
        return False
    sid = setting_id.strip()
    if sid in CREDENTIAL_SETTING_IDS:
        return True
    low = sid.lower()
    if any(low.startswith(p) for p in _LOGIN_PREFIXES):
        if any(kw in low for kw in _CREDENTIAL_KEYWORDS):
            return True
    return False


def _parse_settings_xml_into_map(xml_path: str, addon_id: str, settings_map: dict):
    if not xml_path or not os.path.exists(xml_path):
        return
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except Exception as e:
        control.log(f"get_canonical_settings: XML parse error ({xml_path}): {e}", 'error')
        return

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
                'addon_id': addon_id,
            }


def get_canonical_settings() -> dict:
    """Parse plugin + service resources/settings.xml and return schema metadata for all stored settings."""
    settings_map = {}
    if not os.path.exists(SETTINGS_XML_PATH):
        control.log(f"get_canonical_settings: settings.xml not found at {SETTINGS_XML_PATH}", 'error')
        return settings_map

    _parse_settings_xml_into_map(SETTINGS_XML_PATH, control.ADDON_ID, settings_map)
    svc_xml = SERVICE_SETTINGS_XML_PATH
    if not svc_xml or not os.path.exists(svc_xml):
        svc_path = getattr(control, 'SERVICE_ADDON_PATH', '')
        if svc_path:
            svc_xml = os.path.join(svc_path, 'resources', 'settings.xml')
    if svc_xml and os.path.exists(svc_xml):
        _parse_settings_xml_into_map(svc_xml, getattr(control, 'SERVICE_ADDON_ID', 'service.otaku.rpdev'), settings_map)

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
        elif stype and 'list' in stype.lower():
            if isinstance(value, (list, tuple)):
                list_val = [str(x).strip() for x in value if str(x).strip()]
            else:
                raw_s = str(value if value is not None else '').strip()
                if raw_s.startswith('[') and raw_s.endswith(']'):
                    try:
                        parsed = control.loads_json(raw_s, default=None)
                        if parsed is None:
                            raise ValueError('invalid list json')
                        list_val = [str(x).strip() for x in parsed if str(x).strip()] if isinstance(parsed, list) else []
                    except Exception:
                        list_val = [x.strip() for x in raw_s.split(',') if x.strip()]
                else:
                    list_val = [x.strip() for x in raw_s.split(',') if x.strip()]
            control.setStringList(sid, list_val)
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

    try:
        svc_ver = control.SERVICE_ADDON.getAddonInfo('version')
    except Exception:
        svc_ver = '1.0.0'

    payload = {
        'otaku_backup_version': 2,
        'scope': scope,
        'timestamp': datetime.now().isoformat(),
        'addon_version': control.ADDON_VERSION,
        'addon_versions': {
            control.ADDON_ID: control.ADDON_VERSION,
            getattr(control, 'SERVICE_ADDON_ID', 'service.otaku.rpdev'): svc_ver,
        },
        'settings_count': len(active_data),
        'settings': active_data,
    }
    if scope in ('all', 'settings'):
        try:
            from resources.lib.ui import database
            payload['series_overrides'] = database.list_series_overrides()
        except Exception as e:
            control.log(f"export_settings: Could not include series_overrides: {e}", 'warning')

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
    imported_overrides = []

    try:
        if filepath.endswith('.json'):
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                # If wrapped in backup schema
                imported_map = data.get('settings', data)
                if isinstance(data.get('series_overrides'), list):
                    imported_overrides = data.get('series_overrides')
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

    # Reconcile and auto-heal account state if importing logins or all settings
    if scope in ('all', 'logins'):
        reconcile_authenticated_accounts(imported_map)

    if scope in ('all', 'settings') and imported_overrides:
        try:
            from resources.lib.ui import database
            for ov in imported_overrides:
                if isinstance(ov, dict) and ov.get('mal_id'):
                    database.set_series_override(
                        ov['mal_id'],
                        audio_lang=ov.get('audio_lang'),
                        sub_lang=ov.get('sub_lang'),
                        sub_mode=ov.get('sub_mode'),
                        preferred_provider=ov.get('preferred_provider'),
                        intro_offset_s=ov.get('intro_offset_s', 0),
                        outro_offset_s=ov.get('outro_offset_s', 0),
                        skip_filler_mode=ov.get('skip_filler_mode', 'default'),
                        episode_offset=ov.get('episode_offset', 0),
                        sub_offset_ms=ov.get('sub_offset_ms', 0),
                        preferred_group=ov.get('preferred_group', ''),
                        excluded_groups=ov.get('excluded_groups', ''),
                    )
        except Exception as e:
            control.log(f"import_settings: Could not restore series_overrides: {e}", 'warning')

    control.clearSettingsCache()
    control.log(f"import_settings: Successfully applied {applied_count} settings from {filepath}", 'info')
    return True, applied_count


def heal_simkl_account(token: str = None) -> bool:
    """Fetch Simkl user profile to heal missing username or userid."""
    if not token:
        token = control.getSetting('simkl.token')
    if not token or token == 'None':
        return False
    try:
        from resources.lib.WatchlistFlavor.Simkl import SimklWLF
        inst = SimklWLF(auth_var='', username='', password='', user_id='', token=token, refresh='', sort=0, order=0)
        profile = inst.get_user_profile()
        if profile:
            if profile.get('username'):
                control.setSetting('simkl.username', profile['username'])
            if profile.get('userid'):
                control.setSetting('simkl.userid', profile['userid'])
            control.log(f"heal_simkl_account: Healed Simkl profile: username={profile.get('username')}, userid={profile.get('userid')}", 'info')
            return True
    except Exception as e:
        control.log(f"heal_simkl_account: Error healing Simkl profile: {e}", 'warning')
    return False


def heal_anilist_account(token: str = None) -> bool:
    """Fetch AniList Viewer to heal missing username or userid."""
    if not token:
        token = control.getSetting('anilist.token')
    if not token or token == 'None':
        return False
    try:
        from resources.lib.ui import client
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        query = 'query { Viewer { id name } }'
        r = client.post('https://graphql.anilist.co', json_data={'query': query}, headers=headers, timeout=10)
        if r and r.ok:
            viewer = r.json(default={}).get('data', {}).get('Viewer', {})
            uname = viewer.get('name')
            uid = viewer.get('id')
            if uname:
                control.setSetting('anilist.username', str(uname))
            if uid:
                control.setSetting('anilist.userid', str(uid))
            control.log(f"heal_anilist_account: Healed AniList profile: username={uname}, userid={uid}", 'info')
            return True
    except Exception as e:
        control.log(f"heal_anilist_account: Error healing AniList profile: {e}", 'warning')
    return False


def heal_mal_account(token: str = None) -> bool:
    """Fetch MAL user profile to heal missing username or userid."""
    if not token:
        token = control.getSetting('mal.token')
    if not token or token == 'None':
        return False
    try:
        from resources.lib.ui import client
        headers = {'Authorization': f'Bearer {token}'}
        r = client.get('https://api.myanimelist.net/v2/users/@me', headers=headers, params={'fields': 'name'}, timeout=10)
        if r and r.ok:
            data = r.json(default={})
            uname = data.get('name')
            uid = data.get('id')
            if uname:
                control.setSetting('mal.username', str(uname))
            if uid:
                control.setSetting('mal.userid', str(uid))
            control.log(f"heal_mal_account: Healed MAL profile: username={uname}, userid={uid}", 'info')
            return True
    except Exception as e:
        control.log(f"heal_mal_account: Error healing MAL profile: {e}", 'warning')
    return False


def reconcile_authenticated_accounts(imported_map: dict = None) -> dict:
    """Reconcile and auto-heal account state after backup import or restore.

    1. Debrid Services: Auto-enables realdebrid, premiumize, alldebrid, debridlink,
       torbox, easydebrid, easynews if active credentials exist and the service was not
       explicitly saved as disabled in imported_map.
    2. Watchlist Flavors: Auto-enables anilist, kitsu, mal, simkl if tokens exist,
       and ensures global watchlist.update.enabled and watchlist.sync.enabled are active.
    3. Profile Healing: Auto-fetches missing usernames/userids for Simkl, AniList, MAL.
    4. Anime-Skip & Subtitles: Auto-enables services when active credentials exist.

    Args:
        imported_map (dict): The dictionary of imported settings.

    Returns:
        dict: Summary of reconciled actions and healed accounts.
    """
    imported_map = imported_map or {}
    reconciled = {'enabled_debrid': [], 'enabled_watchlists': [], 'healed_profiles': []}

    def is_explicitly_disabled(sid):
        if sid in imported_map:
            v = imported_map[sid]
            return v is False or str(v).strip().lower() in ('false', '0')
        return False

    # 1. Reconcile Debrid Services
    debrid_token_keys = {
        'realdebrid': 'realdebrid.token',
        'premiumize': 'premiumize.token',
        'alldebrid': 'alldebrid.token',
        'debridlink': 'debridlink.token',
        'torbox': 'torbox.token',
        'easydebrid': 'easydebrid.token',
    }
    for service, token_key in debrid_token_keys.items():
        enabled_key = f"{service}.enabled"
        tok = control.getSetting(token_key)
        if tok and tok != 'None' and not is_explicitly_disabled(enabled_key):
            if not control.getBool(enabled_key):
                control.setBool(enabled_key, True)
                reconciled['enabled_debrid'].append(service)
                control.log(f"reconcile_authenticated_accounts: Auto-enabled {service} debrid", 'info')

    # Easynews
    en_user = control.getSetting('easynews.user')
    en_pass = control.getSetting('easynews.password')
    if (en_user and en_user != 'None') or (en_pass and en_pass != 'None'):
        if not is_explicitly_disabled('easynews.enabled') and not control.getBool('easynews.enabled'):
            control.setBool('easynews.enabled', True)
            reconciled['enabled_debrid'].append('easynews')
            control.log("reconcile_authenticated_accounts: Auto-enabled easynews", 'info')

    # 2. Reconcile Watchlists & Heal Missing Metadata
    watchlist_flavors = ('simkl', 'anilist', 'kitsu', 'mal')
    any_wl_active = False

    for flavor in watchlist_flavors:
        tok = control.getSetting(f"{flavor}.token")
        has_creds = bool(tok and tok != 'None')
        if not has_creds and flavor in ('kitsu', 'mal'):
            pw = control.getSetting(f"{flavor}.password")
            user = control.getSetting(f"{flavor}.username")
            if pw and pw != 'None' and user and user != 'None':
                has_creds = True

        enabled_key = f"{flavor}.enabled"
        if has_creds:
            any_wl_active = True
            if not is_explicitly_disabled(enabled_key) and not control.getBool(enabled_key):
                control.setBool(enabled_key, True)
                reconciled['enabled_watchlists'].append(flavor)
                control.log(f"reconcile_authenticated_accounts: Auto-enabled {flavor} watchlist", 'info')

            # Heal missing usernames / userids
            uname = control.getSetting(f"{flavor}.username")
            if not uname or uname == 'None':
                if flavor == 'simkl' and heal_simkl_account(tok):
                    reconciled['healed_profiles'].append('simkl')
                elif flavor == 'anilist' and heal_anilist_account(tok):
                    reconciled['healed_profiles'].append('anilist')
                elif flavor == 'mal' and heal_mal_account(tok):
                    reconciled['healed_profiles'].append('mal')

    if any_wl_active:
        if not is_explicitly_disabled('watchlist.update.enabled') and not control.getBool('watchlist.update.enabled'):
            control.setBool('watchlist.update.enabled', True)
        if not is_explicitly_disabled('watchlist.sync.enabled') and not control.getBool('watchlist.sync.enabled'):
            control.setBool('watchlist.sync.enabled', True)

    # 3. Anime-Skip
    askip_key = control.getSetting('animeskip.apikey')
    if askip_key and askip_key != 'None' and not is_explicitly_disabled('animeskip.enable'):
        if not control.getBool('animeskip.enable'):
            control.setBool('animeskip.enable', True)

    # 4. Subtitle Providers
    if control.getSetting('subtitles.opensubtitles.username') and control.getSetting('subtitles.opensubtitles.password'):
        if not is_explicitly_disabled('subtitles.provider.opensubtitles'):
            control.setBool('subtitles.provider.opensubtitles', True)
            control.setBool('subtitles.enabled', True)
    if control.getSetting('subtitles.subdl.apikey') and not is_explicitly_disabled('subtitles.provider.subdl'):
        control.setBool('subtitles.provider.subdl', True)
        control.setBool('subtitles.enabled', True)
    if control.getSetting('subtitles.subsource.apikey') and not is_explicitly_disabled('subtitles.provider.subsource'):
        control.setBool('subtitles.provider.subsource', True)
        control.setBool('subtitles.enabled', True)

    return reconciled


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
        if sid == 'service.migrated_from_plugin_v1':
            continue
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

    # 3. Explicitly blank out all credential secrets and tokens
    for sid in CREDENTIAL_SETTING_IDS:
        set_typed_setting(sid, '', 'string')

    # 5. Delete SQLite databases and user JSON caches in plugin + service profiles
    profile_dirs = [control.dataPath]
    try:
        svc_id = getattr(control, 'SERVICE_ADDON_ID', 'service.otaku.rpdev')
        svc_profile_dir = control.xbmcvfs.translatePath(f'special://profile/addon_data/{svc_id}/')
        if svc_profile_dir and os.path.normpath(svc_profile_dir) != os.path.normpath(control.dataPath):
            profile_dirs.append(svc_profile_dir)
    except Exception:
        pass

    for pdir in profile_dirs:
        if os.path.exists(pdir):
            for item in os.listdir(pdir):
                item_path = os.path.join(pdir, item)
                try:
                    if os.path.isfile(item_path):
                        if item.endswith(('.db', '.db-wal', '.db-shm', '.json', '.xml', '.txt')):
                            os.remove(item_path)
                    elif os.path.isdir(item_path):
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
    control.setBool('service.migrated_from_plugin_v1', False)

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
