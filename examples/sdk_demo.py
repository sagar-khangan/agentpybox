"""Two persistent sessions + binary artifacts + end-to-end cleanup."""
from pathlib import Path
from tempfile import TemporaryDirectory

from agenthaven import SandboxManager


def main():
    manager = SandboxManager()
    first = manager.create("python-data", ttl_seconds=300)
    second = manager.create("python-test", ttl_seconds=300)
    print("Sessions:", first.id, second.id)
    try:
        first.put_text("sales.csv", "region,amount\nwest,25\neast,30\nwest,15\n")
        result = first.execute("""import csv
from pathlib import Path
with open('sales.csv', newline='') as file:
    total = sum(int(row['amount']) for row in csv.DictReader(file))
Path('report.txt').write_text(f'Total: {total}')
print('Generated report')
""")
        print("Data execution:", result.to_dict())
        assert result.ok, result.stderr
        with TemporaryDirectory() as folder:
            target = Path(folder) / "report.txt"
            first.download("report.txt", target)
            print("Downloaded:", target.read_text())

        other = second.execute("import unittest\nassert 2 + 2 == 4\nprint('Tests passed')")
        assert other.ok, other.stderr
        print("Test execution:", other.stdout.strip())
        print("First history:", first.history())
        print("Metrics:", manager.metrics())
    finally:
        first.terminate()
        second.terminate()
        print("Both sessions terminated")


if __name__ == "__main__":
    main()
