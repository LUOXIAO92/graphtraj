#!/usr/bin/env python3
"""Produce the Graftling repository, with history, from one GraphTraj commit (Task 395).

    python3 split.py SOURCE_REPO COMMIT OUT_DIR [GIT_DIR]

GIT_DIR (optional) keeps the repository's git directory outside OUT_DIR
(``git init --separate-git-dir``), for sandboxes that refuse nested .git/config.

SOURCE_REPO is any GraphTraj checkout or git dir; COMMIT any revision in it.
OUT_DIR must not exist. The source repository is only read (a fetch from it);
its history is never rewritten.

Steps:
1. ``git init OUT_DIR`` and fetch COMMIT as ``main`` (no tags, no other refs).
2. Choose the kept paths at COMMIT: every path under ``src/graftling/`` and
   ``src/agent_swarm/`` (the name before Task 394), the Claude marketplace
   manifest ``.claude-plugin/marketplace.json``, and Graftling's tests (see
   classify_tests.py), each test with the earlier names ``git log --follow``
   finds for it under ``tests/``.
3. ``git filter-branch --index-filter --prune-empty`` on ``main`` keeps only
   those paths in every commit; commits that keep nothing are dropped. The
   original refs, reflogs and unreachable objects are then removed, so the
   repository holds only the history that would be pushed.
4. One standalone commit on top: LICENSE (Apache-2.0, unmodified text from
   overlay/LICENSE), a root README pointer, pytest.ini, .gitignore, a
   Graftling-only tests/conftest.py, the license fields in
   src/graftling/pyproject.toml and the symlink src/graftling/LICENSE ->
   ../../LICENSE so the wheel carries the licence text.

Prints the head SHA, commit count and the earliest kept commit.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OVERLAY = HERE / "overlay"
LICENSE_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
# Directories kept whole: the package under both names, and the Session format
# examples that PUBLIC_API.md and graftling.sessions.protocol cite.
SRC_PREFIXES = ("src/graftling", "src/agent_swarm", "examples/sessions")
MANIFEST = ".claude-plugin/marketplace.json"
# D1 (user, 2026-11-17): identities using the user's personal e-mail become this one.
PUBLIC_NAME, PUBLIC_EMAIL = "LUOXIAO92", "89069722+LUOXIAO92@users.noreply.github.com"
# D2 (user, 2026-11-17): a local home path in this file's history becomes a neutral one.
SANITIZED_PATH = "tests/test_dsh_official.py"
HOME_PATH = re.compile(rb"/Users/[A-Za-z0-9._\-]+/workspace/[A-Za-z0-9._\-]+")
NEUTRAL_PATH = b"/path/to/harness"
# Tests that mention graftling but test GraphTraj behaviour or need GraphTraj's
# own fixtures (installed GraphTraj wheel, GraphTraj host, GraphTraj copy of the
# review policy); they stay in GraphTraj.
GRAPHTRAJ_SIDE_TESTS = (
    "test_claude_codex_host_shutdown.py", "test_configuration_write_keeps_settings.py",
    "test_review_plugin.py", "test_failed_start_worktree.py", "test_session_extra_fields.py",
    "test_runtime_distribution.py",
    # Expects GraphTraj's installed graftling.environment entry points (GRAPHTRAJ_CLI_CONNECTION).
    "test_agents_cli.py",
)


def git(repo: Path, *args: str, env: dict | None = None, capture: bool = True) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, text=True,
                            capture_output=capture, env=env)
    return result.stdout if capture else ""


def kept_paths(out: Path) -> tuple[list[str], list[str]]:
    """Return (exact paths, current test files) to keep, from the checked-out tree."""
    listed = subprocess.run([sys.executable, str(HERE / "classify_tests.py"), str(out), *GRAPHTRAJ_SIDE_TESTS],
                            check=True, text=True, capture_output=True).stdout.split()
    # harness_isolation.py: the overlay conftest keeps tmp_path outside every Harness with it.
    exact = set(listed) | {MANIFEST, "tests/harness_isolation.py"}
    current = set(git(out, "ls-files", "tests").split())
    for test in listed:
        for old in git(out, "log", "--follow", "--name-only", "--format=", "--", test).split():
            # An earlier name another current GraphTraj test still uses is not this test's history.
            if old.startswith("tests/") and (old not in current or old in listed):
                exact.add(old)
    return sorted(exact), listed


def main() -> int:
    source, commit, out = Path(sys.argv[1]).resolve(), sys.argv[2], Path(sys.argv[3]).resolve()
    if out.exists():
        sys.exit(f"{out} exists; choose a new directory")
    import hashlib
    if hashlib.sha256((OVERLAY / "LICENSE").read_bytes()).hexdigest() != LICENSE_SHA256:
        sys.exit("overlay/LICENSE is not the canonical Apache-2.0 text")
    sha = git(source, "rev-parse", "--verify", commit + "^{commit}").strip()
    separate = [f"--separate-git-dir={Path(sys.argv[4]).resolve()}"] if len(sys.argv) > 4 else []
    subprocess.run(["git", "init", "-q", "--template=", *separate, "-b", "main", str(out)], check=True)
    git(out, "fetch", "-q", "--no-tags", "--update-head-ok", str(source), f"{sha}:refs/heads/main")
    git(out, "checkout", "-q", "main")

    exact, tests = kept_paths(out)
    patterns = Path(git(out, "rev-parse", "--absolute-git-dir").strip()) / "graftling-kept-paths"
    lines = ["\t" + re.escape(p) + "/" for p in SRC_PREFIXES] + ["\t" + re.escape(p) + "$" for p in exact]
    patterns.write_text("\n".join(lines) + "\n")
    # D2: every version of SANITIZED_PATH holding a home path gets a rewritten blob.
    sanitize = Path(git(out, "rev-parse", "--absolute-git-dir").strip()) / "graftling-sanitized-blobs"
    versions = set(git(out, "log", "--format=", "--raw", "--no-abbrev", "main", "--", SANITIZED_PATH).split())
    mapping = []
    for blob in sorted(v for v in versions if re.fullmatch(r"[0-9a-f]{40}", v) and not set(v) == {"0"}):
        content = subprocess.run(["git", "-C", str(out), "cat-file", "blob", blob], capture_output=True).stdout
        if HOME_PATH.search(content):
            new_blob = subprocess.run(["git", "-C", str(out), "hash-object", "-w", "--stdin"], check=True,
                                      capture_output=True, input=HOME_PATH.sub(NEUTRAL_PATH, content)).stdout.decode().strip()
            mapping.append(f"{blob} {new_blob}")
    sanitize.write_text("".join(line + "\n" for line in mapping))
    print(f"sanitized_blobs={len(mapping)}")
    index_filter = (
        f"git ls-files -s | grep -E -f '{patterns}' > \"$GIT_INDEX_FILE.keep\" || true; "
        "rm -f \"$GIT_INDEX_FILE.new\"; "
        "GIT_INDEX_FILE=\"$GIT_INDEX_FILE.new\" git update-index --index-info < \"$GIT_INDEX_FILE.keep\"; "
        "if [ -f \"$GIT_INDEX_FILE.new\" ]; then mv \"$GIT_INDEX_FILE.new\" \"$GIT_INDEX_FILE\"; "
        "else git read-tree --empty; fi; "
        f"old=$(git ls-files -s -- '{SANITIZED_PATH}' | cut -d' ' -f2); "
        f"new=$( [ -n \"$old\" ] && grep \"^$old \" '{sanitize}' | cut -d' ' -f2 ); "
        f"if [ -n \"$new\" ]; then git update-index --cacheinfo \"100644,$new,{SANITIZED_PATH}\"; fi"
    )
    # D1: the personal address is read here and passed only through the environment.
    personal = git(source, "config", "user.email").strip()
    if not personal or personal.endswith("users.noreply.github.com"):
        sys.exit("git config user.email of the source repository is not a personal address to rewrite")
    env_filter = (
        'if [ "$GIT_AUTHOR_EMAIL" = "$SPLIT_PERSONAL_EMAIL" ]; then '
        f'GIT_AUTHOR_NAME="{PUBLIC_NAME}"; GIT_AUTHOR_EMAIL="{PUBLIC_EMAIL}"; export GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL; fi; '
        'if [ "$GIT_COMMITTER_EMAIL" = "$SPLIT_PERSONAL_EMAIL" ]; then '
        f'GIT_COMMITTER_NAME="{PUBLIC_NAME}"; GIT_COMMITTER_EMAIL="{PUBLIC_EMAIL}"; export GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL; fi'
    )
    env = dict(os.environ, FILTER_BRANCH_SQUELCH_WARNING="1", SPLIT_PERSONAL_EMAIL=personal)
    git(out, "filter-branch", "-f", "--env-filter", env_filter, "--index-filter", index_filter,
        "--prune-empty", "--", "main", env=env)
    git(out, "update-ref", "-d", "refs/original/refs/heads/main")
    git(out, "reflog", "expire", "--expire=now", "--all")
    git(out, "gc", "-q", "--prune=now")
    git(out, "checkout", "-q", "-f", "main")
    git(out, "clean", "-q", "-fdx")

    # Standalone commit.
    for name in ("LICENSE", "README.md", "pytest.ini", ".gitignore", "tests/conftest.py"):
        target = out / name
        if target.exists():
            sys.exit(f"{name} already exists in the filtered tree; review the overlay")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(OVERLAY / name, target)
    link = out / "src/graftling/LICENSE"
    if link.exists() or link.is_symlink():
        sys.exit("src/graftling/LICENSE already exists")
    link.symlink_to("../../LICENSE")
    pyproject = out / "src/graftling/pyproject.toml"
    text = pyproject.read_text()
    if re.search(r"(?m)^license", text):
        sys.exit("src/graftling/pyproject.toml already declares a license; review it")
    text = text.replace('requires = ["setuptools>=61"]', 'requires = ["setuptools>=77"]', 1)
    text = text.replace('readme = "README.md"\n', 'readme = "README.md"\nlicense = "Apache-2.0"\nlicense-files = ["LICENSE"]\n', 1)
    if 'license = "Apache-2.0"' not in text or "setuptools>=77" not in text:
        sys.exit("could not place the license fields in src/graftling/pyproject.toml")
    pyproject.write_text(text)
    git(out, "add", "-A")
    message = (
        "Graftling as a standalone repository under the Apache License 2.0\n\n"
        "History up to here is GraphTraj's history filtered to src/agent_swarm,\n"
        f"src/graftling, the Claude marketplace manifest and Graftling's tests,\n"
        f"from GraphTraj commit {sha}.\n\n"
        "This commit adds the unmodified Apache-2.0 LICENSE, declares it in the\n"
        "package metadata (and links it into the package so the wheel carries it),\n"
        "a root README pointer, pytest.ini and a Graftling-only tests/conftest.py.\n\n"
        "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n"
    )
    identity = dict(os.environ, GIT_AUTHOR_NAME=PUBLIC_NAME, GIT_AUTHOR_EMAIL=PUBLIC_EMAIL,
                    GIT_COMMITTER_NAME=PUBLIC_NAME, GIT_COMMITTER_EMAIL=PUBLIC_EMAIL)
    git(out, "commit", "-q", "-m", message, env=identity)
    left = sum(1 for line in git(out, "log", "--format=%ae%n%ce", "main").splitlines() if line == personal)
    print(f"identities_with_personal_email={left}")
    if left:
        sys.exit("an identity with the personal e-mail is left")
    head = git(out, "rev-parse", "HEAD").strip()
    count = git(out, "rev-list", "--count", "HEAD").strip()
    first = git(out, "log", "--reverse", "--format=%h %ad %s", "--date=short", "--", "src/agent_swarm").splitlines()[0]
    print(f"source_commit={sha}\nhead={head}\ncommits={count}\nkept_tests={len(tests)}\nfirst_agent_swarm_commit={first}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
