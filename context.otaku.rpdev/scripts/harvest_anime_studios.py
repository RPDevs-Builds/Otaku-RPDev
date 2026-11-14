#!/usr/bin/env python3
"""
harvest_anime_studios.py - Anime Studio Logo Harvester & Packager for Kodi
========================================================================
Collects high-resolution transparent vector/PNG logos for Japanese animation
studios from Wikimedia Commons and Wikipedia, standardizes dimensions, and
generates two production-ready Kodi image resource add-ons:
  1. resource.images.animestudio.coloured (Full color transparent PNGs)
  2. resource.images.animestudio.white (Monochrome white transparent PNGs)

Author: RPDevs
License: GPL-3.0
"""

import io
import json
import os
import re
import shutil
import sys
import urllib.parse
import urllib.request
from PIL import Image, ImageDraw, ImageFont

TARGET_ROOT = "/mnt/sharedroot/projects/RPDevs-Builds/Otaku-RPDev"
COLOURED_ADDON_ID = "resource.images.animestudio.coloured"
WHITE_ADDON_ID = "resource.images.animestudio.white"

USER_AGENT = "RPDevsLogoHarvester/1.0 (contact@iamrp.dev; Kodi Anime Addon Ecosystem)"

# Core Anime Studios mapped to their definitive file on Wikimedia Commons or Wikipedia
STUDIO_LOGO_MAP = {
    # ── Missing studios identified in live audit ──────────────────────────────
    "Wit Studio": {"source": "commons", "file": "File:Wit studio.svg"},
    "CloverWorks": {"source": "commons", "file": "File:CloverWorks Logo.svg"},
    "Bones": {"source": "commons", "file": "File:Bones logo.svg"},
    "Bones Film": {"source": "commons", "file": "File:Bones Film Logo.png"},
    "Science SARU": {"source": "enwiki", "file": "File:Science SARU logo.png"},
    "Studio Bind": {"source": "commons", "file": "File:Studio Bind logo.svg"},
    "CygamesPictures": {"source": "commons", "file": "File:CygamesPictures Logo (cropped).png"},
    "LIDENFILMS": {"source": "commons", "file": "File:Liden Films Logo.png"},
    "Bibury Animation Studios": {"source": "commons", "file": "File:Bibury Animation Studios.png"},
    "ENGI": {"source": "commons", "file": "File:ENGi Logo-Official.png"},
    "BUG FILMS": {"source": "commons", "file": "File:BUG FILMS Logo.png"},
    "Studio Gokumi": {"source": "commons", "file": "File:Studio Gokimi logo.png"},
    "Passione": {"source": "enwiki", "file": "File:Passione logo.svg"},
    "Lay-duce": {"source": "commons", "file": "File:Lay-Duce logo.png"},
    "Typhoon Graphics": {"source": "commons", "file": "File:Typhoon Graphics Logo.png"},
    "Studio A-CAT": {"source": "commons", "file": "File:Studio A-Cat Logo.png"},
    "Makaria": {"source": "commons", "file": "File:Makaria Logo.jpg"},
    "Arvo Animation": {"source": "commons", "file": "File:Arvo Animation logo.svg"},
    "Tsumugi Akita Animation Lab": {"source": "enwiki", "file": "File:TsumugiAkitaAnimeLab.png"},
    "Okuruto Noboru": {"source": "commons", "file": "File:Okuruto Noboru logo.png"},
    "Geek Toys": {"source": "commons", "file": "File:Geek Toys logo.png"},
    "Yokohama Animation Lab": {"source": "commons", "file": "File:Yokohama Animation Laboratory.png"},
    "Bandai Namco Pictures": {"source": "commons", "file": "File:Bandai Namco Pictures logo.svg"},
    "Studio Pierrot": {"source": "enwiki", "file": "File:Studio Pierrot logo.png"},
    "Pierrot Films": {"source": "enwiki", "file": "File:Studio Pierrot logo.png"},
    "Studio Kafka": {"source": "commons", "file": "File:Logo studio kafka.svg"},
    "Lapin Track": {"source": "commons", "file": "File:Lapin Track Logo (cropped).png"},
    "Ajia-do": {"source": "commons", "file": "File:Ajiado Logo.png"},
    "Felix Film": {"source": "commons", "file": "File:Felix Film Studio.png"},
    "East Fish Studio": {"source": "commons", "file": "File:East Fish Studio Logo.png"},
    "Drive": {"source": "commons", "file": "File:Drive Studio Logo 2.svg"},
    "Nut": {"source": "commons", "file": "File:NUT animation studio logo.png"},
    "Studio KAI": {"source": "commons", "file": "File:Studio Kai Logo (2024).svg"},
    "Brain's Base": {"source": "commons", "file": "File:Brain's Base logo.svg"},
    "Lerche": {"source": "commons", "file": "File:Studio Lerche Logo.svg"},
    "Revoroot": {"source": "enwiki", "file": "File:Logo of Revoroot.png"},
    "NBCUniversal Entertainment Japan": {"source": "enwiki", "file": "File:NBCUniversal Entertainment Japan globe logo.png"},
    "Yostar Pictures": {"source": "enwiki", "file": "File:Yostar Pictures logo.png"},
    "Zero-G": {"source": "enwiki", "file": "File:ZERO-G logo.svg"},
    "Benten Film": {"source": "enwiki", "file": "File:Benten Film Logo.png"},
    "Haoliners Animation": {"source": "enwiki", "file": "File:Haoliners Animation League.jpg"},
    "Quad": {"source": "enwiki", "file": "File:JFK (Quad) logo.png"},

    # ── Major & Prominent Anime Studios ───────────────────────────────────────
    "MAPPA": {"source": "commons", "file": "File:MAPPA Logo.svg"},
    "Kyoto Animation": {"source": "commons", "file": "File:Kyoto Animation logo.svg"},
    "ufotable": {"source": "commons", "file": "File:Ufotable logo.svg"},
    "Madhouse": {"source": "commons", "file": "File:Madhouse studio logo.svg"},
    "Toei Animation": {"source": "commons", "file": "File:Toei Animation Logo.png"},
    "Studio Ghibli": {"source": "commons", "file": "File:Studio Ghibli.svg"},
    "A-1 Pictures": {"source": "commons", "file": "File:A-1 Pictures Logo.svg"},
    "Production I.G": {"source": "commons", "file": "File:Production I.G Logo.svg"},
    "Shaft": {"source": "commons", "file": "File:Shaft logo.svg"},
    "Trigger": {"source": "commons", "file": "File:Trigger Logo.svg"},
    "J.C.Staff": {"source": "commons", "file": "File:J.C.Staff Logo.svg"},
    "Doga Kobo": {"source": "commons", "file": "File:Doga Kobo Logo.svg"},
    "David Production": {"source": "commons", "file": "File:David Production logo.svg"},
    "P.A. Works": {"source": "commons", "file": "File:P.A. Works logo.svg"},
    "Silver Link.": {"source": "commons", "file": "File:Silver Link Logo.svg"},
    "TMS Entertainment": {"source": "enwiki", "file": "File:TMS Entertainment logo.svg"},
    "Studio Deen": {"source": "commons", "file": "File:Studio Deen logo.svg"},
    "White Fox": {"source": "commons", "file": "File:White Fox Logo.png"},
    "OLM": {"source": "commons", "file": "File:OLM logo.svg"},
    "Kinema Citrus": {"source": "commons", "file": "File:Kinema Citrus logo.png"},
    "Feel": {"source": "commons", "file": "File:Feel. logo.png"},
    "Sunrise": {"source": "commons", "file": "File:Sunrise-Logo.svg"},
    "CoMix Wave Films": {"source": "commons", "file": "File:CoMix Wave Films Logo.svg"},
    "Eight Bit": {"source": "commons", "file": "File:Eight Bit Logo.svg"},
    "GoHands": {"source": "commons", "file": "File:GoHands Logo.svg"},
    "Nexus": {"source": "commons", "file": "File:Nexus (estudio) logo.svg"},
    "Project No.9": {"source": "commons", "file": "File:Project No.9 Logo.png"},
    "SANZIGEN": {"source": "commons", "file": "File:Sanzigen Logo.png"},
    "Polygon Pictures": {"source": "commons", "file": "File:Polygon Pictures Logo.png"},
    "Orange": {"source": "commons", "file": "File:Orange (estudio) logo.svg"},
    "Tatsunoko Production": {"source": "enwiki", "file": "File:TatsunokoPro2014.svg"},
    "Geno Studio": {"source": "commons", "file": "File:Geno Studio Logo.png"},
    "Signal.MD": {"source": "commons", "file": "File:Signal MD Logo.png"},
    "SynergySP": {"source": "commons", "file": "File:SynergySP logo.svg"},
    "Tezuka Productions": {"source": "commons", "file": "File:Tezuka Productions logo.png"},
    "Gonzo": {"source": "commons", "file": "File:Logo Gonzo.svg"},
    "Gainax": {"source": "commons", "file": "File:GAINAX.svg"},
    "Actas": {"source": "commons", "file": "File:Actas logo.svg"},
    "Asahi Production": {"source": "commons", "file": "File:Asahi Production logo.svg"},
    "Diomedéa": {"source": "commons", "file": "File:Diomedéa studio logo.png"},
    "Seven Arcs": {"source": "commons", "file": "File:Seven Arcs logo.svg"},
    "Studio Chizu": {"source": "enwiki", "file": "File:Studio Chizu logo.gif"},
    "Studio Colorido": {"source": "commons", "file": "File:Studio Colorido logo.png"},
    "Studio 4°C": {"source": "commons", "file": "File:Studio 4°C Logo.png"},
    "Maho Film": {"source": "commons", "file": "File:Maho Film logo.svg"},
    "Staple Entertainment": {"source": "commons", "file": "File:Staple Entertainment Logo.svg"},
    "Troyca": {"source": "commons", "file": "File:Troyca logo.svg"},
    "Fanworks": {"source": "commons", "file": "File:Fanworks (studio) logo.svg"},
    "Pine Jam": {"source": "commons", "file": "File:Pine Jam logo.png"},
    "Bridge": {"source": "commons", "file": "File:Bridge (estudio) logo.png"},
    "EMT Squared": {"source": "commons", "file": "File:EMT Squared logo.gif"},
    "C-Station": {"source": "commons", "file": "File:C-Station Logo.png"},
    "Atelier Pontdarc": {"source": "commons", "file": "File:Atelier Pontdarc Logo.png"},
    "CONNECT": {"source": "commons", "file": "File:Connect Animación.png"},
    "Millepensee": {"source": "commons", "file": "File:Millepensee Logo.png"},
    "Telecom Animation Film": {"source": "commons", "file": "File:Telecom Animation Film Logo.png"},
    "Studio VOLN": {"source": "commons", "file": "File:Studio VOLN.png"},
    "ZEXCS": {"source": "commons", "file": "File:Zexcs Logo.png"},
    "Studio Hibari": {"source": "commons", "file": "File:Studio Hibari Logo.png"},
    "Studio Blanc.": {"source": "commons", "file": "File:Studio Blanc logo.png"},
    "Bakken Record": {"source": "commons", "file": "File:Bakken Record Logo.png"},
    "E&H production": {"source": "commons", "file": "File:E&H Production Logo.png"},
    "Seven": {"source": "commons", "file": "File:Seven Animation Studio logo.png"},
    "AIC": {"source": "commons", "file": "File:AIC logo.png"},
    "Artland": {"source": "commons", "file": "File:Artland studio logo.png"},
    "Arms": {"source": "commons", "file": "File:Arms Corporation.svg"},
    "Bee Train": {"source": "commons", "file": "File:Bee Train.svg"},
    "Studio 3Hz": {"source": "commons", "file": "File:3Hz Inc. logo.png"},
    "Xebec": {"source": "commons", "file": "File:Xebec studio logo.svg"},
    "Manglobe": {"source": "commons", "file": "File:Manglobe Logo.png"},
}

# Cross-reference alias filenames for redundant lookup tolerance
ALIASES = {
    "Wit Studio": ["WIT STUDIO", "wit studio"],
    "Revoroot": ["REVOROOT", "revoroot"],
    "Bones Film": ["Bones", "BONES"],
    "Studio Pierrot": ["Pierrot", "Pierrot Films", "PIERROT"],
    "Bandai Namco Pictures": ["BN Pictures", "BNP"],
    "CygamesPictures": ["Cygames Pictures", "Cygames"],
    "LIDENFILMS": ["Liden Films", "LIDEN FILMS", "Lidenfilms"],
    "Bibury Animation Studios": ["Bibury Animation Studio", "Bibury"],
    "Silver Link.": ["Silver Link", "SILVER LINK.", "SILVER LINK..", "SILVER LINK"],
    "Eight Bit": ["8bit", "8-bit", "8-Bit", "Eight bit"],
    "Studio Gokumi": ["Studio Gokimi", "Gokumi"],
    "Ajia-do": ["Ajiado", "Ajia-do Animation Works"],
    "Diomedéa": ["Diomedea", "diomedéa", "diomedea", "DIOMEDEA"],
    "Studio 4°C": ["Studio 4C", "Studio 4degC"],
    "Feel": ["feel.", "FEEL"],
    "J.C.Staff": ["J.C. Staff", "JCStaff", "J.C.STAFF"],
    "OLM": ["OLM Digital"],
    "Studio Ghibli": ["Ghibli", "GHIBLI"],
    "Studio Blanc.": ["Studio Blanc"],
    "Production I.G": ["Production IG", "PRODUCTION I.G"],
    "P.A. Works": ["PA Works", "P.A.Works", "P.A. WORKS"],
    "Nut": ["NUT"],
    "Benten Film": ["BENTEN Film", "BENTEN FILM", "Benten film"],
    "Science SARU": ["Science Saru", "SCIENCE SARU"],
    "Zero-G": ["ZERO-G", "Zero G", "ZERO G"],
    "GoHands": ["GOHANDS", "Go Hands"],
    "Maho Film": ["MAHO FILM", "Maho film"],
    "Felix Film": ["FELIX FILM", "Felix film"],
    "NBCUniversal Entertainment Japan": ["NBCUniversal", "NBC Universal Entertainment Japan"],
    "Haoliners Animation": ["Haoliners Animation League", "Haoliners"],
    "Quad": ["QUAD"],
}

# Studios needing crisp transparent typography emblems
SYNTHETIC_STUDIOS = ["GA-CREW", "Hayabusa Film", "Aura Studio"]


def fetch_file_url(filename: str, source: str = "commons") -> str:
    """Resolve MediaWiki image URL with auto-rendered 800px width."""
    base_api = "https://commons.wikimedia.org/w/api.php" if source == "commons" else "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "titles": filename,
        "prop": "imageinfo",
        "iiprop": "url",
        "iiurlwidth": 800,
        "format": "json"
    }
    url = f"{base_api}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            pages = data.get("query", {}).get("pages", {})
            for pid, pdata in pages.items():
                ii = pdata.get("imageinfo", [{}])[0]
                return ii.get("thumburl") or ii.get("url")
    except Exception as e:
        print(f"  [!] Failed to resolve {filename} on {source}: {e}")
    return None


def download_image(url: str) -> Image.Image:
    """Download image bytes and return RGBA PIL Image."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        img_bytes = io.BytesIO(resp.read())
        im = Image.open(img_bytes)
        return im.convert("RGBA")


def process_coloured(im: Image.Image, max_w: int = 800, max_h: int = 350) -> Image.Image:
    """Trim transparent borders and bound image size preserving aspect ratio."""
    bbox = im.getbbox()
    if bbox:
        im = im.crop(bbox)
    
    w, h = im.size
    ratio = min(max_w / w, max_h / h, 1.0) # Downscale only, avoid upscaling pixelation
    if ratio < 1.0:
        new_w = max(1, int(w * ratio))
        new_h = max(1, int(h * ratio))
        im = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
    return im


def process_white(im: Image.Image) -> Image.Image:
    """Convert coloured RGBA image into pure white silhouette preserving alpha mask."""
    r, g, b, a = im.split()
    white_r = Image.new("L", im.size, 255)
    white_g = Image.new("L", im.size, 255)
    white_b = Image.new("L", im.size, 255)
    return Image.merge("RGBA", (white_r, white_g, white_b, a))


def generate_synthetic_logo(name: str, is_white: bool) -> Image.Image:
    """Generate crisp typography logo on transparent background."""
    w, h = 600, 160
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 46)
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), name, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = max(10, (w - text_w) // 2)
    y = max(10, (h - text_h) // 2)

    color = (255, 255, 255, 255) if is_white else (230, 235, 245, 255)
    shadow = (0, 0, 0, 160)
    for dx, dy in [(-2, -2), (-2, 2), (2, -2), (2, 2), (0, 2)]:
        draw.text((x + dx, y + dy), name, font=font, fill=shadow)
    draw.text((x, y), name, font=font, fill=color)
    return im


def create_package_skeleton(addon_id: str, is_white: bool):
    """Build Kodi add-on directory structure and manifests."""
    pkg_dir = os.path.join(TARGET_ROOT, addon_id)
    res_dir = os.path.join(pkg_dir, "resources")
    os.makedirs(res_dir, exist_ok=True)

    variant_name = "White" if is_white else "Coloured"
    summary_text = f"Anime Studio Icons - {variant_name}"
    desc_text = f"{variant_name} studio logos and production company icons for anime media in Kodi."

    addon_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<addon id="{addon_id}" name="Anime Studio Icons - {variant_name}" version="0.0.2" provider-name="RPDev">
	<extension point="kodi.resource.images" compile="false" type="studios" />
	<requires>
		<import addon="kodi.resource" version="1.0.0"/>
	</requires>
	<extension point="xbmc.addon.metadata">
		<summary lang="en">{summary_text}</summary>
		<description lang="en">{desc_text}</description>
		<platform>all</platform>
		<assets>
			<icon>icon.png</icon>
		</assets>
	</extension>
</addon>
"""
    with open(os.path.join(pkg_dir, "addon.xml"), "w", encoding="utf-8") as f:
        f.write(addon_xml)

    info_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<provides>
	<format>png</format>
	<subfolders>false</subfolders>
</provides>
"""
    with open(os.path.join(pkg_dir, "info.xml"), "w", encoding="utf-8") as f:
        f.write(info_xml)

    changelog_txt = f"""v0.0.2
- Added missing anime studios (Revoroot, NBCUniversal, Yostar Pictures, Zero-G, Benten Film, Quad, Haoliners, GA-CREW, Hayabusa Film, Aura Studio)
- Expanded complete case-variant and punctuation aliases (WIT STUDIO, SILVER LINK.., diomedéa, NUT, 8-bit, LIDENFILMS)

v0.0.1
- Initial release of Anime Studio Icons ({variant_name})
- High-resolution transparent logos for 70+ top anime production studios
- Standardized aspect ratios for Kodi video library media flags
"""
    with open(os.path.join(pkg_dir, "changelog.txt"), "w", encoding="utf-8") as f:
        f.write(changelog_txt)

    license_txt = """GNU GENERAL PUBLIC LICENSE
Version 3, 29 June 2007

Copyright (C) 2026 RPDevs

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""
    with open(os.path.join(pkg_dir, "LICENSE.txt"), "w", encoding="utf-8") as f:
        f.write(license_txt)

    # Generate default addon icon (512x512)
    icon_path = os.path.join(pkg_dir, "icon.png")
    if not os.path.exists(icon_path):
        bg_color = (25, 25, 30, 255) if is_white else (20, 24, 38, 255)
        icon_img = Image.new("RGBA", (512, 512), bg_color)
        icon_img.save(icon_path, "PNG")


def main():
    print("═══════════════════════════════════════════════════════════════════════════")
    print(" 🎬 Anime Studio Icon Harvester & Packager")
    print("═══════════════════════════════════════════════════════════════════════════")

    # 1. Initialize Skeletons
    print("📦 Creating package directory skeletons...")
    create_package_skeleton(COLOURED_ADDON_ID, is_white=False)
    create_package_skeleton(WHITE_ADDON_ID, is_white=True)

    coloured_res = os.path.join(TARGET_ROOT, COLOURED_ADDON_ID, "resources")
    white_res = os.path.join(TARGET_ROOT, WHITE_ADDON_ID, "resources")

    print(f"🎯 Target Studio Count: {len(STUDIO_LOGO_MAP)}")
    successful = 0
    failed = []

    for studio_name, meta in STUDIO_LOGO_MAP.items():
        fname = meta["file"]
        source = meta["source"]
        print(f"\n▶ Fetching: {studio_name} ({fname} on {source})...")

        url = fetch_file_url(fname, source)
        if not url:
            print(f"  [✗] Could not resolve URL for {studio_name}")
            failed.append(studio_name)
            continue

        try:
            raw_img = download_image(url)
            coloured_img = process_coloured(raw_img)
            white_img = process_white(coloured_img)

            # Save primary coloured and white PNGs
            col_target = os.path.join(coloured_res, f"{studio_name}.png")
            wh_target = os.path.join(white_res, f"{studio_name}.png")

            coloured_img.save(col_target, "PNG", optimize=True)
            white_img.save(wh_target, "PNG", optimize=True)
            print(f"  ✓ Saved {studio_name}.png ({coloured_img.width}x{coloured_img.height})")

            # Save aliases
            if studio_name in ALIASES:
                for alias in ALIASES[studio_name]:
                    col_alias = os.path.join(coloured_res, f"{alias}.png")
                    wh_alias = os.path.join(white_res, f"{alias}.png")
                    coloured_img.save(col_alias, "PNG", optimize=True)
                    white_img.save(wh_alias, "PNG", optimize=True)
                    print(f"    ↳ Linked alias: {alias}.png")

            successful += 1
        except Exception as e:
            print(f"  [✗] Error processing {studio_name}: {e}")
            failed.append(studio_name)

    # 3. Generate Synthetic Logos
    print("\n🎨 Generating clean typography emblems for specialized studios...")
    for synth_name in SYNTHETIC_STUDIOS:
        try:
            col_img = generate_synthetic_logo(synth_name, is_white=False)
            wh_img = generate_synthetic_logo(synth_name, is_white=True)

            col_target = os.path.join(coloured_res, f"{synth_name}.png")
            wh_target = os.path.join(white_res, f"{synth_name}.png")

            col_img.save(col_target, "PNG", optimize=True)
            wh_img.save(wh_target, "PNG", optimize=True)
            print(f"  ✓ Generated {synth_name}.png")

            # Also save uppercase / variant alias if applicable
            upper_alias = synth_name.upper()
            if upper_alias != synth_name:
                col_img.save(os.path.join(coloured_res, f"{upper_alias}.png"), "PNG", optimize=True)
                wh_img.save(os.path.join(white_res, f"{upper_alias}.png"), "PNG", optimize=True)
                print(f"    ↳ Linked alias: {upper_alias}.png")
            successful += 1
        except Exception as e:
            print(f"  [✗] Error generating synthetic logo for {synth_name}: {e}")
            failed.append(synth_name)

    print("\n═══════════════════════════════════════════════════════════════════════════")
    print(f" ✨ HARVEST COMPLETE: {successful}/{len(STUDIO_LOGO_MAP)} studios packaged successfully!")
    if failed:
        print(f" ⚠️ Failed studios ({len(failed)}): {', '.join(failed)}")
    print("═══════════════════════════════════════════════════════════════════════════")


if __name__ == "__main__":
    main()
