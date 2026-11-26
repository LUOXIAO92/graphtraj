"""Task 644 rehearsal: drive644.py's rollout parsers on recorded rollouts (args: <driver> <label>=<rollout> ...).

Prints per rollout: the shell calls (tool name and exit code read from function_call_output / exec_command_end) and
the cwd Codex recorded (its last path component only), never the rollout's other text.
"""
import importlib.util
import sys
from pathlib import Path, PureWindowsPath

spec = importlib.util.spec_from_file_location('drive644', sys.argv[1])
drive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drive)
for item in sys.argv[2:]:
    label, _, path = item.partition('=')
    records = drive.read_records(Path(path))
    calls = drive.tool_calls(records)
    cwd = drive.reported_cwd(records)
    names = sorted({PureWindowsPath(one).name for one in cwd})
    print(f'{label}: {len(records)} records; {len(calls)} shell call(s): '
          f'{[(call["tool"], call["exit_code"], call["answered"]) for call in calls]} (tool, exit code, output present); '
          f'cwd last component {names}')
