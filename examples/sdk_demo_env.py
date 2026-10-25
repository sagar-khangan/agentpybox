from agenthaven import SandboxManager

manager = SandboxManager()

# Discover packages already available.
matches = manager.environments.find(["boto3", "pydantic"])

if matches:
    env_name = matches[0]["name"]
else:
    # This installation step should be initiated
    # by a trusted user/operator, not an untrusted agent.
    manager.create_environment(
        "python-aws",
        "input/requirements-aws.txt",
    )
    env_name = "python-aws"

# Reuse the registered environment.
with manager.sandbox(
    profile=env_name,
    ttl_seconds=300,
) as sandbox:
    result = sandbox.execute(
        "import boto3\n"
        "import pydantic\n"
        "print('boto3:', boto3.__version__)\n"
        "print('pydantic:', pydantic.__version__)\n"
    )

    print(result.stdout)
    print(result.stderr)
    print("Successful:", result.ok)

print(manager.metrics(hours=24))
