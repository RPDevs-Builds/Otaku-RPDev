# -*- coding: utf-8 -*-
import os
import time
import xml.etree.ElementTree as ET

from resources.lib import MetaBrowser
from resources.lib.ui import control, database, domains, utils
from resources.lib.ui.router import Route


@Route('tools')
def TOOLS_MENU(payload, params):
    from resources.lib import Main
    TOOLS_ITEMS = Main.get_menu_items('tools')

    view_type = 'addons' if control.getBool('interface.content_type') else ''
    control.draw_items([utils.allocate_item(name, url, (url == 'my_cloud'), False, [], image, info) for name, url, image, info in TOOLS_ITEMS], view_type)


@Route('source_filter')
def SOURCE_FILTER(payload, params):
    """Open the filter selection dialog"""
    from resources.lib.windows.filter_select import FilterSelect
    window = None
    try:
        window = FilterSelect("filter_select.xml", control.ADDON_PATH)
        window.doModal()
    finally:
        if window:
            del window


@Route('delete_anime_database/*')
def DELETE_ANIME_DATABASE(payload, params):
    from resources.lib import Main
    mal_id = Main._extract_mal_id(payload)
    database.remove_from_database('shows', mal_id)
    database.remove_from_database('episodes', mal_id)
    database.remove_from_database('show_data', mal_id)
    database.remove_from_database('shows_meta', mal_id)
    control.notify(control.ADDON_NAME, 'Removed from database')
    control.exit_code()


@Route('auth/*')
def AUTH(payload, params):
    if payload == 'realdebrid':
        from resources.lib.debrid.real_debrid import RealDebrid
        RealDebrid().auth()
    elif payload == 'alldebrid':
        from resources.lib.debrid.all_debrid import AllDebrid
        AllDebrid().auth()
    elif payload == 'premiumize':
        from resources.lib.debrid.premiumize import Premiumize
        Premiumize().auth()
    elif payload == 'debridlink':
        from resources.lib.debrid.debrid_link import DebridLink
        DebridLink().auth()
    elif payload == 'torbox':
        from resources.lib.debrid.torbox import TorBox
        TorBox().auth()
    elif payload == 'easydebrid':
        from resources.lib.debrid.easydebrid import EasyDebrid
        EasyDebrid().auth()
    elif payload == 'easynews':
        from resources.lib.debrid.easynews import Easynews
        Easynews().auth()


@Route('refresh/*')
def REFRESH(payload, params):
    if payload == 'realdebrid':
        from resources.lib.debrid.real_debrid import RealDebrid
        RealDebrid().refreshToken()
    elif payload == 'debridlink':
        from resources.lib.debrid.debrid_link import DebridLink
        DebridLink().refreshToken()


def _extract_fanart_list(mal_id):
    if not mal_id:
        return []

    episode = database.get_episode(mal_id)
    if not episode:
        try:
            MetaBrowser.get_anime_init(mal_id)
            episode = database.get_episode(mal_id)
        except Exception:
            episode = None

    fanart = []
    if episode and episode.get('kodi_meta'):
        try:
            meta = database.loads(episode['kodi_meta'])
            img = meta.get('image') if isinstance(meta.get('image'), dict) else {}
            raw_fanart = img.get('fanart') or meta.get('fanart') or []
            if isinstance(raw_fanart, list):
                fanart = [f for f in raw_fanart if f and isinstance(f, str)]
            elif isinstance(raw_fanart, str) and raw_fanart:
                fanart = [raw_fanart]
        except Exception:
            pass

    if not fanart:
        show = database.get_show(mal_id)
        if show and show.get('kodi_meta'):
            try:
                meta = database.loads(show['kodi_meta'])
                img = meta.get('image') if isinstance(meta.get('image'), dict) else {}
                raw_fanart = img.get('fanart') or meta.get('fanart') or []
                if isinstance(raw_fanart, list):
                    fanart = [f for f in raw_fanart if f and isinstance(f, str)]
                elif isinstance(raw_fanart, str) and raw_fanart:
                    fanart = [raw_fanart]
            except Exception:
                pass

    return fanart


@Route('fanart_select/*')
def FANART_SELECT(payload, params):
    from resources.lib import Main
    mal_id = Main._extract_mal_id(payload)
    if not mal_id:
        return control.exit_code()
    fanart = _extract_fanart_list(mal_id)
    fanart_display = fanart + ["None", "Random (Default)"]
    control.draw_items([utils.allocate_item(f, f'fanart/{mal_id}/{i}', False, False, [], f, {}, fanart=f, landscape=f) for i, f in enumerate(fanart_display)], '')


@Route('fanart/*')
def FANART(payload: str, params: dict):
    parts = [p for p in payload.strip('/').split('/') if p]
    mal_id = parts[0] if parts else ''
    select = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    fanart = _extract_fanart_list(mal_id)
    fanart_display = fanart + ["None", "Random"]
    fanart_choices = fanart + ["None", ""]

    if select >= len(fanart_choices):
        return control.exit_code()

    fanart_url = fanart_choices[select]
    display_label = fanart_display[select]

    # Set fanart selection using string lists
    mal_ids = control.getStringList('fanart.mal_ids')
    fanart_selections = control.getStringList('fanart.selections')
    mal_id_str = str(mal_id)

    try:
        # Update existing entry
        index = mal_ids.index(mal_id_str)
        fanart_selections[index] = fanart_url
    except ValueError:
        # Add new entry
        mal_ids.append(mal_id_str)
        fanart_selections.append(fanart_url)

    control.setStringList('fanart.mal_ids', mal_ids)
    control.setStringList('fanart.selections', fanart_selections)
    control.ok_dialog(control.ADDON_NAME, f"Fanart Set to {display_label}")


# ### Maintenance ###
@Route('settings')
def SETTINGS(payload, params):
    control.ADDON.openSettings()
    control.clearSettingsCache()


@Route('change_log')
def CHANGE_LOG(payload, params):
    control.setSetting('changelog.version', control.ADDON_VERSION)
    control.setSetting('version', control.ADDON_VERSION)
    control.setSetting('otaku.version', control.ADDON_VERSION)
    import service
    service.getChangeLog()


@Route('solver_inst')
def SOLVER_INST(payload, params):
    import service
    service.getInstructions()


@Route('clear_cache')
def CLEAR_CACHE(payload, params):
    choice = params.get('select') if params else None
    if not choice:
        try:
            from resources.lib.windows.clear_cache import show_clear_cache_dialog
            choice = show_clear_cache_dialog()
        except Exception as e:
            control.log(f"Error displaying clear cache dialog: {e}", 'error')
            choice = 'cancel'

    if choice == 'providers':
        control.setSetting('last_played_source', str(None))
        database.cache_clear_providers()
    elif choice == 'all':
        control.setSetting('last_played_source', str(None))
        database.cache_clear()
    else:
        control.log("Clear cache cancelled by user", 'debug')


@Route('clear_scrapers_cache')
def CLEAR_SCRAPERS_CACHE(payload, params):
    control.setSetting('last_played_source', str(None))
    database.cache_clear_providers()


@Route('clear_debrid_cache')
def CLEAR_DEBRID_CACHE(payload, params):
    from resources.lib.debrid import debrid_cache
    debrid_cache.clear_debrid_cache()
    control.notify(
        f'{control.ADDON_NAME}: Debrid Cache',
        'Debrid cache successfully cleared', time=5000, sound=False)


@Route('clear_metadata_cache')
def CLEAR_METADATA_CACHE(payload, params):
    database.cache_clear_metadata()


@Route('refresh_hianime_domains')
def REFRESH_HIANIME_DOMAINS(payload, params):
    success, mirrors = domains.refresh_hianime_domains(force=True)
    if success:
        control.notify(
            f'{control.ADDON_NAME}: HiAnime Domains',
            f'Updated {len(mirrors)} mirror(s) from hianime.pw',
            time=5000, sound=False
        )
    else:
        control.notify(
            f'{control.ADDON_NAME}: HiAnime Domains',
            'Failed to update domains from hianime.pw',
            time=5000, sound=False
        )


@Route('clear_selected_fanart')
def CLEAR_SELECTED_FANART(payload, params):
    silent = False

    if not silent:
        confirm = control.yesno_dialog(control.ADDON_NAME, control.lang(30089))
    if confirm == 0:
        return

    # Clear all fanart selections using string lists
    control.setStringList('fanart.mal_ids', [])
    control.setStringList('fanart.selections', [])
    if not silent:
        control.notify(f'{control.ADDON_NAME}: Fanart', 'Fanart Successfully Cleared', sound=False)


@Route('rebuild_database')
def REBUILD_DATABASE(payload, params):
    from resources.lib.ui.database_sync import SyncDatabase
    SyncDatabase().re_build_database()


@Route('database_stats')
def DATABASE_STATS(payload, params):
    stats = database.get_database_stats()
    control.textviewer_dialog('Otaku Database & Storage Telemetry', stats)


@Route('scraper_stats')
def SCRAPER_STATS(payload, params):
    report = database.get_scraper_metrics_report()
    control.textviewer_dialog('Otaku Scraper Health & Latency Dashboard', report)


@Route('clear_scraper_metrics')
def CLEAR_SCRAPER_METRICS(payload, params):
    database.clear_scraper_metrics()
    control.notify(control.ADDON_NAME, "Scraper telemetry metrics cleared", time=3000)


@Route('vacuum_databases')
def VACUUM_DATABASES(payload, params):
    reclaimed = database.vacuum_all_databases()
    reclaimed_str = database._format_db_bytes(reclaimed)
    control.notify(
        f'{control.ADDON_NAME}: Database',
        f'Databases optimized. Reclaimed {reclaimed_str}',
        time=5000, sound=False)


@Route('check_db_integrity')
def CHECK_DB_INTEGRITY(payload, params):
    all_ok, results = database.check_database_integrity()
    if all_ok:
        control.notify(
            f'{control.ADDON_NAME}: Database Integrity',
            'Integrity check passed. All databases healthy.',
            time=5000, sound=False)
    else:
        err_msg = "\n".join([f"• {name}: {status}" for name, status in results.items()])
        control.textviewer_dialog('Database Integrity Issues Found', err_msg)


def generate_diagnostics_report():
    lines = []
    lines.append("=" * 64)
    lines.append(f"  {control.ADDON_NAME} System Health & Diagnostics Report")
    lines.append(f"  Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 64)
    lines.append("")

    # 1. System & Environment
    lines.append("[1] System Environment")
    lines.append(f"  • Platform:        {control.sys.platform}")
    lines.append(f"  • Python Version:  {control.sys.version.split()[0]}")
    lines.append(f"  • Kodi Version:    {control.kodi_version}")
    lines.append(f"  • Addon Version:   v{control.ADDON_VERSION}")
    import sqlite3
    lines.append(f"  • SQLite Version:  {sqlite3.sqlite_version}")
    lines.append(f"  • Low-RAM Mode:    {'YES' if control.is_low_memory() else 'NO'}")
    lines.append("")

    # 2. Debrid Services
    lines.append("[2] Debrid Cloud Providers")
    debrid_keys = [
        ('Real-Debrid', 'realdebrid.token'),
        ('TorBox', 'torbox.token'),
        ('Premiumize', 'premiumize.token'),
        ('AllDebrid', 'alldebrid.token'),
        ('Debrid-Link', 'debridlink.token'),
        ('EasyDebrid', 'easydebrid.token'),
        ('Easynews', 'easynews.username'),
    ]
    for d_name, s_key in debrid_keys:
        token_val = control.getSetting(s_key)
        clean_name = d_name.lower().replace("-", "").replace(" ", "")
        setting_key = 'provider.easynews' if clean_name == 'easynews' else f'{clean_name}.enabled'
        enabled = control.getBool(setting_key, default=True)
        status_str = "AUTHENTICATED" if token_val else "UNCONFIGURED"
        lines.append(f"  • {d_name:<14}: {status_str} (Enabled: {'YES' if enabled else 'NO'})")
    lines.append("")

    # 3. Watchlist Accounts
    lines.append("[3] Watchlist Services")
    watchlist_services = [
        ('Simkl', 'simkl.token', 'simkl.username'),
        ('AniList', 'anilist.token', 'anilist.username'),
        ('MyAnimeList', 'mal.token', 'mal.username'),
        ('Kitsu', 'kitsu.token', 'kitsu.username'),
    ]
    for wl_name, tok_key, usr_key in watchlist_services:
        token_val = control.getSetting(tok_key)
        uname = control.getSetting(usr_key) or '(no username)'
        status_str = f"AUTHENTICATED as {uname}" if token_val else "UNCONFIGURED"
        lines.append(f"  • {wl_name:<14}: {status_str}")
    lines.append("")

    # 4. Database Integrity & Storage
    lines.append("[4] SQLite Databases & Storage")
    dbs = [
        ('Cache Database', getattr(control, 'cacheFile', None)),
        ('Sync Database', getattr(control, 'malSyncDB', None)),
        ('Search History', getattr(control, 'searchHistoryDB', None)),
        ('ID Mappings', getattr(control, 'mappingDB', None)),
    ]
    for db_label, db_file in dbs:
        if not db_file or not os.path.exists(db_file):
            lines.append(f"  • {db_label:<16}: NOT FOUND / UNINITIALIZED")
            continue
        try:
            size_mb = os.path.getsize(db_file) / (1024 * 1024)
            wal_file = db_file + '-wal'
            wal_mb = (os.path.getsize(wal_file) / (1024 * 1024)) if os.path.exists(wal_file) else 0.0
            with database.SQL(db_file, is_readonly=True) as cur:
                cur.execute("PRAGMA integrity_check(1)")
                res = cur.fetchone()
                status = "OK" if res and list(res.values())[0] == 'ok' else "INTEGRITY ERROR"
            lines.append(f"  • {db_label:<16}: {status} | Size: {size_mb:.2f} MB (WAL: {wal_mb:.2f} MB)")
        except Exception as e:
            lines.append(f"  • {db_label:<16}: ERROR ({e})")
    lines.append("")

    # 5. Scrapers, Circuit Breakers & FlareSolverr
    lines.append("[5] Scraper Circuit Breakers & Domains")
    from resources.lib.pages import circuit_breaker
    from resources.lib.ui import domains, client
    fs_enabled = control.getBool('fs_enable')
    fs_url = (control.getSetting('fs_url') or 'http://localhost:8191/v1').strip()
    if fs_enabled:
        try:
            fs_base = fs_url[:-3] if fs_url.endswith('/v1') else fs_url
            fs_resp = client.get(fs_base, timeout=2.0)
            fs_health = f"ONLINE (HTTP {fs_resp.status_code})" if fs_resp and fs_resp.status_code else "UNREACHABLE"
        except Exception as e:
            fs_health = f"UNREACHABLE ({e})"
    else:
        fs_health = "DISABLED"
    lines.append(f"  • {'flaresolverr':<16}: {fs_health:<16} | URL: {fs_url}")

    all_scrapers = [
        'nyaa', 'animetosho', 'torrentio', 'nekobt', 'bitsearch', 'piratebay',
        'hianime', 'animepahe', 'anikoto', 'watchnixtoons2',
    ]
    for sc in all_scrapers:
        tripped = circuit_breaker.is_tripped(sc)
        domain = domains.get_domain(sc) if hasattr(domains, 'get_domain') else 'default'
        state = "OPEN (TRIPPED)" if tripped else "CLOSED (HEALTHY)"
        lines.append(f"  • {sc:<16}: {state:<16} | Mirror: {domain}")

    lines.append("")
    lines.append("=" * 64)
    lines.append("  End of Diagnostics Report")
    lines.append("=" * 64)
    return "\n".join(lines)


def execute_system_repair():
    progress = control.progressDialog
    progress.create(control.ADDON_NAME, "Executing Otaku System Repair...")
    try:
        progress.update(20, "Checkpointing SQLite databases...")
        database.checkpoint_databases(truncate=True)

        progress.update(40, "Pruning expired cache items...")
        database.prune_expired_cache(max_age_days=7)

        progress.update(60, "Optimizing and vacuuming databases...")
        reclaimed = database.vacuum_all_databases()
        reclaimed_str = database._format_db_bytes(reclaimed)

        progress.update(80, "Resetting scraper circuit breakers...")
        from resources.lib.pages import circuit_breaker
        circuit_breaker.reset()

        progress.update(90, "Refreshing dynamic scraper domains...")
        from resources.lib.ui import domains
        domains.refresh_domains()

        progress.update(100, "Cleaning system memory...")
        control.clean_memory()
    finally:
        progress.close()

    control.notify(
        f"{control.ADDON_NAME}: Repair",
        f"Repair complete! Reclaimed {reclaimed_str}, databases flushed & circuits reset.",
        time=5000,
        sound=False
    )


@Route('system_health_diagnostics')
def SYSTEM_HEALTH_DIAGNOSTICS(payload, params):
    choice = control.select_dialog(
        f"{control.ADDON_NAME}: System Health & Diagnostics",
        [
            "[Diagnostics] View Comprehensive Diagnostics Report",
            "[Repair] Execute 1-Click System Repair & Maintenance"
        ]
    )
    if choice == 0:
        report = generate_diagnostics_report()
        control.textviewer_dialog('Otaku System Health & Diagnostics', report)
    elif choice == 1:
        execute_system_repair()


@Route('sync_mappings')
def SYNC_MAPPINGS(payload, params):
    import service
    service.update_mappings_db()
    control.notify(
        f'{control.ADDON_NAME}: Mappings',
        'Anime ID Mappings successfully updated',
        time=5000, sound=False)


@Route('wipe_addon_data')
def WIPE_ADDON_DATA(payload, params):
    control.clear_settings()


@Route('completed_sync')
def COMPLETED_SYNC(payload, params):
    import service
    service.sync_watchlist()


@Route('sort_select')
def SORT_SELECT(payload, params):
    from resources.lib.windows.sort_select import SortSelect
    SortSelect('sort_select.xml', control.ADDON_PATH).doModal()


@Route('download_manager')
def DOWNLOAD_MANAGER(payload, params):
    from resources.lib.windows.download_manager import DownloadManager
    dlg = DownloadManager('download_manager.xml', control.ADDON_PATH)
    try:
        dlg.doModal()
    finally:
        dlg.abort = True
        del dlg


@Route('import_settings')
def IMPORT_SETTINGS(payload, params):
    import xbmcvfs

    setting_xml = os.path.join(control.dataPath, 'settings.xml')

    # Import
    import_location = control.browse(1, f"{control.ADDON_NAME}: Import Setting", 'files', 'settings.xml')
    if not import_location:
        return control.exit_code()
    if not import_location.endswith('settings.xml'):
        control.ok_dialog(control.ADDON_NAME, "Invalid File!")
    else:
        yesno = control.yesno_dialog(control.ADDON_NAME, "Are you sure you want to replace settings.xml?")
        if yesno:
            if xbmcvfs.delete(setting_xml) and xbmcvfs.copy(import_location, setting_xml):
                control.ok_dialog(control.ADDON_NAME, "Replaced settings.xml")
            else:
                control.ok_dialog(control.ADDON_NAME, "Could Not Import File!")
    return control.exit_code()


@Route('export_settings')
def EXPORT_SETTINGS(payload, params):
    import xbmcvfs

    setting_xml = os.path.join(control.dataPath, 'settings.xml')

    # Export
    export_location = control.browse(3, f"{control.ADDON_NAME}: Export Setting", 'files')
    if not export_location:
        control.ok_dialog(control.ADDON_NAME, "Please Select Export Location!")
    else:
        yesno = control.yesno_dialog(control.ADDON_NAME, "Are you sure you want to save settings.xml?")
        if yesno:
            if xbmcvfs.copy(setting_xml, os.path.join(export_location, 'settings.xml')):
                control.ok_dialog(control.ADDON_NAME, "Saved settings.xml")
            else:
                control.ok_dialog(control.ADDON_NAME, "Could Not Export File!")
    return control.exit_code()


@Route('inputstreamadaptive')
def INPUTSTREAMADAPTIVE(payload, params):
    import xbmcaddon
    try:
        xbmcaddon.Addon('inputstream.adaptive').openSettings()
    except RuntimeError:
        control.notify(control.ADDON_NAME, "InputStream Adaptive is not installed.")


@Route('inputstreamhelper')
def INPUTSTREAMHELPER(payload, params):
    import xbmcaddon
    import xbmc
    try:
        xbmcaddon.Addon('inputstream.adaptive')
        control.ok_dialog(control.ADDON_NAME, "InputStream Adaptive is already installed.")
    except RuntimeError:
        xbmc.executebuiltin('InstallAddon(inputstream.adaptive)')


@Route('trakt_settings')
def TRAKT_SETTINGS(payload, params):
    import xbmcaddon
    try:
        xbmcaddon.Addon('script.trakt').openSettings()
    except RuntimeError:
        control.notify(control.ADDON_NAME, "Trakt Script is not installed.")


@Route('trakt_script')
def TRAKT_SCRIPT(payload, params):
    import xbmcaddon
    import xbmc
    try:
        xbmcaddon.Addon('script.trakt')
        control.ok_dialog(control.ADDON_NAME, "Trakt Script is already installed.")
    except RuntimeError:
        xbmc.executebuiltin('InstallAddon(script.trakt)')


def apply_hardware_preset(preset_idx):
    """
    preset_idx:
      0 = High-End (Shield Pro / PC / Mac)
      1 = Balanced (Onn 4K Pro / Fire TV 4K Max)
      2 = Low-RAM (Firestick Lite / Budget TV / RPi)
    """
    if preset_idx == 0:
        control.setInt('scraper.concurrency.workers', 16)
        control.setInt('general.timeout', 20)
        control.setInt('db.sqlite.cache_size_mb', 32)
        control.setInt('db.sqlite.mmap_size_mb', 64)
        control.setBool('general.kodi.cache', True)
        control.setBool('smartplay.preresolve', True)
        control.setBool('clean.memory', False)
        control.log("Setup Wizard: High-End Hardware preset applied (16 workers, 20s timeout, 32MB SQLite cache)")
    elif preset_idx == 1:
        control.setInt('scraper.concurrency.workers', 8)
        control.setInt('general.timeout', 15)
        control.setInt('db.sqlite.cache_size_mb', 16)
        control.setInt('db.sqlite.mmap_size_mb', 32)
        control.setBool('general.kodi.cache', True)
        control.setBool('smartplay.preresolve', True)
        control.setBool('clean.memory', False)
        control.log("Setup Wizard: Balanced Hardware preset applied (8 workers, 15s timeout, 16MB SQLite cache)")
    elif preset_idx == 2:
        control.setInt('scraper.concurrency.workers', 4)
        control.setInt('general.timeout', 12)
        control.setInt('db.sqlite.cache_size_mb', 8)
        control.setInt('db.sqlite.mmap_size_mb', 4)
        control.setBool('general.kodi.cache', False)
        control.setBool('smartplay.preresolve', False)
        control.setBool('clean.memory', True)
        control.log("Setup Wizard: Low-RAM Hardware preset applied (4 workers, 12s timeout, 8MB SQLite cache)")


def apply_playback_profile(profile_idx):
    """
    profile_idx:
      0 = Subbed (Japanese Audio + English Subtitles)
      1 = Dubbed (English Audio + Signs/Songs Subtitles)
    """
    from resources.lib.windows.sort_select import SortSelect
    if profile_idx == 0:
        control.setInt('general.audio', 0)
        control.setInt('general.subtitles', 1)
        control.setBool('general.subtitles.type', True)
        control.setInt('subtitles.types', 1)
        control.setBool('general.subtitles.keyword', True)
        control.setInt('subtitles.keywords', 1)
        control.setBool('general.dubsubtitles', False)
        control.setInt('general.source', 1)
        control.setBool('divflavors.showdub', False)
        control.setBool('jz.dub', False)
        SortSelect.auto_action(0)
        control.log("Setup Wizard: Subbed playback profile applied")
    elif profile_idx == 1:
        control.setInt('general.audio', 1)
        control.setInt('general.subtitles', 0)
        control.setBool('general.subtitles.type', True)
        control.setInt('subtitles.types', 1)
        control.setBool('general.subtitles.keyword', True)
        control.setInt('subtitles.keywords', 2)
        control.setBool('general.dubsubtitles', False)
        control.setInt('general.source', 2)
        control.setBool('divflavors.showdub', True)
        control.setBool('jz.dub', True)
        SortSelect.auto_action(1)
        control.log("Setup Wizard: Dubbed playback profile applied")


def apply_torrent_providers_preset(choice_idx):
    """
    choice_idx:
      0 = Recommended (Nyaa, AnimeTosho, Bitsearch, ThePirateBay)
      1 = All (All 6 torrent indexers)
      2 = None (Disable all torrent scrapers)
    """
    if choice_idx == 0:
        control.setBool('provider.nyaa', True)
        control.setBool('provider.animetosho', True)
        control.setBool('provider.bitsearch', True)
        control.setBool('provider.piratebay', True)
        control.setBool('provider.torrentio', False)
        control.setBool('provider.nekobt', False)
        control.log("Setup Wizard: Recommended torrent providers enabled")
    elif choice_idx == 1:
        control.setBool('provider.nyaa', True)
        control.setBool('provider.animetosho', True)
        control.setBool('provider.bitsearch', True)
        control.setBool('provider.piratebay', True)
        control.setBool('provider.torrentio', True)
        control.setBool('provider.nekobt', True)
        control.log("Setup Wizard: All torrent providers enabled")
    elif choice_idx == 2:
        control.setBool('provider.nyaa', False)
        control.setBool('provider.animetosho', False)
        control.setBool('provider.bitsearch', False)
        control.setBool('provider.piratebay', False)
        control.setBool('provider.torrentio', False)
        control.setBool('provider.nekobt', False)
        control.log("Setup Wizard: All torrent providers disabled")


def apply_embed_providers_preset(choice_idx):
    """
    choice_idx:
      0 = Recommended (HiAnime, AnimePahe, AniKoto, WatchNixtoons2)
      1 = All (All active embed scrapers)
      2 = None (Disable all embed scrapers)
    """
    if choice_idx == 0:
        control.setBool('provider.hianime', True)
        control.setBool('provider.animepahe', True)
        control.setBool('provider.anikoto', True)
        control.setBool('provider.watchnixtoons2', True)
        control.log("Setup Wizard: Recommended embed providers enabled")
    elif choice_idx == 1:
        control.setBool('provider.hianime', True)
        control.setBool('provider.animepahe', True)
        control.setBool('provider.anikoto', True)
        control.setBool('provider.watchnixtoons2', True)
        control.log("Setup Wizard: All embed providers enabled")
    elif choice_idx == 2:
        control.setBool('provider.hianime', False)
        control.setBool('provider.animepahe', False)
        control.setBool('provider.anikoto', False)
        control.setBool('provider.watchnixtoons2', False)
        control.log("Setup Wizard: All embed providers disabled")


@Route('setup_wizard')
def SETUP_WIZARD(payload, params):
    # Step 1: Hardware Performance Preset
    hw_choice = control.select_dialog(
        "Otaku Setup: Hardware Performance Preset",
        [
            "[High-End] Nvidia Shield Pro / PC / Apple TV (16 workers, 20s timeout, 32MB cache)",
            "[Balanced] Onn 4K Pro / Fire TV 4K Max / Chromecast (8 workers, 15s timeout, 16MB cache)",
            "[Low-RAM] Firestick Lite / Budget Smart TV / Raspberry Pi (4 workers, 12s timeout, 8MB cache)"
        ]
    )
    if hw_choice in (0, 1, 2):
        apply_hardware_preset(hw_choice)

    # Step 2: Playback & Language Profile
    play_choice = control.select_dialog(
        "Otaku Setup: Playback & Language Profile",
        [
            "[Subbed] Original Japanese Audio + English Subtitles",
            "[Dubbed] English Audio + Signs/Songs Subtitles"
        ]
    )
    if play_choice in (0, 1):
        apply_playback_profile(play_choice)

    # Step 3: Title Language
    title_choice = control.yesno_dialog(
        control.ADDON_NAME,
        "Please choose your preferred Title Language for Anime content:",
        "English", "Romaji"
    )
    control.setInt('titlelanguage', 0 if title_choice == 1 else 1)

    # Step 4: Torrent Providers Setup (None / All / Recommended)
    torrent_choice = control.select_dialog(
        "Otaku Setup: Torrent Providers",
        [
            "[Recommended] Nyaa, AnimeTosho, Bitsearch, ThePirateBay (Fast & reliable)",
            "[All] Enable all 6 torrent indexers (Includes Torrentio & NekoBT)",
            "[None] Disable all torrent indexers (Optimized for free streaming)"
        ]
    )
    if torrent_choice in (0, 1, 2):
        apply_torrent_providers_preset(torrent_choice)

    # Step 5: Embed Providers Setup (None / All / Recommended)
    embed_choice = control.select_dialog(
        "Otaku Setup: Embed Streaming Providers",
        [
            "[Recommended] HiAnime, AnimePahe, AniKoto, WatchNixtoons2 (Fast & 1080p)",
            "[All] Enable all active embed scrapers",
            "[None] Disable all embed scrapers (Optimized for pure Debrid users)"
        ]
    )
    if embed_choice in (0, 1, 2):
        apply_embed_providers_preset(embed_choice)

    # Step 6: Debrid Account Authorization (Optional)
    debrid_choice = control.select_dialog(
        "Otaku Setup: Debrid Account Authorization (Optional)",
        [
            "Real-Debrid",
            "TorBox",
            "Premiumize",
            "AllDebrid",
            "Debrid-Link",
            "EasyDebrid",
            "Easynews",
            "Skip / Already Authorized"
        ]
    )
    debrid_map = {0: 'realdebrid', 1: 'torbox', 2: 'premiumize', 3: 'alldebrid', 4: 'debridlink', 5: 'easydebrid', 6: 'easynews'}
    if debrid_choice in debrid_map:
        try:
            AUTH(debrid_map[debrid_choice], {})
        except Exception as e:
            control.log(f"Setup Wizard: Debrid auth failed: {e}", 'warning')

    # Step 7: Watchlist Synchronization (Optional)
    watch_choice = control.select_dialog(
        "Otaku Setup: Watchlist Synchronization (Optional)",
        [
            "AniList",
            "MyAnimeList",
            "Simkl",
            "Kitsu",
            "Skip / Already Authorized"
        ]
    )
    watchlist_map = {0: 'anilist', 1: 'mal', 2: 'simkl', 3: 'kitsu'}
    if watch_choice in watchlist_map:
        service_name = watchlist_map[watch_choice]
        try:
            control.execute(f'RunPlugin(plugin://plugin.video.otaku.rpdev/watchlist_login/{service_name}?auth_dialog=true)')
        except Exception as e:
            control.log(f"Setup Wizard: Watchlist auth failed: {e}", 'warning')

    # Final confirmation
    control.ok_dialog(
        control.ADDON_NAME,
        "Setup Wizard complete! Performance presets, playback preferences, and provider profiles have been successfully applied."
    )


@Route('toggleLanguageInvoker')
def TOGGLE_LANGUAGE_INVOKER(payload, params):
    import service
    service.toggle_reuselanguageinvoker()


def _get_advancedsettings_status(element_name):
    """Helper function to get current status of advancedsettings.xml elements"""
    try:
        if os.path.exists(control.kodi_advancedsettings_path):
            tree = ET.parse(control.kodi_advancedsettings_path)
            root = tree.getroot()
            element = root.find(element_name)
            if element is not None:
                return element.text.lower() == 'true'
        return False  # Default to false if not found or file doesn't exist
    except Exception:
        return False


def _update_network_status():
    """Update the status settings to reflect current advancedsettings.xml state"""
    ipv6_disabled = _get_advancedsettings_status('disableipv6')
    http2_disabled = _get_advancedsettings_status('disablehttp2')

    control.setSetting('ipv6.status', 'Disabled' if ipv6_disabled else 'Enabled')
    control.setSetting('http2.status', 'Disabled' if http2_disabled else 'Enabled')


@Route('toggle_ipv6')
def TOGGLE_IPV6(payload, params):
    """Toggle IPv6 setting in Kodi's advancedsettings.xml"""
    try:
        if os.path.exists(control.kodi_advancedsettings_path):
            tree = ET.parse(control.kodi_advancedsettings_path)
            root = tree.getroot()
        else:
            root = ET.Element('advancedsettings')
            tree = ET.ElementTree(root)

        disableipv6_elem = root.find('disableipv6')
        if disableipv6_elem is None:
            disableipv6_elem = ET.SubElement(root, 'disableipv6')
            disableipv6_elem.text = 'false'

        current_value = disableipv6_elem.text.lower() == 'true'
        new_value = not current_value
        disableipv6_elem.text = 'true' if new_value else 'false'

        tree.write(control.kodi_advancedsettings_path, encoding='utf-8', xml_declaration=True)
        _update_network_status()

        status = "disabled" if new_value else "enabled"
        control.notify(
            title=control.ADDON_NAME,
            text=f"IPv6 {status}. Please restart Kodi for changes to take effect.",
            time=5000
        )

    except Exception as e:
        control.notify(
            title=control.ADDON_NAME,
            text=f"Error toggling IPv6 setting: {str(e)}",
            time=5000
        )
        control.log(f"Error in TOGGLE_IPV6: {str(e)}", level='error')


@Route('toggle_http2')
def TOGGLE_HTTP2(payload, params):
    """Toggle HTTP/2 setting in Kodi's advancedsettings.xml"""
    try:
        if os.path.exists(control.kodi_advancedsettings_path):
            tree = ET.parse(control.kodi_advancedsettings_path)
            root = tree.getroot()
        else:
            root = ET.Element('advancedsettings')
            tree = ET.ElementTree(root)

        disablehttp2_elem = root.find('disablehttp2')
        if disablehttp2_elem is None:
            disablehttp2_elem = ET.SubElement(root, 'disablehttp2')
            disablehttp2_elem.text = 'false'

        current_value = disablehttp2_elem.text.lower() == 'true'
        new_value = not current_value
        disablehttp2_elem.text = 'true' if new_value else 'false'

        tree.write(control.kodi_advancedsettings_path, encoding='utf-8', xml_declaration=True)
        _update_network_status()

        status = "disabled" if new_value else "enabled"
        control.notify(
            title=control.ADDON_NAME,
            text=f"HTTP/2 {status}. Please restart Kodi for changes to take effect.",
            time=5000
        )

    except Exception as e:
        control.notify(
            title=control.ADDON_NAME,
            text=f"Error toggling HTTP/2 setting: {str(e)}",
            time=5000
        )
        control.log(f"Error in TOGGLE_HTTP2: {str(e)}", level='error')


@Route('update_network_status')
def UPDATE_NETWORK_STATUS(payload, params):
    """Update network status settings when settings are opened"""
    _update_network_status()


@Route('clean_settings')
def CLEAN_SETTINGS(payload, params):
    """Scan and prune obsolete/orphaned settings from userdata settings.xml."""
    try:
        from resources.lib.ui import clean_settings
        count, removed = clean_settings.clean_settings()
        if count > 0:
            control.notify(
                title=control.ADDON_NAME,
                text=f"Pruned {count} orphaned setting(s)",
                time=4000
            )
        else:
            control.notify(
                title=control.ADDON_NAME,
                text="Settings file is clean. No orphaned settings found.",
                time=4000
            )
    except Exception as e:
        control.notify(
            title=control.ADDON_NAME,
            text=f"Settings cleanup failed: {str(e)}",
            time=5000
        )
        control.log(f"Error in CLEAN_SETTINGS: {e}", level='error')
    finally:
        try:
            import xbmcplugin
            import sys
            handle = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else -1
            if handle >= 0:
                xbmcplugin.endOfDirectory(handle, succeeded=True)
        except Exception:
            pass


@Route('menu_order')
def MENU_ORDER(payload, params):
    """Open interactive menu order and visibility customization dialog."""
    from resources.lib.windows.menu_order import open_menu_order_dialog
    menu_key = params.get('menu', 'menu.mainmenu')
    open_menu_order_dialog(menu_key)


@Route('probe_settings')
def PROBE_SETTINGS(payload, params):
    """Probe and verify all declared settings and localization strings in Kodi runtime."""
    try:
        import json
        import os
        import sys
        import xml.etree.ElementTree as ET
        import xbmcaddon
        import xbmcplugin

        addon_dir = control.ADDON_PATH
        settings_xml = os.path.join(addon_dir, 'resources', 'settings.xml')
        tree = ET.parse(settings_xml)
        settings_elements = [(e.attrib.get('id'), e.attrib.get('type')) for e in tree.findall('.//setting') if e.attrib.get('id')]
        settings = [s[0] for s in settings_elements]

        addon = xbmcaddon.Addon(control.ADDON_ID)
        errors = []
        success_count = 0
        kodi_settings = None
        if hasattr(addon, 'getSettings'):
            try:
                kodi_settings = addon.getSettings()
            except Exception as e:
                errors.append(f"getSettings() exception: {e}")

        for sid, stype in settings_elements:
            try:
                if stype == 'action':
                    val = True
                elif stype == 'boolean':
                    val = addon.getSettingBool(sid) if hasattr(addon, 'getSettingBool') else control.getBool(sid)
                elif stype == 'integer':
                    val = addon.getSettingInt(sid) if hasattr(addon, 'getSettingInt') else control.getInt(sid)
                elif stype == 'number':
                    val = addon.getSettingNumber(sid) if hasattr(addon, 'getSettingNumber') else control.getStr(sid)
                elif stype in ('list[string]', 'list[String]'):
                    if kodi_settings and hasattr(kodi_settings, 'getStringList'):
                        val = kodi_settings.getStringList(sid)
                    else:
                        val = control.getStringList(sid)
                else:
                    val = addon.getSettingString(sid) if hasattr(addon, 'getSettingString') else control.getStr(sid)
                success_count += 1
            except Exception as e:
                errors.append(f"getSetting({sid}, type={stype}): {e}")

        # Sample localized strings across #30000-#30999
        strings_verified = 0
        for sid in range(30000, 31000):
            try:
                text = addon.getLocalizedString(sid)
                if text:
                    strings_verified += 1
            except Exception as e:
                errors.append(f"getLocalizedString({sid}): {e}")

        result = {
            "ok": len(errors) == 0,
            "settings_count": len(settings),
            "settings_read": success_count,
            "strings_verified": strings_verified,
            "has_kodi_settings_obj": kodi_settings is not None,
            "errors": errors,
        }
        out_path = os.path.join(control.dataPath, 'settings_probe.json')
        try:
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2)
        except Exception as e:
            control.log(f"Failed to write settings probe result: {e}", level='error')
    finally:
        try:
            import xbmcplugin
            import sys
            handle = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else -1
            if handle >= 0:
                xbmcplugin.endOfDirectory(handle, succeeded=True)
        except Exception:
            pass


@Route('set_settings')
def SET_SETTINGS(payload, params):
    """Dynamically set settings in Kodi runtime during testing."""
    import sys
    import xbmcplugin
    if params:
        for k, v in params.items():
            if v == 'true':
                control.setBool(k, True)
            elif v == 'false':
                control.setBool(k, False)
            elif v.isdigit():
                control.setInt(k, int(v))
            elif ',' in v or k.endswith('.config') or k in ('fanart.all', 'fanart.mal_ids', 'fanart.selections', 'DMIndex', 'general.filters'):
                items = [x.strip() for x in v.split(',') if x.strip()]
                control.setStringList(k, items)
            else:
                control.setSetting(k, v)
        control.clearSettingsCache()
    try:
        handle = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else -1
        if handle >= 0:
            xbmcplugin.endOfDirectory(handle, succeeded=True)
    except Exception:
        pass


@Route('webpdb_trace')
def WEBPDB_TRACE(payload, params):
    """Trigger an interactive Web-PDB debugging session on the configured port (default 5566)."""
    port = params.get('port') if isinstance(params, dict) else None
    ok = control.start_webpdb_trace(port=port)
    if not ok:
        control.notify(control.ADDON_NAME, "Web-PDB (script.module.web-pdb) is not available.")
    return control.exit_code()



