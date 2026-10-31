#!/bin/bash
# Install, or verify, what a Pi child needs to run sandboxed: agent-sandbox and srt.
#
# Run in your own macOS Terminal (outside any Agent sandbox):
#   /bin/bash scripts/real-host/install-pi-sandbox.sh [--check] [/absolute/location]
#
# Default location: ~/agents-pi-sandbox. It holds a venv and an npm prefix, and
# nothing is written anywhere else: not Conda, the system Python, global npm or any
# project's .venv-runtime. A location inside the Harness or Conda is refused.
#
# Downloads, for this purpose only: agent-sandbox and what pip needs to build and run
# it, from GitHub and PyPI; srt and its dependencies from the npm registry. The sources
# are pinned below, in one place. It does not install ripgrep: it looks for `rg` on PATH,
# then at <location>/bin/rg, and adds its directory to the child's PATH if found. srt
# cannot start without it, so without rg this script ends NOT VERIFIED.
#
# Safe to rerun: a complete install is verified and kept, not reinstalled. Verifying
# includes starting the installed srt on a harmless command. --check verifies only and
# changes nothing outside a temporary directory it removes, so an older
# <location>/pi-sandbox.env does not make it claim success. That file is written last, with
# paths only, so that file existing means this script verified that install. Any failure
# stops before it is written, and a normal run removes an older one first.
#
# Exit status: 0 verified; 1 not verified; 2 wrong arguments or a refused location.
# Written for macOS /bin/bash 3.2. Reusable by Task 392.
set -uo pipefail

# -- The sources, in one place --------------------------------------------------
AGENT_SANDBOX_REPOSITORY=https://github.com/anonx3247/agent-sandbox.git
AGENT_SANDBOX_COMMIT=705d8801356e758819dfbbe4fba7022fe96475f8
AGENT_SANDBOX_DISTRIBUTION=agent-sandbox
AGENT_SANDBOX_VERSION=0.1.0
SRT_PACKAGE=@anthropic-ai/sandbox-runtime
SRT_VERSION=0.0.49
SRT_REGISTRY=https://registry.npmjs.org/
SRT_TARBALL=https://registry.npmjs.org/@anthropic-ai/sandbox-runtime/-/sandbox-runtime-0.0.49.tgz
SRT_INTEGRITY=sha512-t8Ggc0A7UizxMGPk/ANEH8nwnCqzNWIKpkdKgxDVUaKNMQnMzzWR6aErrqIdU03/ZP5RN6/OL/kjFOw/Vox3KQ==
# -------------------------------------------------------------------------------

PYTHON=/Users/luoxiao/miniconda3/bin/python3.13
HARNESS=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
CONDA=/Users/luoxiao/miniconda3

CHECK=
LOCATION=
for argument in "$@"; do
  case "$argument" in
    --check) CHECK=1 ;;
    /*) if [ -n "$LOCATION" ]; then echo "STOP: give one location."; exit 2; fi; LOCATION=$argument ;;
    *) echo "STOP: expected [--check] [/absolute/location], got: $argument"; exit 2 ;;
  esac
done
LOCATION=${LOCATION:-$HOME/agents-pi-sandbox}

# The location is compared after links resolve, whether or not it exists yet.
if ! RESOLVED=$("$PYTHON" -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$LOCATION"); then
  echo "STOP: cannot resolve $LOCATION with $PYTHON."
  exit 2
fi
for forbidden in "$HARNESS" "$CONDA"; do
  case "$RESOLVED/" in
    "$forbidden"/*) echo "STOP: $RESOLVED lies inside $forbidden; choose a dedicated location outside it."; exit 2 ;;
  esac
done
LOCATION=$RESOLVED
VENV=$LOCATION/venv
SRT_DIR=$LOCATION/srt
NPM_CACHE=$LOCATION/npm-cache
ENV_FILE=$LOCATION/pi-sandbox.env
SANDBOX_PYTHON=$VENV/bin/python
SRT=$SRT_DIR/node_modules/.bin/srt
LOCK=$SRT_DIR/package-lock.json

echo "location: $LOCATION"

NODE=$(command -v node || true)
if [ -z "$NODE" ]; then
  echo "STOP: node is not on PATH; srt and the host check both need it. This script does not install it."
  exit 1
fi
NODE_DIR=$(cd "$(dirname "$NODE")" && pwd)
RG=$(command -v rg || true)
if [ -z "$RG" ] && [ -x "$LOCATION/bin/rg" ]; then RG=$LOCATION/bin/rg; fi
if [ -n "$RG" ]; then
  RG_DIR=$(cd "$(dirname "$RG")" && pwd)
  echo "ripgrep: found at $RG; its directory is added to the child's PATH."
  SANDBOX_PATH=$SRT_DIR/node_modules/.bin:$NODE_DIR:$RG_DIR:/usr/bin:/bin:/usr/sbin:/sbin
else
  echo "ripgrep: rg was not found on this PATH or at $LOCATION/bin/rg. It is not installed by this script, because the approval does not cover it."
  SANDBOX_PATH=$SRT_DIR/node_modules/.bin:$NODE_DIR:/usr/bin:/bin:/usr/sbin:/sbin
fi

smoke() {
  # Start the installed srt once: is_sandbox_available() can say yes while srt cannot start.
  [ -x "$SRT" ] || { echo "FAIL: srt smoke check: no srt at $SRT"; return 1; }
  local directory status=0 output
  directory=$(mktemp -d "${TMPDIR:-/tmp}/pi-sandbox-smoke.XXXXXX") || { echo "FAIL: srt smoke check: no temporary directory"; return 1; }
  printf '%s\n' '{"network":{"allowedDomains":[],"deniedDomains":[]},"filesystem":{"denyRead":[],"allowRead":[],"allowWrite":[],"denyWrite":[]}}' > "$directory/settings.json"
  output=$(cd "$directory" && PATH=$SANDBOX_PATH perl -e 'alarm shift; exec @ARGV' 60 "$SRT" --settings "$directory/settings.json" -- /usr/bin/true 2>&1 </dev/null) || status=$?
  rm -rf "$directory"
  if [ "$status" -eq 0 ]; then
    echo "PASS: srt smoke check: srt --settings <file> -- /usr/bin/true exited 0"
    return 0
  fi
  echo "FAIL: srt smoke check: srt --settings <file> -- /usr/bin/true exited $status (142 is the 60 s limit)"
  printf '%s\n' "$output" | sed 's/^/    /'
  return 1
}

verify_packages() {
  # Print each fact and PASS/FAIL; return 0 only when all hold. Reads only.
  local failed=0
  if ! [ -x "$SANDBOX_PYTHON" ]; then
    echo "FAIL: no venv Python at $SANDBOX_PYTHON"
    failed=1
  else
    # The child's PATH, as launch.py gets it.
    if ! PATH=$SANDBOX_PATH "$SANDBOX_PYTHON" - "$AGENT_SANDBOX_DISTRIBUTION" "$AGENT_SANDBOX_VERSION" "$AGENT_SANDBOX_COMMIT" "$AGENT_SANDBOX_REPOSITORY" <<'PY'
import importlib.metadata
import json
import sys

name, version, commit, repository = sys.argv[1:5]
failed = False

def report(label, ok, seen):
    global failed
    print(f"{'PASS' if ok else 'FAIL'}: {label}: {seen}")
    failed = failed or not ok

try:
    distribution = importlib.metadata.distribution(name)
except importlib.metadata.PackageNotFoundError:
    report(f'distribution {name}', False, 'not installed')
    sys.exit(1)
report(f'{name} version {version}', distribution.version == version, distribution.version)
direct = json.loads(distribution.read_text('direct_url.json') or '{}')
seen_commit = direct.get('vcs_info', {}).get('commit_id')
report(f'{name} direct_url commit {commit}', seen_commit == commit, seen_commit)
report(f'{name} direct_url repository', direct.get('url') == repository, direct.get('url'))
try:
    from agent_sandbox import is_sandbox_available, resolve_profile, wrap_command
except Exception as error:
    report('from agent_sandbox import wrap_command, is_sandbox_available, resolve_profile', False,
           f'{type(error).__name__}: {error}')
    sys.exit(1)
report('from agent_sandbox import wrap_command, is_sandbox_available, resolve_profile', True, 'imported')
report("is_sandbox_available() with the child's PATH", is_sandbox_available() is True, is_sandbox_available())
sys.exit(1 if failed else 0)
PY
    then
      failed=1
    fi
  fi
  if ! "$PYTHON" - "$SRT_DIR" "$LOCK" "$SRT_PACKAGE" "$SRT_VERSION" "$SRT_TARBALL" "$SRT_INTEGRITY" <<'PY'
import json
import sys
from pathlib import Path

directory, lock, package, version, tarball, integrity = sys.argv[1:7]
failed = False

def report(label, ok, seen):
    global failed
    print(f"{'PASS' if ok else 'FAIL'}: {label}: {seen}")
    failed = failed or not ok

manifest = Path(directory) / 'node_modules' / package / 'package.json'
try:
    document = json.loads(manifest.read_text())
    report(f'srt package manifest name {package}', document.get('name') == package, document.get('name'))
    report(f'srt package manifest version {version}', document.get('version') == version, document.get('version'))
    packages = json.loads(Path(lock).read_text())['packages']
    entry = packages['node_modules/' + package]
except (OSError, ValueError, KeyError) as error:
    report('srt package and package-lock.json', False, f'{type(error).__name__}: {error}')
    sys.exit(1)
report('package-lock resolved', entry.get('resolved') == tarball, entry.get('resolved'))
report('package-lock integrity', entry.get('integrity') == integrity, entry.get('integrity'))
print('dependencies from package-lock.json (their versions are NOT pinned by this script, only srt itself is):')
for name, item in sorted(packages.items()):
    if name and name != 'node_modules/' + package:
        print(f"    {name.removeprefix('node_modules/')} {item.get('version')}")
sys.exit(1 if failed else 0)
PY
  then
    failed=1
  fi
  if [ -x "$SRT" ]; then
    if PATH=$SANDBOX_PATH "$SRT" --help 2>&1 | grep -q -- '--settings'; then
      echo "PASS: srt --help lists --settings"
    else
      echo "FAIL: srt --help does not list --settings"
      failed=1
    fi
    # The banner has differed from the package version; the manifest above is the version.
    echo "srt --version banner (not the package version): $(PATH=$SANDBOX_PATH "$SRT" --version 2>&1 | head -1)"
  else
    echo "FAIL: no srt at $SRT"
    failed=1
  fi
  return $failed
}

print_result() {
  echo
  echo "== Installed, and where"
  echo "agent-sandbox $AGENT_SANDBOX_VERSION @ $AGENT_SANDBOX_COMMIT in $VENV"
  echo "$SRT_PACKAGE $SRT_VERSION in $SRT_DIR ($SRT_TARBALL)"
  echo "environment file: $ENV_FILE"
  echo
  echo "== runtimes.pi lines for a host configuration"
  echo "runtimes:"
  echo "  pi:"
  echo "    sandbox_python: $SANDBOX_PYTHON"
  echo "    sandbox_path: $SANDBOX_PATH"
}

if [ -n "$CHECK" ]; then
  echo "== Verify only (nothing is changed)"
  packages=0
  verify_packages || packages=1
  if smoke && [ "$packages" -eq 0 ]; then
    echo "VERIFIED: $LOCATION"
    [ -f "$ENV_FILE" ] && echo "environment file present: $ENV_FILE" || echo "environment file absent; a normal run writes it."
    exit 0
  fi
  echo "NOT VERIFIED: $LOCATION"
  if [ -f "$ENV_FILE" ]; then
    echo "environment file $ENV_FILE exists from an earlier run and does not hold now; a normal run removes it."
  fi
  exit 1
fi

mkdir -p "$LOCATION" || exit 1
# From here until verified, no older file may claim this install is good.
rm -f "$ENV_FILE"

echo "== Verify what is already here"
if verify_packages; then
  echo "packages complete: keeping the existing install."
else
  echo "== Install"
  if ! [ -x "$SANDBOX_PYTHON" ]; then
    "$PYTHON" -m venv "$VENV" || { echo "FAIL: python -m venv"; exit 1; }
  fi
  "$SANDBOX_PYTHON" -m pip install --no-cache-dir --disable-pip-version-check \
    "git+$AGENT_SANDBOX_REPOSITORY@$AGENT_SANDBOX_COMMIT" || { echo "FAIL: pip install of agent-sandbox"; exit 1; }
  mkdir -p "$SRT_DIR" || exit 1
  # --ignore-scripts: no install script runs, so the hash check below happens before
  # anything from the package has executed. npm does not check a hash given on the side.
  npm --prefix "$SRT_DIR" install --ignore-scripts --cache "$NPM_CACHE" --no-audit --no-fund --save-exact \
    "--registry=$SRT_REGISTRY" "$SRT_PACKAGE@$SRT_VERSION" || { echo "FAIL: npm install of $SRT_PACKAGE"; exit 1; }
  echo "== Verify the install"
  if ! verify_packages; then
    echo "NOT VERIFIED: $ENV_FILE was not written. Nothing outside $LOCATION was changed."
    exit 1
  fi
fi
echo "== Start the installed srt"
if ! smoke; then
  echo "NOT VERIFIED: $ENV_FILE was not written. Nothing outside $LOCATION was changed."
  exit 1
fi

TEMPORARY=$ENV_FILE.tmp.$$
printf 'sandbox_python=%s\nsandbox_path=%s\n' "$SANDBOX_PYTHON" "$SANDBOX_PATH" > "$TEMPORARY" || exit 1
mv "$TEMPORARY" "$ENV_FILE" || exit 1
print_result
echo "VERIFIED: $LOCATION"
exit 0
