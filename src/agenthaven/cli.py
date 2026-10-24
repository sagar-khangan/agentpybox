"""Command-line interface for local, serverless AgentHaven sandboxes."""

import argparse
import json
import sys
from pathlib import Path

from . import SandboxError, SandboxManager
from .runner import PROFILES, RunnerUnavailable, available


def show(obj):
    print(json.dumps(obj, indent=2, default=str))


def build_parser():
    parser = argparse.ArgumentParser(
        prog="agenthaven", description="Local Bubblewrap sandboxes; no API server"
    )
    parser.add_argument("--root", type=Path, help="Override AgentHaven state directory")
    subs = parser.add_subparsers(dest="action", required=True)

    subs.add_parser("doctor", help="Check Bubblewrap/prlimit availability")
    subs.add_parser("profiles", help="List available Python profiles")

    p = subs.add_parser("create", help="Create persistent sandbox")
    p.add_argument("--profile", choices=PROFILES, default="python-basic")
    p.add_argument("--ttl", type=int, default=300)

    p = subs.add_parser("list", help="List sandboxes")
    p.add_argument("--status")

    p = subs.add_parser("inspect", help="Inspect sandbox")
    p.add_argument("id")

    p = subs.add_parser("execute", help="Execute code in existing sandbox")
    p.add_argument("id")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path)
    source.add_argument("--code")

    p = subs.add_parser("run", help="One-time run: upload, execute, download, clean up")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path, help="Local Python script to execute")
    source.add_argument("--code", help="Python source string to execute")
    p.add_argument("--profile", choices=PROFILES, default="python-basic")
    p.add_argument("--ttl", type=int, default=300)
    p.add_argument(
        "--upload",
        type=Path,
        action="append",
        default=[],
        metavar="LOCAL_FILE",
        help="Upload input file into sandbox; repeat for multiple inputs",
    )
    p.add_argument(
        "--download",
        action="append",
        default=[],
        metavar="SANDBOX_FILE",
        help="Download generated file; repeat for multiple artifacts",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("."),
        help="Directory for downloaded artifacts (default: current directory)",
    )

    p = subs.add_parser("put", help="Upload file into persistent sandbox")
    p.add_argument("id")
    p.add_argument("source", type=Path)
    p.add_argument("--name")

    p = subs.add_parser("get", help="Download artifact from persistent sandbox")
    p.add_argument("id")
    p.add_argument("name")
    p.add_argument("target", type=Path)

    p = subs.add_parser("files", help="List sandbox files")
    p.add_argument("id")
    p = subs.add_parser("rm", help="Remove sandbox file")
    p.add_argument("id")
    p.add_argument("name")

    p = subs.add_parser("history", help="List execution metadata")
    p.add_argument("id")
    p.add_argument("--limit", type=int, default=20)

    p = subs.add_parser("delete", help="Terminate sandbox")
    p.add_argument("id")
    subs.add_parser("cleanup", help="Expire past-due sandboxes")

    p = subs.add_parser("metrics", help="Execution summary")
    p.add_argument("--hours", type=int, default=24)
    return parser


def _code(args):
    return args.file.read_text(encoding="utf-8") if args.file else args.code


def _result(res):
    if res.stdout:
        print(res.stdout, end="")
    if res.stderr:
        print(res.stderr, end="", file=sys.stderr)
    print(
        f"\n[execution={res.id} exit={res.exit_code} "
        f"duration={res.duration_ms}ms timeout={res.timed_out}]",
        file=sys.stderr,
    )
    return 0 if res.ok else 1


def _one_time_run(manager, args):
    # Check local input files before allocating a sandbox.
    code = _code(args)
    for source in args.upload:
        if not source.is_file():
            raise SandboxError(f"Upload input does not exist: {source}")
    if len({source.name for source in args.upload}) != len(args.upload):
        raise SandboxError("Upload filenames must be unique in the sandbox")
    if len(set(args.download)) != len(args.download):
        raise SandboxError("Duplicate download filenames")

    # Download only flat filenames: prevents paths escaping output-dir.
    for name in args.download:
        if name != Path(name).name or name in (".", ".."):
            raise SandboxError(f"Download must be a flat filename: {name}")

    output_dir = args.output_dir
    if args.download:
        output_dir.mkdir(parents=True, exist_ok=True)
        if not output_dir.is_dir():
            raise SandboxError(f"Output path is not a directory: {output_dir}")

    with manager.sandbox(profile=args.profile, ttl_seconds=args.ttl) as sandbox:
        print(f"Sandbox created: {sandbox.id}", file=sys.stderr)
        for source in args.upload:
            sandbox.upload(source)
            print(f"Uploaded: {source.name}", file=sys.stderr)

        result = sandbox.execute(code)
        status = _result(result)

        # Attempt artifact retrieval even if script failed, useful for debugging.
        for name in args.download:
            target = output_dir / name
            try:
                sandbox.download(name, target)
            except (SandboxError, OSError) as exc:
                print(f"Download failed for {name}: {exc}", file=sys.stderr)
                status = 1
            else:
                print(f"Downloaded: {target}", file=sys.stderr)

    print(f"Sandbox terminated: {sandbox.id}", file=sys.stderr)
    return status


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.action == "doctor":
            show(
                {
                    "ready": available(),
                    "requires": ["Linux", "bubblewrap", "prlimit", "/usr/bin/python3"],
                }
            )
            return 0 if available() else 1
        if args.action == "profiles":
            show(PROFILES)
            return 0

        manager = SandboxManager(root=args.root)
        if args.action == "create":
            show(manager.create(args.profile, args.ttl).info)
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
    except (SandboxError, RunnerUnavailable, OSError, ValueError, UnicodeError) as exc:
        print(f"AgentHaven: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
