# -*- coding: utf-8 -*-
"""
    Otaku Add-on - Menu Order & Visibility Customization Dialog
    Allows reordering and toggling visibility of Home screen main menu items.
"""

from resources.lib.ui import control

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
    """Resolve user-visible label for a menu item ID."""
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


def open_menu_order_dialog():
    """
    Interactive Kodi modal dialog for arranging Main Menu item order and toggling visibility.
    """
    ordered_ids, enabled_set = load_menu_order()
    current_focus = 0
    modified = False

    while not control.monitor.abortRequested():
        num_items = len(ordered_ids)
        display_lines = []
        for idx, item_id in enumerate(ordered_ids, start=1):
            title = get_item_label(item_id)
            status = "[X]" if item_id in enabled_set else "[  ]"
            display_lines.append(f"{status}  {idx:02d}.  {title}")

        # Action entries at bottom
        action_divider = num_items
        action_batch = num_items + 1
        action_reset = num_items + 2
        action_save = num_items + 3

        display_lines.append(f"─── {control.lang(30673)} ───")
        display_lines.append(f"[✓] {control.lang(30681)}")  # Batch Select Enabled Items
        display_lines.append(f"[↺] {control.lang(30682)}")  # Reset to Default Order & Visibility
        display_lines.append(f"[✔] {control.lang(30687)}")  # Save and Close

        heading = f"{control.lang(30673)} ({len(enabled_set)}/{num_items} Enabled)"
        selected = control.select_dialog(
            heading,
            display_lines,
            preselect=min(current_focus, len(display_lines) - 1)
        )

        if selected == -1:
            # User pressed Back/ESC
            if modified:
                if control.yesno_dialog(control.lang(30673), control.lang(30688)):
                    save_menu_order(ordered_ids, enabled_set)
                    control.notify(control.ADDON_NAME, control.lang(30684))
            break

        current_focus = selected

        # Actions at bottom
        if selected == action_save:
            save_menu_order(ordered_ids, enabled_set)
            control.notify(control.ADDON_NAME, control.lang(30684))
            break
        elif selected == action_batch:
            preselect = [i for i, item_id in enumerate(ordered_ids) if item_id in enabled_set]
            names = [f"{i+1:02d}. {get_item_label(item_id)}" for i, item_id in enumerate(ordered_ids)]
            new_selection = control.multiselect_dialog(control.lang(30681), names, preselect=preselect)
            if new_selection is not None:
                enabled_set = set(ordered_ids[i] for i in new_selection)
                modified = True
            continue
        elif selected == action_reset:
            if control.yesno_dialog(control.lang(30682), control.lang(30686)):
                ordered_ids = list(DEFAULT_ORDER)
                enabled_set = set(DEFAULT_ENABLED)
                modified = True
            continue
        elif selected >= action_divider:
            continue

        # Item selected
        item_id = ordered_ids[selected]
        title = get_item_label(item_id)
        is_enabled = item_id in enabled_set
        pos = selected + 1

        action_options = [
            f"1. {control.lang(30680)}: {'[Disable]' if is_enabled else '[Enable]'}",
            f"2. {control.lang(30675)} (Up)",
            f"3. {control.lang(30676)} (Down)",
            f"4. {control.lang(30677)}...",
            f"5. {control.lang(30678)}",
            f"6. {control.lang(30679)}",
        ]

        action_choice = control.select_dialog(
            f"{control.lang(30685)}: {title} ({pos}/{num_items})",
            action_options
        )

        if action_choice == -1:
            continue

        modified = True
        if action_choice == 0:  # Toggle Visibility
            if is_enabled:
                enabled_set.discard(item_id)
            else:
                enabled_set.add(item_id)
        elif action_choice == 1:  # Move Up
            current_focus = move_item(ordered_ids, selected, selected - 1)
        elif action_choice == 2:  # Move Down
            current_focus = move_item(ordered_ids, selected, selected + 1)
        elif action_choice == 3:  # Move to Position
            target_str = control.numeric_dialog(0, f"{control.lang(30683)} (1-{num_items}):", str(pos))
            if target_str and target_str.isdigit():
                target_pos = int(target_str)
                if 1 <= target_pos <= num_items:
                    current_focus = move_item(ordered_ids, selected, target_pos - 1)
        elif action_choice == 4:  # Move to Top
            current_focus = move_item(ordered_ids, selected, 0)
        elif action_choice == 5:  # Move to Bottom
            current_focus = move_item(ordered_ids, selected, num_items - 1)
