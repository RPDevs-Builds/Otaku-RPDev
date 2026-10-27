# -*- coding: utf-8 -*-
from urllib import parse

from resources.lib.ui import control, utils
from resources.lib.ui.router import Route, multi_route


def add_my_cloud(items):
    """Add My Debrid Cloud menu item if at least one debrid is active."""
    from resources.lib.debrid import debrid_cloud
    if debrid_cloud.get_active_providers():
        items.append((control.lang(30555), "my_cloud", 'tools.png', {}))
    return items


def _draw_cloud_directory(provider, folder_id=None):
    if control.HANDLE < 0:
        target = f"my_cloud/{provider}/{folder_id}" if folder_id else f"my_cloud/{provider}"
        return control.execute(f"Container.Update({control.addon_url(target)})")
    from resources.lib.debrid import debrid_cloud

    curr_folder = folder_id if (folder_id and folder_id != 'root') else 'root'
    raw_items = debrid_cloud.get_cloud_items(provider, None if curr_folder == 'root' else curr_folder)

    create_url = f"cloud_create_folder/{provider}/{curr_folder}"
    create_cm = [('Create New Folder', f'RunPlugin(plugin://{control.ADDON_ID}/{create_url})')]
    create_item = utils.allocate_item(
        "[COLOR limegreen][+ Create New Folder][/COLOR]",
        create_url,
        False,
        False,
        create_cm,
        'tools.png',
        {
            'title': 'Create New Folder',
            'plot': f"Create a new blank directory in your {provider.capitalize()} cloud.",
            'mediatype': 'files'
        }
    )
    list_items = [create_item]

    if curr_folder == 'root':
        purge_url = f"cloud_purge_stalled/{provider}"
        purge_cm = [('Purge Stalled Torrents', f'RunPlugin(plugin://{control.ADDON_ID}/{purge_url})')]
        purge_item = utils.allocate_item(
            "[COLOR crimson][🧹 Purge Stalled Torrents][/COLOR]",
            purge_url,
            False,
            False,
            purge_cm,
            'tools.png',
            {
                'title': 'Purge Stalled Torrents',
                'plot': f"Scan and delete 0% stalled or error torrents in your {provider.capitalize()} cloud.",
                'mediatype': 'files'
            }
        )
        list_items.append(purge_item)

    for itm in raw_items:
        is_folder = itm.get('is_folder', False)
        item_type = itm.get('item_type', 'folder' if is_folder else 'file')
        title = itm.get('name', 'Unknown')
        clean_title = itm.get('title', title)
        file_ref = itm.get('file_ref', '')
        size_str = itm.get('size', 'Unknown')

        q_params = parse.urlencode({
            'item_type': item_type,
            'file_ref': file_ref,
            'title': clean_title,
            'size': size_str,
            'parent_id': curr_folder,
        })

        cm = [
            ('Rename', f'RunPlugin(plugin://{control.ADDON_ID}/cloud_rename_item/{provider}/{itm["id"]}?{q_params})'),
            ('Move to Folder...', f'RunPlugin(plugin://{control.ADDON_ID}/cloud_move_item/{provider}/{itm["id"]}?{q_params})'),
            ('Create New Folder', f'RunPlugin(plugin://{control.ADDON_ID}/cloud_create_folder/{provider}/{curr_folder})'),
            ('Delete from Cloud', f'RunPlugin(plugin://{control.ADDON_ID}/delete_cloud_item/{provider}/{itm["id"]}?{q_params})'),
        ]

        if is_folder:
            url = f"my_cloud/{provider}/{itm['id']}"
            is_playable = False
        else:
            ref_encoded = parse.quote(file_ref, safe='')
            url = f"play_cloud_file/{provider}/{itm['id']}/{ref_encoded}"
            is_playable = True

        info = {
            'title': clean_title,
            'plot': f"Provider: {provider.capitalize()}\nSize: {size_str}",
            'mediatype': 'video' if not is_folder else 'files'
        }
        item_obj = utils.allocate_item(title, url, is_folder, is_playable, cm, 'tools.png', info)
        list_items.append(item_obj)

    view_type = 'addons' if control.getBool('interface.content_type') else ''
    control.draw_items(list_items, view_type)


@multi_route('my_cloud', 'my_cloud/')
def MY_CLOUD(payload, params):
    if control.HANDLE < 0:
        return control.execute(f"Container.Update({control.addon_url('my_cloud/')})")
    from resources.lib.debrid import debrid_cloud
    providers = debrid_cloud.get_active_providers()
    if not providers:
        control.notify(control.ADDON_NAME, "No active Debrid accounts found", icon=control.ADDON_ICON)
        item = utils.allocate_item("No Debrid Accounts Enabled (Configure in Settings)", "settings", False, False, [], 'tools.png')
        control.draw_items([item], '')
        return

    if len(providers) == 1:
        provider = list(providers.keys())[0]
        _draw_cloud_directory(provider, None)
    else:
        items = []
        for p_key, p_name in providers.items():
            items.append(utils.allocate_item(f"{p_name} Cloud", f"my_cloud/{p_key}", True, False, [], 'tools.png', {'title': f"{p_name} Cloud"}))
        view_type = 'addons' if control.getBool('interface.content_type') else ''
        control.draw_items(items, view_type)


@Route('my_cloud/*')
def MY_CLOUD_BROWSER(payload, params):
    parts = [p for p in payload.strip('/').split('/') if p]
    provider = parts[0] if parts else ''
    folder_id = parts[1] if len(parts) > 1 else None
    _draw_cloud_directory(provider, folder_id)


@Route('play_cloud_file/*')
def PLAY_CLOUD_FILE(payload, params):
    import xbmcgui
    import xbmcplugin
    from resources.lib.debrid import debrid_cloud
    parts = [p for p in payload.strip('/').split('/') if p]
    if len(parts) < 3:
        control.notify(control.ADDON_NAME, "Invalid cloud file reference", icon=control.ADDON_ICON)
        return control.exit_code()

    provider = parts[0]
    item_id = parts[1]
    file_ref = parse.unquote(parts[2])

    stream_url = debrid_cloud.resolve_stream_url(provider, item_id, file_ref)
    if not stream_url:
        control.notify(control.ADDON_NAME, f"Failed to resolve {provider.capitalize()} streaming link", icon=control.ADDON_ICON)
        return control.exit_code()

    item = xbmcgui.ListItem(path=stream_url, offscreen=True)
    item.setProperty('IsPlayable', 'true')
    xbmcplugin.setResolvedUrl(control.HANDLE, True, item)


@Route('cloud_create_folder/*')
def CLOUD_CREATE_FOLDER(payload, params):
    from resources.lib.debrid import debrid_cloud
    parts = [p for p in payload.strip('/').split('/') if p]
    if not parts:
        return
    provider = parts[0]
    parent_id = parts[1] if len(parts) > 1 else 'root'
    folder_name = control.keyboard(f"{control.ADDON_NAME}: New Folder Name", "")
    if not folder_name or not folder_name.strip():
        return
    if debrid_cloud.create_cloud_folder(provider, folder_name.strip(), parent_id):
        control.notify(control.ADDON_NAME, f"Created folder: {folder_name.strip()}", icon=control.ADDON_ICON)
        control.refresh()
    else:
        control.notify(control.ADDON_NAME, "Failed to create folder", icon=control.ADDON_ICON)


@Route('cloud_rename_item/*')
def CLOUD_RENAME_ITEM(payload, params):
    from resources.lib.debrid import debrid_cloud
    parts = [p for p in payload.strip('/').split('/') if p]
    if len(parts) < 2:
        return
    provider = parts[0]
    item_id = parts[1]
    item_type = params.get('item_type', 'file')
    file_ref = params.get('file_ref', '')
    current_title = params.get('title', '')
    new_name = control.keyboard(f"{control.ADDON_NAME}: Rename", current_title)
    if not new_name or not new_name.strip() or new_name.strip() == current_title:
        return
    if debrid_cloud.rename_cloud_item(provider, item_id, new_name.strip(), item_type=item_type, file_ref=file_ref):
        control.notify(control.ADDON_NAME, f"Renamed to: {new_name.strip()}", icon=control.ADDON_ICON)
        control.refresh()
    else:
        control.notify(control.ADDON_NAME, "Failed to rename item", icon=control.ADDON_ICON)


@Route('cloud_move_item/*')
def CLOUD_MOVE_ITEM(payload, params):
    from resources.lib.debrid import debrid_cloud
    parts = [p for p in payload.strip('/').split('/') if p]
    if len(parts) < 2:
        return
    provider = parts[0]
    item_id = parts[1]
    item_type = params.get('item_type', 'file')
    file_ref = params.get('file_ref', '')
    current_title = params.get('title', 'Item')
    size_str = params.get('size', '')
    origin_parent = params.get('parent_id', 'root') or 'root'

    nav_stack = [('root', '/ (Root Directory)')]
    target_folder_id = None
    target_folder_label = None

    while True:
        curr_id, curr_label = nav_stack[-1]
        subfolders = debrid_cloud.list_cloud_folders(
            provider,
            parent_id=curr_id,
            exclude_folder_id=item_id if item_type == 'folder' else None
        )
        options = []
        actions = []

        if curr_id != origin_parent:
            options.append(f"[COLOR limegreen]>> Move Here: {curr_label} <<[/COLOR]")
            actions.append(('move_here', curr_id, curr_label))

        options.append("[COLOR gold][+ Create New Folder Here & Move][/COLOR]")
        actions.append(('create_and_move', curr_id, curr_label))

        if len(nav_stack) > 1:
            options.append(".. (Back to Parent Folder)")
            actions.append(('back', None, None))

        for sf in subfolders:
            options.append(f"[COLOR deepskyblue][Folder][/COLOR] {sf['title']}")
            actions.append(('open_folder', sf['id'], sf['title']))

        heading = f"Move '{current_title}' — Location: {curr_label}"
        choice = control.select_dialog(heading, options)
        if choice is None or choice < 0 or choice >= len(actions):
            return

        act, act_id, act_label = actions[choice]
        if act == 'move_here':
            target_folder_id = act_id
            target_folder_label = act_label
            break
        elif act == 'back':
            nav_stack.pop()
        elif act == 'open_folder':
            nav_stack.append((act_id, act_label))
        elif act == 'create_and_move':
            new_folder_name = control.keyboard(f"{control.ADDON_NAME}: New Folder Name", "")
            if not new_folder_name or not new_folder_name.strip():
                continue
            new_folder_name = new_folder_name.strip()
            if debrid_cloud.create_cloud_folder(provider, new_folder_name, parent_id=curr_id):
                updated_folders = debrid_cloud.list_cloud_folders(provider, parent_id=curr_id)
                matched = next((f for f in reversed(updated_folders) if f['title'] == new_folder_name), None)
                if matched:
                    target_folder_id = matched['id']
                    target_folder_label = matched['title']
                    break
            control.notify(control.ADDON_NAME, "Failed to create destination folder", icon=control.ADDON_ICON)
            return

    if target_folder_id is not None:
        if debrid_cloud.move_cloud_item(
            provider,
            item_id,
            target_folder_id,
            item_type=item_type,
            file_ref=file_ref,
            title=current_title,
            size=size_str
        ):
            control.notify(control.ADDON_NAME, f"Moved to {target_folder_label}", icon=control.ADDON_ICON)
            control.refresh()
        else:
            control.notify(control.ADDON_NAME, "Failed to move item", icon=control.ADDON_ICON)


@Route('delete_cloud_item/*')
def DELETE_CLOUD_ITEM(payload, params):
    from resources.lib.debrid import debrid_cloud
    parts = [p for p in payload.strip('/').split('/') if p]
    if len(parts) < 2:
        return
    provider = parts[0]
    item_id = parts[1]
    item_type = params.get('item_type', 'folder')
    file_ref = params.get('file_ref', '')
    item_title = params.get('title', 'this item')
    confirmed = control.yesno_dialog(
        control.ADDON_NAME,
        f"Delete '{item_title}' from your {provider.capitalize()} cloud?"
    )
    if confirmed:
        success = debrid_cloud.delete_cloud_item(
            provider,
            item_id,
            item_type=item_type,
            file_ref=file_ref
        )
        if success:
            control.notify(control.ADDON_NAME, "Item removed from cloud", icon=control.ADDON_ICON)
            control.refresh()
        else:
            control.notify(control.ADDON_NAME, "Failed to delete item from cloud", icon=control.ADDON_ICON)


@Route('cloud_purge_stalled/*')
def CLOUD_PURGE_STALLED(payload, params):
    from resources.lib.debrid import debrid_cloud
    provider = payload.strip('/').split('/')[0] if payload else None
    if provider:
        purged = debrid_cloud.purge_stalled_torrents(provider)
        if purged > 0:
            control.refresh()

