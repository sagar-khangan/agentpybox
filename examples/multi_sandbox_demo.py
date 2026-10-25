from agentpybox import SandboxManager


def main():
    manager = SandboxManager()
    with manager.sandbox() as left, manager.sandbox() as right:
        left.put_text("input.txt", "left")
        right.put_text("input.txt", "right")
        code = "from pathlib import Path; print(Path('input.txt').read_text())"
        a = left.execute(code)
        b = right.execute(code)
        assert a.ok and b.ok, (a.stderr, b.stderr)
        print(left.id, a.stdout.strip())
        print(right.id, b.stdout.strip())
    print(manager.metrics(hours=24))


if __name__ == "__main__":
    main()
