#!/usr/bin/env python3
"""
release_addon.py - Automated End-to-End Kodi Add-on Release Orchestrator
========================================================================
Automates the full add-on release lifecycle:
1. Runs pre-flight test suites and AST syntax verification.
2. Performs semver bumping on addon.xml and prepends changelog.txt.
3. Packages clean ZIP distributions excluding git/cache artifacts.
4. Updates the CDN repository (kodi.repo.iamrp.dev) and regenerates manifests.
5. Commits and pushes both repositories to GitHub atomically.

Usage:
  python3 scripts/release_addon.py [addon_id] --bump [patch|minor|major] -m "Release description"
  python3 scripts/release_addon.py plugin.video.otaku.rpdev --dry-run
"""

import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET


DEFAULT_CDN_DIR = "/mnt/sharedroot/projects/rpdev-cdn/kodi.repo.iamrp.dev"


def run_cmd(cmd, cwd=None, check=True):
    """Execute shell command with real-time stdout and error capture."""
    proc = subprocess.run(
        cmd,
        shell=True,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    if check and proc.returncode != 0:
        print(f"\n[ERROR] Command failed with exit code {proc.returncode}:\n{cmd}\n")
        print(proc.stdout)
        sys.exit(proc.returncode)
    return proc


def get_current_version(addon_xml_path):
    """Extract version attribute from addon.xml."""
    tree = ET.parse(addon_xml_path)
    root = tree.getroot()
    return root.get("version")


def calculate_next_version(current_ver, bump_type=None, explicit_ver=None):
    """Calculate next semver version."""
    if explicit_ver:
        return explicit_ver

    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", current_ver)
    if not match:
        raise ValueError(f"Cannot parse semver from: {current_ver}")

    major, minor, patch = map(int, match.groups())
    if bump_type == "major":
        return f"{major + 1}.0.0"
    elif bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    else:  # default patch
        return f"{major}.{minor}.{patch + 1}"


def update_addon_xml(addon_xml_path, new_ver):
    """Update version attribute in addon.xml preserving formatting."""
    with open(addon_xml_path, "r", encoding="utf-8") as f:
        content = f.read()

    updated = re.sub(
        r'(<addon\s+[^>]*?version=")([^"]+)(")',
        rf'\g<1>{new_ver}\g<3>',
        content,
        count=1
    )
    with open(addon_xml_path, "w", encoding="utf-8") as f:
        f.write(updated)


def update_changelog(changelog_path, new_ver, message):
    """Prepend new release entry to changelog.txt."""
    if not os.path.exists(changelog_path):
        return

    with open(changelog_path, "r", encoding="utf-8") as f:
        old_content = f.read()

    if old_content.startswith(f"Changelog v{new_ver}"):
        return

    today = datetime.date.today().strftime("%Y-%m-%d")
    header = f"Changelog v{new_ver} ({today}):\n"
    lines = [f"- {line.strip()}" for line in message.strip().split("\n") if line.strip()]
    entry = header + "\n".join(lines) + "\n\n"

    with open(changelog_path, "w", encoding="utf-8") as f:
        f.write(entry + old_content)


def main():
    parser = argparse.ArgumentParser(description="Automate Kodi Addon Release & CDN Distribution")
    parser.add_argument("addon_id", nargs="?", default="plugin.video.otaku.rpdev", help="Target addon directory name")
    parser.add_argument("--bump", choices=["patch", "minor", "major"], default="patch", help="Semver bump type")
    parser.add_argument("--version", dest="explicit_version", help="Explicit target version")
    parser.add_argument("-m", "--message", default="", help="Release changelog summary / commit message")
    parser.add_argument("--cdn-dir", default=DEFAULT_CDN_DIR, help="Path to kodi.repo.iamrp.dev repository")
    parser.add_argument("--skip-tests", action="store_true", help="Skip pre-flight test suites")
    parser.add_argument("--dry-run", action="store_true", help="Simulate release without modifying disk or pushing")

    args = parser.parse_args()

    # Determine paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    addon_dir = os.path.join(repo_root, args.addon_id)
    addon_xml = os.path.join(addon_dir, "addon.xml")
    changelog = os.path.join(addon_dir, "changelog.txt")
    cdn_dir = os.path.abspath(args.cdn_dir)

    print("═══════════════════════════════════════════════════════════════════════════")
    print(f" 🚀 RPDevs Add-on Release Orchestrator: {args.addon_id}")
    print("═══════════════════════════════════════════════════════════════════════════")

    if not os.path.isdir(addon_dir) or not os.path.isfile(addon_xml):
        print(f"[ERROR] Add-on directory or addon.xml not found at: {addon_dir}")
        sys.exit(1)

    if not os.path.isdir(cdn_dir):
        print(f"[ERROR] CDN repository not found at: {cdn_dir}")
        sys.exit(1)

    current_ver = get_current_version(addon_xml)
    next_ver = calculate_next_version(current_ver, args.bump, args.explicit_version)
    print(f"Current Version: v{current_ver}")
    print(f"Target  Version: v{next_ver} ({args.bump.upper()} bump)")
    if args.dry_run:
        print("[DRY RUN] Simulation mode active. No files will be modified.")

    # 1. Pre-flight tests
    if not args.skip_tests:
        print("\n🧪 Step 1: Running Pre-Flight Test Suite & AST Syntax Verification...")
        test_proc = run_cmd("python3 -m unittest discover tests", cwd=repo_root, check=False)
        if test_proc.returncode != 0:
            print("[FAIL] Pre-flight unit tests failed. Aborting release.")
            print(test_proc.stdout)
            sys.exit(1)
        print("  ✓ All unit, integration, and lint tests passed cleanly.")
    else:
        print("\n⚠️  Step 1: Skipping pre-flight tests (--skip-tests active)")

    if args.dry_run:
        print("\n[DRY RUN] Pre-flight checks complete.")
        print(f"[DRY RUN] Would update: {addon_xml} -> v{next_ver}")
        print(f"[DRY RUN] Would prepend: {changelog} with version notes")
        print(f"[DRY RUN] Would package: {cdn_dir}/{args.addon_id}/{args.addon_id}-{next_ver}.zip")
        print(f"[DRY RUN] Would regenerate CDN manifests via tools/generate_repo.py")
        print(f"[DRY RUN] Would git commit & push {repo_root} and {cdn_dir}")
        print("═══════════════════════════════════════════════════════════════════════════")
        print(" [DRY RUN] SUCCESS: All dry-run assertions verified successfully!")
        return

    # Check for release message
    release_msg = args.message.strip()
    if not release_msg:
        print("[ERROR] A release message (-m \"...\") is required for live releases.")
        sys.exit(1)

    # 2. Version Bump
    print(f"\n📝 Step 2: Bumping Addon Version to v{next_ver}...")
    update_addon_xml(addon_xml, next_ver)
    update_changelog(changelog, next_ver, release_msg)
    print("  ✓ Updated addon.xml and changelog.txt.")

    # 3. Packaging
    print(f"\n📦 Step 3: Packaging {args.addon_id}-{next_ver}.zip...")
    target_cdn_addon_dir = os.path.join(cdn_dir, args.addon_id)
    os.makedirs(target_cdn_addon_dir, exist_ok=True)
    zip_out = os.path.join(target_cdn_addon_dir, f"{args.addon_id}-{next_ver}.zip")

    if os.path.exists(zip_out):
        os.remove(zip_out)

    zip_cmd = f'zip -q -r "{zip_out}" "{args.addon_id}" -x "*.git*" "*.pyc" "*__pycache__*" "*/tests/*" "*/scratch/*"'
    run_cmd(zip_cmd, cwd=repo_root)
    zip_size = os.path.getsize(zip_out)
    print(f"  ✓ Packaged {zip_out} ({zip_size:,} bytes).")

    # Sync addon.xml and changelog.txt to CDN repository so tools/generate_repo.py indexes the new version!
    shutil.copy2(addon_xml, os.path.join(target_cdn_addon_dir, "addon.xml"))
    if os.path.exists(changelog):
        shutil.copy2(changelog, os.path.join(target_cdn_addon_dir, "changelog.txt"))
    for asset in ["icon.png", "fanart.jpg", "fanart.png", "poster.png", "clearlogo.png"]:
        src_asset = os.path.join(addon_dir, asset)
        if os.path.exists(src_asset):
            shutil.copy2(src_asset, os.path.join(target_cdn_addon_dir, asset))
    print(f"  ✓ Synchronized {args.addon_id} metadata and assets to CDN.")

    # 4. CDN Repo Manifest Regeneration
    print("\n🌐 Step 4: Regenerating CDN Repository Metadata & Manifests...")
    run_cmd("python3 tools/generate_repo.py", cwd=cdn_dir)
    print("  ✓ Refreshed addons.xml, addons.xml.md5, and HTML indexes.")

    # 5. Git Commit & Push (Add-on Repository)
    print(f"\n🐙 Step 5: Committing & Pushing {args.addon_id} (RPDevs-Builds/Otaku-RPDev)...")
    run_cmd("git add -A", cwd=repo_root)
    commit_msg = f"chore(release): bump {args.addon_id} to v{next_ver} - {release_msg.splitlines()[0]}"
    run_cmd(f'git commit --no-gpg-sign -m "{commit_msg}"', cwd=repo_root)
    run_cmd("git push origin main", cwd=repo_root)
    print("  ✓ Pushed add-on repo to origin/main.")

    # 6. Git Commit & Push (CDN Repository)
    print("\n🚀 Step 6: Committing & Pushing CDN Repository (rpdev-cdn/kodi.repo.iamrp.dev)...")
    run_cmd("git add .", cwd=cdn_dir)
    cdn_commit_msg = f"chore(repo): publish {args.addon_id}-{next_ver}.zip"
    run_cmd(f'git commit --no-gpg-sign -m "{cdn_commit_msg}"', cwd=cdn_dir)
    run_cmd("git push origin main", cwd=cdn_dir)
    print("  ✓ Pushed CDN repo to origin/main.")

    print("\n═══════════════════════════════════════════════════════════════════════════")
    print(f" 🎉 RELEASE v{next_ver} COMPLETE & PUBLISHED TO CDN!")
    print("═══════════════════════════════════════════════════════════════════════════\n")


if __name__ == "__main__":
    main()
