"""Banco SQLite do karaoke (data/karaoke.db): contas, sessoes e o historico das festas.

Uma conexao so, protegida por um lock (o servidor atende varias pessoas ao mesmo
tempo). O esquema cresce por migracoes numeradas, com a versao guardada no proprio
banco (PRAGMA user_version): cada migracao nova so acrescenta, nunca reescreve as
anteriores.
"""
import sqlite3
import threading
from contextlib import contextmanager

MIGRATIONS = (
    # 1 -- contas e sessoes (etapa 1)
    """
    CREATE TABLE accounts (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        name_key    TEXT NOT NULL UNIQUE,   -- nome normalizado: "João B." e "joao b" sao o mesmo
        pin_hash    BLOB NOT NULL,
        pin_salt    BLOB NOT NULL,
        photo       INTEGER NOT NULL DEFAULT 0,  -- versao da foto (0 = sem foto)
        admin       INTEGER NOT NULL DEFAULT 0,
        created_at  REAL NOT NULL,
        seen_at     REAL
    );
    CREATE TABLE sessions (
        token_hash  TEXT PRIMARY KEY,       -- so o hash: o token de verdade fica no aparelho
        account_id  TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        device      TEXT NOT NULL DEFAULT '',
        created_at  REAL NOT NULL,
        seen_at     REAL NOT NULL
    );
    CREATE INDEX sessions_account ON sessions(account_id);
    """,
    # 2 -- festas e o que foi cantado em cada uma (etapa 2)
    """
    CREATE TABLE parties (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at  REAL NOT NULL,
        ended_at    REAL                    -- NULL = a festa de agora
    );
    CREATE TABLE performances (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        party_id    INTEGER NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
        entry_id    TEXT NOT NULL,          -- a entrada da fila que foi cantada
        song_id     TEXT NOT NULL,
        title       TEXT,
        account_id  TEXT,                   -- sem REFERENCES: gravar o que foi cantado nunca pode falhar
        singer      TEXT NOT NULL,          -- nome mostrado (sem conta: o nome digitado no PC)
        singer_key  TEXT NOT NULL,          -- quem e a pessoa (ranking e rodizio)
        client      TEXT NOT NULL DEFAULT '',
        state       TEXT NOT NULL,          -- "done" (cantou) ou "skipped" (pulou)
        score       INTEGER,
        started_at  REAL,
        finished_at REAL NOT NULL
    );
    CREATE INDEX performances_party ON performances(party_id, finished_at);
    CREATE INDEX performances_account ON performances(account_id);
    """,
)
SCHEMA_VERSION = len(MIGRATIONS)


class Database:
    def __init__(self, path):
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    @contextmanager
    def tx(self):
        """Uma transacao por vez (uma conexao so, protegida pelo lock)."""
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            self.conn.execute("COMMIT")

    def query(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args).fetchall()

    def _migrate(self):
        with self.tx() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            for number, script in enumerate(MIGRATIONS[version:], version + 1):
                for stmt in script.split(";"):
                    if stmt.strip():
                        db.execute(stmt)
                db.execute(f"PRAGMA user_version = {number}")

    def close(self):
        with self.lock:
            self.conn.close()
