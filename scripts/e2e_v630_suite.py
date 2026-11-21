#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/e2e_v630_suite.py — Standalone Tier 1-4 Opaque-Box E2E Test Runner
==========================================================================
Discovers ``tests/e2e_v630/suite_*.py`` (excluded from ``unittest discover -s tests``),
filters by ``@tier(1..4)`` and ``@feature(...)`` metadata, lists or executes
selected tests, and optionally writes a machine-readable JSON summary report.
"""

import argparse
import json
import os
import sys
import time
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON_ROOT = os.path.join(REPO_ROOT, 'plugin.video.otaku.rpdev')
CONTEXT_ROOT = os.path.join(REPO_ROOT, 'context.otaku.rpdev')
TESTS_ROOT = os.path.join(REPO_ROOT, 'tests')
E2E_DIR = os.path.join(TESTS_ROOT, 'e2e_v630')

for _p in (REPO_ROOT, ADDON_ROOT, CONTEXT_ROOT, TESTS_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import conftest  # noqa: E402, F401


def _flatten_suite(suite):
    """Recursively flatten a unittest.TestSuite into individual TestCase objects."""
    cases = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            cases.extend(_flatten_suite(item))
        else:
            cases.append(item)
    return cases


def _get_test_metadata(test_case):
    """Extract (tier, features_tuple) from method-level or class-level decorators."""
    cls = type(test_case)
    method_name = getattr(test_case, '_testMethodName', '')
    method_obj = getattr(test_case, method_name, None) if method_name else None

    tier_val = getattr(method_obj, '_e2e_tier', None)
    if tier_val is None:
        tier_val = getattr(cls, '_e2e_tier', None)

    method_feats = getattr(method_obj, '_e2e_features', None)
    cls_feats = getattr(cls, '_e2e_features', ())
    if method_feats:
        feats = tuple(dict.fromkeys(tuple(method_feats) + tuple(cls_feats or ())))
    else:
        feats = tuple(cls_feats or ())

    return tier_val, feats


def discover_e2e_tests():
    """Discover all tests matching tests/e2e_v630/suite_*.py."""
    if not os.path.isdir(E2E_DIR):
        return []
    loader = unittest.defaultTestLoader
    raw_suite = loader.discover(start_dir=E2E_DIR, pattern='suite_*.py', top_level_dir=REPO_ROOT)
    return _flatten_suite(raw_suite)


def _parse_feature_filters(raw_features):
    """Normalize repeatable and comma-separated --feature arguments."""
    wanted = []
    for item in (raw_features or []):
        for part in str(item).split(','):
            cleaned = part.strip().upper()
            if cleaned:
                wanted.append(cleaned)
    return set(wanted)


def filter_tests(test_cases, tier_filter='all', feature_filters=None):
    """Filter discovered TestCases by tier and feature IDs."""
    wanted_tier = None if str(tier_filter).lower() == 'all' else int(tier_filter)
    wanted_features = _parse_feature_filters(feature_filters)

    selected = []
    for tc in test_cases:
        tc_tier, tc_feats = _get_test_metadata(tc)
        if wanted_tier is not None and tc_tier != wanted_tier:
            continue
        if wanted_features:
            upper_feats = {f.upper() for f in tc_feats}
            if not (upper_feats & wanted_features):
                continue
        selected.append((tc, tc_tier, tc_feats))
    return selected


class _TrackingTextTestResult(unittest.TextTestResult):
    """Tracks per-test status and duration for JSON/tier/feature reporting."""

    def __init__(self, stream, descriptions, verbosity):
        super().__init__(stream, descriptions, verbosity)
        self._start_times = {}
        self.test_outcomes = {}

    def startTest(self, test):
        self._start_times[test.id()] = time.perf_counter()
        super().startTest(test)

    def _record(self, test, status, message=''):
        t0 = self._start_times.get(test.id(), time.perf_counter())
        dur = round(time.perf_counter() - t0, 4)
        self.test_outcomes[test.id()] = {
            'status': status,
            'duration_s': dur,
            'message': message,
        }

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, 'passed')

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, 'failed', self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, 'error', self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, 'skipped', str(reason))


def _build_json_report(selected_entries, result, total_duration_s):
    by_tier = {}
    by_feature = {}
    results = []

    counts = {'passed': 0, 'failed': 0, 'errors': 0, 'skipped': 0}

    for tc, tc_tier, tc_feats in selected_entries:
        tid = tc.id()
        outcome = result.test_outcomes.get(tid, {'status': 'not_run', 'duration_s': 0.0, 'message': ''})
        status = outcome['status']
        if status == 'passed':
            counts['passed'] += 1
        elif status == 'failed':
            counts['failed'] += 1
        elif status == 'error':
            counts['errors'] += 1
        elif status == 'skipped':
            counts['skipped'] += 1

        tier_key = str(tc_tier) if tc_tier is not None else 'unassigned'
        t_bucket = by_tier.setdefault(tier_key, {'total': 0, 'passed': 0, 'failed': 0, 'errors': 0, 'skipped': 0})
        t_bucket['total'] += 1
        if status == 'passed':
            t_bucket['passed'] += 1
        elif status == 'failed':
            t_bucket['failed'] += 1
        elif status == 'error':
            t_bucket['errors'] += 1
        elif status == 'skipped':
            t_bucket['skipped'] += 1

        for fid in (tc_feats or ('unassigned',)):
            f_bucket = by_feature.setdefault(fid, {'total': 0, 'passed': 0, 'failed': 0, 'errors': 0, 'skipped': 0})
            f_bucket['total'] += 1
            if status == 'passed':
                f_bucket['passed'] += 1
            elif status == 'failed':
                f_bucket['failed'] += 1
            elif status == 'error':
                f_bucket['errors'] += 1
            elif status == 'skipped':
                f_bucket['skipped'] += 1

        results.append({
            'id': tid,
            'tier': tc_tier,
            'features': list(tc_feats),
            'status': status,
            'duration_s': outcome['duration_s'],
            'message': outcome['message'],
        })

    return {
        'total': len(selected_entries),
        'passed': counts['passed'],
        'failed': counts['failed'],
        'errors': counts['errors'],
        'skipped': counts['skipped'],
        'duration_s': round(total_duration_s, 4),
        'by_tier': by_tier,
        'by_feature': by_feature,
        'results': results,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Standalone Otaku-RPDev v6.3.0 Tier 1-4 Opaque-Box E2E Test Runner'
    )
    parser.add_argument(
        '--tier',
        choices=('1', '2', '3', '4', 'all'),
        default='all',
        help='Filter tests by E2E tier (default: all)',
    )
    parser.add_argument(
        '--feature',
        action='append',
        default=[],
        help='Filter by feature ID (repeatable or comma-separated, e.g. SP-02,CR-01)',
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='List matched tests with TIER and FEATURE metadata without executing',
    )
    parser.add_argument(
        '--json',
        dest='json_path',
        default=None,
        help='Write machine-readable JSON summary report to path',
    )
    parser.add_argument(
        '--fail-fast',
        action='store_true',
        help='Stop on first failure or error',
    )
    parser.add_argument(
        '-v',
        '--verbose',
        action='store_true',
        help='Verbose unittest output',
    )
    args = parser.parse_args(argv)

    discovered = discover_e2e_tests()
    selected = filter_tests(discovered, tier_filter=args.tier, feature_filters=args.feature)

    if args.list:
        for tc, tc_tier, tc_feats in selected:
            tier_str = str(tc_tier) if tc_tier is not None else '?'
            feat_str = ','.join(tc_feats) if tc_feats else 'NONE'
            print(f"TIER={tier_str} FEATURE={feat_str} {tc.id()}")
        if not selected:
            sys.stderr.write("ERROR: 0 E2E tests matched selection criteria.\n")
            return 1
        return 0

    if not selected:
        sys.stderr.write("ERROR: 0 E2E tests matched selection criteria.\n")
        if args.json_path:
            empty_report = {
                'total': 0,
                'passed': 0,
                'failed': 0,
                'errors': 0,
                'skipped': 0,
                'duration_s': 0.0,
                'by_tier': {},
                'by_feature': {},
                'results': [],
            }
            parent = os.path.dirname(os.path.abspath(args.json_path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(args.json_path, 'w', encoding='utf-8') as jf:
                json.dump(empty_report, jf, indent=2)
        return 1

    suite = unittest.TestSuite([tc for tc, _, _ in selected])
    runner = unittest.TextTestRunner(
        verbosity=2 if args.verbose else 1,
        failfast=args.fail_fast,
        resultclass=_TrackingTextTestResult,
    )
    t_start = time.perf_counter()
    result = runner.run(suite)
    total_dur = time.perf_counter() - t_start

    if args.json_path:
        report = _build_json_report(selected, result, total_dur)
        parent = os.path.dirname(os.path.abspath(args.json_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(args.json_path, 'w', encoding='utf-8') as jf:
            json.dump(report, jf, indent=2)

    return 0 if (result.wasSuccessful() and result.testsRun > 0) else 1


if __name__ == '__main__':
    sys.exit(main())
