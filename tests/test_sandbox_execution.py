import shutil

import pytest
from fastapi.testclient import TestClient

from agenthaven import api


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)

    with TestClient(api.app) as test_client:
        yield test_client


def create_sandbox(client):
    response = client.post("/sandboxes")
    assert response.status_code == 201
    return response.json()["id"]


def execute(client, sandbox_id, code):
    return client.post(
        f"/sandboxes/{sandbox_id}/execute",
        json={"language": "python", "code": code},
    )


@pytest.mark.skipif(
    shutil.which("bwrap") is None or shutil.which("prlimit") is None,
    reason="Bubblewrap/prlimit required",
)
class TestSandboxExecution:
    def test_execute_python(self, client):
        sid = create_sandbox(client)

        result = execute(client, sid, "print(10 + 20)")

        assert result.status_code == 200
        data = result.json()

        assert data["exit_code"] == 0, data["stderr"]
        assert data["stdout"].strip() == "30"

    def test_python_error(self, client):
        sid = create_sandbox(client)

        result = execute(client, sid, "raise ValueError('test error')")

        assert result.status_code == 200
        data = result.json()

        assert data["exit_code"] != 0
        assert "ValueError" in data["stderr"]

    def test_workspace_persistence(self, client):
        sid = create_sandbox(client)

        first = execute(
            client,
            sid,
            "from pathlib import Path\nPath('hello.txt').write_text('persisted')",
        )

        assert first.json()["exit_code"] == 0

        second = execute(
            client,
            sid,
            "from pathlib import Path\nprint(Path('hello.txt').read_text())",
        )

        assert second.json()["exit_code"] == 0
        assert second.json()["stdout"].strip() == "persisted"

    def test_host_home_not_visible(self, client):
        sid = create_sandbox(client)

        result = execute(
            client,
            sid,
            "from pathlib import Path\nprint(Path('/home/ubuntu/.aws').exists())",
        )

        assert result.json()["exit_code"] == 0
        assert result.json()["stdout"].strip() == "False"

    def test_network_isolation(self, client):
        sid = create_sandbox(client)

        result = execute(
            client,
            sid,
            "import socket\n"
            "try:\n"
            "    socket.create_connection("
            "('1.1.1.1', 443), timeout=1)\n"
            "    print('CONNECTED')\n"
            "except OSError:\n"
            "    print('BLOCKED')",
        )

        assert result.json()["exit_code"] == 0
        assert result.json()["stdout"].strip() == "BLOCKED"

    def test_termination(self, client, tmp_path):
        sid = create_sandbox(client)
        workspace = tmp_path / "sandboxes" / sid

        assert workspace.exists()

        response = client.delete(f"/sandboxes/{sid}")

        assert response.status_code == 200
        assert response.json()["status"] == "terminated"
        assert not workspace.exists()

        result = execute(client, sid, "print('hello')")
        assert result.status_code == 409
