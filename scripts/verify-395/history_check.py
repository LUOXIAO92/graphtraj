#!/usr/bin/env python3
"""Scan every commit, blob, commit message and identity reachable from a repository's refs (Task 395).

    python3 history_check.py REPO [REPORT.md]

Never prints a matched value: each finding gives the pattern name, path, line
number, the first commit that holds the blob (``git log --find-object``) and,
for e-mail addresses and home paths, a masked form only.
"""
from __future__ import annotations

import collections
import re
import subprocess
import sys
from pathlib import Path

SECRET_PATTERNS = {
    "private-key-block": rb"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----",
    "aws-access-key-id": rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    "github-token": rb"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})",
    "anthropic-key": rb"\bsk-ant-[A-Za-z0-9_\-]{20,}",
    "openai-style-key": rb"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{32,}",
    "slack-token": rb"\bxox[abposr]-[A-Za-z0-9\-]{10,}",
    "google-api-key": rb"\bAIza[0-9A-Za-z_\-]{35}\b",
    "jwt": rb"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}",
    "bearer-header-literal": rb"(?i)authorization['\"]?\s*[:=]\s*['\"]?bearer\s+[A-Za-z0-9._\-]{20,}",
    "url-with-password": rb"[a-z][a-z0-9+.\-]*://[^/\s:@'\"]+:[^/\s@'\"]{6,}@",
    "secret-assignment": rb"(?i)\b[A-Za-z0-9_]*(?:api[_\-]?key|secret|token|passw(?:or)?d|credential)[A-Za-z0-9_]*['\"]?\s*[:=]\s*['\"][^'\"\s]{16,}['\"]",
}
PERSONAL_PATTERNS = {
    "email-address": rb"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}",
    "home-path": rb"/(?:Users|home)/[A-Za-z0-9._\-]+",
    "private-ipv4": rb"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b",
}
SENSITIVE_NAMES = re.compile(r"(?i)(^|/)(\.env(\..*)?|id_[rd]sa|id_ed25519|.*\.pem|.*\.p12|.*\.pfx|.*\.key|credentials(\.json)?|\.netrc|\.npmrc|\.pypirc|auth\.json)$")
GENERIC_HOME_USERS = {"user", "me", "you", "example", "runner", "alice", "bob", "name", "USER", "username"}
NOREPLY = re.compile(rb"(?i)@(?:example\.(?:com|org|net)|users\.noreply\.github\.com|anthropic\.com|localhost|test|invalid|example)\b")


def git(repo: str, *args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, input=data).stdout


def mask(value: bytes) -> str:
    text = value.decode("utf-8", "replace")
    if "@" in text:
        local, _, domain = text.partition("@")
        return f"{local[:1]}***@{domain}"
    head, _, user = text.rpartition("/")
    return f"{head}/{user[:1]}***"


def main() -> int:
    repo = sys.argv[1]
    report = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    head = git(repo, "rev-parse", "HEAD").decode().strip()
    refs = git(repo, "for-each-ref", "--format=%(refname)").decode().split()
    commits = git(repo, "rev-list", "--all").decode().split()
    objects = git(repo, "rev-list", "--objects", "--all").decode().splitlines()
    paths = {}
    for line in objects:
        sha, _, path = line.partition(" ")
        paths.setdefault(sha, set()).add(path)
    checks = git(repo, "cat-file", "--batch-check", data="\n".join(paths).encode() + b"\n").decode().splitlines()
    blobs = [c.split()[0] for c in checks if c.split()[1] == "blob"]
    findings = collections.defaultdict(list)  # (category, pattern) -> [(blob, path, line, masked)]

    def scan(text: bytes, where: tuple, patterns: dict, category: str) -> None:
        for name, pattern in patterns.items():
            for match in re.finditer(pattern, text):
                value = match.group(0)
                if name == "email-address" and NOREPLY.search(value):
                    continue
                if name == "home-path" and value.rsplit(b"/", 1)[1].decode() in GENERIC_HOME_USERS:
                    continue
                line = text.count(b"\n", 0, match.start()) + 1
                masked = mask(value) if category == "personal" else ""
                findings[(category, name)].append((*where, line, masked))

    batch = subprocess.run(["git", "-C", repo, "cat-file", "--batch"], check=True, capture_output=True,
                           input="\n".join(blobs).encode() + b"\n").stdout
    offset = 0
    total_bytes = 0
    for blob in blobs:
        header_end = batch.index(b"\n", offset)
        sha, kind, size = batch[offset:header_end].split()
        size = int(size)
        content = batch[header_end + 1: header_end + 1 + size]
        offset = header_end + 1 + size + 1
        total_bytes += size
        path = sorted(paths[blob])[0]
        scan(content, ("blob", blob, path), SECRET_PATTERNS, "secret")
        scan(content, ("blob", blob, path), PERSONAL_PATTERNS, "personal")
    sensitive_files = sorted({p for b in blobs for p in paths[b] if SENSITIVE_NAMES.search(p)})

    log = git(repo, "log", "--all", "--format=%H%x00%an%x00%ae%x00%cn%x00%ce%x00%B%x1e")
    identities = collections.Counter()
    for record in log.split(b"\x1e"):
        record = record.strip(b"\n")
        if not record:
            continue
        sha, an, ae, cn, ce, body = record.split(b"\x00", 5)
        shown = lambda e: e.decode() if NOREPLY.search(e) else mask(e)
        identities[("author", an.decode(), shown(ae))] += 1
        identities[("committer", cn.decode(), shown(ce))] += 1
        scan(body, ("message", sha.decode(), "-"), SECRET_PATTERNS, "secret")
        scan(body, ("message", sha.decode(), "-"), PERSONAL_PATTERNS, "personal")

    first_commit = {}

    def introduced(blob: str) -> str:
        if blob not in first_commit:
            out = git(repo, "log", "--all", "--reverse", "--format=%h", f"--find-object={blob}").decode().split()
            first_commit[blob] = out[0] if out else "?"
        return first_commit[blob]

    # D1: count the user's personal address (git config user.email) without printing it.
    personal = subprocess.run(["git", "-C", repo, "config", "user.email"], capture_output=True).stdout.strip()
    personal_hits = 0
    if personal and not personal.endswith(b"users.noreply.github.com"):
        personal_hits = log.count(personal) + batch.count(personal)
    lines = [
        f"# History check of {repo}",
        f"- the user's personal e-mail (git config user.email, not printed) occurs {personal_hits} time(s) in commit metadata, messages and blobs",
        "",
        f"- HEAD: `{head}`; refs: {', '.join(refs)}",
        f"- commits reachable from all refs: {len(commits)}",
        f"- distinct blobs reachable (every version of every file, not only the tip): {len(blobs)} ({total_bytes} bytes)",
        f"- commit messages scanned: {len(commits)}",
        "",
        "## Identities in commit metadata (e-mail masked)",
        "",
    ]
    lines += [f"- {role}: {name} <{email}> x{count}" for (role, name, email), count in sorted(identities.items())]
    lines += ["", "## Sensitive file names", ""]
    lines += [f"- {p}" for p in sensitive_files] or ["- none"]
    for category in ("secret", "personal"):
        lines += ["", f"## {category} patterns", ""]
        for name in (SECRET_PATTERNS if category == "secret" else PERSONAL_PATTERNS):
            hits = findings.get((category, name), [])
            lines.append(f"### {name}: {len(hits)} match(es)")
            seen = set()
            for kind, ref, path, line, masked in hits:
                key = (path, masked) if category == "personal" else (ref, path, line)
                if key in seen:
                    continue
                seen.add(key)
                where = f"commit {introduced(ref)} path {path}" if kind == "blob" else f"message of {ref[:12]}"
                lines.append(f"- {where} line {line}" + (f" `{masked}`" if masked else ""))
            lines.append("")
    text = "\n".join(lines) + "\n"
    if report:
        report.write_text(text)
    print(text if not report else f"wrote {report}: {len(commits)} commits, {len(blobs)} blobs, head {head}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
