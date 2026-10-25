#!/bin/sh
# Task 349 real-host kit: build the candidate and an isolated project.
#
# Run from a plain user terminal (not inside a Codex/Claude/Pi/DSH Agent shell),
# so no Agent connection or Main identity is inherited:
#   /bin/bash build/349-real-host/setup.sh            # COMMIT defaults to this Worktree's HEAD
# It never reads or copies credential files; Pi, DSH and Claude keep their own logins.
set -eu

C=${C:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/349-pi-dsh-main-continuity}
COMMIT=${COMMIT:-$(git -C "$C" rev-parse HEAD)}
T=${T:-/private/tmp/graphtraj-349}
P=$T/project
V=$T/venv

# Refuse to reuse an earlier run: every observation must come from this build.
if [ -e "$T" ]; then
  echo "refusing: $T exists; move it aside first" >&2
  exit 1
fi
unset GRAPHTRAJ_CLI_CONNECTION AGENT_SWARM_CONNECTION GRAPHTRAJ_NATIVE_RUNTIME \
      GRAPHTRAJ_NATIVE_SESSION GRAPHTRAJ_NATIVE_SESSION_FILE DSH_SESSION_ID DSH_AGENT_SOURCE \
      DSH_GRAPHTRAJ_SESSION DSH_GRAPHTRAJ_SOURCE CODEX_THREAD_ID 2>/dev/null || true

mkdir -p "$T/src" "$T/dist" "$T/evidence" "$T/pi-sessions"
echo "commit: $COMMIT" | tee "$T/evidence/commit.txt"

# 1. Candidate wheels from the exact commit (both pyprojects exist at it).
git -C "$C" show "$COMMIT:src/agent_swarm/pyproject.toml" > /dev/null
git -C "$C" archive "$COMMIT" | tar -x -C "$T/src"
(cd "$T/src" && python3 -m pip wheel -q --no-deps ${PIP_FLAGS:-} -w "$T/dist" ./src/agent_swarm .)
# VENV_FLAGS/PIP_FLAGS exist only for an offline dry run; leave them unset.
python3 -m venv ${VENV_FLAGS:-} "$V"
"$V/bin/pip" install -q ${PIP_FLAGS:-} "$T"/dist/*.whl
shasum -a 256 "$T"/dist/*.whl | tee "$T/evidence/wheels.sha256"
SP=$("$V/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')

# 2. Isolated project with a resolvable member role and three synthetic Tasks:
#    901 is seeded by Claude, 911 is dispatched by Pi, 921 by DSH.
mkdir -p "$P"
cd "$P"
git init -q -b main
git commit -q --allow-empty -m init
printf 'y\n' | "$V/bin/graphtraj" setup
cat > .graphtraj/roles.yml <<'EOF'
roles:
  member: {runtime: claude, model: claude-opus-5-5, reasoning_effort: high}
role_tree: {member: {}}
EOF
for n in 901 911 921; do
  cat > "$T/task-$n.yml" <<EOF
task_id: '$n'
task_name: probe-$n
source: build/349-real-host
title: Synthetic probe $n
body: 'Synthetic canary Task for the Task 349 real-host check. Reply with the single line CANARY-$n-DONE and finish; change no files.'
dependencies: []
schema_version: 2
parent_id: null
disposition: active
replaced_by: []
retirement_reason: null
EOF
  "$V/bin/graphtraj" task register --task-file "$T/task-$n.yml"
done
"$V/bin/graphtraj" doctor | tee "$T/evidence/doctor.txt"

# 3. Claude Code Main host (seeding and the switch step).
"$V/bin/python" -m graphtraj.runtimes.claude.host configuration --write --project "$P" --claude "$(command -v claude)"

# 4. DSH Main profile overlay: the GraphTraj lifecycle plugin and the agents MCP plugin.
cat > "$T/dsh-main.patch.yml" <<EOF
- insert:
  - id: graphtraj
    name: $SP/graphtraj/runtimes/dsh/tool.mjs
  - id: agents-mcp
    name: $SP/agent_swarm/dsh/plugin.mjs
    config:
      mcpCommand: $V/bin/graphtraj-mcp
      mcpArgs: []
EOF

# 5. Launchers. Each puts the candidate's commands first on PATH and starts the
#    real host in the isolated project; nothing else is changed.
cat > "$T/claude-main.sh" <<EOF
#!/bin/sh
cd "$P" && PATH="$V/bin:\$PATH" exec claude "\$@"
EOF
cat > "$T/pi-main.sh" <<EOF
#!/bin/sh
cd "$P" && PATH="$V/bin:\$PATH" exec pi --extension "$SP/graphtraj/runtimes/pi/extension.mjs" --session-dir "$T/pi-sessions" "\$@"
EOF
# The DSH plugins resolve DSH's own packages from its real entry, not the bin symlink.
cat > "$T/dsh-main.sh" <<EOF
#!/bin/sh
cd "$P" && PATH="$V/bin:\$PATH" GRAPHTRAJ_DSH_PACKAGE="$(realpath "$(command -v dsh)")" exec dsh --profile headless --patch "$T/dsh-main.patch.yml" "\$@"
EOF
chmod +x "$T"/*.sh
(pi --version; dsh --version; claude --version; node --version) 2>&1 | tee "$T/evidence/versions.txt"
echo "ready: $P"
