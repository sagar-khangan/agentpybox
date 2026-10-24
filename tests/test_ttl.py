from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from agenthaven import api


def test_expiration(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)

    with TestClient(api.app) as client:
        response = client.post(
            "/sandboxes",
            json={"ttl_seconds": 10},
        )
        assert response.status_code == 201

        sid = response.json()["id"]
        workspace = tmp_path / "sandboxes" / sid

        assert workspace.is_dir()

        expired_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()

        with api.database() as conn:
            conn.execute(
                "UPDATE sandboxes SET expires_at = ? WHERE id = ?",
                (expired_at, sid),
            )

        response = client.post("/maintenance/cleanup")
        assert response.status_code == 200
        assert response.json()["expired_count"] == 1

        response = client.get(f"/sandboxes/{sid}")
        assert response.json()["status"] == "expired"

        assert not workspace.exists()

        response = client.post(
            f"/sandboxes/{sid}/execute",
            json={"code": "print('hello')"},
        )
        assert response.status_code == 409


def test_default_ttl(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)

    with TestClient(api.app) as client:
        response = client.post("/sandboxes")
        assert response.status_code == 201

        record = response.json()
        assert record["expires_at"] is not None

        created = datetime.fromisoformat(record["created_at"])
        expires = datetime.fromisoformat(record["expires_at"])

        seconds = (expires - created).total_seconds()
        assert 299 <= seconds <= 301


def test_termination_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)

    with TestClient(api.app) as client:
        created = client.post("/sandboxes")
        assert created.status_code == 201
        sid = created.json()["id"]

        first = client.delete(f"/sandboxes/{sid}")
        second = client.delete(f"/sandboxes/{sid}")

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["status"] == "terminated"


def test_invalid_ttl(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)

    with TestClient(api.app) as client:
        response = client.post(
            "/sandboxes",
            json={"ttl_seconds": 999999},
        )

        assert response.status_code == 422
