"""Verify a generated submission in an isolated directory with only Python."""
import argparse
import json
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='campus-package-') as folder:
        destination = Path(folder).resolve()
        with zipfile.ZipFile(args.archive) as archive:
            if archive.testzip() is not None:
                raise RuntimeError('Archive CRC check failed')
            for member in archive.namelist():
                if not (destination / member).resolve().is_relative_to(destination):
                    raise RuntimeError('Unsafe archive path')
                if any(p in {'node_modules', '__pycache__', 'data', '.venv', '.env'} for p in Path(member).parts):
                    raise RuntimeError('Archive contains excluded runtime files')
            archive.extractall(destination)
        checkout = next(p for p in destination.iterdir() if p.is_dir())
        if not (checkout / 'app.py').is_file():
            raise RuntimeError('Missing startup entrypoint app.py')
        db_path = destination / 'fresh.sqlite3'
        commands = [
            ['app.py', '--init-only', '--db', str(db_path)],
            ['app.py', '--init-only', '--db', str(db_path)],
            ['-m', 'unittest', 'discover', '-s', 'tests', '-v'],
            ['scripts/evaluate_ai.py'],
        ]
        for command in commands:
            subprocess.run([sys.executable, *command], cwd=checkout, check=True, timeout=120)
        with closing(sqlite3.connect(db_path)) as db:
            counts = {table: db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                      for table in ('items', 'users', 'rules')}
        if counts != {'items': 8, 'users': 3, 'rules': 1}:
            raise RuntimeError(f'Initialization is not idempotent: {counts}')
    # Temporary SQLite connection is closed before cleaning up on Windows.
    print('PASS: extracted package, two idempotent initializations, full tests, AI evaluation.')
    print(json.dumps({'passed': True, 'initializations': 2, 'counts': counts}))


if __name__ == '__main__':
    main()
