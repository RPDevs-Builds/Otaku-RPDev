# -*- coding: utf-8 -*-
"""
colors.py - Otaku Provider Color Palette & Branding
===================================================
Defines consistent visual branding and HEX colors for Debrid and Embed providers
across Source Select dialogs, list items, and player overlays.
"""

# ARGB / RGB hex colors matching standard Kodi [COLOR <hex>] tags
PROVIDER_COLORS = {
    'premiumize': 'FF4700B4',       # Premiumize Purple
    'real-debrid': 'FF0080FF',      # Real-Debrid Azure Blue
    'realdebrid': 'FF0080FF',
    'torbox': 'FFFF8000',           # TorBox Bright Orange
    'alldebrid': 'FF00CC66',        # AllDebrid Spring Green
    'debrid-link': 'FFFF0055',      # Debrid-Link Crimson
    'debridlink': 'FFFF0055',
    'easydebrid': 'FF00BFFF',       # EasyDebrid Sky Blue
    'easynews': 'FFFFD700',         # Easynews Gold
    'hianime': 'FF00E5FF',          # HiAnime Cyan
    'animepahe': 'FFE91E63',        # AnimePahe Magenta/Pink
    'anikoto': 'FFFF4081',          # AniKoto Pink
    'aniwave': 'FFAEEA00',          # AniWave Lime Green
    'animix': 'FF9C27B0',           # Animix Amethyst
    'animetosho': 'FF26A69A',       # AnimeTosho Teal
    'nyaa': 'FFFF7043',             # Nyaa Deep Coral
    'torrentio': 'FFAB47BC',        # Torrentio Violet
    'nekobt': 'FF7E57C2',           # NekoBT Deep Purple
    'bitsearch': 'FF00B0FF',        # Bitsearch Sky Blue
    'piratebay': 'FF8D6E63',        # PirateBay Wood / Galleon
    'watchnixtoons2': 'FFFFCA28',   # WatchNixtoons Amber
    'direct': 'FF00E676',           # Direct HLS Emerald
    'embed': 'FF00B0FF',            # Embed Light Blue
    'cloud': 'FF29B6F6',            # Personal Cloud Sky Blue
    'default': 'FFB0BEC5',          # Neutral Slate Grey
}


def normalize_provider_name(name):
    """Normalize provider name string for key lookup."""
    if not name:
        return 'default'
    return str(name).strip().lower().replace(' ', '').replace('_', '').replace('.', '')


def get_provider_color(provider_name, default='FFB0BEC5'):
    """
    Get the ARGB hex color code for a provider.
    :param provider_name: Name of provider or debrid service (e.g. 'Premiumize', 'Real-Debrid')
    :param default: Fallback hex color string
    :return: 8-character hex color string (e.g. 'FF4700B4')
    """
    if not provider_name:
        return default
    clean = normalize_provider_name(provider_name)

    # Direct match
    if clean in PROVIDER_COLORS:
        return PROVIDER_COLORS[clean]

    # Partial / substring match
    for key, color in PROVIDER_COLORS.items():
        if key in clean or clean in key:
            return color

    return default


def colorize_label(text, provider_name):
    """
    Wrap text in Kodi [COLOR <hex>] tags based on provider name.
    :param text: Label text to colorize
    :param provider_name: Provider name determining the color
    :return: Formatted Kodi color string
    """
    if not text:
        return ''
    color = get_provider_color(provider_name)
    return f"[COLOR {color}]{text}[/COLOR]"


# Codec, audio channel, and dynamic range badges for Source Select
BADGE_COLORS = {
    # Video codecs
    'hevc': 'FF00E5FF',     # Bright Cyan
    'h265': 'FF00E5FF',
    'x265': 'FF00E5FF',
    'avc': 'FF64B5F6',      # Soft Blue
    'h264': 'FF64B5F6',
    'x264': 'FF64B5F6',
    'av1': 'FFFFB74D',      # Gold / Orange
    'vp9': 'FFAED581',      # Light Green
    '10bit': 'FFFF80AB',    # Neon Pink
    '10-bit': 'FFFF80AB',

    # Dynamic Range / HDR
    'dv': 'FFFF4081',       # Dolby Vision Pink/Magenta
    'dovi': 'FFFF4081',
    'hdr': 'FFFFD700',      # Bright Gold
    'hdr10': 'FFFFD700',
    'hdr10+': 'FFFFD700',
    'hybrid': 'FFE040FB',   # Purple
    'sdr': 'FF9E9E9E',      # Grey

    # Audio channels & codecs
    '7.1': 'FF76FF03',      # Neon Lime
    '5.1': 'FF00E676',      # Emerald Green
    '2.0': 'FF81D4FA',      # Pale Blue
    'atmos': 'FFFF5252',    # Red / Coral
    'truehd': 'FFFF7043',   # Coral Orange
    'dts-hdma': 'FFFFAB40', # Amber
    'dts-x': 'FFFFAB40',
    'flac': 'FFB388FF',     # Violet
    'aac': 'FF90CAF9',      # Light Blue
    'opus': 'FF80CBC4',     # Teal
}


def get_badge_color(tag, default='FFCFD8DC'):
    """Return ARGB hex color code for a badge (codec, HDR, audio)."""
    if not tag:
        return default
    clean = str(tag).strip().lower().replace(' ', '')
    return BADGE_COLORS.get(clean, default)


def colorize_badge(text, tag=None):
    """Wrap badge text in [COLOR <hex>] tags."""
    if not text:
        return ''
    color = get_badge_color(tag or text)
    return f"[COLOR {color}]{text}[/COLOR]"


def get_seeder_color(count):
    """
    Return ARGB hex color code based on seeder count:
    >= 50: Green (High health)
    10-49: Yellow (Moderate health)
    < 10:  Red (Low health)
    """
    try:
        c = int(count)
        if c >= 50:
            return 'FF00E676'  # Emerald Green
        elif c >= 10:
            return 'FFFFD600'  # Yellow
        else:
            return 'FFFF5252'  # Coral Red
    except (ValueError, TypeError):
        return 'FFB0BEC5'      # Slate Grey
