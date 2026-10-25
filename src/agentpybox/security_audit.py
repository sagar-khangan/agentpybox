"""Non-invasive host capability audit; not a guarantee of sandbox safety."""

import json
import os
import shutil
from pathlib import Path


def _read(path):
    try:
        return Path(path).read_text().strip()
    except (OSError, UnicodeError):
        return None


def audit():
    cg = Path("/sys/fs/cgroup")
    controllers = _read(cg / "cgroup.controllers")
    return {
        "unprivileged_user": os.geteuid() != 0,
        "bubblewrap_installed": shutil.which("bwrap") is not None,
        "prlimit_installed": shutil.which("prlimit") is not None,
        "system_python_available": Path("/usr/bin/python3").is_file(),
        "unprivileged_userns_clone": _read(
            "/proc/sys/kernel/unprivileged_userns_clone"
        ),
        "apparmor_userns_restriction": _read(
            "/proc/sys/kernel/apparmor_restrict_unprivileged_userns"
        ),
        "cgroup_v2_detected": (cg / "cgroup.controllers").is_file(),
        "cgroup_controllers": controllers.split() if controllers else [],
        "cgroup_limits_enforced_by_agentpybox": False,
        "note": "Checks are informational. Successful checks do not imply malicious-code containment.",
    }


def main():
    print(json.dumps(audit(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
