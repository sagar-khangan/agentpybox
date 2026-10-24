import shutil

import pytest

from agenthaven import SandboxManager
from agenthaven.runner import available


@pytest.mark.skipif(not available(), reason="Requires working Bubblewrap/prlimit")
def test_actual_bubblewrap(tmp_path):
    manager = SandboxManager(tmp_path)
    with manager.sandbox() as box:
        result = box.execute("print(2 + 3)")
        if result.exit_code != 0 and "Operation not permitted" in result.stderr:
            pytest.skip("Host AppArmor/user namespaces prevent bwrap")
        assert result.ok, result.stderr
        assert result.stdout.strip() == "5"
