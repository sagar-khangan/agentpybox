import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

MAX_SOURCE_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 64 * 1024
TIMEOUT_SECONDS = 5


class SandboxError(Exception):
    pass


def execute_python(workspace: Path, code: str) -> dict:
    """Execute controlled Python code inside a Bubblewrap sandbox."""

    if len(code.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError("Maximum source size is 64 KB")

    if not shutil.which("bwrap"):
        raise SandboxError("Bubblewrap is not installed")

    if not shutil.which("prlimit"):
        raise SandboxError("prlimit is not installed")

    # The caller must supply a trusted AgentHaven-created workspace.
    if workspace.is_symlink() or not workspace.is_dir():
        raise SandboxError("Invalid workspace")

    script_name = f"agenthaven_{uuid4().hex}.py"
    script = workspace / script_name

    # Exclusive creation prevents replacing an existing file.
    with script.open("x", encoding="utf-8") as file:
        file.write(code)

    command = [
        "prlimit",
        "--cpu=3:4",
        "--as=536870912:536870912",
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
        f"/work/{script_name}",
    ]

    started = time.monotonic()
    timed_out = False

    try:
        # Temporary output files prevent unbounded pipe buffering.
        with (
            tempfile.TemporaryFile() as stdout_file,
            tempfile.TemporaryFile() as stderr_file,
        ):
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                start_new_session=True,
                close_fds=True,
            )

            try:
                process.wait(timeout=TIMEOUT_SECONDS)
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
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
                "timed_out": timed_out,
                "truncated": (
                    len(stdout_raw) > MAX_OUTPUT_BYTES
                    or len(stderr_raw) > MAX_OUTPUT_BYTES
                ),
            }

    finally:
        script.unlink(missing_ok=True)
