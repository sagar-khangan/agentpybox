"""SQLite metadata, migrations, and inter-process locking."""

import fcntl
import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        (self.root / "workspaces").mkdir(mode=0o700, exist_ok=True)
        self.path = self.root / "agentpybox.sqlite3"
        self.lock_path = self.root / ".lock"
        self.initialize()

    @contextmanager
    def locked(self):
        # One lock for all read-modify-write and execution operations, across CLIs.
        with self.lock_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize(self):
        with self.locked(), self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sandboxes (
                    id TEXT PRIMARY KEY,
                    profile TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    ended_at TEXT
                );
                CREATE TABLE IF NOT EXISTS executions (
                    id TEXT PRIMARY KEY,
                    sandbox_id TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    executed_at TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    exit_code INTEGER,
                    duration_ms REAL NOT NULL,
                    timed_out INTEGER NOT NULL,
                    truncated INTEGER NOT NULL,
                    FOREIGN KEY (sandbox_id) REFERENCES sandboxes(id)
                );
                CREATE INDEX IF NOT EXISTS ix_exec_sandbox
                    ON executions(sandbox_id, executed_at);
                CREATE INDEX IF NOT EXISTS ix_sandbox_expiry
                    ON sandboxes(status, expires_at);
            """)
