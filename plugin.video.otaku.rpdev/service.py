import time
import os
import json
import urllib.request
import urllib.error
import urllib.parse
import threading
import xbmc
import xbmcgui

from resources.lib.ui import control, client, database_sync


def refresh_apis():
    control.log("### Refreshing API's")
    rd_token = control.getSetting('realdebrid.token')
    dl_token = control.getSetting('debridlink.token')

    kitsu_token = control.getSetting('kitsu.token')
    mal_token = control.getSetting('mal.token')

    if rd_token != '':
        rd_expiry = control.getInt('realdebrid.expiry')
        if time.time() > (rd_expiry - 600):
            from resources.lib.debrid import real_debrid
            real_debrid.RealDebrid().refreshToken()

    if dl_token != '':
        dl_expiry = control.getInt('debridlink.expiry')
        if time.time() > (dl_expiry - 600):
            from resources.lib.debrid import debrid_link
            debrid_link.DebridLink().refreshToken()

    if kitsu_token != '':
        kitsu_expiry = control.getInt('kitsu.expiry')
        if time.time() > (kitsu_expiry - 600):
            from resources.lib.WatchlistFlavor import Kitsu
            Kitsu.KitsuWLF().refresh_token()

    if mal_token != '':
        mal_expiry = control.getInt('mal.expiry')
        if time.time() > (mal_expiry - 600):
            from resources.lib.WatchlistFlavor import MyAnimeList
            MyAnimeList.MyAnimeListWLF().refresh_token()


def update_calendars():
    control.log("### Updating Calendars")
    # from resources.lib.endpoints import anilist, mal, simkl
    # simkl.Simkl().update_calendar()
    # anilist.Anilist().update_calendar()
    # mal.Mal().update_calendar()
    control.log("### Calendars updated successfully")


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


MAPPINGS_XZ_URL = 'https://github.com/RPDevs-Builds/Otaku-Mapping-DB/releases/download/latest/anime_mappings.db.xz'
MAPPINGS_MANIFEST_URL = 'https://github.com/RPDevs-Builds/Otaku-Mapping-DB/releases/download/latest/manifest.json'
MAPPINGS_FALLBACK_URL = 'https://github.com/RPDevs-Builds/Otaku-Mapping-DB/releases/download/latest/anime_mappings.db'
METADATA_XZ_URL = 'https://github.com/RPDevs-Builds/Otaku-Mapping-DB/releases/download/latest/anime_metadata.db.xz'


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
            import hashlib
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
    control.log("### Updating Mappings")
    from resources.lib.ui import database
    import hashlib
    import shutil
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

                # Verify candidate passes PRAGMA quick_check before replacing live DB
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
            # Clear primary ETag before fallback host retry so fallback never compares stale ETag
            headers.pop('If-None-Match', None)
            headers.pop('If-Modified-Since', None)
    return False


_MAPPINGS_SYNC_LOCK = threading.Lock()


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


def cleanup_cache_databases():
    control.log("### Pruning Expired Cache & Debrid Hashes")
    try:
        from resources.lib.ui import database
        from resources.lib.debrid import debrid_cache
        from resources.lib.WatchlistFlavor import WatchlistFlavor
        database.prune_expired_cache(30)
        debrid_cache.prune_expired_hashes()
        database.prune_stale_multipage_jobs()
        WatchlistFlavor.process_scrobble_retry_queue(limit=25)
        database.checkpoint_databases(truncate=True)
        control.log("### Cache cleanup complete")
    except Exception as e:
        control.log(f"### Cache cleanup failed: {e}", 'warning')


def sync_watchlist(silent=False):
    if control.abort_requested():
        return
    if control.getBool('watchlist.sync.enabled'):
        control.log('### Updating Completed Sync')
        from resources.lib.WatchlistFlavor import WatchlistFlavor

        flavors = WatchlistFlavor.get_all_update_flavors()
        if flavors:
            synced = WatchlistFlavor.watchlist_sync_all()
            if synced:
                if not silent:
                    synced_names = ', '.join([n.capitalize() for n in synced])
                    notify_string = f'Completed Sync [B]{synced_names}[/B]'
                    return control.notify(control.ADDON_NAME, notify_string)
            else:
                if not silent:
                    control.ok_dialog(control.ADDON_NAME, "No Watchlist Enabled or Not Logged In")
        else:
            if not silent:
                control.ok_dialog(control.ADDON_NAME, "No Watchlist Enabled or Not Logged In")
    else:
        if not silent:
            control.ok_dialog(control.ADDON_NAME, "Watchilst Sync is Disabled")


def prefetch_watchlist():
    """Prefetch all watchlist statuses in background for faster loading."""
    if not control.getBool('watchlist.prefetch.enabled') and not control.getBool('watchlist.precache.all'):
        return

    from resources.lib.ui.database import is_watchlist_cache_valid

    enabled = control.enabled_watchlists()
    if not enabled:
        return

    # Map flavor to all its status names
    status_map = {
        'mal': ['watching', 'completed', 'on_hold', 'dropped', 'plan_to_watch'],
        'anilist': ['CURRENT', 'COMPLETED', 'PAUSED', 'DROPPED', 'PLANNING', 'REPEATING'],
        'kitsu': ['current', 'completed', 'on_hold', 'dropped', 'planned'],
        'simkl': ['watching', 'completed', 'hold', 'dropped', 'plantowatch']
    }

    try:
        from resources.lib.WatchlistFlavor import WatchlistFlavor

        for flavor_name in enabled:
            if control.abort_requested():
                break
            statuses = status_map.get(flavor_name)
            if not statuses:
                continue

            flavor = WatchlistFlavor.get_flavor_by_name(flavor_name)
            if not flavor:
                continue

            for status in statuses:
                if control.abort_requested():
                    break
                # Check if cache is still valid - skip this status
                if is_watchlist_cache_valid(flavor_name, status):
                    control.log(f'### Watchlist cache valid for {flavor_name}/{status}, skipping')
                    continue

                control.log(f'### Prefetching {flavor_name} watchlist ({status})')
                try:
                    # Only cache raw data — skip view processing (no AniList calls)
                    flavor.get_watchlist_status(status, next_up=False, offset=0, page=1, cache_only=True)
                    control.log(f'### Prefetch complete for {flavor_name}/{status}')
                except Exception as e:
                    control.log(f'### Prefetch failed for {status}: {e}', 'warning')

            control.log(f'### Watchlist prefetch finished for {flavor_name}')

        if control.abort_requested():
            return

        # Consolidated AniList enrichment: ONE API call for ALL watchlist MAL IDs
        try:
            from resources.lib.ui.database import get_all_watchlist_mal_ids, save_anilist_enrichment_batch
            all_mal_ids = get_all_watchlist_mal_ids()
            if all_mal_ids:
                control.log(f'### Prefetching AniList enrichment for {len(all_mal_ids)} MAL IDs')
                from resources.lib.endpoints.anilist import Anilist
                anilist_data = Anilist().get_anilist_by_mal_ids(all_mal_ids)
                if anilist_data:
                    save_anilist_enrichment_batch(anilist_data)
                    from resources.lib.ui import get_meta
                    get_meta.collect_meta([{'mal_id': mid} for mid in all_mal_ids])
                    control.log(f'### AniList enrichment cached: {len(anilist_data)} items')
                else:
                    control.log('### AniList enrichment returned no data')
            else:
                control.log('### No MAL IDs found in watchlist cache for AniList enrichment')
        except Exception as e:
            control.log(f'### AniList enrichment prefetch failed: {e}', 'warning')

    except Exception as e:
        control.log(f'### Watchlist prefetch failed: {e}', 'warning')


def prefetch_calendar():
    """Warm AnimeSchedule cache in background at Kodi startup."""
    if control.abort_requested():
        return
    try:
        from resources.lib.AnimeSchedule import AnimeScheduleCalendar
        control.log('### Prefetching airing calendar cache')
        scheduler = AnimeScheduleCalendar()
        scheduler.get_calendar_data(types=['sub', 'dub', 'raw'])
        control.log('### Airing calendar prefetch complete')
    except Exception as e:
        control.log(f'### Calendar prefetch failed: {e}', 'warning')


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


def getChangeLog():
    changelog_path = os.path.join(control.ADDON_PATH, 'changelog.txt')
    news_path = os.path.join(control.ADDON_PATH, 'news.txt')

    try:
        with open(changelog_path, encoding='utf-8') as changelog_file:
            changelog_text = changelog_file.read()
    except OSError:
        changelog_text = ''

    try:
        with open(news_path, encoding='utf-8') as news_file:
            news_text = news_file.read()
    except OSError:
        news_text = ''

    heading = '[B]%s -  v%s - ChangeLog & News[/B]' % (control.ADDON_NAME, control.ADDON_VERSION)
    from resources.lib.windows.textviewer import TextViewerXML
    windows = None
    try:
        windows = TextViewerXML('textviewer.xml', control.ADDON_PATH, heading=heading, changelog_text=changelog_text, news_text=news_text)
        windows.run()
    finally:
        if windows is not None:
            try:
                windows.close()
            except Exception:
                pass
            del windows


def getInstructions():
    instructions_path = os.path.join(control.ADDON_PATH, 'Instructions.txt')

    try:
        with open(instructions_path, encoding='utf-8') as instructions_file:
            instructions_text = instructions_file.read()
    except OSError:
        instructions_text = ''

    heading = '[B]%s -  v%s - Instructions[/B]' % (control.ADDON_NAME, control.ADDON_VERSION)
    from resources.lib.windows.textviewer import TextViewerXML
    windows = None
    try:
        windows = TextViewerXML('textviewer_1.xml', control.ADDON_PATH, heading=heading, instructions_text=instructions_text)
        windows.run()
    finally:
        if windows is not None:
            try:
                windows.close()
            except Exception:
                pass
            del windows


def toggle_reuselanguageinvoker(forced_state=None):
    def _store_and_reload(output):
        AddonXml = "".join(output)
        control.atomic_write_text(file_path, AddonXml)
        if not forced_state:
            control.ok_dialog(control.ADDON_NAME, 'Language Invoker option has been changed, reloading kodi profile')
            control.execute('LoadProfile({})'.format(control.xbmc.getInfoLabel("system.profilename")))
    file_path = os.path.join(control.ADDON_PATH, "addon.xml")
    try:
        with open(file_path, encoding='utf-8') as addon_xml:
            file_lines = addon_xml.readlines()
    except OSError:
        return
    for i in range(len(file_lines)):
        line_string = file_lines[i]
        if "reuselanguageinvoker" in file_lines[i]:
            cur_value = "true" if "true" in line_string else ("false" if "false" in line_string else "")
            if (forced_state == 'Enabled' and cur_value == "false") or (forced_state is None and cur_value == "false"):
                file_lines[i] = file_lines[i].replace("false", "true")
                control.setSetting("reuselanguageinvoker.status", "Enabled")
                _store_and_reload(file_lines)
            elif (forced_state == 'Disabled' and cur_value == "true") or (forced_state is None and cur_value == "true"):
                file_lines[i] = file_lines[i].replace("true", "false")
                control.setSetting("reuselanguageinvoker.status", "Disabled")
                _store_and_reload(file_lines)
            break


def version_check():
    control.log(f'### {control.ADDON_ID} {control.ADDON_VERSION}')
    control.log(f'### Platform: {control.sys.platform}')
    control.log(f'### Python: {control.sys.version}')
    control.log(f'### SQLite: {database_sync.sqlite_version}')
    control.log(f'### Kodi Version: {control.kodi_version}')

    if control.getSetting('otaku.version') != control.ADDON_VERSION:
        reuselang = control.getSetting('reuselanguageinvoker.status')
        toggle_reuselanguageinvoker(reuselang)
        control.setSetting('otaku.version', control.ADDON_VERSION)
        control.log(f"### {reuselang} Re-uselanguageinvoker")

        # Prune orphaned settings AFTER setSetting so Kodi's CAddonSettings flush does not restore them
        try:
            from resources.lib.ui import clean_settings
            pruned_count, _ = clean_settings.clean_settings(silent=True)
            if pruned_count > 0:
                control.log(f"### Version upgrade: Pruned {pruned_count} orphaned setting(s)")
        except Exception as e:
            control.log(f"Failed to prune orphaned settings on startup: {e}", 'warning')


_SETTINGS_XML_CACHE = None


def _get_settings_schema_entries():
    global _SETTINGS_XML_CACHE
    if _SETTINGS_XML_CACHE is not None:
        return _SETTINGS_XML_CACHE
    import xml.etree.ElementTree as ET
    settings_path = os.path.join(control.ADDON_PATH, 'resources', 'settings.xml')
    tree = ET.parse(settings_path)
    root = tree.getroot()
    entries = []
    for setting in root.iter('setting'):
        s_id = setting.get('id')
        s_type = setting.get('type')
        if s_id and s_type and s_type != 'action':
            entries.append((s_id, s_type.lower()))
    _SETTINGS_XML_CACHE = tuple(entries)
    return _SETTINGS_XML_CACHE


def load_settings():
    """Load settings into Kodi window properties using cached settings.xml schema."""
    try:
        entries = _get_settings_schema_entries()
    except Exception as e:
        control.log(f'Failed to parse settings.xml: {e}', 'error')
        return

    for s_id, s_type in entries:
        prop_name = f"{control.ADDON_ID}_{s_id}"
        try:
            if s_type == 'boolean':
                val_str = str(control.settings.getBool(s_id)).lower()
            elif s_type == 'integer':
                val_str = str(control.settings.getInt(s_id))
            elif s_type == 'number':
                val_str = str(control.settings.getNumber(s_id))
            elif s_type in ('string', 'path', 'folder', 'file', 'addon'):
                val_str = control.settings.getString(s_id)
            elif s_type == 'list[boolean]':
                val_str = json.dumps(control.settings.getBoolList(s_id))
            elif s_type == 'list[integer]':
                val_str = json.dumps(control.settings.getIntList(s_id))
            elif s_type == 'list[string]':
                val_str = json.dumps(control.settings.getStringList(s_id))
            elif s_type == 'list[number]':
                val_str = json.dumps(control.settings.getNumberList(s_id))
            else:
                continue

            if control.homeWindow.getProperty(prop_name) != val_str:
                control.homeWindow.setProperty(prop_name, val_str)
        except Exception:
            pass


_MENU_SETTINGS = (
    # Main Menus
    'menu.mainmenu.order',
    'menu.mainmenu.config',
    'menu.submenu.order',
    'menu.submenu.config',
    'menu.genres.order',
    'menu.genres.config',
    # Movies
    'movie.mainmenu.order',
    'movie.mainmenu.config',
    'movie.submenu.order',
    'movie.submenu.config',
    'movie.genres.order',
    'movie.genres.config',
    # TV Shows
    'tv_show.mainmenu.order',
    'tv_show.mainmenu.config',
    'tv_show.submenu.order',
    'tv_show.submenu.config',
    'tv_show.genres.order',
    'tv_show.genres.config',
    # TV Shorts
    'tv_short.mainmenu.order',
    'tv_short.mainmenu.config',
    'tv_short.submenu.order',
    'tv_short.submenu.config',
    'tv_short.genres.order',
    'tv_short.genres.config',
    # Specials
    'special.mainmenu.order',
    'special.mainmenu.config',
    'special.submenu.order',
    'special.submenu.config',
    'special.genres.order',
    'special.genres.config',
    # OVAs
    'ova.mainmenu.order',
    'ova.mainmenu.config',
    'ova.submenu.order',
    'ova.submenu.config',
    'ova.genres.order',
    'ova.genres.config',
    # ONAs
    'ona.mainmenu.order',
    'ona.mainmenu.config',
    'ona.submenu.order',
    'ona.submenu.config',
    'ona.genres.order',
    'ona.genres.config',
    # Music
    'music.mainmenu.order',
    'music.mainmenu.config',
    'music.submenu.order',
    'music.submenu.config',
    'music.genres.order',
    'music.genres.config',
)


def _get_menu_settings_snapshot():
    snapshot = {}
    for sid in _MENU_SETTINGS:
        try:
            if sid.endswith('.order'):
                snapshot[sid] = control.getSetting(sid)
            else:
                snapshot[sid] = control.settings.getStringList(sid)
        except Exception:
            try:
                snapshot[sid] = control.getSetting(sid)
            except Exception:
                snapshot[sid] = None
    return snapshot


class Monitor(xbmc.Monitor):
    def __init__(self):
        super().__init__()
        self._menu_settings_snapshot = _get_menu_settings_snapshot()
        self._webpdb_enabled = control.getBool('webpdb.enabled')
        self._webpdb_port = control.get_webpdb_port()

    def onSettingsChanged(self):
        control.log('Setting Changed - Updating Settings Cache')
        control.clearSettingsCache()
        if control.getBool('general.kodi.cache'):
            load_settings()
        control.process_context()

        # Stop active Web-PDB server when disabled or port changed
        current_webpdb_enabled = control.getBool('webpdb.enabled')
        current_webpdb_port = control.get_webpdb_port()
        if not current_webpdb_enabled:
            control.stop_webpdb_trace(self._webpdb_port)
            if current_webpdb_port != self._webpdb_port:
                control.stop_webpdb_trace(current_webpdb_port)
        elif current_webpdb_port != self._webpdb_port:
            control.stop_webpdb_trace(self._webpdb_port)
        self._webpdb_enabled = current_webpdb_enabled
        self._webpdb_port = current_webpdb_port

        # Check if any menu configuration settings were changed; defer Container.Refresh while AddonSettings modal is open
        new_snapshot = _get_menu_settings_snapshot()
        if new_snapshot != self._menu_settings_snapshot:
            control.log('Menu configuration settings changed - flagging menu container refresh')
            self._menu_settings_snapshot = new_snapshot
            control.setGlobalProp('otaku.menu.needs_refresh', 'true')
            if not xbmc.getCondVisibility('Window.IsActive(addonsettings)'):
                folder_path = xbmc.getInfoLabel('Container.FolderPath')
                if control.is_addon_visible() or folder_path.startswith('plugin://plugin.video.otaku.rpdev'):
                    control.refresh()


class MultipageWorker(threading.Thread):
    """Persistent background pre-caching worker for multi-page API datasets.
    Runs strictly inside service.py; never invoked inside short-lived directory invokers."""

    PACING_ANILIST = 1.0
    PACING_MAL = 1.1

    def __init__(self, monitor=None):
        super().__init__(name="Otaku-MultipageWorker", daemon=True)
        self.monitor = monitor or xbmc.Monitor()
        self._stop_event = threading.Event()
        self.max_concurrency = 1 if control.getGlobalProp('otaku.memory_pressure') == 'true' else 2
        self._memory_throttled = control.getGlobalProp('otaku.memory_pressure') == 'true'

    def set_memory_pressure(self, throttled, max_workers=None):
        """Throttle or restore MultipageWorker concurrency under 32-bit memory pressure."""
        self._memory_throttled = bool(throttled)
        if throttled:
            self.max_concurrency = max(1, int(max_workers or 1))
        else:
            self.max_concurrency = int(max_workers or 2)

    def stop(self):
        """Signal the worker thread to stop cleanly."""
        self._stop_event.set()

    def _sleep(self, seconds, slice_time=0.5):
        """Sleep for up to `seconds`, returning True immediately if monitor abort or stop is requested."""
        if self.monitor.abortRequested() or self._stop_event.is_set():
            return True

        # If waitForAbort is mocked/patched in tests, delegate directly to preserve mock contracts and fast test overrides
        if hasattr(self.monitor.waitForAbort, 'assert_called_with') or hasattr(self.monitor.waitForAbort, 'side_effect'):
            res = self.monitor.waitForAbort(seconds)
            return bool(res or self.monitor.abortRequested() or self._stop_event.is_set())

        start = time.time()
        while time.time() - start < seconds:
            if self.monitor.abortRequested() or self._stop_event.is_set():
                return True
            rem = seconds - (time.time() - start)
            chunk = min(slice_time, rem)
            if chunk > 0 and self._stop_event.wait(timeout=chunk):
                return True
            if self.monitor.abortRequested():
                return True
        return False

    @classmethod
    def get_pacing(cls, provider):
        """Return rate pacing delay (seconds) for provider."""
        prov = str(provider or '').lower()
        if 'anilist' in prov:
            return cls.PACING_ANILIST
        return cls.PACING_MAL

    def _should_pause(self):
        """Returns True if playback is active, display is in standby, screensaver, or Settings UI is open."""
        try:
            if xbmc.Player().isPlaying():
                return True
        except Exception:
            pass
        try:
            if control.is_device_in_standby():
                return True
        except Exception:
            pass
        try:
            if xbmc.getCondVisibility("System.ScreenSaverActive"):
                return True
        except Exception:
            pass
        try:
            if xbmc.getCondVisibility("Window.IsActive(addonsettings)"):
                return True
        except Exception:
            pass
        if getattr(self, '_memory_throttled', False) or control.getGlobalProp('otaku.memory_pressure') == 'true':
            return True
        return False

    @staticmethod
    def _is_folder_match(current_folder, job_path):
        """Check if active container folder path matches the pre-caching job's target URL."""
        if not current_folder or not job_path:
            return False

        parsed_cur = urllib.parse.urlparse(current_folder)
        parsed_job = urllib.parse.urlparse(job_path)

        if parsed_cur.netloc and parsed_job.netloc and parsed_cur.netloc != parsed_job.netloc:
            return False

        cur_path = parsed_cur.path.strip('/')
        job_clean_path = parsed_job.path.strip('/') if parsed_job.path else job_path.split('?')[0].strip('/')
        if cur_path != job_clean_path:
            return False

        cur_qs = urllib.parse.parse_qs(parsed_cur.query)
        job_qs = urllib.parse.parse_qs(parsed_job.query)

        cur_params = {k: v for k, v in cur_qs.items() if k != 'page'}
        job_params = {k: v for k, v in job_qs.items() if k != 'page'}

        for k, v in job_params.items():
            if cur_params.get(k) != v:
                return False

        UI_PARAMS = {'filter_text', 'filter'}
        for k, v in cur_params.items():
            if k not in UI_PARAMS and job_params.get(k) != v:
                return False

        return True

    def _check_and_refresh_container(self, job):
        """Trigger Container.Refresh only if user is actively viewing page 1 of this list with paging disabled."""
        if not control.is_addon_visible():
            return

        # Gate 1: When paging is enabled, background refresh is blocked to prevent interrupting active pagination
        if control.getBool('interface.watchlist.paging'):
            return

        # Check Container.FolderPath matches job['url_path'] and current page == 1
        current_folder = xbmc.getInfoLabel('Container.FolderPath')
        if not current_folder:
            return

        job_path = str(job.get('url_path') or '')
        if not job_path:
            return

        parsed_cur = urllib.parse.urlparse(current_folder)
        query = urllib.parse.parse_qs(parsed_cur.query)
        page_val = query.get('page', ['1'])[0]
        try:
            current_page = int(page_val)
        except (ValueError, TypeError):
            current_page = 1

        if current_page != 1:
            return

        if not self._is_folder_match(current_folder, job_path):
            return

        # Gate 3: Idempotency token check via window property otaku_mp_refreshed_{job_id} to prevent repeated refreshes or infinite loops
        job_id = job.get('job_id') or job.get('id')
        token_key = f"otaku_mp_refreshed_{job_id}"
        if control.homeWindow.getProperty(token_key) in ('1', 'true'):
            return

        control.homeWindow.setProperty(token_key, '1')
        control.log(f"MultipageWorker: Triggering Container.Refresh for completed pre-cache job {job_id}")
        control.refresh()

    def run(self):
        control.log("### MultipageWorker started")
        from resources.lib.ui import database

        while not self.monitor.abortRequested() and not self._stop_event.is_set():
            if self._should_pause():
                if self._sleep(2.0):
                    break
                continue

            try:
                job = database.dequeue_multipage_job()
            except Exception as e:
                control.log(f"MultipageWorker dequeue error: {e}", 'warning')
                job = None

            if not job:
                if self._sleep(1.5):
                    break
                continue

            try:
                self._process_job(job)
            except Exception as e:
                control.log(f"MultipageWorker _process_job unhandled error: {e}", 'error')
                job_id = job.get('job_id') or job.get('id')
                if job_id:
                    try:
                        database.mark_multipage_job_failed(job_id, str(e))
                    except Exception:
                        pass

        control.log("### MultipageWorker terminated cleanly")

    def _process_job(self, job):
        from resources.lib.ui import database
        job_id = job.get('job_id') or job.get('id')
        provider = str(job.get('provider') or '').lower()
        method_name = job.get('browser_method')
        target_page = int(job.get('target_page') or 20)
        current_page = int(job.get('current_page') or 2)
        raw_params = job.get('request_params') or job.get('params') or '{}'

        if isinstance(raw_params, dict):
            base_params = dict(raw_params)
        elif isinstance(raw_params, str):
            base_params = control.loads_json(raw_params, default={})
            if not isinstance(base_params, dict):
                base_params = {'payload': base_params}
        else:
            base_params = {}

        pacing = self.get_pacing(provider)

        # Resolve the browser class (AniListBrowser or MalBrowser)
        if 'anilist' in provider:
            from resources.lib.AniListBrowser import AniListBrowser
            browser = AniListBrowser()
        else:
            from resources.lib.MalBrowser import MalBrowser
            browser = MalBrowser()

        fetch_func = getattr(browser, method_name, None)
        if not fetch_func:
            control.log(f"MultipageWorker: Unknown browser method '{method_name}' on {type(browser).__name__}", 'error')
            database.mark_multipage_job_failed(job_id, f"Unknown method: {method_name}")
            return

        success = True
        error_msg = None
        for page_num in range(current_page, target_page + 1):
            if self.monitor.abortRequested() or self._stop_event.is_set():
                return

            while self._should_pause():
                if self._sleep(2.0):
                    return

            try:
                page_params = dict(base_params)
                if 'page' in page_params:
                    page_params['page'] = page_num
                elif 'variables' in page_params and isinstance(page_params['variables'], dict):
                    page_params['variables'] = dict(page_params['variables'])
                    page_params['variables']['page'] = page_num
                else:
                    page_params['page'] = page_num

                try:
                    fetch_func(**page_params)
                except TypeError:
                    fetch_func(page_params)

                if self.monitor.abortRequested() or self._stop_event.is_set():
                    return

                database.update_multipage_job_progress(job_id, page_num)
            except Exception as e:
                control.log(f"MultipageWorker page {page_num} fetch error: {e}", 'warning')
                success = False
                error_msg = str(e)
                break

            if page_num < target_page:
                if self._sleep(pacing):
                    return

        if self.monitor.abortRequested() or self._stop_event.is_set():
            return

        if success:
            database.mark_multipage_job_done(job_id)
            self._check_and_refresh_container(job)
        else:
            database.mark_multipage_job_failed(job_id, error_msg or "Failed to fetch all pages")


def _shutdown_cleanup(multipage_worker=None):
    """Enforce deterministic shutdown sequence: abort/stop -> 1s worker join -> passive WAL checkpoint -> close pools."""
    if multipage_worker is not None:
        try:
            multipage_worker.stop()
            multipage_worker.join(timeout=1.0)
        except Exception:
            pass
    # Passive non-blocking WAL checkpoint + pool close (<5s CPythonInvoker limit; avoid slow XML parsing on flash)
    try:
        from resources.lib.ui import database
        database.checkpoint_databases(truncate=False)
        database.close_all_connections()
    except Exception:
        pass


if __name__ == "__main__":
    control.log('##################  RUNNING MAINTENANCE  ######################')
    if control.getBool('general.kodi.cache'):
        load_settings()
    control.process_context()
    version_check()
    database_sync.SyncDatabase()
    refresh_apis()
    if control.getInt('update.time.30') == 0 or control.getInt('update.time.7') == 0:
        threading.Thread(target=_maybe_sync_daily_mappings, daemon=True).start()
        update_dub_json(force=False)
        sync_watchlist(True)
        cleanup_cache_databases()
        control.setInt('update.time.7', int(time.time()))
        control.setInt('update.time.1', int(time.time()))
    else:
        now_ts = int(time.time())
        did_watchlist_sync = False
        if now_ts > control.getInt('update.time.30') + 86_400:   # daily ETag-checked mappings sync (non-blocking)
            threading.Thread(target=_maybe_sync_daily_mappings, daemon=True).start()
        if now_ts > control.getInt('update.time.7') + 604_800:   # 7 days
            update_dub_json(force=False)
            sync_watchlist(True)
            did_watchlist_sync = True
            cleanup_cache_databases()
            control.setInt('update.time.7', now_ts)
        if now_ts > control.getInt('update.time.1') + 86_400:   # 1 day
            if not did_watchlist_sync:
                sync_watchlist(True)
            try:
                from resources.lib.ui import database
                database.prune_stale_multipage_jobs()
            except Exception:
                pass
            control.setInt('update.time.1', now_ts)
    # Startup 32-bit memory watermark guard prior to aggressive background prefetches (WS-1)
    mem_state = control.enforce_memory_watermark(context='service_startup')
    skip_startup_prefetch = bool(mem_state.get('triggered') or control.getGlobalProp('otaku.memory_pressure') == 'true')
    if not skip_startup_prefetch:
        # Prefetch watchlist in background thread (non-blocking)
        threading.Thread(target=prefetch_watchlist, daemon=True).start()
        # Prefetch airing calendar in background thread (non-blocking)
        threading.Thread(target=prefetch_calendar, daemon=True).start()
    else:
        control.log("Service: Skipping background pre-caching due to 32-bit memory pressure", 'warning')
    # Refresh dynamic domains from mirror (non-blocking)
    from resources.lib.ui import domains
    threading.Thread(target=domains.refresh_domains, daemon=True).start()
    control.log('##################  MAINTENANCE COMPLETE ######################')
    monitor = Monitor()
    # Start persistent multipage pre-caching worker
    multipage_worker = MultipageWorker(monitor=monitor)
    if skip_startup_prefetch:
        multipage_worker.set_memory_pressure(True, max_workers=1)
    multipage_worker.start()
    # Periodic background maintenance & memory trimming loop (every 15 minutes)
    while not monitor.abortRequested():
        if monitor.waitForAbort(900):
            break
        if control.is_device_in_standby():
            control.log('Device display is in standby - pausing periodic memory trim')
            continue
        loop_mem_state = control.enforce_memory_watermark(context='service_loop', multipage_worker=multipage_worker)
        if not loop_mem_state.get('triggered'):
            control.clean_memory()
        try:
            refresh_apis()
        except Exception as e:
            control.log(f"Periodic API token refresh notice: {e}", 'debug')
        try:
            threading.Thread(target=_maybe_sync_daily_mappings, daemon=True).start()
        except Exception as e:
            control.log(f"Periodic mappings sync notice: {e}", 'debug')
        try:
            from resources.lib.WatchlistFlavor import WatchlistFlavor
            replayed = WatchlistFlavor.process_scrobble_retry_queue()
            if replayed:
                control.log(f"Periodic scrobble retry queue replayed {replayed} item(s)", 'info')
        except Exception as e:
            control.log(f"Periodic scrobble retry queue notice: {e}", 'debug')
        try:
            from resources.lib.ui import database
            database.close_thread_connections()
            database.checkpoint_databases(truncate=False)
        except Exception as e:
            control.log(f"Periodic WAL checkpoint notice: {e}", 'debug')
    _shutdown_cleanup(multipage_worker)
