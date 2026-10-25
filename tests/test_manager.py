from datetime import UTC, datetime, timedelta

import pytest

from agentpybox import SandboxError, SandboxManager
from agentpybox import manager as manager_module


def test_multiple_sessions_and_files(tmp_path, monkeypatch):
    m = SandboxManager(tmp_path)
    a = m.create(ttl_seconds=20)
    b = m.create("python-data", ttl_seconds=20)
    assert a.id != b.id
    a.put_text("test.txt", "first")
    b.put_bytes("test.bin", b"\x00\xff\x01")
    assert a.get_text("test.txt") == "first"
    assert b.get_bytes("test.bin") == b"\x00\xff\x01"
    assert len(a.files()) == 1
    assert len(m.list("created")) == 2
    assert a.terminate()["status"] == "terminated"
    with pytest.raises(SandboxError):
        a.put_text("later.txt", "no")
    assert b.info["status"] == "created"
    b.terminate()


def test_execution_history_and_metrics(tmp_path, monkeypatch):
    m = SandboxManager(tmp_path)
    a = m.create()

    def fake_execute(workspace, code, profile):
        assert workspace.exists()
        return {
            "exit_code": 0,
            "stdout": "42\n",
            "stderr": "",
            "duration_ms": 12.5,
            "timed_out": False,
            "truncated": False,
        }

    monkeypatch.setattr(manager_module, "execute", fake_execute)
    result = a.execute("print(42)")
    assert result.ok
    assert result.source_sha256
    assert a.history()[0]["id"] == result.id
    metrics = m.metrics()
    assert metrics["executions"] == 1
    assert metrics["success_rate_pct"] == 100
    a.terminate()
    assert len(a.history()) == 1


def test_ttl_and_validation(tmp_path):
    m = SandboxManager(tmp_path)
    with pytest.raises(SandboxError):
        m.create(ttl_seconds=1)
    with pytest.raises(SandboxError):
        m.create("unknown-profile")
    a = m.create()
    with m.store.locked(), m.store.connect() as db:
        db.execute(
            "UPDATE sandboxes SET expires_at=? WHERE id=?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), a.id),
        )
    assert m.cleanup() == 1
    assert a.info["status"] == "expired"
    with pytest.raises(SandboxError):
        a.get_bytes("thing.txt")


def test_reject_invalid_filename_and_symlink(tmp_path):
    m = SandboxManager(tmp_path)
    a = m.create()
    with pytest.raises(SandboxError):
        a.put_text("../oops", "bad")
    a.put_text("a.txt", "ok")
    path = tmp_path / "workspaces" / a.id / "linked.txt"
    path.symlink_to(tmp_path / "external.txt")
    with pytest.raises(OSError):
        a.get_bytes("linked.txt")
    a.terminate()


def test_context_cleanup(tmp_path):
    m = SandboxManager(tmp_path)
    with m.sandbox() as s:
        sid = s.id
    assert m.get(sid).info["status"] == "terminated"
