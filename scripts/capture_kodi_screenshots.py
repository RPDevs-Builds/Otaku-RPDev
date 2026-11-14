#!/usr/bin/env python3
"""
capture_kodi_screenshots.py — Standalone Screenshot Capture Tool for Otaku-RPDev
================================================================================
Dedicated utility script to launch local Flatpak Kodi 22 on an isolated Xvfb
1920x1080 display and capture high-resolution showcase screenshots of Otaku-RPDev
dialogs and settings into plugin.video.otaku.rpdev/resources/screenshots/.

Note: This script is strictly for capturing screenshots on demand and is never
executed during unit or E2E test runs.

Usage:
  python3 scripts/capture_kodi_screenshots.py
"""

import os
import signal
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from scripts.kodi_e2e_mock_server import LocalMockServer
from scripts.test_kodi_installs import (
    ADDON_DIR,
    DEFAULT_MAIN_MENU_ITEMS,
    PROFILES,
    SYMLINK_PATH,
    enable_webserver_in_guisettings,
    get_addon_version,
    jsonrpc,
    seed_test_databases,
    wait_for_kodi_rpc,
    write_addon_settings,
)

SCREENSHOT_DIR = os.path.join(ADDON_DIR, "resources", "screenshots")
DISPLAY_NUM = ":98"


def capture_x11_screenshot(out_path: str) -> bool:
    """Capture the 1920x1080 Xvfb root window using ImageMagick import."""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY_NUM
    res = subprocess.run(
        ["import", "-window", "root", "-quality", "92", out_path],
        env=env,
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    return res.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 5000


def wait_for_window(min_id: int = 10100, timeout: float = 12.0) -> int:
    """Wait until a target modal window ID is active."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            gw = jsonrpc("GUI.GetProperties", {"properties": ["currentwindow"]}, timeout=3.0).get("result", {}).get("currentwindow", {})
            wid = gw.get("id") or 0
            if wid >= min_id and wid != 10138:
                return wid
        except Exception:
            pass
        time.sleep(0.35)
    return 0


def dismiss_modal():
    """Send Input.Back to close the active dialog."""
    for _ in range(3):
        try:
            jsonrpc("Input.Back", timeout=3.0)
        except Exception:
            pass
        time.sleep(0.4)


def main():
    branch, profile_dir = PROFILES["22"]
    addon_ver = get_addon_version()
    print(f"=== Launching Local Kodi 22 ({branch}) on Xvfb {DISPLAY_NUM} for Screenshot Capture ===")

    subprocess.run(["flatpak", "kill", "tv.kodi.Kodi"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-f", f"Xvfb {DISPLAY_NUM}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)

    if os.path.islink(SYMLINK_PATH) or os.path.exists(SYMLINK_PATH):
        try:
            os.unlink(SYMLINK_PATH)
        except OSError:
            pass
    os.symlink(profile_dir, SYMLINK_PATH)

    enable_webserver_in_guisettings(profile_dir)

    mock_server = LocalMockServer(port=0)
    mock_server.start()
    mock_url = mock_server.get_base_url()

    initial_settings = {
        "setup_wizard_ran": "true",
        "changelog.version": addon_ver,
        "version": addon_ver,
        "otaku.version": addon_ver,
        "showchangelog": "1",
        "browser.api": "otaku",
        "titlelanguage": "0",
        "general.source": "0",
        "jz.dub": "false",
        "jz.filler": "false",
        "override.meta.api": "true",
        "meta.api": "otaku",
        "fs_enable": "true",
        "fs_url": f"{mock_url}/v1",
        "fs_timeout": "60",
        "ms_enable": "true",
        "ms_url": f"{mock_url}/ms",
        "webpdb.enabled": "true",
        "webpdb.port": "5566",
        "webpdb.mode": "0",
    }
    write_addon_settings(profile_dir, initial_settings)
    seed_test_databases(profile_dir)

    xvfb_proc = subprocess.Popen(
        ["Xvfb", DISPLAY_NUM, "-screen", "0", "1920x1080x24", "-ac"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    time.sleep(1.0)

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY_NUM
    kodi_proc = subprocess.Popen(
        ["flatpak", "run", f"--branch={branch}", "tv.kodi.Kodi", "--audio-backend=pulseaudio"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    try:
        if not wait_for_kodi_rpc(max_wait=50.0):
            print("[ERROR] Kodi JSON-RPC did not come online within 50s", file=sys.stderr)
            sys.exit(1)

        # Disable unrelated third-party add-ons so startup toasts never photobomb screenshots
        for noisy_addon in ("plugin.video.umbrella", "plugin.program.autowidget", "plugin.video.themoviedb.helper"):
            try:
                jsonrpc("Addons.SetAddonEnabled", {"addonid": noisy_addon, "enabled": False})
            except Exception:
                pass

        for aid in ("plugin.video.otaku.rpdev", "context.otaku.rpdev"):
            jsonrpc("Addons.SetAddonEnabled", {"addonid": aid, "enabled": True})

        # Wait for any initial startup toast notifications to fade out completely
        time.sleep(6.0)

        # 1. Screenshot 05: News & Changelog Viewer (textviewer.xml)
        print("  [1/4] Capturing screenshot-05.jpg (News & Changelog Dual-Pane Viewer)...")
        jsonrpc("Addons.ExecuteAddon", {"addonid": "plugin.video.otaku.rpdev", "params": ["/change_log"], "wait": False})
        wait_for_window(13000, 12.0)
        time.sleep(2.0)
        s05 = os.path.join(SCREENSHOT_DIR, "screenshot-05.jpg")
        capture_x11_screenshot(s05)
        print(f"        Saved {s05} ({os.path.getsize(s05):,} bytes)")
        dismiss_modal()
        time.sleep(1.0)

        # 2. Screenshot 06: Interactive Menu Order & Visibility Customizer (menu_order.xml)
        print("  [2/4] Capturing screenshot-06.jpg (Menu Order & Visibility Customizer)...")
        jsonrpc("Addons.ExecuteAddon", {"addonid": "plugin.video.otaku.rpdev", "params": ["/menu_order"], "wait": False})
        wait_for_window(13000, 12.0)
        time.sleep(2.0)
        s06 = os.path.join(SCREENSHOT_DIR, "screenshot-06.jpg")
        capture_x11_screenshot(s06)
        print(f"        Saved {s06} ({os.path.getsize(s06):,} bytes)")
        dismiss_modal()
        time.sleep(1.0)

        # 3. Screenshot 07: Hierarchical Source Sort Selection Dialog (sort_select.xml)
        print("  [3/4] Capturing screenshot-07.jpg (Hierarchical Source Sort Configuration)...")
        jsonrpc("Addons.ExecuteAddon", {"addonid": "plugin.video.otaku.rpdev", "params": ["/sort_select"], "wait": False})
        wait_for_window(13000, 12.0)
        time.sleep(2.0)
        s07 = os.path.join(SCREENSHOT_DIR, "screenshot-07.jpg")
        capture_x11_screenshot(s07)
        print(f"        Saved {s07} ({os.path.getsize(s07):,} bytes)")
        dismiss_modal()
        time.sleep(1.0)

        # 4. Screenshot 08: Otaku RPDev Settings -> Maintenance -> Web-PDB & Tooltips
        print("  [4/4] Capturing screenshot-08.jpg (Settings -> Maintenance -> Web-PDB & Tooltips)...")
        jsonrpc("Addons.ExecuteAddon", {"addonid": "plugin.video.otaku.rpdev", "params": ["/settings"], "wait": False})
        wait_for_window(10140, 12.0)
        time.sleep(1.5)
        # Navigate to Maintenance category (bottom of left category list)
        jsonrpc("Input.Up")
        time.sleep(0.5)
        # Move right into Maintenance settings and scroll down to Web-PDB section
        jsonrpc("Input.Right")
        time.sleep(0.4)
        for _ in range(19):
            jsonrpc("Input.Down")
            time.sleep(0.15)
        time.sleep(1.0)
        s08 = os.path.join(SCREENSHOT_DIR, "screenshot-08.jpg")
        capture_x11_screenshot(s08)
        print(f"        Saved {s08} ({os.path.getsize(s08):,} bytes)")
        dismiss_modal()

        jsonrpc("Application.Quit", timeout=10.0)
        try:
            kodi_proc.wait(timeout=20.0)
        except subprocess.TimeoutExpired:
            pass
    finally:
        if kodi_proc.poll() is None:
            try:
                os.killpg(os.getpgid(kodi_proc.pid), signal.SIGKILL)
            except Exception:
                pass
        subprocess.run(["flatpak", "kill", "tv.kodi.Kodi"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if xvfb_proc.poll() is None:
            try:
                os.killpg(os.getpgid(xvfb_proc.pid), signal.SIGTERM)
            except Exception:
                pass
        mock_server.stop()


if __name__ == "__main__":
    main()
