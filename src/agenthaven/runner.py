"""Bubblewrap Python executor. Linux only; not a hostile-code security guarantee."""
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4


class RunnerUnavailable(RuntimeError):
    pass


PROFILES = {
    # This is the *system* Python, not the uv virtualenv.
    "python-basic": {"timeout": 5, "memory_mb": 512, "description": "stdlib scripts"},
    "python-data": {"timeout": 10, "memory_mb": 512, "description": "stdlib csv, json, sqlite, statistics"},
    "python-test": {"timeout": 10, "memory_mb": 512, "description": "stdlib unittest/assert tests"},
}
MAX_SOURCE = 64 * 1024
MAX_OUTPUT = 64 * 1024


def available() -> bool:
    return all(shutil.which(x) for x in ("bwrap", "prlimit")) and Path("/usr/bin/python3").exists()


def execute(workspace: Path, code: str, profile: str) -> dict:
    if profile not in PROFILES:
        raise ValueError(f"Unknown profile: {profile}")
    if not available():
        raise RunnerUnavailable("Install bubblewrap and util-linux (prlimit) on Linux")
    if len(code.encode("utf-8")) > MAX_SOURCE:
        raise ValueError("Source exceeds 64 KiB")
    if workspace.is_symlink() or not workspace.is_dir():
        raise RunnerUnavailable("Invalid workspace")

    spec = PROFILES[profile]
    script = workspace / f"agenthaven_{uuid4().hex}.py"
    # Explicit exclusive creation; no caller-provided filenames.
    fd = os.open(script, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(code)
    except BaseException:
        script.unlink(missing_ok=True)
        raise

    cmd = [
        "prlimit", "--cpu=3:4",
        f"--as={spec['memory_mb'] * 1024 * 1024}:{spec['memory_mb'] * 1024 * 1024}",
        "--fsize=1048576:1048576", "--nofile=64:64", "--core=0:0", "--",
        "bwrap", "--unshare-all", "--die-with-parent", "--new-session",
        "--clearenv", "--setenv", "PATH", "/usr/bin:/bin",
        "--setenv", "HOME", "/work", "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        "--setenv", "PYTHONNOUSERSITE", "1",
        "--ro-bind", "/usr", "/usr", "--ro-bind-try", "/bin", "/bin",
        "--ro-bind-try", "/lib", "/lib", "--ro-bind-try", "/lib64", "/lib64",
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--dir", "/work", "--bind", str(workspace), "/work", "--chdir", "/work",
        "--", "/usr/bin/python3", "-I", f"/work/{script.name}",
    ]
    started = time.monotonic()
    timed_out = False
    try:
        # Temporary files prevent an unbounded *memory* buffer. fsize constrains
        # individual output files, but is not a total disk quota.
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out,
                                    stderr=err, start_new_session=True, close_fds=True)
            try:
                proc.wait(timeout=spec["timeout"])
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
            out.seek(0)
            err.seek(0)
            stdout = out.read(MAX_OUTPUT + 1)
            stderr = err.read(MAX_OUTPUT + 1)
            return {
                "exit_code": proc.returncode,
                "stdout": stdout[:MAX_OUTPUT].decode("utf-8", errors="replace"),
                "stderr": stderr[:MAX_OUTPUT].decode("utf-8", errors="replace"),
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
                "timed_out": timed_out,
                "truncated": len(stdout) > MAX_OUTPUT or len(stderr) > MAX_OUTPUT,
            }
    finally:
        script.unlink(missing_ok=True)
