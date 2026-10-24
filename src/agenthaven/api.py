import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agenthaven.isolation.runner import (
    SandboxError,
    execute_python,
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
    return datetime.now(UTC).isoformat()


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

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS executions (
                id TEXT PRIMARY KEY,
                sandbox_id TEXT NOT NULL,
                language TEXT NOT NULL,
                exit_code INTEGER,
                duration_ms REAL NOT NULL,
                timed_out INTEGER NOT NULL DEFAULT 0,
                truncated INTEGER NOT NULL DEFAULT 0,
                executed_at TEXT NOT NULL,
                FOREIGN KEY (sandbox_id)
                    REFERENCES sandboxes(id)
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

        execution_id = str(uuid4())

        with database() as conn:
            conn.execute(
                """
                INSERT INTO executions (
                    id,
                    sandbox_id,
                    language,
                    exit_code,
                    duration_ms,
                    timed_out,
                    truncated,
                    executed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    execution_id,
                    sid,
                    request.language,
                    result["exit_code"],
                    result["duration_ms"],
                    int(result["timed_out"]),
                    int(result["truncated"]),
                    now(),
                ),
            )

        return {
            "execution_id": execution_id,
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


# AgentHaven v0.3.1 — Text File Management

MAX_FILE_BYTES = 64 * 1024

# Flat filenames only. No directories, dotfiles or path traversal.
FILE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$")


class FileRequest(BaseModel):
    content: str = Field(max_length=65536)


def get_active_workspace(sandbox_id: UUID) -> Path:
    sid = str(sandbox_id)
    record = get_record(sid)

    if record["status"] != "created":
        raise HTTPException(409, "Sandbox is not active")

    workspace = DATA_DIR / "sandboxes" / sid

    if workspace.is_symlink() or not workspace.is_dir():
        raise HTTPException(409, "Workspace unavailable")

    return workspace


def validate_filename(name: str) -> None:
    if not FILE_NAME_PATTERN.fullmatch(name) or name.startswith("agenthaven_"):
        raise HTTPException(400, "Invalid filename")


@app.put("/sandboxes/{sandbox_id}/files/{filename}")
def write_sandbox_file(
    sandbox_id: UUID,
    filename: str,
    request: FileRequest,
):
    validate_filename(filename)

    content = request.content.encode("utf-8")

    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(413, "File exceeds 64 KB")

    with EXECUTION_LOCK:
        workspace = get_active_workspace(sandbox_id)
        target = workspace / filename

        if target.is_symlink():
            raise HTTPException(409, "Symlink not permitted")

        if target.exists() and not target.is_file():
            raise HTTPException(409, "Not a regular file")

        # Write to a new temporary file, then atomically replace.
        temp_path = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=workspace,
                prefix=".agenthaven-upload-",
                delete=False,
            ) as tmp:
                temp_path = tmp.name
                tmp.write(content)

            os.replace(temp_path, target)

        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

        return {
            "filename": filename,
            "size_bytes": len(content),
            "status": "saved",
        }


@app.get("/sandboxes/{sandbox_id}/files")
def list_sandbox_files(sandbox_id: UUID):
    with EXECUTION_LOCK:
        workspace = get_active_workspace(sandbox_id)

        files = []

        for path in sorted(workspace.iterdir()):
            if (
                FILE_NAME_PATTERN.fullmatch(path.name)
                and not path.name.startswith("agenthaven_")
                and not path.is_symlink()
                and path.is_file()
            ):
                files.append(
                    {
                        "filename": path.name,
                        "size_bytes": path.stat().st_size,
                    }
                )

        return {"files": files}


@app.get("/sandboxes/{sandbox_id}/files/{filename}")
def read_sandbox_file(sandbox_id: UUID, filename: str):
    validate_filename(filename)

    with EXECUTION_LOCK:
        workspace = get_active_workspace(sandbox_id)
        path = workspace / filename

        if path.is_symlink() or not path.is_file():
            raise HTTPException(404, "File not found")

        if path.stat().st_size > MAX_FILE_BYTES:
            raise HTTPException(413, "File exceeds 64 KB")

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise HTTPException(415, "Only UTF-8 text is supported")

        return {
            "filename": filename,
            "content": content,
        }


@app.delete("/sandboxes/{sandbox_id}/files/{filename}")
def delete_sandbox_file(sandbox_id: UUID, filename: str):
    validate_filename(filename)

    with EXECUTION_LOCK:
        workspace = get_active_workspace(sandbox_id)
        path = workspace / filename

        if path.is_symlink() or not path.is_file():
            raise HTTPException(404, "File not found")

        path.unlink()

        return {
            "filename": filename,
            "status": "deleted",
        }


@app.get("/sandboxes/{sandbox_id}/executions")
def list_executions(sandbox_id: UUID):
    sid = str(sandbox_id)

    with EXECUTION_LOCK:
        get_record(sid)

        with database() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM executions
                WHERE sandbox_id = ?
                ORDER BY executed_at DESC
                """,
                (sid,),
            ).fetchall()

        return {
            "sandbox_id": sid,
            "executions": [dict(row) for row in rows],
        }


@app.get("/sandboxes/{sandbox_id}/executions/{execution_id}")
def get_execution(sandbox_id: UUID, execution_id: UUID):
    sid = str(sandbox_id)

    with EXECUTION_LOCK:
        get_record(sid)

        with database() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM executions
                WHERE sandbox_id = ? AND id = ?
                """,
                (sid, str(execution_id)),
            ).fetchone()

        if row is None:
            raise HTTPException(
                status_code=404,
                detail="Execution not found",
            )

        return dict(row)
