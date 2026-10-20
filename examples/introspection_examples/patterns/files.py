"""Hand the agent a file and download the report it writes.

Uploads a contract, starts a task with it attached, waits for the run to
settle, then finds the task's output under ``tasks/<task-id>/outputs/`` and
downloads it.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run -m introspection_examples.patterns.files

Optional env:
    INTROSPECTION_RUNTIME       - runtime slug or id (default customer-agent)
    INTROSPECTION_BASE_API_URL  - CP REST API host
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient, Runner

CONTRACT = b"""# Service agreement

1. Either party may end this agreement with 30 days' written notice.
2. Fees are due within 14 days of each invoice.
"""


def review_contract(runner: Runner, contract: bytes) -> bytes | None:
    # #region docs:patterns/files/sdk-upload
    f = runner.files.upload(
        file=contract, name="contract.md", file_type="upload"
    )
    handle = runner.tasks.start(
        prompt="Review contract.md and write report.md",
        files=[{"id": str(f.id)}],
    )
    handle.text()  # waits for the run to settle
    outputs = f"tasks/{handle.run.task_id}/outputs/"
    report = next(
        (x for x in runner.files.list() if x.name.startswith(outputs)), None
    )
    data = runner.files.download(str(report.id)) if report else None
    # #endregion docs:patterns/files/sdk-upload
    return data


def main() -> None:
    load_dotenv()
    if not os.getenv("INTROSPECTION_TOKEN"):
        sys.exit("Set INTROSPECTION_TOKEN to an Introspection API key.")
    runtime = os.getenv("INTROSPECTION_RUNTIME", "customer-agent")

    client = IntrospectionClient()
    runner = client.runtimes(runtime).run(identity={"user_id": "user-4821"})
    try:
        report = review_contract(runner, CONTRACT)
        if report is None:
            print("the agent wrote no file to /workspace/outputs")
        else:
            print(report.decode("utf-8", errors="replace"))
    finally:
        runner.close()
        client.shutdown()


if __name__ == "__main__":
    main()
