# -*- coding: utf-8 -*-
"""
    Otaku Add-on - Menu Order & Visibility Customization Dialog
    Allows reordering and toggling visibility of Main Menu, Sub Menu, and Genre Menu items
    across all categories (Main Menus, Movies, TV Shows, TV Shorts, Specials, OVAs, ONAs, Music).
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

# Category specifications: (category_key, category_label_string_id, item_suffix)
CATEGORIES = (
    ('menu', 30407, ''),            # Main Menus
    ('movie', 30408, '_movie'),      # Movies
    ('tv_show', 30409, '_tv_show'),  # TV Shows
    ('tv_short', 30410, '_tv_short'),# TV Shorts
    ('special', 30411, '_special'),  # Specials
    ('ova', 30412, '_ova'),          # OVAs
    ('ona', 30413, '_ona'),          # ONAs
    ('music', 30414, '_music'),      # Music Videos
)

# Sub-category main menu stems (13 items)
_SUBCAT_MAINMENU_ITEMS = (
    ('last_watched', 30000, True, 'last_watched.png'),
    ('watch_history', 30068, True, 'watch_history.png'),
    ('next_up', 30451, True, 'next_up.png'),
    ('airing_last_season', 30002, True, 'airing_anime.png'),
    ('airing_this_season', 30003, True, 'airing_anime.png'),
    ('airing_next_season', 30004, True, 'airing_anime.png'),
    ('trending', 30012, True, 'trending.png'),
    ('popular', 30013, True, 'popular.png'),
    ('voted', 30014, True, 'voted.png'),
    ('favourites', 30015, True, 'favourites.png'),
    ('top_100', 30016, True, 'top_100_anime.png'),
    ('genres', 30017, True, 'genres_&_tags.png'),
    ('search_history', 30018, True, 'search.png'),
)

# Sub menu items (20 items: Trending, Popular, Voted, Favourites)
_SUBMENU_ITEMS = (
    ('trending_last_year', 30020, True, 'trending.png'),
    ('trending_this_year', 30021, True, 'trending.png'),
    ('trending_last_season', 30022, True, 'trending.png'),
    ('trending_this_season', 30023, True, 'trending.png'),
    ('all_time_trending', 30024, True, 'trending.png'),
    ('popular_last_year', 30025, True, 'popular.png'),
    ('popular_this_year', 30026, True, 'popular.png'),
    ('popular_last_season', 30027, True, 'popular.png'),
    ('popular_this_season', 30028, True, 'popular.png'),
    ('all_time_popular', 30029, True, 'popular.png'),
    ('voted_last_year', 30030, True, 'voted.png'),
    ('voted_this_year', 30031, True, 'voted.png'),
    ('voted_last_season', 30032, True, 'voted.png'),
    ('voted_this_season', 30033, True, 'voted.png'),
    ('all_time_voted', 30034, True, 'voted.png'),
    ('favourites_last_year', 30035, True, 'favourites.png'),
    ('favourites_this_year', 30036, True, 'favourites.png'),
    ('favourites_last_season', 30037, True, 'favourites.png'),
    ('favourites_this_season', 30038, True, 'favourites.png'),
    ('all_time_favourites', 30039, True, 'favourites.png'),
)

# Genre menu items (20 items: Multi + 19 standard genres)
_GENRE_ITEMS = (
    ('genres%s//', 30040, True, 'genre_multi.png'),
    ('genre_action%s', 30041, True, 'genre_action.png'),
    ('genre_adventure%s', 30042, True, 'genre_adventure.png'),
    ('genre_comedy%s', 30043, True, 'genre_comedy.png'),
    ('genre_drama%s', 30044, True, 'genre_drama.png'),
    ('genre_ecchi%s', 30045, True, 'genre_ecchi.png'),
    ('genre_fantasy%s', 30046, True, 'genre_fantasy.png'),
    ('genre_hentai%s', 30047, False, 'genre_hentai.png'),  # Default disabled
    ('genre_horror%s', 30048, True, 'genre_horror.png'),
    ('genre_shoujo%s', 30049, True, 'genre_shoujo.png'),
    ('genre_mecha%s', 30050, True, 'genre_mecha.png'),
    ('genre_music%s', 30051, True, 'genre_music.png'),
    ('genre_mystery%s', 30052, True, 'genre_mystery.png'),
    ('genre_psychological%s', 30053, True, 'genre_psychological.png'),
    ('genre_romance%s', 30054, True, 'genre_romance.png'),
    ('genre_sci_fi%s', 30055, True, 'genre_sci-fi.png'),
    ('genre_slice_of_life%s', 30056, True, 'genre_slice_of_life.png'),
    ('genre_sports%s', 30057, True, 'genre_sports.png'),
    ('genre_supernatural%s', 30058, True, 'genre_supernatural.png'),
    ('genre_thriller%s', 30059, True, 'genre_thriller.png'),
)


def get_menu_config(menu_key='menu.mainmenu'):
    """
    Returns full metadata specification for any of the 24 configurable menus.
    Key format: '<category>.<menu_type>' (e.g., 'menu.mainmenu', 'movie.submenu', 'tv_show.genres')
    """
    if '.' in menu_key:
        cat_id, type_id = menu_key.split('.', 1)
    else:
        cat_id, type_id = 'menu', menu_key

    cat_meta = next((c for c in CATEGORIES if c[0] == cat_id), None)
    if not cat_meta:
        cat_id, cat_label_id, suffix = 'menu', 30407, ''
    else:
        cat_id, cat_label_id, suffix = cat_meta

    if type_id not in ('mainmenu', 'submenu', 'genres'):
        type_id = 'mainmenu'

    if cat_id == 'menu' and type_id == 'mainmenu':
        items = list(DEFAULT_MENU_ITEMS)
    elif type_id == 'mainmenu':
        items = [(stem + suffix, lid, def_en, icon) for stem, lid, def_en, icon in _SUBCAT_MAINMENU_ITEMS]
    elif type_id == 'submenu':
        items = [(stem + suffix, lid, def_en, icon) for stem, lid, def_en, icon in _SUBMENU_ITEMS]
    elif type_id == 'genres':
        items = [(stem % suffix, lid, def_en, icon) for stem, lid, def_en, icon in _GENRE_ITEMS]
    else:
        items = list(DEFAULT_MENU_ITEMS)

    cat_label = control.lang(cat_label_id) if cat_label_id else cat_id.title()
    type_label_id = 30404 if type_id == 'mainmenu' else (30405 if type_id == 'submenu' else 30406)
    type_label = control.lang(type_label_id)

    if cat_id == 'menu':
        title = f"{type_label} Order & Customization" if type_id != 'mainmenu' else control.lang(30673)
    else:
        title = f"{cat_label}: {type_label} Order & Customization"

    return {
        'key': f"{cat_id}.{type_id}",
        'category': cat_id,
        'type': type_id,
        'order_key': f"{cat_id}.{type_id}.order",
        'config_key': f"{cat_id}.{type_id}.config",
        'title': title,
        'description': control.lang(30674),
        'items': items,
        'default_order': [x[0] for x in items],
        'default_enabled': [x[0] for x in items if x[2]],
        'metadata': {x[0]: (x[1], x[3]) for x in items},
        'valid_ids': set(x[0] for x in items),
        'is_main_home': (cat_id == 'menu' and type_id == 'mainmenu')
    }


def get_item_label(item_id, metadata=None):
    """Resolve user-visible label for a menu item ID (clean, unnumbered)."""
    meta_dict = metadata if metadata is not None else MENU_ITEM_METADATA
    meta = meta_dict.get(item_id)
    if meta:
        lbl = control.lang(meta[0])
        if lbl:
            return lbl
    # Handle genres// root label
    if item_id.startswith('genres') and '//' in item_id:
        return control.lang(30040)
    return item_id.replace('_', ' ').replace('/', '').title()


def load_menu_order(menu_key='menu.mainmenu'):
    """
    Loads current sequence and enabled set for the specified menu.
    Returns:
        tuple: (ordered_ids, enabled_set)
    """
    cfg = get_menu_config(menu_key)
    order_key = cfg['order_key']
    config_key = cfg['config_key']
    default_order = cfg['default_order']
    default_enabled = cfg['default_enabled']
    valid_ids = cfg['valid_ids']

    order_setting = control.getSetting(order_key)
    if order_setting:
        raw_order = [x.strip() for x in order_setting.split(',') if x.strip()]
        ordered_ids = [x for x in raw_order if x in valid_ids]
        for item in default_order:
            if item not in ordered_ids:
                ordered_ids.append(item)
    else:
        ordered_ids = list(default_order)

    config_list = control.getStringList(config_key)
    if config_list:
        enabled_set = set(config_list)
        # Backward compatibility: Home screen watchlist auto-include when order never customized
        if cfg['is_main_home'] and not order_setting and 'watchlist' not in enabled_set:
            enabled_set.add('watchlist')
    else:
        enabled_set = set(default_enabled)

    return ordered_ids, enabled_set


def save_menu_order(ordered_ids, enabled_set, menu_key='menu.mainmenu'):
    """
    Persists complete order and ordered enabled subset for the menu, then signals refresh.
    """
    cfg = get_menu_config(menu_key)
    order_key = cfg['order_key']
    config_key = cfg['config_key']

    control.setSetting(order_key, ','.join(ordered_ids))
    enabled_ordered = [x for x in ordered_ids if x in enabled_set]
    control.setStringList(config_key, enabled_ordered)
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
    Interactive full GUI Window for arranging item order and toggling visibility
    across all categories and sub-menus in Otaku.
    """

    def __init__(self, xml_file, location, menu_key='menu.mainmenu'):
        super().__init__(xml_file, location)
        self.menu_key = menu_key
        self.menu_config = get_menu_config(menu_key)
        self.ordered_ids, self.enabled_set = load_menu_order(menu_key)
        self.list_control = None
        self.selected_index = 0
        self.modified = False
        self._win_closed = False

    def onInit(self):
        control.closeBusyDialog()
        # Set dynamic title & description for window header
        self.setProperty('menu_title', self.menu_config.get('title', 'Menu Order & Customization'))
        self.setProperty('menu_description', self.menu_config.get('description', ''))

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
                    self.selected_index = pos
                    return pos
            except Exception:
                pass
        return getattr(self, 'selected_index', 0)

    def _populate_list(self, selected_idx=0):
        if self.list_control is None:
            return

        current_focus = None
        try:
            current_focus = self.getFocusId()
        except Exception:
            pass

        self.list_control.reset()
        meta_dict = self.menu_config['metadata']
        is_main = self.menu_config['is_main_home']

        for item_id in self.ordered_ids:
            title = get_item_label(item_id, meta_dict)
            is_enabled = item_id in self.enabled_set

            item = xbmcgui.ListItem(label=title)
            meta = meta_dict.get(item_id)
            icon_file = meta[1] if meta else 'tools.png'
            icon_path = utils._get_artwork_path(icon_file)
            item.setArt({'icon': icon_path, 'thumb': icon_path})

            status_badge = '[COLOR deepskyblue][✓][/COLOR]' if is_enabled else '[COLOR grey][  ][/COLOR]'
            if is_main:
                status_text = control.lang(30690) if is_enabled else control.lang(30691)
            else:
                status_text = control.lang(30695) if is_enabled else control.lang(30696)

            item.setProperty('status_badge', status_badge)
            item.setProperty('status_text', status_text)
            item.setProperty('item_id', item_id)
            self.list_control.addItem(item)

        if len(self.ordered_ids) > 0:
            target_idx = max(0, min(len(self.ordered_ids) - 1, selected_idx))
            self.selected_index = target_idx
            self.list_control.selectItem(target_idx)

        if current_focus and current_focus != 1000:
            try:
                self.setFocusId(current_focus)
            except Exception:
                pass

    def move_up(self):
        idx = self._get_current_index()
        if idx > 0:
            new_idx = move_item(self.ordered_ids, idx, idx - 1)
            self.selected_index = new_idx
            self.modified = True
            self._populate_list(selected_idx=new_idx)
            return new_idx
        return idx

    def move_down(self):
        idx = self._get_current_index()
        if idx < len(self.ordered_ids) - 1:
            new_idx = move_item(self.ordered_ids, idx, idx + 1)
            self.selected_index = new_idx
            self.modified = True
            self._populate_list(selected_idx=new_idx)
            return new_idx
        return idx

    def move_top(self):
        idx = self._get_current_index()
        if idx > 0:
            new_idx = move_item(self.ordered_ids, idx, 0)
            self.selected_index = 0
            self.modified = True
            self._populate_list(selected_idx=0)
            return 0
        return idx

    def move_bottom(self):
        idx = self._get_current_index()
        last_idx = len(self.ordered_ids) - 1
        if idx < last_idx:
            new_idx = move_item(self.ordered_ids, idx, last_idx)
            self.selected_index = last_idx
            self.modified = True
            self._populate_list(selected_idx=last_idx)
            return last_idx
        return idx

    def toggle_visibility(self, index=None):
        idx = index if index is not None else self._get_current_index()
        if idx < 0 or idx >= len(self.ordered_ids):
            return
        item_id = self.ordered_ids[idx]
        if item_id in self.enabled_set:
            self.enabled_set.discard(item_id)
        else:
            self.enabled_set.add(item_id)
        self.modified = True

        # In-place widget update: modify existing ListItem properties without reset()
        if self.list_control is not None:
            try:
                li = self.list_control.getListItem(idx)
                if li is not None:
                    is_enabled = item_id in self.enabled_set
                    status_badge = '[COLOR deepskyblue][✓][/COLOR]' if is_enabled else '[COLOR grey][  ][/COLOR]'
                    if self.menu_config['is_main_home']:
                        status_text = control.lang(30690) if is_enabled else control.lang(30691)
                    else:
                        status_text = control.lang(30695) if is_enabled else control.lang(30696)
                    li.setProperty('status_badge', status_badge)
                    li.setProperty('status_text', status_text)
            except Exception as e:
                control.log(f"MenuOrderDialog: Failed in-place item update: {e}", 'warning')

    def toggle_all(self):
        """
        Toggles all items on or off.
        If all items are currently enabled, disables all items.
        Otherwise (if some or none are enabled), enables all items.
        Updates ListItem properties in-place without resetting scroll or focus.
        """
        if not self.ordered_ids:
            return

        if len(self.enabled_set) == len(self.ordered_ids):
            self.enabled_set.clear()
        else:
            self.enabled_set = set(self.ordered_ids)

        self.modified = True

        # In-place widget update for all items without resetting list focus or position
        if self.list_control is not None:
            is_main = self.menu_config['is_main_home']
            for idx, item_id in enumerate(self.ordered_ids):
                try:
                    li = self.list_control.getListItem(idx)
                    if li is not None:
                        is_enabled = item_id in self.enabled_set
                        status_badge = '[COLOR deepskyblue][✓][/COLOR]' if is_enabled else '[COLOR grey][  ][/COLOR]'
                        if is_main:
                            status_text = control.lang(30690) if is_enabled else control.lang(30691)
                        else:
                            status_text = control.lang(30695) if is_enabled else control.lang(30696)
                        li.setProperty('status_badge', status_badge)
                        li.setProperty('status_text', status_text)
                except Exception as e:
                    control.log(f"MenuOrderDialog: Failed in-place item update at index {idx}: {e}", 'warning')

    def reset_defaults(self):
        if control.yesno_dialog(control.lang(30682), control.lang(30686)):
            self.ordered_ids = list(self.menu_config['default_order'])
            self.enabled_set = set(self.menu_config['default_enabled'])
            self.selected_index = 0
            self.modified = True
            self._populate_list(selected_idx=0)

    def save_and_close(self):
        save_menu_order(self.ordered_ids, self.enabled_set, self.menu_key)
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
            # Clicking on a list item directly toggles its visibility in-place without moving
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
        elif control_id == 3009:  # Toggle All On / Off
            self.toggle_all()
        elif control_id == 3006:  # Reset Defaults
            self.reset_defaults()
        elif control_id == 3007:  # Save & Apply
            self.save_and_close()
        elif control_id == 3008:  # Cancel
            self.cancel_and_close()

    def onAction(self, action):
        action_id = action.getId() if hasattr(action, 'getId') else int(action)
        if action_id in [9, 10, 92, 110, 216]:
            # Back / ESC
            self.cancel_and_close()


def open_menu_order_dialog(menu_key='menu.mainmenu'):
    """
    Open the interactive Menu Order & Customization window for any category or sub-menu.
    """
    window = None
    try:
        window = MenuOrderDialog("menu_order.xml", control.ADDON_PATH, menu_key=menu_key)
        window.doModal()
    except Exception as e:
        control.log(f"Error in open_menu_order_dialog({menu_key}): {e}", 'error')
    finally:
        if window:
            del window
