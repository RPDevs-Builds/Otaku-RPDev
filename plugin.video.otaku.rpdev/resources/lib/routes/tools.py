# -*- coding: utf-8 -*-
import os
import xml.etree.ElementTree as ET

from resources.lib import MetaBrowser
from resources.lib.ui import control, database, utils
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
    try:
        window = FilterSelect("filter_select.xml", control.ADDON_PATH)
        window.doModal()
    finally:
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


@Route('fanart_select/*')
def FANART_SELECT(payload, params):
    from resources.lib import Main
    mal_id = Main._extract_mal_id(payload)
    if not (episode := database.get_episode(mal_id)):
        MetaBrowser.get_anime_init(mal_id)
        episode = database.get_episode(mal_id)
    fanart = database.loads(episode['kodi_meta'])['image']['fanart'] or []
    fanart_display = fanart + ["None", "Random (Default)"]
    fanart += ["None", ""]
    control.draw_items([utils.allocate_item(f, f'fanart/{mal_id}/{i}', False, False, [], f, {}, fanart=f, landscape=f) for i, f in enumerate(fanart_display)], '')


@Route('fanart/*')
def FANART(payload: str, params: dict):
    parts = [p for p in payload.strip('/').split('/') if p]
    mal_id = parts[0] if parts else ''
    select = parts[1] if len(parts) > 1 else '0'
    episode = database.get_episode(mal_id)
    fanart = database.loads(episode['kodi_meta'])['image']['fanart'] or []
    fanart_display = fanart + ["None", "Random"]
    fanart += ["None", ""]

    # Set fanart selection using string lists
    mal_ids = control.getStringList('fanart.mal_ids')
    fanart_selections = control.getStringList('fanart.selections')
    mal_id_str = str(mal_id)
    fanart_url = fanart[int(select)]

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
    control.ok_dialog(control.ADDON_NAME, f"Fanart Set to {fanart_display[int(select)]}")


# ### Maintenance ###
@Route('settings')
def SETTINGS(payload, params):
    control.ADDON.openSettings()
    control.clearSettingsCache()


@Route('change_log')
def CHANGE_LOG(payload, params):
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
    DownloadManager('download_manager.xml', control.ADDON_PATH).doModal()


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


@Route('setup_wizard')
def SETUP_WIZARD(payload, params):
    from resources.lib.windows.sort_select import SortSelect
    import xbmcgui
    choice = control.yesno_dialog(
        control.ADDON_NAME,
        "Would you like to enable search history?",
        "No", "Yes",
    )

    if choice == 1:
        control.setInt('searchhistory', 0)
    elif choice == 0:
        control.setInt('searchhistory', 1)

    choice = control.yesno_dialog(
        control.ADDON_NAME,
        "Would you like to show change log every update?",
        "No", "Yes",
    )

    if choice == 1:
        control.setInt('showchangelog', 0)
    elif choice == 0:
        control.setInt('showchangelog', 1)

    choice = control.yesno_dialog(
        control.ADDON_NAME,
        "Please choose your preferred Title Language for your Anime Content:",
        "English", "Romaji",
    )

    if choice == 1:
        control.setInt('titlelanguage', 0)
    elif choice == 0:
        control.setInt('titlelanguage', 1)

    choice = control.yesnocustom_dialog(
        control.ADDON_NAME,
        "Please choose where you would like to get your Anime Content from:",
        "Anilist", "Mal", "Otaku",
        defaultbutton=xbmcgui.DLG_YESNO_YES_BTN
    )

    if choice == 1:
        control.setSetting('browser.api', 'otaku')
    elif choice == 0:
        control.setSetting('browser.api', 'mal')
    elif choice == 2:
        control.setSetting('browser.api', 'anilist')

        choice = control.yesno_dialog(
            control.ADDON_NAME,
            "Would you like to replace Anilist Posters with Mal Posters?",
            "No", "Yes",
        )

        if choice == 1:
            control.setBool('general.malposters', True)
        elif choice == 0:
            control.setBool('general.malposters', False)

    choice = control.yesno_dialog(
        control.ADDON_NAME,
        "Would you like to have the rest of the menus enabled?\n(Note: This will enabled menus such as Movies, TV Shows, TV Shorts, Specials, OVAs, ONAs, and Music Videos. A restart may be required for the changes to take effect.)",
        "No", "Yes",
    )

    if choice == 1:
        control.setStringList('menu.mainmenu.config', ['last_watched', 'watch_history', 'next_up', 'my_cloud', 'airing_calendar', 'airing_last_season', 'airing_this_season', 'airing_next_season', 'movies', 'tv_shows', 'tv_shorts', 'specials', 'ovas', 'onas', 'music', 'trending', 'popular', 'voted', 'favourites', 'top_100', 'genres', 'search', 'tools'])
    elif choice == 0:
        control.setStringList('menu.mainmenu.config', ['last_watched', 'watch_history', 'next_up', 'my_cloud', 'airing_calendar', 'airing_last_season', 'airing_this_season', 'airing_next_season', 'trending', 'popular', 'voted', 'favourites', 'top_100', 'genres', 'search', 'tools'])

    choice = control.yesno_dialog(
        control.ADDON_NAME,
        "Please choose your preferred language option for playback:",
        "Dubs", "Subs",
    )

    if choice == 1:
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
        control.log("Subs settings applied.")
    elif choice == 0:
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
        control.log("Dubs settings applied.")

        choice = control.yesno_dialog(
            control.ADDON_NAME,
            "Would you like subtitles for dub streams?\n(Note: This may not work for all streams.)",
            "No", "Yes",
        )

        if choice == 1:
            control.setBool('general.dubsubtitles', True)
            control.setInt('general.subtitles', 1)
            control.setInt('subtitles.types', 1)
            control.setInt('subtitles.keywords', 1)


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
