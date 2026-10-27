import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    from src.service import Service, DomainError
except ImportError:
    Service = None
    DomainError = Exception


class CoreTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(Service, '尚未实现失物招领业务服务')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'test.sqlite3'
        self.s = Service(self.path)
        self.s.initialize(seed=True)
        self.alice = self.s.login('alice', 'demo1234')['user']
        self.bob = self.s.login('bob', 'demo1234')['user']
        self.admin = self.s.login('admin', 'admin1234')['user']

    def item(self, user, kind='found', **changes):
        body = dict(kind=kind, title='黑色校园卡包', category='证件',
                    date_from='2026-10-20', date_to='2026-10-21', location='图书馆',
                    color='黑色', description='黑色卡包，内有校园卡', contact='demo@example.test',
                    secret_question='卡包内侧写的两个字是什么？', secret_answer='向阳')
        body.update(changes)
        return self.s.create_item(user, body)

    def claim(self, item, answer='向阳', lost_id=None):
        return self.s.create_claim(self.alice, item['id'], dict(answer=answer, lost_item_id=lost_id, contact='alice@private.example.test'))

    def test_private_contact_and_feature_never_in_public_output(self):
        found = self.item(self.bob)
        public = self.s.get_item(found['id'])
        self.assertNotIn('contact', public)
        self.assertNotIn('secret_answer', json.dumps(public))
        self.assertNotIn('向阳', json.dumps(public, ensure_ascii=False))
        self.assertNotIn('contact', self.s.get_item(found['id'], self.alice))
        self.assertEqual(self.s.get_item(found['id'], self.bob)['contact'], 'demo@example.test')

    def test_wrong_feature_cannot_approve_and_rejection_is_audited(self):
        found = self.item(self.bob)
        claim = self.claim(found, '不知道')
        with self.assertRaises(DomainError):
            self.s.review_claim(self.bob, claim['id'], 'approve', '')
        self.s.review_claim(self.bob, claim['id'], 'reject', '私密特征不符')
        self.assertEqual(self.s.list_claims(self.alice)[0]['status'], 'rejected')
        self.assertNotIn('contact', self.s.get_item(found['id'], self.alice))
        self.assertTrue(any(e['action'] == 'claim.rejected' for e in self.s.list_audits(self.admin)))

    def test_full_handover_links_lost_and_found(self):
        lost = self.item(self.alice, 'lost')
        found = self.item(self.bob)
        claim = self.claim(found, lost_id=lost['id'])
        self.s.review_claim(self.bob, claim['id'], 'approve', '特征一致')
        self.assertEqual(self.s.get_item(found['id'], self.alice)['contact'], 'demo@example.test')
        self.assertEqual(self.s.get_item(lost['id'])['status'], 'reserved')
        with self.assertRaises(DomainError):
            self.s.close_claim(self.alice, claim['id'])
        self.s.close_claim(self.bob, claim['id'])
        self.assertEqual(self.s.get_item(found['id'])['status'], 'resolved')
        self.assertEqual(self.s.get_item(lost['id'])['status'], 'resolved')
        self.assertEqual(self.s.list_claims(self.alice)[0]['status'], 'completed')

    def test_ownership_and_role_enforced(self):
        found = self.item(self.bob)
        with self.assertRaises(DomainError):
            self.s.create_claim(self.bob, found['id'], {'answer': '向阳'})
        claim = self.claim(found)
        with self.assertRaises(DomainError):
            self.s.review_claim(self.alice, claim['id'], 'approve', '')
        with self.assertRaises(DomainError):
            self.s.publish_rule(self.alice, '非法规则', {'text': 1})
        with self.assertRaises(DomainError):
            self.s.delete_item(self.alice, found['id'], '无权限')

    def test_duplicate_claim_and_double_approval_prevented(self):
        found = self.item(self.bob)
        claim = self.claim(found)
        with self.assertRaises(DomainError):
            self.claim(found)
        other = self.s.create_claim(self.admin, found['id'], {'answer': '向阳', 'contact': 'admin@private.example.test'})
        self.s.review_claim(self.bob, claim['id'], 'approve', '')
        with self.assertRaises(DomainError):
            self.s.review_claim(self.bob, other['id'], 'approve', '')
        with self.assertRaises(DomainError):
            self.s.delete_item(self.bob, found['id'], '处理中')

    def test_search_combines_filters_and_soft_delete_persists(self):
        found = self.item(self.bob, title='独特蓝色雨伞', category='雨伞', color='蓝色', location='体育馆')
        result = self.s.list_items(dict(q='独特', category='雨伞', location='体育',
                                       date_from='2026-10-21', date_to='2026-10-22', status='open'))
        self.assertEqual([i['id'] for i in result], [found['id']])
        self.s.delete_item(self.bob, found['id'], '重复发布')
        reopened = Service(self.path)
        reopened.initialize(seed=True)
        self.assertNotIn(found['id'], [i['id'] for i in reopened.list_items({})])
        self.assertTrue(any(e['action'] == 'item.deleted' for e in reopened.list_audits(self.admin)))

    def test_rule_history_recomputes_from_immutable_snapshots(self):
        lost = self.item(self.alice, 'lost')
        found = self.item(self.bob)
        run = self.s.recommend(self.alice, lost['id'])
        match = next(m for m in run['results'] if m['candidate_id'] == found['id'])
        self.assertGreater(match['score'], 70)
        self.assertIn('explanation', match)
        self.s.publish_rule(self.admin, '描述优先', {'category': 0, 'color': 0, 'location': 0, 'time': 0, 'text': 1})
        self.s.delete_item(self.bob, found['id'], '测试快照')
        replay = self.s.recompute(self.alice, run['id'])
        self.assertTrue(replay['identical'])
        self.assertEqual(run['rule_version'], replay['rule_version'])
        self.assertEqual(run['results'], replay['results'])
        with self.assertRaises(DomainError):
            self.s.recompute(self.bob, run['id'])

    def test_required_fields_dates_and_weights_are_validated(self):
        for changes in ({'secret_answer': ''}, {'date_to': '2026-01-01'}, {'kind': 'invalid'}, {'title': ''}):
            with self.subTest(changes=changes), self.assertRaises(DomainError):
                self.item(self.bob, **changes)
        for weights in ({'text': -1}, {'text': float('nan')}, {'unknown': 1}, {'text': 0}):
            with self.subTest(weights=weights), self.assertRaises(DomainError):
                self.s.publish_rule(self.admin, '错误规则', weights)

    def test_concurrent_reviews_have_exactly_one_winner(self):
        found = self.item(self.bob)
        first = self.claim(found)
        second = self.s.create_claim(self.admin, found['id'], {'answer': '向阳', 'contact': 'admin@private.example.test'})

        def approve(cid):
            try:
                self.s.review_claim(self.bob, cid, 'approve', '并发核验')
                return True
            except DomainError:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(approve, [first['id'], second['id']]))
        self.assertEqual(sum(results), 1)
        rows = [c for c in self.s.list_claims(self.bob) if c['item_id'] == found['id']]
        self.assertEqual(sorted(c['status'] for c in rows), ['approved', 'rejected'])

    def test_unlinked_claim_contact_is_private_until_approved(self):
        found = self.item(self.bob)
        with self.assertRaises(DomainError):
            self.s.create_claim(self.alice, found['id'], {'answer': '向阳'})
        claim = self.claim(found)
        for user in (self.alice, self.bob):
            row = next(c for c in self.s.list_claims(user) if c['id'] == claim['id'])
            self.assertNotIn('alice@private.example.test', json.dumps(row))
        self.s.review_claim(self.bob, claim['id'], 'approve', '')
        row = next(c for c in self.s.list_claims(self.bob) if c['id'] == claim['id'])
        self.assertEqual(row['applicant_contact'], 'alice@private.example.test')

    def test_secret_answer_cannot_be_a_public_field(self):
        for changes in ({'secret_answer': '黑色'}, {'secret_answer': '图书馆'},
                        {'secret_answer': '证件'}, {'secret_answer': '2026-10-20'}):
            with self.subTest(changes=changes), self.assertRaises(DomainError):
                self.item(self.bob, **changes)

    def test_legacy_rule_generates_and_replays_using_legacy_engine(self):
        with self.s.db.transaction() as db:
            db.execute("UPDATE rules SET engine_version='offline-text-v1'")
        lost = self.item(self.alice, 'lost', location='一食堂')
        found = self.item(self.bob, location='第一食堂')
        run = self.s.recommend(self.alice, lost['id'])
        self.assertEqual(run['engine_version'], 'offline-text-v1')
        self.assertEqual(next(r for r in run['results'] if r['candidate_id'] == found['id'])['score'], 97)
        self.assertTrue(self.s.recompute(self.alice, run['id'])['identical'])
        self.s.publish_rule(self.admin, '新引擎规则', {'category':25,'location':20,'color':15,'time':15,'text':25})
        new_run = self.s.recommend(self.alice, lost['id'])
        self.assertEqual(new_run['engine_version'], 'offline-text-v2')
        self.assertEqual(next(r for r in new_run['results'] if r['candidate_id'] == found['id'])['score'], 100)
        self.assertTrue(self.s.recompute(self.alice, run['id'])['identical'])

    def test_old_database_contact_migration_is_idempotent(self):
        lost = self.item(self.alice, 'lost', contact='legacy@example.test')
        found = self.item(self.bob)
        claim = self.claim(found, lost_id=lost['id'])
        self.s.review_claim(self.bob, claim['id'], 'approve', '')
        with self.s.db.transaction() as db:
            db.execute('ALTER TABLE claims DROP COLUMN applicant_contact')
        self.s.initialize()
        self.s.initialize()
        row = next(c for c in self.s.list_claims(self.bob) if c['id'] == claim['id'])
        self.assertEqual(row['applicant_contact'], 'legacy@example.test')


if __name__ == '__main__':
    unittest.main()
