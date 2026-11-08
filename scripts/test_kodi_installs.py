#!/usr/bin/env python3
"""
test_kodi_installs.py — Real-World Headless Kodi 21 & Kodi 22 E2E Test Runner
=============================================================================
Executes end-to-end integration and smoke tests for Otaku-RPDev inside real,
isolated Kodi 21 (Omega) and Kodi 22 (Piers) Flatpak runtimes via kodi-env,
Xvfb display server, and Kodi JSON-RPC API.

Tests cover:
  1. Addon loading, manifest validation, and settings registration
  2. Main, categories, and tools directory navigation
  3. Airing calendar WindowXML modal dialog lifecycle
  4. Browser API backends (Otaku, MyAnimeList, AniList)
  5. Episode listing and InfoTagVideo metadata population
  6. Spoiler shield image masking
  7. Metadata API providers (Simkl, AniZip, Jikan, Kitsu, Otaku)
  8. Title language localization (Romaji vs English)
  9. Reviews WindowXML and SQLite review cache
 10. Database maintenance and cache management tools
 11. Real VideoPlayer playback via embed and direct providers
 12. Clean Kodi shutdown and kodi.log exception/traceback auditing

Usage:
  python3 scripts/test_kodi_installs.py [--versions 21 22] [--fs-url <url>] [--skip-playback] [--out <path>]
"""

import argparse
import base64
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON_DIR = os.path.join(REPO_ROOT, "plugin.video.otaku.rpdev")
KODI_ENV_PROFILES = "/mnt/sharedroot/projects/kodi-test-env/profiles"

PROFILES = {
    "21": ("stable", os.path.join(KODI_ENV_PROFILES, "kodi21")),
    "22": ("beta", os.path.join(KODI_ENV_PROFILES, "kodi22")),
}
SYMLINK_PATH = os.path.expanduser("~/.var/app/tv.kodi.Kodi/data")
RPC_URL = "http://127.0.0.1:8080/jsonrpc"


def get_addon_version():
    """Extract current addon version from addon.xml dynamically."""
    addon_xml_path = os.path.join(ADDON_DIR, "addon.xml")
    try:
        tree = ET.parse(addon_xml_path)
        return tree.getroot().attrib.get("version", "6.0.6")
    except Exception:
        return "6.0.6"


def enable_webserver_in_guisettings(profile_dir):
    gs_path = os.path.join(profile_dir, "userdata", "guisettings.xml")
    os.makedirs(os.path.dirname(gs_path), exist_ok=True)
    if not os.path.exists(gs_path):
        root = ET.Element("settings", version="4")
        tree = ET.ElementTree(root)
    else:
        tree = ET.parse(gs_path)
        root = tree.getroot()

    overrides = {
        "services.webserver": "true",
        "services.webserverport": "8080",
        "services.webserverauthentication": "false",
        "services.webserverusername": "kodi",
        "services.webserverpassword": "",
        "addons.unknownsources": "true",
        "general.addonupdates": "2",
    }
    for key, val in overrides.items():
        elem = root.find(f"./setting[@id='{key}']")
        if elem is None:
            elem = ET.SubElement(root, "setting", id=key)
        elem.attrib.pop("default", None)
        elem.text = val

    tree.write(gs_path, encoding="utf-8", xml_declaration=True)


def write_addon_settings(profile_dir, overrides):
    s_dir = os.path.join(profile_dir, "userdata", "addon_data", "plugin.video.otaku.rpdev")
    os.makedirs(s_dir, exist_ok=True)
    s_path = os.path.join(s_dir, "settings.xml")
    if os.path.exists(s_path):
        try:
            tree = ET.parse(s_path)
            root = tree.getroot()
        except Exception:
            root = ET.Element("settings", version="2")
            tree = ET.ElementTree(root)
    else:
        root = ET.Element("settings", version="2")
        tree = ET.ElementTree(root)

    for k, v in overrides.items():
        elem = root.find(f"./setting[@id='{k}']")
        if elem is None:
            elem = ET.SubElement(root, "setting", id=k)
        elem.attrib.pop("default", None)
        elem.text = str(v)

    tree.write(s_path, encoding="utf-8", xml_declaration=True)


def jsonrpc(method, params=None, timeout=45.0):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params
    data = json.dumps(payload).encode("utf-8")
    auth = base64.b64encode(b"kodi:").decode("ascii")
    headers = {"Content-Type": "application/json", "Authorization": f"Basic {auth}"}
    req = urllib.request.Request(RPC_URL, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=float(timeout)) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def wait_for_kodi_rpc(max_wait=45.0):
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            resp = jsonrpc("JSONRPC.Ping", timeout=2.5)
            if resp.get("result") == "pong":
                return True
        except Exception:
            pass
        time.sleep(1.0)
    return False


def get_dir(plugin_path, props=None, timeout=45.0):
    t0 = time.perf_counter()
    params = {"directory": plugin_path, "media": "video"}
    if props:
        params["properties"] = props
    try:
        res = jsonrpc("Files.GetDirectory", params, timeout=timeout)
        dt = int((time.perf_counter() - t0) * 1000)
        if "error" in res:
            return {"ok": False, "count": 0, "latency_ms": dt, "error": res["error"]}
        files = (res.get("result") or {}).get("files") or []
        return {"ok": True, "count": len(files), "latency_ms": dt, "sample_labels": [f.get("label") for f in files[:5]], "files": files}
    except Exception as e:
        return {"ok": False, "count": 0, "latency_ms": int((time.perf_counter() - t0) * 1000), "error": str(e)}


def test_autoplay_playback(profile_dir, fs_enable, fs_url, only_wco=False, smartplay=False, dub_source=False):
    """Trigger real Player.Open on plugin://plugin.video.otaku.rpdev/play/52991/1 inside Kodi and check VideoPlayer."""
    settings = {
        "general.smartplay": "true" if smartplay else "false",
        "smartplay.prescrape": "true" if smartplay else "false",
        "smartplay.preresolve": "true" if smartplay else "false",
        "skipintro.aniskip.enable": "true" if smartplay else "false",
        "general.playstyle.episode": "0",
        "general.source": "1" if dub_source else "0",
        "fs_enable": "true" if fs_enable else "false",
        "fs_url": fs_url,
        "fs_timeout": "40",
        "provider.nyaa": "false",
        "provider.animetosho": "false",
        "provider.bitsearch": "false",
        "provider.piratebay": "false",
        "provider.torrentio": "false",
        "provider.nekobt": "false",
        "provider.hianime": "false" if only_wco else "true",
        "provider.anikoto": "false" if only_wco else "true",
        "provider.animepahe": "false" if only_wco else "true",
        "provider.watchnixtoons2": "true",
    }
    write_addon_settings(profile_dir, settings)
    t0 = time.perf_counter()
    try:
        jsonrpc("Player.Open", {"item": {"file": "plugin://plugin.video.otaku.rpdev/play/52991/1"}}, timeout=20.0)
    except Exception:
        pass

    # Poll up to 65s for active player (scraper + resolver + prefetch_play_link + VideoPlayer open)
    active_info = None
    deadline = time.time() + (65.0 if only_wco else 45.0)
    while time.time() < deadline:
        try:
            players = jsonrpc("Player.GetActivePlayers", timeout=5.0).get("result") or []
            if players:
                pid = players[0]["playerid"]
                pitem = jsonrpc("Player.GetItem", {"playerid": pid, "properties": ["title", "file", "showtitle", "episode"]}, timeout=5.0).get("result", {}).get("item", {})
                pprops = jsonrpc("Player.GetProperties", {"playerid": pid, "properties": ["time", "totaltime", "speed", "currentaudiostream", "currentsubtitle"]}, timeout=5.0).get("result", {})
                active_info = {
                    "playing": True,
                    "startup_ms": int((time.perf_counter() - t0) * 1000),
                    "item_title": pitem.get("title") or pitem.get("label"),
                    "totaltime": pprops.get("totaltime"),
                    "audiostream": pprops.get("currentaudiostream"),
                }
                jsonrpc("Player.Stop", {"playerid": pid}, timeout=5.0)
                stop_deadline = time.time() + 10.0
                while time.time() < stop_deadline:
                    if not (jsonrpc("Player.GetActivePlayers", timeout=3.0).get("result") or []):
                        break
                    time.sleep(0.5)
                break
        except Exception:
            pass
        time.sleep(1.5)

    # Dismiss any modal OK/resolver dialog if playback didn't start
    if not active_info:
        try:
            jsonrpc("Input.Back", timeout=3.0)
        except Exception:
            pass
        return {"playing": False, "elapsed_ms": int((time.perf_counter() - t0) * 1000)}
    return active_info


def run_kodi_version_suite(ver, fs_url, skip_playback=False):
    branch, profile_dir = PROFILES[ver]
    addon_ver = get_addon_version()

    print(f"\n=======================================================")
    print(f" Launching Headless Kodi {ver} ({branch}) E2E Suite")
    print(f" Profile: {profile_dir}")
    print(f" Addon:   plugin.video.otaku.rpdev v{addon_ver}")
    print(f"=======================================================")

    subprocess.run(["flatpak", "kill", "tv.kodi.Kodi"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)

    kodi_env_bin = shutil.which("kodi-env") or "/usr/local/bin/kodi-env"
    if os.path.exists(kodi_env_bin):
        subprocess.run([kodi_env_bin, "link-addons"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if os.path.islink(SYMLINK_PATH) or os.path.exists(SYMLINK_PATH):
        try:
            os.unlink(SYMLINK_PATH)
        except OSError:
            pass
    try:
        os.symlink(profile_dir, SYMLINK_PATH)
    except OSError as e:
        print(f"  Warning: Could not create symlink {SYMLINK_PATH} -> {profile_dir}: {e}")

    enable_webserver_in_guisettings(profile_dir)
    write_addon_settings(profile_dir, {
        "setup_wizard_ran": "true",
        "changelog.version": addon_ver,
        "version": addon_ver,
        "otaku.version": addon_ver,
        "showchangelog": "1",
        "browser.api": "otaku",
        "titlelanguage": "0",
        "fs_enable": "false",
        "fs_url": fs_url,
        "fs_timeout": "40",
        "general.source": "0",
    })

    # Clear stale caches and logs prior to launching
    for stale_fn in ("domains.json", "cache.db", "cache.db-wal", "cache.db-shm"):
        stale_p = os.path.join(profile_dir, "userdata", "addon_data", "plugin.video.otaku.rpdev", stale_fn)
        if os.path.exists(stale_p):
            try:
                os.remove(stale_p)
            except OSError:
                pass

    log_path = os.path.join(profile_dir, "temp", "kodi.log")
    if os.path.exists(log_path):
        try:
            os.remove(log_path)
        except OSError:
            pass

    proc = subprocess.Popen(
        ["xvfb-run", "-a", "-s", "-screen 0 1920x1080x24", "flatpak", "run", f"--branch={branch}", "tv.kodi.Kodi", "--audio-backend=pulseaudio"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    tests = {}
    app_props = {}
    try:
        if not wait_for_kodi_rpc(max_wait=50.0):
            return {"boot_ok": False, "error": "JSON-RPC failed to come online within 50s"}

        time.sleep(3.5)

        app_props = jsonrpc("Application.GetProperties", {"properties": ["version", "name"]}).get("result", {})
        print(f"  Connected to {app_props.get('name')} {app_props.get('version')}")

        for aid in ("plugin.video.otaku.rpdev", "context.otaku.rpdev"):
            jsonrpc("Addons.SetAddonEnabled", {"addonid": aid, "enabled": True})
        addon_info = jsonrpc("Addons.GetAddonDetails", {"addonid": "plugin.video.otaku.rpdev", "properties": ["version", "enabled", "broken"]}).get("result", {}).get("addon", {})
        tests["addon_details"] = addon_info
        print(f"  Addon: {addon_info.get('addonid')} v{addon_info.get('version')} enabled={addon_info.get('enabled')} broken={addon_info.get('broken')}")

        # 1. Core Menus & Navigation
        menu_routes = [
            ("main_menu", "plugin://plugin.video.otaku.rpdev/"),
            ("movies_menu", "plugin://plugin.video.otaku.rpdev/movies"),
            ("tv_shows_menu", "plugin://plugin.video.otaku.rpdev/tv_shows"),
            ("ovas_menu", "plugin://plugin.video.otaku.rpdev/ovas"),
            ("onas_menu", "plugin://plugin.video.otaku.rpdev/onas"),
            ("trending_menu", "plugin://plugin.video.otaku.rpdev/trending"),
            ("popular_menu", "plugin://plugin.video.otaku.rpdev/popular"),
            ("genres_menu", "plugin://plugin.video.otaku.rpdev/genres"),
            ("search_menu", "plugin://plugin.video.otaku.rpdev/search"),
            ("tools_menu", "plugin://plugin.video.otaku.rpdev/tools"),
        ]
        for label, url in menu_routes:
            r = get_dir(url)
            if label == "main_menu":
                cal_items = [f for f in (r.get("files") or []) if "airing_calendar" in (f.get("file") or "")]
                tests["airing_calendar_isfolder_false"] = bool(cal_items and cal_items[0].get("filetype") == "file")
                print(f"  [Directory] airing_calendar filetype=='file' (isFolder=False) -> {tests['airing_calendar_isfolder_false']}")
            tests[label] = {k: v for k, v in r.items() if k != "files"}
            print(f"  [Menu] {label:<20} -> ok={r['ok']} items={r['count']} ({r['latency_ms']}ms)")

        # 1b. Airing Calendar Modal WindowXML Launch & Clean Close
        t_cal = time.perf_counter()
        jsonrpc("Addons.ExecuteAddon", {"addonid": "plugin.video.otaku.rpdev", "params": ["/airing_calendar"], "wait": False}, timeout=10.0)
        cal_opened = False
        cal_deadline = time.time() + 18.0
        while time.time() < cal_deadline:
            gw = jsonrpc("GUI.GetProperties", {"properties": ["currentwindow"]}, timeout=4.0).get("result", {}).get("currentwindow", {})
            if (gw.get("id") or 0) >= 13000:
                cal_opened = True
                break
            time.sleep(0.8)
        if cal_opened:
            jsonrpc("Input.Back", timeout=4.0)
            time.sleep(1.0)
        tests["airing_calendar_modal"] = {"opened": cal_opened, "latency_ms": int((time.perf_counter() - t_cal) * 1000)}
        print(f"  [Modal] airing_calendar Anichart -> opened={cal_opened} ({tests['airing_calendar_modal']['latency_ms']}ms)")

        # 2. Browser API Backends Flag Matrix (otaku / mal / anilist) + Search
        for api_backend in ("otaku", "mal", "anilist"):
            write_addon_settings(profile_dir, {"browser.api": api_backend, "titlelanguage": "0"})
            for rname, rpath in [
                (f"api_{api_backend}_airing_this_season", "plugin://plugin.video.otaku.rpdev/airing_this_season"),
                (f"api_{api_backend}_trending", "plugin://plugin.video.otaku.rpdev/trending_this_season"),
                (f"api_{api_backend}_top_100", "plugin://plugin.video.otaku.rpdev/top_100"),
                (f"api_{api_backend}_genre_action", "plugin://plugin.video.otaku.rpdev/genre_action"),
                (f"api_{api_backend}_search_frieren", "plugin://plugin.video.otaku.rpdev/search_anime/Frieren"),
            ]:
                r = get_dir(rpath, timeout=40.0)
                tests[rname] = {k: v for k, v in r.items() if k != "files"}
                print(f"  [BrowserAPI={api_backend}] {rname:<34} -> ok={r['ok']} items={r['count']} ({r['latency_ms']}ms)")

        # 3. Episodes & InfoTagVideo Metadata + Title Language Flag (0 Romaji vs 1 English)
        write_addon_settings(profile_dir, {"browser.api": "otaku", "titlelanguage": "0", "override.meta.api": "false", "interface.spoilers.hide_thumbs": "false"})
        ep_romaji = get_dir(
            "plugin://plugin.video.otaku.rpdev/animes/52991/",
            props=["title", "plot", "rating", "season", "episode", "year", "studio", "genre", "art"],
            timeout=45.0,
        )
        tests["episodes_frieren"] = {
            "ok": ep_romaji["ok"],
            "count": ep_romaji["count"],
            "latency_ms": ep_romaji["latency_ms"],
            "ep1_sample": ep_romaji["files"][0] if ep_romaji.get("files") else None,
        }
        print(f"  [Episodes/InfoTagVideo] animes/52991/ -> ok={ep_romaji['ok']} eps={ep_romaji['count']} ({ep_romaji['latency_ms']}ms)")

        # 3b. Spoiler Shield Flag (interface.spoilers.hide_thumbs = true)
        write_addon_settings(profile_dir, {"interface.spoilers.hide_thumbs": "true", "interface.spoilers.shield_mode": "0"})
        ep_spoiler = get_dir("plugin://plugin.video.otaku.rpdev/animes/52991/?spoiler_shield=true", props=["title", "plot", "art"], timeout=35.0)
        ep1_norm_thumb = ((ep_romaji["files"][0].get("art") or {}).get("thumb") if ep_romaji.get("files") else "") or ""
        ep1_spoil_thumb = ((ep_spoiler["files"][0].get("art") or {}).get("thumb") if ep_spoiler.get("files") else "") or ""
        tests["flag_spoiler_shield"] = {
            "ok": ep_spoiler["ok"],
            "normal_thumb": ep1_norm_thumb[-60:],
            "shield_thumb": ep1_spoil_thumb[-60:],
            "thumb_masked": ep1_norm_thumb != ep1_spoil_thumb,
        }
        write_addon_settings(profile_dir, {"interface.spoilers.hide_thumbs": "false"})
        print(f"  [Flag:SpoilerShield] thumb_masked={tests['flag_spoiler_shield']['thumb_masked']}")

        # 3c. Episode Meta API Override Matrix (simkl, anizip, jikanmoe, kitsu, otaku) + jz.dub + jz.filler
        for meta_backend in ("simkl", "anizip", "jikanmoe", "kitsu", "otaku"):
            jsonrpc("Addons.ExecuteAddon", {"addonid": "plugin.video.otaku.rpdev", "params": ["/clear_metadata_cache?setting=true"], "wait": True}, timeout=20.0)
            write_addon_settings(profile_dir, {"override.meta.api": "true", "meta.api": meta_backend, "jz.dub": "true", "jz.filler": "true"})
            rm = get_dir("plugin://plugin.video.otaku.rpdev/animes/52991/", timeout=40.0)
            tests[f"meta_api_{meta_backend}"] = {"ok": rm["ok"], "count": rm["count"], "latency_ms": rm["latency_ms"]}
            print(f"  [Flag:meta.api={meta_backend}] animes/52991/ -> ok={rm['ok']} eps={rm['count']} ({rm['latency_ms']}ms)")
        write_addon_settings(profile_dir, {"override.meta.api": "false", "jz.dub": "false", "jz.filler": "false"})

        write_addon_settings(profile_dir, {"browser.api": "otaku", "titlelanguage": "1"})
        top_eng = get_dir("plugin://plugin.video.otaku.rpdev/search_anime/Attack%20on%20Titan", timeout=35.0)
        write_addon_settings(profile_dir, {"browser.api": "otaku", "titlelanguage": "0"})
        top_rom = get_dir("plugin://plugin.video.otaku.rpdev/search_anime/Attack%20on%20Titan", timeout=35.0)
        tests["flag_titlelanguage"] = {
            "english_top5": top_eng.get("sample_labels"),
            "romaji_top5": top_rom.get("sample_labels"),
            "labels_differ": top_eng.get("sample_labels") != top_rom.get("sample_labels"),
        }
        print(f"  [Flag:titlelanguage] English vs Romaji labels differ = {tests['flag_titlelanguage']['labels_differ']}")

        # 4. Reviews Route
        rev = get_dir("plugin://plugin.video.otaku.rpdev/anime_reviews/52991/1", timeout=35.0)
        tests["anime_reviews_52991"] = {k: v for k, v in rev.items() if k != "files"}
        print(f"  [Reviews] anime_reviews/52991/1 -> ok={rev['ok']} items={rev['count']} ({rev['latency_ms']}ms)")

        # 5. Tools & Maintenance Routes (including domain refresh & cache clears)
        for tool_action in ("clean_settings", "check_db_integrity", "vacuum_databases", "clear_scraper_metrics", "update_network_status", "refresh_hianime_domains?setting=true", "clear_scrapers_cache?setting=true"):
            r_exec = jsonrpc("Addons.ExecuteAddon", {"addonid": "plugin.video.otaku.rpdev", "params": [f"/{tool_action}"], "wait": True}, timeout=25.0)
            tkey = tool_action.split("?")[0]
            tests[f"tool_{tkey}"] = "error" not in r_exec
            print(f"  [Tool] {tkey:<25} -> ok={'error' not in r_exec}")

        # 6. Live Playback Tests inside Kodi VideoPlayer (optional via flag)
        if not skip_playback:
            # 6a. All active embed providers (Sub, general.source=0) with FlareSolverr OFF
            jsonrpc("Addons.ExecuteAddon", {"addonid": "plugin.video.otaku.rpdev", "params": ["/clear_scrapers_cache?setting=true"], "wait": True}, timeout=20.0)
            time.sleep(2.5)
            pb_all_fs_off = test_autoplay_playback(profile_dir, fs_enable=False, fs_url=fs_url, only_wco=False)
            tests["playback_all_embeds_fs_off"] = pb_all_fs_off
            print(f"  [Playback:AllEmbeds Sub FS=OFF] -> {pb_all_fs_off}")
            time.sleep(2.5)

            # 6b. WatchNixtoons2 ONLY (Cloudflare-protected) with FlareSolverr ON
            jsonrpc("Addons.ExecuteAddon", {"addonid": "plugin.video.otaku.rpdev", "params": ["/clear_scrapers_cache?setting=true"], "wait": True}, timeout=20.0)
            time.sleep(2.5)
            pb_wco_fs_on = test_autoplay_playback(profile_dir, fs_enable=True, fs_url=fs_url, only_wco=True)
            tests["playback_wco_only_fs_on"] = pb_wco_fs_on
            print(f"  [Playback:WCO_Only FS=ON]       -> {pb_wco_fs_on}")
            time.sleep(2.5)

            # 6c. All active embed providers with FlareSolverr ON + SmartPlay & AniSkip ON
            jsonrpc("Addons.ExecuteAddon", {"addonid": "plugin.video.otaku.rpdev", "params": ["/clear_scrapers_cache?setting=true"], "wait": True}, timeout=20.0)
            time.sleep(2.5)
            pb_all_fs_on = test_autoplay_playback(profile_dir, fs_enable=True, fs_url=fs_url, only_wco=False, smartplay=True, dub_source=True)
            tests["playback_all_embeds_dub_smartplay_fs_on"] = pb_all_fs_on
            print(f"  [Playback:AllEmbeds Dub+SmartPlay FS=ON] -> {pb_all_fs_on}")

        # Clean shutdown via JSON-RPC Application.Quit
        jsonrpc("Application.Quit", timeout=10.0)
        try:
            proc.wait(timeout=15.0)
            clean_exit = True
        except subprocess.TimeoutExpired:
            clean_exit = False
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except Exception:
                pass
        tests["clean_shutdown"] = clean_exit
        print(f"  [Shutdown] Clean Application.Quit exit = {clean_exit}")

    finally:
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass
        subprocess.run(["flatpak", "kill", "tv.kodi.Kodi"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    log_summary = {"total_lines": 0, "otaku_errors": [], "python_tracebacks": [], "otaku_warnings": [], "otaku_cf_logs": []}
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8", errors="replace") as lf:
            lines = lf.readlines()
        log_summary["total_lines"] = len(lines)
        for i, line in enumerate(lines):
            low = line.lower()
            if "traceback (most recent call last)" in low or "exception thrown" in low:
                snippet = "".join(lines[i:min(i + 10, len(lines))]).strip()
                log_summary["python_tracebacks"].append(snippet[:600])
            if any(w in low for w in ("cloudflare", "flaresolverr", "ddos-guard", "collect tokens", "wcostream", "animepahe")):
                log_summary["otaku_cf_logs"].append(line.strip()[:260])
            if "otaku" in low:
                if " <error> " in low or "error:" in low:
                    log_summary["otaku_errors"].append(line.strip()[:260])
                elif " <warning> " in low or "warning:" in low:
                    log_summary["otaku_warnings"].append(line.strip()[:260])

    print(
        f"  [kodi.log] lines={log_summary['total_lines']} tracebacks={len(log_summary['python_tracebacks'])} "
        f"otaku_errors={len(log_summary['otaku_errors'])} otaku_warnings={len(log_summary['otaku_warnings'])} "
        f"cf_fs_logs={len(log_summary['otaku_cf_logs'])}"
    )
    return {"version": app_props, "tests": tests, "log_audit": log_summary}


def print_summary_table(results):
    """Print readable Markdown table summarizing test results."""
    print("\n=======================================================")
    print(" Headless Kodi E2E Test Execution Summary")
    print("=======================================================")
    print(f"| {'Kodi Target':<15} | {'Addon Broken':<12} | {'Menu Dirs':<10} | {'Modal':<8} | {'Playback (FS OFF)':<18} | {'Playback (WCO)':<15} | {'Errors/Tracebacks':<18} |")
    print(f"| {'-'*15} | {'-'*12} | {'-'*10} | {'-'*8} | {'-'*18} | {'-'*15} | {'-'*18} |")

    for kver in ("21", "22"):
        kdata = results.get(f"kodi{kver}")
        if not kdata or "tests" not in kdata:
            continue
        t = kdata["tests"]
        logs = kdata.get("log_audit", {})
        broken = str(t.get("addon_details", {}).get("broken", False))
        menu_ok = "PASS (10/10)" if all(t.get(m, {}).get("ok") for m in ("main_menu", "movies_menu", "tv_shows_menu", "ovas_menu", "onas_menu", "trending_menu", "popular_menu", "genres_menu", "search_menu", "tools_menu")) else "FAIL"
        modal = "PASS" if t.get("airing_calendar_modal", {}).get("opened") else "FAIL"
        pb_off = "PASS" if t.get("playback_all_embeds_fs_off", {}).get("playing") else ("SKIPPED" if "playback_all_embeds_fs_off" not in t else "FAIL")
        pb_wco = "PASS" if t.get("playback_wco_only_fs_on", {}).get("playing") else ("SKIPPED" if "playback_wco_only_fs_on" not in t else "FAIL")
        err_count = len(logs.get("otaku_errors", [])) + len(logs.get("python_tracebacks", []))
        err_str = "0 / 0" if err_count == 0 else f"{len(logs.get('otaku_errors', []))} err, {len(logs.get('python_tracebacks', []))} tb"

        ver_label = f"Kodi {kver} ({PROFILES[kver][0]})"
        print(f"| {ver_label:<15} | {broken:<12} | {menu_ok:<10} | {modal:<8} | {pb_off:<18} | {pb_wco:<15} | {err_str:<18} |")
    print("=======================================================\n")


def main():
    ap = argparse.ArgumentParser(description="Real-world headless Kodi 21 & Kodi 22 E2E integration test runner for Otaku-RPDev.")
    ap.add_argument("--versions", nargs="+", choices=["21", "22"], default=["21", "22"], help="Kodi versions to run (default: 21 22)")
    ap.add_argument("--tag", default="e2e_live", help="Test tag identifier (default: e2e_live)")
    ap.add_argument("--fs-url", default="http://127.0.0.1:8191/v1", help="FlareSolverr API URL (default: http://127.0.0.1:8191/v1)")
    ap.add_argument("--skip-playback", action="store_true", help="Skip live VideoPlayer playback tests")
    ap.add_argument("--out", default=None, help="Path to save output JSON report (optional)")
    args = ap.parse_args()

    out = {
        "tag": args.tag,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "addon_version": get_addon_version(),
    }
    for ver in args.versions:
        out[f"kodi{ver}"] = run_kodi_version_suite(ver, args.fs_url, skip_playback=args.skip_playback)

    print_summary_table(out)

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        print(f"Saved E2E report -> {args.out}")


if __name__ == "__main__":
    main()
