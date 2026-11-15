#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_autoskip_coverage.py - Benchmark AniSkip vs Anime-Skip vs IntroDB across 576 anime test cases.

Measures:
1. Presence in AniSkip (https://api.aniskip.com)
2. Presence in Anime-Skip (https://api.anime-skip.com/graphql)
3. Presence in IntroDB (https://api.introdb.app)
4. Presence in All 3, Pairwise Overlaps, Exclusive Titles, and Missing in All 3
5. Fallback sequence comparisons:
   - Order A: AniSkip -> Anime-Skip -> IntroDB
   - Order B: Anime-Skip -> AniSkip -> IntroDB
6. Segment breakdown (OP/Intro, ED/Outro, Recap, Post-Credits)
7. Categorical breakdown across all genres/categories

Saves output to:
- .staging/autoskip_full_results.json
- .staging/autoskip_coverage_summary.json
- .staging/autoskip_coverage_report.md
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# Ensure project root is in sys.path
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

DATASET_PATH = os.path.join(_REPO_ROOT, 'tests', 'fixtures', 'comprehensive_anime_dataset.json')
STAGING_DIR = os.path.join(_REPO_ROOT, '.staging')
CACHE_DIR = os.path.join(STAGING_DIR, 'cache')
MAPPINGS_DB = os.path.join(STAGING_DIR, 'mappings.db')

ANIME_SKIP_API_KEY = 'EjXN75HSiw2mDoL8awhGikFHRVaEe21c'
ANIME_SKIP_GRAPHQL_URL = 'https://api.anime-skip.com/graphql'

# Rate limiter for Anime-Skip: 60 req/min (1 req per 1.05s)
_animeskip_lock = threading.Lock()
_last_animeskip_call = 0.0

ANIME_SKIP_TYPE_MAP = {
    '97e3629a-95e5-4b1a-9411-73a47c0d0e25': 'Branding',
    '9edc0037-fa4e-47a7-a29a-d9c43368daa8': 'Canon',
    '2a730a51-a601-439b-bc1f-7b94a640ffb9': 'Credits',
    'c48f1dce-1890-4394-8ce6-c3f5b2f95e5e': 'Filler',
    '14550023-2589-46f0-bfb4-152976506b4c': 'Intro',
    '6c4ade53-4fee-447f-89e4-3bb29184e87a': 'Mixed Credits',
    'cbb42238-d285-4c88-9e91-feab4bb8ae0a': 'Mixed Intro',
    'e384759b-3cd2-4824-9569-128363b4452b': 'Must Watch',
    'd839cdb1-21b3-455d-9c21-7ffeb37adbec': 'New Credits',
    '679fb610-ff3c-4cf4-83c0-75bcc7fe8778': 'New Intro',
    'c7b1eddb-defa-4bc6-a598-f143081cfe4b': 'Preview',
    'f38ac196-0d49-40a9-8fcf-f3ef2f40f127': 'Recap',
    '67321535-a4ea-4f21-8bed-fb3c8286b510': 'Title Card',
    '9f0c6532-ccae-4238-83ec-a2804fe5f7b0': 'Transition',
    'ae57fcf9-27b0-49a7-9a99-a91aa7518a29': 'Unknown'
}


def ensure_directories():
    os.makedirs(os.path.join(CACHE_DIR, 'aniskip'), exist_ok=True)
    os.makedirs(os.path.join(CACHE_DIR, 'animeskip'), exist_ok=True)
    os.makedirs(os.path.join(CACHE_DIR, 'introdb'), exist_ok=True)
    os.makedirs(os.path.join(CACHE_DIR, 'anizip'), exist_ok=True)


def get_db_mapping(mal_id: int) -> dict[str, Any]:
    """Retrieve IMDb ID, season, media type, and AniList ID from local mappings.db."""
    if not os.path.exists(MAPPINGS_DB):
        return {}
    try:
        conn = sqlite3.connect(f'file:{MAPPINGS_DB}?mode=ro', uri=True)
        cur = conn.cursor()
        cur.execute(
            'SELECT imdb_id, thetvdb_season, anime_media_type, anilist_id FROM anime WHERE mal_id=?',
            (mal_id,)
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return {
                'imdb_id': row[0] or None,
                'season': row[1] or 1,
                'media_type': row[2] or 'TV',
                'anilist_id': row[3] or None
            }
    except Exception:
        pass
    return {}


def get_anizip_mapping(mal_id: int) -> dict[str, Any]:
    """Fallback lookup via AniZip for titles missing from mappings.db."""
    cache_path = os.path.join(CACHE_DIR, 'anizip', f'{mal_id}.json')
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass

    url = f'https://api.ani.zip/mappings?mal_id={mal_id}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Otaku-Auditor)'})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            mappings = data.get('mappings') or {}
            res = {
                'imdb_id': mappings.get('imdb_id'),
                'season': 1,
                'media_type': mappings.get('type') or 'TV',
                'anilist_id': mappings.get('anilist_id') or mal_id
            }
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(res, f)
            return res
    except Exception:
        return {'imdb_id': None, 'season': 1, 'media_type': 'TV', 'anilist_id': mal_id}


def fetch_aniskip(mal_id: int, episode: int = 1) -> dict[str, Any]:
    """Query AniSkip API with caching and rate limit backoff."""
    cache_path = os.path.join(CACHE_DIR, 'aniskip', f'{mal_id}_ep{episode}.json')
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass

    url = f'https://api.aniskip.com/v2/skip-times/{mal_id}/{episode}?types=op&types=ed&types=mixed-op&types=mixed-ed&episodeLength=0'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Otaku-RPDev/6.1.9)'})

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                with open(cache_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f)
                return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                data = {'found': False, 'results': [], 'statusCode': 404}
                with open(cache_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f)
                return data
            elif e.code == 429:
                retry_after = int(e.headers.get('Retry-After', 2))
                time.sleep(retry_after + 1)
                continue
            else:
                break
        except Exception:
            time.sleep(1)

    return {'found': False, 'results': [], 'statusCode': 500}


def fetch_animeskip(anilist_id: int | str, episode: int = 1) -> dict[str, Any]:
    """Query Anime-Skip GraphQL API with strict rate limiting (max 60/min) and caching."""
    if not anilist_id:
        return {'found': False, 'op': None, 'ed': None, 'timestamps_count': 0}

    cache_path = os.path.join(CACHE_DIR, 'animeskip', f'{anilist_id}_ep{episode}.json')
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass

    query = '''
    query FindShows($service: ExternalService!, $serviceId: String!) {
        findShowsByExternalId(service: $service, serviceId: $serviceId) {
            id
            name
            episodes {
                id
                number
                timestamps {
                    at
                    typeId
                }
            }
        }
    }
    '''
    headers = {
        'Content-Type': 'application/json',
        'X-Client-ID': ANIME_SKIP_API_KEY,
        'User-Agent': 'Mozilla/5.0 (Otaku-Coverage/6.1.9)'
    }
    payload = json.dumps({'query': query, 'variables': {'service': 'ANILIST', 'serviceId': str(anilist_id)}}).encode('utf-8')

    global _last_animeskip_call
    for attempt in range(3):
        with _animeskip_lock:
            now = time.time()
            elapsed = now - _last_animeskip_call
            if elapsed < 1.05:
                time.sleep(1.05 - elapsed)
            _last_animeskip_call = time.time()

        req = urllib.request.Request(ANIME_SKIP_GRAPHQL_URL, data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                shows = (data.get('data') or {}).get('findShowsByExternalId') or []
                
                # Find all episode cuts matching episode number
                candidate_timestamps = []
                for s in shows:
                    for ep in s.get('episodes', []):
                        try:
                            num = float(ep.get('number') or -1)
                        except (ValueError, TypeError):
                            continue
                        if int(num) == episode and ep.get('timestamps'):
                            candidate_timestamps.append(ep['timestamps'])

                # Pick candidate with most timestamps
                best_raw = max(candidate_timestamps, key=len) if candidate_timestamps else []
                
                # Parse timestamps
                stamps = []
                for t in best_raw:
                    at = t.get('at')
                    if at is None or at < 0:
                        continue
                    tname = ANIME_SKIP_TYPE_MAP.get(t.get('typeId'), 'Unknown')
                    stamps.append((float(at), tname))
                stamps.sort(key=lambda x: x[0])

                op = None
                ed = None
                for i, (at, name) in enumerate(stamps):
                    if op is None and name in ('Intro', 'New Intro', 'Mixed Intro'):
                        for next_at, next_name in stamps[i+1:]:
                            if next_name != name:
                                op = {'startTime': round(at, 2), 'endTime': round(next_at, 2)}
                                break
                    if ed is None and name in ('Credits', 'New Credits', 'Mixed Credits'):
                        for next_at, next_name in stamps[i+1:]:
                            if next_name != name:
                                ed = {'startTime': round(at, 2), 'endTime': round(next_at, 2)}
                                break
                        if ed is None and i == len(stamps) - 1:
                            ed = {'startTime': round(at, 2), 'endTime': round(at + 90.0, 2)}

                res = {
                    'found': bool(op or ed),
                    'has_op': op is not None,
                    'has_ed': ed is not None,
                    'op': op,
                    'ed': ed,
                    'timestamps_count': len(best_raw)
                }

                with open(cache_path, 'w', encoding='utf-8') as f:
                    json.dump(res, f)
                return res

        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(10)
                continue
            elif e.code == 404:
                res = {'found': False, 'has_op': False, 'has_ed': False, 'op': None, 'ed': None, 'timestamps_count': 0}
                with open(cache_path, 'w', encoding='utf-8') as f:
                    json.dump(res, f)
                return res
            else:
                break
        except Exception:
            time.sleep(2)

    res = {'found': False, 'has_op': False, 'has_ed': False, 'op': None, 'ed': None, 'timestamps_count': 0}
    return res


def fetch_introdb(imdb_id: str, season: int = 1, episode: int = 1, is_movie: bool = False) -> dict[str, Any]:
    """Query IntroDB API with caching."""
    if not imdb_id:
        return {'found': False, 'intro': None, 'outro': None, 'recap': None, 'post_credits': None}

    tag = 'movie' if is_movie else f's{season}_e{episode}'
    cache_path = os.path.join(CACHE_DIR, 'introdb', f'{imdb_id}_{tag}.json')
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass

    if is_movie:
        url = f'https://api.introdb.app/segments?imdb_id={imdb_id}&is_movie=true'
    else:
        url = f'https://api.introdb.app/segments?imdb_id={imdb_id}&season={season}&episode={episode}'

    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Otaku-RPDev/6.1.9)'})

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                with open(cache_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f)
                return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                data = {'found': False, 'intro': None, 'outro': None, 'recap': None, 'post_credits': None}
                with open(cache_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f)
                return data
            elif e.code == 429:
                time.sleep(2)
                continue
            else:
                break
        except Exception:
            time.sleep(1)

    return {'found': False, 'intro': None, 'outro': None, 'recap': None, 'post_credits': None}


def process_item(item: dict[str, Any]) -> dict[str, Any]:
    mal_id = item['mal_id']
    title = item.get('title', '')
    category = item.get('category', 'unknown')
    year = item.get('year', 0)

    # 1. Resolve IMDb ID, media type & AniList ID
    mapping = get_db_mapping(mal_id)
    if not mapping or not mapping.get('imdb_id') or not mapping.get('anilist_id'):
        anizip_map = get_anizip_mapping(mal_id)
        if anizip_map:
            if not mapping.get('imdb_id'):
                mapping['imdb_id'] = anizip_map.get('imdb_id')
            if not mapping.get('anilist_id'):
                mapping['anilist_id'] = anizip_map.get('anilist_id')

    imdb_id = mapping.get('imdb_id')
    season = mapping.get('season') or 1
    media_type = mapping.get('media_type') or 'TV'
    anilist_id = mapping.get('anilist_id') or mal_id
    is_movie = (str(media_type).upper() == 'MOVIE')

    # 2. Query AniSkip (cached)
    as_data = fetch_aniskip(mal_id, episode=1)
    as_results = as_data.get('results') or []
    as_found = bool(as_data.get('found') and as_results)

    as_op = None
    as_ed = None
    for r in as_results:
        stype = r.get('skipType', '')
        if stype in ('op', 'mixed-op') and as_op is None:
            as_op = r.get('interval')
        elif stype in ('ed', 'mixed-ed') and as_ed is None:
            as_ed = r.get('interval')

    # 3. Query Anime-Skip (rate limited 60/min + cached)
    ams_data = fetch_animeskip(anilist_id, episode=1)
    ams_found = bool(ams_data.get('found'))
    ams_op = ams_data.get('op')
    ams_ed = ams_data.get('ed')

    # 4. Query IntroDB (cached)
    idb_data = fetch_introdb(imdb_id, season=season, episode=1, is_movie=is_movie) if imdb_id else {}
    idb_intro = idb_data.get('intro')
    idb_outro = idb_data.get('outro')
    idb_recap = idb_data.get('recap')
    idb_post_credits = idb_data.get('post_credits')
    idb_found = bool(idb_intro or idb_outro or idb_recap or idb_post_credits)

    # 5. Overlap & exclusivity
    in_all_3 = as_found and ams_found and idb_found
    as_and_ams = as_found and ams_found
    as_and_idb = as_found and idb_found
    ams_and_idb = ams_found and idb_found

    as_only = as_found and not ams_found and not idb_found
    ams_only = ams_found and not as_found and not idb_found
    idb_only = idb_found and not as_found and not ams_found
    none_found = not as_found and not ams_found and not idb_found

    # 6. Fallback Orders
    # Order A: AniSkip -> Anime-Skip -> IntroDB
    order_a_source = 'None'
    if as_found:
        order_a_source = 'AniSkip'
    elif ams_found:
        order_a_source = 'Anime-Skip'
    elif idb_found:
        order_a_source = 'IntroDB'

    # Order B: Anime-Skip -> AniSkip -> IntroDB
    order_b_source = 'None'
    if ams_found:
        order_b_source = 'Anime-Skip'
    elif as_found:
        order_b_source = 'AniSkip'
    elif idb_found:
        order_b_source = 'IntroDB'

    return {
        'mal_id': mal_id,
        'title': title,
        'category': category,
        'year': year,
        'imdb_id': imdb_id,
        'anilist_id': anilist_id,
        'season': season,
        'is_movie': is_movie,
        'aniskip_found': as_found,
        'aniskip_has_op': as_op is not None,
        'aniskip_has_ed': as_ed is not None,
        'aniskip_op': as_op,
        'aniskip_ed': as_ed,
        'animeskip_found': ams_found,
        'animeskip_has_op': ams_op is not None,
        'animeskip_has_ed': ams_ed is not None,
        'animeskip_op': ams_op,
        'animeskip_ed': ams_ed,
        'introdb_found': idb_found,
        'introdb_has_intro': idb_intro is not None,
        'introdb_has_outro': idb_outro is not None,
        'introdb_has_recap': idb_recap is not None,
        'introdb_has_post_credits': idb_post_credits is not None,
        'introdb_intro': idb_intro,
        'introdb_outro': idb_outro,
        'in_all_3': in_all_3,
        'as_and_ams': as_and_ams,
        'as_and_idb': as_and_idb,
        'ams_and_idb': ams_and_idb,
        'as_only': as_only,
        'ams_only': ams_only,
        'idb_only': idb_only,
        'none_found': none_found,
        'order_a_source': order_a_source,
        'order_b_source': order_b_source,
    }


def main():
    ensure_directories()
    with open(DATASET_PATH, 'r', encoding='utf-8') as f:
        items = json.load(f)

    total_items = len(items)
    print(f"Loaded {total_items} items from {DATASET_PATH}")
    print("Benchmarking AniSkip vs Anime-Skip vs IntroDB (respecting Anime-Skip 60 req/min)...")

    results = []
    completed = 0
    start_time = time.time()

    # Anime-Skip requires 1 req/sec rate limiting. We use a gentle 2-worker pool
    # so cached items return instantly while network queries are rate-locked.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_to_item = {executor.submit(process_item, it): it for it in items}
        for future in concurrent.futures.as_completed(future_to_item):
            res = future.result()
            results.append(res)
            completed += 1
            if completed % 10 == 0 or completed == total_items:
                elapsed = time.time() - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                eta = (total_items - completed) / rate if rate > 0 else 0
                sys.stdout.write(f"\rProgress: {completed}/{total_items} ({completed/total_items*100:.1f}%) | {rate:.2f} items/sec | ETA: {eta/60:.1f}m")
                sys.stdout.flush()

    print("\n\nAll queries completed. Analyzing metrics across all 3 services...")

    results.sort(key=lambda r: r['mal_id'])

    # Totals
    aniskip_count = sum(1 for r in results if r['aniskip_found'])
    animeskip_count = sum(1 for r in results if r['animeskip_found'])
    introdb_count = sum(1 for r in results if r['introdb_found'])

    all_3_count = sum(1 for r in results if r['in_all_3'])
    as_and_ams_count = sum(1 for r in results if r['as_and_ams'])
    as_and_idb_count = sum(1 for r in results if r['as_and_idb'])
    ams_and_idb_count = sum(1 for r in results if r['ams_and_idb'])

    as_only_count = sum(1 for r in results if r['as_only'])
    ams_only_count = sum(1 for r in results if r['ams_only'])
    idb_only_count = sum(1 for r in results if r['idb_only'])
    none_count = sum(1 for r in results if r['none_found'])
    any_count = total_items - none_count

    # Cumulative Fallback: Order A (AniSkip -> Anime-Skip -> IntroDB)
    order_a_as = sum(1 for r in results if r['order_a_source'] == 'AniSkip')
    order_a_ams = sum(1 for r in results if r['order_a_source'] == 'Anime-Skip')
    order_a_idb = sum(1 for r in results if r['order_a_source'] == 'IntroDB')

    # Cumulative Fallback: Order B (Anime-Skip -> AniSkip -> IntroDB)
    order_b_ams = sum(1 for r in results if r['order_b_source'] == 'Anime-Skip')
    order_b_as = sum(1 for r in results if r['order_b_source'] == 'AniSkip')
    order_b_idb = sum(1 for r in results if r['order_b_source'] == 'IntroDB')

    # Segments
    aniskip_op_count = sum(1 for r in results if r['aniskip_has_op'])
    aniskip_ed_count = sum(1 for r in results if r['aniskip_has_ed'])
    animeskip_op_count = sum(1 for r in results if r['animeskip_has_op'])
    animeskip_ed_count = sum(1 for r in results if r['animeskip_has_ed'])
    introdb_op_count = sum(1 for r in results if r['introdb_has_intro'])
    introdb_ed_count = sum(1 for r in results if r['introdb_has_outro'])

    # Category breakdown
    categories = sorted(list({r['category'] for r in results}))
    cat_summary = {}
    for cat in categories:
        cat_items = [r for r in results if r['category'] == cat]
        c_tot = len(cat_items)
        c_as = sum(1 for r in cat_items if r['aniskip_found'])
        c_ams = sum(1 for r in cat_items if r['animeskip_found'])
        c_idb = sum(1 for r in cat_items if r['introdb_found'])
        c_any = sum(1 for r in cat_items if not r['none_found'])
        cat_summary[cat] = {
            'total': c_tot,
            'aniskip': c_as,
            'aniskip_pct': round(c_as / c_tot * 100, 1),
            'animeskip': c_ams,
            'animeskip_pct': round(c_ams / c_tot * 100, 1),
            'introdb': c_idb,
            'introdb_pct': round(c_idb / c_tot * 100, 1),
            'combined_any': c_any,
            'combined_pct': round(c_any / c_tot * 100, 1),
        }

    summary = {
        'total_test_cases': total_items,
        'aniskip': {'count': aniskip_count, 'pct': round(aniskip_count / total_items * 100, 1)},
        'animeskip': {'count': animeskip_count, 'pct': round(animeskip_count / total_items * 100, 1)},
        'introdb': {'count': introdb_count, 'pct': round(introdb_count / total_items * 100, 1)},
        'overlap': {
            'all_3': all_3_count,
            'all_3_pct': round(all_3_count / total_items * 100, 1),
            'aniskip_and_animeskip': as_and_ams_count,
            'aniskip_and_introdb': as_and_idb_count,
            'animeskip_and_introdb': ams_and_idb_count,
            'aniskip_only': as_only_count,
            'animeskip_only': ams_only_count,
            'introdb_only': idb_only_count,
            'missing_all_3': none_count,
            'missing_all_3_pct': round(none_count / total_items * 100, 1),
            'combined_any_3': any_count,
            'combined_any_3_pct': round(any_count / total_items * 100, 1),
        },
        'order_a_aniskip_first': {
            'tier1_aniskip': order_a_as,
            'tier2_animeskip_gain': order_a_ams,
            'tier3_introdb_gain': order_a_idb,
            'total_coverage': order_a_as + order_a_ams + order_a_idb,
            'total_pct': round((order_a_as + order_a_ams + order_a_idb) / total_items * 100, 1),
        },
        'order_b_animeskip_first': {
            'tier1_animeskip': order_b_ams,
            'tier2_aniskip_gain': order_b_as,
            'tier3_introdb_gain': order_b_idb,
            'total_coverage': order_b_ams + order_b_as + order_b_idb,
            'total_pct': round((order_b_ams + order_b_as + order_b_idb) / total_items * 100, 1),
        },
        'segments': {
            'aniskip': {'op': aniskip_op_count, 'ed': aniskip_ed_count},
            'animeskip': {'op': animeskip_op_count, 'ed': animeskip_ed_count},
            'introdb': {'op': introdb_op_count, 'ed': introdb_ed_count},
        },
        'categories': cat_summary,
    }

    full_results_path = os.path.join(STAGING_DIR, 'autoskip_full_results.json')
    summary_path = os.path.join(STAGING_DIR, 'autoskip_coverage_summary.json')
    report_path = os.path.join(STAGING_DIR, 'autoskip_coverage_report.md')

    with open(full_results_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2)

    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)

    # Determine winning primary service
    if animeskip_count > aniskip_count:
        winner = "Anime-Skip"
        recommended_order = "Anime-Skip > AniSkip > IntroDB"
        winner_reason = f"Anime-Skip has higher standalone coverage ({animeskip_count} titles / {summary['animeskip']['pct']}%) than AniSkip ({aniskip_count} titles / {summary['aniskip']['pct']}%)."
    else:
        winner = "AniSkip"
        recommended_order = "AniSkip > Anime-Skip > IntroDB"
        winner_reason = f"AniSkip has higher standalone coverage ({aniskip_count} titles / {summary['aniskip']['pct']}%) than Anime-Skip ({animeskip_count} titles / {summary['animeskip']['pct']}%)."

    report_md = f"""# 📊 Comprehensive Autoskip Benchmark: AniSkip vs Anime-Skip vs IntroDB

- **Test Dataset**: `comprehensive_anime_dataset.json` ({total_items} titles across 15 categories)
- **Target APIs**:
  - **AniSkip**: `https://api.aniskip.com` (Direct MAL ID query, public)
  - **Anime-Skip**: `https://api.anime-skip.com/graphql` (AniList ID query, API key required, 60 req/min)
  - **IntroDB**: `https://api.introdb.app` (IMDb ID + Season query, public)
- **Generated At**: {time.strftime('%Y-%m-%d %H:%M:%S')}

---

## 1. Standalone Coverage Comparison

| Service | Found Titles | Coverage % | OP / Intro Available | ED / Outro Available |
|---|---:|---:|---:|---:|
| **AniSkip** | **{aniskip_count}** | **{summary['aniskip']['pct']}%** | {aniskip_op_count} | {aniskip_ed_count} |
| **Anime-Skip** | **{animeskip_count}** | **{summary['animeskip']['pct']}%** | {animeskip_op_count} | {animeskip_ed_count} |
| **IntroDB** | **{introdb_count}** | **{summary['introdb']['pct']}%** | {introdb_op_count} | {introdb_ed_count} |

---

## 2. Overlap & Exclusivity Analysis

| Metric | Count | Percentage |
|---|---:|---:|
| **Present in All 3 Services** | **{all_3_count}** | **{summary['overlap']['all_3_pct']}%** |
| Present in AniSkip & Anime-Skip | {as_and_ams_count} | {round(as_and_ams_count / total_items * 100, 1)}% |
| Present in AniSkip & IntroDB | {as_and_idb_count} | {round(as_and_idb_count / total_items * 100, 1)}% |
| Present in Anime-Skip & IntroDB | {ams_and_idb_count} | {round(ams_and_idb_count / total_items * 100, 1)}% |
| **AniSkip ONLY** (missing in other 2) | {as_only_count} | {round(as_only_count / total_items * 100, 1)}% |
| **Anime-Skip ONLY** (missing in other 2) | {ams_only_count} | {round(ams_only_count / total_items * 100, 1)}% |
| **IntroDB ONLY** (missing in other 2) | {idb_only_count} | {round(idb_only_count / total_items * 100, 1)}% |
| **Missing in All 3 Services** | {none_count} | {summary['overlap']['missing_all_3_pct']}% |
| **Combined Coverage (Any of the 3)** | **{any_count}** | **{summary['overlap']['combined_any_3_pct']}%** |

---

## 3. Fallback Order Comparison (When All 3 Enabled)

### Sequence A: AniSkip &rarr; Anime-Skip &rarr; IntroDB
- **Tier 1 (AniSkip)**: resolves **{order_a_as}** titles ({round(order_a_as / total_items * 100, 1)}%)
- **Tier 2 (Anime-Skip fallback)**: resolves +**{order_a_ams}** titles (+{round(order_a_ams / total_items * 100, 1)}%)
- **Tier 3 (IntroDB fallback)**: resolves +**{order_a_idb}** titles (+{round(order_a_idb / total_items * 100, 1)}%)
- **Total Resolved**: **{order_a_as + order_a_ams + order_a_idb} / {total_items} ({summary['order_a_aniskip_first']['total_pct']}%)**

### Sequence B: Anime-Skip &rarr; AniSkip &rarr; IntroDB
- **Tier 1 (Anime-Skip)**: resolves **{order_b_ams}** titles ({round(order_b_ams / total_items * 100, 1)}%)
- **Tier 2 (AniSkip fallback)**: resolves +**{order_b_as}** titles (+{round(order_b_as / total_items * 100, 1)}%)
- **Tier 3 (IntroDB fallback)**: resolves +**{order_b_idb}** titles (+{round(order_b_idb / total_items * 100, 1)}%)
- **Total Resolved**: **{order_b_ams + order_b_as + order_b_idb} / {total_items} ({summary['order_b_animeskip_first']['total_pct']}%)**

---

## 4. Architectural Decision & Recommendation

- **Winner**: **{winner}**
- **Recommended Fallback Chain**: `{recommended_order}`
- **Rationale**: {winner_reason}
- IntroDB remains the universal secondary/tertiary net because it is public (no API key required) and covers non-standard releases and Western-distributed catalog titles.

---

## 5. Category Breakdown

| Category | Total | AniSkip | Anime-Skip | IntroDB | Combined (Any) |
|---|---:|---:|---:|---:|---:|
"""
    for cat, cdata in cat_summary.items():
        report_md += f"| {cat.title()} | {cdata['total']} | {cdata['aniskip']} ({cdata['aniskip_pct']}%) | {cdata['animeskip']} ({cdata['animeskip_pct']}%) | {cdata['introdb']} ({cdata['introdb_pct']}%) | **{cdata['combined_any']} ({cdata['combined_pct']}%)** |\n"

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_md)

    print(f"\nSaved full results to: {full_results_path}")
    print(f"Saved summary to:      {summary_path}")
    print(f"Saved markdown report: {report_path}")
    print("\n" + "=" * 60)
    print("  3-WAY AUTOSKIP COVERAGE BENCHMARK SUMMARY")
    print("=" * 60)
    print(f"  Total Test Cases:            {total_items}")
    print(f"  AniSkip Found:               {aniskip_count} ({summary['aniskip']['pct']}%)")
    print(f"  Anime-Skip Found:            {animeskip_count} ({summary['animeskip']['pct']}%)")
    print(f"  IntroDB Found:               {introdb_count} ({summary['introdb']['pct']}%)")
    print("-" * 60)
    print(f"  Present in ALL 3:            {all_3_count} ({summary['overlap']['all_3_pct']}%)")
    print(f"  AniSkip ONLY:                {as_only_count}")
    print(f"  Anime-Skip ONLY:             {ams_only_count}")
    print(f"  IntroDB ONLY:                {idb_only_count}")
    print(f"  Missing in All 3:            {none_count} ({summary['overlap']['missing_all_3_pct']}%)")
    print("-" * 60)
    print(f"  COMBINED COVERAGE:           {any_count} / {total_items} ({summary['overlap']['combined_any_3_pct']}%)")
    print(f"  RECOMMENDED ORDER:           {recommended_order}")
    print("=" * 60)


if __name__ == '__main__':
    main()
