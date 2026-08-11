"""SQLite storage for Padhai.

The app used to be deliberately memory-only. It now keeps accounts, sticky
notes, uploaded material and — importantly — every generated analysis, so a
document is only ever sent to the AI once. Coming back the next day loads the
summary, mind map and flashcards straight from disk.

One connection is shared across Flask's threads (`check_same_thread=False`)
with a lock around writes; WAL mode keeps concurrent reads fast.
"""
import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path

log = logging.getLogger("padhai.db")


def _db_path() -> Path:
    """Where the database lives.

    The project was renamed from StudyAI to Padhai. Simply changing the default
    filename would orphan every document already stored, so an existing
    studyai.db is adopted (renamed) instead of abandoned.
    """
    override = os.getenv("PADHAI_DB") or os.getenv("STUDYAI_DB")
    if override:
        return Path(override).expanduser()

    # On a serverless host the deployment bundle is read-only, so creating the
    # database next to the code fails with "unable to open database file" and
    # every account/upload/notes route 500s. /tmp is the one writable path.
    # Vercel sets VERCEL=1 in every function environment.
    #
    # This storage is per-instance and cleared when the instance is recycled,
    # so accounts do not survive a cold start. Point PADHAI_DB at a hosted
    # database (or a mounted volume) for real persistence.
    if os.getenv("VERCEL"):
        return Path("/tmp/padhai.db")

    root = Path(__file__).resolve().parent.parent.parent
    new_path, old_path = root / "padhai.db", root / "studyai.db"
    if not new_path.exists() and old_path.exists():
        for suffix in ("", "-wal", "-shm"):        # WAL journal files too
            src = Path(str(old_path) + suffix)
            if src.exists():
                src.rename(str(new_path) + suffix)
        log.info("Adopted existing database: studyai.db -> padhai.db")
    return new_path


DB_PATH = _db_path()

# Reentrant: query()/write() hold the lock and may call connect() inside it.
_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id         TEXT PRIMARY KEY,
  email      TEXT UNIQUE NOT NULL,
  name       TEXT NOT NULL DEFAULT '',
  pw_hash    TEXT NOT NULL,
  pw_salt    TEXT NOT NULL,
  created    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  token   TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created REAL NOT NULL,
  expires REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

-- user_id is NULL for guests; those rows are evicted on the usual TTL.
CREATE TABLE IF NOT EXISTS documents (
  id       TEXT PRIMARY KEY,
  user_id  TEXT REFERENCES users(id) ON DELETE CASCADE,
  filename TEXT NOT NULL,
  text     TEXT NOT NULL,
  chunks   TEXT NOT NULL,
  meta     TEXT NOT NULL,
  created  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_user ON documents(user_id, created);

CREATE TABLE IF NOT EXISTS analyses (
  doc_id  TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  kind    TEXT NOT NULL,
  payload TEXT NOT NULL,
  created REAL NOT NULL,
  PRIMARY KEY (doc_id, kind)
);

-- One row per graded exam paper. weak_topics/details/timings are JSON blobs;
-- the report service aggregates these into the student's progress report.
CREATE TABLE IF NOT EXISTS attempts (
  id          TEXT PRIMARY KEY,
  user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  doc_name    TEXT NOT NULL DEFAULT '',
  topic       TEXT NOT NULL DEFAULT '',
  difficulty  TEXT NOT NULL DEFAULT '',
  awarded     REAL NOT NULL DEFAULT 0,
  total       REAL NOT NULL DEFAULT 0,
  pct         REAL NOT NULL DEFAULT 0,
  grade       TEXT NOT NULL DEFAULT '',
  weak_topics TEXT NOT NULL DEFAULT '[]',
  details     TEXT NOT NULL DEFAULT '[]',
  created     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attempts_user ON attempts(user_id, created);

-- One row per practice question answered (lightweight event log).
CREATE TABLE IF NOT EXISTS practice_log (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id  TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  qtype    TEXT NOT NULL DEFAULT '',
  topic    TEXT NOT NULL DEFAULT '',
  doc_name TEXT NOT NULL DEFAULT '',
  question TEXT NOT NULL DEFAULT '',
  correct  INTEGER NOT NULL DEFAULT 0,
  seconds  REAL NOT NULL DEFAULT 0,
  created  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_practice_user ON practice_log(user_id, created);

-- Latest generated AI progress report per user (regenerating replaces it).
CREATE TABLE IF NOT EXISTS reports (
  user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  payload TEXT NOT NULL,
  created REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
  id      TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  board   TEXT NOT NULL DEFAULT 'main',
  text    TEXT NOT NULL DEFAULT '',
  colour  TEXT NOT NULL DEFAULT 'yellow',
  x       REAL NOT NULL DEFAULT 40,
  y       REAL NOT NULL DEFAULT 40,
  w       REAL NOT NULL DEFAULT 210,
  h       REAL NOT NULL DEFAULT 210,
  rot     REAL NOT NULL DEFAULT 0,
  z       INTEGER NOT NULL DEFAULT 1,
  created REAL NOT NULL,
  updated REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id, board);

-- Contact-form messages. Stored before any delivery attempt, so nothing is
-- lost when email is unconfigured or a provider is down.
CREATE TABLE IF NOT EXISTS messages (
  id        TEXT PRIMARY KEY,
  name      TEXT NOT NULL DEFAULT '',
  email     TEXT NOT NULL DEFAULT '',
  subject   TEXT NOT NULL DEFAULT '',
  body      TEXT NOT NULL,
  user_id   TEXT,
  ip        TEXT NOT NULL DEFAULT '',
  delivered TEXT NOT NULL DEFAULT '',   -- transport that sent it, or ''
  error     TEXT NOT NULL DEFAULT '',
  created   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created);
CREATE INDEX IF NOT EXISTS idx_messages_ip ON messages(ip, created);
"""


def connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        with _lock:
            if _conn is None:
                DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA foreign_keys=ON")
                conn.executescript(SCHEMA)
                conn.commit()
                _conn = conn
                log.info("SQLite ready at %s", DB_PATH)
    return _conn


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with _lock:
        return connect().execute(sql, params).fetchall()


def one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    with _lock:
        return connect().execute(sql, params).fetchone()


def write(sql: str, params: tuple = ()) -> None:
    with _lock:
        conn = connect()
        conn.execute(sql, params)
        conn.commit()


def write_many(statements: list[tuple[str, tuple]]) -> None:
    """Run several statements in one transaction."""
    with _lock:
        conn = connect()
        for sql, params in statements:
            conn.execute(sql, params)
        conn.commit()


# --- small helpers so callers don't repeat json.dumps everywhere ---
dump = json.dumps


def load(raw, fallback=None):
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return fallback


def now() -> float:
    return time.time()
