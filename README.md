# AgentHaven

**Lightweight, Dockerless Python execution sandboxes for local developers and AI agents.**

AgentHaven is a **Python library and command-line tool**, not a web service. It creates multiple isolated execution sessions on Linux, runs Python code inside Bubblewrap, transfers files (including binary artifacts), records execution history, reports lightweight metrics, and cleans up sandbox workspaces.

**No FastAPI, Docker, LangChain, LangGraph, or always-running service required.** Future agents can call the same Python library directly.

> [!WARNING]
> **Local developer prototype — not a hardened untrusted-code sandbox.** Bubblewrap shares the host kernel, sandbox processes share the operator's OS user identity for the writable workspace, and resource controls are not enforced over an entire process tree. Do **not** run hostile or unreviewed LLM-generated code on a sensitive host, run AgentHaven as root, or expose it as a multi-user isolation service. See [Security model and limitations](#security-model-and-limitations).

## Features

- **Multiple sessions:** Create, inspect, list, reuse, and terminate independent sandboxes.
- **Python execution:** Run scripts or snippets with separate Python interpreter launches; workspace files persist per session.
- **Runtime profiles:** `python-basic`, `python-data`, and `python-test`, each with predefined limits.
- **One-command workflow:** Create → upload input files → execute → download outputs → terminate.
- **Artifacts:** Text and binary file upload/download, with flat filenames and a 10 MiB transfer limit per file.
- **State:** SQLite execution history, source hashes, timestamps, and sandbox lifecycle information.
- **Observability:** Execution counts, outcomes, timeout and truncation counts, and p50/p95/p99 wall-clock durations.
- **TTL and recovery:** Expire sessions when the manager starts or the CLI cleanup command runs.
- **CLI + SDK:** The same engine is accessible through terminal commands or Python classes.

## Architecture

```text
          Developer / Python application / AI agent
                            |
                 +----------+----------+
                 |                     |
          agenthaven CLI         Python SDK
                 |                     |
                 +----------+----------+
                            |
                      SandboxManager
                            |
               +------------+------------+
               |                         |
         SQLite lifecycle,             Runner
         history, metrics                |
                                  Bubblewrap + prlimit
                                         |
                               Isolated Python process
                                         |
                               Per-sandbox workspace
```

There is no REST endpoint to deploy or call. The CLI and SDK invoke the local execution engine directly.

## Requirements

- Ubuntu or another supported Linux distribution.
- `/usr/bin/python3` for code executed inside the sandbox.
- `bubblewrap` (`bwrap`) and `prlimit` (`util-linux`).
- Host Python **3.11+** and [`uv`](https://docs.astral.sh/uv/) for development and execution.
- A Linux configuration permitting Bubblewrap user namespaces. Ubuntu may require its distribution-supplied Bubblewrap AppArmor profile. **Do not disable AppArmor globally.**

```bash
sudo apt-get update
sudo apt-get install -y bubblewrap util-linux
uv sync --extra dev
uv run agenthaven doctor
uv run agenthaven profiles
uv run agenthaven run --code "print(2 + 2)"
```

For common development commands:

```bash
make install
make doctor
make check
make demo
```

## Project layout

The examples use `input/` for source data and scripts and `output/` for downloaded results:

```text
agenthaven/
├── src/agenthaven/          # Package, CLI, manager, runner and SQLite store
├── examples/                # Python SDK demonstration
├── tests/                   # Automated tests
├── input/
│   ├── analyze.py
│   ├── sales.csv
│   └── customers.csv        # Optional second input
├── output/                  # Downloaded artifacts (generated)
├── pyproject.toml
├── Makefile
└── README.md
```

`input/` is a **local project folder**, not a special sandbox mount. A `--upload input/sales.csv` option copies the file into the sandbox workspace as `sales.csv`. Scripts should open `sales.csv`, not `input/sales.csv`, unless they create that subdirectory themselves.

## Quick start: one-command execution

Create `input/sales.csv`:

```csv
product,quantity,price
Laptop,2,50000
Mouse,5,800
Keyboard,3,1500
Monitor,2,12000
```

Create `input/analyze.py`:

```python
import csv
from pathlib import Path

with open("sales.csv", newline="", encoding="utf-8") as stream:
    rows = list(csv.DictReader(stream))

total = sum(int(row["quantity"]) * float(row["price"]) for row in rows)
Path("report.txt").write_text(f"Total Revenue: Rs {total:,.2f}\n", encoding="utf-8")
print(f"Processed {len(rows)} rows")
```

Run the complete workflow:

```bash
mkdir -p output
uv run agenthaven run \
  --profile python-data \
  --file input/analyze.py \
  --upload input/sales.csv \
  --download report.txt \
  --output-dir output

cat output/report.txt
```

Expected report content for the sample data:

```text
Total Revenue: Rs 132,500.00
```

The `run` command creates a temporary sandbox and tears it down after the workflow, including on execution failures. Requested downloads must be files generated inside the sandbox. Review how your installed CLI reports missing output files before using it in automation.

### Multiple input and output files

```bash
uv run agenthaven run \
  --profile python-data \
  --file input/analyze.py \
  --upload input/sales.csv \
  --upload input/customers.csv \
  --download report.csv \
  --download summary.json \
  --output-dir output
```

**This is an advanced example, not the simple CSV demo above.** Your `input/analyze.py` must actually read both inputs and generate `report.csv` and `summary.json`; otherwise the downloads cannot succeed. Use the earlier `report.txt` command with the sample script unchanged.

### Makefile shortcuts

If you have the updated Makefile from the CLI workflow, common commands are:

```bash
make analyze                  # Input CSV -> output/report.txt
make run-script FILE=input/analyze.py
make run-code CODE="print(42)"
make metrics HOURS=24
make sandboxes
make cleanup
```

`make run-script` runs a script but does not automatically upload any additional data unless your Makefile target explicitly supplies those files.

## Persistent sandbox sessions (CLI)

Use this mode when one execution must leave files for another:

```bash
uv run agenthaven create --profile python-data --ttl 300
# Copy the returned sandbox ID:
SID="<sandbox-id>"

uv run agenthaven put "$SID" input/sales.csv
uv run agenthaven execute "$SID" --file input/analyze.py
uv run agenthaven files "$SID"
uv run agenthaven get "$SID" report.txt output/report.txt
uv run agenthaven history "$SID"
uv run agenthaven inspect "$SID"
uv run agenthaven delete "$SID"
```

Other available commands:

```bash
uv run agenthaven list
uv run agenthaven profiles
uv run agenthaven metrics --hours 24
uv run agenthaven cleanup
uv run agenthaven doctor
```

Use `uv run agenthaven --help` and `uv run agenthaven <command> --help` for exact options. CLI execution errors and nonzero script exit codes cause a nonzero CLI exit status.

## Python SDK

```python
from agenthaven import SandboxManager

manager = SandboxManager()

with manager.sandbox(profile="python-data", ttl_seconds=300) as sandbox:
    sandbox.put_text("input.csv", "a,b\n1,2\n")

    result = sandbox.execute(
        "from pathlib import Path\n"
        "print(Path('input.csv').read_text())"
    )

    print(result.stdout)
    print(result.exit_code, result.duration_ms)
    print(sandbox.files())
    print(sandbox.history())

# Context manager terminates the session.
print(manager.metrics(hours=24))
```

For sessions reused across processes, call `manager.create(...)`, save the returned `.id`, then later use `manager.get(id)` and terminate the sandbox explicitly.

File methods include `upload`, `download`, `put_bytes`, `get_bytes`, `put_text`, `get_text`, `delete_file`, and `files`. Each code execution starts a **new Python interpreter**, but the workspace persists while the session exists. Executions are serialized with a local file lock (`flock`) to keep resource use modest.

## Runtime profiles

| Profile | Intended use | Timeout | Address-space limit |
| --- | --- | ---: | ---: |
| `python-basic` | General standard-library scripts | 5 seconds | 512 MiB per process |
| `python-data` | CSV, JSON, statistics, SQLite via stdlib | 10 seconds | 512 MiB per process |
| `python-test` | Standard-library `unittest` and assertions | 10 seconds | 512 MiB per process |

All profiles currently invoke `/usr/bin/python3` with predefined Bubblewrap restrictions. `python-data` **does not imply pandas or NumPy**, and `python-test` **does not imply pytest** inside the sandbox. These profiles do not currently provide distinct package sets or mount policies.

## Execution history and metrics

Execution metadata is stored in local SQLite. It includes sandbox and execution IDs, profile, SHA-256 source hash, timestamps, exit code, timeout and truncation flags, and elapsed wall time. **Source code and stdout/stderr are not retained in history**, although a calling program can store them elsewhere.

```bash
uv run agenthaven metrics --hours 24
uv run agenthaven history "$SID"
```

The metrics summary includes:

- Number of executions, successes, failures and timeouts.
- Success percentage and output truncation count.
- p50, p95, and p99 wall-clock execution duration.
- Sandbox lifecycle counts.

**Not collected:** per-execution CPU usage, peak RAM, whole-process-tree resource use or live streamed telemetry. Percentiles are calculated from stored runs; very small sample sizes should not be treated as benchmark-quality distributions.

## TTL, cleanup, and concurrency

A sandbox has an expiration time. Expired sessions are cleaned up when a new `SandboxManager` is initialized or `agenthaven cleanup` is invoked. There is **no background daemon**, so expired workspaces may remain on disk if AgentHaven is idle. Context-managed temporary sessions are terminated when the context exits.

Several sandboxes can exist at once and have separate workspaces. Execution is serialized locally; this is **not parallel multi-tenant execution**.

## Troubleshooting

**`ImportError: cannot import name 'main' from 'agenthaven.cli'`**

The `pyproject.toml` console entry point expects `agenthaven.cli:main`. Ensure the complete `src/agenthaven/cli.py` defines `main()`:

```bash
uv run python -c "from agenthaven.cli import main; print('CLI import OK')"
uv run agenthaven --help
```

**`No such file or directory: 'sales.csv'`**

Local input paths must exist before an upload. If you organized files under `input/`, use `--upload input/sales.csv`, not `--upload sales.csv`.

**A downloaded file is missing**

The executed script must generate the exact requested filename in its sandbox workspace. The basic example creates `report.txt`, not `report.csv` or `summary.json`.

**Bubblewrap fails with a namespace or permission error**

Run `uv run agenthaven doctor`; check Ubuntu's supplied Bubblewrap AppArmor/user-namespace configuration. Do not globally disable AppArmor or unprivileged namespace protections as a workaround.

**Tests**

```bash
uv sync --extra dev
make check
uv run pytest -q
```

## Security model and limitations

> [!CAUTION]
> AgentHaven is for a **single trusted local operator** experimenting with controlled code. It is **not suitable for malicious or arbitrarily unreviewed code** without significant additional isolation work.

- **Shared kernel and user identity:** Bubblewrap uses Linux namespaces but does not supply a virtual machine or different kernel. Sandbox execution uses the current operating-system account for writable workspace files.
- **No network by default:** Networking is unshared; this does not establish that every possible host escape has been prevented.
- **Incomplete process-tree controls:** `prlimit` is not a cgroup-v2 whole-tree CPU/memory/process limit, and descendant processes require stronger lifecycle enforcement.
- **Filesystem controls are not hard quotas:** API/SDK file size checks do not prevent Python code from creating additional workspace files. File operations have remaining race/host-user risks.
- **No multi-user authorization boundary:** Any program running with your OS account can potentially access local state. There is no authentication layer because there is no HTTP service.
- **No seccomp profile or hardened filesystem mount policy:** Additional kernel-level containment, filesystem quotas, and adversarial tests are needed before operating as an untrusted-code service.
- **Keep secrets outside sandbox inputs:** Source code is hashed rather than persisted in SQLite, but your OS user still owns local workspace and history files.

Never run AgentHaven as root or make it an execution endpoint for untrusted remote users in its present form.

## Development and contribution

```bash
make install
make doctor
make lint
make format
make test
make check
make demo
```

Keep `.venv/`, `.runtime/`, SQLite files, `.env` secrets, and generated `output/` artifacts out of version control. Sample files in `input/` can be committed if they contain no personal or confidential data.

## Direction

AgentHaven deliberately focuses on being a **small, framework-independent execution tool**, not a new agent orchestration framework. Possible next improvements include stronger cgroup-v2 and filesystem containment, more thorough adversarial tests, resource telemetry, controlled dependency profiles, and an improved installable CLI/SDK experience.
