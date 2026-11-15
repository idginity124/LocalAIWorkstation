"""SQLite schema versioning and atomic schema migrations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 5


def open_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 10000")
    migrate(connection)
    return connection


def migrate(connection: sqlite3.Connection) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"Veritabanı sürümü ({version}) bu uygulamadan yeni ({SCHEMA_VERSION})."
        )
    if version == 0:
        try:
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE jobs (
                    id TEXT PRIMARY KEY,
                    module TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN (
                        'QUEUED','PREPARING','RUNNING','CANCELLING','CLEANUP',
                        'COMPLETED','FAILED','INTERRUPTED','RECOVERY_REQUIRED'
                    )),
                    priority INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX jobs_status_created ON jobs(status, created_at);
                CREATE TABLE history (
                    job_id TEXT PRIMARY KEY REFERENCES jobs(id),
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE models (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    revision TEXT,
                    license TEXT,
                    path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    sha256 TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE workflows (
                    id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    revision TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    workflow_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                PRAGMA user_version = 1;
                COMMIT;
                """
            )
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        version = 1
    if version == 1:
        try:
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    root_path TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE edit_proposals (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    relative_path TEXT NOT NULL,
                    expected_sha256 TEXT,
                    proposed_content BLOB NOT NULL,
                    diff_text TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('PENDING','APPLIED','STALE','REJECTED')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    applied_at TEXT
                );
                CREATE INDEX edit_proposals_project_created ON edit_proposals(project_id, created_at);
                PRAGMA user_version = 2;
                COMMIT;
                """
            )
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        version = 2
    if version == 2:
        try:
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                ALTER TABLE conversations ADD COLUMN kind TEXT NOT NULL DEFAULT 'code'
                    CHECK (kind IN ('assistant','code'));
                CREATE INDEX conversations_kind_updated ON conversations(kind, updated_at DESC);
                PRAGMA user_version = 3;
                COMMIT;
                """
            )
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        version = 3
    if version == 3:
        try:
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                ALTER TABLE conversations ADD COLUMN model_id TEXT NOT NULL DEFAULT 'gemma-4-12b';
                CREATE INDEX conversations_kind_model_updated ON conversations(kind, model_id, updated_at DESC);
                PRAGMA user_version = 4;
                COMMIT;
                """
            )
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

        version = 4
    if version == 4:
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("ALTER TABLE conversations ADD COLUMN auto_title INTEGER NOT NULL DEFAULT 0")
            connection.execute("ALTER TABLE messages ADD COLUMN finish_reason TEXT NOT NULL DEFAULT 'stop'")
            # Recover default titles written by older translated frontends.
            defaults = ('Yeni sohbet', 'New chat', '新对话', 'नई बातचीत', 'Nuevo chat',
                        'محادثة جديدة', 'নতুন চ্যাট', 'Nova conversa', 'Новый чат',
                        'نئی گفتگو', 'Nouvelle conversation')
            placeholders = ','.join('?' for _ in defaults)
            rows = connection.execute(f"SELECT id FROM conversations WHERE title IN ({placeholders})", defaults).fetchall()
            for row in rows:
                first = connection.execute("SELECT content FROM messages WHERE conversation_id=? AND role='user' ORDER BY rowid LIMIT 1", (row[0],)).fetchone()
                if first:
                    title = next((line.strip()[:60] for line in first[0].splitlines() if line.strip()), 'Yeni sohbet')
                    connection.execute("UPDATE conversations SET title=? WHERE id=?", (title, row[0]))
                else:
                    connection.execute("UPDATE conversations SET auto_title=1 WHERE id=?", (row[0],))
            connection.execute("PRAGMA user_version = 5")
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
