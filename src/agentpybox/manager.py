"""Class-based AgentPyBox SDK. No HTTP server."""

import hashlib
import os
import re
import shutil
import stat
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from .environments import EnvironmentRegistry
from .models import ExecutionResult
from .runner import PROFILES, execute
from .store import Store, utcnow

DEFAULT_ROOT = Path.home() / ".local" / "share" / "agentpybox"

MAX_ARTIFACT = 10 * 1024 * 1024
MAX_FILES = 100

FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")


class SandboxError(RuntimeError):
    pass


def _sid(value):
    try:
        return str(UUID(str(value)))
    except ValueError as exc:
        raise SandboxError("Invalid sandbox ID") from exc


def _filename(value):
    if not FILENAME.fullmatch(value) or value.startswith("agentpybox_"):
        raise SandboxError("Only flat, non-reserved filenames allowed")
    return value


class SandboxManager:
    def __init__(self, root=None):
        self.store = Store(Path(root) if root is not None else DEFAULT_ROOT)
        self.environments = EnvironmentRegistry(self.store.root)
        self.cleanup()

    def create_environment(
        self,
        name,
        requirements,
        python="/usr/bin/python3",
    ):
        with self.store.locked():
            return self.environments.create(name, requirements, python)

    def delete_environment(self, name):
        with self.store.locked(), self.store.connect() as db:
            rows = db.execute(
                """
                SELECT DISTINCT profile
                FROM sandboxes
                WHERE status = 'created'
                """
            ).fetchall()

            active_names = {row[0] for row in rows}

            self.environments.delete(
                name,
                active_names=active_names,
            )

    def _record(self, db, sid):
        row = db.execute(
            "SELECT * FROM sandboxes WHERE id=?",
            (sid,),
        ).fetchone()

        if row is None:
            raise SandboxError("Sandbox not found")

        return dict(row)

    def _workspace(self, sid):
        return self.store.root / "workspaces" / sid

    def _terminate_locked(self, db, sid, status):
        record = self._record(db, sid)

        if record["status"] != "created":
            return record

        path = self._workspace(sid)

        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise SandboxError("Unexpected workspace type; cleanup refused")

        if path.exists():
            shutil.rmtree(path)

        db.execute(
            """
            UPDATE sandboxes
            SET status=?, ended_at=?
            WHERE id=?
            """,
            (status, utcnow(), sid),
        )

        return self._record(db, sid)

    def _active(self, db, sid):
        record = self._record(db, sid)

        if record["status"] != "created":
            raise SandboxError(f"Sandbox is {record['status']}")

        if record["expires_at"] <= utcnow():
            self._terminate_locked(db, sid, "expired")
            raise SandboxError("Sandbox expired")

        workspace = self._workspace(sid)

        if workspace.is_symlink() or not workspace.is_dir():
            raise SandboxError("Workspace missing or invalid")

        return workspace

    def create(
        self,
        profile="python-basic",
        ttl_seconds=300,
    ):
        try:
            self.environments.inspect(profile)
        except ValueError as exc:
            raise SandboxError(str(exc)) from exc

        if not 10 <= ttl_seconds <= 3600:
            raise SandboxError("TTL must be 10..3600 seconds")

        sid = str(uuid4())

        with self.store.locked(), self.store.connect() as db:
            workspace = self._workspace(sid)
            workspace.mkdir(mode=0o700)

            expires = (datetime.now(UTC) + timedelta(seconds=ttl_seconds)).isoformat()

            try:
                db.execute(
                    """
                    INSERT INTO sandboxes
                    VALUES (?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        sid,
                        profile,
                        "created",
                        utcnow(),
                        expires,
                    ),
                )

            except BaseException:
                shutil.rmtree(workspace)
                raise

        return Sandbox(self, sid)

    def get(self, sandbox_id):
        sid = _sid(sandbox_id)

        with self.store.locked(), self.store.connect() as db:
            self._record(db, sid)

        return Sandbox(self, sid)

    def list(self, status=None):
        with self.store.locked(), self.store.connect() as db:
            if status:
                rows = db.execute(
                    """
                    SELECT * FROM sandboxes
                    WHERE status=?
                    ORDER BY created_at DESC
                    """,
                    (status,),
                )
            else:
                rows = db.execute(
                    """
                    SELECT * FROM sandboxes
                    ORDER BY created_at DESC
                    """
                )

            return [dict(row) for row in rows]

    def cleanup(self):
        count = 0

        with self.store.locked(), self.store.connect() as db:
            rows = db.execute(
                """
                SELECT id FROM sandboxes
                WHERE status='created'
                AND expires_at<=?
                """,
                (utcnow(),),
            ).fetchall()

            for row in rows:
                self._terminate_locked(db, row["id"], "expired")
                count += 1

        return count

    def metrics(self, hours=24):
        if not 1 <= hours <= 720:
            raise SandboxError("hours must be 1..720")

        cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()

        with self.store.locked(), self.store.connect() as db:
            executions = db.execute(
                """
                SELECT * FROM executions
                WHERE executed_at>=?
                """,
                (cutoff,),
            ).fetchall()

            statuses = db.execute(
                """
                SELECT status, COUNT(*) AS n
                FROM sandboxes
                GROUP BY status
                """
            ).fetchall()

        times = sorted(float(row["duration_ms"]) for row in executions)

        def percentile(percent):
            if not times:
                return 0.0

            pos = (len(times) - 1) * percent / 100
            lower = int(pos)
            upper = min(lower + 1, len(times) - 1)

            value = times[lower] + (times[upper] - times[lower]) * (pos - lower)

            return round(value, 2)

        success = sum(
            row["exit_code"] == 0 and not row["timed_out"] for row in executions
        )

        timeouts = sum(bool(row["timed_out"]) for row in executions)

        total = len(executions)

        return {
            "window_hours": hours,
            "executions": total,
            "success": success,
            "failure": total - success - timeouts,
            "timeouts": timeouts,
            "success_rate_pct": (round(100 * success / total, 2) if total else 0.0),
            "truncated": sum(bool(row["truncated"]) for row in executions),
            "duration_ms": {
                "p50": percentile(50),
                "p95": percentile(95),
                "p99": percentile(99),
            },
            "sandboxes_all_time": {row["status"]: row["n"] for row in statuses},
        }

    @contextmanager
    def sandbox(
        self,
        profile="python-basic",
        ttl_seconds=300,
    ):
        box = self.create(
            profile=profile,
            ttl_seconds=ttl_seconds,
        )
        try:
            yield box
        finally:
            box.terminate()


class Sandbox:
    def __init__(self, manager, sandbox_id):
        self.manager = manager
        self.id = _sid(sandbox_id)

    @property
    def info(self):
        with (
            self.manager.store.locked(),
            self.manager.store.connect() as db,
        ):
            return self.manager._record(db, self.id)

    def execute(self, code):
        with (
            self.manager.store.locked(),
            self.manager.store.connect() as db,
        ):
            workspace = self.manager._active(db, self.id)
            profile = self.manager._record(db, self.id)["profile"]

            if profile in PROFILES:
                result = execute(workspace, code, profile)
            else:
                result = execute(
                    workspace,
                    code,
                    profile,
                    root=self.manager.store.root,
                )

            execution_id = str(uuid4())
            executed_at = utcnow()

            digest = hashlib.sha256(code.encode("utf-8")).hexdigest()

            db.execute(
                """
                INSERT INTO executions
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    execution_id,
                    self.id,
                    profile,
                    executed_at,
                    digest,
                    result["exit_code"],
                    result["duration_ms"],
                    int(result["timed_out"]),
                    int(result["truncated"]),
                ),
            )

            return ExecutionResult(
                execution_id,
                self.id,
                profile,
                result["exit_code"],
                result["stdout"],
                result["stderr"],
                result["duration_ms"],
                result["timed_out"],
                result["truncated"],
                executed_at,
                digest,
            )

    def terminate(self):
        with (
            self.manager.store.locked(),
            self.manager.store.connect() as db,
        ):
            return self.manager._terminate_locked(db, self.id, "terminated")

    def history(self, limit=100):
        if not 1 <= limit <= 1000:
            raise SandboxError("limit must be 1..1000")

        with (
            self.manager.store.locked(),
            self.manager.store.connect() as db,
        ):
            self.manager._record(db, self.id)

            return [
                dict(row)
                for row in db.execute(
                    """
                    SELECT * FROM executions
                    WHERE sandbox_id=?
                    ORDER BY executed_at DESC
                    LIMIT ?
                    """,
                    (self.id, limit),
                )
            ]

    @contextmanager
    def _directory_fd(self):
        with (
            self.manager.store.locked(),
            self.manager.store.connect() as db,
        ):
            path = self.manager._active(db, self.id)

            fd = os.open(
                path,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            )

            try:
                yield fd
            finally:
                os.close(fd)

    def files(self):
        with self._directory_fd() as fd:
            entries = []

            for name in os.listdir(fd):
                try:
                    _filename(name)

                    info = os.stat(
                        name,
                        dir_fd=fd,
                        follow_symlinks=False,
                    )

                    if stat.S_ISREG(info.st_mode):
                        entries.append(
                            {
                                "name": name,
                                "bytes": info.st_size,
                            }
                        )

                except (
                    SandboxError,
                    FileNotFoundError,
                ):
                    continue

            return sorted(
                entries,
                key=lambda entry: entry["name"],
            )

    def put_bytes(self, name, content):
        name = _filename(name)

        if len(content) > MAX_ARTIFACT:
            raise SandboxError("Single artifact exceeds 10 MiB")

        with self._directory_fd() as fd:
            entries = os.listdir(fd)

            if name not in entries and len(entries) >= MAX_FILES:
                raise SandboxError("Workspace file-count limit exceeded")

            temp = f".upload_{uuid4().hex}"

            file_fd = os.open(
                temp,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                0o600,
                dir_fd=fd,
            )

            try:
                with os.fdopen(file_fd, "wb") as file:
                    file.write(content)

                os.replace(
                    temp,
                    name,
                    src_dir_fd=fd,
                    dst_dir_fd=fd,
                )

            finally:
                try:
                    os.unlink(temp, dir_fd=fd)
                except FileNotFoundError:
                    pass

    def get_bytes(self, name):
        name = _filename(name)

        with self._directory_fd() as fd:
            file_fd = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=fd,
            )

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

    def delete_file(self, name):
        name = _filename(name)

        with self._directory_fd() as fd:
            info = os.stat(
                name,
                dir_fd=fd,
                follow_symlinks=False,
            )

            if not stat.S_ISREG(info.st_mode):
                raise SandboxError("Not a regular file")

            os.unlink(name, dir_fd=fd)

    def upload(self, source, name=None):
        source = Path(source)

        if source.stat().st_size > MAX_ARTIFACT:
            raise SandboxError("Artifact exceeds 10 MiB")

        self.put_bytes(
            name or source.name,
            source.read_bytes(),
        )

    def download(self, name, target):
        target = Path(target)

        if target.is_symlink():
            raise SandboxError("Destination symlink refused")

        target.write_bytes(self.get_bytes(name))

    def put_text(self, name, content):
        self.put_bytes(
            name,
            content.encode("utf-8"),
        )

    def get_text(self, name):
        return self.get_bytes(name).decode("utf-8")
