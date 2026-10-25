"""Basic isolation probes. Passing does NOT establish hostile-code safety."""

import pytest

from agentpybox import SandboxManager
from agentpybox.runner import available


@pytest.fixture
def box(tmp_path):
    if not available():
        pytest.skip("Bubblewrap and prlimit unavailable")
    manager = SandboxManager(tmp_path)
    with manager.sandbox(profile="python-basic") as sandbox:
        probe = sandbox.execute("print('ready')")
        if "Operation not permitted" in probe.stderr:
            pytest.skip("User namespaces blocked by the host")
        assert probe.ok, probe.stderr
        yield sandbox


def test_host_home_is_not_mounted(box):
    result = box.execute("from pathlib import Path; print(Path('/home').exists())")
    assert result.ok, result.stderr
    assert result.stdout.strip() == "False"


def test_outbound_socket_is_blocked(box):
    result = box.execute(
        "import socket\ntry:\n socket.socket().connect(('1.1.1.1', 443))\n print('CONNECTED')\nexcept OSError:\n print('BLOCKED')"
    )
    assert result.ok, result.stderr
    assert result.stdout.strip() == "BLOCKED"


def test_execution_failure_is_recorded(box):
    result = box.execute("raise ValueError('deliberate failure')")
    assert not result.ok
    assert "ValueError" in result.stderr
    history = box.history()
    assert any(row["exit_code"] != 0 for row in history)


def test_workspace_is_not_shared_between_sandboxes(tmp_path):
    manager = SandboxManager(tmp_path)
    with manager.sandbox() as first, manager.sandbox() as second:
        first.put_text("example.txt", "only-first")
        assert second.files() == []
