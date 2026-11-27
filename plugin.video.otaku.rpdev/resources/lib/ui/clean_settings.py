# -*- coding: utf-8 -*-
"""
clean_settings.py - Orphaned Settings Pruner
============================================
Inspects user profile settings.xml against the canonical resources/settings.xml
definition and removes obsolete / dangling setting tags left behind by older
add-on versions. Prevents Kodi 22 C++ settings serialization warnings.
"""

import os
import xml.etree.ElementTree as ET
from resources.lib.ui import control


def get_active_setting_ids(settings_xml_path=None):
    """
    Extract all defined setting IDs from canonical resources/settings.xml.
    :param settings_xml_path: Optional custom path for testing
    :return: Set of valid setting ID strings
    """
    if not settings_xml_path:
        settings_xml_path = os.path.join(control.ADDON_PATH, 'resources', 'settings.xml')

    active_ids = set()
    if not os.path.exists(settings_xml_path):
        control.log(f"clean_settings: Canonical settings file not found: {settings_xml_path}", 'warning')
        return active_ids

    try:
        tree = ET.parse(settings_xml_path)
        root = tree.getroot()
        for setting in root.iter('setting'):
            sid = setting.get('id')
            if sid:
                active_ids.add(sid)
    except Exception as e:
        control.log(f"clean_settings: Failed to parse canonical settings.xml: {e}", 'error')

    return active_ids


def clean_settings(profile_settings_path=None, canonical_settings_path=None, silent=False):
    """
    Scan userdata settings.xml and strip settings that are no longer defined in resources/settings.xml.
    :param profile_settings_path: Path to user's profile settings.xml (defaults to addon profile)
    :param canonical_settings_path: Path to addon resources/settings.xml
    :param silent: Optional flag to suppress interactive notifications
    :return: (pruned_count: int, removed_ids: list[str])
    """
    if not profile_settings_path:
        profile_settings_path = os.path.join(control.dataPath, 'settings.xml')

    if not os.path.exists(profile_settings_path):
        control.log("clean_settings: No profile settings.xml found to clean", 'info')
        return 0, []

    active_ids = get_active_setting_ids(canonical_settings_path)
    if not active_ids:
        control.log("clean_settings: Active settings list is empty, aborting prune to prevent data loss", 'warning')
        return 0, []

    try:
        tree = ET.parse(profile_settings_path)
        root = tree.getroot()
    except Exception as e:
        control.log(f"clean_settings: Failed to parse profile settings.xml: {e}", 'error')
        return 0, []

    removed_ids = []
    # Protect unmigrated SERVICE_SETTING_IDS from being pruned out of plugin settings.xml
    is_plugin_profile = (
        not canonical_settings_path
        or os.path.normpath(canonical_settings_path) == os.path.normpath(os.path.join(control.ADDON_PATH, 'resources', 'settings.xml'))
    )
    service_migrated = True
    if is_plugin_profile:
        try:
            service_migrated = bool(control.getBool('service.migrated_from_plugin_v1', False))
        except Exception:
            service_migrated = False
    protected_service_ids = set() if service_migrated else set(getattr(control, 'SERVICE_SETTING_IDS', ()))

    # Identify and remove dangling settings
    for setting in list(root):
        sid = setting.get('id')
        if sid and sid not in active_ids and sid not in protected_service_ids:
            removed_ids.append(sid)
            root.remove(setting)

    if removed_ids:
        try:
            # Atomically write updated settings XML
            temp_path = profile_settings_path + '.tmp'
            tree.write(temp_path, encoding='utf-8', xml_declaration=True)
            if os.path.exists(temp_path):
                os.replace(temp_path, profile_settings_path)
            control.log(f"clean_settings: Successfully pruned {len(removed_ids)} orphaned setting(s): {', '.join(removed_ids)}", 'info')
        except Exception as e:
            control.log(f"clean_settings: Failed to write sanitized settings.xml: {e}", 'error')
            return 0, []
    else:
        control.log("clean_settings: Settings file clean — no orphaned settings found", 'info')

    return len(removed_ids), removed_ids


def clean_all_settings(silent=False):
    """Prune orphaned settings across both plugin.video.otaku.rpdev and service.otaku.rpdev."""
    total_count = 0
    all_removed = []

    p_count, p_removed = clean_settings(silent=silent)
    total_count += p_count
    all_removed.extend(p_removed)

    svc_id = getattr(control, 'SERVICE_ADDON_ID', 'service.otaku.rpdev')
    svc_addon_path = getattr(control, 'SERVICE_ADDON_PATH', '')
    svc_canonical = os.path.join(svc_addon_path, 'resources', 'settings.xml') if svc_addon_path else ''
    if svc_canonical and os.path.exists(svc_canonical):
        try:
            svc_profile_dir = control.xbmcvfs.translatePath(f'special://profile/addon_data/{svc_id}/')
            svc_profile = os.path.join(svc_profile_dir, 'settings.xml')
            if os.path.exists(svc_profile):
                s_count, s_removed = clean_settings(
                    profile_settings_path=svc_profile,
                    canonical_settings_path=svc_canonical,
                    silent=silent,
                )
                total_count += s_count
                all_removed.extend(s_removed)
        except Exception as e:
            control.log(f"clean_all_settings: service.otaku.rpdev prune notice: {e}", 'warning')

    return total_count, all_removed
