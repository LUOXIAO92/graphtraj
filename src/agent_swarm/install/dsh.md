# agents on DSH

This makes a DeepSeek Harness (DSH) main Session the host of its child Agents, through
a DSH plugin. Back to the [README](../README.md).

## Prerequisites

- Python 3.12 or later.
- DSH 0.2.0-rc.2 or later, with a login or an API key. An older DSH, or one whose
  version cannot be read, is refused. The sources and real runs are DSH `0.2.2-alpha.2`.
- pnpm, for `dsh plugin add`, which runs pnpm in the profile directory. `--patch` does
  not need it.

## Install the wheel

In a checkout of the repository, or skip the `pip wheel` line and give `pip install`
the path of a wheel you were given:

```sh
AGENTS_VENV=/absolute/agents-venv
python3 -m venv "$AGENTS_VENV"
WHEELS="$(mktemp -d)"
"$AGENTS_VENV/bin/python" -m pip wheel --no-deps -w "$WHEELS" ./src/agent_swarm
"$AGENTS_VENV/bin/python" -m pip install "$WHEELS"/agent_swarm-*.whl
```

## Distribution: `dsh plugin add`

The installed directory `agent_swarm/dsh/` is a DSH plugin bundle named `agents-dsh`.
Install it with DSH's own plugin command, once per profile, from the agents environment
DSH should use. It is not on a public market.

```sh
DSH_PACKAGE="$("$AGENTS_VENV/bin/python" -c 'import agent_swarm.dsh, pathlib; print(pathlib.Path(agent_swarm.dsh.__file__).parent)')"
dsh plugin --profile headless add "$DSH_PACKAGE"
```

Any profile works the same way: `headless`, `web`, `tui`, `acp` or `sdk`.

> Not yet walked on a real host: `dsh plugin add` of this directory. An earlier real
> attempt failed because pnpm was missing, so the real runs used `--patch`, below.

## Local files: `--patch` for one invocation

Nothing is installed. Write a patch file that names the plugin, and pass it for this
one run:

```sh
cat > /absolute/agents-host.patch.yml <<EOF
- insert:
    - id: agents-host
      name: $DSH_PACKAGE/plugin.mjs
EOF
```

Then add `--patch /absolute/agents-host.patch.yml` to the `dsh` command below.

## Minimal configuration

`/absolute/dsh-host.json`:

```json
{"root": "/absolute/agents-data"}
```

Allowed keys: `root` (required, absolute), `dsh`, `claude`, `codex` and `pi`. Any other
key stops the start.

`config.yml` for connections and presets goes in `root`. See
[Configuration](../README.md#configuration).

## Start it

```sh
AGENT_SWARM_PYTHON="$AGENTS_VENV/bin/python" AGENT_SWARM_DSH_CONFIG=/absolute/dsh-host.json \
  env -u DEEPSEEK_BASE_URL dsh --profile headless "Your task."
```

`AGENT_SWARM_PYTHON` names the Python that has `agent-swarm`. The plugin does nothing
without `AGENT_SWARM_DSH_CONFIG`. The `env -u` concerns only this main Session's own
endpoint, which DSH takes from that variable when its profile names none. DSH children
ignore that variable.

To continue a `headless` Session:

```sh
AGENT_SWARM_PYTHON="$AGENTS_VENV/bin/python" AGENT_SWARM_DSH_CONFIG=/absolute/dsh-host.json \
  env -u DEEPSEEK_BASE_URL dsh --profile headless --session-id "<session id>" "Next task."
```

A refused start prints one `{"error": {"code", "message"}}` line, DSH's `agent/created`
handler fails with that text, and the Session has no `agents` tool.

> Not yet walked on a real host from a wheel-only install: these steps run as written
> in a clean environment. The same host ran on real DSH 0.2.2-alpha.2 with `--patch` in
> earlier checks.

## See that it worked

- The model can call the `agents` tool, through the MCP server `agents`.
- Ask it to create a Claude child that answers one word, and to `wait` for it before
  ending the task.
- A notice appears in the Session as a relay message `[agents notice from <agent> ·
  completed]` followed by the answer.
- `status` shows `last_result.notification: delivered` and `state: standby`.

## Children on other Runtimes

`create`'s `runtime` selects the driver. `dsh` and `claude` need nothing more. The
sections below set defaults for each:

```json
{
  "root": "/absolute/agents-data",
  "dsh": {"sandbox": "workspace-write", "api_key_env": "DEEPSEEK_API_KEY"},
  "claude": {"model": "claude-sonnet-5-5"},
  "codex": {
    "adapter_request": {
      "arguments": ["codex"],
      "worktree_path": "/absolute/work",
      "session_parameters": {
        "cwd": "/absolute/work",
        "model": "your-codex-model",
        "developerInstructions": "",
        "config": {
          "default_permissions": "work",
          "permissions": {
            "work": {"extends": ":workspace", "filesystem": {":workspace_roots": {".": "write"}}}
          }
        }
      }
    }
  },
  "pi": {
    "executable": "/absolute/path/to/pi",
    "provider": "deepseek",
    "model": "deepseek-flash",
    "agent_dir": "/absolute/home/.pi/agent",
    "instructions": "",
    "worktree_access": "read",
    "api_key_env": "DEEPSEEK_API_KEY",
    "sandbox_python": "/absolute/pi-sandbox/venv/bin/python",
    "sandbox_path": "/absolute/pi-sandbox/srt/node_modules/.bin:/absolute/node/bin:/absolute/ripgrep/bin:/usr/bin:/bin:/usr/sbin:/sbin"
  }
}
```

- `dsh`: the sandbox defaults to `read-only`, and the model to the parent's current one.
- `claude`: the keys of the [Claude host's `settings`](claude-code.md#minimal-configuration).
  Children default to read access. Needs Claude Code 2.1.299 or later.
- `codex`: the document [`agent_swarm.codex.host --settings`](codex.md) reads. Without
  it a Codex `create` fails with `invalid-config`.
- `pi`: the whole Pi child request, every field above but `api_key_env` is required, and
  `worktree_path` is the host's working directory. Without it a Pi `create` fails with
  `unsupported-runtime`. It needs [what a Pi child needs](../README.md#what-a-pi-child-needs),
  and the data root must lie outside the directory the Pi child works in.

Set a model at `create` to choose another one for one child.

> Not yet walked on a real host: Codex, DSH and Pi children of this host. Claude
> children have run on a real host.

## Upgrade

1. Install the new wheel into the same environment, as above.
2. If you used `dsh plugin add`, run it again for each profile, so that profile loads
   the new plugin. With `--patch`, nothing else is needed: the path does not change.
3. Start DSH with the same configuration. Reopening a Session binds a new host, which
   delivers what was held, each once.

> Not yet walked on a real host: `dsh plugin add` over an earlier install of this package.

## Limits

- A notice reaches a running parent at its next step, after the current model response
  or tool call.
- A `headless` DSH exits once its task is idle, without waiting for agents children, and
  then its children are stopped. So a parent that needs a child's answer within its task
  calls `wait` before ending it. Later notices arrive when you continue the Session.
- While DSH or the Session is stopped, nothing is delivered and notices are held. On
  resume each arrives once, unless the parent read it through `status` or `wait` first.
- A notice admitted between the `headless` runner's last Session write and its exit may
  not reach the Session file, and it stays `delivered`. This is in upstream DSH.
- An Agent the host cannot confirm stopped is named in a `stop-unconfirmed` line on
  stderr, the host exits non-zero, and the plugin writes that text to the DSH logger.
  The Session does not show it; read the state through `status` on the next host.
- `agents` calls run one at a time on this host.
- The DSH driver runs the `deepseek-official` provider only.
- `DEEPSEEK_BASE_URL` and `DEEPSEEK_SEARCH_BASE_URL` do not route a DSH child. Declare
  `base_url` on the connection or the DSH settings. With `DEEPSEEK_API_KEY` as that
  connection's key at another origin, web search goes to the same endpoint and DSH's
  Search and Fetch API provider is off. To keep official search beside a gateway, name
  the gateway's key in another variable.
- A native DSH subagent gets no host and no `agents` tool.
</content>
