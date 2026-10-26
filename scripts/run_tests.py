"""Run every test suite in the repository from one command.

    python scripts/run_tests.py            # code-only checks (fresh clone, no data needed)
    python scripts/run_tests.py --data     # also run checks that need prepared viewer data

Works the same on Windows, macOS, Linux and in GitHub Actions. Requires
Python 3.11+ and Node.js 20+.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY = sys.executable

# (name, working directory, command, needs prepared data)
SUITES = [
    ('scripts: dataset tool', 'scripts', [PY, '-m', 'unittest', 'discover', '-s', 'tests'], False),
    ('explorer: python unit tests', 'explorer', [PY, '-m', 'unittest', 'discover', '-s', 'tests'], False),
    ('explorer: dsu', 'explorer', ['node', 'tests/dsu.mjs', '--no-data'], False),
    ('explorer: dsu production', 'explorer', ['node', 'tests/dsu-production.mjs'], False),
    ('explorer: footage model', 'explorer', ['node', 'tests/footage-model.mjs'], False),
    ('explorer: footage controller', 'explorer', ['node', 'tests/footage-controller.mjs'], False),
    ('explorer: operator colors', 'explorer', ['node', 'tests/operator-colors.mjs'], False),
    ('backend: python unit tests', 'backend', [PY, '-m', 'unittest', 'discover', '-s', 'tests'], False),
    ('backend: profiles frontend', 'backend/profiles', ['node', 'test_profiles.mjs'], False),
    ('backend: activity model', 'backend/viewer', ['node', 'test_activity.mjs'], False),
    ('site: release validator (code, pages, links)', 'site', [PY, 'validate_release.py'], False),
    ('site: release validator (with data)', 'site', [PY, 'validate_release.py', '--require-data'], True),
    ('site: public asset transport', 'site', ['node', 'test_public_transport.mjs'], True),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--data', action='store_true', help='also run suites that need prepared viewer data')
    args = parser.parse_args()

    failures = []
    for name, folder, command, needs_data in SUITES:
        if needs_data and not args.data:
            print(f'- skip  {name} (needs --data)')
            continue
        started = time.monotonic()
        result = subprocess.run(command, cwd=REPO / folder, capture_output=True, text=True,
                                encoding='utf-8', errors='replace')
        elapsed = time.monotonic() - started
        if result.returncode == 0:
            print(f'- pass  {name} ({elapsed:.1f}s)')
        else:
            failures.append(name)
            print(f'- FAIL  {name} ({elapsed:.1f}s)')
            print((result.stdout + result.stderr).strip()[-4000:])
    print()
    if failures:
        print(f'{len(failures)} suite(s) failed: ' + ', '.join(failures))
        return 1
    print('All suites passed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
