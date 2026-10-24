import json
import os
import re
import sys

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
SANDBOX_URL = "http://127.0.0.1:8000"

MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")
MAX_ATTEMPTS = 2

SYSTEM_PROMPT = """
You are a Python coding agent for a restricted local sandbox.

Generate Python code to solve the user's task.

Constraints:
- Python standard library only.
- No network requests.
- No pip installation.
- No subprocess or OS command execution.
- No accessing host files or credentials.
- All generated files must be in the current directory.
- Keep code short and deterministic.

Return ONLY valid Python code.
Do not use Markdown code fences.
"""


def generate_code(task, previous_code=None, error=None):
    api_key = os.environ["OPENROUTER_API_KEY"]

    prompt = f"Task:\n{task}"

    if error is not None:
        prompt += (
            f"\n\nPrevious code:\n{previous_code}"
            f"\n\nExecution error:\n{error}"
            "\n\nCorrect the code and return the complete script."
        )

    with httpx.Client(timeout=60) as client:
        response = client.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "X-OpenRouter-Title": "AgentHaven",
            },
            json={
                "model": MODEL,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            },
        )
        response.raise_for_status()

    result = response.json()
    code = result["choices"][0]["message"]["content"]

    if not isinstance(code, str) or not code.strip():
        raise ValueError("Model returned no Python code")

    code = code.strip()

    # Handle models that ignore the no-Markdown instruction.
    match = re.fullmatch(
        r"```(?:python|py)?\s*\n(.*?)\n```",
        code,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if match:
        code = match.group(1).strip()

    if len(code.encode("utf-8")) > 64 * 1024:
        raise ValueError("Generated code exceeds sandbox source limit")

    return code


def approve(code):
    print("\n" + "=" * 60)
    print("GENERATED PYTHON CODE")
    print("=" * 60)
    print(code)
    print("=" * 60)

    answer = input("\nExecute this code in AgentHaven? [y/N]: ")
    return answer.strip().lower() == "y"


def main():
    if not os.getenv("OPENROUTER_API_KEY"):
        print("Missing OPENROUTER_API_KEY environment variable")
        sys.exit(1)

    task = " ".join(sys.argv[1:]).strip()

    if not task:
        task = input("What should the agent do? ").strip()

    if not task:
        print("No task provided")
        return

    with httpx.Client(timeout=20) as client:
        # Check that AgentHaven is running.
        health = client.get(f"{SANDBOX_URL}/health")
        health.raise_for_status()
        print("AgentHaven connected")

        sandbox_id = None

        try:
            code = generate_code(task)

            for attempt in range(1, MAX_ATTEMPTS + 1):
                print(f"\n--- Attempt {attempt}/{MAX_ATTEMPTS} ---")

                if not approve(code):
                    print("Execution cancelled by user")
                    break

                # Only create the session after approval.
                if sandbox_id is None:
                    response = client.post(
                        f"{SANDBOX_URL}/sandboxes",
                        json={"ttl_seconds": 300},
                    )
                    response.raise_for_status()
                    sandbox_id = response.json()["id"]
                    print("Sandbox created:", sandbox_id)

                response = client.post(
                    f"{SANDBOX_URL}/sandboxes/{sandbox_id}/execute",
                    json={
                        "language": "python",
                        "code": code,
                    },
                )
                response.raise_for_status()
                result = response.json()

                print("\nSTDOUT:")
                print(result.get("stdout", ""))

                print("\nSTDERR:")
                print(result.get("stderr", ""))

                print("Exit code:", result["exit_code"])
                print("Duration:", result["duration_ms"], "ms")

                if result["exit_code"] == 0 and not result["timed_out"]:
                    print("\nTask executed successfully")
                    break

                if attempt == MAX_ATTEMPTS:
                    print("\nMaximum attempts reached")
                    break

                print("\nAsking OpenRouter to correct the code...")

                code = generate_code(
                    task,
                    previous_code=code,
                    error=(
                        result.get("stderr")
                        or result.get("stdout")
                        or "Execution timed out or returned a nonzero exit code."
                    )[:4000],
                )

        finally:
            if sandbox_id:
                try:
                    response = client.delete(f"{SANDBOX_URL}/sandboxes/{sandbox_id}")
                    response.raise_for_status()
                    print("\nSandbox terminated:", sandbox_id)
                except httpx.HTTPError as exc:
                    print(
                        f"\nWARNING: Sandbox cleanup failed: {exc}",
                        file=sys.stderr,
                    )


if __name__ == "__main__":
    main()
