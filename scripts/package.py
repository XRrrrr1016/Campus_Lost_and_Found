"""Create a source-only submission zip without databases, caches or credentials."""
import argparse
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def collect_files(root):
    files = [root / p for p in ('app.py', 'README.md', 'config.example', 'start.cmd', 'start.ps1', '.gitignore')]
    allowed = {'.py', '.js', '.cjs', '.html', '.css', '.json', '.md', '.txt', '.svg'}
    for folder in ('src', 'tests', 'scripts', 'docs', 'recordings'):
        files.extend(p for p in (root / folder).rglob('*') if p.is_file() and p.suffix in allowed and '__pycache__' not in p.parts)
    return sorted(set(files))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate-id', default='待填写编号', help='填写真实候选人编号')
    args = parser.parse_args()
    if not re.fullmatch(r'[\w-]{1,40}', args.candidate_id):
        parser.error('候选人编号只能包含字母、数字、汉字、下划线或横线')
    name = f'{args.candidate_id}_T03_失物招领'
    output = ROOT / 'output' / f'{name}.zip'
    output.parent.mkdir(exist_ok=True)
    files = collect_files(ROOT)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(set(files)):
            archive.write(file, Path(name) / file.relative_to(ROOT))
    # Read back every member; zip CRC and layout are part of verification.
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('压缩包校验失败')
        assert all(n.startswith(name + '/') for n in archive.namelist())
        print(f'Packaged {len(archive.namelist())} source files:')
    print(output)
    print('Recording files are not included automatically. Read docs/recording-index.md before submission.')


if __name__ == '__main__':
    main()
