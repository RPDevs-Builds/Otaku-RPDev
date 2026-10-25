"""
MegaCloud/VidCloud video source extractor and standalone decryptor.
Ported from script.service.megacloud & mega-embed-2 into Otaku-RPDev.
Native pure-Python in-process solver without requiring external webservices.
"""
import base64
import json
import math
import os
import re
import time
import urllib.parse
from resources.lib.ui import client, control

# In-memory keys cache
_KEYS_CACHE = None
_KEYS_CACHE_TIME = 0
_CACHE_TTL = 43200  # 12 hours

DEFAULT_KEYS = {
    "vidstr": "pXJdDCTByENrAOGFOyziD",
    "_meta": {
        "source": "bundled_fallback",
        "description": "Megacloud decryption keys fallback",
        "last_updated": "2026-10-24T22:50:00Z"
    }
}

KEY_URLS = [
    "https://raw.githubusercontent.com/RPDevs-Builds/script.service.megacloud/master/keys/keys.json",
    "https://raw.githubusercontent.com/yogesh-hacker/MegacloudKeys/main/keys.json",
]


def _get_decryption_keys(force_refresh: bool = False):
    """
    Get current Megacloud decryption keys with auto-refresh on failure.
    Fast path: returns in-memory, disk-cached, or bundled keys instantly.
    Only reaches out to remote mirror if force_refresh is True or keys are missing.
    """
    global _KEYS_CACHE, _KEYS_CACHE_TIME

    now = time.time()
    if not force_refresh and _KEYS_CACHE and (now - _KEYS_CACHE_TIME < _CACHE_TTL):
        return _KEYS_CACHE

    # 1. Check bundled file first (instant, guaranteed valid)
    if not _KEYS_CACHE and not force_refresh:
        addon_path = getattr(control, 'ADDON_PATH', '') or ''
        bundled_file = os.path.join(addon_path, 'resources', 'data', 'keys.json') if addon_path else ''
        if bundled_file and os.path.exists(bundled_file):
            try:
                with open(bundled_file, 'r', encoding='utf-8') as f:
                    keys = json.load(f)
                    if keys and keys.get('vidstr'):
                        _KEYS_CACHE = keys
                        _KEYS_CACHE_TIME = now
                        return keys
            except (json.JSONDecodeError, OSError) as e:
                control.log(f"Megacloud bundled keys parse error: {e}", 'debug')

    # 2. Check disk cache in user profile
    cache_dir = getattr(control, 'dataPath', '') or ''
    cache_file = os.path.join(cache_dir, 'megacloud_keys.json') if cache_dir else ''
    if not force_refresh and cache_file and os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                keys = json.load(f)
                if keys and keys.get('vidstr'):
                    _KEYS_CACHE = keys
                    _KEYS_CACHE_TIME = now
                    return keys
        except (json.JSONDecodeError, OSError) as e:
            control.log(f"Megacloud disk cache parse error: {e}", 'debug')

    # 3. If force_refresh or missing keys, fetch from remote mirrors
    if force_refresh or not _KEYS_CACHE:
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0"
        for url in KEY_URLS:
            try:
                resp = client.get(url, headers={"User-Agent": user_agent}, timeout=5)
                if resp and resp.text:
                    data = resp.json()
                    if data and data.get('vidstr'):
                        _KEYS_CACHE = data
                        _KEYS_CACHE_TIME = now
                        if cache_file:
                            try:
                                os.makedirs(os.path.dirname(cache_file), exist_ok=True)
                                with open(cache_file, 'w', encoding='utf-8') as f:
                                    json.dump(data, f, indent=2)
                            except OSError as e:
                                control.log(f"Megacloud disk cache write error: {e}", 'debug')
                        control.log("Megacloud: Keys refreshed from remote mirror", level='info')
                        return data
            except Exception as e:
                control.log(f"Megacloud fetch keys failed from {url}: {e}", 'debug')
                continue

    if not _KEYS_CACHE:
        _KEYS_CACHE = DEFAULT_KEYS
        _KEYS_CACHE_TIME = now

    return _KEYS_CACHE


class MegacloudDecryptor:
    """Standalone pure-Python Megacloud / Rabbitstream cipher reversal engine."""

    def __init__(self):
        self.char_array = [chr(32 + i) for i in range(95)]  # ASCII 32-126 (95 chars)

    def keygen2(self, megacloud_key: str, client_key: str, use_float_hash: bool = True) -> str:
        """Derive decryption key from secret and nonce."""
        temp_key = megacloud_key + client_key
        hash_val = 0
        keygen_hash_mult_val = 31
        for char in temp_key:
            hash_val = ord(char) + hash_val * keygen_hash_mult_val + (hash_val << 7) - hash_val

        hash_val = abs(hash_val)
        if use_float_hash:
            # Replicates JavaScript IEEE 754 float64 conversion: Number(hashVal % 0x7FFFFFFFFFFFFFFFn)
            l_hash = int(float(hash_val % 0x7FFFFFFFFFFFFFFF))
        else:
            l_hash = hash_val % 0x7FFFFFFFFFFFFFFF

        keygen_xor_val = 247
        temp_key = ''.join(chr(ord(c) ^ keygen_xor_val) for c in temp_key)

        keygen_shift_val = 5
        pivot = (l_hash % len(temp_key)) + keygen_shift_val
        temp_key = temp_key[pivot:] + temp_key[:pivot]

        leaf_str = client_key[::-1]
        return_key = ''
        max_len = max(len(temp_key), len(leaf_str))
        for i in range(max_len):
            c1 = temp_key[i] if i < len(temp_key) else ''
            c2 = leaf_str[i] if i < len(leaf_str) else ''
            return_key += c1 + c2

        return_key = return_key[:96 + l_hash % 33]
        return ''.join(chr((ord(c) % 95) + 32) for c in return_key)

    def columnar_cipher2(self, src: str, ikey: str) -> str:
        """Reverses columnar transposition cipher."""
        column_count = len(ikey)
        row_count = math.ceil(len(src) / column_count)

        grid = [[' ' for _ in range(column_count)] for _ in range(row_count)]
        key_map = [{'char': char, 'idx': index} for index, char in enumerate(ikey)]
        sorted_map = sorted(key_map, key=lambda x: ord(x['char']))

        src_index = 0
        for item in sorted_map:
            idx = item['idx']
            for r in range(row_count):
                if src_index < len(src):
                    grid[r][idx] = src[src_index]
                    src_index += 1

        res = []
        for r in range(row_count):
            for c in range(column_count):
                res.append(grid[r][c])
        return ''.join(res)

    def seed_shuffle2(self, char_array, ikey: str):
        """Deterministic Fisher-Yates unshuffle using LCG PRNG."""
        hash_val = 0
        for char in ikey:
            hash_val = (hash_val * 31 + ord(char)) & 0xFFFFFFFF

        shuffle_num = hash_val

        def pseudo_rand(arg):
            nonlocal shuffle_num
            shuffle_num = (shuffle_num * 1103515245 + 12345) & 0x7FFFFFFF
            return shuffle_num % arg

        ret_list = list(char_array)
        for i in range(len(ret_list) - 1, 0, -1):
            swap_index = pseudo_rand(i + 1)
            ret_list[i], ret_list[swap_index] = ret_list[swap_index], ret_list[i]
        return ret_list

    def decrypt(self, encrypted_src: str, nonce: str, secret: str) -> str:
        """Decrypt Megacloud 3-layer encrypted ciphertext."""
        # Try primary float-based keygen (matches upstream V8/Node JS), then int fallback
        for use_float in (True, False):
            try:
                dec = self._decrypt_internal(encrypted_src, nonce, secret, use_float=use_float)
                if dec:
                    return dec
            except Exception:
                continue
        return ''

    def _decrypt_internal(self, encrypted_src: str, nonce: str, secret: str, use_float: bool = True) -> str:
        layers = 3
        gen_key = self.keygen2(secret, nonce, use_float_hash=use_float)
        dec_src = base64.b64decode(encrypted_src).decode('latin1')

        for iteration in range(layers, 0, -1):
            layer_key = gen_key + str(iteration)

            hash_val = 0
            for char in layer_key:
                hash_val = (hash_val * 31 + ord(char)) & 0xFFFFFFFF

            seed = hash_val

            def seed_rand(arg):
                nonlocal seed
                seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
                return seed % arg

            shifted_chars = []
            for char in dec_src:
                try:
                    c_idx = self.char_array.index(char)
                    rand_num = seed_rand(95)
                    new_idx = (c_idx - rand_num + 95) % 95
                    shifted_chars.append(self.char_array[new_idx])
                except ValueError:
                    shifted_chars.append(char)
            dec_src = ''.join(shifted_chars)

            dec_src = self.columnar_cipher2(dec_src, layer_key)

            sub_values = self.seed_shuffle2(self.char_array, layer_key)
            char_map = {char: self.char_array[idx] for idx, char in enumerate(sub_values)}

            dec_src = ''.join(char_map.get(char, char) for char in dec_src)

        try:
            data_len = int(dec_src[:4])
            return dec_src[4:4 + data_len]
        except (ValueError, IndexError):
            return dec_src


def extract_megacloud_sources(embed_url, referer="https://hianime.to/"):
    """
    Extract video sources, subtitles, and chapter marks from Megacloud/Rabbitstream embed URLs.

    Args:
        embed_url: The embed URL or xrax token (e.g. https://megacloud.blog/embed-2/v3/e-1/xxxxx?k=1)
        referer: The referer URL to use in requests

    Returns:
        dict with keys: sources (list), tracks (list), intro (dict), outro (dict)
        or None on failure
    """
    if not embed_url:
        return None

    try:
        # Handle external solver override if explicitly enabled by user
        if control.getBool('ms_enable') is True:
            ms_url = control.getSetting('ms_url')
            if ms_url and ms_url.startswith('http'):
                try:
                    control.log(f"Megacloud: Trying external solver at {ms_url}", level='info')
                    ext_url = f"{ms_url.rstrip('/')}/get?url={urllib.parse.quote(embed_url)}"
                    ext_resp = client.get(ext_url, timeout=10)
                    if ext_resp and ext_resp.text:
                        ext_data = ext_resp.json()
                        if ext_data and (ext_data.get('sources') or ext_data.get('tracks')):
                            return ext_data
                except Exception as e:
                    control.log(f"Megacloud: External solver failed ({e}), falling back to built-in", level='warning')

        # Normalize embed URL if bare ID passed
        if not embed_url.startswith('http://') and not embed_url.startswith('https://'):
            embed_url = f"https://megacloud.blog/embed-2/v3/e-1/{embed_url}?k=1"

        url_obj = urllib.parse.urlparse(embed_url)
        domain = url_obj.netloc
        parts = url_obj.path.rstrip('/').split('/')
        xrax = parts[-1].split('?')[0]
        path = '/'.join(parts[:-1])
        get_sources_base = f"https://{domain}{path}/getSources?id="

        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0"
        headers = {
            "User-Agent": user_agent,
            "Referer": referer,
            "X-Requested-With": "XMLHttpRequest",
        }

        # Step 1: Fetch embed page to extract nonce
        response = client.get(embed_url, headers=headers, timeout=10)
        if not response or not response.text:
            control.log(f"Megacloud: Failed to load embed page: {embed_url}", level='info')
            return None

        html = response.text

        # Extract nonce (48-char hex or 3x16 concatenated)
        match = re.search(r'\b[a-zA-Z0-9]{48}\b', html)
        if match:
            nonce = match.group(0)
        else:
            match2 = re.search(r'\b([a-zA-Z0-9]{16})\b.*?\b([a-zA-Z0-9]{16})\b.*?\b([a-zA-Z0-9]{16})\b', html)
            if match2:
                nonce = ''.join(match2.groups())
            else:
                control.log("Megacloud: Nonce not found in embed page", level='info')
                return None

        # Step 2: Fetch getSources with nonce
        get_sources_url = f"{get_sources_base}{xrax}&_k={nonce}"
        sources_resp = client.get(get_sources_url, headers=headers, timeout=10)
        if not sources_resp or not sources_resp.text:
            control.log(f"Megacloud: Failed to fetch getSources: {get_sources_url}", level='info')
            return None

        try:
            data = sources_resp.json()
        except Exception as e:
            control.log(f"Megacloud: getSources returned invalid JSON: {e}", level='error')
            return None

        # Step 3: Decrypt if encrypted
        if data.get('encrypted'):
            keys = _get_decryption_keys()
            key = keys.get('vidstr') if keys else None
            decryptor = MegacloudDecryptor()
            decrypted = decryptor.decrypt(data.get('sources', ''), nonce, key) if key else ''

            # If decryption failed, try force-refreshing keys from remote mirror
            if not decrypted or not (decrypted.startswith('[') or decrypted.startswith('{')):
                control.log("Megacloud: Decryption failed with cached key, refreshing keys from mirror...", level='info')
                keys = _get_decryption_keys(force_refresh=True)
                key = keys.get('vidstr') if keys else None
                if key:
                    decrypted = decryptor.decrypt(data.get('sources', ''), nonce, key)

            if decrypted:
                try:
                    data['sources'] = json.loads(decrypted)
                except Exception as e:
                    control.log(f"Megacloud: Failed to parse decrypted sources JSON: {e}", level='error')
                    data['sources'] = [{'file': ''}]
            else:
                control.log("Megacloud: Decryption returned empty payload", level='error')
                data['sources'] = [{'file': ''}]

        return data

    except Exception as e:
        control.log(f"Megacloud: Extractor error: {str(e)}", level='error')
        return None
