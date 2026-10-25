import pytest

from agentpybox import SandboxManager


def test_registry_empty_requirements(tmp_path):
    manager = SandboxManager(tmp_path / "state")

    requirements = tmp_path / "requirements.txt"
    requirements.write_text("# No dependencies\n")

    info = manager.create_environment(
        "example",
        requirements,
    )

    assert info["status"] == "ready"

    registered = manager.environments.inspect("example")
    assert registered["packages"] == {}

    matches = manager.environments.find(["boto3"])
    assert "example" not in [env["name"] for env in matches]

    sandbox = manager.create("example")

    with pytest.raises(ValueError):
        manager.delete_environment("example")

    sandbox.terminate()

    manager.delete_environment("example")

    names = [env["name"] for env in manager.environments.list()]

    assert "example" not in names


def test_requirements_validation(tmp_path):
    manager = SandboxManager(tmp_path / "state")

    requirements = tmp_path / "requirements.txt"
    requirements.write_text("-e .\n")

    with pytest.raises(ValueError):
        manager.create_environment(
            "bad",
            requirements,
        )
