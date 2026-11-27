#!/usr/bin/env python3
"""
Otaku-RPDev Add-on Asset Audit & Lossless PNG Optimizer (WS-7)
==============================================================
Scans both ``context.otaku.rpdev/resources/images/`` (including all 8 icon themes
and studio/genre icon packs) and ``plugin.video.otaku.rpdev/resources/images/``
(or a staged release directory passed via ``--target-dir``).

Default mode runs a read-only byte & theme audit without modifying tracked git assets.
Pass ``--apply`` (intended for staged CI release copies) to run lossless
``oxipng -o 4 --strip safe`` optimization cleanly when ``oxipng`` is installed.
"""
# -*- coding: utf-8 -*-

import argparse
import json
import os
import shutil
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_IMAGE_ROOTS = (
    os.path.join('context.otaku.rpdev', 'resources', 'images'),
    os.path.join('plugin.video.otaku.rpdev', 'resources', 'images'),
)


def scan_image_assets(base_dir=REPO_ROOT, roots=DEFAULT_IMAGE_ROOTS):
    """Collect PNG counts, byte totals, icon-theme breakdown, and top largest files."""
    by_root = {}
    icon_themes = {}
    png_paths = []
    total_files = 0
    total_bytes = 0

    for rel_root in roots:
        abs_root = os.path.join(base_dir, rel_root)
        if not os.path.isdir(abs_root):
            continue
        root_count = 0
        root_bytes = 0
        subgroups = {}
        for dirpath, _dirnames, filenames in os.walk(abs_root):
            for fname in sorted(filenames):
                if not fname.lower().endswith('.png'):
                    continue
                full_p = os.path.join(dirpath, fname)
                try:
                    sz = os.path.getsize(full_p)
                except OSError:
                    continue
                rel_p = os.path.relpath(full_p, abs_root).replace('\\', '/')
                parts = rel_p.split('/')
                group = parts[0] if len(parts) > 1 else '<root>'
                sg = subgroups.setdefault(group, {'files': 0, 'bytes': 0})
                sg['files'] += 1
                sg['bytes'] += sz
                if 'context.otaku.rpdev' in rel_root and group == 'icons' and len(parts) >= 3:
                    theme = parts[1]
                    th = icon_themes.setdefault(theme, {'files': 0, 'bytes': 0})
                    th['files'] += 1
                    th['bytes'] += sz
                root_count += 1
                root_bytes += sz
                total_files += 1
                total_bytes += sz
                png_paths.append((sz, full_p, os.path.join(rel_root, rel_p).replace('\\', '/')))
        by_root[rel_root] = {
            'files': root_count,
            'bytes': root_bytes,
            'subgroups': subgroups,
        }

    png_paths.sort(key=lambda item: item[0], reverse=True)
    return {
        'total_png_files': total_files,
        'total_bytes': total_bytes,
        'by_root': by_root,
        'icon_themes': icon_themes,
        'largest_assets': [{'path': p, 'bytes': sz} for sz, _full, p in png_paths[:10]],
        '_full_paths': [full for _sz, full, _rel in png_paths],
    }


def optimize_png_files(paths, apply=False):
    """Run lossless `oxipng -o 4 --strip safe` when `apply=True` and oxipng is available."""
    oxipng_bin = shutil.which('oxipng')
    if not apply:
        return {
            'mode': 'audit_only',
            'oxipng_available': bool(oxipng_bin),
            'optimized_files': 0,
            'bytes_saved': 0,
            'skipped_reason': 'dry_run',
        }
    if not oxipng_bin:
        return {
            'mode': 'apply_skipped',
            'oxipng_available': False,
            'optimized_files': 0,
            'bytes_saved': 0,
            'skipped_reason': 'oxipng not found on PATH',
        }
    if not paths:
        return {
            'mode': 'apply',
            'oxipng_available': True,
            'optimized_files': 0,
            'bytes_saved': 0,
            'skipped_reason': 'no png files found',
        }

    before_bytes = sum(os.path.getsize(p) for p in paths if os.path.exists(p))
    chunk_size = 200
    for idx in range(0, len(paths), chunk_size):
        chunk = paths[idx:idx + chunk_size]
        proc = subprocess.run(
            [oxipng_bin, '-o', '4', '--strip', 'safe', '--quiet', *chunk],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"oxipng failed (rc={proc.returncode}): {proc.stderr.strip()}")
    after_bytes = sum(os.path.getsize(p) for p in paths if os.path.exists(p))
    return {
        'mode': 'apply',
        'oxipng_available': True,
        'optimized_files': len(paths),
        'before_bytes': before_bytes,
        'after_bytes': after_bytes,
        'bytes_saved': max(0, before_bytes - after_bytes),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description='Audit & optimize Otaku-RPDev PNG image assets.')
    parser.add_argument('--target-dir', default=REPO_ROOT, help='Root directory containing addon subdirectories (default: repo root)')
    parser.add_argument('--apply', action='store_true', help='Run oxipng lossless optimization in-place on target-dir')
    parser.add_argument('--json', dest='json_out', default=None, help='Write JSON summary to file or "-" for stdout')
    args = parser.parse_args(argv)

    scan = scan_image_assets(base_dir=os.path.abspath(args.target_dir))
    full_paths = scan.pop('_full_paths', [])
    opt = optimize_png_files(full_paths, apply=args.apply)
    report = {
        'target_dir': os.path.abspath(args.target_dir),
        'scan': scan,
        'optimization': opt,
    }

    if args.json_out == '-':
        print(json.dumps(report, indent=2))
    else:
        if args.json_out:
            os.makedirs(os.path.dirname(os.path.abspath(args.json_out)), exist_ok=True)
            with open(args.json_out, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2)
        print(f"Asset Audit: {scan['total_png_files']} PNGs ({scan['total_bytes']:,} bytes) across {len(scan['by_root'])} roots")
        for root_key, info in scan['by_root'].items():
            print(f"  - {root_key}: {info['files']} files, {info['bytes']:,} bytes")
        if scan['icon_themes']:
            print(f"  - Icon themes ({len(scan['icon_themes'])}): {', '.join(sorted(scan['icon_themes'].keys()))}")
        if opt['mode'] == 'apply':
            print(f"  - oxipng optimized {opt['optimized_files']} files, saved {opt['bytes_saved']:,} bytes")
        elif opt.get('skipped_reason'):
            print(f"  - Optimization: {opt['mode']} ({opt['skipped_reason']})")
    return 0


if __name__ == '__main__':
    sys.exit(main())
