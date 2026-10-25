#!/usr/bin/env python3
"""
check_scraper_health.py — Automated Scraper Health & Yield Monitor
==================================================================
Runs automated search and extraction health checks across active anime providers
(Nyaa, AnimeTosho, HiAnime, AnimePahe, AniKoto, AnimeKai, Gogoanime).
Measures latency, HTTP status, and items yielded. Outputs markdown summary table.

Usage:
    python3 scripts/check_scraper_health.py [--provider <name>] [--timeout <sec>] [--json] [--strict]
"""

import argparse
import json
import os
import sys
import time
import traceback

# 1. Ensure test conftest mock harness is loaded
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.join(REPO_ROOT, 'tests')
ADDON_ROOT = os.path.join(REPO_ROOT, 'plugin.video.otaku.rpdev')

if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)
if ADDON_ROOT not in sys.path:
    sys.path.insert(0, ADDON_ROOT)

import conftest  # Sets up xbmc, xbmcaddon, xbmcgui mocks and test sqlite db

from resources.lib.ui import database, database_sync


def _seed_test_show_metadata():
    """Ensure database has metadata for test MAL ID 52991 (Sousou no Frieren)."""
    database_sync.SyncDatabase()._create_all_tables()
    mal_id = '52991'
    kodi_meta = database.dumps({
        'name': "Sousou no Frieren",
        'ename': "Frieren: Beyond Journey's End",
        'title_userPreferred': "Sousou no Frieren",
        'title_english': "Frieren: Beyond Journey's End",
        'title_romaji': "Sousou no Frieren",
        'format': 'TV',
        'status': 'Finished Airing',
        'episodes': 28,
        'year': 2023,
        'start_date': '2023-09-29',
    })
    database.update_show(mal_id, kodi_meta)


def check_provider(name, func, *args, timeout=20):
    """Run health check against a provider function with latency measurement."""
    t0 = time.perf_counter()
    status = 'FAIL'
    count = 0
    err_msg = ''

    try:
        results = func(*args)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        if isinstance(results, list):
            count = len(results)
            status = 'PASS' if count > 0 else 'WARN (0 items)'
        else:
            status = 'PASS' if results else 'WARN (empty)'
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        err_msg = str(e)
        status = 'FAIL'

    return {
        'provider': name,
        'status': status,
        'latency_ms': elapsed_ms,
        'yield_count': count,
        'error': err_msg
    }


def run_health_checks(target_provider=None, timeout=20):
    _seed_test_show_metadata()

    providers = {}

    try:
        from resources.lib.pages import nyaa
        providers['Nyaa'] = ('Torrent', lambda: nyaa.Sources().get_sources("Frieren", "52991", "1", "Ongoing", "tv"))
    except Exception as e:
        providers['Nyaa'] = ('Torrent', lambda: (_ for _ in ()).throw(e))

    try:
        from resources.lib.pages import animetosho
        providers['AnimeTosho'] = ('Torrent/NZB', lambda: animetosho.Sources().get_sources("Frieren", "52991", "1", "Ongoing", "tv"))
    except Exception as e:
        providers['AnimeTosho'] = ('Torrent/NZB', lambda: (_ for _ in ()).throw(e))

    try:
        from resources.lib.pages import hianime
        providers['HiAnime'] = ('Embed/Cloud', lambda: hianime.Sources().get_sources("52991", "1"))
    except Exception as e:
        providers['HiAnime'] = ('Embed/Cloud', lambda: (_ for _ in ()).throw(e))

    try:
        from resources.lib.pages import animepahe
        providers['AnimePahe'] = ('Direct/HLS', lambda: animepahe.Sources().get_sources("52991", "1"))
    except Exception as e:
        providers['AnimePahe'] = ('Direct/HLS', lambda: (_ for _ in ()).throw(e))

    try:
        from resources.lib.pages import anikoto
        providers['AniKoto'] = ('Embed/HLS', lambda: anikoto.Sources().get_sources("52991", "1"))
    except Exception as e:
        providers['AniKoto'] = ('Embed/HLS', lambda: (_ for _ in ()).throw(e))

    try:
        from resources.lib.pages import animekai
        providers['AnimeKai'] = ('Embed/Cloud', lambda: animekai.Sources().get_sources("52991", "1"))
    except Exception as e:
        providers['AnimeKai'] = ('Embed/Cloud', lambda: (_ for _ in ()).throw(e))

    try:
        from resources.lib.pages import gogoanime
        providers['Gogoanime'] = ('Embed/Direct', lambda: gogoanime.Sources().get_sources("52991", "1"))
    except Exception as e:
        providers['Gogoanime'] = ('Embed/Direct', lambda: (_ for _ in ()).throw(e))

    results = []
    for prov_name, (ptype, pfunc) in providers.items():
        if target_provider and target_provider.lower() != prov_name.lower():
            continue
        print(f"Testing {prov_name} ({ptype})...", end=' ', flush=True)
        res = check_provider(prov_name, pfunc, timeout=timeout)
        res['type'] = ptype
        results.append(res)
        icon = '✅' if 'PASS' in res['status'] else ('⚠️' if 'WARN' in res['status'] else '❌')
        print(f"{icon} {res['status']} ({res['latency_ms']}ms, {res['yield_count']} items)")

    return results


def format_markdown_table(results):
    lines = [
        "### 📡 Otaku-RPDev Scraper Health Dashboard",
        "",
        "| Provider | Type | Status | Latency | Yield | Notes |",
        "| :--- | :--- | :---: | :---: | :---: | :--- |",
    ]
    for r in results:
        icon = '✅' if 'PASS' in r['status'] else ('⚠️' if 'WARN' in r['status'] else '❌')
        err_str = f"`{r['error'][:40]}`" if r['error'] else "OK"
        lines.append(f"| **{r['provider']}** | {r['type']} | {icon} {r['status']} | {r['latency_ms']}ms | {r['yield_count']} items | {err_str} |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Check Otaku provider scraper health.")
    parser.add_argument('--provider', type=str, default=None, help="Target specific provider name")
    parser.add_argument('--timeout', type=int, default=20, help="Timeout in seconds per provider")
    parser.add_argument('--json', action='store_true', help="Output results as JSON")
    parser.add_argument('--strict', action='store_true', help="Exit code 1 if any provider fails")
    args = parser.parse_args()

    results = run_health_checks(target_provider=args.provider, timeout=args.timeout)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        table = format_markdown_table(results)
        print("\n" + table)
        # Also write to GITHUB_STEP_SUMMARY if available
        step_summary_path = os.environ.get('GITHUB_STEP_SUMMARY')
        if step_summary_path and os.path.exists(os.path.dirname(step_summary_path)):
            with open(step_summary_path, 'a', encoding='utf-8') as f:
                f.write("\n" + table + "\n")

    if args.strict:
        has_failure = any('FAIL' in r['status'] for r in results)
        if has_failure:
            sys.exit(1)


if __name__ == '__main__':
    main()
