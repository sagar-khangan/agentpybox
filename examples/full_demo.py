import httpx

BASE_URL = "http://127.0.0.1:8000"


def checked(response):
    response.raise_for_status()
    return response.json()


def main():
    with httpx.Client(timeout=15) as client:
        sandbox = checked(
            client.post(
                f"{BASE_URL}/sandboxes",
                json={"ttl_seconds": 300},
            )
        )

        sid = sandbox["id"]
        base = f"{BASE_URL}/sandboxes/{sid}"

        print(f"\n[1] CREATED: {sid}")

        try:
            checked(
                client.put(
                    f"{base}/files/input.txt",
                    json={"content": "AgentHaven"},
                )
            )
            print("[2] UPLOADED: input.txt")

            code = (
                "from pathlib import Path\n"
                "name = Path('input.txt').read_text()\n"
                "Path('output.txt').write_text("
                "f'Hello, {name}!')\n"
                "print('Python executed successfully')\n"
            )

            result = checked(
                client.post(
                    f"{base}/execute",
                    json={
                        "language": "python",
                        "code": code,
                    },
                )
            )

            assert result["exit_code"] == 0, result["stderr"]
            print(f"[3] EXECUTED: {result['stdout'].strip()}")
            print(f"    Duration: {result['duration_ms']} ms")

            output = checked(client.get(f"{base}/files/output.txt"))
            assert output["content"] == "Hello, AgentHaven!"
            print(f"[4] OUTPUT: {output['content']}")

            history = checked(client.get(f"{base}/executions"))
            assert len(history["executions"]) == 1
            print("[5] HISTORY: 1 execution recorded")

            info = checked(client.get(base))
            assert info["status"] == "created"
            print(f"[6] SESSION: {info['status']}")
            print(f"    Expires: {info['expires_at']}")

        finally:
            terminated = checked(client.delete(base))
            assert terminated["status"] == "terminated"
            print(f"[7] TERMINATED: {terminated['status']}")

    print("\nAGENTHAVEN FULL LIFECYCLE PASSED")


if __name__ == "__main__":
    main()
