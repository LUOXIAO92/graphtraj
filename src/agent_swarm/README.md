# agents

`agents` lets the main Agent of Claude Code, Codex, Pi or DeepSeek Harness (DSH)
start and control child Agents through one tool. A child can run on any of those
four Runtimes and keeps its own native Session there. It needs no project, Task or
Git repository, and no GraphTraj installation.

The distribution is called `agent-swarm`. It installs two commands, `agents` and
`agents-mcp`, and the Python package `agent_swarm`.

- [`PUBLIC_API.md`](PUBLIC_API.md): the stable interface and the version rules.
- [`CHANGELOG.md`](CHANGELOG.md): what changed in each version.
- Host notes: [Claude Code](install/claude-code.md), [Codex](install/codex.md),
  [Pi](install/pi.md), [DSH](install/dsh.md).

The wheel contains all of these files beside the code.

## How it works

Your main Agent runs inside a **host**: Claude Code, Codex, Pi or DSH with agents
attached. The host owns the children and answers the `agents` tool. Children report
back to the parent that created them.

The `agents` command and the `agents-mcp` server only forward a request to the host
that owns the calling process. Run from a plain shell, or registered by hand in
another MCP client, every request fails with `authority-denied`, including
`discover`. So attaching a host is the first step, and each host registers the
`agents` tool for you.

## Install

`agent-swarm` is not on PyPI and no version has been published. Build the wheel from
a checkout, or use a wheel you were given, and install it alone in a dedicated
environment with Python 3.12 or later. Its only dependencies are PyYAML and
websockets.

```sh
AGENTS_VENV=/absolute/agents-venv
python3 -m venv "$AGENTS_VENV"

# In a checkout of the repository. The new directory holds exactly one wheel.
WHEELS="$(mktemp -d)"
"$AGENTS_VENV/bin/python" -m pip wheel --no-deps -w "$WHEELS" ./src/agent_swarm
"$AGENTS_VENV/bin/python" -m pip install "$WHEELS"/agent_swarm-*.whl

"$AGENTS_VENV/bin/agents" --help
```

With a wheel you were given, run only the `pip install` line with its path.

Use this environment's Python for every `python -m agent_swarm...` command in these
documents. Install and log in to each Runtime separately; agents never copies
credentials. Then follow the note for the host you use:

| Your main Agent runs in | Note | How the host is delivered |
| --- | --- | --- |
| Claude Code | [install/claude-code.md](install/claude-code.md) | Plugin files generated into your project. No marketplace package exists today |
| Codex | [install/codex.md](install/codex.md) | A command that runs a headless parent. No plugin |
| Pi | [install/pi.md](install/pi.md) | `pi install` of the installed package directory, or `-e` for one invocation |
| DSH | [install/dsh.md](install/dsh.md) | `dsh plugin add` of the installed package directory, or `--patch` for one invocation |

## Use the tool

Ask your main Agent to use the `agents` tool. It takes three actions: `discover`
lists the features, `describe` gives one feature's input, and `execute` runs it.

```json
{"action": "execute", "feature": "create",
 "arguments": {"runtime": "codex", "instruction": "Summarize README.md.",
               "name": "reader", "model": "your-model", "reasoning_effort": "low"}}
```

| Feature | What it does |
| --- | --- |
| `create` | Starts a child. Requires `runtime` and `instruction`. Optional: `name`, `preset`, `model`, `reasoning_effort`, `workspace`, `extra_fields`, and `configuration`, which every independent host refuses with `invalid-config` |
| `status` | Shows one child, or without `agent` every child you can see |
| `wait` | Waits for a child, up to the `timeout_seconds` you must give. Ends early on an unanswered request |
| `send` | Sends a message to a child; continues it if it is in standby |
| `interrupt` | Stops a child's current work |
| `resume` | Continues a child in its native Session; needs `message` in standby |
| `requests`, `reply` | Read a child's permission requests and answer each once |
| `retire` | Ends a child for good |
| `ask_parent` | Called by a child: asks its parent to decide something or grant resources, and waits for the answer |

`model` must be a known candidate, and agents never silently replaces it. When a
Runtime answers with another model, as with a safeguard fallback, the child ends
`failed` with `RUNTIME_REQUEST_FAILED`, and `last_result.error` names the requested
model, the observed model and the reason. Every other code is in
[`PUBLIC_API.md`](PUBLIC_API.md) 1.2.

Inside a host, a process the host started can also call the same request as
`agents '{"action":"discover"}'`, which prints one JSON document.

## Configuration

agents reads one optional file, `config.yml`, in its data root, and native login
state. It reads no other product's configuration.

| Host | Data root |
| --- | --- |
| Claude Code | `root` in `.agents-control/claude-host.json`, by default `<project>/.agents-control` |
| Codex | the `--directory` you pass |
| Pi, DSH | `root` in the host's JSON configuration file |

Reading is strict: an unknown or repeated field or a wrong type stops the read, and
the message names the file and line. Each host also checks every declared connection
when it starts, so a Runtime that has no driver in that host, is not installed or is
not logged in stops the start with its own code.

### Connections

A connection says how to reach a Runtime. Without one, a child uses the host's
settings and the Runtime's own login.

```yaml
connections:
  work-claude:
    runtime: claude
    models:
      - claude-opus-5-5
      - id: claude-sonnet-5-5
        supported_efforts: [low, high]
  deepseek-dsh:
    runtime: dsh
    provider: deepseek-official
    api_key_env: DEEPSEEK_API_KEY
```

`runtime` is required: `claude`, `codex`, `pi` or `dsh`. Optional: `home` (the native
home), `provider`, `base_url`, `api_key_env` (the name of an environment variable,
never a key), `review`, and `models` (without it, agents asks the Runtime, which can
make `create` take up to about 30 seconds).

If several connections declare one Runtime, `create` needs a preset that selects one,
else it fails with `ambiguous-connection`.

### Presets

A preset names a choice you reuse. `create` selects it with `preset` and still gives
`runtime`.

```yaml
connections:
  work-claude:
    runtime: claude
presets:
  careful:
    connection: work-claude
    model: claude-opus-5-5
    reasoning_effort: high
  quick-codex:
    runtime: codex
    reasoning_effort: low
```

A preset names exactly one of `connection` and `runtime`. An explicit `model` or
`reasoning_effort` on `create` must equal the preset's; a different value is an
error, not an override.

### Archive

```yaml
save_normalized_sessions: true
backfill_history: false
```

With `save_normalized_sessions: true`, every execution of every Runtime writes its
normalized Session to `<data root>/sessions/<sha256 of the Session ID>/session.jsonl`.
The default is `false`. Switching it back stops later saves and keeps what was
written. The format is in [`PUBLIC_API.md`](PUBLIC_API.md) 1.5, and `read_session`
reads it.

### Review connections

Where a Runtime's own approval is missing or unusable, for example through a
third-party provider, declare a reviewer on the connection. agents does not detect
this for you: `review` is your statement that native approval cannot be relied on.
A connection without it keeps native approval and no reviewer ever runs.

```yaml
connections:
  gateway-claude:
    runtime: claude
    review: local-review
  gateway-pi:
    runtime: pi
    review: own-script
reviewers:
  local-review:
    base_url: http://127.0.0.1:1234/v1
    model: tuned-reviewer
    timeout_seconds: 20
  own-script:
    command: [/absolute/reviewer, --strict]
    timeout_seconds: 30
```

A reviewer is either a chat completions endpoint (`base_url`, `model`, optional
`api_key_env`, `json_mode`, `timeout_seconds`) or a local process (`command`, optional
`timeout_seconds`). It answers with `{"decision": "allow" | "deny" | "escalate",
"reason": "..."}`. Only `allow` lets the call run. Anything else, including a bad
answer or a failure, goes to the direct parent.

`create` calls the reviewer once with a harmless request. If that fails, `create`
fails at once with `review-unavailable` and the cause, and no Agent is recorded. The
reviewer never defaults to the child's own provider.

### What a Pi child needs

A Pi child always runs in a native sandbox, so its host must reach four things beyond
Pi. The wheel does not install them:

| Needed | Where it comes from |
| --- | --- |
| A Python that can import `agent_sandbox` (setting `sandbox_python`) | `agent-sandbox` 0.1.0, commit `705d8801356e758819dfbbe4fba7022fe96475f8` of `https://github.com/anonx3247/agent-sandbox.git` |
| `srt` on the child's PATH (setting `sandbox_path`) | npm package `@anthropic-ai/sandbox-runtime` 0.0.49 |
| `node` on the child's PATH | Node.js |
| `rg` on the child's PATH | ripgrep. `srt` does not start without it |

```sh
PI_SANDBOX=/absolute/pi-sandbox
python3 -m venv "$PI_SANDBOX/venv"
"$PI_SANDBOX/venv/bin/python" -m pip install \
  "git+https://github.com/anonx3247/agent-sandbox.git@705d8801356e758819dfbbe4fba7022fe96475f8"
npm --prefix "$PI_SANDBOX/srt" install --ignore-scripts --save-exact \
  @anthropic-ai/sandbox-runtime@0.0.49
```

Then set `sandbox_python` to `$PI_SANDBOX/venv/bin/python`, and `sandbox_path` to
`$PI_SANDBOX/srt/node_modules/.bin`, the directories holding `node` and `rg`, and
`/usr/bin:/bin:/usr/sbin:/sbin`. All values are absolute.

What happens when one of these is missing depends on the host:

- **Claude Code and Codex hosts** check their `runtimes.pi` entry when they start. A
  `sandbox_python` that does not run or cannot import `agent_sandbox`, or `srt` or `node`
  not on the child's PATH, stops the start with `runtime-unavailable`, and the message
  names the setting that fixes it.
- **Pi and DSH hosts** do not check these when they start. The host starts, and the Pi
  child's own start fails: `create` returns a failed result with
  `last_result.outcome: failed`, and the error message holds the cause.

`rg` is outside the Claude Code and Codex check too: without it the child itself fails,
on any host.

The agents data root must also lie outside the directory the Pi child works in,
because the child must not read it. See the note for your host.

> Not yet walked on a real host: these install commands as written. The real runs
> used an equivalent install at the same two pinned sources.

## What works today

**Real** means seen on a real host with the real Runtime. **Tests** means shown only
by automated tests with stand-in Runtimes, so treat it as untried on a real host. A
real run of the whole Runtime × Runtime matrix is not finished yet. Everything marked
Tests is expected to work and has not been seen to.

| Capability | Claude Code host | Codex host | Pi host | DSH host |
| --- | --- | --- | --- | --- |
| Attach as host | Yes, with `configuration --write`. `/agents-context` shows the binding. Real | Yes, a headless parent that runs one instruction per invocation; `--resume` continues it. Real | Yes, as a Pi extension. Real with `-e`; `pi install` untried | Yes, as a DSH plugin. Real with `--patch`; `dsh plugin add` untried |
| `create`, `status`, `wait`, `send`, `interrupt`, `resume`, `retire` | Yes. Real: `create`, `wait`, `send`, `resume`. Tests: `interrupt`, `retire` | Yes. Real: `create`, `wait`, `status`, `send`, `resume`. Tests: `interrupt`, `retire` | Yes. Real: `create`, `status`, `wait`, `resume`. Tests: `send`, `interrupt`, `retire` | Yes. Real: `create`, `wait`, `send`, `resume`. Tests: `interrupt`, `retire` |
| Choose the child Runtime | `claude` always. `codex`, `dsh`, `pi` with a `runtimes` entry, else `unsupported-runtime` | `codex` always. `claude`, `dsh`, `pi` with a `runtimes` entry, else `unsupported-runtime` | `pi`, `claude` always, `dsh` with a model. `codex` needs a `codex` section, else `invalid-config` | `dsh`, `claude` always. `codex` needs a `codex` section, else `invalid-config`; `pi` needs a `pi` section, else `unsupported-runtime` |
| Choose model or effort per child | Yes. Real on a Codex child: model equal to its default, effort `low` different from it | Yes. Real: a Claude child's model and effort, a DSH child's effort | Yes. Real: a Claude child's model. Tests: effort | Yes. Real: a Claude child's model. Tests: effort |
| Notices to the parent, each once | Pushed into the Main Session, or attached as `main_notices` to the next result. Real: the next-result form. Tests: the push | Host events during the parent's turn; `--resume` delivers what was held. Real | A message in the Pi Session, starting a turn when idle. Real: on a busy parent. Tests: on an idle parent, after a resume | A message through DSH's relay. Real: on a running Session. Tests: holding and delivery on resume |
| Relay of approval requests | One notice per request; `wait` ends early; `requests` and `reply`. Tests | The same. Tests under this host; a real Codex child's refusal reached a test parent through the Python interface. Under `auto_review` Codex decides first and only refusals and failures reach the parent | The same. Real: a Claude child's request, once. Its notice can arrive after the parent has already answered | The same. Tests |
| Review plugin | Children on all four Runtimes, through a connection's `review`. Each adapter is real with a test parent through the Python interface. Tests: under this host | As Claude Code host | As Claude Code host | As Claude Code host |
| Archive | Yes, with `save_normalized_sessions`. Tests | Yes. Real: a Codex child | Yes. Tests | Yes. Tests |
| Children on other Runtimes | Real: Codex. Tests: DSH, Pi | Real: Claude, DSH. Tests: Pi | Real: Claude. Tests: Codex, DSH | Real: Claude. Tests: Codex, Pi |
| Grandchild notices | Go to the child that is the grandchild's parent, on any Runtime, once each; held while it is stopped. Tests | As Claude Code host | As Claude Code host | As Claude Code host |
| Host shutdown | Stops every child this process runs, up to 10 seconds in total. Their ends are held for the next run. Real: a confirmed stop. Tests: an unconfirmed one, reported as `stop-unconfirmed` in `host.log` | The same, reported on stderr and in `stop_unconfirmed` in `--output`. Real: a confirmed stop. Tests: an unconfirmed one | The same, reported on stderr, and the extension's shutdown handler rejects. Tests | The same, reported on stderr and in DSH's logger. Tests |

A Pi child has not yet run under a real host parent. Real Pi children have only run
with a test parent through the Python interface. `ask_parent` from a real Pi child has
not run at all.

The real runs used DSH `0.2.2-alpha.2`, Pi `1.4.0`, `codex-cli` 0.164.0 and Claude
Code 2.1.312 and 2.1.314, and each ran on its own Task's code before later merges. A
real run of this version as a whole is still to come. In particular the stop code
changed in 0.2.2 and 0.2.4, after the real shutdown runs.

## Known limits

- Some names still say GraphTraj until the project's rename. The Claude Code host's
  notice title reads `[GraphTraj notice from <alias> · <event>]`, the variables it
  writes to `.claude/settings.local.json` start with `GRAPHTRAJ_`, and a few native
  names (Codex's `clientInfo`, Pi's custom message type) keep the name. The full list
  is the appendix of [`PUBLIC_API.md`](PUBLIC_API.md).
- `workspace` on `create` narrows a child to a directory inside the caller's own. It
  is not a sandbox by itself; each Runtime confines the child only as far as its own
  sandbox follows the working directory ([`PUBLIC_API.md`](PUBLIC_API.md) section 2).
- Native Sessions are not interchangeable between Runtimes. A child continues only on
  the Runtime it started on.
</content>
