# Release checklist

1. `make format && make check && make test-security` on Ubuntu with a working Bubblewrap profile.
2. `make demo-basic && make demo-multi && make benchmark` and retain `output/benchmark.json` locally.
3. `uv build`; inspect artifacts in `dist/` and confirm no secrets or `.runtime` files.
4. Push a release branch; review the GitHub Actions workflow on that branch.
5. Update `CHANGELOG.md` with actual test and benchmark results. Do **not** claim hostile-code isolation or cgroup enforcement.
6. Once reviewed, tag a release candidate with `git tag -a v1.2.0rc1 -m 'AgentHaven v1.2.0rc1' && git push origin v1.2.0rc1`.
7. GitHub Releases can attach artifacts from CI after verification; this project does not publish automatically to PyPI.

## Testing limitations
GitHub-hosted runners may prohibit unprivileged namespaces. Tests that require Bubblewrap can skip there; the release is not verified until they pass on your own configured Ubuntu host. The runner's isolation is not audited and has no cgroup-v2 enforcement.
