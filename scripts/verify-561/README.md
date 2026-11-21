# verify-561 (graftling: agentMessages declares its own inject)

Run from this Worktree in Main's Bash: `zsh scripts/verify-561/steps.zsh <00|R|T|TB|C>`; each step prints the next
command. No step should show a native dialog. BASE=/private/tmp/gl-561.

- Candidate: graftling clone `.scratch/561/graftling` (git dir `.scratch/561/graftling.gitdir`), branch
  `agent/561-graftling-dsh-agentmessages-inject-for-new-dsh`, commit 04d5b00c75989d33e9aa16dd1c3364bb3cbfa607.
- Baseline: graftling dev 6794ce02b6210ec88837437affb8d7b525612804.
- `drv561.py`: the real entry (installed `dsh web` + graftling plugin.mjs, started by graftling's DshService;
  `agentMessages/receive`). Needs a local listener, which the Engineer sandbox refuses (`listen EPERM 127.0.0.1`).
- `probe561.mjs`: the same plugin.mjs loaded into the installed DSH packages, Gateway invoke, no listener.
- `rehearsal/output.txt`: 00 (VERIFY561_NOMODEL), R, `T tests/test_dsh_live.py`, TB, C from an empty directory in
  the Engineer sandbox; `<REH>` stands for the scratch BASE.
