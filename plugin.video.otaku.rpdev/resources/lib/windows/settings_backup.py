# -*- coding: utf-8 -*-
"""Settings Backup & Restore Dialog for Otaku.

Provides a multi-option modal popup dialog allowing users to choose between:
1. All Settings (complete backup/restore including logins & preferences)
2. Logins Only (sensitive account credentials, Debrid tokens & Watchlist logins)
3. Settings Only (general configuration preferences without sensitive logins)
4. Cancel (exit without making changes)

Matches the layout and visual presentation of the Clear Cache window with live dynamic descriptions.
"""

import xbmcgui
from resources.lib.ui import control


class SettingsBackupDialog(xbmcgui.WindowXMLDialog):
    """Modal dialog presenting settings backup and restore options with dynamic descriptions."""

    def __init__(self, xml_file, location, mode='export'):
        super().__init__(xml_file, location)
        self.mode = mode.lower() if mode in ('export', 'import') else 'export'
        self.selected = 'cancel'
        self.list_control = None
        self._win_closed = False

        if self.mode == 'export':
            self.header = "Otaku - Export Settings Backup"
            self.subtitle = "Select an export scope below. Review the description before proceeding."
            self._items_meta = [
                {
                    'action': 'all',
                    'label': 'Export All Settings',
                    'subtitle': 'Full configuration backup including logins & preferences',
                    'title': 'Export All Settings (Complete Backup)',
                    'description': (
                        'Exports every configuration setting, scraper option, player preference, '
                        'along with your authenticated account credentials (Debrid tokens, Watchlist logins, '
                        'Subtitle API keys).\n\n'
                        'Recommended: Use this when migrating your complete Otaku setup to another device '
                        'or saving a complete disaster recovery backup.'
                    )
                },
                {
                    'action': 'logins',
                    'label': 'Export Accounts & Logins',
                    'subtitle': 'Account settings, Debrid tokens & Watchlist authorizations',
                    'title': 'Export Accounts & Logins (Credentials & Account Settings)',
                    'description': (
                        'Exports your authenticated accounts, credentials, and service settings:\n'
                        '• Real-Debrid, Premiumize, AllDebrid, Debrid-Link, TorBox, EasyDebrid, Easynews\n'
                        '• AniList, MyAnimeList, Kitsu, Simkl (including watchlist sync options)\n'
                        '• OpenSubtitles, SubDL, SubSource & Anime-Skip\n\n'
                        'Account toggles, cloud inspection, auto-delete, and sort rules are included.\n'
                        'General player, scraping, and skin layout settings are excluded.'
                    )
                },
                {
                    'action': 'settings',
                    'label': 'Export Settings Only',
                    'subtitle': 'Preferences & configurations without sensitive logins',
                    'title': 'Export Settings Only (Safe Non-Credential Backup)',
                    'description': (
                        'Exports all non-sensitive configuration settings, provider toggles, scraper timeouts, '
                        'sorting rules, and interface preferences.\n\n'
                        'All login passwords, API keys, and Debrid/Watchlist tokens are strictly excluded. '
                        'Safe for sharing configurations across devices or with other users.'
                    )
                }
            ]
        else:
            self.header = "Otaku - Import Settings Backup"
            self.subtitle = "Select an import scope below. Review the description before proceeding."
            self._items_meta = [
                {
                    'action': 'all',
                    'label': 'Import All Settings',
                    'subtitle': 'Restore full configuration including logins & preferences',
                    'title': 'Import All Settings (Complete Restore)',
                    'description': (
                        'Imports and applies all settings found in the backup file, restoring both general '
                        'add-on preferences and authenticated account credentials.\n\n'
                        'Existing configuration and logins will be replaced with values from the backup file.'
                    )
                },
                {
                    'action': 'logins',
                    'label': 'Import Accounts & Logins',
                    'subtitle': 'Restore account settings, Debrid tokens & Watchlist logins',
                    'title': 'Import Accounts & Logins (Credentials & Account Settings)',
                    'description': (
                        'Restores account credentials, Debrid tokens, Watchlist authorizations, and '
                        'Subtitle/Anime-Skip API keys along with their enabled toggles and sync settings.\n\n'
                        'Automatically reconciles and activates authorized accounts.\n'
                        'General player, scraper, and playback rules will remain untouched.'
                    )
                },
                {
                    'action': 'settings',
                    'label': 'Import Settings Only',
                    'subtitle': 'Restore preferences & configurations without touching logins',
                    'title': 'Import Settings Only (Safe Non-Credential Restore)',
                    'description': (
                        'Restores scraper settings, sorting options, and interface preferences from the backup file.\n\n'
                        'All currently logged-in accounts, Debrid authorizations, and Watchlist tokens are strictly '
                        'preserved and will not be overwritten.'
                    )
                }
            ]

    def onInit(self):
        """Initialize list items and configure window header properties."""
        control.closeBusyDialog()

        self.setProperty('backup.header', self.header)
        self.setProperty('backup.subtitle', self.subtitle)

        try:
            self.list_control = self.getControl(1000)
        except Exception as e:
            control.log(f"SettingsBackupDialog: Failed to get list control 1000: {e}", 'error')
            self.list_control = None

        if self.list_control is not None:
            self.list_control.reset()
            for meta in self._items_meta:
                item = xbmcgui.ListItem(label=str(meta.get('label') or ''))
                item.setProperty('subtitle', str(meta.get('subtitle') or ''))
                item.setProperty('title', str(meta.get('title') or ''))
                item.setProperty('description', str(meta.get('description') or ''))
                item.setProperty('action', str(meta.get('action') or ''))
                self.list_control.addItem(item)

            self.list_control.selectItem(0)

        self.setFocusId(1000)

    def onClick(self, control_id):
        """Handle button and list click events."""
        if control_id == 3001:
            self.selected = 'cancel'
            self.close()
        elif control_id == 1000:
            self._handle_selection()

    def onAction(self, action):
        """Handle keyboard/remote controller actions."""
        action_id = action.getId()
        if action_id in [9, 10, 92]:
            self.selected = 'cancel'
            self.close()

    def _handle_selection(self):
        """Extract user selection from active list position."""
        if self.list_control is not None:
            try:
                pos = self.list_control.getSelectedPosition()
            except Exception:
                pos = 0

            if 0 <= pos < len(self._items_meta):
                self.selected = self._items_meta[pos]['action']
            else:
                self.selected = 'all'
        else:
            self.selected = 'all'

        self.close()

    def doModal(self):
        """Display modal dialog and return chosen action string."""
        super().doModal()
        return self.selected

    def close(self):
        """Close dialog safely."""
        if getattr(self, '_win_closed', False):
            return
        self._win_closed = True
        super().close()


def show_settings_backup_dialog(mode='export'):
    """Display settings backup/restore options dialog with fallback to select_dialog.

    Args:
        mode (str): 'export' or 'import'.

    Returns:
        str: 'all', 'logins', 'settings', or 'cancel'.
    """
    mode = mode.lower() if mode in ('export', 'import') else 'export'
    try:
        dlg = SettingsBackupDialog("settings_backup.xml", control.ADDON_PATH, mode=mode)
        try:
            result = dlg.doModal()
            if result in ['all', 'logins', 'settings', 'cancel']:
                return result
        finally:
            del dlg
    except Exception as e:
        control.log(f"show_settings_backup_dialog skin dialog error: {e}, falling back to select_dialog", 'warning')

    action_label = "Export" if mode == 'export' else "Import"
    options = [
        f"{action_label} All Settings",
        f"{action_label} Accounts & Logins",
        f"{action_label} Settings Only",
        "Cancel"
    ]
    choice = control.select_dialog(f"Otaku - {action_label} Settings Backup", options)
    if choice == 0:
        return 'all'
    elif choice == 1:
        return 'logins'
    elif choice == 2:
        return 'settings'
    return 'cancel'
