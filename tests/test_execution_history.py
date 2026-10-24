import shutil

import pytest
from fastapi.testclient import TestClient

from agenthaven import api


@pytest.mark.skipif(
    not shutil.which("bwrap") or not shutil.which("prlimit"),
    reason="Bubblewrap and prlimit required",
)
def test_execution_history(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)

    with TestClient(api.app) as client:
        # Create sandbox.
        response = client.post("/sandboxes")
        assert response.status_code == 201

        sid = response.json()["id"]
        base = f"/sandboxes/{sid}"

        # Execute Python.
        response = client.post(
            f"{base}/execute",
            json={
                "language": "python",
                "code": "print(42)",
            },
        )

        assert response.status_code == 200
        result = response.json()

        assert result["exit_code"] == 0, result["stderr"]
        assert result["stdout"].strip() == "42"
        assert "execution_id" in result

        execution_id = result["execution_id"]

        # List executions.
        response = client.get(f"{base}/executions")
        assert response.status_code == 200

        history = response.json()["executions"]
        assert len(history) == 1
        assert history[0]["id"] == execution_id
        assert history[0]["exit_code"] == 0

        # Inspect one execution.
        response = client.get(f"{base}/executions/{execution_id}")

        assert response.status_code == 200
        assert response.json()["sandbox_id"] == sid

        # Terminate sandbox.
        response = client.delete(base)
        assert response.status_code == 200

        # History remains after termination.
        response = client.get(f"{base}/executions")
        assert response.status_code == 200
        assert len(response.json()["executions"]) == 1
