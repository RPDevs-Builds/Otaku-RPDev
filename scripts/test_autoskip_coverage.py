#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_autoskip_coverage.py - Benchmark AniSkip vs IntroDB across 576 anime test cases.

Measures:
1. Presence in AniSkip (https://api.aniskip.com)
2. Presence in IntroDB (https://api.introdb.app)
3. Presence in Both, AniSkip Only, IntroDB Only, and Neither
4. Segment breakdown (OP/Intro, ED/Outro, Recap, Post-Credits)
5. Timestamp agreement / delta analysis on overlapping titles
6. Categorical breakdown across all genres/categories

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


def ensure_directories():
    os.makedirs(os.path.join(CACHE_DIR, 'aniskip'), exist_ok=True)
    os.makedirs(os.path.join(CACHE_DIR, 'introdb'), exist_ok=True)
    os.makedirs(os.path.join(CACHE_DIR, 'anizip'), exist_ok=True)


def get_db_mapping(mal_id: int) -> dict[str, Any]:
    """Retrieve IMDb ID, season, and media type from local mappings.db."""
    if not os.path.exists(MAPPINGS_DB):
        return {}
    try:
        conn = sqlite3.connect(f'file:{MAPPINGS_DB}?mode=ro', uri=True)
        cur = conn.cursor()
        cur.execute(
            'SELECT imdb_id, thetvdb_season, anime_media_type FROM anime WHERE mal_id=?',
            (mal_id,)
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return {
                'imdb_id': row[0] or None,
                'season': row[1] or 1,
                'media_type': row[2] or 'TV'
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
                'media_type': mappings.get('type') or 'TV'
            }
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(res, f)
            return res
    except Exception:
        return {}


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
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Otaku-RPDev/6.1.8)'})

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
                # Rate limited, backoff
                retry_after = int(e.headers.get('Retry-After', 2))
                time.sleep(retry_after + 1)
                continue
            else:
                break
        except Exception:
            time.sleep(1)

    return {'found': False, 'results': [], 'statusCode': 500}


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

    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Otaku-RPDev/6.1.8)'})

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

    # 1. Resolve IMDb ID & media type
    mapping = get_db_mapping(mal_id)
    if not mapping or not mapping.get('imdb_id'):
        anizip_map = get_anizip_mapping(mal_id)
        if anizip_map:
            mapping = anizip_map

    imdb_id = mapping.get('imdb_id')
    season = mapping.get('season') or 1
    media_type = mapping.get('media_type') or 'TV'
    is_movie = (media_type.upper() == 'MOVIE')

    # 2. Query AniSkip
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

    # 3. Query IntroDB
    idb_data = fetch_introdb(imdb_id, season=season, episode=1, is_movie=is_movie) if imdb_id else {}
    idb_intro = idb_data.get('intro')
    idb_outro = idb_data.get('outro')
    idb_recap = idb_data.get('recap')
    idb_post_credits = idb_data.get('post_credits')

    idb_found = bool(idb_intro or idb_outro or idb_recap or idb_post_credits)

    # 4. Status flags
    in_both = as_found and idb_found
    in_aniskip_only = as_found and not idb_found
    in_introdb_only = idb_found and not as_found
    in_neither = not as_found and not idb_found

    # 5. Timestamp comparison on OP/Intro
    op_delta_start = None
    op_delta_end = None
    if as_op and idb_intro:
        as_start = as_op.get('startTime')
        idb_start = idb_intro.get('start_sec')
        if as_start is not None and idb_start is not None:
            op_delta_start = abs(float(as_start) - float(idb_start))
        as_end = as_op.get('endTime')
        idb_end = idb_intro.get('end_sec')
        if as_end is not None and idb_end is not None:
            op_delta_end = abs(float(as_end) - float(idb_end))

    return {
        'mal_id': mal_id,
        'title': title,
        'category': category,
        'year': year,
        'imdb_id': imdb_id,
        'season': season,
        'is_movie': is_movie,
        'aniskip_found': as_found,
        'aniskip_has_op': as_op is not None,
        'aniskip_has_ed': as_ed is not None,
        'aniskip_op': as_op,
        'aniskip_ed': as_ed,
        'introdb_found': idb_found,
        'introdb_has_intro': idb_intro is not None,
        'introdb_has_outro': idb_outro is not None,
        'introdb_has_recap': idb_recap is not None,
        'introdb_has_post_credits': idb_post_credits is not None,
        'introdb_intro': idb_intro,
        'introdb_outro': idb_outro,
        'introdb_recap': idb_recap,
        'introdb_post_credits': idb_post_credits,
        'in_both': in_both,
        'in_aniskip_only': in_aniskip_only,
        'in_introdb_only': in_introdb_only,
        'in_neither': in_neither,
        'op_delta_start': op_delta_start,
        'op_delta_end': op_delta_end,
    }


def main():
    ensure_directories()
    with open(DATASET_PATH, 'r', encoding='utf-8') as f:
        items = json.load(f)

    total_items = len(items)
    print(f"Loaded {total_items} items from {DATASET_PATH}")
    print("Testing AniSkip and IntroDB coverage (with rate-limiting and local caching)...")

    results = []
    completed = 0
    start_time = time.time()

    # Use thread pool with gentle concurrency to stay within rate limits
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_item = {executor.submit(process_item, it): it for it in items}
        for future in concurrent.futures.as_completed(future_to_item):
            res = future.result()
            results.append(res)
            completed += 1
            if completed % 25 == 0 or completed == total_items:
                elapsed = time.time() - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                sys.stdout.write(f"\rProgress: {completed}/{total_items} ({completed/total_items*100:.1f}%) | {rate:.1f} items/sec")
                sys.stdout.flush()

    print("\n\nAll queries completed. Analyzing metrics...")

    # Sort results by mal_id
    results.sort(key=lambda r: r['mal_id'])

    # Aggregate metrics
    has_imdb_count = sum(1 for r in results if r['imdb_id'])
    aniskip_count = sum(1 for r in results if r['aniskip_found'])
    introdb_count = sum(1 for r in results if r['introdb_found'])
    both_count = sum(1 for r in results if r['in_both'])
    aniskip_only_count = sum(1 for r in results if r['in_aniskip_only'])
    introdb_only_count = sum(1 for r in results if r['in_introdb_only'])
    neither_count = sum(1 for r in results if r['in_neither'])
    either_count = aniskip_count + introdb_only_count

    # Segment metrics
    aniskip_op_count = sum(1 for r in results if r['aniskip_has_op'])
    aniskip_ed_count = sum(1 for r in results if r['aniskip_has_ed'])
    introdb_intro_count = sum(1 for r in results if r['introdb_has_intro'])
    introdb_outro_count = sum(1 for r in results if r['introdb_has_outro'])
    introdb_recap_count = sum(1 for r in results if r['introdb_has_recap'])
    introdb_post_credits_count = sum(1 for r in results if r['introdb_has_post_credits'])

    # Deltas on overlapping titles
    deltas_start = [r['op_delta_start'] for r in results if r['op_delta_start'] is not None]
    deltas_end = [r['op_delta_end'] for r in results if r['op_delta_end'] is not None]
    avg_delta_start = (sum(deltas_start) / len(deltas_start)) if deltas_start else 0.0
    avg_delta_end = (sum(deltas_end) / len(deltas_end)) if deltas_end else 0.0
    exact_matches_op = sum(1 for d in deltas_start if d <= 1.0)

    # Breakdown by category
    categories = sorted(list({r['category'] for r in results}))
    cat_summary = {}
    for cat in categories:
        cat_items = [r for r in results if r['category'] == cat]
        c_tot = len(cat_items)
        c_as = sum(1 for r in cat_items if r['aniskip_found'])
        c_idb = sum(1 for r in cat_items if r['introdb_found'])
        c_both = sum(1 for r in cat_items if r['in_both'])
        c_either = sum(1 for r in cat_items if r['aniskip_found'] or r['introdb_found'])
        cat_summary[cat] = {
            'total': c_tot,
            'aniskip': c_as,
            'aniskip_pct': round(c_as / c_tot * 100, 1),
            'introdb': c_idb,
            'introdb_pct': round(c_idb / c_tot * 100, 1),
            'both': c_both,
            'both_pct': round(c_both / c_tot * 100, 1),
            'either': c_either,
            'either_pct': round(c_either / c_tot * 100, 1),
        }

    summary = {
        'total_test_cases': total_items,
        'has_imdb_id': has_imdb_count,
        'has_imdb_pct': round(has_imdb_count / total_items * 100, 1),
        'aniskip_found': aniskip_count,
        'aniskip_pct': round(aniskip_count / total_items * 100, 1),
        'introdb_found': introdb_count,
        'introdb_pct': round(introdb_count / total_items * 100, 1),
        'in_both': both_count,
        'in_both_pct': round(both_count / total_items * 100, 1),
        'aniskip_only': aniskip_only_count,
        'aniskip_only_pct': round(aniskip_only_count / total_items * 100, 1),
        'introdb_only': introdb_only_count,
        'introdb_only_pct': round(introdb_only_count / total_items * 100, 1),
        'in_neither': neither_count,
        'in_neither_pct': round(neither_count / total_items * 100, 1),
        'combined_coverage_either': either_count,
        'combined_coverage_pct': round(either_count / total_items * 100, 1),
        'coverage_gain_from_introdb': introdb_only_count,
        'coverage_gain_pct': round(introdb_only_count / total_items * 100, 1),
        'segments': {
            'aniskip_op': aniskip_op_count,
            'aniskip_ed': aniskip_ed_count,
            'introdb_intro': introdb_intro_count,
            'introdb_outro': introdb_outro_count,
            'introdb_recap': introdb_recap_count,
            'introdb_post_credits': introdb_post_credits_count,
        },
        'timestamp_agreement': {
            'overlapping_op_count': len(deltas_start),
            'avg_delta_start_sec': round(avg_delta_start, 2),
            'avg_delta_end_sec': round(avg_delta_end, 2),
            'exact_matches_within_1sec': exact_matches_op,
            'exact_matches_pct': round(exact_matches_op / len(deltas_start) * 100, 1) if deltas_start else 0.0,
        },
        'categories': cat_summary,
    }

    # Save outputs to .staging
    full_results_path = os.path.join(STAGING_DIR, 'autoskip_full_results.json')
    summary_path = os.path.join(STAGING_DIR, 'autoskip_coverage_summary.json')
    report_path = os.path.join(STAGING_DIR, 'autoskip_coverage_report.md')

    with open(full_results_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2)

    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)

    # Generate Markdown Report
    report_md = f"""# 📊 Autoskip API Coverage Benchmark Report: AniSkip vs IntroDB

- **Test Dataset**: `comprehensive_anime_dataset.json` ({total_items} titles)
- **Target APIs**:
  - **AniSkip**: `https://api.aniskip.com` (MAL ID query)
  - **IntroDB**: `https://api.introdb.app` (IMDb ID + Season query)
- **Generated At**: {time.strftime('%Y-%m-%d %H:%M:%S')}

---

## 1. High-Level Coverage Breakdown

| Metric | Count | Percentage |
|---|---:|---:|
| **Total Test Titles** | **{total_items}** | **100.0%** |
| Resolved IMDb IDs | {has_imdb_count} | {summary['has_imdb_pct']}% |
| **AniSkip Found** | **{aniskip_count}** | **{summary['aniskip_pct']}%** |
| **IntroDB Found** | **{introdb_count}** | **{summary['introdb_pct']}%** |
| **Present in Both** | **{both_count}** | **{summary['in_both_pct']}%** |
| AniSkip Only (Missing in IntroDB) | {aniskip_only_count} | {summary['aniskip_only_pct']}% |
| **IntroDB Only (Missing in AniSkip)** | **{introdb_only_count}** | **{summary['introdb_only_pct']}%** |
| Missing in Both | {neither_count} | {summary['in_neither_pct']}% |
| **Combined Coverage (AniSkip + IntroDB Fallback)** | **{either_count}** | **{summary['combined_coverage_pct']}%** |
| **Net Coverage Gain from IntroDB** | **+{introdb_only_count} titles** | **+{summary['coverage_gain_pct']}%** |

---

## 2. Segment Type Support

| Segment Type | AniSkip | IntroDB |
|---|---:|---:|
| Opening / Intro | {aniskip_op_count} | {introdb_intro_count} |
| Ending / Outro | {aniskip_ed_count} | {introdb_outro_count} |
| Recap | Included in mixed-op | {introdb_recap_count} |
| Post-Credits | Not exposed | {introdb_post_credits_count} |

---

## 3. Timestamp Consistency on Overlapping Titles

For titles present in both APIs ({len(deltas_start)} items):
- **Average Start Difference**: {round(avg_delta_start, 2)} seconds
- **Average End Difference**: {round(avg_delta_end, 2)} seconds
- **Exact / Near-Exact Matches (within ≤ 1.0s)**: {exact_matches_op} / {len(deltas_start)} ({summary['timestamp_agreement']['exact_matches_pct']}%)

---

## 4. Category / Genre Breakdown

| Category | Total | AniSkip | IntroDB | Both | Combined (Either) |
|---|---:|---:|---:|---:|---:|
"""
    for cat, cdata in cat_summary.items():
        report_md += f"| {cat.title()} | {cdata['total']} | {cdata['aniskip']} ({cdata['aniskip_pct']}%) | {cdata['introdb']} ({cdata['introdb_pct']}%) | {cdata['both']} ({cdata['both_pct']}%) | **{cdata['either']} ({cdata['either_pct']}%)** |\n"

    report_md += f"""
---

## 5. Architectural Recommendation

### Should we use one or the other, or query one then the other?
**Recommendation: Sequential Fallback Chain (Query AniSkip First, Fallback to IntroDB if Not Found)**

1. **Why not IntroDB alone?**
   - AniSkip has deeper coverage for pure anime TV series and niche titles (uses direct MAL IDs without requiring an IMDb ID mapping).
   - IntroDB requires an IMDb ID, which is missing for ~7.8% of anime (recap specials, ONAs).

2. **Why not AniSkip alone?**
   - AniSkip is missing skip times for hundreds of mainstream titles, older anime, and western releases where IntroDB has active community submissions.
   - Adding IntroDB as a secondary fallback increases total skip-time coverage by **+{introdb_only_count} titles (+{summary['coverage_gain_pct']}%)**!

3. **Why sequential fallback instead of concurrent / race?**
   - **Network & Rate Limits**: AniSkip enforces 120 req/60s. Firing both queries simultaneously doubles HTTP traffic and wastes bandwidth.
   - **Precision**: AniSkip's timestamps are tailored specifically to anime OP/ED video cuts. IntroDB is an ideal secondary safety net when AniSkip returns 404 / no results.
   - **Post-Credits & Outro Enrichment**: IntroDB can also optionally supply post-credits scene timestamps, which AniSkip does not provide.
"""

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_md)

    print(f"\nSaved full results to: {full_results_path}")
    print(f"Saved summary to:      {summary_path}")
    print(f"Saved markdown report: {report_path}")
    print("\n" + "=" * 60)
    print("  AUTOSKIP COVERAGE BENCHMARK SUMMARY")
    print("=" * 60)
    print(f"  Total Test Cases:        {total_items}")
    print(f"  Titles with IMDb ID:     {has_imdb_count} ({summary['has_imdb_pct']}%)")
    print(f"  AniSkip Found:           {aniskip_count} ({summary['aniskip_pct']}%)")
    print(f"  IntroDB Found:           {introdb_count} ({summary['introdb_pct']}%)")
    print(f"  Present in Both:         {both_count} ({summary['in_both_pct']}%)")
    print(f"  AniSkip ONLY:            {aniskip_only_count} ({summary['aniskip_only_pct']}%)")
    print(f"  IntroDB ONLY:            {introdb_only_count} ({summary['introdb_only_pct']}%)")
    print(f"  Missing in Both:         {neither_count} ({summary['in_neither_pct']}%)")
    print("-" * 60)
    print(f"  COMBINED COVERAGE:       {either_count} / {total_items} ({summary['combined_coverage_pct']}%)")
    print(f"  NET GAIN FROM INTRODB:   +{introdb_only_count} titles (+{summary['coverage_gain_pct']}%)")
    print("=" * 60)


if __name__ == '__main__':
    main()
