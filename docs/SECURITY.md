# AgentHaven threat model and security boundaries

AgentHaven is designed for **one trusted local OS user**. It is **not** a hardened solution for hostile generated code or multi-tenant use. The executable and its package dependencies run with the current user's privileges at the host kernel boundary.

## Current controls
- Bubblewrap user, mount, PID, network and other namespace separation (`--unshare-all`).
- `/usr` and environment dependencies are mounted read-only; writable `/work` is session-scoped.
- No network namespace connectivity from the sandbox by default.
- Host-side source/output limits and per-process `prlimit` CPU, address-space, file-size, FD and core limits.
- Serialized execution under inter-process lock; TTL checked on lifecycle operations.
- Artifact filename validation and descriptor-relative operations for some file access.

## Not guaranteed
- **No cgroup v2 whole-process-tree memory/PID/CPU quota**. `RLIMIT_AS` is virtual address space, not resident RAM; `RLIMIT_CPU` is not a cgroup CPU-time budget.
- The sandbox shares the Linux kernel and current host UID for workspace access.
- Process group killing may not capture malicious children that deliberately escape the group.
- File creation from executed code is not covered by a hard workspace disk quota.
- Executable third-party wheels can contain native code and packaging vulnerabilities.
- No seccomp application-specific syscall denylist or supply-chain package attestation.
- No networked authentication because this is a local library/CLI.

## Host setup
Run as an unprivileged account. Never loosen system AppArmor/userns restrictions globally to make tests pass. Only install trusted dependencies after review. Keep registry state and workspaces in a private home directory, away from credentials; don't mount host secrets into the sandbox. Treat tests as smoke/regression probes, not as proof of security.

## Safe release label
**Local developer prototype / reviewed code only.** For unreviewed autonomous execution, use a dedicated VM/microVM, a separately privileged sandbox service and whole-tree resource quotas.
