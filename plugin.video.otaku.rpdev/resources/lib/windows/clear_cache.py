# -*- coding: utf-8 -*-
"""Clear Cache Dialog for Otaku.

Provides a multi-option modal dialog allowing users to choose between:
1. Provider Cache (torrents, embeds, season packs, debrid availability hashes, circuit breaker)
2. All Cache & Database (complete reset of caches, external API metadata, and malSync.db)
3. Cancel (exit without making changes)

Each option includes live descriptive explanations when highlighted.
"""

import xbmcgui
from resources.lib.ui import control


class ClearCacheDialog(xbmcgui.WindowXMLDialog):
    """Modal dialog presenting cache clearing options with dynamic descriptions."""

    def __init__(self, xml_file, location):
        super().__init__(xml_file, location)
        self.selected = 'cancel'
        self.list_control = None
        self._win_closed = False

        self._items_meta = [
            {
                'action': 'providers',
                'label': 'Provider Cache (Torrents & Embeds)',
                'subtitle': 'Torrents, embed sources, season packs & debrid hashes',
                'title': 'Provider Cache (Torrents & Embeds)',
                'description': (
                    'Clears cached torrent scrapes, embed links, season packs, last played sources, '
                    'and cached debrid availability hashes. Resets scraper circuit breakers.\n\n'
                    'Recommended: Use this to guarantee a fresh source scan without losing your '
                    'watchlist sync or anime metadata.'
                )
            },
            {
                'action': 'all',
                'label': 'All Cache & Database',
                'subtitle': 'Total reset of all caches, API responses & local DB',
                'title': 'All Cache & Database',
                'description': (
                    'Completely purges all addon caches, external API metadata (AniList, MAL, Kitsu, Simkl), '
                    'and local SQLite anime databases (malSync.db).\n\n'
                    'Use this if you encounter database errors or want a full reset. '
                    'Your watchlist will re-sync from your configured tracking service.'
                )
            }
        ]

    def onInit(self):
        """Initialize list items and focus default option (Provider Cache)."""
        control.closeBusyDialog()

        try:
            self.list_control = self.getControl(1000)
        except Exception as e:
            control.log(f"ClearCacheDialog: Failed to get list control 1000: {e}", 'error')
            self.list_control = None

        if self.list_control is not None:
            self.list_control.reset()
            for meta in self._items_meta:
                item = xbmcgui.ListItem(label=meta['label'])
                item.setProperty('subtitle', meta['subtitle'])
                item.setProperty('title', meta['title'])
                item.setProperty('description', meta['description'])
                item.setProperty('action', meta['action'])
                self.list_control.addItem(item)

            # Default to item 0: Provider Cache
            self.list_control.selectItem(0)

        # Set default focus to list
        self.setFocusId(1000)
        self._update_description(0)

    def _update_description(self, index=None):
        """Update window properties for active description panel."""
        focus_id = None
        try:
            focus_id = self.getFocusId()
        except Exception:
            pass

        if focus_id == 3001:
            self.setProperty('cache.option_title', 'Cancel Operation')
            self.setProperty(
                'cache.option_description',
                'Exits this maintenance dialog without clearing any caches, scraper records, '
                'or databases. Your existing setup and cached data will remain untouched.'
            )
            return

        if index is None and self.list_control is not None:
            try:
                index = self.list_control.getSelectedPosition()
            except Exception:
                index = 0

        if index is None or index < 0 or index >= len(self._items_meta):
            index = 0

        meta = self._items_meta[index]
        self.setProperty('cache.option_title', meta['title'])
        self.setProperty('cache.option_description', meta['description'])

    def onClick(self, control_id):
        """Handle button and list click events."""
        if control_id == 3001:
            # Cancel Button
            self.selected = 'cancel'
            self.close()
        elif control_id == 1000:
            # List selection
            self._handle_selection()

    def onAction(self, action):
        """Handle keyboard/remote controller actions."""
        action_id = action.getId()

        # Back / Escape / Previous menu
        if action_id in [9, 10, 92]:
            self.selected = 'cancel'
            self.close()
            return

        # Select / Enter / Space
        if action_id in [7, 100]:
            try:
                focus_id = self.getFocusId()
            except Exception:
                focus_id = 1000

            if focus_id == 3001:
                self.selected = 'cancel'
                self.close()
            else:
                self._handle_selection()
            return

        # Up, Down, Left, Right navigation: refresh description
        if action_id in [1, 2, 3, 4]:
            self._update_description()

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
                self.selected = 'providers'
        else:
            self.selected = 'providers'

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


def show_clear_cache_dialog():
    """Display clear cache options dialog with fallback to select_dialog.

    Returns:
        str: 'providers', 'all', or 'cancel'
    """
    try:
        dialog = ClearCacheDialog("clear_cache.xml", control.ADDON_PATH)
        result = dialog.doModal()
        del dialog
        if result in ['providers', 'all', 'cancel']:
            return result
    except Exception as e:
        control.log(f"show_clear_cache_dialog skin dialog error: {e}, falling back to select_dialog", 'warning')

    # Fallback to standard Kodi select dialog if custom XML is unavailable
    options = [
        "Provider Cache (Torrents & Embeds)",
        "All Cache & Database",
        "Cancel"
    ]
    choice = control.select_dialog("Otaku - Clear Cache", options)
    if choice == 0:
        return 'providers'
    elif choice == 1:
        return 'all'
    return 'cancel'
