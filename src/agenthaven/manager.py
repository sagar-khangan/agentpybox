"""Class-based public API; no network server required."""
import hashlib
import os
import re
import shutil
import stat
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from .models import ExecutionResult
from .runner import MAX_OUTPUT, PROFILES, execute
from .store import Store, utcnow

DEFAULT_ROOT = Path.home() / ".local" / "share" / "agenthaven"
MAX_ARTIFACT = 10 * 1024 * 1024
MAX_FILES = 100
FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")


class SandboxError(RuntimeError):
    pass


def _sid(value: str) -> str:
    try:
        return str(UUID(str(value)))
    except ValueError as exc:
        raise SandboxError("Invalid sandbox ID") from exc


def _filename(value: str) -> str:
    if not FILENAME.fullmatch(value) or value.startswith("agenthaven_"):
        raise SandboxError("Only flat, non-reserved filenames are allowed")
    return value


class SandboxManager:
    """Manage multiple persistent sessions; serializes operations across processes."""

    def __init__(self, root: str | Path | None = None):
        self.store = Store(Path(root) if root is not None else DEFAULT_ROOT)
        self.cleanup()

    def _record(self, db, sid: str) -> dict:
        row = db.execute("SELECT * FROM sandboxes WHERE id=?", (sid,)).fetchone()
        if row is None:
            raise SandboxError("Sandbox not found")
        return dict(row)

    def _workspace(self, sid: str) -> Path:
        return self.store.root / "workspaces" / sid

    def _terminate_locked(self, db, sid: str, status: str) -> dict:
        record = self._record(db, sid)
        if record["status"] != "created":
            return record
        path = self._workspace(sid)
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise SandboxError("Unexpected workspace type; cleanup refused")
        if path.exists():
            shutil.rmtree(path)
        db.execute("UPDATE sandboxes SET status=?, ended_at=? WHERE id=?",
                   (status, utcnow(), sid))
        return self._record(db, sid)

    def _active(self, db, sid: str) -> Path:
        record = self._record(db, sid)
        if record["status"] != "created":
            raise SandboxError(f"Sandbox is {record['status']}")
        if record["expires_at"] <= utcnow():
            self._terminate_locked(db, sid, "expired")
            raise SandboxError("Sandbox expired")
        path = self._workspace(sid)
        if path.is_symlink() or not path.is_dir():
            raise SandboxError("Workspace missing or invalid")
        return path

    def create(self, profile: str = "python-basic", ttl_seconds: int = 300) -> "Sandbox":
        if profile not in PROFILES:
            raise SandboxError(f"Unknown profile: {profile}; choose {', '.join(PROFILES)}")
        if not 10 <= ttl_seconds <= 3600:
            raise SandboxError("TTL must be 10..3600 seconds")
        sid = str(uuid4())
        with self.store.locked(), self.store.connect() as db:
            path = self._workspace(sid)
            path.mkdir(mode=0o700)
            try:
                db.execute("INSERT INTO sandboxes VALUES (?, ?, ?, ?, ?, NULL)",
                           (sid, profile, "created", utcnow(),
                            (datetime.now(UTC) + timedelta(seconds=ttl_seconds)).isoformat()))
            except BaseException:
                shutil.rmtree(path)
                raise
        return Sandbox(self, sid)

    def get(self, sandbox_id: str) -> "Sandbox":
        sid = _sid(sandbox_id)
        with self.store.locked(), self.store.connect() as db:
            self._record(db, sid)
        return Sandbox(self, sid)

    def list(self, status: str | None = None) -> list[dict]:
        with self.store.locked(), self.store.connect() as db:
            if status:
                rows = db.execute("SELECT * FROM sandboxes WHERE status=? ORDER BY created_at DESC", (status,))
            else:
                rows = db.execute("SELECT * FROM sandboxes ORDER BY created_at DESC")
            return [dict(row) for row in rows]

    def cleanup(self) -> int:
        count = 0
        with self.store.locked(), self.store.connect() as db:
            rows = db.execute("SELECT id FROM sandboxes WHERE status='created' AND expires_at<=?",
                              (utcnow(),)).fetchall()
            for row in rows:
                self._terminate_locked(db, row["id"], "expired")
                count += 1
        return count

    def metrics(self, hours: int = 24) -> dict:
        if not 1 <= hours <= 720:
            raise SandboxError("hours must be 1..720")
        cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        with self.store.locked(), self.store.connect() as db:
            rows = db.execute("SELECT * FROM executions WHERE executed_at>=?", (cutoff,)).fetchall()
            statuses = db.execute("SELECT status, COUNT(*) n FROM sandboxes GROUP BY status").fetchall()
        times = sorted(float(row["duration_ms"]) for row in rows)

        def pct(p):
            if not times:
                return 0.0
            pos = (len(times) - 1) * p / 100
            lo = int(pos)
            return round(times[lo] + (times[min(lo + 1, len(times) - 1)] - times[lo]) * (pos - lo), 2)

        success = sum(r["exit_code"] == 0 and not r["timed_out"] for r in rows)
        timeouts = sum(bool(r["timed_out"]) for r in rows)
        return {
            "window_hours": hours, "executions": len(rows),
            "success": success, "failure": len(rows) - success - timeouts,
            "timeouts": timeouts,
            "success_rate_pct": round(100 * success / len(rows), 2) if rows else 0.0,
            "truncated": sum(bool(r["truncated"]) for r in rows),
            "duration_ms": {"p50": pct(50), "p95": pct(95), "p99": pct(99)},
            "sandboxes_all_time": {r["status"]: r["n"] for r in statuses},
        }

    @contextmanager
    def sandbox(self, profile: str = "python-basic", ttl_seconds: int = 300):
        box = self.create(profile=profile, ttl_seconds=ttl_seconds)
        try:
            yield box
        finally:
            box.terminate()


class Sandbox:
    def __init__(self, manager: SandboxManager, sandbox_id: str):
        self.manager = manager
        self.id = _sid(sandbox_id)

    @property
    def info(self) -> dict:
        with self.manager.store.locked(), self.manager.store.connect() as db:
            return self.manager._record(db, self.id)

    def execute(self, code: str) -> ExecutionResult:
        with self.manager.store.locked(), self.manager.store.connect() as db:
            workspace = self.manager._active(db, self.id)
            profile = self.manager._record(db, self.id)["profile"]
            result = execute(workspace, code, profile)
            execution_id = str(uuid4())
            executed_at = utcnow()
            digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
            db.execute("""INSERT INTO executions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                       (execution_id, self.id, profile, executed_at, digest,
                        result["exit_code"], result["duration_ms"],
                        int(result["timed_out"]), int(result["truncated"])))
            return ExecutionResult(execution_id, self.id, profile,
                                   result["exit_code"], result["stdout"], result["stderr"],
                                   result["duration_ms"], result["timed_out"],
                                   result["truncated"], executed_at, digest)

    def terminate(self) -> dict:
        with self.manager.store.locked(), self.manager.store.connect() as db:
            return self.manager._terminate_locked(db, self.id, "terminated")

    def history(self, limit: int = 100) -> list[dict]:
        if not 1 <= limit <= 1000:
            raise SandboxError("limit must be 1..1000")
        with self.manager.store.locked(), self.manager.store.connect() as db:
            self.manager._record(db, self.id)
            return [dict(r) for r in db.execute(
                "SELECT * FROM executions WHERE sandbox_id=? ORDER BY executed_at DESC LIMIT ?",
                (self.id, limit))]

    @contextmanager
    def _directory_fd(self):
        with self.manager.store.locked(), self.manager.store.connect() as db:
            path = self.manager._active(db, self.id)
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                yield fd
            finally:
                os.close(fd)

    def files(self) -> list[dict]:
        with self._directory_fd() as fd:
            entries = []
            for name in os.listdir(fd):
                try:
                    _filename(name)
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if stat.S_ISREG(info.st_mode):
                        entries.append({"name": name, "bytes": info.st_size})
                except (SandboxError, FileNotFoundError):
                    continue
            return sorted(entries, key=lambda e: e["name"])

    def put_bytes(self, name: str, content: bytes) -> None:
        name = _filename(name)
        if len(content) > MAX_ARTIFACT:
            raise SandboxError("Single artifact exceeds 10 MiB")
        with self._directory_fd() as fd:
            entries = os.listdir(fd)
            if name not in entries and len(entries) >= MAX_FILES:
                raise SandboxError("Workspace file-count limit exceeded")
            temp = f".upload_{uuid4().hex}"
            file_fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                              0o600, dir_fd=fd)
            try:
                with os.fdopen(file_fd, "wb") as file:
                    file.write(content)
                os.replace(temp, name, src_dir_fd=fd, dst_dir_fd=fd)
            finally:
                try:
                    os.unlink(temp, dir_fd=fd)
                except FileNotFoundError:
                    pass

    def get_bytes(self, name: str) -> bytes:
        name = _filename(name)
        with self._directory_fd() as fd:
            file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            try:
                info = os.fstat(file_fd)
                if not stat.S_ISREG(info.st_mode):
                    raise SandboxError("Not a regular file")
                if info.st_size > MAX_ARTIFACT:
                    raise SandboxError("Artifact exceeds 10 MiB")
                with os.fdopen(file_fd, "rb", closefd=False) as file:
                    data = file.read(MAX_ARTIFACT + 1)
                if len(data) > MAX_ARTIFACT:
                    raise SandboxError("Artifact exceeds 10 MiB")
                return data
            finally:
                os.close(file_fd)

    def delete_file(self, name: str) -> None:
        name = _filename(name)
        with self._directory_fd() as fd:
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                raise SandboxError("Not a regular file")
            os.unlink(name, dir_fd=fd)

    def upload(self, source: str | Path, name: str | None = None) -> None:
        source = Path(source)
        if source.stat().st_size > MAX_ARTIFACT:
            raise SandboxError("Artifact exceeds 10 MiB")
        self.put_bytes(name or source.name, source.read_bytes())

    def download(self, name: str, target: str | Path) -> None:
        dest = Path(target)
        if dest.is_symlink():
            raise SandboxError("Destination symlink refused")
        dest.write_bytes(self.get_bytes(name))

    def put_text(self, name: str, content: str) -> None:
        self.put_bytes(name, content.encode("utf-8"))

    def get_text(self, name: str) -> str:
        return self.get_bytes(name).decode("utf-8")
