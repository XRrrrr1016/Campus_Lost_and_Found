import unittest
from pathlib import Path

try:
    from scripts.package import collect_files
except ImportError:
    collect_files = None


class PackageTest(unittest.TestCase):
    def test_submission_contains_startup_entrypoint_and_required_files(self):
        self.assertIsNotNone(collect_files, '源码打包需要可验证的文件清单')
        root = Path(__file__).resolve().parents[1]
        files = {p.relative_to(root).as_posix() for p in collect_files(root)}
        required = {'app.py', 'README.md', 'config.example', 'src/server.py', 'src/service.py',
                    'src/static/index.html', 'tests/fixtures/ai_cases.json', 'docs/06-test-report.md'}
        self.assertTrue(required <= files, f'缺少启动或验收文件: {required-files}')
        self.assertFalse(any('__pycache__' in p or p.startswith(('data/', 'node_modules/', '.env', 'tmp/')) for p in files))


if __name__ == '__main__':
    unittest.main()
