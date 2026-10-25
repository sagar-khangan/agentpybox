# AgentPyBox Integration Guide

**Audience:** Python developers, coding-agent builders, and maintainers integrating with the local AgentPyBox SDK or CLI.

AgentPyBox is a **Linux-only, Dockerless Python sandbox** with a local Python SDK and CLI. It does **not** run an HTTP server. It uses Bubblewrap for namespace-based execution, SQLite for lifecycle/history, and reusable Python environments prepared with `uv`.

> **Security boundary:** AgentPyBox is a local developer prototype, **not** a hardened sandbox for hostile code. Do not auto-execute unreviewed agent output on a sensitive machine. Environment creation and dependency installation must remain under trusted operator control. See [SECURITY.md](SECURITY.md) and [SECURITY_MATRIX.md](SECURITY_MATRIX.md).

## 1. Prerequisites

On Ubuntu/Linux, ensure `uv`, `/usr/bin/python3`, `bwrap`, and `prlimit` are available:

```bash
sudo apt-get install bubblewrap util-linux
cd /path/to/agentpybox
uv sync --extra dev
uv run agentpybox doctor
make check
```

Ubuntu may require a distribution-provided AppArmor profile for Bubblewrap user namespaces. Do not globally disable AppArmor to make a test pass.

The SDK and CLI are local; **no `make dev`, localhost HTTP URL, or FastAPI service is needed**.

## 2. Choose an integration style

| Client | Recommended interface | Typical use |
|---|---|---|
| Python application | `SandboxManager` SDK | Programmatic lifecycle and artifact transfer |
| Terminal, build pipeline | `agentpybox` CLI | Scripts, smoke tests, one-off jobs |
| AI coding agent | SDK behind a reviewed tool wrapper | Generate, inspect, execute, evaluate, retry |
| LangChain/LangGraph later | Thin adapter calling the SDK | Framework-specific tools without changing AgentPyBox |

Do not import or depend on a nonexistent AgentPyBox HTTP endpoint.

## 3. Discover or prepare an environment

### Inspect existing environments

```bash
uv run agentpybox env list
uv run agentpybox env inspect python-basic
uv run agentpybox env find --package pandas
uv run agentpybox env find --package pandas --package numpy
```

Built-in `python-basic`, `python-data`, and `python-test` profiles use the system Python standard library. They do not install pandas or pytest. Other environments are prepared once and reused across sandbox sessions.

### Register dependencies (trusted operator only)

Create `input/requirements-data.txt`:

```text
pandas
numpy
```

Then:

```bash
uv run agentpybox env create python-pandas \
  --requirements input/requirements-data.txt
uv run agentpybox env inspect python-pandas
```

For reproducible builds, pin tested package versions and review package provenance. Registration downloads/install packages **outside** Bubblewrap; it must never be triggered automatically from arbitrary agent text. Agents can *request* an environment, but approval belongs to the operator.

### Python discovery

```python
from agentpybox import SandboxManager

manager = SandboxManager()
for env in manager.environments.list():
    print(env["name"], env.get("status"), env.get("packages", {}))

matches = manager.environments.find(["pandas", "numpy"])
if not matches:
    raise RuntimeError("No approved environment contains pandas and numpy")
env_name = matches[0]["name"]
```

A package name in the registry is **not** proof that every import or native extension works inside Bubblewrap; run a smoke test.

## 4. One-command execution (CLI)

Use repository-relative paths for local inputs. Files are uploaded under their basenames into the sandbox workspace.

```bash
uv run agentpybox run \
  --env python-pandas \
  --file input/pandas_analysis.py \
  --upload input/sales.csv \
  --upload input/customers.csv \
  --download report.csv \
  --download summary.json \
  --output-dir output/
```

The `run` command creates a temporary session, uploads inputs, executes the script, attempts requested downloads, and terminates the session. Its exit status indicates whether execution/downloads succeeded. The executed script must create the named output files in its working directory.

Simpler examples:

```bash
uv run agentpybox run --env python-basic --code "print(sum(range(100)))"
uv run agentpybox run --env python-pandas --code "import pandas; print(pandas.__version__)"
```

## 5. Persistent sessions via the CLI

Use this flow when separate executions need access to the same workspace files.

```bash
uv run agentpybox create --env python-basic --ttl 300
# Set SID to the ID from the returned JSON:
SID="<sandbox-id>"
uv run agentpybox put "$SID" input/sales.csv
uv run agentpybox execute "$SID" --file input/analyze.py
uv run agentpybox files "$SID"
uv run agentpybox get "$SID" report.txt output/report.txt
uv run agentpybox history "$SID"
uv run agentpybox inspect "$SID"
uv run agentpybox delete "$SID"
```

Each `execute` call starts a **new Python interpreter**; files persist between calls until the sandbox is terminated or expires. Multiple sessions may exist, but executions are serialized by the current local locking implementation.

## 6. Python SDK: complete lifecycle

```python
from pathlib import Path
from agentpybox import SandboxManager

manager = SandboxManager()
Path("output").mkdir(exist_ok=True)

with manager.sandbox(profile="python-basic", ttl_seconds=300) as box:
    box.upload("input/sales.csv")

    result = box.execute('''
import csv
from pathlib import Path
with open("sales.csv", newline="") as f:
    rows = list(csv.DictReader(f))
total = sum(int(r["quantity"]) * float(r["price"]) for r in rows)
Path("report.txt").write_text(f"Total revenue: {total:.2f}\\n")
print("Processed", len(rows), "rows")
''')

    print("Exit code:", result.exit_code)
    print("Time (ms):", result.duration_ms)
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)

    if not result.ok:
        raise RuntimeError("Execution failed")

    box.download("report.txt", "output/report.txt")
    print("Files:", box.files())
    print("History:", box.history())

# The context manager terminates the sandbox even if code raises.
print("Metrics:", manager.metrics(hours=24))
```

Other supported artifact operations include `put_text`, `get_text`, `put_bytes`, `get_bytes`, `upload`, `download`, `delete_file`, and `files`. File names inside a sandbox are **flat names**, not arbitrary paths. Individual transfers are limited to 10 MiB by the SDK; that is not a hard storage quota on code executing inside the workspace.

### SDK-managed persistent sessions

```python
from agentpybox import SandboxManager

manager = SandboxManager()
box = manager.create(profile="python-basic", ttl_seconds=300)
print(box.id)  # persist this ID in your application

# In a later Python process:
box = SandboxManager().get("<sandbox-id>")
print(box.execute("print('resume')").stdout)
box.terminate()
```

## 7. Integrating a coding agent safely

The recommended host-side workflow:

1. Receive a user task and optional input artifacts.
2. Read the environment registry and select an existing approved environment.
3. Ask the LLM to generate Python code using only the selected environment's available packages.
4. **Show the exact generated code and request human approval.**
5. Create a sandbox, upload input files, and execute the approved code.
6. Inspect `exit_code`, `timed_out`, `stderr`, and expected artifacts; success of the process alone does **not** prove task correctness.
7. Optionally request corrected code using a **sanitized, bounded** error excerpt; require approval again.
8. Download outputs, record metrics, and terminate in a `finally` block/context manager.

The repository's working demonstration is `examples/openrouter_agent.py`. OpenRouter requests happen in the host-side process, **not** inside the sandbox (which is network-isolated by default).

```bash
export OPENROUTER_API_KEY="<your-key>"
uv run python examples/openrouter_agent.py --list-envs

uv run python examples/openrouter_agent.py \
  --env python-pandas \
  --upload input/sales.csv \
  --download report.csv \
  --output-dir output \
  "Analyze sales.csv and write report.csv"
```

The example optionally supports `-y` / `--yes` to bypass approval. **Do not enable that mode for untrusted tasks or source material:** the sandbox does not offer a verified hostile-code security boundary.

### Minimal custom agent/tool adapter

This adapter does **not** create environments or download dependencies. It assumes the caller already approved the code.

```python
from agentpybox import SandboxManager

manager = SandboxManager()

def run_approved_python(code: str, env_name: str = "python-basic") -> dict:
    env = manager.environments.inspect(env_name)
    if env.get("status") != "ready":
        raise ValueError("Environment is not ready")

    with manager.sandbox(profile=env_name, ttl_seconds=300) as box:
        result = box.execute(code)
        return {
            "execution_id": result.id,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_ms": result.duration_ms,
            "timed_out": result.timed_out,
            "ok": result.ok,
        }
```

**Important:** The `run_approved_python` function is a building block, not an authorization system. Enforce human approval, task limits, access policy, and tool authorization **before** allowing an LLM to call it.

A future LangChain/LangGraph adapter should wrap the same SDK method; it should not change AgentPyBox's isolation implementation or grant package installation tools to the agent.

## 8. Handling failures and retries

| Symptom | Interpretation / next step |
|---|---|
| `exit_code != 0` | Python or launcher failed; inspect `stderr` |
| `timed_out=True` | Execution exceeded the configured wall-clock limit |
| `truncated=True` | Returned stdout/stderr exceeded capture limit |
| `ModuleNotFoundError` | Inspect installed packages, selected env, and Bubblewrap mount compatibility |
| `KeyError: 'customer_id'` | CSV schema mismatch; check uploaded sample files |
| Missing download artifact | Code did not create the expected file, or exited before doing so |
| `env create` fails | Review requirements syntax, package index access, and approved package versions |
| `bwrap` initialization fails | Check Ubuntu user namespace/AppArmor configuration; do not disable global protections |

Limit retries and execution counts. Include only necessary sanitized error details in LLM requests—stdout/stderr may contain sensitive application data.

## 9. Observability and lifecycle

```bash
uv run agentpybox metrics --hours 24
uv run agentpybox history "$SID"
uv run agentpybox list
uv run agentpybox cleanup
```

History contains execution IDs, environment IDs, code SHA-256 hashes, timestamps, duration, exit code and timeout/truncation flags. It does **not** permanently retain source code or execution stdout/stderr. Metrics include counts and p50/p95/p99 **wall-clock** execution duration. Do not interpret duration as CPU time or as measured peak memory.

TTL cleanup occurs on manager initialization or manual `cleanup`, **not continuously** when AgentPyBox is idle. The default implementation uses a single host user's SQLite and workspace directories.

## 10. Security responsibilities

**What AgentPyBox currently does:** Bubblewrap namespace separation, disabled execution-network namespace, restricted mounts, read-only dependency environment mount, timeout, source/output limits, and `prlimit` resource ceilings.

**What is not guaranteed:** whole-process-tree CPU/RAM enforcement, cgroup-v2 containment, seccomp hardening, hard filesystem quotas, orphaned-child cleanup, tenant isolation, safe execution of hostile packages, and a multi-user permission boundary.

Third-party package installation through `env create` is performed by `uv` on the **host side**. It requires explicit trusted operator approval and review; agents should be given only read/list/find/use capabilities, not environment creation or deletion.

Run your host checks:

```bash
make security-audit
make test-security
```

These are diagnostic and regression checks, not proof of security certification. For a detailed control-by-control list, read [SECURITY_MATRIX.md](SECURITY_MATRIX.md).

## 11. Further documentation

- [Architecture](architecture.md) — components, environment creation and execution flow
- [Security model](SECURITY.md) — threat model and limitations
- [Security matrix](SECURITY_MATRIX.md) — implemented versus missing controls
- [Release checklist](RELEASE.md) — packaging, CI and release verification
- `README.md` — quick start and full CLI overview

**Summary:** Keep the agent's model calls and decision logic in a trusted host-side application; use AgentPyBox solely for bounded, reviewed code execution and artifacts. Reuse registered environments without letting untrusted agent prompts alter them.
