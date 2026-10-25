"""Measure local AgentPyBox wall-clock overhead; no security guarantees implied."""

import argparse
import json
import platform
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from agentpybox import SandboxManager

CODE = "print(sum(range(1000)))"


def summary(samples):
    ordered = sorted(samples)

    def pct(p):
        if not ordered:
            return 0.0
        i = (len(ordered) - 1) * p / 100
        low = int(i)
        high = min(low + 1, len(ordered) - 1)
        return round(ordered[low] + (ordered[high] - ordered[low]) * (i - low), 3)

    return {
        "runs": len(samples),
        "mean_ms": round(statistics.mean(samples), 3),
        "p50_ms": pct(50),
        "p95_ms": pct(95),
        "p99_ms": pct(99),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--env", default="python-basic")
    parser.add_argument("--output", type=Path, default=Path("output/benchmark.json"))
    args = parser.parse_args()
    if not 1 <= args.runs <= 200 or not 0 <= args.warmups <= 20:
        parser.error("runs must be 1..200; warmups 0..20")
    manager = SandboxManager()
    plain = []
    sandboxed = []
    with manager.sandbox(profile=args.env, ttl_seconds=3600) as box:
        for i in range(args.warmups + args.runs):
            started = time.perf_counter()
            direct = subprocess.run(
                ["/usr/bin/python3", "-I", "-c", CODE],
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
            elapsed = (time.perf_counter() - started) * 1000
            result = box.execute(CODE)
            if not result.ok or result.stdout.strip() != direct.stdout.strip():
                raise RuntimeError(
                    f"Benchmark sandbox execution failed: {result.stderr}"
                )
            if i >= args.warmups:
                plain.append(elapsed)
                sandboxed.append(result.duration_ms)
    report = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "environment": args.env,
        "comparison_note": "Host subprocess vs Bubblewrap process. Includes startup; not normalized CPU or memory utilization.",
        "direct": summary(plain),
        "sandbox": summary(sandboxed),
        "wall_time_ratio_mean": round(
            statistics.mean(sandboxed) / statistics.mean(plain), 2
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
