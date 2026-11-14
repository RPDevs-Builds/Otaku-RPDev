#!/usr/bin/env python3
"""
Generate crisp typography and emblem logos for anime studios present in
comprehensive_anime_dataset.json and top studios without vector assets.
"""
import os, sys, re, json
from PIL import Image, ImageDraw, ImageFont

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ADDON_DIR = os.path.dirname(SCRIPT_DIR)
COLOURED_DIR = os.path.join(ADDON_DIR, 'resources', 'images', 'studios', 'coloured')
WHITE_DIR = os.path.join(ADDON_DIR, 'resources', 'images', 'studios', 'white')

os.makedirs(COLOURED_DIR, exist_ok=True)
os.makedirs(WHITE_DIR, exist_ok=True)

DATASET_PATH = os.path.join(os.path.dirname(ADDON_DIR), 'tests', 'fixtures', 'comprehensive_anime_dataset.json')

with open(DATASET_PATH) as f:
    data = json.load(f)

studios = set()
for item in data:
    s = item.get('studio')
    if s and s != 'Unknown':
        studios.add(s)
    for s_alt in item.get('studios', []):
        if s_alt and s_alt != 'Unknown':
            studios.add(s_alt)

def norm(s):
    return re.sub(r'[^a-z0-9]+', '', s.lower())

existing = {os.path.splitext(f)[0] for f in os.listdir(COLOURED_DIR)}
existing_norm = {norm(x): x for x in existing}

def render_logo(name, is_white=False):
    w, h = 600, 160
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 44)
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), name, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    
    # Scale down font if text is too wide
    if text_w > 540:
        fontsize = max(24, int(44 * (540 / text_w)))
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", fontsize)
        except Exception:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), name, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

    x = max(10, (w - text_w) // 2)
    y = max(10, (h - text_h) // 2)

    color = (255, 255, 255, 255) if is_white else (235, 240, 250, 255)
    shadow = (0, 0, 0, 170)
    for dx, dy in [(-2, -2), (-2, 2), (2, -2), (2, 2), (0, 2)]:
        draw.text((x + dx, y + dy), name, font=font, fill=shadow)
    draw.text((x, y), name, font=font, fill=color)

    bbox_crop = im.getbbox()
    if bbox_crop:
        im = im.crop(bbox_crop)
    return im

generated = 0
for s in sorted(studios):
    n = norm(s)
    # If not on disk with exact or normalized name, generate it
    c_path = os.path.join(COLOURED_DIR, f"{s}.png")
    w_path = os.path.join(WHITE_DIR, f"{s}.png")
    if not os.path.exists(c_path) and n not in existing_norm:
        col = render_logo(s, is_white=False)
        wh = render_logo(s, is_white=True)
        col.save(c_path, "PNG", optimize=True)
        wh.save(w_path, "PNG", optimize=True)
        generated += 1
    elif n in existing_norm and not os.path.exists(c_path):
        # Create symlink/alias so exact case matches immediately
        src_c = os.path.join(COLOURED_DIR, f"{existing_norm[n]}.png")
        src_w = os.path.join(WHITE_DIR, f"{existing_norm[n]}.png")
        if os.path.exists(src_c):
            col = Image.open(src_c)
            col.save(c_path, "PNG", optimize=True)
        if os.path.exists(src_w):
            wh = Image.open(src_w)
            wh.save(w_path, "PNG", optimize=True)
        generated += 1

print(f"Generated/aliased {generated} studio logos. Total in coloured: {len(os.listdir(COLOURED_DIR))}")
