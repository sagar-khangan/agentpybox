from fastapi.testclient import TestClient

from agenthaven import api


def test_file_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)

    with TestClient(api.app) as client:
        # Create sandbox
        response = client.post("/sandboxes")
        assert response.status_code == 201

        sid = response.json()["id"]
        base = f"/sandboxes/{sid}"

        # Write file
        response = client.put(
            f"{base}/files/hello.py",
            json={"content": "print('hello')\n"},
        )
        assert response.status_code == 200

        # List files
        response = client.get(f"{base}/files")
        assert response.status_code == 200
        assert any(f["filename"] == "hello.py" for f in response.json()["files"])

        # Read file
        response = client.get(f"{base}/files/hello.py")
        assert response.json()["content"] == "print('hello')\n"

        # Reject traversal and hidden files
        response = client.put(
            f"{base}/files/.secret",
            json={"content": "no"},
        )
        assert response.status_code == 400

        # Delete file
        response = client.delete(f"{base}/files/hello.py")
        assert response.status_code == 200

        # Terminate sandbox
        response = client.delete(base)
        assert response.json()["status"] == "terminated"

        # Terminated sessions cannot be modified
        response = client.put(
            f"{base}/files/new.txt",
            json={"content": "test"},
        )
        assert response.status_code == 409
