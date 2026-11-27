#!/usr/bin/env python3
"""
scripts/verify_all.py - Unified Multi-Silo Verification & LLM Diagnostic Runner
================================================================================
Single source of truth executed identically across local development, GitHub
Actions CI (.github/workflows/ci.yml), release CI (.github/workflows/release.yml),
scripts/release_addon.py, and autonomous LLM agents.

Silos executed (in order):
  1. ruff        : Static analysis (--select E9,F63,F7,F82,F811,F405,F541)
  2. compileall  : Python bytecode syntax verification across add-ons, tests, scripts
  3. unittest    : Full offline suite (lint + unit + integration) with strict
                   project warnings-as-errors for resources.* Deprecation/ResourceWarning
  4. coverage    : Function & 100% module coverage audit (audit_function_coverage.py)
  5. e2e (opt)   : Headless Flatpak Kodi 21/22 E2E suite (--e2e)

Usage:
  python3 scripts/verify_all.py
  python3 scripts/verify_all.py --json /tmp/verify_report.json
  python3 scripts/verify_all.py --fail-below 65 --verbose
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET_DIRS = ['plugin.video.otaku.rpdev', 'context.otaku.rpdev', 'service.subtitles.otaku.rpdev', 'service.otaku.rpdev', 'tests', 'scripts']
RUFF_RULES = 'E9,F63,F7,F82,F811,F405,F541'


def _run_silo(name, cmd, verbose=False, remediation=''):
    t0 = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    elapsed = round(time.perf_counter() - t0, 2)
    combined = (proc.stdout or '') + ('\n' + proc.stderr if proc.stderr else '')
    ok = proc.returncode == 0

    if verbose or not ok:
        print(f"\n--- [{name}] {'PASS' if ok else 'FAIL'} ({elapsed:.2f}s) ---")
        if not ok:
            tail = '\n'.join(combined.strip().splitlines()[-40:])
            if tail:
                print(tail)
    else:
        print(f"  ✓ [{name:<12}] passed ({elapsed:.2f}s)")

    entry = {
        'name': name,
        'status': 'pass' if ok else 'fail',
        'exit_code': proc.returncode,
        'duration_s': elapsed,
        'command': ' '.join(cmd),
    }
    if not ok:
        entry['remediation'] = remediation
        entry['tail'] = combined.strip().splitlines()[-30:]
    return ok, entry, combined


def _extract_unittest_metrics(output):
    metrics = {}
    m = re.search(r'Ran (\d+) tests? in ([\d.]+)s', output)
    if m:
        metrics['tests_run'] = int(m.group(1))
        metrics['unittest_duration_s'] = float(m.group(2))
    else:
        mp = re.search(r'(\d+) passed(?:,\s*\d+\s*\w+)*\s+in\s+([\d.]+)s', output)
        if mp:
            metrics['tests_run'] = int(mp.group(1))
            metrics['unittest_duration_s'] = float(mp.group(2))
    failed_ids = re.findall(r'^(?:FAIL|ERROR): (\S+ \([^)]+\))', output, flags=re.MULTILINE)
    if not failed_ids:
        failed_ids = re.findall(r'^FAILED (\S+)', output, flags=re.MULTILINE)
    if failed_ids:
        metrics['failed_tests'] = failed_ids
    return metrics


def _extract_coverage_metrics(output):
    metrics = {}
    m = re.search(r'All Functions/Methods:\s*\d+\s*/\s*\d+\s*\(([\d.]+)%\)', output)
    if m:
        metrics['function_coverage_pct'] = float(m.group(1))
    m_pub = re.search(r'Public Functions/Methods:\s*\d+\s*/\s*\d+\s*\(([\d.]+)%\)', output)
    if m_pub:
        metrics['public_function_coverage_pct'] = float(m_pub.group(1))
    m_mod = re.search(r'Covered Source Files:\s*\d+\s*\(([\d.]+)%\)', output)
    if m_mod:
        metrics['module_coverage_pct'] = float(m_mod.group(1))
    return metrics


def main():
    parser = argparse.ArgumentParser(description='Unified Otaku-RPDev multi-silo verification runner')
    parser.add_argument('--fail-below', type=float, default=65.0, help='Minimum function coverage percentage (default: 65.0)')
    parser.add_argument('--skip-coverage', action='store_true', help='Skip function coverage audit silo')
    parser.add_argument('--fast', action='store_true', help='Fast incremental QA mode (ruff, compileall, lint + targeted tests, skips coverage)')
    parser.add_argument('--tests', nargs='*', default=None, help='Specific unittest target files/modules to execute')
    parser.add_argument('--e2e', action='store_true', help='Also run headless Flatpak Kodi 22 hermetic E2E suite')
    parser.add_argument('--no-strict-warnings', action='store_true', help='Use -W default instead of project warnings-as-errors')
    parser.add_argument('--runner', choices=['pytest', 'unittest'], default='pytest', help='Test runner engine (default: pytest with unittest fallback)')
    parser.add_argument('--json', dest='json_path', default=None, help='Write machine-readable JSON report to path')
    parser.add_argument('-v', '--verbose', action='store_true', help='Show verbose output for all silos')
    args = parser.parse_args()

    print("═══════════════════════════════════════════════════════════════════════")
    print(" 🛡️  Otaku-RPDev Unified Multi-Silo Verification Gate")
    print("═══════════════════════════════════════════════════════════════════════")

    total_start = time.perf_counter()
    silos = []
    all_ok = True

    # Silo 1: Ruff static analysis
    ok, entry, _ = _run_silo(
        'ruff',
        ['ruff', 'check', '--select', RUFF_RULES, *TARGET_DIRS],
        verbose=args.verbose,
        remediation=f'Fix syntax/redefinition/star-import issues: ruff check --select {RUFF_RULES} ' + ' '.join(TARGET_DIRS),
    )
    silos.append(entry)
    all_ok = all_ok and ok

    # Silo 2: Python bytecode compilation
    ok, entry, _ = _run_silo(
        'compileall',
        [sys.executable, '-m', 'compileall', '-q', *TARGET_DIRS],
        verbose=args.verbose,
        remediation='Fix Python syntax error reported by compileall.',
    )
    silos.append(entry)
    all_ok = all_ok and ok

    # Silo 3 & 4: Offline test suite + Function & Module coverage audit
    warn_flags = ['-W', 'default']
    if not args.no_strict_warnings:
        warn_flags += [
            '-W', 'error::DeprecationWarning:resources',
            '-W', 'error::ResourceWarning:resources',
        ]

    single_pass_cov = (
        sys.version_info >= (3, 12)
        and not args.skip_coverage
        and not args.fast
        and not args.tests
    )

    if single_pass_cov:
        cov_cmd = [
            sys.executable,
            *warn_flags,
            'scripts/audit_function_coverage.py',
            '--fail-below',
            str(args.fail_below),
            '--runner',
            args.runner,
        ]
        if not args.no_strict_warnings:
            cov_cmd.append('--strict-warnings')
        ok, entry, cov_out = _run_silo(
            'unittest+cov',
            cov_cmd,
            verbose=args.verbose,
            remediation='Inspect failed_tests, Deprecation/ResourceWarning, or uncovered functions and re-run.',
        )
        entry.update(_extract_unittest_metrics(cov_out))
        entry.update(_extract_coverage_metrics(cov_out))
        if ok:
            if entry.get('tests_run'):
                print(f"    ↳ {entry['tests_run']} tests passed (single-pass PEP 669 coverage [{args.runner}], strict project warnings)")
            if 'function_coverage_pct' in entry:
                print(f"    ↳ Function coverage: {entry['function_coverage_pct']}% (threshold >= {args.fail_below}%)")
        silos.append(entry)
        all_ok = all_ok and ok
    else:
        import importlib.util
        use_pytest = (args.runner == 'pytest') and (importlib.util.find_spec('pytest') is not None)
        lint_targets = [
            'tests/lint/test_ast_integrity.py',
            'tests/lint/test_suite_quality.py',
            'tests/lint/test_docs_and_customizations.py',
        ]
        if use_pytest:
            pt_base = [sys.executable, *warn_flags, '-m', 'pytest', '-q' if not args.verbose else '-v', '--tb=short', '-p', 'no:cov']
            if args.tests:
                targets = [*lint_targets, *args.tests] if args.fast else list(args.tests)
                dedup_targets = [t.replace('.', os.sep) + '.py' if (not os.path.exists(t) and not t.endswith('.py')) else t for t in dict.fromkeys(targets)]
                unittest_cmd = [*pt_base, *dedup_targets]
            elif args.fast:
                unittest_cmd = [*pt_base, 'tests/lint']
            else:
                unittest_cmd = [*pt_base, '-o', 'python_files=test_*.py', 'tests']
        else:
            if args.tests:
                targets = [*lint_targets, *args.tests] if args.fast else list(args.tests)
                dedup_targets = list(dict.fromkeys(targets))
                unittest_cmd = [sys.executable, *warn_flags, '-m', 'unittest', *dedup_targets]
            elif args.fast:
                unittest_cmd = [sys.executable, *warn_flags, '-m', 'unittest', 'discover', '-s', 'tests/lint']
            else:
                unittest_cmd = [sys.executable, *warn_flags, '-m', 'unittest', 'discover', '-s', 'tests']
            if args.verbose:
                unittest_cmd.append('-v')
        ok, entry, ut_out = _run_silo(
            'unittest',
            unittest_cmd,
            verbose=args.verbose,
            remediation='Inspect failed_tests or project Deprecation/ResourceWarning and re-run targeted test.',
        )
        entry.update(_extract_unittest_metrics(ut_out))
        if ok and entry.get('tests_run'):
            scope_label = 'fast lint/targeted' if args.fast else 'targeted' if args.tests else 'lint + unit + integration'
            runner_lbl = 'pytest' if use_pytest else 'unittest'
            print(f"    ↳ {entry['tests_run']} tests passed ({scope_label} [{runner_lbl}], strict project warnings)")
        silos.append(entry)
        all_ok = all_ok and ok

        # Silo 4: Function & 100% module coverage audit
        if not args.skip_coverage and not args.fast:
            ok, entry, cov_out = _run_silo(
                'coverage',
                [sys.executable, *warn_flags, 'scripts/audit_function_coverage.py', '--fail-below', str(args.fail_below), '--runner', args.runner],
                verbose=args.verbose,
                remediation='Add behavioral unit/integration tests for uncovered public functions or fix unimported modules.',
            )
            entry.update(_extract_coverage_metrics(cov_out))
            if ok and 'function_coverage_pct' in entry:
                print(f"    ↳ Function coverage: {entry['function_coverage_pct']}% (threshold >= {args.fail_below}%)")
            silos.append(entry)
            all_ok = all_ok and ok

    # Silo 5 (Optional): Headless Flatpak Kodi 22 hermetic E2E
    if args.e2e:
        ok, entry, _ = _run_silo(
            'kodi22_e2e',
            [sys.executable, 'scripts/test_kodi_installs.py', '--versions', '22', '--mode', 'hermetic'],
            verbose=args.verbose,
            remediation='Inspect headless Kodi 22 E2E log for runtime/SWIG/addon errors.',
        )
        silos.append(entry)
        all_ok = all_ok and ok

    total_elapsed = round(time.perf_counter() - total_start, 2)
    report = {
        'overall_status': 'pass' if all_ok else 'fail',
        'python_version': sys.version.split()[0],
        'total_duration_s': total_elapsed,
        'strict_project_warnings': not args.no_strict_warnings,
        'silos': silos,
    }

    if args.json_path:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_path)), exist_ok=True)
        with open(args.json_path, 'w', encoding='utf-8') as jf:
            json.dump(report, jf, indent=2)
        print(f"  📄 JSON report written to {args.json_path}")

    print("═══════════════════════════════════════════════════════════════════════")
    if all_ok:
        print(f" ✅ ALL VERIFICATION SILOS PASSED ({total_elapsed:.2f}s)")
    else:
        failed = [s['name'] for s in silos if s['status'] != 'pass']
        print(f" ❌ VERIFICATION FAILED in silo(s): {', '.join(failed)} ({total_elapsed:.2f}s)")
    print("═══════════════════════════════════════════════════════════════════════")
    return 0 if all_ok else 1


if __name__ == '__main__':
    sys.exit(main())
