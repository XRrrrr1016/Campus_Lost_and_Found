import json
import inspect
import unittest
from pathlib import Path

try:
    from src.matching import score_pair, DEFAULT_WEIGHTS, normalize
except ImportError:
    score_pair = None
    DEFAULT_WEIGHTS = {}
    normalize = None


class MatchingTest(unittest.TestCase):
    def test_legacy_engine_remains_reproducible_after_synonym_fix(self):
        self.assertIsNotNone(score_pair)
        self.assertIn('engine_version', inspect.signature(score_pair).parameters, '匹配器必须支持历史引擎分派')
        left = dict(category='雨伞', location='一食堂', color='蓝色',
                    date_from='2026-10-26', description='蓝色折叠伞')
        right = left | {'location': '第一食堂'}
        self.assertEqual(score_pair(left, right, DEFAULT_WEIGHTS, engine_version='offline-text-v1')['score'], 97)
        self.assertEqual(score_pair(left, right, DEFAULT_WEIGHTS, engine_version='offline-text-v2')['score'], 100)
        self.assertEqual(normalize('一餐厅', 'offline-text-v1'), '第一食堂')

    def test_location_synonyms_are_idempotent(self):
        self.assertIsNotNone(normalize)
        self.assertEqual(normalize('一食堂'), normalize('第一食堂'))
        self.assertEqual(normalize('第一食堂'), normalize(normalize('第一食堂')))

    def test_labeled_evaluation_corpus(self):
        self.assertIsNotNone(score_pair, '尚未实现可复现文本匹配引擎')
        cases = json.loads((Path(__file__).parent / 'fixtures' / 'ai_cases.json').read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(cases), 10)
        self.assertEqual({c['label'] for c in cases}, {'correct', 'similar_wrong', 'insufficient'})
        for case in cases:
            with self.subTest(case=case['name']):
                result = score_pair(case['left'], case['right'], DEFAULT_WEIGHTS)
                self.assertGreaterEqual(result['score'], case['min_score'])
                self.assertLessEqual(result['score'], case['max_score'])
                self.assertEqual(result['confidence'], case['confidence'])
                self.assertTrue(result['explanation'])
                self.assertEqual(result, score_pair(case['left'], case['right'], DEFAULT_WEIGHTS))


if __name__ == '__main__':
    unittest.main()
