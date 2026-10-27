"""Run the labeled offline AI evaluation; returns nonzero on any failed case."""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.matching import DEFAULT_WEIGHTS, ENGINE_VERSION, score_pair


def evaluate():
    cases = json.loads((ROOT / 'tests/fixtures/ai_cases.json').read_text(encoding='utf-8'))
    details = []
    for case in cases:
        result = score_pair(case['left'], case['right'], DEFAULT_WEIGHTS)
        passed = (case['min_score'] <= result['score'] <= case['max_score'] and
                  result['confidence'] == case['confidence'] and bool(result['explanation']))
        details.append({'name': case['name'], 'label': case['label'], 'passed': passed, 'result': result})
    passed_count = sum(r['passed'] for r in details)
    return {'engine_version': ENGINE_VERSION, 'generated_at': datetime.now(timezone.utc).isoformat(),
            'total': len(cases), 'passed': passed_count,
            'pass_rate': passed_count / len(cases), 'criteria': 'Score range + confidence + nonempty explanation; all cases must pass.',
            'details': details}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', help='可选 JSON 报告路径')
    args = parser.parse_args()
    report = evaluate()
    for row in report['details']:
        # ensure_ascii keeps the command usable even in legacy Windows terminals.
        print(f'{"PASS" if row["passed"] else "FAIL"} [{row["label"]}] score={row["result"]["score"]} {json.dumps(row["name"], ensure_ascii=True)}')
    print(f'AI evaluation: {report["passed"]}/{report["total"]} passed ({report["pass_rate"]:.0%})')
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['passed'] == report['total'] else 1


if __name__ == '__main__':
    sys.exit(main())
