# 450 real-host check

Main runs `zsh steps.zsh 00`, then `01` (which runs `02`), then `03`. The user acts only at
`00u` (folder trust), and only when `00` says the plugin is not loaded.

- 00: scratch venv from HEAD in `$HOME/graphtraj-verify-450`, isolated project, one-line model answer,
  plugin check, task 1 ready (Leader: Claude, `permission_mode: auto`, 10-minute budget).
- 01: Main dispatches the Leader. Its only Bash command starts
  `($VV/bin/python -c 'import time; time.sleep(600)' probe450-<nonce> >/dev/null 2>&1 &)`, and then it ends its turn.
  Main waits until the Leader's `claude-termination-*.yml` exists.
- 02: read only, signals nothing. Prints each record's `escaped_processes` and scans same-user argv for the tag.
  `CRITERION PASS` needs the tagged pid in `found` and `stopped`, with no tagged process alive.
- 03: full suite in the background (`--shards 6 --timeout 1500`) into `realhost/03-suite.txt` and `03-shards/`.

Output: `.graphtraj/core/state/tasks/450-orphaned-member-processes-and-hung-tests/realhost/`.
