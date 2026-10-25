"""AgentPyBox CLI — local sandbox and environment registry."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import SandboxError, SandboxManager
from .runner import PROFILES, RunnerUnavailable, available


def show(obj):
    print(json.dumps(obj, indent=2, default=str))


def build_parser():
    parser = argparse.ArgumentParser(
        prog="agentpybox",
        description="Dockerless local Python sandboxes",
    )

    parser.add_argument(
        "--root",
        type=Path,
        help="Override AgentPyBox state directory",
    )

    subs = parser.add_subparsers(
        dest="action",
        required=True,
    )

    subs.add_parser("doctor")
    subs.add_parser("profiles")

    p = subs.add_parser("create")
    p.add_argument(
        "--profile",
        "--env",
        dest="profile",
        default="python-basic",
    )
    p.add_argument("--ttl", type=int, default=300)

    p = subs.add_parser("list")
    p.add_argument("--status")

    p = subs.add_parser("inspect")
    p.add_argument("id")

    p = subs.add_parser("execute")
    p.add_argument("id")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path)
    source.add_argument("--code")

    p = subs.add_parser("run")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path)
    source.add_argument("--code")

    p.add_argument(
        "--profile",
        "--env",
        dest="profile",
        default="python-basic",
    )
    p.add_argument("--ttl", type=int, default=300)
    p.add_argument(
        "--upload",
        type=Path,
        action="append",
        default=[],
    )
    p.add_argument(
        "--download",
        action="append",
        default=[],
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("."),
    )

    p = subs.add_parser("put")
    p.add_argument("id")
    p.add_argument("source", type=Path)
    p.add_argument("--name")

    p = subs.add_parser("get")
    p.add_argument("id")
    p.add_argument("name")
    p.add_argument("target", type=Path)

    p = subs.add_parser("files")
    p.add_argument("id")

    p = subs.add_parser("rm")
    p.add_argument("id")
    p.add_argument("name")

    p = subs.add_parser("history")
    p.add_argument("id")
    p.add_argument("--limit", type=int, default=20)

    p = subs.add_parser("delete")
    p.add_argument("id")

    subs.add_parser("cleanup")

    p = subs.add_parser("metrics")
    p.add_argument("--hours", type=int, default=24)

    # Environment registry
    env = subs.add_parser(
        "env",
        help="Manage registered Python environments",
    )

    subenv = env.add_subparsers(
        dest="env_action",
        required=True,
    )

    e = subenv.add_parser("create")
    e.add_argument("name")
    e.add_argument(
        "--requirements",
        type=Path,
        required=True,
    )
    e.add_argument(
        "--python",
        default="/usr/bin/python3",
    )

    subenv.add_parser("list")

    e = subenv.add_parser("inspect")
    e.add_argument("name")

    e = subenv.add_parser("find")
    e.add_argument(
        "--package",
        action="append",
        required=True,
    )

    e = subenv.add_parser("delete")
    e.add_argument("name")

    return parser


def _code(args):
    if args.file:
        return args.file.read_text(encoding="utf-8")
    return args.code


def _result(result):
    if result.stdout:
        print(result.stdout, end="")

    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)

    print(
        f"\n[execution={result.id} "
        f"exit={result.exit_code} "
        f"duration={result.duration_ms}ms "
        f"timeout={result.timed_out}]",
        file=sys.stderr,
    )

    return 0 if result.ok else 1


def _one_time_run(manager, args):
    code = _code(args)

    for source in args.upload:
        if not source.is_file():
            raise SandboxError(f"Upload input does not exist: {source}")

    names = [source.name for source in args.upload]

    if len(set(names)) != len(names):
        raise SandboxError("Upload filenames must be unique")

    if len(set(args.download)) != len(args.download):
        raise SandboxError("Duplicate download filenames")

    for name in args.download:
        if name != Path(name).name or name in (".", ".."):
            raise SandboxError(f"Download must be a flat filename: {name}")

    output_dir = args.output_dir

    if args.download:
        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        if not output_dir.is_dir():
            raise SandboxError("Output path is not a directory")

    with manager.sandbox(
        profile=args.profile,
        ttl_seconds=args.ttl,
    ) as sandbox:
        print(
            f"Sandbox created: {sandbox.id}",
            file=sys.stderr,
        )

        for source in args.upload:
            sandbox.upload(source)
            print(
                f"Uploaded: {source.name}",
                file=sys.stderr,
            )

        result = sandbox.execute(code)
        status = _result(result)

        for name in args.download:
            target = output_dir / name

            try:
                sandbox.download(name, target)

            except (SandboxError, OSError) as exc:
                print(
                    f"Download failed for {name}: {exc}",
                    file=sys.stderr,
                )
                status = 1

            else:
                print(
                    f"Downloaded: {target}",
                    file=sys.stderr,
                )

    print(
        f"Sandbox terminated: {sandbox.id}",
        file=sys.stderr,
    )

    return status


def main(argv=None):
    args = build_parser().parse_args(argv)

    try:
        if args.action == "doctor":
            show(
                {
                    "ready": available(),
                    "requires": [
                        "Linux",
                        "bubblewrap",
                        "prlimit",
                        "/usr/bin/python3",
                    ],
                }
            )
            return 0 if available() else 1

        if args.action == "profiles":
            show(PROFILES)
            return 0

        manager = SandboxManager(root=args.root)

        # Environment registry operations
        if args.action == "env":
            registry = manager.environments

            if args.env_action == "create":
                show(
                    manager.create_environment(
                        args.name,
                        args.requirements,
                        args.python,
                    )
                )

            elif args.env_action == "list":
                show(registry.list())

            elif args.env_action == "inspect":
                show(registry.inspect(args.name))

            elif args.env_action == "find":
                show(registry.find(args.package))

            elif args.env_action == "delete":
                manager.delete_environment(args.name)
                print("Environment deleted")

            return 0

        if args.action == "create":
            show(
                manager.create(
                    args.profile,
                    args.ttl,
                ).info
            )

        elif args.action == "list":
            show(manager.list(args.status))

        elif args.action == "inspect":
            show(manager.get(args.id).info)

        elif args.action == "execute":
            return _result(manager.get(args.id).execute(_code(args)))

        elif args.action == "run":
            return _one_time_run(manager, args)

        elif args.action == "put":
            manager.get(args.id).upload(args.source, args.name)
            print("Uploaded")

        elif args.action == "get":
            manager.get(args.id).download(args.name, args.target)
            print(f"Saved {args.target}")

        elif args.action == "files":
            show(manager.get(args.id).files())

        elif args.action == "rm":
            manager.get(args.id).delete_file(args.name)
            print("Deleted")

        elif args.action == "history":
            show(manager.get(args.id).history(args.limit))

        elif args.action == "delete":
            show(manager.get(args.id).terminate())

        elif args.action == "cleanup":
            show({"expired": manager.cleanup()})

        elif args.action == "metrics":
            show(manager.metrics(args.hours))

        return 0

    except (
        SandboxError,
        RunnerUnavailable,
        OSError,
        ValueError,
        UnicodeError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        print(
            f"AgentPyBox: {exc}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
