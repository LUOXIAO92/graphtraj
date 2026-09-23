"""Leader-run macOS probe of public Runner access under a directory denial.

This is a diagnostic, not a substitute for Runtime-projected permission tests.
It preserves the calling process ancestry, environment and user configuration.
It never reads Session records directly or creates/resumes an Agent.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    """Record synthetic access checks and one direct-child public status query.

    Run only from the direct parent's existing execution. The output directory
    must be new. Exit 0 means the host canary checks and both status commands
    succeeded; it does not establish complete Agent isolation.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--sessions", type=Path, required=True)
    parser.add_argument("--child", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    output = arguments.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    private = output / "private"
    private.mkdir()
    denied = private / "denied.txt"
    allowed = private / "allowed.txt"
    denied.write_text("synthetic-private-canary\n", encoding="utf-8")
    allowed.write_text("synthetic-direct-canary\n", encoding="utf-8")

    # Seatbelt only adds restrictions to the caller's existing sandbox. The
    # exact descendant models an authorized report within a private directory.
    policy = output / "probe.sb"
    policy.write_text(
        '(version 1)\n(allow default)\n'
        '(deny file-read* file-write* '
        f'(subpath {json.dumps(str(private))}) '
        f'(subpath {json.dumps(str(arguments.sessions.resolve()))}))\n'
        f'(allow file-read* (literal {json.dumps(str(allowed))}))\n',
        encoding="utf-8",
    )
    sandbox = ["/usr/bin/sandbox-exec", "-f", str(policy)]
    results: list[dict[str, object]] = []

    def run(name: str, command: list[str]) -> int:
        """Retain the exact command, result and output without reading traces."""
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        (output / f"{name}.stdout").write_text(result.stdout, encoding="utf-8")
        (output / f"{name}.stderr").write_text(result.stderr, encoding="utf-8")
        results.append({
            "name": name, "command": command, "exit_code": result.returncode,
        })
        (output / "results.json").write_text(
            json.dumps(results, indent=2) + "\n", encoding="utf-8"
        )
        print(f"{name}: exit {result.returncode}", flush=True)
        return result.returncode

    read_file = [
        sys.executable, "-c",
        "from pathlib import Path; import sys; print(Path(sys.argv[1]).read_text())",
    ]
    allowed_result = run("allowed", sandbox + read_file + [str(allowed)])
    denied_result = run("denied", sandbox + read_file + [str(denied)])
    permission_denied = "PermissionError" in (output / "denied.stderr").read_text()
    if allowed_result != 0 or denied_result == 0 or not permission_denied:
        print("Host canary checks failed; do not interpret a Runner failure as isolation.")
        return 2

    status = [str(arguments.runner.resolve()), "status", arguments.child]
    if run("status-original", status) != 0:
        print("Original public status failed; inspect that error before comparing permissions.")
        return 3
    if run("status-restricted", sandbox + status) != 0:
        print("Public status failed with Session directory denied; retain the concrete error.")
        return 4
    print("Status remained available. Dispatch/send/resume and Runtime helper checks remain required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
