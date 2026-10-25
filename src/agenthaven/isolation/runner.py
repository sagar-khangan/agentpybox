"""Linux Bubblewrap Python executor."""

import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from .environments import EnvironmentRegistry


class RunnerUnavailable(RuntimeError):
    pass


PROFILES = {
    "python-basic": {
        "timeout": 5,
        "memory_mb": 512,
        "description": "Python standard-library scripts",
    },
    "python-data": {
        "timeout": 10,
        "memory_mb": 512,
        "description": "Legacy standard-library data profile",
    },
    "python-test": {
        "timeout": 10,
        "memory_mb": 512,
        "description": "Legacy standard-library test profile",
    },
}

MAX_SOURCE = 64 * 1024
MAX_OUTPUT = 64 * 1024


def available() -> bool:
    return (
        all(shutil.which(x) for x in ("bwrap", "prlimit"))
        and Path("/usr/bin/python3").exists()
    )


def execute(
    workspace: Path,
    code: str,
    profile: str,
    root: Path | None = None,
) -> dict:
    if profile not in PROFILES and root is None:
        raise ValueError("Registry root required")

    if not available():
        raise RunnerUnavailable("Install bubblewrap and util-linux")

    if len(code.encode("utf-8")) > MAX_SOURCE:
        raise ValueError("Source exceeds 64 KiB")

    if workspace.is_symlink() or not workspace.is_dir():
        raise RunnerUnavailable("Invalid workspace")

    spec = PROFILES.get(
        profile,
        {"timeout": 10, "memory_mb": 1024},
    )

    env = EnvironmentRegistry(root).mount(profile) if root is not None else None

    script = workspace / f"agenthaven_{uuid4().hex}.py"

    fd = os.open(
        script,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(code)
    except BaseException:
        script.unlink(missing_ok=True)
        raise

    memory = spec["memory_mb"] * 1024 * 1024

    # A larger CPU allowance for dependency-heavy environments.
    cpu_limit = "--cpu=10:11" if env is not None else "--cpu=3:4"

    cmd = [
        "prlimit",
        cpu_limit,
        f"--as={memory}:{memory}",
        "--fsize=1048576:1048576",
        "--nofile=64:64",
        "--core=0:0",
        "--",
        "bwrap",
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--clearenv",
        "--setenv",
        "PATH",
        "/usr/bin:/bin",
        "--setenv",
        "HOME",
        "/work",
        "--setenv",
        "PYTHONDONTWRITEBYTECODE",
        "1",
        "--setenv",
        "PYTHONNOUSERSITE",
        "1",
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind-try",
        "/bin",
        "/bin",
        "--ro-bind-try",
        "/lib",
        "/lib",
        "--ro-bind-try",
        "/lib64",
        "/lib64",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--dir",
        "/work",
        "--bind",
        str(workspace),
        "/work",
        "--chdir",
        "/work",
        "--",
        "/usr/bin/python3",
        "-I",
        f"/work/{script.name}",
    ]

    if env is not None:
        # Mount the prepared environment read-only.
        # Keep pyvenv.cfg and site-packages together.
        pos = cmd.index("--proc")

        cmd[pos:pos] = [
            "--dir",
            "/env",
            "--ro-bind",
            str(env),
            "/env/venv",
        ]

        cmd[-2] = "/env/venv/bin/python"

    started = time.monotonic()
    timed_out = False

    try:
        with (
            tempfile.TemporaryFile() as stdout_file,
            tempfile.TemporaryFile() as stderr_file,
        ):
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                start_new_session=True,
                close_fds=True,
            )

            try:
                process.wait(timeout=spec["timeout"])

            except subprocess.TimeoutExpired:
                timed_out = True

                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

                process.wait()

            stdout_file.seek(0)
            stderr_file.seek(0)

            stdout_raw = stdout_file.read(MAX_OUTPUT + 1)
            stderr_raw = stderr_file.read(MAX_OUTPUT + 1)

            return {
                "exit_code": process.returncode,
                "stdout": stdout_raw[:MAX_OUTPUT].decode("utf-8", errors="replace"),
                "stderr": stderr_raw[:MAX_OUTPUT].decode("utf-8", errors="replace"),
                "duration_ms": round(
                    (time.monotonic() - started) * 1000,
                    2,
                ),
                "timed_out": timed_out,
                "truncated": (
                    len(stdout_raw) > MAX_OUTPUT or len(stderr_raw) > MAX_OUTPUT
                ),
            }

    finally:
        script.unlink(missing_ok=True)
