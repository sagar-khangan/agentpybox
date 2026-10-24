import math
import sqlite3
from collections import Counter
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/observability", tags=["Observability"])

# Configured by the API on startup / module import.
_db_factory = None


def configure(database_factory):
    global _db_factory
    _db_factory = database_factory


def get_db():
    if _db_factory is None:
        raise RuntimeError("Observability not configured")
    return _db_factory()


def percentile(values, percent):
    if not values:
        return 0.0

    ordered = sorted(values)
    index = (len(ordered) - 1) * percent / 100
    lower = math.floor(index)
    upper = math.ceil(index)

    value = ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)

    return round(value, 2)


def outcome(row):
    if row["timed_out"]:
        return "timeout"
    if row["exit_code"] == 0:
        return "success"
    return "failure"


class TimeWindow(BaseModel):
    hours: int = Field(default=24, ge=1, le=720)


@router.get("/summary")
def summary(hours: int = 24):
    if not 1 <= hours <= 720:
        raise HTTPException(422, "hours must be 1..720")

    cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT exit_code, duration_ms, timed_out, truncated
            FROM executions
            WHERE executed_at >= ?
            ORDER BY executed_at DESC
            """,
            (cutoff,),
        ).fetchall()

        statuses = conn.execute(
            """
            SELECT status, COUNT(*) AS total
            FROM sandboxes
            GROUP BY status
            """
        ).fetchall()

    counts = Counter(outcome(row) for row in rows)
    durations = [row["duration_ms"] for row in rows]
    total = len(rows)

    return {
        "window_hours": hours,
        "executions": {
            "total": total,
            "success": counts["success"],
            "failure": counts["failure"],
            "timeout": counts["timeout"],
            "success_rate_pct": round(counts["success"] / total * 100, 2)
            if total
            else 0.0,
            "truncated_output": sum(bool(row["truncated"]) for row in rows),
        },
        "latency_ms": {
            "average": round(sum(durations) / total, 2) if total else 0.0,
            "p50": percentile(durations, 50),
            "p95": percentile(durations, 95),
            "p99": percentile(durations, 99),
            "maximum": max(durations, default=0),
        },
        "sandboxes": {row["status"]: row["total"] for row in statuses},
    }


@router.get("/executions")
def recent_executions(limit: int = 20):
    if not 1 <= limit <= 100:
        raise HTTPException(422, "limit must be 1..100")

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, sandbox_id, language,
                   exit_code, duration_ms,
                   timed_out, truncated, executed_at
            FROM executions
            ORDER BY executed_at DESC, rowid DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return {"executions": [{**dict(row), "outcome": outcome(row)} for row in rows]}


@router.get("/sandboxes/{sandbox_id}")
def sandbox_metrics(sandbox_id: str):
    with get_db() as conn:
        sandbox = conn.execute(
            "SELECT * FROM sandboxes WHERE id = ?",
            (sandbox_id,),
        ).fetchone()

        if sandbox is None:
            raise HTTPException(404, "Sandbox not found")

        rows = conn.execute(
            """
            SELECT exit_code, duration_ms, timed_out, truncated
            FROM executions
            WHERE sandbox_id = ?
            """,
            (sandbox_id,),
        ).fetchall()

    counts = Counter(outcome(row) for row in rows)
    durations = [row["duration_ms"] for row in rows]

    return {
        "sandbox_id": sandbox_id,
        "status": sandbox["status"],
        "created_at": sandbox["created_at"],
        "terminated_at": sandbox["terminated_at"],
        "expires_at": sandbox["expires_at"],
        "total_executions": len(rows),
        "success": counts["success"],
        "failure": counts["failure"],
        "timeout": counts["timeout"],
        "latency_ms": {
            "p50": percentile(durations, 50),
            "p95": percentile(durations, 95),
            "p99": percentile(durations, 99),
        },
    }


@router.get("/health")
def observability_health():
    try:
        with get_db() as conn:
            conn.execute("SELECT 1").fetchone()
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(503, "Observability storage unavailable") from exc

    return {
        "status": "ok",
        "storage": "sqlite",
        "timestamp": datetime.now(UTC).isoformat(),
    }
