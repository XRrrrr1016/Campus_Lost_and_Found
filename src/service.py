"""Domain services: every mutation validates permissions inside a transaction."""
import base64
import hashlib
import hmac
import json
import math
import re
import secrets
import time
import unicodedata
from datetime import date, datetime, timezone

from .database import Database
from .matching import DEFAULT_WEIGHTS, ENGINE_VERSION, SUPPORTED_ENGINES, score_pair

CATEGORIES = ['电子产品', '证件', '钥匙', '雨伞', '书籍', '包袋', '衣物', '其他']


class DomainError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def pack(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def hash_secret(value):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', value.encode(), salt.encode(), 120_000).hex()
    return f'{salt}:{digest}'


def check_secret(value, encoded):
    if not encoded or ':' not in encoded:
        return False
    salt, expected = encoded.split(':', 1)
    actual = hashlib.pbkdf2_hmac('sha256', value.encode(), salt.encode(), 120_000).hex()
    return hmac.compare_digest(actual, expected)


def answer_key(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value).casefold())


def text_field(body, key, limit=200, required=True):
    value = body.get(key, '')
    if not isinstance(value, str):
        raise DomainError(f'{key} 必须为字符串')
    value = value.strip()
    if (required and not value) or len(value) > limit:
        raise DomainError(f'{key} 必填且不得超过 {limit} 字' if required else f'{key} 不得超过 {limit} 字')
    return value


def valid_date(value):
    try:
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ValueError()
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise DomainError('日期必须为有效的 YYYY-MM-DD') from None


class Service:
    def __init__(self, path):
        self.db = Database(path)

    def initialize(self, seed=True):
        self.db.initialize()
        with self.db.transaction() as db:
            if not db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
                for username, name, role, password in (
                    ('alice', '林同学', 'user', 'demo1234'),
                    ('bob', '陈同学', 'user', 'demo1234'),
                    ('admin', '校园管理员', 'admin', 'admin1234')):
                    db.execute('INSERT INTO users(username,name,role,password_hash) VALUES (?,?,?,?)',
                               (username, name, role, hash_secret(password)))
            if not db.execute('SELECT 1 FROM rules LIMIT 1').fetchone():
                db.execute('INSERT INTO rules(name,weights,engine_version,created_at) VALUES (?,?,?,?)',
                           ('校园基础匹配规则', pack(DEFAULT_WEIGHTS), ENGINE_VERSION, now()))
            if seed and not db.execute('SELECT 1 FROM items LIMIT 1').fetchone():
                self._seed(db)

    def _seed(self, db):
        examples = [
            (1, 'lost', '在图书馆遗失黑色卡包', '证件', '图书馆二楼', '黑色', '黑色卡包，内有校园卡和借书卡，边缘有磨损。'),
            (2, 'found', '图书馆捡到一个黑色卡包', '证件', '图书馆二楼', '黑色', '黑色卡包，内有校园卡和借书卡，请失主核验。'),
            (2, 'found', '一食堂门口的蓝色折叠伞', '雨伞', '第一食堂', '蓝色', '蓝色三折雨伞，木质伞柄，在门口长椅发现。'),
            (1, 'lost', '寻找白色无线耳机', '电子产品', '体育馆', '白色', '白色无线耳机和充电盒，外壳有小猫贴纸。'),
            (2, 'found', '体育馆拾到白色耳机盒', '电子产品', '体育馆东门', '白色', '白色无线耳机和充电盒，外壳有小猫贴纸。'),
            (2, 'found', '操场看台的银色钥匙', '钥匙', '操场看台', '银色', '三把银色钥匙，带着一个小熊挂件。'),
            (1, 'lost', '蓝色双肩包寻物启事', '包袋', '教学楼A座', '蓝色', '蓝色双肩包，装有高等数学课本。'),
            (2, 'found', '自习室拾到高等数学书', '书籍', '教学楼A座', '白色', '白色封面的高等数学课本，有手写笔记。'),
        ]
        for owner, kind, title, category, location, color, description in examples:
            question, answer = ('卡包内侧手写的两个字是什么？', '向阳') if category == '证件' else ('物品隐蔽处的专属标记是什么？', '小太阳')
            db.execute('''INSERT INTO items(owner_id,kind,title,category,date_from,date_to,location,color,
                       description,contact,secret_question,secret_hash,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                       (owner, kind, title, category, '2026-10-25', '2026-10-26', location, color, description,
                        f'{"alice" if owner == 1 else "bob"}@campus.example.test',
                        question if kind == 'found' else '', hash_secret(answer_key(answer)) if kind == 'found' else '', now()))
        self._audit(db, None, 'system.seeded', 'system', None, {'items': len(examples)})

    def _audit(self, db, user, action, entity, entity_id, detail=None):
        db.execute('INSERT INTO audits(actor_id,action,entity_type,entity_id,detail,created_at) VALUES (?,?,?,?,?,?)',
                   (user['id'] if user else None, action, entity, entity_id, pack(detail or {}), now()))

    def _require_user(self, user):
        if not user:
            raise DomainError('请先登录', 401)

    def _admin(self, user):
        self._require_user(user)
        if user['role'] != 'admin':
            raise DomainError('仅管理员可执行此操作', 403)

    def _manage(self, user, item):
        self._require_user(user)
        if user['id'] != item['owner_id'] and user['role'] != 'admin':
            raise DomainError('仅发布者或管理员可执行此操作', 403)

    def _item(self, db, item_id):
        row = db.execute('SELECT i.*,u.name AS owner_name FROM items i JOIN users u ON u.id=i.owner_id WHERE i.id=?', (item_id,)).fetchone()
        if not row or row['status'] == 'deleted':
            raise DomainError('记录不存在或已删除', 404)
        return dict(row)

    def login(self, username, password):
        if not isinstance(username, str) or not isinstance(password, str) or len(password) > 200:
            raise DomainError('账号或密码错误', 401)
        with self.db.transaction() as db:
            row = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
            if not row or not check_secret(password, row['password_hash']):
                # Equalize common unknown-user timing; no credentials enter the audit.
                if not row:
                    hashlib.pbkdf2_hmac('sha256', password.encode(), b'unknown-user', 120_000)
                raise DomainError('账号或密码错误', 401)
            user = {k: row[k] for k in ('id', 'username', 'name', 'role')}
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
            db.execute('DELETE FROM sessions WHERE expires_at<?', (int(time.time()),))
            db.execute('INSERT INTO sessions VALUES (?,?,?,?)',
                       (hashlib.sha256(token.encode()).hexdigest(), user['id'], csrf, int(time.time()) + 43200))
            self._audit(db, user, 'auth.login', 'user', user['id'])
            return {'user': user, 'token': token, 'csrf': csrf}

    def session(self, token):
        if not token:
            return None
        with self.db.read() as db:
            row = db.execute('''SELECT u.id,u.username,u.name,u.role,s.csrf FROM sessions s
                              JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?''',
                             (hashlib.sha256(token.encode()).hexdigest(), int(time.time()))).fetchone()
            return dict(row) if row else None

    def logout(self, token):
        with self.db.transaction() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))

    def _public(self, db, row, user=None):
        item = dict(row)
        item.pop('secret_hash', None)
        contact = item.pop('contact', None)
        allowed = user and (user['id'] == item['owner_id'] or user['role'] == 'admin')
        if user and not allowed:
            allowed = db.execute('''SELECT 1 FROM claims WHERE status IN ('approved','completed') AND
                        ((item_id=? AND applicant_id=?) OR (lost_item_id=? AND item_id IN
                        (SELECT id FROM items WHERE owner_id=?))) LIMIT 1''',
                                 (item['id'], user['id'], item['id'], user['id'])).fetchone()
        if allowed:
            item['contact'] = contact
        return item

    def get_item(self, item_id, user=None):
        with self.db.read() as db:
            return self._public(db, self._item(db, item_id), user)

    def list_items(self, filters, user=None):
        clauses, args = ["i.status!='deleted'"], []
        for key in ('kind', 'category', 'status'):
            if filters.get(key):
                clauses.append(f'i.{key}=?')
                args.append(filters[key])
        for key in ('q', 'location'):
            if filters.get(key):
                # instr treats user input literally, so % is not a SQL wildcard.
                clauses.append('instr(lower(i.title || i.description || i.location), lower(?))>0' if key == 'q' else 'instr(lower(i.location),lower(?))>0')
                args.append(str(filters[key])[:200])
        if filters.get('date_from'):
            clauses.append('i.date_to>=?')
            args.append(valid_date(filters['date_from']))
        if filters.get('date_to'):
            clauses.append('i.date_from<=?')
            args.append(valid_date(filters['date_to']))
        if filters.get('date_from') and filters.get('date_to') and filters['date_from'] > filters['date_to']:
            raise DomainError('开始日期不能晚于结束日期')
        if filters.get('mine'):
            self._require_user(user)
            clauses.append('i.owner_id=?')
            args.append(user['id'])
        with self.db.read() as db:
            rows = db.execute('SELECT i.*,u.name AS owner_name FROM items i JOIN users u ON u.id=i.owner_id WHERE '
                              + ' AND '.join(clauses) + ' ORDER BY i.id DESC LIMIT 500', args).fetchall()
            return [self._public(db, row, user) for row in rows]

    def create_item(self, user, body):
        self._require_user(user)
        values = {k: text_field(body, k, limit) for k, limit in (
            ('kind', 10), ('title', 80), ('category', 20), ('location', 100), ('color', 30),
            ('description', 2000), ('contact', 150))}
        if values['kind'] not in ('lost', 'found') or values['category'] not in CATEGORIES:
            raise DomainError('无效的类型或类别')
        values['date_from'] = valid_date(body.get('date_from'))
        values['date_to'] = valid_date(body.get('date_to'))
        if values['date_from'] > values['date_to']:
            raise DomainError('开始日期不能晚于结束日期')
        found = values['kind'] == 'found'
        values['secret_question'] = text_field(body, 'secret_question', 200, required=found) if found else ''
        answer = text_field(body, 'secret_answer', 100, required=found) if found else ''
        public_fields = ('kind', 'title', 'category', 'location', 'color', 'date_from', 'date_to', 'description', 'secret_question')
        if found and any(answer_key(answer) in answer_key(values[k]) for k in public_fields):
            raise DomainError('私密答案不能直接出现在任何公开文字字段中')
        values['secret_hash'] = hash_secret(answer_key(answer)) if found else ''
        image = text_field(body, 'image', 700_000, required=False)
        if image:
            try:
                header, payload = image.split(',', 1)
                signatures = {'data:image/png;base64': b'\x89PNG\r\n\x1a\n', 'data:image/jpeg;base64': b'\xff\xd8\xff',
                              'data:image/webp;base64': b'RIFF'}
                raw = base64.b64decode(payload, validate=True)
                if header not in signatures or len(raw) > 500_000 or not raw.startswith(signatures[header]):
                    raise ValueError()
                if header.endswith('webp;base64') and raw[8:12] != b'WEBP':
                    raise ValueError()
            except (ValueError, TypeError):
                raise DomainError('图片仅支持 500KB 内的 PNG/JPEG/WebP') from None
        values.update(image=image, owner_id=user['id'], created_at=now())
        with self.db.transaction() as db:
            columns = ','.join(values)
            item_id = db.execute(f'INSERT INTO items({columns}) VALUES ({",".join("?" for _ in values)})', tuple(values.values())).lastrowid
            self._audit(db, user, 'item.created', 'item', item_id, {'kind': values['kind']})
            return self._public(db, self._item(db, item_id), user)

    def delete_item(self, user, item_id, reason):
        reason = text_field({'reason': reason}, 'reason', 300)
        with self.db.transaction() as db:
            item = self._item(db, item_id)
            self._manage(user, item)
            if item['status'] != 'open':
                raise DomainError('仅开放记录可删除，保留中请先完成交接')
            pending = db.execute('SELECT id FROM claims WHERE (item_id=? OR lost_item_id=?) AND status="pending"', (item_id, item_id)).fetchall()
            for claim in pending:
                self._reject(db, user, claim['id'], '关联记录已删除')
            db.execute('UPDATE items SET status="deleted" WHERE id=?', (item_id,))
            self._audit(db, user, 'item.deleted', 'item', item_id, {'reason': reason, 'from': item['status'], 'to': 'deleted'})
        return {'ok': True}

    def create_claim(self, user, item_id, body):
        self._require_user(user)
        answer = text_field(body, 'answer', 100)
        note = text_field(body, 'note', 500, required=False)
        contact = text_field(body, 'contact', 150, required=False)
        lost_id = body.get('lost_item_id') or None
        if lost_id is not None and (type(lost_id) is not int or lost_id < 1):
            raise DomainError('关联失物 ID 无效')
        with self.db.transaction() as db:
            item = self._item(db, item_id)
            if item['kind'] != 'found' or item['status'] != 'open':
                raise DomainError('只能认领开放的招领记录')
            if user['id'] == item['owner_id']:
                raise DomainError('不能认领自己发布的物品')
            if db.execute('SELECT 1 FROM claims WHERE item_id=? AND applicant_id=?', (item_id, user['id'])).fetchone():
                raise DomainError('你已经提交过申请，请查看认领进度', 409)
            if lost_id:
                lost = self._item(db, lost_id)
                if lost['kind'] != 'lost' or lost['owner_id'] != user['id'] or lost['status'] != 'open':
                    raise DomainError('只能关联本人开放的失物记录')
                contact = contact or lost['contact']
            if not contact:
                raise DomainError('请提供受保护的联系方式，或关联带联系方式的本人失物')
            cid = db.execute('''INSERT INTO claims(item_id,applicant_id,lost_item_id,feature_matches,note,applicant_contact,created_at,updated_at)
                               VALUES (?,?,?,?,?,?,?,?)''',
                             (item_id, user['id'], lost_id, int(check_secret(answer_key(answer), item['secret_hash'])), note, contact, now(), now())).lastrowid
            self._audit(db, user, 'claim.created', 'claim', cid, {'item_id': item_id})
            return {'id': cid, 'status': 'pending', 'message': '申请已提交，请等待拾获者核验。'}

    def list_claims(self, user):
        self._require_user(user)
        with self.db.read() as db:
            rows = db.execute('''SELECT c.*,i.title,i.owner_id,i.secret_question,u.name AS applicant_name,
                           o.name AS owner_name FROM claims c JOIN items i ON i.id=c.item_id
                           JOIN users u ON u.id=c.applicant_id JOIN users o ON o.id=i.owner_id
                           WHERE c.applicant_id=? OR i.owner_id=? OR ?='admin' ORDER BY c.id DESC''',
                              (user['id'], user['id'], user['role'])).fetchall()
            result = []
            for row in rows:
                claim = dict(row)
                if user['id'] != row['owner_id'] and user['role'] != 'admin':
                    claim.pop('feature_matches')
                if row['status'] in ('approved', 'completed'):
                    claim['finder_contact'] = db.execute('SELECT contact FROM items WHERE id=?', (row['item_id'],)).fetchone()[0]
                else:
                    claim.pop('applicant_contact', None)
                result.append(claim)
            return result

    def _claim(self, db, claim_id):
        row = db.execute('SELECT * FROM claims WHERE id=?', (claim_id,)).fetchone()
        if not row:
            raise DomainError('申请不存在', 404)
        return dict(row)

    def _reject(self, db, user, cid, note):
        db.execute('UPDATE claims SET status="rejected",review_note=?,updated_at=? WHERE id=?', (note, now(), cid))
        self._audit(db, user, 'claim.rejected', 'claim', cid, {'reason': note, 'from': 'pending', 'to': 'rejected'})

    def review_claim(self, user, claim_id, decision, note):
        note = text_field({'note': note}, 'note', 500, required=False)
        if decision not in ('approve', 'reject'):
            raise DomainError('无效的审核操作')
        with self.db.transaction() as db:
            claim = self._claim(db, claim_id)
            item = self._item(db, claim['item_id'])
            self._manage(user, item)
            if claim['status'] != 'pending' or item['status'] != 'open':
                raise DomainError('申请状态已变化，请刷新', 409)
            if decision == 'reject':
                if not note:
                    raise DomainError('请填写驳回原因')
                self._reject(db, user, claim_id, note)
            else:
                if not claim['feature_matches']:
                    raise DomainError('未公开特征核验不符，不能通过')
                lost = self._item(db, claim['lost_item_id']) if claim['lost_item_id'] else None
                if lost and lost['status'] != 'open':
                    raise DomainError('关联失物已被处理，请驳回该申请', 409)
                db.execute('UPDATE claims SET status="approved",review_note=?,updated_at=? WHERE id=?', (note, now(), claim_id))
                ids = [item['id']] + ([lost['id']] if lost else [])
                for iid in ids:
                    db.execute('UPDATE items SET status="reserved" WHERE id=?', (iid,))
                    self._audit(db, user, 'item.reserved', 'item', iid, {'claim_id': claim_id, 'from': 'open', 'to': 'reserved'})
                pending = db.execute('''SELECT id FROM claims WHERE status='pending' AND
                          (item_id=? OR (lost_item_id IS NOT NULL AND lost_item_id=?))''', (item['id'], claim['lost_item_id'])).fetchall()
                for other in pending:
                    self._reject(db, user, other['id'], '物品或关联失物已有核验通过的申请')
                self._audit(db, user, 'claim.approved', 'claim', claim_id, {'from': 'pending', 'to': 'approved'})
        return {'ok': True}

    def close_claim(self, user, claim_id):
        with self.db.transaction() as db:
            claim = self._claim(db, claim_id)
            item = self._item(db, claim['item_id'])
            self._manage(user, item)
            if claim['status'] != 'approved' or item['status'] != 'reserved':
                raise DomainError('只有核验通过的申请可确认交接', 409)
            db.execute('UPDATE claims SET status="completed",updated_at=? WHERE id=?', (now(), claim_id))
            for iid in [item['id']] + ([claim['lost_item_id']] if claim['lost_item_id'] else []):
                db.execute('UPDATE items SET status="resolved" WHERE id=?', (iid,))
                self._audit(db, user, 'item.resolved', 'item', iid, {'claim_id': claim_id, 'from': 'reserved', 'to': 'resolved'})
            self._audit(db, user, 'claim.completed', 'claim', claim_id, {'from': 'approved', 'to': 'completed'})
        return {'ok': True}

    def list_rules(self):
        with self.db.read() as db:
            return [dict(row) | {'weights': json.loads(row['weights'])} for row in db.execute('SELECT * FROM rules ORDER BY id DESC')]

    def publish_rule(self, user, name, weights):
        self._admin(user)
        name = text_field({'name': name}, 'name', 100)
        if not isinstance(weights, dict) or not weights or set(weights) - set(DEFAULT_WEIGHTS):
            raise DomainError('权重字段仅支持 category/location/color/time/text')
        if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 or v > 100 for v in weights.values()):
            raise DomainError('权重必须为 0–100 的有限数值')
        total = sum(weights.values())
        if total <= 0:
            raise DomainError('至少启用一个字段，权重和需大于 0')
        normalized = {k: weights.get(k, 0) / total for k in DEFAULT_WEIGHTS}
        with self.db.transaction() as db:
            rid = db.execute('INSERT INTO rules(name,weights,engine_version,created_by,created_at) VALUES (?,?,?,?,?)',
                             (name, pack(normalized), ENGINE_VERSION, user['id'], now())).lastrowid
            self._audit(db, user, 'rule.published', 'rule', rid, {'weights': normalized})
            return {'id': rid, 'name': name, 'weights': normalized, 'engine_version': ENGINE_VERSION}

    def _snapshot(self, row):
        return {k: row[k] for k in ('id', 'title', 'kind', 'category', 'location', 'color', 'description', 'date_from', 'date_to')}

    def _calculate(self, snapshot):
        results = [dict(candidate_id=c['id'], title=c['title'], **score_pair(snapshot['source'], c, snapshot['weights'], snapshot['engine_version'])) for c in snapshot['candidates']]
        return sorted(results, key=lambda r: (-r['score'], r['candidate_id']))

    def recommend(self, user, item_id):
        self._require_user(user)
        with self.db.transaction() as db:
            source = self._item(db, item_id)
            self._manage(user, source)
            if source['status'] != 'open':
                raise DomainError('只能为开放记录生成推荐')
            rule = db.execute('SELECT * FROM rules ORDER BY id DESC LIMIT 1').fetchone()
            if rule['engine_version'] not in SUPPORTED_ENGINES:
                raise DomainError('当前规则使用的匹配引擎不受支持，请管理员发布新规则', 409)
            candidates = db.execute('SELECT * FROM items WHERE kind!=? AND status="open" AND owner_id!=? ORDER BY id LIMIT 500',
                                    (source['kind'], source['owner_id'])).fetchall()
            snapshot = {'engine_version': rule['engine_version'], 'weights': json.loads(rule['weights']),
                        'source': self._snapshot(source), 'candidates': [self._snapshot(c) for c in candidates]}
            results = self._calculate(snapshot)
            rid = db.execute('INSERT INTO recommendations(user_id,source_id,rule_id,snapshot,results,created_at) VALUES (?,?,?,?,?,?)',
                             (user['id'], item_id, rule['id'], pack(snapshot), pack(results), now())).lastrowid
            self._audit(db, user, 'matching.generated', 'recommendation', rid, {'rule_version': rule['id'], 'source_id': item_id})
            return {'id': rid, 'source_id': item_id, 'rule_version': rule['id'], 'engine_version': rule['engine_version'], 'results': results}

    def list_recommendations(self, user):
        self._require_user(user)
        with self.db.read() as db:
            rows = db.execute('''SELECT r.id,r.source_id,r.rule_id AS rule_version,r.created_at,i.title
                                 FROM recommendations r JOIN items i ON i.id=r.source_id
                                 WHERE r.user_id=? OR ?='admin' ORDER BY r.id DESC LIMIT 100''', (user['id'], user['role'])).fetchall()
            return [dict(r) for r in rows]

    def recompute(self, user, run_id):
        self._require_user(user)
        with self.db.read() as db:
            row = db.execute('SELECT * FROM recommendations WHERE id=?', (run_id,)).fetchone()
            if not row:
                raise DomainError('推荐记录不存在', 404)
            if row['user_id'] != user['id'] and user['role'] != 'admin':
                raise DomainError('无权查看该推荐记录', 403)
            snapshot = json.loads(row['snapshot'])
            if snapshot['engine_version'] not in SUPPORTED_ENGINES:
                raise DomainError('历史引擎版本当前不可用，拒绝不准确的复算', 409)
            result = self._calculate(snapshot)
            return {'id': row['id'], 'source_id': row['source_id'], 'rule_version': row['rule_id'],
                    'engine_version': snapshot['engine_version'], 'results': result,
                    'identical': result == json.loads(row['results'])}

    def list_audits(self, user):
        self._admin(user)
        with self.db.read() as db:
            return [dict(row) | {'detail': json.loads(row['detail'])} for row in db.execute('''SELECT a.*,u.name AS actor_name
                    FROM audits a LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.id DESC LIMIT 500''')]
