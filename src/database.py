import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('user','admin')), password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 csrf TEXT NOT NULL, expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
 id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id),
 kind TEXT NOT NULL CHECK(kind IN ('lost','found')), title TEXT NOT NULL, category TEXT NOT NULL,
 date_from TEXT NOT NULL, date_to TEXT NOT NULL, location TEXT NOT NULL, color TEXT NOT NULL,
 description TEXT NOT NULL, contact TEXT NOT NULL, secret_question TEXT NOT NULL DEFAULT '',
 secret_hash TEXT NOT NULL DEFAULT '', image TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','reserved','resolved','deleted')),
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claims (
 id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES items(id),
 applicant_id INTEGER NOT NULL REFERENCES users(id), lost_item_id INTEGER REFERENCES items(id),
 feature_matches INTEGER NOT NULL, note TEXT NOT NULL, applicant_contact TEXT NOT NULL DEFAULT '',
 review_note TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected','completed')),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(item_id,applicant_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_winner ON claims(item_id) WHERE status IN ('approved','completed');
CREATE TABLE IF NOT EXISTS rules (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, weights TEXT NOT NULL,
 engine_version TEXT NOT NULL, created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recommendations (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), source_id INTEGER NOT NULL REFERENCES items(id),
 rule_id INTEGER NOT NULL REFERENCES rules(id), snapshot TEXT NOT NULL, results TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audits (
 id INTEGER PRIMARY KEY, actor_id INTEGER REFERENCES users(id), action TEXT NOT NULL,
 entity_type TEXT NOT NULL, entity_id INTEGER, detail TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS item_filters ON items(status,kind,category,date_from,date_to);
CREATE INDEX IF NOT EXISTS claim_applicant ON claims(applicant_id,status);
'''


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=15000')
        return db

    def initialize(self):
        db = self.connect()
        try:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript(SCHEMA)
            # Idempotent upgrade for databases created before private claim contacts.
            columns = {row['name'] for row in db.execute('PRAGMA table_info(claims)')}
            if 'applicant_contact' not in columns:
                db.execute("ALTER TABLE claims ADD COLUMN applicant_contact TEXT NOT NULL DEFAULT ''")
            db.execute('''UPDATE claims SET applicant_contact=COALESCE(
                          (SELECT contact FROM items WHERE id=claims.lost_item_id),'')
                          WHERE applicant_contact='' AND lost_item_id IS NOT NULL''')
            db.commit()
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        db = self.connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @contextmanager
    def read(self):
        db = self.connect()
        try:
            yield db
        finally:
            db.close()
