#!/usr/bin/env python3
"""
scripts/qa_fast.py - Thin Fast Incremental QA Runner
====================================================
Delegates to scripts/verify_all.py --fast (ruff + compileall + lint/targeted
tests with strict project warnings) for rapid developer/agent iteration.
"""

import argparse
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VERIFY_ALL = os.path.join(SCRIPT_DIR, 'verify_all.py')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Fast incremental QA gate delegating to scripts/verify_all.py')
    parser.add_argument('--tests', nargs='*', default=None, help='Additional unittest target files/modules to include')
    parser.add_argument('--all-unit', action='store_true', help='Run full unittest suite without coverage audit')
    parser.add_argument('--json', dest='json_path', default=None, help='Write JSON report to path')
    parser.add_argument('-v', '--verbose', action='store_true', help='Show verbose output')
    args = parser.parse_args(argv)

    cmd = [sys.executable, VERIFY_ALL]
    if args.all_unit:
        cmd.append('--skip-coverage')
    else:
        cmd.append('--fast')
    if args.tests:
        cmd.extend(['--tests', *args.tests])
    if args.json_path:
        cmd.extend(['--json', args.json_path])
    if args.verbose:
        cmd.append('--verbose')

    return subprocess.run(cmd).returncode


if __name__ == '__main__':
    sys.exit(main())
