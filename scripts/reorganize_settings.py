#!/usr/bin/env python3
"""
Reorganize and deduplicate resources/settings.xml for Otaku-RPDev.
Eliminates duplicate actions, consolidates fragmented domains, wires help guides,
and maintains 100% backward compatibility for all stored user settings.
"""

import os
import shutil
import xml.etree.ElementTree as ET


def reorganize_settings():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    settings_xml = os.path.join(base_dir, "plugin.video.otaku.rpdev", "resources", "settings.xml")
    backup_xml = settings_xml + ".bak"

    if not os.path.exists(settings_xml):
        raise FileNotFoundError(f"settings.xml not found at {settings_xml}")

    # Create backup
    shutil.copyfile(settings_xml, backup_xml)
    print(f"Backed up settings.xml to {backup_xml}")

    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    tree = ET.parse(settings_xml, parser=parser)
    root = tree.getroot()

    # Collect all settings by ID
    all_settings_by_id = {}
    for s in root.iter("setting"):
        sid = s.get("id")
        if sid:
            all_settings_by_id[sid] = s

    print(f"Total original settings discovered: {len(all_settings_by_id)}")

    # Attribute modifications dictionary
    attr_updates = {
        "artwork.fanart.count": {"label": "30627", "help": "30628"},
        "interface.viewidswitch": {"help": "30657"},
        "reuselanguageinvoker.toggle": {"help": "30629"},
        "download.location": {"help": "30631"},
        "contentyear.bool": {"help": "30633"},
        "contentseason.bool": {"help": "30634"},
        "contentformat.bool": {"help": "30635"},
        "contentstatus.bool": {"help": "30636"},
        "contentrating.bool": {"help": "30637"},
        "contentorigin.bool": {"help": "30638"},
        "contentgenre.menu": {"help": "30639"},
        "divflavors.dubonly": {"help": "30640"},
        "search.adult": {"label": "30641", "help": "30642"},
        "interface.watchlist.paging": {"help": "30643"},
        "interface.perpage.watchlist": {"help": "30644"},
        "interface.check.updates": {"help": "30645"},
        "interface.watchlist.data": {"help": "30646"},
        "general.subtitles": {"help": "30648"},
        "general.subtitles.type": {"help": "30649"},
        "general.subtitles.keyword": {"help": "30650"},
        "general.dubsubtitles": {"help": "30651"},
        "rebuild_database": {"help": "30656"},
        "wipe_addon_data": {"help": "30655"},
        "general.movie.maxGB": {"help": "30658"},
        "general.episode.maxGB": {"help": "30659"},
        "subtitles.use_chardet": {"help": "30660"},
        "subtitles.auto_download": {"help": "30661"},
        "subtitles.timeout": {"help": "30662"},
        "subtitles.prefer_sdh": {"help": "30663"},
        "subtitles.prefer_forced": {"help": "30664"},
    }

    # Apply updates to setting elements
    for sid, updates in attr_updates.items():
        if sid in all_settings_by_id:
            for k, v in updates.items():
                all_settings_by_id[sid].set(k, v)

    # Categories to preserve untouched
    untouched_categories = {
        "Providers",
        "Scraping",
        "Accounts",
        "Menu Customization",
        "Context Customization",
    }

    # Define the exact layout for reorganized categories
    layout = {
        "general": [
            ("1", "30415", [
                "setup.wizard",
                "showchangelog",
                "general.verify_ssl",
            ]),
            ("2", "30290", [
                "titlelanguage",
                "searchhistory",
                "general.smart.scroll.enable",
                "interface.cleantitles",
                "interface.watchhistory.click",
                "interface.aired_episodes",
                "interface.aired.show_countdown",
                "interface.content_type",
                "interface.viewtype",
                "interface.viewidswitch",
                "interface.addon.view",
                "interface.show.view",
                "interface.episode.view",
                "interface.addon.view.id",
                "interface.show.view.id",
                "interface.episode.view.id",
            ]),
            ("3", "30128", [
                "browser.api",
                "override.meta.api",
                "meta.api",
                "override.meta.notify",
            ]),
            ("4", "30175", [
                "interface.perpage.general.anilist",
                "interface.perpage.general.mal",
                "jz.dub",
                "jz.dub.api",
                "jz.filler",
            ]),
            ("5", "30104", [
                "interface.icons",
                "artwork.studios",
                "general.dialog",
                "general.malposters",
                "interface.spoilers.hide_thumbs",
                "interface.spoilers.shield_mode",
                "artwork.preference",
                "artwork.titlesearch",
                "artwork.advanced",
                "artwork.fanart.count",
                "artwork.fanart",
                "artwork.landscape",
                "artwork.clearlogo",
                "artwork.clearart",
                "artwork.banner",
            ]),
            ("6", "30255", [
                "widget.hide.nextpage",
                "widgets.delay",
            ]),
        ],
        "Cache": [
            ("1", "30497", [
                "general.kodi.cache",
                "cache.scrapers.ttl",
                "cache.torrents.ttl",
                "cache.metadata.ttl",
                "cache.calendar.ttl",
            ]),
            ("2", "30499", [
                "db.sqlite.cache_size_mb",
                "db.sqlite.mmap_size_mb",
                "db.sqlite.synchronous",
                "db.sqlite.temp_store_ram",
            ]),
            ("3", "30496", [
                "clear_cache_all",
                "clear_cache_scrapers",
                "clear_cache_debrid",
                "clear_cache_metadata",
                "refresh_hianime_domains",
                "clean_settings",
            ]),
        ],
        "Playback": [
            ("1", "30289", [
                "general.smartplay",
                "smartplay.reuse_season_pack",
                "smartplay.match_quality",
                "smartplay.prefer_same_embed",
                "smartplay.prescrape",
                "smartplay.preresolve",
                "general.playstyle.movie",
                "general.playstyle.episode",
                "interface.source_select.badges",
            ]),
            ("2", "30275", [
                "general.kodi_language",
                "general.audio",
                "playlist.unaired",
            ]),
            ("3", "30471", [
                "ffprobe.chapters.enable",
                "ffprobe.path",
            ]),
            ("4", "30148", [
                "smartplay.skipintrodialog",
                "skipintro.aniskip.enable",
                "skipintro.aniskip.auto",
                "skipintro.aniskip.offset",
                "skipintro.time",
                "skipintro.delay",
                "skipintro.duration",
            ]),
            ("5", "30145", [
                "smartplay.playingnextdialog",
                "smartplay.binge_mode",
                "smartplay.stillwatching_count",
                "smartplay.stillwatching_timeout",
                "skipoutro.aniskip.enable",
                "skipoutro.aniskip.auto",
                "skipoutro.aniskip.offset",
                "playingnext.time",
                "playingnext.defaultaction",
            ]),
        ],
        "Subtitles": [
            ("1", "30600", [
                "subtitles.enabled",
                "subtitles.auto_search",
                "subtitles.auto_download",
                "subtitles.prefer_sdh",
                "subtitles.prefer_forced",
                "subtitles.use_chardet",
                "subtitles.timeout",
                "subtitles.results_limit",
            ]),
            ("2", "30647", [
                "general.subtitles",
                "general.subtitles.type",
                "subtitles.types",
                "general.subtitles.keyword",
                "subtitles.keywords",
                "subtitles.customkeyword",
                "general.dubsubtitles",
            ]),
            ("3", "30614", [
                "subtitles.provider.opensubtitles",
                "subtitles.opensubtitles.username",
                "subtitles.opensubtitles.password",
                "subtitles.provider.subdl",
                "subtitles.subdl.apikey",
                "subtitles.provider.subsource",
                "subtitles.subsource.apikey",
                "subtitles.provider.podnadpisi",
                "subtitles.provider.bsplayer",
                "subtitles.provider.addic7ed",
            ]),
        ],
        "Sort and Filter": [
            ("1", "30632", [
                "contentyear.bool",
                "contentyear.menu",
                "contentseason.bool",
                "contentseason.menu",
                "contentformat.bool",
                "contentformat.menu",
                "contentstatus.bool",
                "contentstatus.menu.anilist",
                "contentstatus.menu.mal",
                "contentrating.bool",
                "contentrating.menu.mal",
                "contentorigin.bool",
                "contentorigin.menu",
                "contentgenre.bool",
                "contentgenre.menu",
                "divflavors.dubonly",
                "divflavors.showdub",
                "search.adult",
            ]),
            ("2", "30152", [
                "source.filter",
                "general.maxResolution",
                "general.minResolution",
                "general.fileFilter",
                "general.webspeed",
                "general.movie.maxGB",
                "general.movie.minGB",
                "general.episode.maxGB",
                "general.episode.minGB",
            ]),
            ("3", "30156", [
                "sort_select",
                "general.source",
            ]),
            ("4", "30308", [
                "general.release_title_filter.enabled",
                "general.release_title_filter.selection",
                "general.release_title_filter.logic",
                "general.release_title_filter.value1",
                "general.release_title_filter.value2",
                "general.release_title_filter.value3",
                "general.release_title_filter.value4",
                "general.release_title_filter.value5",
                "general.release_title_filter.exclude1",
                "general.release_title_filter.exclude2",
                "general.release_title_filter.exclude3",
                "general.release_title_filter.exclude4",
                "general.release_title_filter.exclude5",
            ]),
        ],
        "Watchlist": [
            ("1", "30653", [
                "watchlist.update.enabled",
                "watchlist.sync.enabled",
                "watchlist.prefetch.enabled",
                "watchlist.update.percent",
                "nextup.flavor",
                "interface.watchlist.data",
                "interface.watchlist.paging",
                "interface.perpage.watchlist",
                "interface.check.updates",
            ]),
            ("2", "30220", [
                "anilist.enabled",
                "anilist.username",
                "anilist.login",
                "anilist.sort",
                "anilist.order",
            ]),
            ("3", "30222", [
                "kitsu.enabled",
                "kitsu.username",
                "kitsu.authvar",
                "kitsu.password",
                "kitsu.login",
                "kitsu.sort",
                "kitsu.order",
            ]),
            ("4", "30218", [
                "mal.enabled",
                "mal.username",
                "mal.login",
                "mal.sort",
                "mal.order",
            ]),
            ("5", "30227", [
                "simkl.enabled",
                "simkl.username",
                "simkl.login",
                "simkl.sort",
                "simkl.order",
            ]),
            ("6", "30392", [
                "trakt.enabled",
                "trakt.settings",
                "trakt.script",
            ]),
        ],
        "Maintenance": [
            ("1", "30652", [
                "database_stats",
                "scraper_stats",
                "clear_scraper_metrics",
                "check_db_integrity",
                "vacuum_databases",
                "sync_mappings",
            ]),
            ("2", "30654", [
                "change_log",
                "clear_cache",
                "clear_search_history",
                "clear_watch_history",
                "clear_selected_fanart",
                "completed_sync",
                "rebuild_database",
                "wipe_addon_data",
            ]),
            ("3", "30630", [
                "download_manager",
                "download.location",
            ]),
            ("4", "30342", [
                "inputstreamadaptive.enabled",
                "inputstreamadaptive.settings",
                "inputstreamhelper",
            ]),
            ("5", "30122", [
                "reuselanguageinvoker.toggle",
                "reuselanguageinvoker.status",
            ]),
            ("6", "30346", [
                "fs_enable",
                "fs_inst",
                "fs_url",
                "fs_timeout",
            ]),
            ("7", "30376", [
                "ms_enable",
                "ms_inst",
                "ms_url",
            ]),
            ("8", "30428", [
                "update_network_status",
                "toggle_ipv6",
                "ipv6.status",
                "toggle_http2",
                "http2.status",
            ]),
            ("9", "30125", [
                "import_settings",
                "export_settings",
            ]),
            ("10", "", [
                "cache.useragent",
                "cache.useragent.timestamp",
                "cache.mobile.useragent",
                "cache.mobile.useragent.timestamp",
                "otaku.version",
                "fanart.all",
                "fanart.mal_ids",
                "fanart.selections",
                "DMIndex",
                "general.filters",
                "last_played_source",
                "last_watched_series",
                "addon.last_watched",
                "dub.etag",
                "mappings.etag",
                "mappings.last_modified",
                "alldebrid.token",
                "anilist.authvar",
                "anilist.password",
                "anilist.refresh",
                "anilist.titles",
                "anilist.token",
                "anilist.userid",
                "aniwave.skipintro.end",
                "aniwave.skipintro.start",
                "aniwave.skipoutro.end",
                "aniwave.skipoutro.start",
                "best_match",
                "debridlink.expiry",
                "debridlink.refresh",
                "debridlink.token",
                "easydebrid.token",
                "first_time",
                "format",
                "general.fuzzy",
                "hianime.skipintro.end",
                "hianime.skipintro.start",
                "hianime.skipoutro.end",
                "hianime.skipoutro.start",
                "animekai.skipintro.end",
                "animekai.skipintro.start",
                "animekai.skipoutro.end",
                "animekai.skipoutro.start",
                "anikoto.skipintro.end",
                "anikoto.skipintro.start",
                "anikoto.skipoutro.end",
                "anikoto.skipoutro.start",
                "interface.show_last_watched",
                "interface.show_watch_history",
                "kitsu.expiry",
                "kitsu.refresh",
                "kitsu.titles",
                "kitsu.token",
                "kitsu.userid",
                "mal.authvar",
                "mal.expiry",
                "mal.password",
                "mal.refresh",
                "mal.titles",
                "mal.token",
                "mal.userid",
                "premiumize.token",
                "provider.gogo",
                "provider.gogoalt",
                "realdebrid.client_id",
                "realdebrid.expiry",
                "realdebrid.refresh",
                "realdebrid.secret",
                "realdebrid.token",
                "regex.question",
                "resolve_season",
                "simkl.authvar",
                "simkl.password",
                "simkl.refresh",
                "simkl.titles",
                "simkl.token",
                "simkl.userid",
                "torbox.token",
                "update.time.1",
                "update.time.30",
                "update.time.7",
                "anidb_last_request",
                "april_fools_day",
                "changelog.version",
                "version",
            ]),
        ],
    }

    # Verify that all settings in layout exist in all_settings_by_id
    total_reorganized_settings = 0
    for cat_id, groups in layout.items():
        for grp_id, grp_label, setting_ids in groups:
            for sid in setting_ids:
                if sid not in all_settings_by_id:
                    raise ValueError(f"Setting '{sid}' in layout for category '{cat_id}' group '{grp_id}' not found in original settings!")
                total_reorganized_settings += 1

    print(f"Total settings in reorganized categories layout: {total_reorganized_settings}")

    # Build new category elements for reorganized categories
    section = root.find("section")
    if section is None:
        raise ValueError("No <section> element found in settings.xml")

    new_categories = []
    for cat in section.findall("category"):
        cat_id = cat.get("id")
        if cat_id in untouched_categories:
            new_categories.append(cat)
        elif cat_id in layout:
            new_cat = ET.Element("category", attrib=cat.attrib)
            for grp_id, grp_label, setting_ids in layout[cat_id]:
                grp_attrib = {"id": grp_id}
                if grp_label:
                    grp_attrib["label"] = grp_label
                grp_elem = ET.SubElement(new_cat, "group", attrib=grp_attrib)
                for sid in setting_ids:
                    s_elem = all_settings_by_id[sid]
                    grp_elem.append(s_elem)
            new_categories.append(new_cat)
        else:
            raise ValueError(f"Unknown category '{cat_id}' in settings.xml")

    # Replace section children
    section.clear()
    for cat in new_categories:
        section.append(cat)

    # Indent cleanly
    ET.indent(root, space="\t")

    # Verify total settings in new root
    new_settings = root.findall(".//setting")
    print(f"Total settings in restructured XML: {len(new_settings)}")
    if len(new_settings) != 417:
        raise ValueError(f"Expected exactly 417 settings, found {len(new_settings)}")

    # Write out with XML declaration
    xml_header = '<?xml version="1.0" ?>\n'
    xml_body = ET.tostring(root, encoding="utf-8").decode("utf-8") + "\n"

    with open(settings_xml, "w", encoding="utf-8") as f:
        f.write(xml_header + xml_body)

    print(f"Successfully wrote reorganized settings.xml ({len(new_settings)} settings, 12 categories).")


if __name__ == "__main__":
    reorganize_settings()
