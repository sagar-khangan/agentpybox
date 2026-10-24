import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException

from threading import Lock
from pydantic import BaseModel, Field

from agenthaven.isolation.runner import (
    execute_python,
    SandboxError,
)

app = FastAPI(
    title="AgentHaven",
    description="Local execution sandbox runtime",
    version="0.1.0",
)
EXECUTION_LOCK = Lock()


class ExecuteRequest(BaseModel):
    code: str = Field(min_length=1, max_length=65536)
    language: str = "python"


DATA_DIR = Path(__file__).resolve().parents[2] / ".runtime"


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def database():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATA_DIR / "agenthaven.db")
    try:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sandboxes (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                terminated_at TEXT
            )
        """
        )
        conn.commit()
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_record(sandbox_id: str):
    with database() as conn:
        row = conn.execute(
            "SELECT * FROM sandboxes WHERE id = ?",
            (sandbox_id,),
        ).fetchone()

    if row is None:
        raise HTTPException(404, "Sandbox not found")

    return dict(row)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/sandboxes", status_code=201)
def create_sandbox():
    sandbox_id = str(uuid4())
    workspace = DATA_DIR / "sandboxes" / sandbox_id
    workspace.mkdir(parents=True, exist_ok=False)

    try:
        with database() as conn:
            conn.execute(
                """
                INSERT INTO sandboxes
                (id, status, created_at)
                VALUES (?, ?, ?)
                """,
                (sandbox_id, "created", now()),
            )
    except Exception:
        shutil.rmtree(workspace)
        raise

    return get_record(sandbox_id)


@app.get("/sandboxes")
def list_sandboxes():
    with database() as conn:
        rows = conn.execute(
            "SELECT * FROM sandboxes ORDER BY created_at DESC"
        ).fetchall()

    return [dict(row) for row in rows]


@app.get("/sandboxes/{sandbox_id}")
def inspect_sandbox(sandbox_id: UUID):
    return get_record(str(sandbox_id))


@app.delete("/sandboxes/{sandbox_id}")
def terminate_sandbox(sandbox_id: UUID):
    sid = str(sandbox_id)
    record = get_record(sid)

    if record["status"] == "terminated":
        return record

    workspace = DATA_DIR / "sandboxes" / sid

    if workspace.is_symlink():
        raise HTTPException(409, "Unexpected workspace symlink")

    if workspace.exists():
        shutil.rmtree(workspace)

    with database() as conn:
        conn.execute(
            """
            UPDATE sandboxes
            SET status = ?, terminated_at = ?
            WHERE id = ?
            """,
            ("terminated", now(), sid),
        )

    return get_record(sid)


@app.post("/sandboxes/{sandbox_id}/execute")
def execute_sandbox(sandbox_id: UUID, request: ExecuteRequest):
    if request.language != "python":
        raise HTTPException(
            status_code=400,
            detail="Only Python is supported in v0.2",
        )

    with EXECUTION_LOCK:
        sid = str(sandbox_id)
        record = get_record(sid)

        if record["status"] != "created":
            raise HTTPException(
                status_code=409,
                detail="Sandbox is not active",
            )

        workspace = DATA_DIR / "sandboxes" / sid

        if workspace.is_symlink() or not workspace.is_dir():
            raise HTTPException(
                status_code=409,
                detail="Sandbox workspace unavailable",
            )

        try:
            result = execute_python(workspace, request.code)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except (SandboxError, OSError) as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Sandbox execution unavailable: {exc}",
            )

        return {
            "sandbox_id": sid,
            "language": request.language,
            **result,
        }


@app.delete("/sandboxes/{sandbox_id}")
def terminate_sandbox(sandbox_id: UUID):
    with EXECUTION_LOCK:
        sid = str(sandbox_id)
        record = get_record(sid)

        if record["status"] == "terminated":
            return record

        workspace = DATA_DIR / "sandboxes" / sid

        if workspace.is_symlink():
            raise HTTPException(409, "Unexpected workspace symlink")

        if workspace.exists():
            shutil.rmtree(workspace)

        with database() as conn:
            conn.execute(
                """
                UPDATE sandboxes
                SET status = ?, terminated_at = ?
                WHERE id = ?
                """,
                ("terminated", now(), sid),
            )

        return get_record(sid)
