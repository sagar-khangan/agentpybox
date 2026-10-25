"""Reusable, locally managed Python environments."""

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

NAME = re.compile(r"^[a-z][a-z0-9-]{0,39}$")

BUILTINS = ("python-basic", "python-data", "python-test")


def normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()


class EnvironmentRegistry:
    def __init__(self, root):
        self.root = Path(root).resolve() / "environments"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.uv = shutil.which("uv")

    def _path(self, name):
        if not NAME.fullmatch(name) or name in BUILTINS:
            raise ValueError("Invalid or reserved environment name")
        return self.root / name

    def _metadata(self, name):
        if name in BUILTINS:
            return {
                "name": name,
                "status": "ready",
                "python": "/usr/bin/python3",
                "packages": {},
                "builtin": True,
            }

        path = self._path(name)
        metadata = path / "metadata.json"

        if not metadata.is_file():
            raise ValueError(f"Environment not registered: {name}")

        data = json.loads(metadata.read_text())

        if data["status"] != "ready" or not (path / "venv" / "pyvenv.cfg").is_file():
            raise ValueError(f"Environment not ready: {name}")

        return data

    def list(self):
        items = [self._metadata(name) for name in BUILTINS]

        for path in sorted(self.root.iterdir()):
            if path.is_dir() and (path / "metadata.json").is_file():
                try:
                    items.append(self._metadata(path.name))
                except (ValueError, KeyError, json.JSONDecodeError):
                    items.append(
                        {
                            "name": path.name,
                            "status": "broken",
                        }
                    )

        return items

    def inspect(self, name):
        return self._metadata(name)

    def find(self, packages):
        wanted = {normalized(p) for p in packages}

        if not wanted:
            raise ValueError("Provide at least one package")

        return [
            env
            for env in self.list()
            if env.get("status") == "ready" and wanted <= set(env.get("packages", {}))
        ]

    def create(
        self,
        name,
        requirements,
        python="/usr/bin/python3",
    ):
        """
        Prepare a reusable virtual environment.

        Intended for trusted local operators only.
        Only simple package/version requirements are accepted.
        """
        target = self._path(name)

        if target.exists():
            raise ValueError(f"Environment already exists: {name}")

        if not self.uv:
            raise ValueError("uv executable is required")

        requirements = Path(requirements).resolve()

        if not requirements.is_file() or requirements.stat().st_size > 32 * 1024:
            raise ValueError("Requirements file missing or too large")

        lines = []

        for raw in requirements.read_text().splitlines():
            line = raw.strip()

            if not line or line.startswith("#"):
                continue

            # Disallow direct URLs, local paths, editable installs,
            # installer directives and nested requirements.
            pattern = (
                r"[A-Za-z0-9][A-Za-z0-9._-]*"
                r"(?:\s*(?:==|>=|<=|~=|>|<)\s*"
                r"[A-Za-z0-9.*+_-]+)?"
            )

            if not re.fullmatch(pattern, line):
                raise ValueError(f"Unsupported requirement: {line}")

            lines.append(line)

        if len(lines) > 40:
            raise ValueError("Too many requirements")

        target.mkdir(mode=0o700)

        try:
            saved = target / "requirements.txt"
            saved.write_text("\n".join(lines) + "\n")

            venv = target / "venv"

            subprocess.run(
                [
                    self.uv,
                    "venv",
                    "--python",
                    str(python),
                    str(venv),
                ],
                check=True,
                timeout=120,
            )

            if lines:
                subprocess.run(
                    [
                        self.uv,
                        "pip",
                        "install",
                        "--python",
                        str(venv / "bin/python"),
                        "--only-binary",
                        ":all:",
                        "--no-config",
                        "-r",
                        str(saved),
                    ],
                    check=True,
                    timeout=600,
                )

            # Read actual installed distribution metadata.
            script = (
                "import json,importlib.metadata as m;"
                "print(json.dumps({"
                "d.metadata['Name']:d.version "
                "for d in m.distributions() "
                "if d.metadata.get('Name')}))"
            )

            result = subprocess.run(
                [
                    str(venv / "bin/python"),
                    "-I",
                    "-c",
                    script,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )

            packages = {
                normalized(name): version
                for name, version in json.loads(result.stdout).items()
            }

            metadata = {
                "name": name,
                "status": "ready",
                "builtin": False,
                "python": str(python),
                "requirements_sha256": hashlib.sha256(
                    requirements.read_bytes()
                ).hexdigest(),
                "packages": packages,
            }

            (target / "metadata.json").write_text(json.dumps(metadata, indent=2))

            return metadata

        except BaseException:
            shutil.rmtree(target)
            raise

    def delete(self, name, active_names=()):
        if name in active_names:
            raise ValueError(f"Environment in use: {name}")

        target = self._path(name)

        if not target.exists():
            raise ValueError("Environment not found")

        if target.is_symlink():
            raise ValueError("Symlink environment refused")

        shutil.rmtree(target)

    def mount(self, name):
        self._metadata(name)

        if name in BUILTINS:
            return None

        return self._path(name) / "venv"
