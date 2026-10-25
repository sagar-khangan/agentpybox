# AgentPyBox Security Control Matrix

**Classification:** Local developer prototype / reviewed code only. **Not certified for hostile, multi-tenant or unreviewed autonomous code execution.**

This matrix reflects the current Bubblewrap-based runner and registered-environment design. **Implemented** means code attempts to apply a control; **tested** means a relevant test exists or a specific behavior has been observed. Neither status establishes resistance to a determined adversary.

## Control inventory

| Control | Status | Mechanism | Verification | Residual risk / limitation |
|---|---|---|---|---|
| Unprivileged execution | Operator requirement | Run SDK/CLI as an ordinary Linux user | `id -u`; `make security-audit` | No privilege separation between trusted host app and writable sandbox files |
| Linux namespace isolation | Implemented | Bubblewrap `--unshare-all`, `--die-with-parent`, `--new-session` | `make doctor`; Bubblewrap integration/security tests on Ubuntu | Shared kernel; user namespace/AppArmor configuration matters |
| Network isolation | Implemented by default | Bubblewrap network namespace with no network setup | Representative network-denial regression test (`make test-security`) | A test of selected connections is not formal proof of universal network isolation |
| Filesystem mounts | Implemented | Read-only `/usr`, system libraries and registered venv; writable `/work`, temporary `/tmp` | Host-path and workspace isolation tests; inspect runner command | Host UID shared for workspace; race conditions and mount/kernel vulnerabilities remain |
| Virtual environment immutability during execution | Implemented mount policy | `--ro-bind` registered environment | Execute with installed packages and attempt write in integration tests | Trusted host can edit/delete environment; packages may contain native code |
| Approved environment creation | Policy/process, partially technical | Registry validates a subset of requirements; `uv` installation initiated by caller | `tests/test_environments.py` and manual operator review | Installs occur outside Bubblewrap; no mandatory human-approval enforcement in SDK; no provenance/signature attestation |
| Wall-clock execution timeout | Implemented | `subprocess.wait(timeout=...)` followed by process-group signal | Timeout integration test | Descendants may escape process group; not guaranteed whole-tree teardown |
| Per-process CPU time | Implemented | `prlimit --cpu` | Inspect runner flags and resource-limit tests | Not an aggregate cgroup CPU quota |
| Virtual address-space limit | Implemented | `prlimit --as` | Inspect runner flags | Not actual resident RAM accounting; may reject native scientific libraries before physical RAM is exhausted |
| Output-size limit | Implemented return limit | Bounded stdout/stderr reads | Output-truncation test | Temporary capture files can grow while process runs; not bounded at write time |
| File-size and FD limits | Implemented per process | `prlimit --fsize`, `--nofile`, `--core` | Inspect runner flags; targeted limit tests | Not full workspace disk quota or process-tree quota |
| Artifact name/size checks | Implemented in SDK | Flat filenames; single-transfer cap; some descriptor-relative and no-follow operations | SDK file tests | Sandbox code can create additional files; hostile concurrent filesystem modifications may race checks |
| Sandbox TTL | Implemented on access/cleanup | SQLite expiry timestamps; `SandboxManager.cleanup()` | Lifecycle tests; `agentpybox cleanup` | No always-running cleanup service; expired sessions persist until next management action |
| Persistent audit data | Partial | SQLite records execution ID, hash, timestamps, exit, timeout, truncated, wall time | `agentpybox history`, `agentpybox metrics` | stdout/stderr not retained, no immutable audit log, CPU and peak RSS not collected |
| Inter-process coordination | Implemented for local CLI | File lock serializes execution/management operations | Multi-process smoke tests | Not distributed locking or multi-host orchestration |
| cgroup-v2 CPU/RAM/PID limits | **Not implemented** | None in current executor | `make security-audit` reports detection and `cgroup_limits_enforced_by_agentpybox: false` | No guaranteed total resource quota across descendants |
| Application-specific seccomp policy | **Not implemented** | None | Code/config review | Broader syscall access than a tightly hardened sandbox |
| Hard filesystem quota | **Not implemented** | None | Code/config review | Workspace may exhaust available filesystem space |
| Strong process-tree cleanup | **Not guaranteed** | Process-group kill on timeout and Bubblewrap parent death | Timeout and descendant tests | Deliberately detached children can defeat simple process-group cleanup |
| Authentication / tenant authorization | Not applicable to local-only design | No HTTP server | Architectural review | Any code running as the same OS user can potentially access local state |

## Status vocabulary

- **Implemented:** mechanism is present in the project, not a security certification.
- **Partially implemented:** specific functionality exists but has known enforcement gaps.
- **Operator requirement:** safety depends on local decisions or permissions outside AgentPyBox.
- **Not implemented:** no effective corresponding control is provided.
- **Tested on host:** only claim this after running the test successfully on the actual Linux machine; a skipped test gives no positive evidence.

## Validation checklist (Ubuntu)

Run from the AgentPyBox repository:

```bash
uv run agentpybox doctor
make security-audit
make test-security
make check
uv run agentpybox run --env python-basic --code "print('isolated execution smoke test')"
```

For registered package environments, also test the specific environment and a representative import:

```bash
uv run agentpybox env list
uv run agentpybox run --env python-pandas --code "import pandas; print(pandas.__version__)"
```

Record **date, OS/kernel, Bubblewrap version, AppArmor mode, skipped tests, and actual test results** when publishing security claims. Avoid describing cgroup availability as cgroup enforcement. `make security-audit` is a capability inventory, not a penetration test.

## Threat model and recommended use

**In scope:** avoiding accidental host file access, reducing unwanted network activity, limiting individual execution time, managing temporary workspaces, and providing useful diagnostics for *reviewed* local scripts.

**Out of scope:** malicious code deliberately attempting sandbox escape, native extension exploits, denial of service by process trees/disk exhaustion, hostile package installation, concurrent malicious filesystem races, multi-user/remote tenancy, and confidentiality against software running as the same host user.

For unreviewed AI-generated code on a sensitive machine, do **not** treat `-y` auto-approval as a safety mechanism. Use human review or stronger VM/microVM isolation with independent identities and enforceable resource quotas.

## Related documents

- [`SECURITY.md`](SECURITY.md) — security model and host guidance
- [`../README.md`](../README.md) — setup, CLI and SDK usage
- [`architecture.md`](architecture.md) — design and execution flow (where present)
