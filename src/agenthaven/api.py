import asyncio
import logging
import os
import re
import shutil
import sqlite3
import stat
import tempfile
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from agenthaven import observability

from agenthaven.isolation.runner import SandboxError, execute_python

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / ".runtime"
EXECUTION_LOCK = Lock()

DEFAULT_TTL = 300
MAX_TTL = 3600
CLEANUP_INTERVAL = 30

MAX_SOURCE_BYTES = 64 * 1024
MAX_FILE_BYTES = 64 * 1024
MAX_WORKSPACE_BYTES = 10 * 1024 * 1024
MAX_FILES = 100

FILE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")


def now() -> str:
    return datetime.now(UTC).isoformat()


@contextmanager
def database():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATA_DIR / "agenthaven.db", timeout=10)
    conn.row_factory = sqlite3.Row

    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sandboxes (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                terminated_at TEXT,
                expires_at TEXT
            )
        """
        )

        columns = {row["name"] for row in conn.execute("PRAGMA table_info(sandboxes)")}

        if "expires_at" not in columns:
            conn.execute("ALTER TABLE sandboxes ADD COLUMN expires_at TEXT")

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
                FOREIGN KEY(sandbox_id) REFERENCES sandboxes(id)
            )
        """
        )

        yield conn
        conn.commit()

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_record(sid: str) -> dict:
    with database() as conn:
        row = conn.execute("SELECT * FROM sandboxes WHERE id = ?", (sid,)).fetchone()

    if row is None:
        raise HTTPException(404, "Sandbox not found")

    return dict(row)


def workspace_for(sid: str) -> Path:
    return DATA_DIR / "sandboxes" / sid


def remove_workspace(sid: str) -> None:
    workspace = workspace_for(sid)

    if workspace.is_symlink():
        raise RuntimeError("Workspace symlink detected")

    if workspace.exists():
        if not workspace.is_dir():
            raise RuntimeError("Workspace is not a directory")
        shutil.rmtree(workspace)


def terminate_record(sid: str, status: str = "terminated") -> dict:
    record = get_record(sid)

    if record["status"] not in ("created", "running"):
        return record

    remove_workspace(sid)

    with database() as conn:
        conn.execute(
            """
            UPDATE sandboxes
            SET status = ?, terminated_at = ?
            WHERE id = ?
            """,
            (status, now(), sid),
        )

    return get_record(sid)


def get_active_workspace(sid: str) -> Path:
    record = get_record(sid)

    if record["status"] != "created":
        raise HTTPException(409, "Sandbox is not active")

    if record["expires_at"] and record["expires_at"] <= now():
        terminate_record(sid, "expired")
        raise HTTPException(410, "Sandbox expired")

    workspace = workspace_for(sid)

    if workspace.is_symlink() or not workspace.is_dir():
        raise HTTPException(409, "Workspace unavailable")

    return workspace


def expire_sandboxes() -> int:
    """Called from maintenance or background cleanup."""
    count = 0

    with EXECUTION_LOCK:
        with database() as conn:
            rows = conn.execute(
                """
                SELECT id FROM sandboxes
                WHERE status = 'created'
                AND expires_at IS NOT NULL
                AND expires_at <= ?
                """,
                (now(),),
            ).fetchall()

        for row in rows:
            try:
                terminate_record(row["id"], "expired")
                count += 1
            except Exception:
                logger.exception("Could not expire sandbox %s", row["id"])

    return count


async def cleanup_loop():
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL)
        await asyncio.to_thread(expire_sandboxes)


@asynccontextmanager
async def lifespan(app: FastAPI):
    with database():
        pass

    await asyncio.to_thread(expire_sandboxes)
    task = asyncio.create_task(cleanup_loop())

    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="AgentHaven",
    description="Local Dockerless Python execution sandbox API",
    version="1.0.0-dev",
    lifespan=lifespan,
)

observability.configure(database)
app.include_router(observability.router)


class CreateRequest(BaseModel):
    ttl_seconds: int = Field(default=DEFAULT_TTL, ge=10, le=MAX_TTL)


class ExecuteRequest(BaseModel):
    language: str = "python"
    code: str = Field(min_length=1, max_length=MAX_SOURCE_BYTES)


class FileRequest(BaseModel):
    content: str = Field(max_length=MAX_FILE_BYTES)


def validate_filename(filename: str) -> None:
    if not FILE_PATTERN.fullmatch(filename) or filename.startswith("agenthaven_"):
        raise HTTPException(400, "Invalid filename")


def safe_regular_file(path: Path) -> bool:
    try:
        info = path.lstat()
        return stat.S_ISREG(info.st_mode)
    except FileNotFoundError:
        return False


def read_safe_file(workspace: Path, filename: str) -> bytes:
    """Open a regular file without following its final symlink."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open(filename, flags, dir_fd=_workspace_fd(workspace))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise HTTPException(404, "Not a regular file")
        if info.st_size > MAX_FILE_BYTES:
            raise HTTPException(413, "File too large")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            content = stream.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            raise HTTPException(413, "File too large")
        return content
    finally:
        os.close(fd)


def _workspace_fd(workspace: Path) -> int:
    """Caller must close returned descriptor."""
    return os.open(workspace, os.O_RDONLY | os.O_DIRECTORY)


@app.get("/health")
def health():
    return {"status": "ok", "service": "agenthaven"}


@app.post("/sandboxes", status_code=201)
def create_sandbox(request: CreateRequest | None = None):
    request = request or CreateRequest()

    with EXECUTION_LOCK:
        sid = str(uuid4())
        workspace = workspace_for(sid)
        workspace.mkdir(parents=True, exist_ok=False, mode=0o700)

        expires = (
            datetime.now(UTC) + timedelta(seconds=request.ttl_seconds)
        ).isoformat()

        try:
            with database() as conn:
                conn.execute(
                    """
                    INSERT INTO sandboxes
                    (id, status, created_at, expires_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (sid, "created", now(), expires),
                )
        except Exception:
            remove_workspace(sid)
            raise

        return get_record(sid)


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
    with EXECUTION_LOCK:
        return terminate_record(str(sandbox_id))


@app.post("/sandboxes/{sandbox_id}/execute")
def execute_sandbox(sandbox_id: UUID, request: ExecuteRequest):
    if request.language != "python":
        raise HTTPException(400, "Only Python is supported")

    if len(request.code.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise HTTPException(413, "Source too large")

    with EXECUTION_LOCK:
        sid = str(sandbox_id)
        workspace = get_active_workspace(sid)

        try:
            result = execute_python(workspace, request.code)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except (SandboxError, OSError) as exc:
            raise HTTPException(503, "Sandbox runtime unavailable") from exc

        execution_id = str(uuid4())

        with database() as conn:
            conn.execute(
                """
                INSERT INTO executions
                (id, sandbox_id, language, exit_code,
                 duration_ms, timed_out, truncated, executed_at)
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


@app.get("/sandboxes/{sandbox_id}/executions")
def list_executions(sandbox_id: UUID):
    sid = str(sandbox_id)
    get_record(sid)

    with database() as conn:
        rows = conn.execute(
            """
            SELECT * FROM executions
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
def inspect_execution(sandbox_id: UUID, execution_id: UUID):
    sid = str(sandbox_id)
    get_record(sid)

    with database() as conn:
        row = conn.execute(
            """
            SELECT * FROM executions
            WHERE sandbox_id = ? AND id = ?
            """,
            (sid, str(execution_id)),
        ).fetchone()

    if row is None:
        raise HTTPException(404, "Execution not found")

    return dict(row)


@app.put("/sandboxes/{sandbox_id}/files/{filename}")
def write_file(
    sandbox_id: UUID,
    filename: str,
    request: FileRequest,
):
    validate_filename(filename)
    content = request.content.encode("utf-8")

    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(413, "File too large")

    with EXECUTION_LOCK:
        workspace = get_active_workspace(str(sandbox_id))
        target = workspace / filename

        if target.is_symlink():
            raise HTTPException(409, "Symlinks not allowed")

        if target.exists() and not safe_regular_file(target):
            raise HTTPException(409, "Not a regular file")

        files = [p for p in workspace.iterdir() if safe_regular_file(p)]

        if not target.exists() and len(files) >= MAX_FILES:
            raise HTTPException(413, "Too many files")

        used = sum(p.stat().st_size for p in files)
        previous = target.stat().st_size if target.exists() else 0

        if used - previous + len(content) > MAX_WORKSPACE_BYTES:
            raise HTTPException(413, "Workspace limit reached")

        temp_path = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=workspace,
                prefix=".agenthaven-upload-",
                delete=False,
            ) as stream:
                temp_path = stream.name
                stream.write(content)

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
def list_files(sandbox_id: UUID):
    with EXECUTION_LOCK:
        workspace = get_active_workspace(str(sandbox_id))
        files = []

        for path in sorted(workspace.iterdir()):
            if (
                FILE_PATTERN.fullmatch(path.name)
                and not path.name.startswith("agenthaven_")
                and safe_regular_file(path)
            ):
                files.append(
                    {
                        "filename": path.name,
                        "size_bytes": path.stat().st_size,
                    }
                )

        return {"files": files}


@app.get("/sandboxes/{sandbox_id}/files/{filename}")
def read_file(sandbox_id: UUID, filename: str):
    validate_filename(filename)

    with EXECUTION_LOCK:
        workspace = get_active_workspace(str(sandbox_id))
        target = workspace / filename

        if not safe_regular_file(target):
            raise HTTPException(404, "File not found")

        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK

        try:
            fd = os.open(target, flags)
        except OSError as exc:
            raise HTTPException(404, "File unavailable") from exc

        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise HTTPException(404, "Not a regular file")
            if info.st_size > MAX_FILE_BYTES:
                raise HTTPException(413, "File too large")

            content = os.read(fd, MAX_FILE_BYTES + 1)
            if len(content) > MAX_FILE_BYTES:
                raise HTTPException(413, "File too large")
        finally:
            os.close(fd)

        try:
            decoded = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(415, "UTF-8 text only") from exc

        return {"filename": filename, "content": decoded}


@app.delete("/sandboxes/{sandbox_id}/files/{filename}")
def delete_file(sandbox_id: UUID, filename: str):
    validate_filename(filename)

    with EXECUTION_LOCK:
        workspace = get_active_workspace(str(sandbox_id))
        target = workspace / filename

        if not safe_regular_file(target):
            raise HTTPException(404, "File not found")

        target.unlink()

        return {"filename": filename, "status": "deleted"}


@app.post("/maintenance/cleanup")
def manual_cleanup():
    expired = expire_sandboxes()
    return {"status": "completed", "expired_count": expired}
