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
    # Identify and remove dangling settings
    for setting in list(root):
        sid = setting.get('id')
        if sid and sid not in active_ids:
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
