"""
debrid_cloud.py - Unified Debrid Cloud Browser, File/Folder Manager & Streaming Resolver
========================================================================================
Provides unified listing, playback unrestrict, folder creation, item renaming,
moving files/folders into subdirectories, and deletion for active torrents and
cached files across Real-Debrid, TorBox, Premiumize, and AllDebrid.
"""
import json
import os
import uuid
from resources.lib.ui import control, source_utils


def format_bytes(num_bytes):
    """Format bytes into readable size string (e.g. 1.45 GB)"""
    try:
        num_bytes = float(num_bytes)
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if num_bytes < 1024.0:
                if unit == 'B':
                    return f"{int(num_bytes)} B"
                elif unit in ['KB', 'MB']:
                    return f"{num_bytes:.1f} {unit}"
                else:
                    return f"{num_bytes:.2f} {unit}"
            num_bytes /= 1024.0
        return f"{num_bytes:.2f} PB"
    except (ValueError, TypeError):
        return "0 B"


def get_active_providers():
    """Return dict of enabled debrid providers with valid tokens and their display labels."""
    enabled = control.enabled_debrid()
    labels = {
        'realdebrid': 'Real-Debrid',
        'torbox': 'TorBox',
        'premiumize': 'Premiumize',
        'alldebrid': 'AllDebrid',
        'debridlink': 'Debrid-Link',
    }
    return {k: labels.get(k, k.capitalize()) for k, v in enabled.items() if v}


# ═══════════════════════════════════════════════════════════════════════════
#  Virtual Cloud Organization Layer (VFS) for Flat-Torrent Debrid Providers
# ═══════════════════════════════════════════════════════════════════════════

def _get_vfs_path():
    if not os.path.exists(control.dataPath):
        os.makedirs(control.dataPath, exist_ok=True)
    return os.path.join(control.dataPath, 'cloud_vfs.json')


def _load_vfs():
    path = _get_vfs_path()
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            control.log(f"Error loading cloud_vfs.json: {str(e)}", "warning")
    return {}


def _save_vfs(data):
    path = _get_vfs_path()
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
        return True
    except Exception as e:
        control.log(f"Error saving cloud_vfs.json: {str(e)}", "error")
        return False


def _get_provider_vfs(vfs, provider):
    p = vfs.setdefault(provider, {})
    p.setdefault('folders', {})
    p.setdefault('folder_moves', {})
    p.setdefault('file_moves', {})
    p.setdefault('renames', {})
    p.setdefault('hidden_files', [])
    return p


def _normalize_folder_id(folder_id):
    return str(folder_id) if (folder_id and str(folder_id) != 'root') else 'root'


def _is_descendant_folder(p_vfs, candidate_id, source_folder_id):
    """Return True if candidate_id is equal to or nested inside source_folder_id."""
    curr = _normalize_folder_id(candidate_id)
    src = _normalize_folder_id(source_folder_id)
    if curr == src:
        return True
    visited = set()
    folders = p_vfs.get('folders', {})
    folder_moves = p_vfs.get('folder_moves', {})
    while curr != 'root' and curr not in visited:
        visited.add(curr)
        if curr in folders:
            curr = _normalize_folder_id(folders[curr].get('parent_id'))
        elif curr in folder_moves:
            curr = _normalize_folder_id(folder_moves[curr])
        else:
            break
        if curr == src:
            return True
    return False


def _resolve_effective_parent(p_vfs, raw_parent):
    parent = _normalize_folder_id(raw_parent)
    if parent != 'root' and parent.startswith('vfs_') and parent not in p_vfs.get('folders', {}):
        return 'root'
    return parent


def _append_vfs_subfolders(items, provider, p_vfs, norm_folder):
    """Append custom VFS directories whose parent_id matches norm_folder."""
    for fid, fmeta in p_vfs.get('folders', {}).items():
        parent = _normalize_folder_id(fmeta.get('parent_id'))
        if parent == norm_folder:
            fname = p_vfs.get('renames', {}).get(f"folder::{fid}", fmeta.get('name', 'Folder'))
            items.append({
                'name': f"[COLOR deepskyblue][Folder][/COLOR] {fname}",
                'title': fname,
                'id': str(fid),
                'provider': provider,
                'is_folder': True,
                'item_type': 'folder',
                'parent_id': norm_folder,
                'size': 'Folder',
            })


def _append_moved_files(items, provider, p_vfs, norm_folder):
    """Append video files that were explicitly moved into norm_folder via VFS."""
    hidden = set(p_vfs.get('hidden_files', []))
    renames = p_vfs.get('renames', {})
    existing_keys = {f"{itm.get('id')}::{itm.get('file_ref')}" for itm in items if not itm.get('is_folder')}
    for fkey, mdata in p_vfs.get('file_moves', {}).items():
        if fkey in hidden or fkey in existing_keys:
            continue
        target = _resolve_effective_parent(p_vfs, mdata.get('target_folder_id'))
        if target == norm_folder:
            orig_id = str(mdata.get('id', ''))
            file_ref = mdata.get('file_ref', '')
            fname = renames.get(f"file::{fkey}", mdata.get('title', 'Video'))
            size_str = mdata.get('size', '0 B')
            size_badge = f"[{size_str}]" if size_str else ""
            items.append({
                'name': f"{size_badge} {fname}".strip(),
                'title': fname,
                'id': orig_id,
                'file_ref': file_ref,
                'provider': provider,
                'is_folder': False,
                'item_type': 'file',
                'parent_id': norm_folder,
                'size': size_str or '0 B',
            })


# ═══════════════════════════════════════════════════════════════════════════
#  Cloud Listing & Navigation
# ═══════════════════════════════════════════════════════════════════════════

def get_cloud_items(provider, folder_id=None):
    """
    Fetch items from user's debrid cloud.
    If folder_id is None/'root': returns root folders, torrents, and root video files.
    If folder_id is provided: returns subfolders and playable video files inside that folder.
    """
    items = []
    norm_folder = _normalize_folder_id(folder_id)
    try:
        if provider == 'premiumize':
            from resources.lib.debrid.premiumize import Premiumize
            pm = Premiumize()
            folder_res = pm.list_folder(None if norm_folder == 'root' else norm_folder)
            content = folder_res.get('content', []) if isinstance(folder_res, dict) else (folder_res if isinstance(folder_res, list) else [])
            for item in content:
                itype = item.get('type')
                iid = str(item.get('id', ''))
                name = item.get('name', 'Unknown')
                size_val = item.get('size', 0)
                if itype == 'folder':
                    items.append({
                        'name': f"[COLOR deepskyblue][Folder][/COLOR] {name}",
                        'title': name,
                        'id': iid,
                        'provider': 'premiumize',
                        'is_folder': True,
                        'item_type': 'folder',
                        'parent_id': norm_folder,
                        'size': format_bytes(size_val) if size_val else 'Folder',
                    })
                elif itype == 'file':
                    if not source_utils.is_file_ext_valid(name):
                        continue
                    size_str = format_bytes(size_val)
                    size_badge = f"[{size_str}]"
                    items.append({
                        'name': f"{size_badge} {name}",
                        'title': name,
                        'id': iid,
                        'file_ref': item.get('link', ''),
                        'provider': 'premiumize',
                        'is_folder': False,
                        'item_type': 'file',
                        'parent_id': norm_folder,
                        'size': size_str,
                    })
            return items

        vfs = _load_vfs()
        p_vfs = _get_provider_vfs(vfs, provider)
        hidden_files = set(p_vfs.get('hidden_files', []))
        renames = p_vfs.get('renames', {})
        folder_moves = p_vfs.get('folder_moves', {})
        file_moves = p_vfs.get('file_moves', {})

        # 1. Custom VFS folders inside norm_folder
        _append_vfs_subfolders(items, provider, p_vfs, norm_folder)

        need_torrents = (norm_folder == 'root') or any(
            _resolve_effective_parent(p_vfs, dest) == norm_folder for dest in folder_moves.values()
        )

        if provider == 'realdebrid':
            from resources.lib.debrid.real_debrid import RealDebrid
            rd = RealDebrid()
            if need_torrents:
                torrents = rd.list_torrents() or []
                for t in torrents:
                    tid = str(t.get('id', ''))
                    eff_parent = _resolve_effective_parent(p_vfs, folder_moves.get(tid, 'root'))
                    if eff_parent != norm_folder:
                        continue
                    filename = renames.get(f"folder::{tid}", t.get('filename', 'Unknown'))
                    bytes_val = t.get('bytes', 0)
                    progress = t.get('progress', 0)
                    status = t.get('status', '')
                    is_ready = status == 'downloaded' or progress == 100
                    status_badge = "[COLOR forestgreen][100%][/COLOR]" if is_ready else f"[COLOR orange][{progress}%][/COLOR]"
                    size_str = format_bytes(bytes_val)
                    size_badge = f"[{size_str}]"
                    items.append({
                        'name': f"{status_badge} {size_badge} {filename}",
                        'title': filename,
                        'id': tid,
                        'provider': 'realdebrid',
                        'is_folder': True,
                        'item_type': 'folder',
                        'parent_id': norm_folder,
                        'size': size_str,
                        'progress': progress,
                        'status': status,
                    })

            if norm_folder != 'root' and not norm_folder.startswith('vfs_'):
                info = rd.torrentInfo(norm_folder) or {}
                selected_files = [f for f in info.get('files', []) if f.get('selected') == 1]
                links = info.get('links', [])
                for idx, f in enumerate(selected_files):
                    link = links[idx] if idx < len(links) else None
                    if not link:
                        continue
                    path = f.get('path', '')
                    orig_fname = path.rsplit('/', 1)[-1] if '/' in path else path
                    if not source_utils.is_file_ext_valid(orig_fname):
                        continue
                    fkey = f"{norm_folder}::{link}"
                    if fkey in hidden_files:
                        continue
                    if fkey in file_moves:
                        moved_target = _resolve_effective_parent(p_vfs, file_moves[fkey].get('target_folder_id'))
                        if moved_target != norm_folder:
                            continue
                    fname = renames.get(f"file::{fkey}", orig_fname)
                    size_str = format_bytes(f.get('bytes', 0))
                    items.append({
                        'name': f"[{size_str}] {fname}",
                        'title': fname,
                        'id': norm_folder,
                        'file_ref': link,
                        'provider': 'realdebrid',
                        'is_folder': False,
                        'item_type': 'file',
                        'parent_id': norm_folder,
                        'size': size_str,
                    })

        elif provider == 'torbox':
            from resources.lib.debrid.torbox import TorBox
            tb = TorBox()
            if need_torrents:
                torrents = tb.list_torrents() or []
                for t in torrents:
                    tid = str(t.get('id', ''))
                    eff_parent = _resolve_effective_parent(p_vfs, folder_moves.get(tid, 'root'))
                    if eff_parent != norm_folder:
                        continue
                    name = renames.get(f"folder::{tid}", t.get('name', 'Unknown'))
                    size_val = t.get('size', 0)
                    progress = int(t.get('progress', 0) * 100) if isinstance(t.get('progress'), float) else t.get('progress', 0)
                    state = t.get('download_state', '')
                    is_ready = state in ('completed', 'cached') or progress == 100
                    status_badge = "[COLOR forestgreen][100%][/COLOR]" if is_ready else f"[COLOR orange][{progress}%][/COLOR]"
                    size_str = format_bytes(size_val)
                    items.append({
                        'name': f"{status_badge} [{size_str}] {name}",
                        'title': name,
                        'id': tid,
                        'provider': 'torbox',
                        'is_folder': True,
                        'item_type': 'folder',
                        'parent_id': norm_folder,
                        'size': size_str,
                        'progress': progress,
                        'status': state,
                    })

            if norm_folder != 'root' and not norm_folder.startswith('vfs_'):
                info = tb.get_torrent_info(norm_folder) or {}
                files = info.get('files', [])
                for f in files:
                    fid = str(f.get('id', ''))
                    raw_name = f.get('name', 'Unknown')
                    orig_fname = raw_name.rsplit('/', 1)[-1] if '/' in raw_name else raw_name
                    if not source_utils.is_file_ext_valid(orig_fname):
                        continue
                    fkey = f"{norm_folder}::{fid}"
                    if fkey in hidden_files:
                        continue
                    if fkey in file_moves:
                        moved_target = _resolve_effective_parent(p_vfs, file_moves[fkey].get('target_folder_id'))
                        if moved_target != norm_folder:
                            continue
                    fname = renames.get(f"file::{fkey}", orig_fname)
                    size_str = format_bytes(f.get('size', 0))
                    items.append({
                        'name': f"[{size_str}] {fname}",
                        'title': fname,
                        'id': norm_folder,
                        'file_ref': fid,
                        'provider': 'torbox',
                        'is_folder': False,
                        'item_type': 'file',
                        'parent_id': norm_folder,
                        'size': size_str,
                    })

        elif provider == 'alldebrid':
            from resources.lib.debrid.all_debrid import AllDebrid
            ad = AllDebrid()
            need_ad_list = need_torrents or (norm_folder != 'root' and not norm_folder.startswith('vfs_'))
            torrents = (ad.list_torrents() or []) if need_ad_list else []
            if need_torrents:
                for t in torrents:
                    tid = str(t.get('id', ''))
                    eff_parent = _resolve_effective_parent(p_vfs, folder_moves.get(tid, 'root'))
                    if eff_parent != norm_folder:
                        continue
                    fname = renames.get(f"folder::{tid}", t.get('filename', 'Unknown'))
                    fsize = t.get('size', 0)
                    status_code = t.get('statusCode', 0)
                    is_ready = status_code == 4
                    status_badge = "[COLOR forestgreen][100%][/COLOR]" if is_ready else "[COLOR orange][Downloading][/COLOR]"
                    size_str = format_bytes(fsize)
                    items.append({
                        'name': f"{status_badge} [{size_str}] {fname}",
                        'title': fname,
                        'id': tid,
                        'provider': 'alldebrid',
                        'is_folder': True,
                        'item_type': 'folder',
                        'parent_id': norm_folder,
                        'size': size_str,
                    })

            if norm_folder != 'root' and not norm_folder.startswith('vfs_'):
                match = next((t for t in torrents if str(t.get('id')) == norm_folder), None)
                if match:
                    raw_files = match.get('files', [])
                    extracted = []
                    if raw_files:
                        folder_details = []
                        for x in raw_files:
                            ad.collect_files(x, folder_details)
                        for f in folder_details:
                            path = f.get('path', '')
                            orig_fname = path.rsplit('/', 1)[-1] if '/' in path else path
                            extracted.append((f.get('link', ''), orig_fname, f.get('size', 0)))
                    else:
                        for link_entry in match.get('links', []):
                            extracted.append((
                                link_entry.get('link', ''),
                                link_entry.get('filename', ''),
                                link_entry.get('size', 0)
                            ))
                    for link, orig_fname, fsize in extracted:
                        if not link or not source_utils.is_file_ext_valid(orig_fname):
                            continue
                        fkey = f"{norm_folder}::{link}"
                        if fkey in hidden_files:
                            continue
                        if fkey in file_moves:
                            moved_target = _resolve_effective_parent(p_vfs, file_moves[fkey].get('target_folder_id'))
                            if moved_target != norm_folder:
                                continue
                        fname = renames.get(f"file::{fkey}", orig_fname)
                        size_str = format_bytes(fsize)
                        items.append({
                            'name': f"[{size_str}] {fname}",
                            'title': fname,
                            'id': norm_folder,
                            'file_ref': link,
                            'provider': 'alldebrid',
                            'is_folder': False,
                            'item_type': 'file',
                            'parent_id': norm_folder,
                            'size': size_str,
                        })

        # Append any files moved into norm_folder
        _append_moved_files(items, provider, p_vfs, norm_folder)

    except Exception as e:
        control.log(f"Error fetching {provider} cloud items: {str(e)}", "error")

    return items


# ═══════════════════════════════════════════════════════════════════════════
#  Cloud Management Operations (Create Folder, Rename, Move, Delete)
# ═══════════════════════════════════════════════════════════════════════════

def create_cloud_folder(provider, name, parent_id=None):
    """Create a blank directory in the user's cloud (at root or inside parent_id)."""
    clean_name = (name or '').strip()
    if not clean_name:
        return False
    norm_parent = _normalize_folder_id(parent_id)
    try:
        if provider == 'premiumize':
            from resources.lib.debrid.premiumize import Premiumize
            res = Premiumize().create_folder(clean_name, None if norm_parent == 'root' else norm_parent)
            return bool(res and res.get('status') == 'success')

        vfs = _load_vfs()
        p_vfs = _get_provider_vfs(vfs, provider)
        new_id = f"vfs_{uuid.uuid4().hex[:8]}"
        p_vfs['folders'][new_id] = {
            'name': clean_name,
            'parent_id': norm_parent,
        }
        return _save_vfs(vfs)
    except Exception as e:
        control.log(f"Error creating {provider} cloud folder '{clean_name}': {str(e)}", "error")
        return False


def rename_cloud_item(provider, item_id, new_name, item_type='file', file_ref=''):
    """Rename a file or folder in the user's cloud."""
    clean_name = (new_name or '').strip()
    if not clean_name:
        return False
    item_id = str(item_id)
    try:
        if provider == 'premiumize':
            from resources.lib.debrid.premiumize import Premiumize
            pm = Premiumize()
            if item_type == 'folder':
                res = pm.rename_folder(item_id, clean_name)
            else:
                res = pm.rename_item(item_id, clean_name)
            return bool(res and res.get('status') == 'success')

        vfs = _load_vfs()
        p_vfs = _get_provider_vfs(vfs, provider)
        if item_type == 'folder':
            if item_id in p_vfs['folders']:
                p_vfs['folders'][item_id]['name'] = clean_name
            p_vfs['renames'][f"folder::{item_id}"] = clean_name
        else:
            fkey = f"{item_id}::{file_ref}"
            p_vfs['renames'][f"file::{fkey}"] = clean_name
            if fkey in p_vfs['file_moves']:
                p_vfs['file_moves'][fkey]['title'] = clean_name
        return _save_vfs(vfs)
    except Exception as e:
        control.log(f"Error renaming {provider} cloud item {item_id}: {str(e)}", "error")
        return False


def move_cloud_item(provider, item_id, target_folder_id, item_type='file', file_ref='', title='', size=''):
    """Move a file or folder into target_folder_id (or 'root')."""
    item_id = str(item_id)
    norm_target = _normalize_folder_id(target_folder_id)
    try:
        if provider == 'premiumize':
            from resources.lib.debrid.premiumize import Premiumize
            pm = Premiumize()
            if item_type == 'folder':
                if item_id == norm_target:
                    return False
                res = pm.move_items(norm_target, folder_ids=[item_id])
            else:
                res = pm.move_items(norm_target, file_ids=[item_id])
            return bool(res and res.get('status') == 'success')

        vfs = _load_vfs()
        p_vfs = _get_provider_vfs(vfs, provider)
        if item_type == 'folder':
            if _is_descendant_folder(p_vfs, norm_target, item_id):
                return False
            if item_id in p_vfs['folders']:
                p_vfs['folders'][item_id]['parent_id'] = norm_target
            else:
                if norm_target == 'root':
                    p_vfs['folder_moves'].pop(item_id, None)
                else:
                    p_vfs['folder_moves'][item_id] = norm_target
        else:
            fkey = f"{item_id}::{file_ref}"
            if norm_target == item_id:
                p_vfs['file_moves'].pop(fkey, None)
            else:
                existing = p_vfs['file_moves'].get(fkey, {})
                resolved_title = p_vfs['renames'].get(f"file::{fkey}") or title or existing.get('title', 'Video')
                resolved_size = size or existing.get('size', '0 B')
                p_vfs['file_moves'][fkey] = {
                    'target_folder_id': norm_target,
                    'id': item_id,
                    'file_ref': file_ref,
                    'title': resolved_title,
                    'size': resolved_size,
                }
        return _save_vfs(vfs)
    except Exception as e:
        control.log(f"Error moving {provider} cloud item {item_id} to {norm_target}: {str(e)}", "error")
        return False


def list_cloud_folders(provider, parent_id=None, exclude_folder_id=None):
    """Return list of folders [{'id': ..., 'title': ...}] inside parent_id for destination picking."""
    norm_parent = _normalize_folder_id(parent_id)
    excl = str(exclude_folder_id) if exclude_folder_id else None
    folders = []
    for itm in get_cloud_items(provider, None if norm_parent == 'root' else norm_parent):
        if itm.get('is_folder'):
            fid = str(itm.get('id', ''))
            if excl and fid == excl:
                continue
            folders.append({
                'id': fid,
                'title': itm.get('title') or itm.get('name', 'Folder'),
            })
    return folders


def _delete_provider_torrent(provider, item_id):
    if provider == 'realdebrid':
        from resources.lib.debrid.real_debrid import RealDebrid
        return RealDebrid().deleteTorrent(item_id)
    elif provider == 'torbox':
        from resources.lib.debrid.torbox import TorBox
        return TorBox().delete_torrent(item_id)
    elif provider == 'alldebrid':
        from resources.lib.debrid.all_debrid import AllDebrid
        return AllDebrid().delete_magnet(item_id)
    return False


def _cleanup_torrent_vfs(p_vfs, torrent_id):
    tid = str(torrent_id)
    p_vfs['folder_moves'].pop(tid, None)
    p_vfs['renames'].pop(f"folder::{tid}", None)
    prefix = f"{tid}::"
    for fkey in [k for k in p_vfs['file_moves'] if k.startswith(prefix)]:
        p_vfs['file_moves'].pop(fkey, None)
    for rkey in [k for k in p_vfs['renames'] if k.startswith(f"file::{prefix}")]:
        p_vfs['renames'].pop(rkey, None)
    p_vfs['hidden_files'] = [k for k in p_vfs['hidden_files'] if not k.startswith(prefix)]


def delete_cloud_item(provider, item_id, item_type='folder', file_ref=''):
    """Delete folder or video file from user's debrid cloud."""
    item_id = str(item_id)
    try:
        if provider == 'premiumize':
            from resources.lib.debrid.premiumize import Premiumize
            pm = Premiumize()
            if item_type == 'file':
                res = pm.delete_item(item_id)
                return bool(res and res.get('status') == 'success')
            else:
                res = pm.delete_folder(item_id)
                if res and res.get('status') == 'success':
                    return True
                res2 = pm.delete_torrent(item_id)
                return bool(res2 and res2.get('status') == 'success')

        vfs = _load_vfs()
        p_vfs = _get_provider_vfs(vfs, provider)

        if item_type == 'folder':
            if item_id.startswith('vfs_'):
                # Collect this VFS folder and any nested VFS subfolders
                to_remove = [
                    fid for fid in list(p_vfs['folders'].keys())
                    if _is_descendant_folder(p_vfs, fid, item_id)
                ]
                if item_id not in to_remove:
                    to_remove.append(item_id)
                for fid in to_remove:
                    p_vfs['folders'].pop(fid, None)
                    p_vfs['renames'].pop(f"folder::{fid}", None)
                # Hide files that were moved into the deleted folder tree
                for fkey, mdata in list(p_vfs['file_moves'].items()):
                    if mdata.get('target_folder_id') in to_remove:
                        p_vfs['file_moves'].pop(fkey, None)
                        if fkey not in p_vfs['hidden_files']:
                            p_vfs['hidden_files'].append(fkey)
                # Delete torrents moved into the deleted folder tree
                for tid, dest in list(p_vfs['folder_moves'].items()):
                    if dest in to_remove:
                        p_vfs['folder_moves'].pop(tid, None)
                        try:
                            _delete_provider_torrent(provider, tid)
                        except Exception as e:
                            control.log(f"debrid_cloud delete torrent {tid} error: {e}", 'debug')
                        _cleanup_torrent_vfs(p_vfs, tid)
                return _save_vfs(vfs)
            else:
                res = _delete_provider_torrent(provider, item_id)
                _cleanup_torrent_vfs(p_vfs, item_id)
                _save_vfs(vfs)
                return bool(res)
        else:
            # Deleting an individual video file (in root or inside a folder)
            fkey = f"{item_id}::{file_ref}"
            if fkey not in p_vfs['hidden_files']:
                p_vfs['hidden_files'].append(fkey)
            p_vfs['file_moves'].pop(fkey, None)
            p_vfs['renames'].pop(f"file::{fkey}", None)
            _save_vfs(vfs)

            # Check if any visible video files remain for the underlying torrent; if none, delete torrent from provider too
            prefix = f"{item_id}::"
            has_moved_siblings = any(
                k.startswith(prefix) and k not in p_vfs['hidden_files']
                for k in p_vfs['file_moves']
            )
            remaining_in_torrent = [
                itm for itm in get_cloud_items(provider, item_id)
                if not itm.get('is_folder') and str(itm.get('id')) == item_id
            ]
            if not remaining_in_torrent and not has_moved_siblings:
                try:
                    _delete_provider_torrent(provider, item_id)
                    _cleanup_torrent_vfs(p_vfs, item_id)
                    _save_vfs(vfs)
                except Exception as e:
                    control.log(f"debrid_cloud delete torrent item {item_id} error: {e}", 'debug')
            return True

    except Exception as e:
        control.log(f"Error deleting {provider} cloud item {item_id}: {str(e)}", "error")
    return False


# ═══════════════════════════════════════════════════════════════════════════
#  Stream URL Resolution
# ═══════════════════════════════════════════════════════════════════════════

def resolve_stream_url(provider, item_id, file_ref):
    """Resolve direct unrestrict streaming URL from debrid cloud."""
    try:
        if provider == 'realdebrid':
            from resources.lib.debrid.real_debrid import RealDebrid
            res = RealDebrid().resolve_hoster(file_ref)
            if isinstance(res, str) and res:
                return res
            if res and isinstance(res, dict):
                return res.get('download')

        elif provider == 'premiumize':
            if file_ref and file_ref.startswith('http'):
                return file_ref
            from resources.lib.debrid.premiumize import Premiumize
            pm = Premiumize()
            details = pm.item_details(item_id)
            if isinstance(details, dict) and details.get('link'):
                return details.get('link')
            folder_res = pm.list_folder(item_id)
            content = folder_res.get('content', []) if isinstance(folder_res, dict) else (folder_res if isinstance(folder_res, list) else [])
            for item in content:
                if str(item.get('id')) == str(file_ref):
                    return item.get('link')

        elif provider == 'torbox':
            from resources.lib.debrid.torbox import TorBox
            return TorBox().request_dl_link(item_id, int(file_ref))

        elif provider == 'alldebrid':
            from resources.lib.debrid.all_debrid import AllDebrid
            res = AllDebrid().resolve_hoster(file_ref)
            if isinstance(res, str) and res:
                return res
            if res and isinstance(res, dict):
                return res.get('data', {}).get('link') or res.get('link')

    except Exception as e:
        control.log(f"Error resolving {provider} stream URL: {str(e)}", "error")

    return None


# ═══════════════════════════════════════════════════════════════════════════
#  Stalled Torrent Auto-Cleaner
# ═══════════════════════════════════════════════════════════════════════════

def find_stalled_torrents(provider):
    """
    Find incomplete, dead, or error torrents for a given debrid provider.
    Returns list of dicts: [{'id': str, 'title': str, 'status': str, 'progress': int/float}]
    """
    stalled = []
    try:
        if provider == 'realdebrid':
            from resources.lib.debrid.real_debrid import RealDebrid
            torrents = RealDebrid().list_torrents() or []
            for t in torrents:
                status = str(t.get('status', '')).lower()
                progress = t.get('progress', 0)
                # Stalled: explicit error/dead, or 0% progress stuck in file selection / conversion
                if status in ['magnet_error', 'error', 'virus', 'dead'] or (progress == 0 and status in ['waiting_files_selection', 'magnet_conversion']):
                    stalled.append({
                        'id': str(t.get('id', '')),
                        'title': t.get('filename') or 'Unknown Torrent',
                        'status': status,
                        'progress': progress
                    })

        elif provider == 'torbox':
            from resources.lib.debrid.torbox import TorBox
            torrents = TorBox().list_torrents() or []
            for t in torrents:
                state = str(t.get('download_state', '')).lower()
                progress = int(t.get('progress', 0) * 100) if isinstance(t.get('progress'), float) else t.get('progress', 0)
                if state in ['error', 'failed', 'stalled', 'upload_failed'] or (progress == 0 and state in ['paused', 'stalled']):
                    stalled.append({
                        'id': str(t.get('id', '')),
                        'title': t.get('name') or 'Unknown Torrent',
                        'status': state,
                        'progress': progress
                    })

        elif provider == 'premiumize':
            from resources.lib.debrid.premiumize import Premiumize
            transfers = Premiumize().transfer_list() or []
            for t in transfers:
                status = str(t.get('status', '')).lower()
                progress = int(t.get('progress', 0) * 100) if isinstance(t.get('progress'), float) else t.get('progress', 0)
                if status in ['error', 'deleted'] or (progress == 0 and status in ['waiting']):
                    stalled.append({
                        'id': str(t.get('id', '')),
                        'title': t.get('name') or t.get('src') or 'Unknown Transfer',
                        'status': status,
                        'progress': progress
                    })

        elif provider == 'alldebrid':
            from resources.lib.debrid.all_debrid import AllDebrid
            torrents = AllDebrid().list_torrents() or []
            for t in torrents:
                code = t.get('statusCode', 0)
                speed = t.get('downloadSpeed', 0)
                if code >= 5 or (code in [0, 1] and speed == 0 and t.get('downloaded', 0) == 0 and t.get('seeders', 0) == 0):
                    stalled.append({
                        'id': str(t.get('id', '')),
                        'title': t.get('filename') or 'Unknown Torrent',
                        'status': f"code {code}",
                        'progress': 0
                    })

    except Exception as e:
        control.log(f"Error checking stalled torrents for {provider}: {str(e)}", "error")

    return stalled


def purge_stalled_torrents(provider):
    """
    Find and delete stalled/dead torrents for a provider after user confirmation.
    Returns number of purged torrents.
    """
    stalled = find_stalled_torrents(provider)
    provider_name = provider.capitalize() if provider != 'realdebrid' else 'Real-Debrid'
    if not stalled:
        control.notify(control.ADDON_NAME, f"No stalled or error torrents found in {provider_name}", icon=control.ADDON_ICON)
        return 0

    preview_lines = [f"• {t['title'][:45]} ({t['status']})" for t in stalled[:4]]
    if len(stalled) > 4:
        preview_lines.append(f"...and {len(stalled) - 4} more")
    preview = "\n".join(preview_lines)

    msg = f"Found {len(stalled)} stalled/error torrent(s) in {provider_name}:\n\n{preview}\n\nDelete all {len(stalled)} item(s)?"
    confirmed = control.yesno_dialog(control.ADDON_NAME, msg)
    if not confirmed:
        return 0

    purged = 0
    vfs = _load_vfs()
    p_vfs = _get_provider_vfs(vfs, provider)

    for t in stalled:
        tid = t['id']
        success = False
        try:
            if provider == 'realdebrid':
                from resources.lib.debrid.real_debrid import RealDebrid
                success = RealDebrid().deleteTorrent(tid)
            elif provider == 'torbox':
                from resources.lib.debrid.torbox import TorBox
                success = TorBox().delete_torrent(tid)
            elif provider == 'premiumize':
                from resources.lib.debrid.premiumize import Premiumize
                res = Premiumize().delete_torrent(tid)
                success = bool(res and res.get('status') == 'success')
            elif provider == 'alldebrid':
                from resources.lib.debrid.all_debrid import AllDebrid
                success = AllDebrid().delete_magnet(tid)

            if success:
                purged += 1
                _cleanup_torrent_vfs(p_vfs, tid)
        except Exception as e:
            control.log(f"Error purging torrent {tid} from {provider}: {e}", "warning")

    if purged > 0:
        try:
            _save_vfs(vfs)
        except Exception as e:
            control.log(f"debrid_cloud save vfs purge error: {e}", 'debug')
        control.notify(control.ADDON_NAME, f"Purged {purged} stalled torrent(s) from {provider_name}", icon=control.ADDON_ICON)
    else:
        control.notify(control.ADDON_NAME, f"Failed to purge stalled torrents from {provider_name}", icon=control.ADDON_ICON)

    return purged

