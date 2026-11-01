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
