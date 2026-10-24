"""Public data types for AgentHaven."""
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ExecutionResult:
    id: str
    sandbox_id: str
    profile: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool
    truncated: bool
    executed_at: str
    source_sha256: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "ok": self.ok}
