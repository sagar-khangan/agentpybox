# AgentHaven

**Lightweight, Dockerless Execution Sandboxes for AI Agents**

*Create. Execute. Inspect. Destroy.*

AgentHaven is an experimental, Linux-native execution runtime designed to let AI agents run code inside temporary, restricted environments without requiring Docker, Kubernetes or a virtual machine.

The project explores how lightweight process isolation, resource controls and sandbox lifecycle management can be built using Python, Go, Rust and Linux primitives.

> **Project status: Early development.** AgentHaven is not yet a security-hardened execution environment. Do not use it for untrusted production workloads.

## Why AgentHaven?

AI agents increasingly need to execute generated code, run tests, manipulate files and inspect program output.

Tools such as Daytona provide managed execution environments, but building a smaller local runtime is an interesting way to understand the underlying engineering challenges.

AgentHaven focuses on:

- Lightweight, local-first development
- Dockerless execution using Linux isolation primitives
- Explicit sandbox lifecycle management
- Temporary and persistent-session workspaces
- Bounded execution and resource consumption
- Simple APIs for agent frameworks
- Reproducible testing and performance measurement

## Planned Capabilities

| Capability | Status |
|---|---|
| Python execution | Planned for v0.1 |
| Bubblewrap isolation | Planned for v0.1 |
| Create / Execute / Destroy API | Planned for v0.1 |
| Session persistence with SQLite | Planned for v0.1 |
| Timeouts and output limits | Planned for v0.1 |
| Go execution supervisor | Planned for v0.2 |
| Go code execution | Planned for v0.2 |
| Rust launcher and policy experiments | Planned for v0.3 |
| LangGraph integration | Planned for v0.3 |
| Security and performance benchmarks | Planned for v0.4 |

## Target Architecture

```text
AI Agent / LangGraph
         |
         v
Python API + Control Plane
         |
         v
Go Execution Supervisor
         |
         v
Isolation Backend
(Bubblewrap / Linux)
         |
         v
Temporary Sandbox Workspace
         |
         v
Execution Result + Cleanup
```

SQLite stores session metadata and lifecycle history. The runtime manages temporary workspaces and execution limits.

## Proposed API

```text
POST   /sandboxes
GET    /sandboxes
GET    /sandboxes/{id}
POST   /sandboxes/{id}/execute
DELETE /sandboxes/{id}
```

Illustrative request:

```json
{
  "language": "python",
  "code": "print(2 + 2)",
  "timeout_seconds": 5
}
```

Illustrative response:

```json
{
  "exit_code": 0,
  "stdout": "4\n",
  "stderr": "",
  "duration_ms": 25
}
```

These examples describe the intended API, not functionality currently available.

## Security Scope

The initial implementation is intended for local experimentation with code from known or controlled sources.

Future work will evaluate:

- Linux namespaces and filesystem restrictions
- Network isolation
- Process and execution time limits
- Cgroup-based resource accounting
- Syscall filtering
- Termination and orphan-process handling
- Filesystem and credential exposure tests

A lightweight sandbox is not automatically a secure sandbox. Isolation guarantees must be measured and validated.

## Development Roadmap

**v0.1 — Lifecycle MVP:** Python API, Bubblewrap execution, SQLite sessions, temporary workspaces and cleanup.

**v0.2 — Go Supervisor:** Worker management, process cancellation, concurrency control and execution metrics.

**v0.3 — Multi-Language and Agent Integration:** Go/Rust experiments, Python SDK and LangGraph integration.

**v0.4 — Hardening and Benchmarks:** Isolation tests, fault injection, resource accounting, performance comparisons and documentation.

## Technology Stack

Python · FastAPI · SQLite · Go · Rust · Bubblewrap · Linux namespaces · LangGraph

## License

MIT License.

## Inspiration

Inspired by developer sandbox platforms including Daytona, with a focus on exploring a smaller, local-first execution runtime.