# Task 600: graftling 0.9.1 release

The user decided this release (Worldline user-decision 20261124T114043.053104+0900), and that decision also covers the push.
It is a compatible patch release. The changes since 0.9.0 are:
- 597: the printed install command and the install documentation;
- 599: a PUBLIC_API note on Retired Agents.

No public name, result, archive format or behavior changes. The wording of error messages is internal, by PUBLIC_API's preamble.
Nothing is published to PyPI or npm, and production (`.venv-runtime`) is not touched.

## Values (fixed in steps.zsh)

| name | value |
|---|---|
| graftling dev at dispatch (GBASE) | `2b4a33aef93dc45b953bd412e4d5dd61347c38ea` (597 + 599) |
| graftling main = v0.9.0 (GMAIN0) | `7b5f4e6b48ec2c502947942f5ebbb3029ecc2fc9` |
| release commit (GCOMMIT) | `e8c2e80241dff1151f2122e8957fca5598ec987b` "graftling 0.9.1 (600)": one commit on GBASE that changes 5 files (CHANGELOG, `__init__.py`, the plugin.json and the 2 package.json). Author and committer are LUOXIAO92 &lt;89069722+LUOXIAO92@users.noreply.github.com&gt;. |
| bundle | `graftling-0.9.1.bundle`, `2b4a33ae..agent/600-graftling-0.9.1`; sha256 `b5c6d530ef5f3f5324438a4f3ba6d47d0ef8bee271e4b7f53f34f2f2fe66ee12` |
| tag | annotated `v0.9.1` at GCOMMIT, with the noreply tagger; the message names 597, 599 and "compatible" |
| install (C5) | `uv tool install --managed-python "git+https://github.com/LUOXIAO92/graftling.git@v0.9.1"`, with UV_TOOL_DIR, UV_TOOL_BIN_DIR, UV_CACHE_DIR and UV_PYTHON_INSTALL_DIR under `/private/tmp/uvtool-600` |
| raw output | `<Harness>/.graphtraj/core/state/tasks/600-graftling-0-9-1-release/realhost/main-raw/` |
| scratch | `<Harness>/tmp/600` (00 creates it), `/private/tmp/uvtool-600` |

## Steps

Main runs each step as `zsh <Worktree>/scripts/adopt-600/steps.zsh <step>`, in this order: 00 → rel → B → rp → gh → C5 → done.
No step shows a dialog, needs a login, or calls Claude, Codex, Pi or DSH. Every step prints the exact next command.

| step | who | network | PASS lines (all `CHECK 600 <step> …: PASS`) |
|---|---|---|---|
| 00 | Main, read only (creates `tmp/600` and the scratch clone `tmp/600/g00.git`) | github.com (`ls-remote`) | runs under zsh; uv lists `--managed-python`; `$UVT` absent; dev = GBASE; main = GMAIN0; dev is checked out in graftling-dev and main in `graftling`, both clean; v0.9.1 absent locally and on GitHub; GitHub main = GMAIN0; GitHub dev is an ancestor of GBASE; bundle sha256, verify and head; GCOMMIT is one noreply commit on GBASE that changes exactly the 5 files; README line @v0.9.1 = C5's command |
| rel | Main | none | v0.9.1 peels to GCOMMIT; main == dev == GCOMMIT; annotated tag with the noreply tagger; tag message names 597, 599 and compatible; version at the tag is 0.9.1. STOPs, changing nothing, if dev ≠ GBASE or main ≠ GMAIN0. A rerun prints "already released". |
| B | Main, before the push | none | archive version strings 0.9.1; CHANGELOG `## 0.9.1 (compatible)` and no `## Unreleased`; wheel version strings 0.9.1 (METADATA, `__init__.py`, 3 json); console scripts exactly subagents, subagents-mcp; wheel = git archive (pkgdiff532.py); 597/599 markers present; no build/ or `__pycache__`; GraphTraj's range includes 0.9.1 (REPORT: no change needed) |
| rp | Main; needs `ADOPT600_PUSH_CONFIRMED=yes` | github.com (the user's git credentials) | remote main == v0.9.1^{} == GCOMMIT; remote dev == local dev. The push is atomic and fast-forward only, never forced. |
| gh | Main, read only | github.com | GitHub main = GCOMMIT; v0.9.1^{} = GCOMMIT; GitHub's tag object = the local tag object |
| C5 | Main | github.com, PyPI, uv's Python download | uv rc 0; `uv tool dir` = `$UVT/tools`; `__version__` and metadata 0.9.1; sys.prefix `$UVT/tools/graftling`; base interpreter uv-managed under `$UVT/python`; direct_url commit_id = GCOMMIT; `uv tool dir --bin` = `$UVT/bin`; `subagents --help` rc 0; subagents-mcp exists; USER directories and conda unchanged (593's homesnap593.py) |
| done | Main, read only | none | every step has a raw file and no CHECK failed |

Every process the steps start gets an allowlist environment: clean() passes only HOME, USER, PATH, TERM, TMPDIR and LANG. cred_guard STOPs on credential-like names.
The steps reuse two of 593's helpers by path: `scripts/adopt-593/homesnap593.py` and `pkgdiff532.py`.

## Rehearsal (`rehearse.zsh`, outputs in `rehearsal/`)

The rehearsal runs against scratch repositories under `$TMPDIR/r600`:
- a clone of `<Harness>/graftling`, with main checked out and dev in a second worktree at GBASE;
- a bare repository standing in for GitHub, with main = GMAIN0 and dev = GMAIN0, as on GitHub after 593.

It sets only these overrides: ADOPT600_G, _GDEV, _GURL, _OUT, _SCRATCH, _UVT, _NOSNAP=1, _SOURCE (C5 only) and _CLEAN_EXTRA (the sandbox's proxy variables).

Results:
- `console-stops.txt`:
  - rel with dev moved STOPs and changes nothing (no branch, tag, dev or main change).
  - rp before rel STOPs.
- `console-release.txt`:
  - 00 passes with every CHECK PASS.
  - rel releases; a second rel prints "already released".
  - B passes.
  - rp without confirmation STOPs. rp with confirmation pushes; a second rp passes again.
  - gh passes.
- `console-C5.txt`: C5 installs from `git+file://<scratch origin>@v0.9.1` and gets uv-managed CPython 3.14.7 and commit_id GCOMMIT. done reports 46 PASS and 0 FAIL.
- A check over the names the script assigns finds only clean()'s intended pass-throughs among zsh's special parameters, and no `$NAME:letter` modifier trap.

**Not rehearsed:**
- the real `<Harness>/graftling` and graftling-dev Worktree (only clones of them);
- GitHub itself: `ls-remote`, the push with the user's credentials, and uv's `git fetch` of GitHub, which the sandbox proxy refuses;
- the USER-directory and conda snapshots, because the sandbox cannot read `$HOME`;
- the `uv` that is on Main's clean PATH. The rehearsal used Miniconda's uv; 597's real run used `~/.local/bin/uv` 0.9.18.
