# -*- coding: utf-8 -*-
"""otaku_service.sync - Offline Mappings, Correlated Metadata & Dub Index Sync."""

import hashlib
import os
import shutil
import threading
import time

import xbmc

from resources.lib.ui import client, control

MAPPINGS_XZ_URL = 'https://github.com/RPDevs-Builds/Otaku-Mapping-DB/releases/download/latest/anime_mappings.db.xz'
MAPPINGS_MANIFEST_URL = 'https://github.com/RPDevs-Builds/Otaku-Mapping-DB/releases/download/latest/manifest.json'
MAPPINGS_FALLBACK_URL = 'https://github.com/RPDevs-Builds/Otaku-Mapping-DB/releases/download/latest/anime_mappings.db'
METADATA_XZ_URL = 'https://github.com/RPDevs-Builds/Otaku-Mapping-DB/releases/download/latest/anime_metadata.db.xz'

_MAPPINGS_SYNC_LOCK = threading.Lock()


def _decompress_mappings_payload(raw_bytes, url=''):
    """Decompress .xz or .gz mappings payload if compressed, or return raw SQLite bytes."""
    if not raw_bytes:
        return b''
    import gzip
    import lzma
    if raw_bytes.startswith(b'\xfd7zXZ\x00') or str(url).lower().endswith('.xz'):
        return lzma.decompress(raw_bytes)
    if raw_bytes.startswith(b'\x1f\x8b') or str(url).lower().endswith('.gz'):
        return gzip.decompress(raw_bytes)
    return raw_bytes


def _fetch_mappings_manifest_sha256(file_key='raw'):
    """Fetch expected raw SHA-256 checksum from Otaku-Mapping-DB manifest.json if reachable."""
    try:
        resp = client.get(MAPPINGS_MANIFEST_URL, timeout=6)
        if resp and resp.status_code == 200:
            data = control.safe_json(resp, default={})
            raw_sha = ((data.get('files') or {}).get(file_key) or {}).get('sha256')
            if raw_sha and len(str(raw_sha).strip()) == 64:
                return str(raw_sha).strip().lower()
    except Exception:
        pass
    return None


def update_metadata_db(url=None, expected_sha256=None):
    """Download and verify optional correlated anime_metadata.db.xz into control.metadataDB."""
    target_url = url or METADATA_XZ_URL
    dest_path = getattr(control, 'metadataDB', None) or os.path.join(control.dataPath, 'anime_metadata.db')
    tmp_path = f"{dest_path}.candidate.tmp"
    etag_path = f"{dest_path}.etag"
    manifest_sha = expected_sha256 if url is not None else _fetch_mappings_manifest_sha256('metadata_raw')
    try:
        headers = {}
        if os.path.exists(dest_path) and os.path.exists(etag_path):
            try:
                with open(etag_path, 'r', encoding='utf-8') as ef:
                    saved_etag = ef.read().strip()
                if saved_etag:
                    headers['If-None-Match'] = saved_etag
            except OSError:
                pass
        response = client.get(target_url, headers=headers, timeout=25)
        if response and response.status_code == 304:
            return True
        if response and response.status_code == 200 and response.content:
            from resources.lib.ui import database
            raw_payload = _decompress_mappings_payload(response.content, target_url)
            if manifest_sha:
                actual_sha = hashlib.sha256(raw_payload).hexdigest().lower()
                if actual_sha != str(manifest_sha).strip().lower():
                    control.log(f"### Metadata DB SHA-256 mismatch: expected {manifest_sha}, got {actual_sha}", 'error')
                    return False
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(tmp_path, 'wb') as tf:
                tf.write(raw_payload)
            ok_check, reason = database.verify_sqlite_integrity(tmp_path, required_tables=('anime_metadata',))
            if not ok_check:
                control.log(f"### Candidate anime_metadata.db failed quick_check ({reason})", 'warning')
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                return False
            database.close_all_connections(dest_path)
            os.replace(tmp_path, dest_path)
            new_etag = response.headers.get('Etag') or response.headers.get('ETag', '') if hasattr(response, 'headers') and response.headers else ''
            if new_etag:
                try:
                    with open(etag_path, 'w', encoding='utf-8') as ef:
                        ef.write(str(new_etag).strip())
                except OSError:
                    pass
            control.log("### Metadata DB updated successfully")
            return True
    except Exception as e:
        control.log(f"### Failed to update Metadata DB: {e}", 'warning')
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
    return False


def update_mappings_db(url=None, expected_sha256=None):
    """Download, verify SHA-256 + PRAGMA quick_check, and atomically swap mappings.db with .bak rollback."""
    control.log("### Updating Mappings")
    from resources.lib.ui import database
    using_default = (url is None)
    target_url = url or MAPPINGS_XZ_URL
    dest_path = os.path.join(control.dataPath, 'mappings.db')
    bak_path = f"{dest_path}.bak"
    tmp_path = f"{dest_path}.candidate.tmp"
    headers = {}
    saved_etag = control.getSetting('mappings.etag')
    saved_mtime = control.getSetting('mappings.last_modified')
    if os.path.exists(dest_path):
        if saved_etag:
            headers['If-None-Match'] = saved_etag
        if saved_mtime:
            headers['If-Modified-Since'] = saved_mtime

    manifest_sha = expected_sha256
    if using_default and manifest_sha is None:
        manifest_sha = _fetch_mappings_manifest_sha256()

    candidate_urls = [target_url]
    if using_default and MAPPINGS_FALLBACK_URL not in candidate_urls:
        candidate_urls.append(MAPPINGS_FALLBACK_URL)

    for idx, fetch_url in enumerate(candidate_urls):
        try:
            response = client.get(fetch_url, headers=headers, timeout=20)
            if response and response.status_code == 304:
                control.log("### Mappings unchanged (304 Not Modified)")
                return True
            if response and response.status_code == 200 and response.content:
                raw_payload = _decompress_mappings_payload(response.content, fetch_url)
                sha_header = (
                    (manifest_sha if fetch_url == MAPPINGS_XZ_URL else expected_sha256)
                    or (response.headers.get('X-Checksum-Sha256') if hasattr(response, 'headers') and response.headers else None)
                )
                if sha_header:
                    actual_sha = hashlib.sha256(raw_payload).hexdigest().lower()
                    if actual_sha != str(sha_header).strip().lower():
                        control.log(f"### Mappings SHA-256 mismatch: expected {sha_header}, got {actual_sha}", 'error')
                        return False

                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                with open(tmp_path, 'wb') as tf:
                    tf.write(raw_payload)

                if raw_payload.startswith(b'SQLite format 3\x00') or os.path.exists(dest_path):
                    ok_check, reason = database.verify_sqlite_integrity(tmp_path, required_tables=())
                    if not ok_check:
                        control.log(f"### Candidate mappings.db failed quick_check ({reason}); keeping existing DB", 'warning')
                        try:
                            os.remove(tmp_path)
                        except OSError:
                            pass
                        if (not os.path.exists(dest_path) or not database.verify_sqlite_integrity(dest_path, required_tables=())[0]) and os.path.exists(bak_path):
                            shutil.copy2(bak_path, dest_path)
                        return False

                if os.path.exists(dest_path) and database.verify_sqlite_integrity(dest_path, required_tables=())[0]:
                    try:
                        shutil.copy2(dest_path, bak_path)
                    except OSError:
                        pass

                database.close_all_connections(dest_path)
                try:
                    with open(tmp_path, 'rb+') as tf_sync:
                        os.fsync(tf_sync.fileno())
                except OSError:
                    pass

                atomic_ok = False
                try:
                    os.replace(tmp_path, dest_path)
                    atomic_ok = os.path.exists(dest_path)
                except OSError:
                    atomic_ok = control.atomic_write_bytes(dest_path, raw_payload)
                    try:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    except OSError:
                        pass

                if atomic_ok:
                    database.close_all_connections(dest_path)
                    new_etag = response.headers.get('Etag') or response.headers.get('ETag', '')
                    new_mtime = response.headers.get('Last-Modified', '')
                    if new_etag:
                        control.setSetting('mappings.etag', new_etag)
                    if new_mtime:
                        control.setSetting('mappings.last_modified', new_mtime)
                    control.log("### Mappings updated successfully")
                    return True
                control.log("### Failed to save mappings atomically")
                if os.path.exists(bak_path) and not os.path.exists(dest_path):
                    shutil.copy2(bak_path, dest_path)
                return False
            control.log(f"### Failed to update mappings from {fetch_url}: HTTP {getattr(response, 'status_code', 'unknown')}")
        except Exception as e:
            control.log(f"### Failed to update mappings from {fetch_url}: {e}")
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
        if idx + 1 < len(candidate_urls):
            headers.pop('If-None-Match', None)
            headers.pop('If-Modified-Since', None)
    return False


def _maybe_sync_daily_mappings(interval_s=86_400):
    """Run daily ETag-checked mappings.db + anime_metadata.db sync while idle."""
    if control.abort_requested() or control.is_device_in_standby():
        return False
    try:
        if xbmc.Player().isPlayingVideo():
            return False
    except Exception:
        pass
    last_sync = control.getInt('update.time.30')
    if last_sync and time.time() <= last_sync + interval_s:
        return False
    if not _MAPPINGS_SYNC_LOCK.acquire(blocking=False):
        return False
    try:
        ok_map = update_mappings_db()
        ok_meta = update_metadata_db()
        if ok_map:
            control.setInt('update.time.30', int(time.time()))
        return bool(ok_map or ok_meta)
    finally:
        _MAPPINGS_SYNC_LOCK.release()


def _mappings_has_dub_data():
    """Return True if local read-only mappings.db already contains mal_dub_id rows."""
    try:
        mapping_path = getattr(control, 'mappingDB', None)
        if not mapping_path or not os.path.exists(mapping_path):
            return False
        from resources.lib.ui import database
        with database.SQL(mapping_path, is_readonly=True) as cur:
            row = cur.execute('SELECT 1 FROM anime WHERE mal_dub_id IS NOT NULL LIMIT 1').fetchone()
            return bool(row)
    except Exception:
        return False


def update_dub_json(force=False):
    """Fetch fallback dubInfo.json if mappings.db does not already supply mal_dub_id."""
    if not force and _mappings_has_dub_data():
        control.log("### Dub index served by mappings.db; skipping redundant dubInfo.json fetch")
        return
    control.log("### Updating Dub json")
    url = 'https://raw.githubusercontent.com/MAL-Dubs/MAL-Dubs/main/data/dubInfo.json'
    headers = {}
    saved_etag = control.getSetting('dub.etag')
    if os.path.exists(control.maldubFile) and saved_etag:
        headers['If-None-Match'] = saved_etag

    try:
        response = client.get(url, headers=headers, timeout=20)
        if response and response.status_code == 304:
            control.log("### Dubs unchanged (304 Not Modified)")
            return
        if response and response.status_code == 200:
            data = response.json()
            if isinstance(data, dict) and "dubbed" in data:
                mal_dub_list = data["dubbed"]
                mal_dub = {str(item): {'dub': True} for item in mal_dub_list}
                if control.atomic_write_json(control.maldubFile, mal_dub):
                    new_etag = response.headers.get('Etag') or response.headers.get('ETag', '')
                    if new_etag:
                        control.setSetting('dub.etag', new_etag)
                    control.log("### Dubs updated successfully")
                else:
                    control.log("### Failed to save Dubs atomically")
            else:
                control.log("### Failed to parse Dubs payload")
        else:
            control.log(f"### Failed to update Dubs: HTTP {getattr(response, 'status_code', 'unknown')}")
    except Exception as e:
        control.log(f"### Failed to update Dubs: {e}")
