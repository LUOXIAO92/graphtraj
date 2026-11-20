"""Task 535 Vb/V: SessionStart hook of the isolated project — GraphTraj's Main claim for the interactive Main ONLY.

usage (hooks.json): <venv python> -I main_start535.py      (native SessionStart event on stdin)

Why: the Main receives a pushed notice only while it is the project's current Main (agents.py _main_notice:
current_main + recorded_by_main), and for Codex only GraphTraj's SessionStart hook (stop_hook.py bind_session)
records that claim. But a Task-free agents child is `codex exec` in the same project: it runs the same project hook,
session_entry.session_source classifies source 'exec' as 'main', and the child became the current Main, so the
notice went to its ended thread (Vb try 1, pre-existing product defect reported by the Leader; not fixed by 535).
So this wrapper returns {} only when the transcript's session_meta source is 'exec' (the agents child) and passes
every other SessionStart to graphtraj.runtimes.codex.stop_hook: there is no real-host evidence of which source the
interactive TUI records ('cli', or 'appServer'/'vscode' through the shared app-server), and stop_hook itself still
refuses unknown sources. Stop's completion checker and SessionEnd are not
installed: 535 shows messages, not the completion check.
"""
import json
import subprocess
import sys


def source(transcript: object) -> object:
    """Return session_meta.payload.source of a Codex rollout, or None."""
    try:
        with open(str(transcript), encoding='utf-8') as stream:
            for line in stream:
                record = json.loads(line)
                if record.get('type') == 'session_meta':
                    return (record.get('payload') or {}).get('source')
    except (OSError, ValueError, TypeError):
        return None
    return None


def main() -> int:
    raw = sys.stdin.read()
    event = json.loads(raw)
    if event.get('hook_event_name') != 'SessionStart' or source(event.get('transcript_path')) == 'exec':
        print(json.dumps({}))
        return 0
    return subprocess.run([sys.executable, '-m', 'graphtraj.runtimes.codex.stop_hook'], input=raw, text=True).returncode


if __name__ == '__main__':
    sys.exit(main())
