"""
domains.py – Dynamic domain resolver with multi-tier caching and remote mirror fallback.
Allows scrapers (HiAnime, AnimePahe, Gogoanime, Nyaa, etc.) to adapt dynamically to domain
moves without requiring manual add-on updates.
"""

import json
import os
import time

from resources.lib.ui import control

_DOMAINS_CACHE = None
_DOMAINS_CACHE_TIME = 0
_CACHE_TTL = 86400  # 24 hours

DOMAIN_MIRRORS = [
    "https://raw.githubusercontent.com/RPDevs-Builds/Otaku-RPDev/main/plugin.video.otaku.rpdev/resources/data/domains.json",
]


def _get_bundled_domains_path():
    addon_path = getattr(control, 'ADDON_PATH', '') or ''
    if addon_path:
        return os.path.join(addon_path, 'resources', 'data', 'domains.json')
    return ''


def _get_profile_domains_path():
    profile_path = getattr(control, 'dataPath', '') or ''
    if profile_path:
        return os.path.join(profile_path, 'domains.json')
    return ''


def _load_domains(force_refresh=False):
    """Load domains from memory, disk cache, or bundled fallback."""
    global _DOMAINS_CACHE, _DOMAINS_CACHE_TIME

    now = time.time()
    if not force_refresh and _DOMAINS_CACHE and (now - _DOMAINS_CACHE_TIME < _CACHE_TTL):
        return _DOMAINS_CACHE

    # 1. Profile disk cache (user profile)
    profile_file = _get_profile_domains_path()
    if not force_refresh and profile_file and os.path.exists(profile_file):
        try:
            with open(profile_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict) and data.get('hianime'):
                    _DOMAINS_CACHE = data
                    _DOMAINS_CACHE_TIME = now
                    return data
        except Exception as e:
            control.log(f"Domains: error reading profile cache: {e}", 'warning')

    # 2. Bundled fallback file (inside add-on)
    bundled_file = _get_bundled_domains_path()
    if bundled_file and os.path.exists(bundled_file):
        try:
            with open(bundled_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict) and data.get('hianime'):
                    _DOMAINS_CACHE = data
                    _DOMAINS_CACHE_TIME = now
                    return data
        except Exception as e:
            control.log(f"Domains: error reading bundled file: {e}", 'warning')

    # 3. Fallback hardcoded defaults if files missing
    return {
        "hianime": "https://hianime.to/",
        "gogoanime": "https://anitaku.so/",
        "animepahe": "https://animepahe.ru/",
        "animekai": "https://animekai.to/",
        "anikoto": "https://anikoto.com/",
        "nyaa": "https://nyaa.si/",
        "animetosho": "https://animetosho.org/",
        "nekobt": "https://nekobt.to/api/v1",
        "torrentio": "https://torrentio.strem.fun",
        "watchnixtoons2": "https://www.wcostream.tv/"
    }


def get_domain(provider_key, default=None):
    """
    Get the canonical base URL for a provider.
    Respects user alt/proxy settings where applicable.
    """
    # Check alt settings first
    if provider_key == 'nyaa' and control.getBool('provider.nyaaalt'):
        return 'https://nyaa-si.translate.goog/?_x_tr_sl=es&_x_tr_tl=en&_x_tr_hl=en/'
    if provider_key == 'animetosho' and control.getBool('provider.animetoshoalt'):
        return 'https://animetosho-org.translate.goog/?_x_tr_sl=es&_x_tr_tl=en&_x_tr_hl=en/'
    if provider_key == 'animepahe' and control.getBool('provider.animepahealt'):
        return 'https://animepahe-pw.translate.goog/?_x_tr_sl=auto&_x_tr_tl=en&_x_tr_hl=en&_x_tr_pto=wapp/'

    domains = _load_domains()
    domain = domains.get(provider_key)
    if domain:
        return domain
    return default or ''


def get_all_domains():
    """Return dictionary of all canonical provider domains."""
    return dict(_load_domains())


def refresh_domains():
    """
    Background worker to refresh domains from remote GitHub mirror.
    Saves to profile disk cache on success.
    """
    global _DOMAINS_CACHE, _DOMAINS_CACHE_TIME
    from resources.lib.ui import client

    for mirror in DOMAIN_MIRRORS:
        try:
            resp = client.get(mirror, timeout=10)
            if resp and resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get('hianime'):
                    _DOMAINS_CACHE = data
                    _DOMAINS_CACHE_TIME = time.time()
                    profile_file = _get_profile_domains_path()
                    if profile_file:
                        os.makedirs(os.path.dirname(profile_file), exist_ok=True)
                        tmp_file = f"{profile_file}.tmp"
                        with open(tmp_file, 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=2)
                        os.replace(tmp_file, profile_file)
                    control.log("Domains: successfully refreshed domain mappings from mirror", 'info')
                    return True
        except Exception as e:
            control.log(f"Domains: mirror fetch error ({mirror}): {e}", 'warning')

    return False
