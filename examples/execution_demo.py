import httpx

BASE_URL = "http://127.0.0.1:8000"

with httpx.Client(timeout=15) as client:
    # CREATE
    response = client.post(f"{BASE_URL}/sandboxes")
    response.raise_for_status()

    sandbox_id = response.json()["id"]
    print("CREATED:", sandbox_id)

    try:
        # EXECUTE 1: write a file
        code_1 = """
from pathlib import Path

Path("result.txt").write_text("Hello from AgentHaven!")
print("File created inside sandbox")
"""
        response = client.post(
            f"{BASE_URL}/sandboxes/{sandbox_id}/execute",
            json={"language": "python", "code": code_1},
        )
        response.raise_for_status()
        print("EXECUTION 1:", response.json())

        # EXECUTE 2: read the file from the same workspace
        code_2 = """
from pathlib import Path

print(Path("result.txt").read_text())
"""
        response = client.post(
            f"{BASE_URL}/sandboxes/{sandbox_id}/execute",
            json={"language": "python", "code": code_2},
        )
        response.raise_for_status()
        print("EXECUTION 2:", response.json())

        # INSPECT
        response = client.get(f"{BASE_URL}/sandboxes/{sandbox_id}")
        response.raise_for_status()
        print("INSPECT:", response.json())

    finally:
        # TERMINATE (also runs if execution fails)
        response = client.delete(f"{BASE_URL}/sandboxes/{sandbox_id}")
        response.raise_for_status()
        print("TERMINATED:", response.json())
