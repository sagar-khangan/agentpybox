# AgentHaven release-preparation overlay

This overlay intentionally does NOT replace your current `runner.py`, `manager.py`,
`cli.py`, `environments.py`, `Makefile`, `pyproject.toml` or `README.md`.
Your current local project may contain newer working fixes, including the pandas
virtual environment mount. Keep those files unchanged.

1. Back up/commit your working project.
2. Copy the contents of this overlay into the project root (merge directories).
3. Add `include Makefile.release` at the bottom of your existing Makefile.
4. Run `make check`, `make test-security`, `make security-audit`, `make benchmark`.
5. Run `make build`. Review `docs/SECURITY.md` and `docs/RELEASE.md`.
6. Inspect the Git diff, then commit and push. Tag only after a successful Ubuntu
   local integration run and GitHub CI.

The overlay does not implement cgroup quotas, seccomp hardening or audited
process-tree cleanup. Those require separate host-specific engineering.
