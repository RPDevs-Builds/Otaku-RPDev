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

DEFAULT_DOMAINS = {
    "hianime": "https://hianime.at/",
    "hianime_mirrors": [
        "https://hianime.at/",
        "https://hianime.ba/",
        "https://hianime.gy/",
        "https://hianime.lu/",
        "https://hianime.tr/",
        "https://hianimetv.bz/",
    ],
    "gogoanime": "https://anitaku.so/",
    "animepahe": "https://animepahe.ru/",
    "animekai": "https://animekai.to/",
    "anikoto": "https://anikoto.com/",
    "nyaa": "https://nyaa.si/",
    "animetosho": "https://animetosho.org/",
    "nekobt": "https://nekobt.to/api/v1",
    "torrentio": "https://torrentio.strem.fun",
    "bitsearch": "https://bitsearch.to",
    "piratebay": "https://apibay.org",
    "watchnixtoons2": "https://www.wcostream.tv/",
}


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
    return dict(DEFAULT_DOMAINS)


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


def get_hianime_mirrors():
    """
    Return ordered list of live HiAnime mirrors, ensuring primary domain is first
    and all entries are normalized with trailing slashes.
    """
    domains = _load_domains()
    primary = domains.get('hianime') or DEFAULT_DOMAINS['hianime']
    if not primary.endswith('/'):
        primary += '/'

    raw_mirrors = domains.get('hianime_mirrors')
    if not isinstance(raw_mirrors, list) or not raw_mirrors:
        raw_mirrors = list(DEFAULT_DOMAINS['hianime_mirrors'])

    mirrors = []
    if primary not in mirrors:
        mirrors.append(primary)

    for m in raw_mirrors:
        if not isinstance(m, str):
            continue
        m = m.strip()
        if not m.startswith('http'):
            continue
        if not m.endswith('/'):
            m += '/'
        if m not in mirrors:
            mirrors.append(m)

    return mirrors


_FAILED_MIRRORS = {}
_FAILURE_COOLDOWN = 600  # 10 minutes


def mark_mirror_failure(url):
    """Mark a mirror URL as temporarily failing with a 10-minute cooldown."""
    if not url:
        return
    url_norm = url.strip().rstrip('/') + '/'
    _FAILED_MIRRORS[url_norm] = time.time()
    control.log(f"Domains: marked mirror {url_norm} as failing (cooldown {int(_FAILURE_COOLDOWN)}s)", 'debug')


def is_mirror_healthy(url):
    """Check if a mirror URL is healthy (not currently in failure cooldown)."""
    if not url:
        return False
    url_norm = url.strip().rstrip('/') + '/'
    last_fail = _FAILED_MIRRORS.get(url_norm)
    if not last_fail:
        return True
    if time.time() - last_fail > _FAILURE_COOLDOWN:
        _FAILED_MIRRORS.pop(url_norm, None)
        return True
    return False


def get_healthy_mirrors(provider_key):
    """
    Get ordered mirrors for a provider with healthy ones prioritized first,
    placing failed mirrors in cooldown at the tail of the list.
    """
    if provider_key == 'hianime':
        all_mirrors = get_hianime_mirrors()
    else:
        domains = _load_domains()
        raw = domains.get(f"{provider_key}_mirrors")
        if isinstance(raw, list):
            all_mirrors = [m if m.endswith('/') else f"{m}/" for m in raw if isinstance(m, str)]
        else:
            base = get_domain(provider_key)
            all_mirrors = [base] if base else []

    healthy = [m for m in all_mirrors if is_mirror_healthy(m)]
    unhealthy = [m for m in all_mirrors if not is_mirror_healthy(m)]
    return healthy + unhealthy


def get_all_domains():
    """Return dictionary of all canonical provider domains."""
    return dict(_load_domains())


def save_profile_domains(data):
    """Save domain mapping dictionary to user profile disk cache and update memory cache."""
    global _DOMAINS_CACHE, _DOMAINS_CACHE_TIME
    if not isinstance(data, dict):
        return False
    _DOMAINS_CACHE = data
    _DOMAINS_CACHE_TIME = time.time()
    profile_file = _get_profile_domains_path()
    if profile_file:
        try:
            os.makedirs(os.path.dirname(profile_file), exist_ok=True)
            tmp_file = f"{profile_file}.tmp"
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_file, profile_file)
            return True
        except Exception as e:
            control.log(f"Domains: error writing profile cache: {e}", 'warning')
    return False


def is_internet_available(timeout=3):
    """
    Check if the local device has functional internet connectivity.
    Performs quick TCP probes to reliable public DNS resolvers (1.1.1.1, 8.8.8.8)
    without relying on local DNS, with an HTTP fallback.
    """
    import socket
    for host, port in [("1.1.1.1", 53), ("8.8.8.8", 53), ("1.1.1.1", 80)]:
        try:
            sock = socket.create_connection((host, port), timeout=timeout)
            sock.close()
            return True
        except (OSError, socket.timeout):
            continue

    try:
        from resources.lib.ui import client
        resp = client.get("https://1.1.1.1", timeout=timeout)
        return resp is not None and resp.status_code in (200, 301, 302, 403)
    except Exception:
        return False


def fetch_domains_from_hianime_pw(timeout=10):
    """
    Query https://hianime.pw/ and extract canonical domain and mirror links.
    Returns (canonical_url, list_of_mirrors) or None on failure.
    """
    import re
    from urllib.parse import urlparse
    from resources.lib.ui import client

    landing_url = "https://hianime.pw/"
    try:
        resp = client.get(landing_url, timeout=timeout)
        if not resp or resp.status_code != 200:
            control.log(f"Domains: fetch hianime.pw returned status {resp.status_code if resp else 'None'}", 'warning')
            return None

        html = resp.text
        canonical = None
        canon_match = re.search(r"<link\s+rel=[\x22\x27]canonical[\x22\x27]\s+href=[\x22\x27]([^\x22\x27]+)[\x22\x27]", html, re.I)
        if canon_match:
            c = canon_match.group(1).strip()
            if c.startswith('http'):
                canonical = c if c.endswith('/') else f"{c}/"

        raw_domains = re.findall(r"https?://(?:[a-z0-9\-]+\.)*hianime[^\x22\x27\s/]*", html, re.I)
        mirrors = []
        if canonical and canonical not in mirrors:
            mirrors.append(canonical)

        for d in raw_domains:
            d = d.strip().lower()
            parsed = urlparse(d)
            if not parsed.scheme or not parsed.netloc:
                continue
            if 'hianime.pw' in parsed.netloc:
                continue
            formatted = f"{parsed.scheme}://{parsed.netloc}/"
            if formatted not in mirrors:
                mirrors.append(formatted)

        if mirrors:
            primary = canonical or mirrors[0]
            return primary, mirrors
    except Exception as e:
        control.log(f"Domains: error fetching from hianime.pw: {e}", 'warning')

    return None


def refresh_hianime_domains(force=False):
    """
    Refresh HiAnime canonical domain and mirrors by querying https://hianime.pw/.
    Updates user profile cache and returns (success, list_of_mirrors).
    """
    res = fetch_domains_from_hianime_pw()
    if not res:
        control.log("Domains: failed to fetch HiAnime mirrors from hianime.pw", 'warning')
        return False, []

    primary, mirrors = res
    domains = dict(_load_domains())
    domains['hianime'] = primary
    domains['hianime_mirrors'] = mirrors
    domains.setdefault('_meta', {})
    domains['_meta']['hianime_last_refreshed'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())

    saved = save_profile_domains(domains)
    control.log(f"Domains: refreshed HiAnime domains (primary: {primary}, {len(mirrors)} mirrors, saved: {saved})", 'info')
    return True, mirrors


def refresh_domains():
    """
    Background worker to refresh domains from remote GitHub mirror.
    Saves to profile disk cache on success.
    """
    from resources.lib.ui import client

    for mirror in DOMAIN_MIRRORS:
        try:
            resp = client.get(mirror, timeout=10)
            if resp and resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get('hianime'):
                    save_profile_domains(data)
                    control.log("Domains: successfully refreshed domain mappings from mirror", 'info')
                    return True
        except Exception as e:
            control.log(f"Domains: mirror fetch error ({mirror}): {e}", 'warning')

    return False
