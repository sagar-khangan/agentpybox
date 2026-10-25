"""OpenRouter coding agent using the AgentPyBox Python SDK.

No FastAPI, HTTP sandbox service, LangChain or LangGraph required.

Usage:
    uv run python examples/openrouter_agent.py \
        "Calculate the first 20 Fibonacci numbers"

    uv run python examples/openrouter_agent.py \
        --env python-pandas \
        --upload input/sales.csv \
        --download report.csv \
        --output-dir output \
        "Analyze sales.csv and write report.csv"
"""

import argparse
import os
import re
import sys
from pathlib import Path

import httpx

from agentpybox import SandboxManager

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

DEFAULT_MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "openrouter/free",
)

MAX_SOURCE_BYTES = 64 * 1024

SYSTEM_PROMPT = """
You are a Python coding assistant.

Generate Python code that solves the user's task.

Execution environment:
- Python runs inside an isolated AgentPyBox sandbox.
- No network access during sandbox execution.
- No pip installation inside the sandbox.
- No subprocess or shell commands.
- Read input files from the current working directory.
- Write generated artifacts into the current working directory.
- Use only packages available in the selected environment.
- Never attempt to access host credentials or private files.
- Keep code concise and deterministic.
- Do not request elevated privileges or change sandbox settings.

Return only complete executable Python code.
Do not include Markdown fences or explanations.
"""


def parse_args():
    parser = argparse.ArgumentParser(
        description="OpenRouter agent powered by AgentPyBox"
    )

    parser.add_argument(
        "task",
        nargs="*",
        help="Natural-language task",
    )

    parser.add_argument(
        "--env",
        default="python-basic",
        help="Registered AgentPyBox environment",
    )

    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="OpenRouter model ID",
    )

    parser.add_argument(
        "--upload",
        action="append",
        type=Path,
        default=[],
        help="Local file to upload; repeatable",
    )

    parser.add_argument(
        "--download",
        action="append",
        default=[],
        help="Sandbox artifact to download; repeatable",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
    )

    parser.add_argument(
        "--attempts",
        type=int,
        default=2,
        help="Maximum code generation/execution attempts",
    )

    parser.add_argument(
        "--ttl",
        type=int,
        default=300,
        help="Sandbox lifetime in seconds",
    )

    parser.add_argument(
        "--list-envs",
        action="store_true",
        help="List registered environments and exit",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Auto-approve generated code and retries",
    )

    return parser.parse_args()


def print_environments(manager):
    print("\nAvailable AgentPyBox environments:\n")

    for env in manager.environments.list():
        print(f"- {env['name']} [{env.get('status', 'unknown')}]")

        packages = env.get("packages", {})

        if packages:
            print(
                "  Packages: "
                + ", ".join(
                    f"{name}=={version}" for name, version in sorted(packages.items())
                )
            )
        else:
            print("  Packages: standard library")


def generate_code(
    client,
    task,
    model,
    environment,
    files,
    previous_code=None,
    error=None,
):
    api_key = os.environ["OPENROUTER_API_KEY"]

    packages = environment.get("packages", {})

    package_text = (
        ", ".join(f"{name}=={version}" for name, version in sorted(packages.items()))
        if packages
        else "Python standard library only"
    )

    prompt = (
        f"Task:\n{task}\n\n"
        f"Available packages:\n{package_text}\n\n"
        f"Input files:\n"
        f"{', '.join(files) if files else 'None'}\n"
    )

    if error is not None:
        prompt += (
            "\nPrevious code:\n"
            f"{previous_code}\n\n"
            "Execution error:\n"
            f"{error[:4000]}\n\n"
            "Fix the code and return the complete corrected script."
        )

    response = client.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-OpenRouter-Title": "AgentPyBox",
        },
        json={
            "model": model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        },
    )

    response.raise_for_status()

    data = response.json()
    code = data["choices"][0]["message"]["content"]

    if not isinstance(code, str) or not code.strip():
        raise ValueError("OpenRouter returned no Python code")

    code = code.strip()

    # Strip surrounding Markdown fences when present.
    match = re.fullmatch(
        r"```(?:python|py)?[ \t]*\n(.*?)\n```",
        code,
        flags=re.DOTALL | re.IGNORECASE,
    )

    if match:
        code = match.group(1).strip()

    if len(code.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError("Generated Python exceeds 64 KiB")

    return code


def approve_execution(code, auto_approve=False):
    print("\n" + "=" * 65)
    print("GENERATED PYTHON")
    print("=" * 65)
    print(code)
    print("=" * 65)

    if auto_approve:
        print("\n[AUTO-APPROVED] Executing in AgentPyBox")
        return True

    answer = input("\nApprove execution inside AgentPyBox? [y/N]: ")
    return answer.strip().lower() in ("y", "yes")


def validate_files(args):
    for source in args.upload:
        if not source.is_file():
            raise FileNotFoundError(f"Input file not found: {source}")

    upload_names = [source.name for source in args.upload]

    if len(upload_names) != len(set(upload_names)):
        raise ValueError("Uploaded files must have unique basenames")

    for name in args.download:
        if (
            Path(name).name != name
            or name in (".", "..")
            or name.startswith("agentpybox_")
        ):
            raise ValueError(f"Invalid artifact filename: {name}")

    return upload_names


def download_artifacts(sandbox, names, output_dir):
    if not names:
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    for name in names:
        destination = output_dir / name

        try:
            sandbox.download(name, destination)
            print(f"[ARTIFACT] {destination}")
        except (OSError, ValueError, RuntimeError) as exc:
            print(
                f"[DOWNLOAD FAILED] {name}: {exc}",
                file=sys.stderr,
            )


def run_agent(args):
    if not os.getenv("OPENROUTER_API_KEY"):
        raise RuntimeError("OPENROUTER_API_KEY environment variable is missing")

    if not 1 <= args.attempts <= 5:
        raise ValueError("--attempts must be between 1 and 5")

    manager = SandboxManager()

    environment = manager.environments.inspect(args.env)

    if environment.get("status") != "ready":
        raise RuntimeError(f"Environment is not ready: {args.env}")

    filenames = validate_files(args)

    task = " ".join(args.task).strip()

    if not task:
        task = input("What should the agent do? ").strip()

    if not task:
        raise ValueError("Task cannot be empty")

    print(f"\nEnvironment: {args.env}")
    print(f"Model: {args.model}")
    print(f"Task: {task}")

    # OpenRouter HTTP is called by the host-side agent.
    # Generated code executes separately inside AgentPyBox.
    with httpx.Client(timeout=60) as client:
        code = generate_code(
            client,
            task,
            args.model,
            environment,
            filenames,
        )

        # Create a sandbox only after first approval.
        sandbox_context = None
        sandbox = None

        try:
            previous_error = None

            for attempt in range(1, args.attempts + 1):
                print(f"\nAttempt {attempt}/{args.attempts}")

                if not approve_execution(code, auto_approve=args.yes):
                    print("Execution declined.")
                    return 1

                if sandbox is None:
                    sandbox_context = manager.sandbox(
                        profile=args.env,
                        ttl_seconds=args.ttl,
                    )

                    sandbox = sandbox_context.__enter__()

                    print(f"[SANDBOX CREATED] {sandbox.id}")

                    for source in args.upload:
                        sandbox.upload(source)
                        print(f"[UPLOADED] {source.name}")

                result = sandbox.execute(code)

                print("\n--- STDOUT ---")
                print(result.stdout or "(empty)")

                print("\n--- STDERR ---")
                print(result.stderr or "(empty)")

                print("\n--- EXECUTION METRICS ---")
                print(f"ID: {result.id}")
                print(f"Exit code: {result.exit_code}")
                print(f"Duration: {result.duration_ms} ms")
                print(f"Timed out: {result.timed_out}")
                print(f"Truncated: {result.truncated}")

                if result.ok:
                    print("\nExecution completed successfully.")

                    download_artifacts(
                        sandbox,
                        args.download,
                        args.output_dir,
                    )

                    print(f"History records: {len(sandbox.history())}")

                    return 0

                previous_error = (
                    result.stderr or result.stdout or "Execution failed or timed out."
                )

                if attempt == args.attempts:
                    print("\nMaximum attempts reached.")

                    download_artifacts(
                        sandbox,
                        args.download,
                        args.output_dir,
                    )

                    return 1

                print("\nRequesting corrected code from OpenRouter...")

                code = generate_code(
                    client,
                    task,
                    args.model,
                    environment,
                    filenames,
                    previous_code=code,
                    error=previous_error,
                )

            return 1

        finally:
            if sandbox_context is not None:
                sandbox_context.__exit__(None, None, None)

                if sandbox is not None:
                    print(f"\n[SANDBOX TERMINATED] {sandbox.id}")

            print("\nAgentPyBox metrics:")
            print(manager.metrics(hours=24))


def main():
    args = parse_args()

    try:
        if args.list_envs:
            print_environments(SandboxManager())
            return 0

        return run_agent(args)

    except (
        RuntimeError,
        ValueError,
        OSError,
        httpx.HTTPError,
        KeyError,
        IndexError,
    ) as exc:
        print(f"Agent error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
