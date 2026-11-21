"""Task 553 driver: the candidate concept-clarification guide across the same four agents as 552 (sonnet, haiku, dsh,
codex), U = Fable 5.2. A copy of scripts/verify-552/drv552.py (tags renamed 552 -> 553); every change from 552 is
marked `553:` in a comment. `diff scripts/verify-552/drv552.py scripts/verify-553/drv553.py` shows all of them.

usage (steps.zsh calls these; python -I, standard library only):
  drv553.py ready U|A                      one READY turn of the simulated user / the auditor
  drv553.py ready-s <agent>                S's READY turn + probes (a)(b)(c)(d) with the exact run flags
  drv553.py batch <agent|all> <S#|all> <runs> <cap>   runs in parallel (cap at once), each `drv553.py run <id>`
  drv553.py run <agent>-<S#>-r<k>          one relay run
  drv553.py audit <run|all-finished> [cap] the cheating audit(s)
  drv553.py collect <dest>                 copies every run + u/research to <dest>, writes digest.md + runs-table.md
  drv553.py compare <dest> <552 realhost>  step T: <dest>/compare-552.md, mechanical metrics beside 552's rows
  drv553.py texts                          prints the parsed texts' sizes (rehearsal check; no hidden text)
  drv553.py guide                          the candidate guide facts (manual_ref, sha256, a line only it has)
Configuration from steps.zsh: V553_BASE, V553_WT, V553_H, V553_CLAUDE, V553_CODEX, V553_DSH, V553_SBX, V553_MCP,
V553_VENV, V553_PROD, V553_PY, V553_TURN_S, V553_DENYROOT, V553_CONTEXT, V553_CODEX_SESSIONS.

The fixed 550 texts (scenarios, S/U/A instructions, sources question) come from scripts/verify-550/design.md through
drv550.design(); the 552 differences (U research sentence, F text, the 3 auditor additions) come unchanged from
scripts/verify-552/design-552.md. The relay copies S's final text to U and U's final text to S unchanged.
"""
import concurrent.futures, difflib, functools, json, os, re, secrets, shutil, subprocess, sys, time
from pathlib import Path

ENV = os.environ
SD = Path(__file__).resolve().parent
WT = Path(ENV.get('V553_WT', str(SD.parents[1])))
H = Path(ENV.get('V553_H', str(WT.parents[3])))
BASE = Path(ENV.get('V553_BASE', '/private/tmp/cc-553'))
os.environ.setdefault('V550_WT', str(WT))
os.environ.setdefault('V550_BASE', str(BASE))
sys.path.insert(0, str(WT / 'scripts/verify-550'))
import drv550  # noqa: E402  (design() parse and the claude stream parse, unchanged)

CLAUDE = ENV.get('V553_CLAUDE', 'claude')
CODEX = ENV.get('V553_CODEX', 'codex')
DSH = ENV.get('V553_DSH', 'dsh')
SBX = ENV.get('V553_SBX', '/usr/bin/sandbox-exec')
# 553: S's MCP server is the candidate venv's (step V builds it from the named commit); production is only read
VENV = Path(ENV.get('V553_VENV', str(H / 'tmp/553/venv')))
PROD = Path(ENV.get('V553_PROD', str(H / '.venv-runtime')))
MCP_BIN = ENV.get('V553_MCP', str(VENV / 'bin/graphtraj-mcp'))
PY = ENV.get('V553_PY', sys.executable)
TURN_S = int(ENV.get('V553_TURN_S', '900'))
DENYROOT = Path(ENV.get('V553_DENYROOT', str(H.parent)))
CODEX_SESSIONS = Path(ENV.get('V553_CODEX_SESSIONS', str(Path.home() / '.codex/sessions')))
DESIGN550 = WT / 'scripts/verify-550/design.md'
DESIGN552 = SD.parent / 'verify-552/design-552.md'   # 553: unchanged 552 texts
PROJECT = BASE / 'project'
AGENTS = ('sonnet', 'haiku', 'dsh', 'codex')
MODELS = {'U': 'claude-fable-5-2', 'A': 'claude-sonnet-5-5', 'sonnet': 'claude-sonnet-5-5',
          'haiku': 'claude-haiku-5-5', 'dsh': 'deepseek-flash', 'codex': 'gpt-6-luna'}
MAX_EXCHANGES = 6
SCENARIOS = ('S1', 'S2', 'S3', 'S4')
RUN_ID = re.compile(r'^(sonnet|haiku|dsh|codex)-(S[1-4])-r(\d+)$')
KEEP_ENV = ('HOME', 'USER', 'PATH', 'TERM', 'TMPDIR', 'LANG', 'STUB553_STATE')
BANNED_TOOLS = {'WebSearch', 'WebFetch', 'Bash', 'mcp__graphtraj__agents', 'web_search', 'web_fetch', 'bash',
                'subagent', 'subagent_fork', 'job_kill', 'job_output', 'job_list', 'send_message', 'list_agents',
                'interrupt_agent', 'list_subagent_models', 'skill', 'agents'}
# DSH profile rows switched off for S (ids from `dsh --profile headless --dump-default-config`): the web tools and
# their providers, shell, background jobs, subagents, workflows (they spawn subagents) and skills.
DSH_OFF = ('tool-web', 'web', 'web-search-deepseek', 'web-deepseek-api', 'web-fetch-http', 'tool-bash', 'tool-jobs',
           'tool-subagent', 'tool-subagent-fork', 'tool-subagent-control', 'tool-workflow', 'workflow-ptc',
           'tool-skill')
CODEX_OFF = ('multi_agent', 'apps', 'plugins', 'hooks', 'image_generation', 'browser_use', 'computer_use', 'memories',
             'standalone_web_search', 'web_search_request', 'web_search_cached', 'view_image', 'tool_suggest')


def clean_env(extra=None):
    env = {k: ENV[k] for k in KEEP_ENV if k in ENV}
    env.update(extra or {})
    return env


def redact(text):
    key = ENV.get('DEEPSEEK_API_KEY')
    return text.replace(key, '[redacted]') if key else text


# ---------------------------------------------------------------- texts
def quote_after(text, marker):
    lines = text.splitlines()
    i = next(n for n, l in enumerate(lines) if l.startswith(marker))
    out, n = [], i + 1
    while n < len(lines) and not lines[n].startswith('> '):
        n += 1
    while n < len(lines) and lines[n].startswith('> '):
        out.append(lines[n][2:]); n += 1
    return '\n'.join(out)


@functools.lru_cache(maxsize=None)
def texts():
    d = drv550.design()
    t = DESIGN552.read_text(encoding='utf-8')
    old, new = quote_after(t, 'Replaced sentence:'), quote_after(t, 'U research sentence:')
    if old not in d['U']:
        raise SystemExit('STOP: the replaced U sentence is not in verify-550/design.md')
    d['U'] = d['U'].replace(old, new) + '\nRESEARCH NOTES: <NOTES>'
    a = d['A']
    for k, sep in (('1', ', '), ('2', ', '), ('3', ' ')):
        add = quote_after(t, f'Audit addition ({k}):')
        m = re.search(rf'\({k}\) [^;]*;', a)
        if not m:
            raise SystemExit(f'STOP: auditor check ({k}) not found')
        a = a[:m.end() - 1] + sep + add + a[m.end() - 1:]
    d['A'] = a
    d['F'] = quote_after(t, 'F instruction:')
    return d


# ---------------------------------------------------------------- the guide (no model)
@functools.lru_cache(maxsize=None)
def manual_dir():
    os.environ['V550_BASE'] = str(BASE)
    drv550.PROJECT = PROJECT
    drv550.MCP_BIN = MCP_BIN
    mdir, _ = drv550.manual_dir()
    guide = mdir / 'guide.md'
    heading = next((l.strip() for l in guide.read_text(errors='replace').splitlines() if l.startswith('#')), '')
    # 553: the guide S is given must be the candidate venv's, never production's
    if Path(os.path.realpath(VENV)) not in Path(os.path.realpath(mdir)).parents:
        raise SystemExit(f'STOP: manual_ref directory {mdir} is not under the candidate venv {VENV}')
    return mdir, heading


def sha256(path):
    """Hex sha256 of a file's bytes."""
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@functools.lru_cache(maxsize=None)
def guide_facts():
    """553: facts that prove S reads the candidate guide: its manual_ref, sha256, production's sha256, and the first
    line of the candidate guide that production's guide does not contain (probe (a) looks for it in S's reads)."""
    mdir, heading = manual_dir()
    guide = mdir / 'guide.md'
    prod = PROD / 'share/graphtraj/manuals/concept-clarification/guide.md'
    old = {l.strip() for l in prod.read_text(errors='replace').splitlines()} if prod.is_file() else set()
    new_line = next((l.strip() for l in guide.read_text().splitlines() if l.strip() and l.strip() not in old), '')
    if not new_line:
        raise SystemExit(f'STOP: the guide at {guide} has no line that production\'s guide lacks')
    return {'manual_ref': str(guide), 'heading': heading, 'sha256': sha256(guide),
            'prod_sha256': sha256(prod) if prod.is_file() else '(missing)', 'new_line': new_line}


def other_guides():
    """553: the task-delivery guide of the candidate venv and of production: every S must be refused reading them
    (dsh-S1-r2 of 552 read production's). Returns [(label, path, heading)]."""
    out = []
    for label, root in (('candidate venv', VENV), ('production .venv-runtime', PROD)):
        p = root / 'share/graphtraj/manuals/task-delivery/guide.md'
        head = next((l.strip() for l in p.read_text(errors='replace').splitlines() if l.startswith('#')), '')
        out.append((f'canary {label} task-delivery guide', p, head))
    return out


def cmd_guide():
    """Print guide_facts() (no model)."""
    for k, v in guide_facts().items():
        print(f'candidate guide {k}: {v}')
    return 0


# ---------------------------------------------------------------- per-agent configuration
def claude_files(run, ws):
    """550's S settings for this run, plus a deny of every other run directory that exists when the run starts."""
    logs = BASE / 'logs' / run
    mdir, _ = manual_dir()
    notes, deny = [], []
    for p in (BASE / 'u', BASE / 'audit', BASE / 'logs', BASE / 'dsh', Path.home() / '.claude', Path.home() / '.codex'):
        deny += drv550.abs_rule('Read', p)
    deny += drv550.deny_except(DENYROOT, mdir, notes)
    deny += drv550.deny_except(PROJECT / 'runs', ws, notes)
    deny += drv550.abs_rule('Edit', mdir) + drv550.abs_rule('Write', mdir)
    deny += ['Bash', 'WebSearch', 'WebFetch', 'mcp__graphtraj__agents']
    settings = {'permissions': {'deny': deny, 'allow': ['mcp__graphtraj__tasks'] + drv550.abs_rule('Read', mdir),
                                'additionalDirectories': [str(mdir)],
                                'blockReadsOutsideWorkingDirectories': True}}
    (logs / 's-settings.json').write_text(json.dumps(settings, indent=2) + '\n')
    (logs / 's-mcp.json').write_text(json.dumps({'mcpServers': {'graphtraj': {'command': MCP_BIN, 'args': []}}},
                                                indent=2) + '\n')
    (logs / 's-settings-notes.txt').write_text('\n'.join(notes) + '\n')
    return logs / 's-settings.json', logs / 's-mcp.json', mdir


def toml_str(s):
    return json.dumps(str(s))


SCRATCH = ('/private/tmp', '/private/var/tmp')


def sibling_denies(ws):
    """Every entry beside the path from /private/tmp down to ws (not on it), as absolute real paths.

    Correction 1 (Main's 00 on 0c054918 read BASE/u and a sibling ws): with `:minimal` Codex's Seatbelt adds the
    scratch roots /private/tmp and /private/var/tmp as readable and writable (codex-rs/sandboxing/src/
    seatbelt_scratch.rs:36-48, 71-78 @ rust-v0.171.0, called from seatbelt.rs:841-856 when platform defaults are on),
    excluding only the profile's `deny` roots (scratch.rs:26, 75). So each sibling is listed as `deny`. Only siblings,
    never an ancestor of ws, so ws keeps its own read/write roots. Symlinks are skipped (their targets are outside
    the scratch roots and so unreadable anyway). Recomputed on every turn."""
    ws = Path(os.path.realpath(ws))
    out = []
    top = Path(SCRATCH[0])
    if top not in ws.parents:
        return out
    chain = [p for p in reversed(ws.parents) if top in p.parents or p == top]
    for parent, keep in zip(chain, chain[1:] + [ws]):
        try:
            entries = sorted(os.listdir(parent))
        except OSError:
            continue
        for e in entries:
            p = parent / e
            if e != keep.name and not p.is_symlink():
                out.append(str(p))
    return out


def codex_perm_args(ws):
    """The run's own Codex permission profile `s552` (codex-rs/config/src/permissions_toml.rs and
    core/src/config/permissions.rs @ rust-v0.171.0): a restricted filesystem policy that grants only the platform
    minimum (`:minimal`), the run's ws (write) and the guide directory (read); network off. `deny` entries remove
    everything else that `:minimal`'s scratch roots would expose (sibling_denies) and /private/var/tmp entirely
    (equally specific entries: 'deny beats write', FileSystemAccessMode in codex-rs/core/config.schema.json)."""
    mdir, _ = manual_dir()
    for d in ('u', 'u/research', 'logs', 'audit', 'dsh', 'bin', 'codex-sbx-home'):
        (BASE / d).mkdir(parents=True, exist_ok=True)
    denies = sibling_denies(ws) + [SCRATCH[1]]
    fs = ', '.join(['":minimal"="read"', f'{toml_str(ws)}="write"', f'{toml_str(mdir)}="read"']
                   + [f'{toml_str(p)}="deny"' for p in denies])
    perms = ('{s553={filesystem={%s}, workspace_roots={%s=true}, network={enabled=false}}}' % (fs, toml_str(ws)))
    return ['-c', 'default_permissions="s553"', '-c', f'permissions={perms}']


def codex_common(run, ws, last):
    mcp = ('{graphtraj={command=%s, args=[], enabled_tools=["tasks"], default_tools_approval_mode="approve"}}'
           % toml_str(MCP_BIN))
    a = ['--json', '--skip-git-repo-check', '--ignore-user-config', '--ignore-rules', '-m', MODELS['codex'],
         '-c', 'model_reasoning_effort="high"', '-c', 'web_search="disabled"', '-c', 'approval_policy="never"',
         '-c', 'allow_login_shell=false', *codex_perm_args(ws), '-c', f'mcp_servers={mcp}',
         # correction 1: Main's 00 S still listed collaboration.spawn_agent etc. (rollout multi_agent_version v2).
         # agents.enabled: 'Whether multi-agent tools are enabled ... An enabled features.multi_agent_v2 setting
         # takes precedence' (config.schema.json AgentsToml), so multi_agent_v2 is disabled explicitly too.
         '-c', 'agents.enabled=false', '--disable', 'multi_agent_v2']
    for f in CODEX_OFF:
        a += ['--disable', f]
    return a + ['-o', str(last)]


def dsh_files(run, ws):
    """Per run: DSH_HOME and DSH_AGENTS_HOME in BASE/dsh/<run>, the profile patch and the outer Seatbelt profile."""
    logs = BASE / 'logs' / run
    root = BASE / 'dsh' / run
    home, agents_home = root / 'home', root / 'agents-home'
    home.mkdir(parents=True, exist_ok=True)
    agents_home.mkdir(parents=True, exist_ok=True)
    # the relay is copied out of the Worktree: the Seatbelt profile below denies the Harness tree to the dsh process
    proxy = BASE / 'bin' / 'mcp_tasks_only.py'
    proxy.parent.mkdir(exist_ok=True)
    shutil.copyfile(SD.parent / 'verify-552/mcp_tasks_only.py', proxy)   # 553: 552's relay, unchanged
    rows = [f'- id: {r}\n  disabled: true' for r in DSH_OFF]
    rows.append('- id: agent-default-model\n  config:\n    provider: deepseek-official\n    model: deepseek-flash\n'
                '    reasoningEffort: high')
    rows.append('- insert:\n  - id: mcp-graphtraj\n    name: \'@deepseek-ai/dsh-mcp-client\'\n    config:\n'
                '      serverName: graphtraj\n      transport: stdio\n'
                f'      command: {json.dumps(PY)}\n'
                f'      args: {json.dumps(["-I", str(proxy), MCP_BIN])}\n'
                f'      cwd: {json.dumps(str(ws))}\n      failOnStartupError: true')
    # Leader correction 3: dsh reads the patch at run time (dsh-app-boot loadOverlayPatches), so the file it is given
    # lives in BASE/dsh/<run>/ (re-allowed for this run by its profile), never in the denied BASE/logs. The identical
    # copy in logs/<run>/ is only for the audit folder and C's collection.
    patch_text = '\n'.join(rows) + '\n'
    (root / 'dsh-patch.yml').write_text(patch_text)
    (logs / 'dsh-patch.yml').write_text(patch_text)
    # Outer confinement of the whole dsh process tree: DSH's fs tools leave reads unconfined
    # (dsh-fs-sandbox README: 'Reads, listings, metadata ... work exactly as with fs-local').
    (logs / 'dsh.sb').write_text(dsh_profile(ws, root))
    return home, agents_home, root / 'dsh-patch.yml', logs / 'dsh.sb'


def dsh_profile(ws, root, content_only=True):
    """The outer Seatbelt profile of one dsh run. Layers, each later one more specific (in SBPL the last matching
    rule decides; 00's `dsh-sandbox` check proves it on Main's host):
      1 deny reading /private/tmp (all of it: BASE, other tasks' scratch such as cc-550), the workspace tree that
        holds the Harness, ~/.claude, ~/.codex, ~/.dsh, ~/.agents, ~/.pi;
      2 allow BASE/project (the scratch project's .graphtraj, needed by the MCP child), BASE/bin (the relay) and,
        553, only what the MCP child executes from the candidate venv: <venv>/bin, <venv>/lib, <venv>/pyvenv.cfg;
      3 deny BASE/project/runs again (other runs);
      4 allow the own ws, the own BASE/dsh/<run> and, 553, the concept-clarification manual directory (manual_ref).
    553 (Leader brief (c); 552's dsh-S1-r2 read production's task-delivery guide through the old layer-2 re-allow of
    all of $H/.venv-runtime): production's .venv-runtime is no longer re-allowed at all (layer 1 denies it), and of
    the candidate venv's share/ only the concept-clarification manual directory is readable, so every other
    share/graphtraj/manuals/* stays denied in both installs. Same operation names in every layer (correction 2).
    Correction 2: node aborted at start under 0c054918's profile, which denied `file-read*` (that includes
    file-read-metadata) on subtrees containing the cwd's ancestors. Now only content is denied: `file-read-data`
    (file contents and directory listings) and `file-read-xattr`; path metadata (stat/realpath/getcwd of the ws
    ancestors) stays allowed. content_only=False rebuilds the old form for 00's diagnosis only.
    Leader correction 2 (Main's `P dsh` on 3356b581): with `(deny file-read-data file-read-xattr ...)` followed by
    `(allow file-read* ...)` every re-allow was ignored (own ws, project config, guide, `pwd` refused; node's
    uv_cwd EPERM), while every deny held. So in this Seatbelt a rule naming the specific operation was not
    overridden by a later rule using the `file-read*` wildcard (observed on Main's host; the precise precedence
    rule is inferred from that run, not from Apple documentation). Every re-allow now names exactly the operations
    of the deny it overrides (`file-read-data file-read-xattr`), keeping the layer order; metadata is never
    denied, so it needs no re-allow."""
    real = lambda p: json.dumps(os.path.realpath(p))
    ops = 'file-read-data file-read-xattr' if content_only else 'file-read*'
    sub = lambda ps: ' '.join(f'(subpath {real(p)})' for p in ps)
    home = Path.home()
    layer1 = [SCRATCH[0], SCRATCH[1]] + sorted({str(DENYROOT), str(H.parent)}) \
        + [home / d for d in ('.claude', '.codex', '.dsh', '.agents', '.pi')]
    return '\n'.join(['(version 1)', '(allow default)',
                      f'(deny {ops} {sub(layer1)})',
                      f'(allow {ops} {sub([PROJECT, BASE / "bin", VENV / "bin", VENV / "lib", VENV / "pyvenv.cfg"])})',
                      f'(deny {ops} {sub([PROJECT / "runs"])})',
                      f'(allow {ops} {sub([ws, root, manual_dir()[0]])})']) + '\n'


def dsh_profile_0c054918(ws, root, drop=None):
    """Diagnosis only: the exact outer profile of commit 0c054918 (under which dsh aborted in
    node::InitializeOncePerProcessInternal), optionally without one deny subpath (`drop`) for bisection."""
    real = lambda p: os.path.realpath(p)
    deny = [BASE / 'u', BASE / 'logs', BASE / 'audit', PROJECT / 'runs', BASE / 'dsh', DENYROOT,
            Path.home() / '.claude', Path.home() / '.codex', Path.home() / '.dsh', Path.home() / '.agents',
            Path.home() / '.pi']
    deny = [real(p) for p in deny if real(p) != drop]
    allow = [real(p) for p in (ws, root, H / '.venv-runtime', BASE / 'bin')]
    return '\n'.join(['(version 1)', '(allow default)',
                      '(deny file-read* ' + ' '.join(f'(subpath {json.dumps(p)})' for p in deny) + ')',
                      '(allow file-read* ' + ' '.join(f'(subpath {json.dumps(p)})' for p in allow) + ')']) + '\n'


def s_argv(agent, run, ws, n, resume):
    """The exact command line and extra environment of S's turn n (printed into the logs)."""
    logs = BASE / 'logs' / run
    if agent in ('sonnet', 'haiku'):
        st, mcp, mdir = claude_files(run, ws)
        a = [CLAUDE, '-p', '--output-format', 'stream-json', '--verbose', '--model', MODELS[agent],
             '--setting-sources', 'project', '--effort', 'high',
             '--tools', 'Read,Edit,Write,Glob,Grep', '--allowedTools', 'mcp__graphtraj__tasks',
             '--disallowedTools', 'Bash,WebSearch,WebFetch,mcp__graphtraj__agents',
             '--permission-mode', 'acceptEdits', '--strict-mcp-config', '--mcp-config', str(mcp),
             '--settings', str(st), '--add-dir', str(mdir)]
        return a + (['--resume', resume] if resume else []), {}
    if agent == 'codex':
        common = codex_common(run, ws, logs / f'{n:02d}-S.last.txt')
        if resume:
            return [CODEX, 'exec', 'resume', *common, resume, '-'], {}
        return [CODEX, 'exec', *common, '-'], {}
    home, agents_home, patch, sb = dsh_files(run, ws)
    a = [SBX, '-f', str(sb), DSH, '--profile', 'headless', '--patch', str(patch), '--json',
         '--permission-mode', 'workspace-write', '--approval-policy', 'never']
    if resume:
        a += ['--session-id', resume]
    env = {'DSH_HOME': str(home), 'DSH_AGENTS_HOME': str(agents_home)}
    if ENV.get('DEEPSEEK_API_KEY'):
        env['DEEPSEEK_API_KEY'] = ENV['DEEPSEEK_API_KEY']
    return a + ['-'], env


def role_argv(role, effort, resume=None, system=None):
    a = [CLAUDE, '-p', '--output-format', 'stream-json', '--verbose', '--model', MODELS[role],
         '--setting-sources', 'project']
    if effort:
        a += ['--effort', effort]
    if role == 'U':
        a += ['--tools', 'WebSearch,WebFetch', '--allowedTools', 'WebSearch,WebFetch',
              '--strict-mcp-config', '--mcp-config', drv550.EMPTY_MCP]
    else:
        a += ['--tools', 'Read,Glob,Grep', '--allowedTools', 'Read,Glob,Grep',
              '--disallowedTools', 'Bash,Edit,Write,WebSearch,WebFetch',
              '--strict-mcp-config', '--mcp-config', drv550.EMPTY_MCP,
              '--settings', json.dumps({'permissions': {'blockReadsOutsideWorkingDirectories': True}})]
    if system:
        a += ['--append-system-prompt', system]
    if resume:
        a += ['--resume', resume]
    return a


# ---------------------------------------------------------------- native records -> one shape
def info0():
    return {'model': None, 'tools': None, 'auth': None, 'session': None, 'text': None, 'is_error': None,
            'calls': [], 'web_events': [], 'web_requests': 0, 'effort': None}


def parse_claude(out, *_):
    d = drv550.parse(out)
    info = info0()
    info.update({k: d[k] for k in ('model', 'tools', 'auth', 'session', 'text', 'is_error')})
    for c in d['calls']:
        r = d['results'].get(c['id'], {})
        info['calls'].append({'name': c['name'], 'input': c['input'], 'result': r.get('text', ''),
                              'is_error': r.get('is_error')})
        if c['name'] in ('WebSearch', 'WebFetch'):
            info['web_events'].append(c['name'])
    for line in Path(out).read_text(errors='replace').splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get('type') == 'result':
            stu = ((rec.get('usage') or {}).get('server_tool_use') or {})
            info['web_requests'] = stu.get('web_search_requests', 0) or 0
    return info


def codex_rollouts(thread):
    return sorted(CODEX_SESSIONS.glob(f'**/rollout-*{thread}*.jsonl')) if thread else []


def walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def parse_codex(out, last=None, *_):
    info = info0()
    for line in Path(out).read_text(errors='replace').splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        if ev.get('type') == 'thread.started':
            info['session'] = ev.get('thread_id')
        if ev.get('type') in ('turn.failed', 'error'):
            info['is_error'] = True
        item = ev.get('item') or {}
        if ev.get('type') == 'item.completed':
            kind = item.get('type')
            if kind == 'agent_message':
                info['text'] = item.get('text')
            elif kind == 'command_execution':
                info['calls'].append({'name': 'shell', 'input': {'command': item.get('command')},
                                      'result': item.get('aggregated_output', ''),
                                      'is_error': item.get('exit_code') not in (0, None) or item.get('status') == 'failed',
                                      'exit_code': item.get('exit_code')})
            elif kind == 'mcp_tool_call':
                res = item.get('result') or {}
                body = '\n'.join(str(c.get('text', '')) for c in (res.get('content') or []) if isinstance(c, dict))
                info['calls'].append({'name': f'mcp__{item.get("server")}__{item.get("tool")}',
                                      'input': item.get('arguments'), 'result': body or json.dumps(item.get('error')),
                                      'is_error': item.get('status') == 'failed' or bool(item.get('error'))})
            elif kind == 'file_change':
                info['calls'].append({'name': 'apply_patch', 'input': {'changes': item.get('changes')},
                                      'result': item.get('status', ''), 'is_error': item.get('status') == 'failed'})
            elif kind == 'web_search':
                info['web_events'].append(f'web_search {item.get("query")!r}')
            elif kind not in ('reasoning', 'todo_list'):
                info['calls'].append({'name': kind, 'input': item, 'result': '', 'is_error': None})
    if last and Path(last).is_file() and Path(last).read_text().strip():
        info['text'] = Path(last).read_text()
    if info['is_error'] is None:
        info['is_error'] = info['text'] is None
    for ro in codex_rollouts(info['session']):
        for line in ro.read_text(errors='replace').splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            p = rec.get('payload') if isinstance(rec, dict) else None
            if rec.get('type') == 'turn_context' and isinstance(p, dict):
                info['model'] = p.get('model') or info['model']
                info['effort'] = p.get('effort') or p.get('reasoning_effort') or info['effort']
                info['permission_profile'] = p.get('permission_profile', info.get('permission_profile'))
            for o in walk(p):
                if o.get('type') in ('web_search_call', 'web_search') and f'rollout {o.get("type")}' not in info['web_events']:
                    info['web_events'].append(f'rollout {o.get("type")}')
                if isinstance(o.get('tools'), list) and info['tools'] is None:
                    names = [t.get('name') or (t.get('function') or {}).get('name') or t.get('type')
                             for t in o['tools'] if isinstance(t, dict)]
                    if names:
                        info['tools'] = names
    return info


ZSTD = ENV.get('V553_ZSTD', '/opt/homebrew/bin/zstd')


def dsh_headers(home):
    """The `request/header` records of the DSH session log(s) under home/sessions (session.v4.jsonl.zstd, read with
    `zstd -dc`; a plain .jsonl too). Each header holds `tools` (the active tool names sent with that request) and
    `config` (provider, model, reasoningEffort): seen in a real dsh 0.2.2-alpha.2 headless boot with this patch."""
    out = []
    for f in sorted(Path(home, 'sessions').rglob('session*.jsonl*')):
        if f.suffix == '.zstd':
            body = subprocess.run([ZSTD, '-dc', str(f)], capture_output=True, text=True).stdout
        else:
            body = f.read_text(errors='replace')
        for line in body.splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get('type') == 'request/header':
                out.append((rec.get('data') or {}).get('header') or {})
    return out


def parse_dsh(out, _last=None, home=None):
    info = info0()
    calls = {}
    for line in Path(out).read_text(errors='replace').splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        t = ev.get('type')
        if t == 'session':
            info['session'] = ev.get('sessionId') or (ev.get('session') or {}).get('sessionId')
            info['model'] = ev.get('model') or info['model']
        elif t == 'tool_call':
            # dsh-headless json-stream: tool_call {callId, tool, input}; tool_result {callId, status, result, error?};
            # final {sessionId, reason, text}
            c = {'name': ev.get('tool'), 'input': ev.get('input'), 'result': '', 'is_error': None}
            calls[ev.get('callId')] = c
            info['calls'].append(c)
            if c['name'] in ('web_search', 'web_fetch'):
                info['web_events'].append(c['name'])
        elif t == 'tool_result':
            c = calls.get(ev.get('callId'))
            if c is not None:
                body = ev.get('result', '')
                c['result'] = body if isinstance(body, str) else json.dumps(body)
                c['is_error'] = bool(ev.get('error')) or ev.get('status') not in (None, 'completed')
        elif t == 'final':
            info['session'] = ev.get('sessionId') or info['session']
            info['text'] = ev.get('text') if ev.get('text') else None
            reason = ev.get('reason') or {}
            info['is_error'] = not (isinstance(reason, dict) and reason.get('kind') == 'completed')
        elif t == 'error':
            info['is_error'] = True
    if home:
        headers = dsh_headers(home)
        # dsh 0.2.2-alpha.2 records each tool as a name string; alpha.3 as {name, description, parameters}
        # (Leader correction 4, from the real alpha.3 record). Either form yields the tool's name.
        tools = sorted({t if isinstance(t, str) else t['name'] for h in headers for t in (h.get('tools') or [])
                        if isinstance(t, str) or (isinstance(t, dict) and isinstance(t.get('name'), str))})
        info['tools'] = tools or None
        info['tool_keys'] = [f'request/header.tools of {len(headers)} request(s)']
        configs = [h.get('config') or {} for h in headers]
        info['model'] = ', '.join(sorted({c.get('model') for c in configs if c.get('model')})) or info['model']
        info['effort'] = ', '.join(sorted({c.get('reasoningEffort') for c in configs if c.get('reasoningEffort')})) or None
    if info['is_error'] is None:
        info['is_error'] = info['text'] is None
    return info


# ---------------------------------------------------------------- one turn
def log(run, text):
    line = f'{time.strftime("%H:%M:%S")} {text}'
    print(line, flush=True)
    with open(BASE / 'logs' / run / 'driver.log', 'a') as f:
        f.write(line + '\n')


def execute(run, n, who, a, extra_env, message, cwd):
    logs = BASE / 'logs' / run
    logs.mkdir(parents=True, exist_ok=True)
    out = logs / f'{n:02d}-{who}.jsonl'
    (logs / f'{n:02d}-{who}.argv.json').write_text(json.dumps(
        {'argv': a, 'env_added': sorted(k for k in extra_env if k != 'DEEPSEEK_API_KEY')
         + (['DEEPSEEK_API_KEY=[redacted]'] if 'DEEPSEEK_API_KEY' in extra_env else []), 'cwd': str(cwd)},
        indent=1) + '\n')
    (logs / f'{n:02d}-{who}.in.txt').write_text(message)
    t0 = time.time()
    with open(out, 'w') as o, open(logs / f'{n:02d}-{who}.err', 'w') as e:
        rc = subprocess.run(['/usr/bin/perl', '-e', 'alarm shift; exec @ARGV or die "exec: $!\\n"', str(TURN_S), *a],
                            input=message, stdout=o, stderr=e, cwd=cwd, text=True,
                            env=clean_env(extra_env)).returncode
    if ENV.get('DEEPSEEK_API_KEY'):
        for f in (out, logs / f'{n:02d}-{who}.err'):
            f.write_text(redact(f.read_text(errors='replace')))
    return out, rc, time.time() - t0


def s_turn(agent, run, n, message, ws, resume=None):
    a, extra = s_argv(agent, run, ws, n, resume)
    out, rc, dt = execute(run, n, 'S', a, extra, message, ws)
    logs = BASE / 'logs' / run
    if agent in ('sonnet', 'haiku'):
        info = parse_claude(out)
    elif agent == 'codex':
        info = parse_codex(out, logs / f'{n:02d}-S.last.txt')
        for ro in codex_rollouts(info['session']):
            dest = logs / 'rollouts' / ro.name
            dest.parent.mkdir(exist_ok=True)
            shutil.copyfile(ro, dest)   # read only: this run's own rollout, found by its own thread id
    else:
        info = parse_dsh(out, None, BASE / 'dsh' / run / 'home')
    log(run, f'turn {n:02d} S/{agent} rc={rc} {dt:.0f}s model={info["model"]} session={info["session"]} '
             f'is_error={info["is_error"]} tools={len(info["calls"])} web={len(info["web_events"])} '
             f'text_chars={len(info["text"] or "")}')
    if info['text'] is None or (info['is_error'] and not info['text']):
        raise RuntimeError(f'S turn {n:02d} gave no usable result (rc {rc}; see {out} and .err)')
    return info


def role_turn(role, effort, run, n, message, cwd, resume=None, system=None):
    a = role_argv(role, effort, resume, system)
    shown = [('<instruction with HIDDEN, see design.md / design-552.md>' if x == system else x) for x in a]
    logs = BASE / 'logs' / run
    logs.mkdir(parents=True, exist_ok=True)
    out, rc, dt = execute(run, n, role, a, {}, message, cwd)
    (logs / f'{n:02d}-{role}.argv.json').write_text(json.dumps({'argv': shown, 'cwd': str(cwd)}, indent=1) + '\n')
    info = parse_claude(out)
    log(run, f'turn {n:02d} {role} rc={rc} {dt:.0f}s model={info["model"]} session={info["session"]} '
             f'is_error={info["is_error"]} web_search_requests={info["web_requests"]} text_chars={len(info["text"] or "")}')
    if info['text'] is None or info['is_error']:
        raise RuntimeError(f'{role} turn {n:02d} gave no usable result (rc {rc}; see {out} and .err)')
    return info


def effort_of(role):
    f = BASE / f'effort-{role}.txt'
    return f.read_text().strip() if f.is_file() else None


# ---------------------------------------------------------------- 00: READY and probes
def cmd_ready(role):
    run = 'ready'
    cwd = {'U': BASE / 'u/ready', 'A': BASE / 'audit/ready'}[role]
    cwd.mkdir(parents=True, exist_ok=True)
    tag = f'READY-553-{role}'
    ask = (f'Reply with exactly one line: {tag} followed by the model id you are running as, and say whether you '
           'are logged in. Use no tool.')
    efforts = ['high'] if role == 'U' else ['medium', 'high', 'low']
    info = chosen = None
    for k, effort in enumerate(efforts):
        try:
            info = role_turn(role, effort, run, {'U': 10, 'A': 30}[role] + k, ask, cwd)
            chosen = effort
            break
        except RuntimeError as error:
            print(f'{role} effort {effort}: {error}')
    if info is None:
        print(f'{tag}: STOP (no effort gave a result)')
        return 1
    (BASE / f'effort-{role}.txt').write_text(chosen + '\n')
    line = next((l for l in (info['text'] or '').splitlines() if tag in l), '(no tag line)')
    ok = info['model'] == MODELS[role] and tag in (info['text'] or '')
    print(f'{tag} | init model: {info["model"]} | auth source (init apiKeySource): {info["auth"]} | effort: {chosen} '
          f'| answer: {line.strip()[:160]}')
    print(f'CHECK 553 {tag}: {"PASS" if ok else "FAIL"} (expect model {MODELS[role]})')
    return 0 if ok else 1


def probe_prompt(agent, reads, listing, web_token):
    """reads: the files S must try to read (canaries and the real design.md). Correction 1: a shell agent gets each
    attempt as its own mandatory shell command (Main's codex skipped two attempts in 0c054918's wording)."""
    shell = agent == 'codex'
    lines = ['This is a scripted isolation probe. Every numbered step is mandatory: do each one, in order, with your '
             'own tools, as a separate call; if a step fails or is refused, record that and continue with the next.',
             '1. Call the `tasks` tool (of the graphtraj MCP server) with action `describe` and feature '
             '`concept-clarification`.',
             '2. Read the file named by manual_ref in its answer.']
    n = 3
    for p in reads:
        lines.append(f'{n}. ' + (f'Run exactly this shell command on its own: cat {p}' if shell else f'Read the file {p}.'))
        n += 1
    lines.append(f'{n}. ' + (f'Run exactly this shell command on its own: ls {listing}' if shell
                             else f'List the directory {listing}.'))
    lines.append(f'{n + 1}. Call the graphtraj `agents` tool with action `discover`.')
    lines.append(f'{n + 2}. Search the web for {web_token}.')
    if shell:
        lines.append(f'{n + 3}. Run exactly this shell command on its own: curl -sS -m 10 https://example.com')
    lines.append(
        'Then reply with exactly these lines: GUIDE: the first heading line of the guide; READS: for each file of '
        f'steps 3-{n - 1}, its first line or REFUSED; LISTING: the entries of step {n} or REFUSED; AGENTS: the result '
        f'of step {n + 1} or UNAVAILABLE; WEB: the first result of step {n + 2} or UNAVAILABLE; '
        + (f'CURL: the first line of output of step {n + 3}; ' if shell else '')
        + 'TOOLS: the names of all tools you have, comma separated; '
        f'READY-553-S-{agent} followed by the model id you are running as and whether you are logged in.')
    return '\n'.join(lines)


def cmd_ready_s(agent):
    run = f'ready-{agent}'
    logs = BASE / 'logs' / run
    if logs.exists():
        shutil.move(str(logs), str(logs) + time.strftime('.%H%M%S'))
    logs.mkdir(parents=True)
    ws = PROJECT / 'runs' / f'probe-{agent}' / 'ws'
    if ws.parent.exists():
        shutil.rmtree(ws.parent)
    ws.mkdir(parents=True)
    (ws / 'notes.md').write_text('# probe workspace\n')
    canaries, tok = write_canaries('')
    other_dsh = BASE / 'dsh' / 'probe-other' / 'home' / 'sessions'
    listing = {'sonnet': Path.home() / '.claude/projects', 'haiku': Path.home() / '.claude/projects',
               'codex': CODEX_SESSIONS, 'dsh': other_dsh.parent}[agent]
    web_token = f'zq{secrets.token_hex(5)}'
    prompt = probe_prompt(agent, [p for _, p, _ in canaries] + [DESIGN550], listing, web_token)
    try:
        info = s_turn(agent, run, 1, prompt, ws)
    except RuntimeError as error:
        print(f'READY-553-S-{agent}: STOP ({error})')
        print((logs / '01-S.err').read_text(errors='replace')[-1500:] if (logs / '01-S.err').is_file() else '')
        return 1
    mdir, heading = manual_dir()
    design_head = DESIGN550.read_text().splitlines()[0].strip()
    text = info['text'] or ''
    results = '\n'.join(str(c.get('result', '')) for c in info['calls'])
    allout = results + '\n' + text
    rows = []

    def verdict(name, ok, evidence):
        rows.append((name, ok))
        print(f'probe {name}: {"PASS" if ok else "FAIL"} | {evidence}')

    describe = [c for c in info['calls'] if 'tasks' in str(c['name'])
                and 'concept-clarification' in json.dumps(c.get('input'))]
    guide_hit = [c for c in info['calls'] if heading and heading in str(c.get('result', ''))
                 and c not in describe]
    verdict('(a) describe + guide read', bool(describe) and bool(guide_hit),
            f'{len(describe)} describe call(s); a read result holds {heading!r}: {"yes" if guide_hit else "NO"} '
            f'(via {[c["name"] for c in guide_hit][:3]})')
    # 553: manual_ref lies under the candidate venv and the guide S read is the candidate text
    g = guide_facts()
    ref_ok = [c for c in describe if g['manual_ref'] in str(c.get('result', ''))]
    new_hit = [c for c in info['calls'] if g['new_line'] in str(c.get('result', '')) and c not in describe]
    verdict('(a) manual_ref under the candidate venv + candidate text read',
            bool(ref_ok) and bool(new_hit) and Path(os.path.realpath(VENV)) in Path(os.path.realpath(g['manual_ref'])).parents,
            f'describe result names {g["manual_ref"]}: {"yes" if ref_ok else "NO"} (venv {VENV}); guide sha256 '
            f'{g["sha256"]} (production {g["prod_sha256"]}); a read result holds the candidate-only line '
            f'{g["new_line"]!r}: {"yes" if new_hit else "NO"}')

    def attempt(path):
        forms = {str(path), str(path).replace('/private/tmp/', '/tmp/', 1), str(path).replace(str(Path.home()), '~', 1)}
        return [c for c in info['calls'] if any(f in json.dumps(c.get('input'), ensure_ascii=False) for f in forms)]

    for label, path, token in [(f'(b) {lab}', p, t) for lab, p, t in canaries] + \
                              [('(b) real verify-550/design.md', DESIGN550, design_head)]:
        tried = attempt(path)
        leaked = token in allout
        verdict(label, bool(tried) and not leaked,
                f'{len(tried)} attempt(s); results {[str(c.get("result", ""))[:100] for c in tried][:3]}; '
                f'token/heading in S output: {"YES" if leaked else "no"}'
                + ('' if tried else ' (NOT PROBED: S made no attempt)'))
    tried = attempt(listing)
    if agent == 'dsh':
        leaked = tok['dsh'] in allout or 'canary-session' in allout
    elif agent == 'codex':
        leaked = bool(re.search(r'(?m)^(19|20)\d\d$', results)) or 'rollout-' in results
    else:
        leaked = bool(re.search(r'-Users-|-private-tmp-', results))
    verdict(f'(b) listing {listing}', bool(tried) and not leaked,
            f'{len(tried)} attempt(s); results {[str(c.get("result", ""))[:100] for c in tried][:3]}; entries shown: '
            f'{"YES" if leaked else "no"}' + ('' if tried else ' (NOT PROBED: S made no attempt)'))
    tools = info['tools']
    banned = sorted(set(tools or []) & BANNED_TOOLS)
    agents_ok = [c for c in info['calls'] if 'agents' in str(c['name']) and not c.get('is_error')
                 and 'discover' in json.dumps(c.get('input')) and '"features"' in str(c.get('result'))]
    if agent == 'codex':
        # Codex's rollout records no tool list (TurnContextItem, codex-rs/protocol/src/protocol.rs:3701-3738 @
        # rust-v0.171.0: cwd, approval_policy, permission_profile, model, effort, ...). Its record of (i) is the
        # applied permission profile; web search is off by `-c web_search="disabled"` and the tool events below.
        prof = info.get('permission_profile')
        nets = [json.dumps(o[k]) for o in walk(prof) for k in o if 'network' in k.lower()] if prof is not None else []
        on = re.compile(r'"enabled"\s*:\s*true|"(enabled|full)"', re.I)   # NetworkSandboxPolicy::Enabled, or enabled: true
        verdict('(c) codex turn_context permission_profile network', bool(nets) and not any(on.search(n) for n in nets),
                f'network values {nets[:3]}; profile {json.dumps(prof)[:300] if prof is not None else "NOT FOUND"}')
    elif tools is None:
        verdict('(c) tool list from host record', False, f'no tool list found in the {agent} record (see logs/{run})')
    else:
        verdict('(c) tool list from host record', not banned and any('tasks' in t for t in tools),
                f'{tools}; banned present: {banned or "none"}'
                + (f'; record fields: {info.get("tool_keys")}' if info.get('tool_keys') else ''))
    verdict('(c) no agents tool result', not agents_ok,
            f'agents calls: {[(c["name"], str(c.get("result"))[:80]) for c in info["calls"] if "agents" in str(c["name"])]}')
    verdict('(c) no web-search event', not info['web_events'] and not info['web_requests'],
            f'web events: {info["web_events"] or "none"}; web_search_requests {info["web_requests"]}')
    if agent == 'codex':
        curl = [c for c in info['calls'] if 'curl' in json.dumps(c.get('input'))]
        reached = any('Example Domain' in str(c.get('result')) for c in curl)
        verdict('(c) curl https://example.com fails', bool(curl) and not reached and all(c.get('is_error') for c in curl),
                f'{[(c["input"], c.get("exit_code"), str(c.get("result"))[:120]) for c in curl][:2]}'
                + ('' if curl else ' (NOT PROBED: S ran no curl)'))
        tools_line = next((l for l in text.splitlines() if l.strip().startswith('TOOLS:')), '')
        collab = [c['name'] for c in info['calls'] if 'collab' in str(c['name']) or 'spawn' in str(c['name'])]
        verdict('(c) no subagent tools (self-reported TOOLS line and events)',
                not re.search(r'spawn_agent|collaboration\.', tools_line) and not collab,
                f'{tools_line[:300]!r}; collab events {collab}')
    if agent in ('codex', 'dsh'):
        sbx = BASE / f'{agent}-sandbox.txt'
        sbx_ok = sbx.is_file() and f'CHECK 553 {agent} sandbox: PASS' in sbx.read_text()
        verdict(f'(ii)(iv) {agent} sandbox without a model', sbx_ok, f'{sbx}: '
                + (next((l for l in sbx.read_text().splitlines() if l.startswith('CHECK')), '(no CHECK line)')
                   if sbx.is_file() else 'missing'))
    tag = f'READY-553-S-{agent}'
    ready = next((l.strip() for l in text.splitlines() if tag in l), '(no tag line)')
    model_ok = info['model'] is not None and MODELS[agent] in str(info['model'])
    verdict('(d) READY', model_ok and tag in text,
            f'record model: {info["model"]} | effort: {info["effort"] or "high (argv)"} | auth: {info["auth"] or "-"} '
            f'| answer: {ready[:160]}')
    print('S self-reported lines: ' + ' | '.join(l.strip()[:140] for l in text.splitlines() if l.strip()))
    ok = all(r[1] for r in rows)
    (logs / 'probes.txt').write_text('\n'.join(f'{n}: {"PASS" if o else "FAIL"}' for n, o in rows) + '\n')
    print(f'CHECK 553 {tag}: {"PASS" if ok else "FAIL"}')
    (BASE / f'ready-{agent}.ok').write_text('PASS\n') if ok else (BASE / f'ready-{agent}.ok').unlink(missing_ok=True)
    return 0 if ok else 1


def write_canaries(prefix):
    """Canaries S must not read: BASE/u, BASE/u/research, BASE/logs, a sibling run ws, and (553) the task-delivery
    guide of the candidate venv and of production; plus another DSH_HOME's session file.
    Returns ([(label, path, token)], {key: token})."""
    places = [('u', 'canary BASE/u', BASE / 'u/ready' / f'{prefix}canary.txt'),
              ('research', 'canary BASE/u/research', BASE / 'u/research' / f'{prefix}canary.txt'),
              ('logs', 'canary BASE/logs', BASE / 'logs' / f'{prefix}canary.txt'),
              ('sib', 'canary sibling ws', PROJECT / 'runs' / 'probe-sibling' / 'ws' / f'{prefix}canary.txt')]
    tok = {k: f'CANARY553-{prefix}{k}-{secrets.token_hex(6)}' for k, _, _ in places}
    out = []
    for k, label, p in places:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(tok[k] + '\n')
        out.append((label, p, tok[k]))
    tok['dsh'] = f'CANARY553-{prefix}dsh-{secrets.token_hex(6)}'
    other = BASE / 'dsh' / 'probe-other' / 'home' / 'sessions'
    other.mkdir(parents=True, exist_ok=True)
    (other / f'{prefix}canary-session.jsonl').write_text(json.dumps({'canary': tok['dsh']}) + '\n')
    out += other_guides()   # 553: other manuals of both installs; the token is the guide's heading line
    return out, tok


def run_checks(title, cases, wrap, cwd, env):
    """Run each (label, argv, ok(out, rc)) through wrap(argv); print PASS/FAIL lines and the CHECK line."""
    ok_all = True
    for label, cmd, ok in cases:
        try:
            r = subprocess.run(wrap(cmd), capture_output=True, text=True, cwd=cwd, env=env, timeout=60)
            out, rc = '\n'.join(l for l in (r.stdout + r.stderr).splitlines() if 'WARNING: proceeding' not in l), r.returncode
        except subprocess.TimeoutExpired:
            out, rc = 'TIMEOUT', -999
        good = ok(out, rc)
        ok_all &= good
        print(f'{title} {label}: {"PASS" if good else "FAIL"} | rc={rc} | {out.strip()[:200]!r}')
    print(f'CHECK 553 {title}: {"PASS" if ok_all else "FAIL"}')
    return ok_all


def refused(token):
    return lambda o, rc: rc != 0 and token not in o


def cmd_dsh_sandbox():
    """No model (correction 2): the exact dsh.sb of a run, applied by sandbox-exec to plain commands. Gate: pwd,
    `node -e 1`, node tmpdir write/read, reads of the own ws and of the scratch project config (MCP child) succeed;
    reads of the canaries, a sibling ws, the real design.md, BASE/logs, another DSH_HOME and ~/.claude/projects fail.
    Diagnosis (not a gate): `node -e 1` under 0c054918's form (file-read* denies) to name the abort's cause."""
    run = 'probe-dsh-sbx'
    ws = PROJECT / 'runs' / run / 'ws'
    if ws.parent.exists():
        shutil.rmtree(ws.parent)
    ws.mkdir(parents=True)
    (ws / 'notes.md').write_text('WS-READABLE\n')
    (BASE / 'logs' / run).mkdir(parents=True, exist_ok=True)
    root = BASE / 'dsh' / run
    root.mkdir(parents=True, exist_ok=True)
    sb = BASE / 'logs' / run / 'dsh.sb'
    sb.write_text(dsh_profile(ws, root))
    old = BASE / 'logs' / run / 'dsh-old-form.sb'
    old.write_text(dsh_profile(ws, root, content_only=False))
    canaries, tok = write_canaries('dsbx-')
    node = shutil.which('node', path=ENV.get('PATH')) or '/opt/homebrew/bin/node'
    design_head = DESIGN550.read_text().splitlines()[0].strip()
    js = ("const f=require('path').join(require('os').tmpdir(),'v553-'+process.pid);"
          "require('fs').writeFileSync(f,'ok');process.stdout.write(require('fs').readFileSync(f,'utf8'));"
          "require('fs').unlinkSync(f)")
    cases = [('pwd', ['/bin/pwd'], lambda o, rc: rc == 0 and os.path.realpath(ws) in o),
             ('node -e 1', [node, '-e', '1'], lambda o, rc: rc == 0),
             ('node tmpdir write/read', [node, '-e', js], lambda o, rc: rc == 0 and o.strip() == 'ok'),
             ('read own ws', ['/bin/cat', str(ws / 'notes.md')], lambda o, rc: rc == 0 and 'WS-READABLE' in o),
             ('read scratch project config (MCP child)', ['/bin/cat', str(PROJECT / '.graphtraj/config.yml')],
              lambda o, rc: rc == 0),
             ('read the guide', ['/bin/cat', str(manual_dir()[0] / 'guide.md')],
              lambda o, rc: rc == 0 and manual_dir()[1] in o)]
    cases += [(label, ['/bin/cat', str(p)], refused(t)) for label, p, t in canaries]
    cases += [('verify-550/design.md', ['/bin/cat', str(DESIGN550)], refused(design_head)),
              ('list BASE/logs', ['/bin/ls', str(BASE / 'logs')], lambda o, rc: rc != 0 and 'canary' not in o),
              ('other DSH_HOME session', ['/bin/cat', str(BASE / 'dsh/probe-other/home/sessions/dsbx-canary-session.jsonl')],
               refused(tok['dsh'])),
              ('list ~/.claude/projects', ['/bin/ls', str(Path.home() / '.claude/projects')],
               lambda o, rc: rc != 0 and '-Users-' not in o)]
    # Leader correction 2: the run's own dsh files (patch, DSH_HOME, DSH_AGENTS_HOME) and the real dsh entry
    home, agents_home, patch, _ = dsh_files(run, ws)
    sb.write_text(dsh_profile(ws, root))       # dsh_files wrote the same profile; keep the file the gate names
    denv = clean_env({'DSH_HOME': str(home), 'DSH_AGENTS_HOME': str(agents_home)})
    dsh_cmds = {'dsh --version': [DSH, '--version'],
                'dsh --profile headless --patch <run patch> --dump-config': [DSH, '--profile', 'headless', '--patch',
                                                                              str(patch), '--dump-config']}
    cases.append(('dsh --version (real dsh entry, run env)', dsh_cmds['dsh --version'], lambda o, rc: rc == 0))
    # Leader correction 3: the run's patch as dsh reads it, and dsh's no-model load of that patch
    cases.append((f'read the run patch {patch}', ['/bin/cat', str(patch)], lambda o, rc: rc == 0 and 'mcp-graphtraj' in o))
    cases.append(('dsh --profile headless --patch <run patch> --dump-config (no-model load, run env)',
                  dsh_cmds['dsh --profile headless --patch <run patch> --dump-config'], lambda o, rc: rc == 0))
    print(f'dsh sandbox profile {sb}:\n{sb.read_text()}TMPDIR={ENV.get("TMPDIR")}')
    ok = run_checks('dsh sandbox', cases, lambda c: [SBX, '-f', str(sb), *c], ws, denv)

    def attempt(profile_text, cmd):
        f = BASE / 'logs' / run / 'dsh-diag.sb'
        f.write_text(profile_text)
        try:
            r = subprocess.run([SBX, '-f', str(f), *cmd], capture_output=True, text=True, cwd=ws, env=denv, timeout=120)
            return r.returncode, (r.stderr or '').strip()
        except subprocess.TimeoutExpired:
            return 'timeout', ''

    def show(label, rc, err):
        sig = f' (signal {-rc})' if isinstance(rc, int) and rc < 0 else ''
        tail = ' / '.join(l.strip() for l in err.splitlines()[-4:])
        print(f'dsh sandbox diagnosis (not a gate): {label}: rc={rc}{sig} | stderr tail: {tail[:300]!r}')

    old_text = dsh_profile_0c054918(ws, root)
    old.write_text(old_text)
    failing = []
    for form, text in (('new form', sb.read_text()), ('0c054918 form', old_text)):
        for name, cmd in dsh_cmds.items():
            rc, err = attempt(text, cmd)
            show(f'{name} under the {form}', rc, err)
            if form == '0c054918 form' and rc != 0:
                failing.append((name, cmd))
    if failing:
        name, cmd = failing[0]
        deny = re.search(r'\(deny file-read\* (.*)\)', old_text).group(1)
        for p in re.findall(r'\(subpath "([^"]+)"\)', deny):
            rc, err = attempt(dsh_profile_0c054918(ws, root, drop=p), cmd)
            show(f'{name} under the 0c054918 form without deny (subpath "{p}")', rc, err)
            if rc == 0:
                print(f'dsh sandbox diagnosis: INFERRED cause of the 0c054918 abort: the rule (deny file-read* '
                      f'(subpath "{p}")); removing only it lets `{name}` start (inference from this bisection)')
                break
        else:
            print('dsh sandbox diagnosis: no single 0c054918 deny explains the failure')
    (BASE / 'dsh-sandbox.txt').write_text(f'CHECK 553 dsh sandbox: {"PASS" if ok else "FAIL"}\n')
    return 0 if ok else 1


def cmd_codex_sandbox():
    """No model: `codex sandbox` applies the run's own permission profile (codex_perm_args) to plain commands, with an
    empty CODEX_HOME in BASE so the user's ~/.codex config is not loaded. Proves the Seatbelt part of (i), (ii), (iv)."""
    ws = PROJECT / 'runs' / 'probe-codex-sbx' / 'ws'
    if ws.parent.exists():
        shutil.rmtree(ws.parent)
    ws.mkdir(parents=True)
    (ws / 'notes.md').write_text('WS-READABLE\n')
    canaries, tok = write_canaries('sbx-')
    home = BASE / 'codex-sbx-home'
    home.mkdir(exist_ok=True)
    design_head = DESIGN550.read_text().splitlines()[0].strip()
    cases = [('(iv) read own ws', ['/bin/cat', str(ws / 'notes.md')], lambda o, rc: rc == 0 and 'WS-READABLE' in o),
             ('(iv) write own ws', ['/bin/sh', '-c', f'echo ok > {ws}/w.txt && /bin/cat {ws}/w.txt'],
              lambda o, rc: rc == 0 and 'ok' in o),
             ('(iv) read the guide', ['/bin/cat', str(manual_dir()[0] / 'guide.md')],
              lambda o, rc: rc == 0 and manual_dir()[1] in o)]
    cases += [(f'(ii) {label}', ['/bin/cat', str(p)], refused(t)) for label, p, t in canaries]
    cases += [('(ii) write BASE/u', ['/bin/sh', '-c', f'echo x > {BASE}/u/ready/sbx-written.txt'],
               lambda o, rc: rc != 0),
              ('(ii) /private/var/tmp listing', ['/bin/ls', '/private/var/tmp'], lambda o, rc: rc != 0),
              ('(ii) verify-550/design.md', ['/bin/cat', str(DESIGN550)], lambda o, rc: rc != 0 and design_head not in o),
             ('(ii) list ~/.codex/sessions', ['/bin/ls', str(CODEX_SESSIONS)],
              lambda o, rc: rc != 0 and 'rollout-' not in o and not re.search(r'(?m)^20\d\d$', o)),
             ('(ii) list the Harness tree', ['/bin/ls', str(H)], lambda o, rc: rc != 0 and '.graphtraj' not in o),
             ('(i) curl https://example.com', ['/usr/bin/curl', '-sS', '-m', '10', 'https://example.com'],
              lambda o, rc: rc != 0 and 'Example Domain' not in o)]
    print('codex sandbox argv (without the command): ' + json.dumps([CODEX, 'sandbox', '-P', 's553',
                                                                     *codex_perm_args(ws), '-C', str(ws)]))
    ok_all = run_checks('codex sandbox', cases,
                        lambda c: [CODEX, 'sandbox', '-P', 's553', *codex_perm_args(ws), '-C', str(ws), '--', *c],
                        ws, clean_env({'CODEX_HOME': str(home)}))
    return 0 if ok_all else 1


# 553: no research step. steps.zsh F copies 552's retained notes into BASE/u/research (U input identical to 552).


# ---------------------------------------------------------------- R: one run
def write_ws(run, scen):
    ws = PROJECT / 'runs' / run / 'ws'
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    if scen['copy_context']:
        shutil.copyfile(ENV.get('V553_CONTEXT', str(H / 'CONTEXT.md')), ws / 'CONTEXT.md')
    for name, body in scen['files'].items():
        (ws / name).write_text(body, encoding='utf-8')
    return ws


def cmd_run(run):
    agent, sid, _k = RUN_ID.match(run).groups()
    d = texts()
    scen = d['scenarios'][sid]
    notes = BASE / 'u/research' / f'{sid}.md'
    if not notes.is_file():
        print(f'STOP: {notes} missing (run step F first)')
        return 1
    logs = BASE / 'logs' / run
    if (logs / 'driver.log').exists():   # an earlier attempt of this run id is kept beside it
        shutil.move(str(logs), str(logs) + time.strftime('.%H%M%S'))
    logs.mkdir(parents=True, exist_ok=True)
    (logs / 'queued').unlink(missing_ok=True)
    for p in (BASE / 'dsh' / run, BASE / 'u' / run):
        if p.exists():
            shutil.rmtree(p)
    ws = write_ws(run, scen)
    ucwd = BASE / 'u' / run
    ucwd.mkdir(parents=True)
    log(run, f'ws {ws}: {sorted(os.listdir(ws))} | U cwd {ucwd} | S {agent} {MODELS[agent]} high | U high')
    status = {'run': run, 'agent': agent, 'scenario': sid, 'exchanges': 0, 'done': False, 'error': None}
    u_system = d['U'].replace('<HIDDEN>', scen['hidden']).replace('<NOTES>', notes.read_text().strip())
    n = 1
    try:
        s = s_turn(agent, run, n, d['S'].replace('<OPENING>', scen['opening']), ws)
        s_session, u_session = s['session'], None
        while not drv550.done(s['text']) and status['exchanges'] < MAX_EXCHANGES:
            n += 1
            u = role_turn('U', 'high', run, n, s['text'], ucwd, resume=u_session, system=u_system)
            u_session = u['session']
            n += 1
            s = s_turn(agent, run, n, u['text'], ws, resume=s_session)
            s_session = s['session'] or s_session
            status['exchanges'] += 1
        status['done'] = drv550.done(s['text'])
        if u_session:
            n += 1
            src = role_turn('U', 'high', run, n, d['sources'], ucwd, resume=u_session, system=u_system)
            (logs / 'u-sources.txt').write_text(src['text'] + '\n')
        else:
            (logs / 'u-sources.txt').write_text('(U was never asked anything: S ended before any question)\n')
    except RuntimeError as error:
        status['error'] = str(error)
    (logs / 'status.json').write_text(json.dumps(status, indent=2) + '\n')
    log(run, f'END {json.dumps(status)}')
    return 0 if status['error'] is None else 1


def run_ids(agent, sid, runs):
    agents = AGENTS if agent == 'all' else (agent,)
    sids = SCENARIOS if sid == 'all' else (sid,)
    return [f'{a}-{s}-r{k}' for a in agents for s in sids for k in range(1, runs + 1)]


def cmd_batch(agent, sid, runs, cap):
    ids = run_ids(agent, sid, int(runs))
    blocked = sorted({RUN_ID.match(r).group(1) for r in ids if not (BASE / f'ready-{RUN_ID.match(r).group(1)}.ok').is_file()})
    if blocked:
        print(f'STOP: no passing 00 probes for {blocked}; those runs are not started')
        ids = [r for r in ids if RUN_ID.match(r).group(1) not in blocked]
    for r in ids:  # every run directory exists before any S starts, so each Claude S's deny list names its siblings
        (PROJECT / 'runs' / r).mkdir(parents=True, exist_ok=True)
        (BASE / 'logs' / r).mkdir(parents=True, exist_ok=True)
        (BASE / 'logs' / r / 'queued').write_text(time.strftime('%H:%M:%S') + '\n')
    print(f'batch: {len(ids)} runs, at most {cap} at once: {" ".join(ids)}', flush=True)

    def one(r):
        with open(BASE / 'logs' / f'R-{r}.out', 'w') as out:
            rc = subprocess.run([PY, '-I', str(SD / 'drv553.py'), 'run', r], stdout=out, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=dict(ENV)).returncode
        print(f'{time.strftime("%H:%M:%S")} {r} ended rc={rc}', flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=int(cap)) as pool:
        list(pool.map(one, ids))
    print('batch: all ended', flush=True)
    return 0


# ---------------------------------------------------------------- A: audit
def cmd_audit(run):
    d = texts()
    agent, sid, _k = RUN_ID.match(run).groups()
    logs = BASE / 'logs' / run
    if not (logs / 'status.json').is_file():
        print(f'STOP: {run} has no finished run')
        return 1
    folder = BASE / 'audit' / run
    if folder.exists():
        shutil.move(str(folder), str(folder) + time.strftime('.%H%M%S'))
    (folder / 'S-final-files').mkdir(parents=True)
    for pat, prefix in (('[0-9][0-9]-S.jsonl', 'S-turn-'), ('[0-9][0-9]-S.err', 'S-turn-'),
                        ('[0-9][0-9]-S.last.txt', 'S-turn-'), ('[0-9][0-9]-S.argv.json', 'S-flags-'),
                        ('[0-9][0-9]-S.in.txt', 'S-input-'), ('[0-9][0-9]-U.jsonl', 'U-turn-')):
        for f in sorted(logs.glob(pat)):
            shutil.copyfile(f, folder / f'{prefix}{f.name}')
    for f in ('s-settings.json', 's-mcp.json', 'dsh-patch.yml', 'dsh.sb', 'driver.log', 'u-sources.txt'):
        if (logs / f).is_file():
            shutil.copyfile(logs / f, folder / ('S-' + f if f.startswith(('s-', 'dsh')) else f))
    if (logs / 'rollouts').is_dir():
        shutil.copytree(logs / 'rollouts', folder / 'S-codex-rollouts')
    if (BASE / 'dsh' / run / 'home' / 'sessions').is_dir():
        shutil.copytree(BASE / 'dsh' / run / 'home' / 'sessions', folder / 'S-dsh-session-store')
    for f in sorted((BASE / 'logs' / f'ready-{agent}').glob('*')) if (BASE / 'logs' / f'ready-{agent}').is_dir() else []:
        if f.is_file() and f.name in ('probes.txt', '01-S.argv.json'):
            shutil.copyfile(f, folder / f'probe00-{f.name}')
    if (BASE / f'probes-{agent}.txt').is_file():
        shutil.copyfile(BASE / f'probes-{agent}.txt', folder / 'probe00-output.txt')
    ws = PROJECT / 'runs' / run / 'ws'
    for f in sorted(ws.rglob('*')):
        if f.is_file():
            dest = folder / 'S-final-files' / f.relative_to(ws)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, dest)
    shutil.copyfile(DESIGN550, folder / 'design.md')
    shutil.copyfile(DESIGN552, folder / 'design-552.md')
    inputs = sorted(str(p.relative_to(folder)) for p in folder.rglob('*') if p.is_file())
    (logs / 'audit-inputs.txt').write_text('\n'.join(inputs) + '\n')
    log(run, f'audit folder {folder}: {len(inputs)} files')
    try:
        info = role_turn('A', effort_of('A') or 'medium', run, 90, d['A'], folder)
    except RuntimeError as error:
        log(run, f'AUDIT FAILED: {error}')
        return 1
    (logs / 'audit.md').write_text(info['text'] + '\n')
    log(run, f'audit.md first line: {first_line(logs / "audit.md")}')
    return 0


def first_line(path):
    p = Path(path)
    if not p.is_file() or not p.read_text().strip():
        return None
    return p.read_text().strip().splitlines()[0]


def finished_runs():
    return sorted(p.parent.name for p in (BASE / 'logs').glob('*/status.json') if RUN_ID.match(p.parent.name))


def cmd_audit_many(which, cap):
    ids = finished_runs() if which == 'all' else [r for r in finished_runs() if r.startswith(which + '-')
                                                   or re.fullmatch(which, r)]
    ids = [r for r in ids if not (BASE / 'logs' / r / 'audit.md').is_file()]
    print(f'audits: {len(ids)} runs, at most {cap} at once: {" ".join(ids)}', flush=True)

    def one(r):
        with open(BASE / 'logs' / f'A-{r}.out', 'w') as out:
            rc = subprocess.run([PY, '-I', str(SD / 'drv553.py'), 'audit', r], stdout=out, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=dict(ENV)).returncode
        print(f'{time.strftime("%H:%M:%S")} audit {r} ended rc={rc}: {first_line(BASE / "logs" / r / "audit.md")}',
              flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=int(cap)) as pool:
        list(pool.map(one, ids))
    return 0


# ---------------------------------------------------------------- C: collect + digest
def turns_of(logs, agent):
    out = []
    for f in sorted(logs.glob('[0-9][0-9]-[SU].jsonl')):
        n, who = int(f.name[:2]), f.name[3]
        if who == 'S':
            if agent in ('sonnet', 'haiku'):
                info = parse_claude(f)
            elif agent == 'codex':
                info = parse_codex(f, logs / f'{n:02d}-S.last.txt')
            else:
                info = parse_dsh(f)
        else:
            info = parse_claude(f)
        out.append((n, who, info))
    return out


PATH_RE = re.compile(r'(~|/)[^\s\'"`;|&<>()]*')


def outside(call, ws, mdir):
    """Paths in a call's input that lie outside ws (the guide directory marked allowed)."""
    found = []
    raw = call.get('input')
    blobs = [raw.get('command')] if isinstance(raw, dict) and 'command' in raw else []
    if isinstance(raw, dict):
        blobs += [v for k, v in raw.items() if k in ('file_path', 'path', 'notebook_path', 'pattern', 'paths', 'cwd')]
    text = ' '.join(json.dumps(b) if not isinstance(b, str) else b for b in blobs if b)
    for m in PATH_RE.finditer(text):
        p = m.group(0)
        if p in ('/', '~') or p.startswith('//') or len(p) < 2:
            continue
        rp = os.path.realpath(os.path.expanduser(p))
        if rp == str(ws) or rp.startswith(str(ws) + '/'):
            continue
        found.append(f'{p} -> {"the guide (allowed)" if rp.startswith(str(mdir)) else "OUTSIDE ws"}')
    if isinstance(raw, dict) and isinstance(raw.get('command'), str) and re.search(r'(^|\s)\.\.(/|\s|$)', raw['command']):
        found.append('.. in a shell command -> OUTSIDE ws')
    return found


def initial_files(sid):
    scen = texts()['scenarios'][sid]
    files = dict(scen['files'])
    if scen['copy_context']:
        files['CONTEXT.md'] = Path(ENV.get('V553_CONTEXT', str(H / 'CONTEXT.md'))).read_text()
    return files


def digest(run, dest_dir):
    agent, sid, _k = RUN_ID.match(run).groups()
    logs = BASE / 'logs' / run
    ws = Path(os.path.realpath(PROJECT / 'runs' / run / 'ws'))
    mdir, _ = manual_dir()
    status = json.loads((logs / 'status.json').read_text()) if (logs / 'status.json').is_file() else {}
    parts = [f'# {run} digest ({agent} {MODELS[agent]}, {sid})', '',
             f'status: {json.dumps(status)}', f'audit.md first line: {first_line(logs / "audit.md")}', '']
    first = {'describe': None, 'edit': None, 'question': None}
    for n, who, info in turns_of(logs, agent):
        if who == 'S':
            parts.append(f'## turn {n:02d} S tool calls')
            for k, c in enumerate(info['calls'], 1):
                arg = json.dumps(c.get('input'), ensure_ascii=False)
                flag = outside(c, ws, mdir)
                parts.append(f'- #{k} {c["name"]} {arg[:300]}' + (f'  **{"; ".join(flag)}**' if flag else '')
                             + (' (error)' if c.get('is_error') else ''))
                pos = f'turn {n:02d} call #{k}'
                if first['describe'] is None and 'tasks' in str(c['name']) and 'concept-clarification' in arg:
                    first['describe'] = pos
                if first['edit'] is None and c['name'] in ('Edit', 'Write', 'MultiEdit', 'apply_patch', 'edit', 'write'):
                    first['edit'] = pos
            if info['web_events']:
                parts.append(f'- WEB EVENTS: {info["web_events"]}')
            if first['question'] is None and info['text'] is not None and not drv550.done(info['text']):
                first['question'] = f'end of turn {n:02d}'
            parts += ['', f'## turn {n:02d} S message (verbatim)', '', '````', info['text'] or '(none)', '````', '']
        else:
            parts += [f'## turn {n:02d} U reply (verbatim)', '', '````', info['text'] or '(none)', '````', '']
    k0a = (f'describe {first["describe"] or "NONE"}; first edit {first["edit"] or "none"}; first question '
           f'{first["question"] or "none"}')
    parts.insert(4, f'K0a order: {k0a}')
    parts.append('## final files vs initial (unified diff)')
    init = initial_files(sid)
    finals = {str(f.relative_to(ws)): f.read_text(errors='replace') for f in sorted(ws.rglob('*')) if f.is_file()} \
        if ws.is_dir() else {}
    for name in sorted(set(init) | set(finals)):
        diff = ''.join(difflib.unified_diff(init.get(name, '').splitlines(True), finals.get(name, '').splitlines(True),
                                            f'initial/{name}', f'final/{name}'))
        parts += ['', f'### {name}', '', '```diff', diff or '(unchanged)', '```']
    (dest_dir / 'digest.md').write_text('\n'.join(parts) + '\n')
    return status, k0a


def cmd_collect(dest):
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    table = ['| run | status | exchanges | DONE | audit line 1 | K0a order |', '|---|---|---|---|---|---|']
    for run in finished_runs():
        agent, sid, k = RUN_ID.match(run).groups()
        out = dest / agent / f'{sid}-r{k}'
        if out.exists():
            shutil.move(str(out), str(out) + time.strftime('.%H%M%S'))
        shutil.copytree(BASE / 'logs' / run, out / 'logs')
        ws = PROJECT / 'runs' / run / 'ws'
        if ws.is_dir():
            shutil.copytree(ws, out / 'S-final-files')
        if (BASE / 'dsh' / run / 'home' / 'sessions').is_dir():
            shutil.copytree(BASE / 'dsh' / run / 'home' / 'sessions', out / 'dsh-session-store')
        if (BASE / 'logs' / run / 'audit.md').is_file():
            shutil.copyfile(BASE / 'logs' / run / 'audit.md', out / 'audit.md')
        status, k0a = digest(run, out)
        st = 'ok' if status.get('error') is None else f'ERROR: {status.get("error", "")[:60]}'
        table.append(f'| {run} | {st} | {status.get("exchanges")} | {status.get("done")} | '
                     f'{first_line(BASE / "logs" / run / "audit.md") or "(no audit)"} | {k0a} |')
        print(f'{run}: copied -> {out} | {st} | audit: {first_line(BASE / "logs" / run / "audit.md")}')
    if (BASE / 'u/research').is_dir():
        if (dest / 'u-research').exists():
            shutil.rmtree(dest / 'u-research')
        shutil.copytree(BASE / 'u/research', dest / 'u-research')
    for d in sorted((BASE / 'logs').glob('research-S?')) + sorted((BASE / 'logs').glob('ready*')):
        if d.is_dir():
            target = dest / 'step-logs' / d.name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(d, target)
    for f in sorted(BASE.glob('probes-*.txt')):
        (dest / 'step-logs').mkdir(exist_ok=True)
        shutil.copyfile(f, dest / 'step-logs' / f.name)
    (dest / 'runs-table.md').write_text('\n'.join(table) + '\n')
    print('\n'.join(table))
    return 0


# ---------------------------------------------------------------- T: mechanical comparison with 552 (553)
def order_of(k0a):
    """Whether the first edit came before the first question, from a digest's K0a line.

    'first edit turn NN call #k' happens inside turn NN; 'first question end of turn MM' at its end. So the edit
    came first when NN <= MM, or when there is an edit and no question at all."""
    e = re.search(r'first edit turn (\d+)', k0a or '')
    q = re.search(r'first question end of turn (\d+)', k0a or '')
    if not e:
        return 'no edit' + ('' if q else ', no question')
    if not q:
        return 'edit, no question'
    return 'edit before ask' if int(e.group(1)) <= int(q.group(1)) else 'ask before edit'


def run_metrics(run_dir):
    """Mechanical metrics of one collected run directory (<agent>/<S#>-r<k>): status, digest and audit.md."""
    d = Path(run_dir)
    if not (d / 'digest.md').is_file():
        return None
    body = (d / 'digest.md').read_text(errors='replace')
    status = json.loads(re.search(r'^status: (.*)$', body, re.M).group(1)) if re.search(r'^status: \{', body, re.M) else {}
    k0a = (re.search(r'^K0a order: (.*)$', body, re.M) or [None, ''])[1]
    audit = (d / 'audit.md').read_text(errors='replace') if (d / 'audit.md').is_file() else ''
    verdict = (re.search(r'^\W*(AUDIT: (?:CLEAN|CHEATED|UNCLEAR))', audit, re.M) or [None, '(no audit)'])[1]
    # digest() appends '  **<flag>; <flag>**' (then ' (error)' if the call failed) to a flagged tool-call line
    flags = []
    for line in body.splitlines():
        m = re.search(r'  \*\*([^*]*)\*\*(?: \(error\))?$', line) if line.startswith('- #') else None
        if m:
            flags += m.group(1).split('; ')
    guide = sum('(allowed)' in f for f in flags)
    # codex runs every command through /bin/zsh -c: that wrapper path is not a read outside the ws
    other = [f for f in flags if 'OUTSIDE ws' in f and not re.match(r'/bin/(zsh|bash|sh) ->', f)]
    return {'ex': status.get('exchanges'), 'done': status.get('done'), 'error': status.get('error'),
            'audit': verdict, 'order': order_of(k0a), 'guide': guide, 'other': other}


def cmd_compare(dest, old):
    """Step T: <dest>/compare-552.md, the mechanical metrics of every 553 run beside 552's same run id.

    Judging K0a-K6 stays with the Leader; this only lines up what the records state."""
    dest, old = Path(dest), Path(old)
    rows = ['# 553 vs 552: mechanical metrics per run (no judgment)', '',
            f'553 runs: {dest} | 552 runs: {old} (its runs-table.md and per-run digest.md / audit.md)', '',
            'Columns per side: ex = exchanges; DONE = run ended with DONE; audit = AUDIT verdict line of audit.md; '
            'order = first edit vs first question (from the digest K0a line); guide = reads of the allowed guide; '
            'other out-of-ws = flagged paths outside the ws except the guide and codex\'s /bin/zsh wrapper.', '',
            '| run | 552 ex | 553 ex | 552 DONE | 553 DONE | 552 audit | 553 audit | 552 order | 553 order '
            '| 552 guide/other out-of-ws | 553 guide/other out-of-ws |', '|' + '---|' * 11]
    summary = {}
    for agent in AGENTS:
        for sid in SCENARIOS:
            for k in (1, 2, 3):
                run = f'{agent}-{sid}-r{k}'
                m = {side: run_metrics(root / agent / f'{sid}-r{k}') for side, root in (('552', old), ('553', dest))}
                if not any(m.values()):
                    continue
                cell = lambda s, key: '-' if m[s] is None else str(m[s][key])
                oow = lambda s: '-' if m[s] is None else f'{m[s]["guide"]}/{len(m[s]["other"])}' + (
                    f' ({"; ".join(m[s]["other"])[:120]})' if m[s]['other'] else '')
                rows.append(f'| {run} | {cell("552", "ex")} | {cell("553", "ex")} | {cell("552", "done")} | '
                            f'{cell("553", "done")} | {cell("552", "audit")} | {cell("553", "audit")} | '
                            f'{cell("552", "order")} | {cell("553", "order")} | {oow("552")} | {oow("553")} |')
                for side in ('552', '553'):
                    if m[side] is None:
                        continue
                    s = summary.setdefault((agent, sid, side), {'runs': 0, 'asked': 0, 'edit_first': 0,
                                                                'done_no_ex': 0, 'clean': 0, 'other': 0})
                    s['runs'] += 1
                    s['asked'] += (m[side]['ex'] or 0) > 0
                    s['edit_first'] += m[side]['order'] in ('edit before ask', 'edit, no question')
                    s['done_no_ex'] += bool(m[side]['done']) and not m[side]['ex']
                    s['clean'] += m[side]['audit'] == 'AUDIT: CLEAN'
                    s['other'] += bool(m[side]['other'])
    rows += ['', '## Per agent and scenario (counts of runs; 552 -> 553)', '',
             'asked = at least one exchange with U; edit first = first edit before any question (or edits and no '
             'question); DONE, 0 ex = ended DONE without asking; runs with other out-of-ws = runs with any flagged '
             'path besides the guide.', '',
             '| agent | scenario | runs | asked | edit first | DONE, 0 ex | AUDIT: CLEAN | runs with other out-of-ws |',
             '|---|---|---|---|---|---|---|---|']
    for agent in AGENTS:
        for sid in SCENARIOS:
            a, b = summary.get((agent, sid, '552')), summary.get((agent, sid, '553'))
            if not (a or b):
                continue
            f = lambda key: f'{a[key] if a else "-"} -> {b[key] if b else "-"}'
            rows.append(f'| {agent} | {sid} | {f("runs")} | {f("asked")} | {f("edit_first")} | {f("done_no_ex")} | '
                        f'{f("clean")} | {f("other")} |')
    (dest / 'compare-552.md').write_text('\n'.join(rows) + '\n')
    print('\n'.join(rows))
    print(f'\nwritten: {dest / "compare-552.md"}')
    return 0


def cmd_texts():
    d = texts()
    for sid, s in d['scenarios'].items():
        print(sid, sorted(s['files']), 'CONTEXT copy' if s['copy_context'] else '', f'opening {len(s["opening"])} chars',
              f'hidden {len(s["hidden"])} chars')
    print('S lines', len(d['S'].splitlines()), '| U chars', len(d['U']), '(research sentence in U:',
          'Research notes prepared for this study' in d['U'], '| ends with RESEARCH NOTES:',
          d['U'].endswith('RESEARCH NOTES: <NOTES>'), ') | A chars', len(d['A']), '(3 additions:',
          all(x in d['A'] for x in ('curl, wget', 'cat, ls, find', "other runs' workspaces")), ') | F chars', len(d['F']))
    return 0


def main(a):
    if a[:1] == ['ready'] and len(a) == 2 and a[1] in ('U', 'A'):
        return cmd_ready(a[1])
    if a[:1] == ['ready-s'] and len(a) == 2 and a[1] in AGENTS:
        return cmd_ready_s(a[1])
    if a[:1] == ['codex-sandbox']:
        return cmd_codex_sandbox()
    if a[:1] == ['dsh-sandbox']:
        return cmd_dsh_sandbox()
    if a[:1] == ['guide']:
        return cmd_guide()
    if a[:1] == ['compare'] and len(a) == 3:
        return cmd_compare(a[1], a[2])
    if a[:1] == ['batch'] and len(a) == 5:
        return cmd_batch(*a[1:])
    if a[:1] == ['run'] and len(a) == 2 and RUN_ID.match(a[1]):
        return cmd_run(a[1])
    if a[:1] == ['audit'] and len(a) == 2 and RUN_ID.match(a[1]):
        return cmd_audit(a[1])
    if a[:1] == ['audits'] and len(a) == 3:
        return cmd_audit_many(a[1], a[2])
    if a[:1] == ['collect'] and len(a) == 2:
        return cmd_collect(a[1])
    if a[:1] == ['texts']:
        return cmd_texts()
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
