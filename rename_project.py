#!/usr/bin/env python3
"""Rename AgentPyBox to AgentPyBox throughout the project."""

import argparse
import os
from pathlib import Path

REPLACEMENTS = [
    (b"AGENT_PY_BOX", b"AGENT_PY_BOX"),
    (b"AGENT-PY-BOX", b"AGENT-PY-BOX"),
    (b"AGENTPYBOX", b"AGENTPYBOX"),
    (b"Agent_Py_Box", b"Agent_Py_Box"),
    (b"Agent-Py-Box", b"Agent-Py-Box"),
    (b"AgentPyBox", b"AgentPyBox"),
    (b"Agent PyBox", b"Agent PyBox"),
    (b"agentPyBox", b"agentPyBox"),
    (b"agent_py_box", b"agent_py_box"),
    (b"agent-py-box", b"agent-py-box"),
    (b"agent pybox", b"agent pybox"),
    (b"agentpybox", b"agentpybox"),
]

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    ".runtime",
    ".runtimes",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".tox",
    ".idea",
    ".vscode",
    "__pycache__",
    "dist",
    "build",
    "output",
    "environments",
    "node_modules",
}

EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".so",
    ".dll",
    ".exe",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".pdf",
    ".zip",
    ".gz",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".whl",
}


def replace_bytes(data):
    for old, new in REPLACEMENTS:
        data = data.replace(old, new)
    return data


def replace_name(name):
    result = name
    for old, new in REPLACEMENTS:
        result = result.replace(old.decode(), new.decode())
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually change files; otherwise preview only",
    )
    args = parser.parse_args()

    root = Path.cwd()
    files_changed = 0
    paths_renamed = 0

    # Bottom-up traversal safely renames files then directories.
    for directory, dirs, files in os.walk(root, topdown=False):
        current = Path(directory)

        relative = current.relative_to(root)

        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue

        for filename in files:
            path = current / filename

            if path.is_symlink():
                continue

            if path.suffix.lower() not in EXCLUDED_SUFFIXES:
                try:
                    data = path.read_bytes()

                    if b"\x00" not in data:
                        updated = replace_bytes(data)

                        if updated != data:
                            print(f"CONTENT: {path.relative_to(root)}")
                            files_changed += 1

                            if args.apply:
                                path.write_bytes(updated)
                except (OSError, PermissionError):
                    pass

            new_name = replace_name(filename)

            if new_name != filename:
                new_path = current / new_name
                print(
                    f"RENAME: {path.relative_to(root)} "
                    f"-> {new_path.relative_to(root)}"
                )
                paths_renamed += 1

                if args.apply:
                    if new_path.exists():
                        raise FileExistsError(new_path)
                    path.rename(new_path)

        for dirname in dirs:
            if dirname in EXCLUDED_DIRS:
                continue

            old_path = current / dirname
            new_name = replace_name(dirname)

            if new_name != dirname:
                new_path = current / new_name
                print(
                    f"RENAME DIR: {old_path.relative_to(root)} "
                    f"-> {new_path.relative_to(root)}"
                )
                paths_renamed += 1

                if args.apply:
                    if new_path.exists():
                        raise FileExistsError(new_path)
                    old_path.rename(new_path)

    print()
    print(f"Content updates: {files_changed}")
    print(f"Path renames: {paths_renamed}")
    print("Applied." if args.apply else "Dry run only.")


if __name__ == "__main__":
    main()
