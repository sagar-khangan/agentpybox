# AgentPyBox v1.0.0 — First Public Release

AgentPyBox is a lightweight, Dockerless Python execution sandbox for local development and AI-agent experimentation.

This first release introduces a standalone Python SDK and CLI, built on Linux Bubblewrap and SQLite, with reusable Python environments managed using `uv`.

## Highlights

- **Python SDK and CLI:** Run isolated Python workloads without starting an HTTP server.
- **Multiple sandbox sessions:** Create, inspect and terminate independent workspaces.
- **Dynamic environment registry:** Create environments from requirements files, discover installed packages and reuse environments across sessions.
- **One-command execution:** Upload input files, execute Python and download generated artifacts.
- **Execution observability:** Capture exit codes, execution durations, timeouts and historical metrics.
- **AI-agent example:** OpenRouter integration with code generation, execution retries and optional approval.
- **Developer tooling:** Automated tests, security diagnostics, benchmarking and GitHub Actions CI.

## Quick Start

```bash
uv sync --extra dev
uv run agentpybox doctor
uv run agentpybox run --code "print('Hello from AgentPyBox')"
```

Register a reusable Python environment:

```bash
uv run agentpybox env create python-pandas \
  --requirements input/requirements-data.txt

uv run agentpybox env inspect python-pandas

uv run agentpybox run \
  --env python-pandas \
  --code "import pandas; print(pandas.__version__)"
```

## Platform Support

- Linux, including supported Ubuntu environments
- Bubblewrap and util-linux (`prlimit`)
- Python 3.11+ for the host application
- `uv` for installation and environment management

## Security Status

AgentPyBox is a **local developer prototype, not a hardened security boundary for hostile code**.

It provides Linux namespace isolation, restricted filesystem mounts, network isolation and resource limits, but does not currently enforce comprehensive cgroup-v2 process-tree budgets, seccomp restrictions or hard disk quotas.

Review `docs/SECURITY.md` and `docs/SECURITY_MATRIX.md` before using AI-generated code.

## Known Limitations

- Linux only
- No HTTP or remote execution service
- Environment installation requires trusted operator approval
- Sandboxes share the host kernel
- TTL cleanup is triggered by application activity or manual cleanup, not a background daemon
- CPU and peak memory telemetry are not yet available

Feedback, issues and contributions are welcome.