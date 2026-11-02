# -*- coding: utf-8 -*-
"""
    Otaku Add-on - Menu Order & Visibility Customization Dialog
    Allows reordering and toggling visibility of Home screen main menu items.
"""

import xbmcgui
from resources.lib.ui import control, utils

# All 24 Home screen items with default order, string label ID, default enabled state, and icon
DEFAULT_MENU_ITEMS = [
    ('watchlist', 30162, True, 'watchlist.png'),
    ('last_watched', 30000, True, 'last_watched.png'),
    ('watch_history', 30068, True, 'watch_history.png'),
    ('next_up', 30451, True, 'next_up.png'),
    ('my_cloud', 30555, True, 'tools.png'),
    ('airing_calendar', 30001, True, 'airing_anime_calendar.png'),
    ('airing_last_season', 30002, True, 'airing_anime.png'),
    ('airing_this_season', 30003, True, 'airing_anime.png'),
    ('airing_next_season', 30004, True, 'airing_anime.png'),
    ('movies', 30005, False, 'movies.png'),
    ('tv_shows', 30006, False, 'tv_shows.png'),
    ('tv_shorts', 30007, False, 'tv_shorts.png'),
    ('specials', 30008, False, 'specials.png'),
    ('ovas', 30009, False, 'ovas.png'),
    ('onas', 30010, False, 'onas.png'),
    ('music', 30011, False, 'music.png'),
    ('trending', 30012, True, 'trending.png'),
    ('popular', 30013, True, 'popular.png'),
    ('voted', 30014, True, 'voted.png'),
    ('favourites', 30015, True, 'favourites.png'),
    ('top_100', 30016, True, 'top_100_anime.png'),
    ('genres', 30017, True, 'genres_&_tags.png'),
    ('search', 30018, True, 'search.png'),
    ('tools', 30019, True, 'tools.png'),
]

DEFAULT_ORDER = [x[0] for x in DEFAULT_MENU_ITEMS]
DEFAULT_ENABLED = [x[0] for x in DEFAULT_MENU_ITEMS if x[2]]
MENU_ITEM_METADATA = {x[0]: (x[1], x[3]) for x in DEFAULT_MENU_ITEMS}


def get_item_label(item_id):
    """Resolve user-visible label for a menu item ID (clean, unnumbered)."""
    meta = MENU_ITEM_METADATA.get(item_id)
    if meta:
        lbl = control.lang(meta[0])
        if lbl:
            return lbl
    return item_id.replace('_', ' ').title()


def load_menu_order():
    """
    Loads the current order and enabled set for the main menu.
    Returns:
        tuple: (ordered_ids, enabled_set)
    """
    order_setting = control.getSetting('menu.mainmenu.order')
    if order_setting:
        raw_order = [x.strip() for x in order_setting.split(',') if x.strip()]
        ordered_ids = [x for x in raw_order if x in MENU_ITEM_METADATA]
        for item in DEFAULT_ORDER:
            if item not in ordered_ids:
                ordered_ids.append(item)
    else:
        ordered_ids = list(DEFAULT_ORDER)

    config_list = control.getStringList('menu.mainmenu.config')
    if config_list:
        enabled_set = set(config_list)
        # Backward compatibility: If order was never customized and watchlist wasn't in config_list, enable it
        if not order_setting and 'watchlist' not in enabled_set:
            enabled_set.add('watchlist')
    else:
        enabled_set = set(DEFAULT_ENABLED)

    return ordered_ids, enabled_set


def save_menu_order(ordered_ids, enabled_set):
    """
    Persists the complete order and ordered enabled subset, then signals refresh.
    """
    control.setSetting('menu.mainmenu.order', ','.join(ordered_ids))
    enabled_ordered = [x for x in ordered_ids if x in enabled_set]
    control.setStringList('menu.mainmenu.config', enabled_ordered)
    control.setGlobalProp('otaku.menu.needs_refresh', 'true')
    control.clearSettingsCache()
    control.refresh()


def move_item(items, from_idx, to_idx):
    """
    Moves an item in items list from from_idx to to_idx safely with bounds checking.
    Returns new index.
    """
    if not items:
        return 0
    from_idx = max(0, min(len(items) - 1, from_idx))
    to_idx = max(0, min(len(items) - 1, to_idx))
    if from_idx != to_idx:
        item = items.pop(from_idx)
        items.insert(to_idx, item)
    return to_idx


class MenuOrderDialog(xbmcgui.WindowXMLDialog):
    """
    Interactive full GUI Window for arranging Home screen item order and toggling visibility.
    Displays items cleanly without numbers and provides prominent action buttons:
    Move Up, Move Down, Move to Top, Move to Bottom, Toggle Visibility, Reset, Save, Cancel.
    """

    def __init__(self, xml_file, location):
        super().__init__(xml_file, location)
        self.ordered_ids, self.enabled_set = load_menu_order()
        self.list_control = None
        self.modified = False
        self._win_closed = False

    def onInit(self):
        control.closeBusyDialog()
        try:
            self.list_control = self.getControl(1000)
        except Exception as e:
            control.log(f"MenuOrderDialog: Failed to get list control 1000: {e}", 'error')
            self.list_control = None

        self._populate_list(selected_idx=0)
        self.setFocusId(1000)

    def _get_current_index(self):
        if self.list_control is not None:
            try:
                pos = self.list_control.getSelectedPosition()
                if 0 <= pos < len(self.ordered_ids):
                    return pos
            except Exception:
                pass
        return 0

    def _populate_list(self, selected_idx=0):
        if self.list_control is None:
            return

        self.list_control.reset()
        for item_id in self.ordered_ids:
            title = get_item_label(item_id)
            is_enabled = item_id in self.enabled_set

            item = xbmcgui.ListItem(label=title)
            meta = MENU_ITEM_METADATA.get(item_id)
            icon_file = meta[1] if meta else 'tools.png'
            icon_path = utils._get_artwork_path(icon_file)
            item.setArt({'icon': icon_path, 'thumb': icon_path})

            status_badge = '[COLOR deepskyblue][✓][/COLOR]' if is_enabled else '[COLOR grey][  ][/COLOR]'
            status_text = control.lang(30690) if is_enabled else control.lang(30691)

            item.setProperty('status_badge', status_badge)
            item.setProperty('status_text', status_text)
            item.setProperty('item_id', item_id)
            self.list_control.addItem(item)

        if len(self.ordered_ids) > 0:
            target_idx = max(0, min(len(self.ordered_ids) - 1, selected_idx))
            self.list_control.selectItem(target_idx)

    def move_up(self):
        idx = self._get_current_index()
        if idx > 0:
            new_idx = move_item(self.ordered_ids, idx, idx - 1)
            self.modified = True
            self._populate_list(selected_idx=new_idx)
            return new_idx
        return idx

    def move_down(self):
        idx = self._get_current_index()
        if idx < len(self.ordered_ids) - 1:
            new_idx = move_item(self.ordered_ids, idx, idx + 1)
            self.modified = True
            self._populate_list(selected_idx=new_idx)
            return new_idx
        return idx

    def move_top(self):
        idx = self._get_current_index()
        if idx > 0:
            new_idx = move_item(self.ordered_ids, idx, 0)
            self.modified = True
            self._populate_list(selected_idx=0)
            return 0
        return idx

    def move_bottom(self):
        idx = self._get_current_index()
        last_idx = len(self.ordered_ids) - 1
        if idx < last_idx:
            new_idx = move_item(self.ordered_ids, idx, last_idx)
            self.modified = True
            self._populate_list(selected_idx=last_idx)
            return last_idx
        return idx

    def toggle_visibility(self):
        idx = self._get_current_index()
        item_id = self.ordered_ids[idx]
        if item_id in self.enabled_set:
            self.enabled_set.discard(item_id)
        else:
            self.enabled_set.add(item_id)
        self.modified = True
        self._populate_list(selected_idx=idx)

    def reset_defaults(self):
        if control.yesno_dialog(control.lang(30682), control.lang(30686)):
            self.ordered_ids = list(DEFAULT_ORDER)
            self.enabled_set = set(DEFAULT_ENABLED)
            self.modified = True
            self._populate_list(selected_idx=0)

    def save_and_close(self):
        save_menu_order(self.ordered_ids, self.enabled_set)
        control.notify(control.ADDON_NAME, control.lang(30684))
        self._win_closed = True
        self.close()

    def cancel_and_close(self):
        if self.modified:
            if control.yesno_dialog(control.lang(30673), control.lang(30688)):
                self.save_and_close()
                return
        self._win_closed = True
        self.close()

    def onClick(self, control_id):
        if control_id == 1000:
            # Clicking on a list item directly toggles its visibility
            self.toggle_visibility()
        elif control_id == 3001:  # Move Up
            self.move_up()
        elif control_id == 3002:  # Move Down
            self.move_down()
        elif control_id == 3003:  # Move to Top
            self.move_top()
        elif control_id == 3004:  # Move to Bottom
            self.move_bottom()
        elif control_id == 3005:  # Toggle Visibility
            self.toggle_visibility()
        elif control_id == 3006:  # Reset Defaults
            self.reset_defaults()
        elif control_id == 3007:  # Save & Apply
            self.save_and_close()
        elif control_id == 3008:  # Cancel
            self.cancel_and_close()

    def onAction(self, action):
        action_id = action.getId() if hasattr(action, 'getId') else int(action)
        if action_id in [9, 10, 92, 216]:
            # Back / ESC
            self.cancel_and_close()
        elif action_id == 7:
            # Enter / Select
            focus_id = self.getFocusId()
            if focus_id == 1000:
                self.toggle_visibility()
            else:
                self.onClick(focus_id)


def open_menu_order_dialog():
    """
    Open the interactive Main Menu Order & Customization window.
    """
    window = None
    try:
        window = MenuOrderDialog("menu_order.xml", control.ADDON_PATH)
        window.doModal()
    except Exception as e:
        control.log(f"Error in open_menu_order_dialog: {e}", 'error')
    finally:
        if window:
            del window
