from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from agenthaven import api


def test_observability_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)

    with TestClient(api.app) as client:
        response = client.post("/sandboxes")
        assert response.status_code == 201
        sid = response.json()["id"]

        with api.database() as conn:
            for exit_code, duration, timed_out in [
                (0, 50.0, 0),
                (0, 100.0, 0),
                (1, 200.0, 0),
                (None, 5000.0, 1),
            ]:
                conn.execute(
                    """
                    INSERT INTO executions
                    (id, sandbox_id, language, exit_code,
                     duration_ms, timed_out, truncated, executed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        sid,
                        "python",
                        exit_code,
                        duration,
                        timed_out,
                        0,
                        datetime.now(UTC).isoformat(),
                    ),
                )

        response = client.get("/observability/summary")
        assert response.status_code == 200

        data = response.json()
        assert data["executions"]["total"] == 4
        assert data["executions"]["success"] == 2
        assert data["executions"]["failure"] == 1
        assert data["executions"]["timeout"] == 1
        assert data["executions"]["success_rate_pct"] == 50.0
        assert data["latency_ms"]["p50"] == 150.0

        response = client.get(f"/observability/sandboxes/{sid}")
        assert response.status_code == 200
        assert response.json()["total_executions"] == 4

        response = client.get("/observability/executions?limit=2")
        assert response.status_code == 200
        assert len(response.json()["executions"]) == 2

        response = client.get("/observability/health")
        assert response.status_code == 200
