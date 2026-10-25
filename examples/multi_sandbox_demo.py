"""Demonstrate independent AgentHaven sandbox sessions."""

from agenthaven import SandboxManager


def main():
    manager = SandboxManager()

    first = manager.create(
        profile="python-basic",
        ttl_seconds=300,
    )
    second = manager.create(
        profile="python-basic",
        ttl_seconds=300,
    )

    try:
        print("Sandbox A:", first.id)
        print("Sandbox B:", second.id)

        first.put_text("shared.txt", "Data from A")
        second.put_text("shared.txt", "Data from B")

        code = """
from pathlib import Path
print(Path("shared.txt").read_text())
"""

        result_a = first.execute(code)
        result_b = second.execute(code)

        assert result_a.ok, result_a.stderr
        assert result_b.ok, result_b.stderr

        assert result_a.stdout.strip() == "Data from A"
        assert result_b.stdout.strip() == "Data from B"

        print("Sandbox A output:", result_a.stdout.strip())
        print("Sandbox B output:", result_b.stdout.strip())

        # Each execution starts a new interpreter,
        # but workspace files persist.
        result = first.execute(
            """
from pathlib import Path
Path("result.txt").write_text("Second execution worked")
print(Path("result.txt").read_text())
"""
        )

        assert result.ok, result.stderr

        print("Second execution:", result.stdout.strip())
        print("Sandbox A files:", first.files())
        print("Sandbox A history:", len(first.history()))
        print("Sandbox B history:", len(second.history()))

    finally:
        first.terminate()
        second.terminate()

    print("Both sandboxes terminated.")
    print("Metrics:", manager.metrics(hours=24))


if __name__ == "__main__":
    main()
