"""Compare parent/helper visibility through public Runner status, without raw reads.

The Leader runs this once directly and once through an allowed native helper.
Only the presence of private status fields is returned, never their values.
This script creates no Agent and changes no permissions or Runtime settings.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import yaml


def main() -> int:
    """Print the public status outcome from the current actual process ancestry.

    Supply an existing direct child of the Leader. The Leader should receive
    Session identity fields; its native helper is a non-direct observer of that
    same child and should receive only a summary. A failed command is reported
    separately and must not be counted as a successful summary check.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--harness", type=Path, required=True)
    parser.add_argument("--child", required=True)
    arguments = parser.parse_args()
    result = subprocess.run(
        [str(arguments.runner.resolve()), "status", arguments.child],
        cwd=arguments.harness.resolve(), capture_output=True, text=True, check=False,
    )
    document = yaml.safe_load(result.stdout)
    observation: dict[str, object] = {"exit_code": result.returncode}
    if result.returncode != 0:
        error = document.get("error") if isinstance(document, dict) else None
        observation["error_code"] = error.get("code") if isinstance(error, dict) else None
        print(json.dumps(observation, sort_keys=True))
        return 2

    if not isinstance(document, dict) or not isinstance(document.get("aliases"), list):
        raise ValueError("Public status did not return its alias list.")
    records = [entry for entry in document["aliases"] if entry.get("alias") == arguments.child]
    if len(records) != 1 or "activity" not in records[0]:
        raise ValueError("Public status did not return the requested child's activity.")
    observation.update(
        activity=records[0]["activity"],
        has_session="session" in records[0],
        has_execution_id="execution_id" in records[0],
    )
    print(json.dumps(observation, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
