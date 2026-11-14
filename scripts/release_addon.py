#!/usr/bin/env python3
"""
RPDevs Add-on Release Orchestrator (scripts/release_addon.py)
=============================================================
Single-command, zero-error release orchestrator for plugin.video.otaku.rpdev.

Strictly adheres to the Tag-Based GitHub Actions Release Pipeline:
  1. Validates or updates version metadata across:
       - plugin.video.otaku.rpdev/addon.xml (version attribute & <news> summary)
       - plugin.video.otaku.rpdev/news.txt (<=32-char dividers & vX.Y.Z section)
       - plugin.video.otaku.rpdev/changelog.txt (Changelog vX.Y.Z (YYYY-MM-DD): block)
  2. Executes the mandatory Pre-Flight Verification Gate:
       - Ruff linter (ruff check)
       - Python bytecode compilation (python3 -m compileall -q)
       - Full unit/integration/lint test suite with warnings enabled (-W default)
       - Function-level coverage gate (audit_function_coverage.py --fail-below 60)
  3. Commits (--no-gpg-sign), tags (git tag -a vX.Y.Z --no-sign), and pushes
     both main and vX.Y.Z to origin (RPDevs-Builds/Otaku-RPDev).
  4. Monitors the GitHub Actions Release workflow (.github/workflows/release.yml)
     until completion and verifies uploaded GitHub Release assets
     (plugin.video.otaku.rpdev-X.Y.Z.zip, SHA256SUMS.txt, MD5SUMS.txt).
  5. Verifies live CDN propagation on https://kodi.repo.iamrp.dev/
     (addons.xml version match, addons.xml.md5 checksum match, and HTTP 200
     availability of https://kodi.repo.iamrp.dev/plugin.video.otaku.rpdev/plugin.video.otaku.rpdev-X.Y.Z.zip).

Usage Examples:
  # When addon.xml, news.txt, and changelog.txt are already updated for the target version:
  python3 scripts/release_addon.py

  # Automated version bump + metadata generation + release:
  python3 scripts/release_addon.py --bump patch --title "Short Banner Title" -m "Detailed changelog bullet 1\nDetailed changelog bullet 2"

  # Dry-run pre-flight validation without committing, tagging, or pushing:
  python3 scripts/release_addon.py --dry-run

  # Verify an already-published tag across GitHub Actions, GitHub Releases, and CDN:
  python3 scripts/release_addon.py --verify-tag v6.1.3
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

GITHUB_REPO = "RPDevs-Builds/Otaku-RPDev"
CDN_REPO = "rpdev-cdn/kodi.repo.iamrp.dev"
CDN_BASE_URL = "https://kodi.repo.iamrp.dev"
ADDON_ID = "plugin.video.otaku.rpdev"
MAX_NEWS_DIVIDER_LEN = 32


def run_cmd(cmd, cwd=None, check=True, capture=True):
    """Execute a subprocess command and return CompletedProcess."""
    print(f"  $ {cmd if isinstance(cmd, str) else ' '.join(cmd)}")
    res = subprocess.run(
        cmd,
        shell=isinstance(cmd, str),
        cwd=cwd,
        text=True,
        capture_output=capture,
    )
    if check and res.returncode != 0:
        print(f"\n[ERROR] Command failed (exit {res.returncode}): {cmd}", file=sys.stderr)
        if capture:
            if res.stdout:
                print(res.stdout, file=sys.stderr)
            if res.stderr:
                print(res.stderr, file=sys.stderr)
        sys.exit(res.returncode)
    return res


def get_addon_xml_version_and_news(addon_xml_path):
    """Return (version_str, news_text) from addon.xml."""
    tree = ET.parse(addon_xml_path)
    root = tree.getroot()
    ver = root.attrib.get("version", "").strip()
    news_el = root.find("./extension[@point='xbmc.addon.metadata']/news")
    news_txt = (news_el.text or "").strip() if news_el is not None else ""
    return ver, news_txt


def calculate_next_version(current_ver, bump_type="patch", explicit_ver=None):
    """Calculate next semantic version."""
    if explicit_ver:
        return explicit_ver.lstrip("v")
    parts = [int(x) for x in current_ver.split(".")]
    while len(parts) < 3:
        parts.append(0)
    if bump_type == "major":
        parts[0] += 1
        parts[1] = 0
        parts[2] = 0
    elif bump_type == "minor":
        parts[1] += 1
        parts[2] = 0
    else:
        parts[2] += 1
    return ".".join(str(x) for x in parts)


def update_addon_xml(addon_xml_path, new_ver, news_lines=None):
    """Update version attribute and optional <news> block in addon.xml preserving formatting."""
    with open(addon_xml_path, "r", encoding="utf-8") as f:
        content = f.read()

    new_content, count = re.subn(
        r'(<addon\b[^>]*?\bversion=")([^"]+)(")',
        rf"\g<1>{new_ver}\g<3>",
        content,
        count=1,
        flags=re.DOTALL,
    )
    if count == 0:
        raise RuntimeError(f"Failed to update version attribute in {addon_xml_path}")

    if news_lines:
        formatted_bullets = "\n".join(f"- {line.lstrip('- ').strip()}" for line in news_lines if line.strip())
        news_block = f"<news>[B]OTAKU RPDEV v{new_ver}[/B]\n{formatted_bullets}</news>"
        new_content, _ = re.subn(
            r"<news>.*?</news>",
             lambda _: news_block,
            new_content,
            count=1,
            flags=re.DOTALL,
        )

    with open(addon_xml_path, "w", encoding="utf-8") as f:
        f.write(new_content)


def update_news_txt(news_path, new_ver, title, highlights):
    """Prepend a new release block to news.txt with <=32-char dividers and demote prior === divider to ---."""
    with open(news_path, "r", encoding="utf-8") as f:
        old_content = f.read()

    # Demote previous top-level ================================ header to --------------------------------
    demoted_old = re.sub(
        r"^={16,}\n(\[B\]OTAKU RPDEV v[^\n]+\[/B\]\n[^\n]+\n)={16,}",
        r"--------------------------------\n\1--------------------------------",
        old_content.lstrip(),
        count=1,
    )

    bullet_blocks = []
    for raw_line in highlights:
        clean = raw_line.lstrip("-*• ").strip()
        if not clean:
            continue
        wrapped = textwrap.fill(
            clean,
            width=76,
            initial_indent="  * ",
            subsequent_indent="    ",
        )
        bullet_blocks.append(wrapped)

    header_title = (title or f"Release v{new_ver}").strip()
    new_section = (
        f"================================\n"
        f"[B]OTAKU RPDEV v{new_ver}[/B]\n"
        f"{header_title}\n"
        f"================================\n\n"
        f"v{new_ver} Highlights:\n"
        + "\n".join(bullet_blocks)
        + "\n\n"
    )

    with open(news_path, "w", encoding="utf-8") as f:
        f.write(new_section + demoted_old)


def update_changelog_txt(changelog_path, new_ver, title, bullets):
    """Prepend a new Changelog vX.Y.Z (YYYY-MM-DD): entry to changelog.txt."""
    today = datetime.date.today().strftime("%Y-%m-%d")
    old_content = ""
    if os.path.exists(changelog_path):
        with open(changelog_path, "r", encoding="utf-8") as f:
            old_content = f.read()

    header = f"Changelog v{new_ver} ({today}):\n"
    section_title = (title or f"Release v{new_ver}").strip()
    lines = [f"- {section_title}:"]
    for b in bullets:
        clean = b.lstrip("-*• ").strip()
        if clean:
            lines.append(f"  - {clean}")
    entry = header + "\n".join(lines) + "\n\n"

    with open(changelog_path, "w", encoding="utf-8") as f:
        f.write(entry + old_content.lstrip())


def validate_release_metadata(addon_xml_path, news_path, changelog_path, target_ver):
    """Verify addon.xml, news.txt, and changelog.txt all match target_ver and obey formatting rules."""
    errors = []

    xml_ver, xml_news = get_addon_xml_version_and_news(addon_xml_path)
    if xml_ver != target_ver:
        errors.append(f"addon.xml version is '{xml_ver}', expected '{target_ver}'")
    if xml_news and f"v{target_ver}" not in xml_news:
        errors.append(f"addon.xml <news> block does not reference v{target_ver}")

    if not os.path.isfile(news_path):
        errors.append(f"Missing {news_path}")
    else:
        with open(news_path, "r", encoding="utf-8") as f:
            news_content = f.read()
        if f"[B]OTAKU RPDEV v{target_ver}[/B]" not in news_content:
            errors.append(f"news.txt is missing '[B]OTAKU RPDEV v{target_ver}[/B]' header")
        for idx, line in enumerate(news_content.splitlines()[:40], 1):
            stripped = line.strip()
            if stripped and (set(stripped) == {"="} or set(stripped) == {"-"}):
                if len(stripped) > MAX_NEWS_DIVIDER_LEN:
                    errors.append(
                        f"news.txt line {idx} divider length is {len(stripped)} chars (max {MAX_NEWS_DIVIDER_LEN})"
                    )

    if not os.path.isfile(changelog_path):
        errors.append(f"Missing {changelog_path}")
    else:
        with open(changelog_path, "r", encoding="utf-8") as f:
            changelog_head = "".join(f.readline() for _ in range(15))
        if f"Changelog v{target_ver} " not in changelog_head:
            errors.append(f"changelog.txt does not start with 'Changelog v{target_ver} (YYYY-MM-DD):'")

    return errors


def run_preflight_gate(repo_root, with_flatpak_e2e=False):
    """Execute the mandatory 5-step pre-flight verification gate from AGENTS.md."""
    print("\n🧪 Step 2: Running Pre-Flight Verification Gate...")

    # 2a. Ruff Linter
    if shutil.which("ruff"):
        print("  • [1/4] Running Ruff linter (--select E9,F63,F7,F82)...")
        run_cmd(
            "ruff check --select E9,F63,F7,F82 plugin.video.otaku.rpdev context.otaku.rpdev tests scripts",
            cwd=repo_root,
        )
    else:
        print("  • [1/4] ruff not found in PATH; skipping standalone ruff binary (covered by unit lint test).")

    # 2b. Bytecode compilation
    print("  • [2/4] Verifying Python bytecode compilation...")
    run_cmd("python3 -m compileall -q plugin.video.otaku.rpdev context.otaku.rpdev tests scripts", cwd=repo_root)

    # 2c. Full unit/integration/lint suite with -W default
    print("  • [3/4] Running full test suite with -W default...")
    res = run_cmd("python3 -W default -m unittest discover -s tests -v", cwd=repo_root)
    # Summarize test count from stderr
    match = re.search(r"Ran (\d+) tests in [\d.]+s", res.stderr)
    test_count = match.group(1) if match else "all"
    print(f"    ✓ {test_count} tests passed with zero errors.")

    # 2d. Function-level coverage audit
    print("  • [4/4] Auditing function and module test coverage (--fail-below 60)...")
    cov_res = run_cmd("python3 scripts/audit_function_coverage.py --fail-below 60", cwd=repo_root)
    for line in cov_res.stdout.splitlines():
        if "Modules with tests:" in line or "Tested functions:" in line or "[PASS]" in line:
            print(f"    {line.strip()}")

    # Optional 2e. Hermetic Flatpak Kodi 21/22 E2E runner
    if with_flatpak_e2e:
        print("  • [5/5] Running hermetic Flatpak Kodi 21 & 22 E2E smoke test...")
        run_cmd("python3 scripts/run_flatpak_kodi_e2e.py", cwd=repo_root)


def ensure_gh_default_repo(repo_root):
    """Ensure gh CLI has RPDevs-Builds/Otaku-RPDev configured as default repository."""
    subprocess.run(
        ["gh", "repo", "set-default", GITHUB_REPO],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )


def watch_github_release_workflow(repo_root, tag_name, timeout_sec=300):
    """Wait for .github/workflows/release.yml triggered by tag_name to complete and succeed."""
    print(f"\n⚙️  Step 4: Monitoring GitHub Actions Release Pipeline for {tag_name}...")
    ensure_gh_default_repo(repo_root)

    run_id = None
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        res = subprocess.run(
            [
                "gh", "run", "list",
                "-R", GITHUB_REPO,
                "--workflow=release.yml",
                "--limit", "5",
                "--json", "databaseId,headBranch,status,conclusion,url",
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if res.returncode == 0 and res.stdout.strip():
            runs = json.loads(res.stdout)
            for run in runs:
                if run.get("headBranch") == tag_name:
                    run_id = run.get("databaseId")
                    status = run.get("status")
                    conclusion = run.get("conclusion")
                    run_url = run.get("url", "")
                    if status == "completed":
                        if conclusion == "success":
                            print(f"  ✓ GitHub Actions workflow run #{run_id} succeeded ({run_url})")
                            return run_id
                        raise RuntimeError(
                            f"GitHub Actions workflow run #{run_id} failed with conclusion '{conclusion}' ({run_url})"
                        )
                    break
        if run_id:
            print(f"  • Watching workflow run #{run_id} to completion...")
            watch_res = subprocess.run(
                ["gh", "run", "watch", str(run_id), "-R", GITHUB_REPO, "--exit-status"],
                cwd=repo_root,
            )
            if watch_res.returncode != 0:
                raise RuntimeError(f"GitHub Actions workflow run #{run_id} failed during execution.")
            print(f"  ✓ Workflow run #{run_id} completed successfully.")
            return run_id
        time.sleep(3)

    raise TimeoutError(f"Timed out waiting for release.yml workflow for tag {tag_name}")


def verify_github_release_assets(repo_root, tag_name, version):
    """Verify GitHub Release exists and has the zip, SHA256SUMS.txt, and MD5SUMS.txt assets."""
    print(f"\n📦 Step 5: Verifying GitHub Release Assets for {tag_name}...")
    res = run_cmd(
        ["gh", "release", "view", tag_name, "-R", GITHUB_REPO, "--json", "name,url,assets"],
        cwd=repo_root,
    )
    data = json.loads(res.stdout)
    assets = {a["name"]: a["size"] for a in data.get("assets", [])}
    expected_zip = f"{ADDON_ID}-{version}.zip"
    required = [expected_zip, "SHA256SUMS.txt", "MD5SUMS.txt"]
    missing = [r for r in required if r not in assets]
    if missing:
        raise RuntimeError(f"GitHub Release {tag_name} is missing required assets: {missing}")

    print(f"  ✓ GitHub Release: {data.get('name')} ({data.get('url')})")
    for name in required:
        print(f"    • {name} ({assets[name]:,} bytes)")


def fetch_url_text(url, timeout=10):
    """Fetch text content from URL with cache-busting query string."""
    sep = "&" if "?" in url else "?"
    bust_url = f"{url}{sep}_t={int(time.time())}"
    req = urllib.request.Request(bust_url, headers={"User-Agent": "RPDevs-Release-Verifier/1.0", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace"), resp.status


def head_url_status(url, timeout=10):
    """Perform HTTP HEAD request and return (status_code, content_length)."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "RPDevs-Release-Verifier/1.0", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, int(resp.headers.get("Content-Length", "0") or 0)


def verify_live_cdn(version, timeout_sec=180):
    """Poll https://kodi.repo.iamrp.dev until addons.xml, addons.xml.md5, and the release zip are live."""
    print(f"\n🌐 Step 6: Verifying Live CDN Propagation ({CDN_BASE_URL})...")
    addons_xml_url = f"{CDN_BASE_URL}/addons.xml"
    addons_md5_url = f"{CDN_BASE_URL}/addons.xml.md5"
    zip_url = f"{CDN_BASE_URL}/{ADDON_ID}/{ADDON_ID}-{version}.zip"

    deadline = time.time() + timeout_sec
    last_seen_ver = None

    while time.time() < deadline:
        try:
            xml_text, _ = fetch_url_text(addons_xml_url)
            md5_text, _ = fetch_url_text(addons_md5_url)
            remote_md5 = md5_text.strip().split()[0] if md5_text.strip() else ""
            computed_md5 = hashlib.md5(xml_text.encode("utf-8")).hexdigest()

            root = ET.fromstring(xml_text)
            addon_node = root.find(f"./addon[@id='{ADDON_ID}']")
            last_seen_ver = addon_node.attrib.get("version") if addon_node is not None else None

            if last_seen_ver == version and remote_md5 == computed_md5:
                status_code, content_len = head_url_status(zip_url)
                if status_code == 200 and content_len > 0:
                    print(f"  ✓ Live CDN addons.xml version verified: v{last_seen_ver}")
                    print(f"  ✓ Live CDN addons.xml.md5 verified:     {remote_md5}")
                    print(f"  ✓ Live CDN archive verified (HTTP 200): {zip_url} ({content_len:,} bytes)")
                    return True
        except Exception:
            pass
        time.sleep(5)

    raise TimeoutError(
        f"Live CDN did not propagate v{version} within {timeout_sec}s (last seen version: {last_seen_ver})."
    )


def main():
    parser = argparse.ArgumentParser(
        description="Single-command Tag-Based Release Orchestrator for plugin.video.otaku.rpdev"
    )
    parser.add_argument(
        "--version",
        dest="explicit_version",
        help="Explicit target version (e.g. 6.1.4). Defaults to current addon.xml version if already bumped, or calculates next bump.",
    )
    parser.add_argument(
        "--bump",
        choices=["patch", "minor", "major"],
        default=None,
        help="Semantic version bump to apply if addon.xml has not already been bumped.",
    )
    parser.add_argument(
        "--title",
        default="",
        help="Short release banner title for news.txt (<=32 chars recommended) when bumping via CLI.",
    )
    parser.add_argument(
        "-m",
        "--message",
        default="",
        help="Newline-separated or semicolon-separated changelog/news bullet items when bumping via CLI.",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip pre-flight test gate (not recommended for production releases).",
    )
    parser.add_argument(
        "--with-flatpak-e2e",
        action="store_true",
        help="Also run the headless Flatpak Kodi 21 & 22 E2E runner during pre-flight.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run metadata validation and pre-flight tests without committing, tagging, or pushing.",
    )
    parser.add_argument(
        "--verify-tag",
        default="",
        help="Verify an already-published tag (e.g. v6.1.3) across local metadata, GitHub Actions, GitHub Release, and CDN.",
    )
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    addon_dir = os.path.join(repo_root, ADDON_ID)
    addon_xml_path = os.path.join(addon_dir, "addon.xml")
    news_path = os.path.join(addon_dir, "news.txt")
    changelog_path = os.path.join(addon_dir, "changelog.txt")

    print("═══════════════════════════════════════════════════════════════════════════")
    print(f" 🚀 RPDevs Tag-Based Release Orchestrator ({GITHUB_REPO})")
    print("═══════════════════════════════════════════════════════════════════════════")

    ensure_gh_default_repo(repo_root)

    # Mode A: Verify an existing release tag
    if args.verify_tag:
        tag_name = args.verify_tag if args.verify_tag.startswith("v") else f"v{args.verify_tag}"
        ver = tag_name.lstrip("v")
        print(f"Mode: Verify Published Release ({tag_name})")
        errors = validate_release_metadata(addon_xml_path, news_path, changelog_path, ver)
        if errors:
            for e in errors:
                print(f"  [ERROR] {e}", file=sys.stderr)
            sys.exit(1)
        print(f"  ✓ Local release metadata (addon.xml, news.txt, changelog.txt) verified for v{ver}.")
        watch_github_release_workflow(repo_root, tag_name)
        verify_github_release_assets(repo_root, tag_name, ver)
        verify_live_cdn(ver)
        print("\n═══════════════════════════════════════════════════════════════════════════")
        print(f" ✅ VERIFIED: {tag_name} is live on GitHub Releases and CDN!")
        print("═══════════════════════════════════════════════════════════════════════════")
        return

    # Determine current version vs target version
    current_xml_ver, _ = get_addon_xml_version_and_news(addon_xml_path)
    existing_tags_res = run_cmd("git tag -l 'v*'", cwd=repo_root)
    existing_tags = set(existing_tags_res.stdout.split())

    if args.explicit_version or args.bump:
        target_ver = calculate_next_version(current_xml_ver, args.bump or "patch", args.explicit_version)
    else:
        # If current addon.xml version doesn't have a git tag yet, assume metadata was already updated for release
        if f"v{current_xml_ver}" not in existing_tags:
            target_ver = current_xml_ver
        else:
            target_ver = calculate_next_version(current_xml_ver, "patch")

    tag_name = f"v{target_ver}"
    print(f"Current addon.xml Version: v{current_xml_ver}")
    print(f"Target Release Version:    {tag_name}")

    # Step 1: Prepare or validate metadata
    print(f"\n📝 Step 1: Validating Release Metadata for {tag_name}...")
    metadata_errors = validate_release_metadata(addon_xml_path, news_path, changelog_path, target_ver)
    if metadata_errors:
        if args.message:
            raw_bullets = [
                b.strip()
                for b in re.split(r"\\n|\n|;", args.message)
                if b.strip()
            ]
            title = args.title.strip() or raw_bullets[0][:MAX_NEWS_DIVIDER_LEN]
            if not args.dry_run:
                update_addon_xml(addon_xml_path, target_ver, raw_bullets)
                update_news_txt(news_path, target_ver, title, raw_bullets)
                update_changelog_txt(changelog_path, target_ver, title, raw_bullets)
                metadata_errors = validate_release_metadata(addon_xml_path, news_path, changelog_path, target_ver)
                if metadata_errors:
                    for err in metadata_errors:
                        print(f"  [ERROR] {err}", file=sys.stderr)
                    sys.exit(1)
                print(f"  ✓ Automatically updated addon.xml, news.txt, and changelog.txt to v{target_ver}.")
            else:
                print(f"  [DRY RUN] Would update addon.xml, news.txt, and changelog.txt to v{target_ver}.")
        else:
            print("  [ERROR] Release metadata is not yet prepared for target version:", file=sys.stderr)
            for err in metadata_errors:
                print(f"    • {err}", file=sys.stderr)
            print(
                "\n  Either update addon.xml, news.txt, and changelog.txt first, or pass --bump patch --title \"...\" -m \"...\"",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        print(f"  ✓ addon.xml, news.txt (<=32-char dividers), and changelog.txt verified for v{target_ver}.")

    # Step 2: Pre-Flight Verification Gate
    if not args.skip_tests:
        run_preflight_gate(repo_root, with_flatpak_e2e=args.with_flatpak_e2e)
    else:
        print("\n⚠️  Step 2: Skipping pre-flight test suite (--skip-tests)")

    if args.dry_run:
        print("\n═══════════════════════════════════════════════════════════════════════════")
        print(f" [DRY RUN] Pre-flight gate passed for {tag_name}. No git commits or tags created.")
        print("═══════════════════════════════════════════════════════════════════════════")
        return

    # Step 3: Commit, Tag, and Push
    print(f"\n🐙 Step 3: Committing, Tagging ({tag_name}), and Pushing to {GITHUB_REPO}...")
    status_res = run_cmd("git status --porcelain", cwd=repo_root)
    if status_res.stdout.strip():
        run_cmd("git add -A", cwd=repo_root)
        summary_title = args.title.strip() or f"release {tag_name}"
        commit_msg = f"chore(release): {tag_name} - {summary_title}"
        run_cmd(["git", "commit", "--no-gpg-sign", "-m", commit_msg], cwd=repo_root)
        print(f"  ✓ Created release commit: {commit_msg}")
    else:
        print("  • Working tree already clean; proceeding to tag HEAD.")

    if tag_name in existing_tags:
        print(f"  [ERROR] Tag {tag_name} already exists locally. Use --verify-tag {tag_name} to verify it.", file=sys.stderr)
        sys.exit(1)

    tag_msg = f"Release {tag_name}" + (f": {args.title.strip()}" if args.title.strip() else "")
    run_cmd(["git", "tag", "-a", tag_name, "-m", tag_msg, "--no-sign"], cwd=repo_root)
    run_cmd(["git", "push", "origin", "main", tag_name], cwd=repo_root)
    print(f"  ✓ Pushed main and {tag_name} to origin.")

    # Step 4, 5, 6: Monitor CI workflow, verify GitHub Release assets, verify Live CDN
    watch_github_release_workflow(repo_root, tag_name)
    verify_github_release_assets(repo_root, tag_name, target_ver)
    verify_live_cdn(target_ver)

    print("\n═══════════════════════════════════════════════════════════════════════════")
    print(f" 🎉 RELEASE {tag_name} COMPLETE, VERIFIED ON GITHUB RELEASES & LIVE ON CDN!")
    print("═══════════════════════════════════════════════════════════════════════════")


if __name__ == "__main__":
    main()
