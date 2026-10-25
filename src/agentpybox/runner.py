"""AgentPyBox Bubblewrap execution engine.

Supports:
- Built-in Python profiles
- Registered Python virtual environments
- Read-only dependency environments
- Persistent per-sandbox workspaces
- Execution timeouts and output capture

Linux only. Intended for controlled local development.
Not hardened for arbitrary hostile code.
"""

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
    """Sandbox execution prerequisites are unavailable."""


PROFILES = {
    "python-basic": {
        "timeout": 5,
        "memory_mb": 512,
        "cpu_seconds": 3,
        "description": "Standard-library Python",
    },
    "python-data": {
        "timeout": 10,
        "memory_mb": 512,
        "cpu_seconds": 5,
        "description": "Standard-library data processing",
    },
    "python-test": {
        "timeout": 10,
        "memory_mb": 512,
        "cpu_seconds": 5,
        "description": "Standard-library test execution",
    },
}

DEFAULT_REGISTERED_POLICY = {
    "timeout": 10,
    "memory_mb": 1024,
    "cpu_seconds": 10,
}

MAX_SOURCE_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 64 * 1024

SYSTEM_PYTHON = Path("/usr/bin/python3")


def available() -> bool:
    """Check basic Linux runtime prerequisites."""
    return (
        os.name == "posix"
        and shutil.which("bwrap") is not None
        and shutil.which("prlimit") is not None
        and SYSTEM_PYTHON.is_file()
    )


def _runtime_for(profile: str, root: Path | None):
    """Resolve runtime policy and optional registered venv."""
    if profile in PROFILES:
        return PROFILES[profile], None

    if root is None:
        raise ValueError("Registry root is required for registered environments")

    registry = EnvironmentRegistry(root)
    env_path = registry.mount(profile)

    if env_path is None:
        raise ValueError(f"Registered environment has no virtualenv: {profile}")

    env_path = Path(env_path).resolve()

    if not (env_path / "pyvenv.cfg").is_file():
        raise RunnerUnavailable(f"Invalid virtual environment: {profile}")

    return DEFAULT_REGISTERED_POLICY, env_path


def _command(
    workspace: Path,
    script_name: str,
    policy: dict,
    env_path: Path | None,
):
    """Build the Bubblewrap command."""
    memory_bytes = policy["memory_mb"] * 1024 * 1024
    cpu_seconds = policy["cpu_seconds"]

    interpreter = "/usr/bin/python3"

    mounts = [
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
    ]

    if env_path is not None:
        # Mount the venv at a consistent location.
        mounts.extend(
            [
                "--dir",
                "/env",
                "--ro-bind",
                str(env_path),
                "/env/venv",
            ]
        )

        interpreter = "/env/venv/bin/python"

    return [
        "prlimit",
        f"--cpu={cpu_seconds}:{cpu_seconds + 1}",
        f"--as={memory_bytes}:{memory_bytes}",
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
        *mounts,
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
        interpreter,
        "-I",
        f"/work/{script_name}",
    ]


def execute(
    workspace: Path,
    code: str,
    profile: str,
    root: Path | None = None,
) -> dict:
    """Execute Python inside an isolated Bubblewrap workspace.

    Returns:
        exit_code, stdout, stderr, duration_ms,
        timed_out, truncated
    """
    if not available():
        raise RunnerUnavailable("Bubblewrap, prlimit or /usr/bin/python3 unavailable")

    if not isinstance(code, str):
        raise TypeError("Code must be a string")

    if len(code.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError("Source exceeds 64 KiB")

    workspace = Path(workspace).absolute()

    if workspace.is_symlink() or not workspace.is_dir():
        raise RunnerUnavailable("Invalid sandbox workspace")

    policy, env_path = _runtime_for(profile, root)

    script_name = f"agentpybox_{uuid4().hex}.py"
    script = workspace / script_name

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

    command = _command(
        workspace,
        script_name,
        policy,
        env_path,
    )

    started = time.monotonic()
    timed_out = False

    try:
        with (
            tempfile.TemporaryFile() as stdout_file,
            tempfile.TemporaryFile() as stderr_file,
        ):
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    start_new_session=True,
                    close_fds=True,
                )
            except OSError as exc:
                raise RunnerUnavailable(f"Could not launch sandbox: {exc}") from exc

            try:
                process.wait(timeout=policy["timeout"])

            except subprocess.TimeoutExpired:
                timed_out = True

                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

                process.wait()

            stdout_file.seek(0)
            stderr_file.seek(0)

            stdout_raw = stdout_file.read(MAX_OUTPUT_BYTES + 1)
            stderr_raw = stderr_file.read(MAX_OUTPUT_BYTES + 1)

            return {
                "exit_code": process.returncode,
                "stdout": stdout_raw[:MAX_OUTPUT_BYTES].decode(
                    "utf-8", errors="replace"
                ),
                "stderr": stderr_raw[:MAX_OUTPUT_BYTES].decode(
                    "utf-8", errors="replace"
                ),
                "duration_ms": round(
                    (time.monotonic() - started) * 1000,
                    2,
                ),
                "timed_out": timed_out,
                "truncated": (
                    len(stdout_raw) > MAX_OUTPUT_BYTES
                    or len(stderr_raw) > MAX_OUTPUT_BYTES
                ),
            }

    finally:
        script.unlink(missing_ok=True)
