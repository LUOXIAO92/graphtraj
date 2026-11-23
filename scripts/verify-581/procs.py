"""Task 581: what ran under one host Session, read from the process table (never from canned text).

usage:
  procs.py watch <pid> <out>              until <pid> exits, every 0.3 s: each descendant of <pid> whose command line
                                          names graftling, one line per new (pid, command) to <out>; and for EVERY
                                          descendant, once, the NAMES of its credential-like environment variables
                                          to <out>.env ("<pid> <n variables> <names|->  <command, 120 chars>");
                                          values are dropped before anything is written
  procs.py judge <out> <prefix> <label>   PASS when at least one Python process ran graftling and every such
                                          process's interpreter (argv[0]) lies under <prefix> (the uv install)
  procs.py creds <out.env> <user names file> <allowed,...> <label> [<kind>]
                                          FAIL when a descendant holds a credential-like name that is not allowed
                                          and either the Session's Main process (the <kind> host: claude -p,
                                          dsh --profile, pi -p) holds it too, or it names a provider credential
                                          (PROVIDER below); another name a host set inside the tree is a NOTE.
                                          If the Main is not identified, your shell's names (the file) count instead
  procs.py names                          stdin: `env` output; prints the credential-like names, one per line
  procs.py pattern                        prints CRED (for steps.zsh's clean(), which matches upper-cased names)
Only descendants of the Session are kept, so other processes on the machine (another Harness, an IDE) never count.
A Python process is one whose argv[0] file name starts with 'python'.
"""
import os, re, subprocess, sys, time

# Credential-like variable names (user decision for 581: DeepSeek is the only provider). Upper case; matched
# case-insensitively.
CRED = ('API_KEY|_KEY$|TOKEN|SECRET|PASSWORD|CREDENTIAL|_BASE_URL$|^OPENAI|^OPENROUTER|^OPEN_ROUTER|^OPENCODE|'
        '^GEMINI|^GOOGLE_|^AWS_|^AZURE_|^HF_|^MISTRAL|^GROQ|^XAI|^ALI_|^DASHSCOPE|^MOONSHOT|^ZHIPU|^ANTHROPIC_API')
CRED_RE = re.compile(CRED, re.I)
# Names that are a provider credential or endpoint whoever set them.
PROVIDER = re.compile('API_KEY|_BASE_URL$|^OPENAI|^OPENROUTER|^OPEN_ROUTER|^OPENCODE|^GEMINI|^GOOGLE_|^AWS_|^AZURE_|'
                      '^HF_|^MISTRAL|^GROQ|^XAI|^ALI_|^DASHSCOPE|^MOONSHOT|^ZHIPU|^ANTHROPIC|OAUTH', re.I)
ENV_NAME = re.compile(r'(?:^| )([A-Za-z_][A-Za-z0-9_]*)=')


def ps(flags):
    out = subprocess.run(['ps', flags, '-o', 'pid=,ppid=,command='], capture_output=True, text=True).stdout
    rows = {}
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            rows[int(parts[0])] = (int(parts[1]), parts[2])
    return rows


def descendants(rows, root):
    children = {}
    for pid, (ppid, _) in rows.items():
        children.setdefault(ppid, []).append(pid)
    found, todo = set(), [root]
    while todo:
        for child in children.get(todo.pop(), []):
            if child not in found:
                found.add(child)
                todo.append(child)
    return found


def env_names(command, with_env):
    """The names in `ps -E`'s environment part (after the command), never the values."""
    if not with_env.startswith(command):
        return None
    return ENV_NAME.findall(with_env[len(command):])


def watch(pid, out):
    seen, envs = set(), set()
    with open(out, 'a') as sink, open(out + '.env', 'a') as env_sink:
        while True:
            try:
                os.kill(pid, 0)
            except OSError:
                return 0
            rows, with_env = ps('-axww'), ps('-axwwE')
            for child in sorted(descendants(rows, pid)):
                command = rows[child][1]
                if 'graftling' in command and (child, command) not in seen:
                    seen.add((child, command))
                    sink.write(f'{child} {command}\n')
                    sink.flush()
                if child not in envs and child in with_env:
                    names = env_names(command, with_env[child][1])
                    if names is None:
                        continue
                    envs.add(child)
                    creds = sorted({n for n in names if CRED_RE.search(n)})
                    env_sink.write(f'{child} {len(names)} {",".join(creds) or "-"}  {command[:120]}\n')
                    env_sink.flush()
            time.sleep(0.3)


def judge(out, prefix, label):
    prefix = prefix.rstrip('/') + '/'
    lines = [l.rstrip('\n') for l in open(out, errors='replace')] if os.path.exists(out) else []
    pythons = []
    for line in lines:
        command = line.split(' ', 1)[1] if ' ' in line else ''
        argv0 = command.split(' ', 1)[0]
        if os.path.basename(argv0).startswith('python'):
            pythons.append((argv0, command))
    for argv0, command in sorted(set(pythons)):
        print(f'  {label} graftling process: {command[:220]}')
    outside = sorted({a for a, _ in pythons if not a.startswith(prefix)})
    ok = bool(pythons) and not outside
    if not pythons:
        print(f'FAIL: {label}: no Python process running graftling was seen under the Session ({len(lines)} graftling '
              f'command line(s) sampled in {out})')
    elif outside:
        print(f'FAIL: {label}: graftling ran from an interpreter outside the uv install {prefix}: {outside}')
    else:
        print(f'PASS: {label}: every Python process running graftling ({len(set(pythons))}) started from the uv '
              f'install: {sorted({a for a, _ in pythons})}')
    return 0 if ok else 1


def is_main(kind, command):
    """The Session's own host process: `claude -p ...`, `dsh --profile ...` or `pi -p ...` (node scripts included)."""
    tokens = command.split()
    if not tokens:
        return False
    first = os.path.basename(tokens[0])
    prog = os.path.basename(tokens[1]) if first == 'node' and len(tokens) > 1 else first
    flag = {'claude': '-p', 'pi': '-p', 'dsh': '--profile'}.get(kind)
    return prog == kind and flag in tokens[:4]


def creds(out, user_file, allowed, label, kind=''):
    """A non-allowed name FAILs when the Session's Main process itself holds it (it came in from outside) or when it
    is a provider name (PROVIDER); otherwise a host set it inside the tree (e.g. Claude Code's own
    CLAUDE_CODE_MESSAGING_TOKEN for its plugin processes) and it is a NOTE. Without an identified Main process, the
    stricter rule applies: your shell's names (user_file) count as inherited."""
    allowed = set(filter(None, allowed.split(',')))
    user = set(open(user_file).read().split()) if os.path.exists(user_file) else set()
    rows = [l.rstrip('\n') for l in open(out, errors='replace')] if os.path.exists(out) else []
    read = [r for r in rows if r.split(' ', 2)[1:2] != ['0']]
    main = next((r for r in rows if is_main(kind, r.split(' ', 3)[3] if len(r.split(' ', 3)) > 3 else '')), None)
    if main:
        pid, _, names, _ = main.split(' ', 3)
        inherited = set() if names == '-' else set(names.split(','))
        print(f'  {label}: the Main process is pid {pid}; names it holds count as inherited: {sorted(inherited)}')
    else:
        inherited = user
        print(f'  {label}: the Main process ({kind or "kind not given"}) was not identified in {out}; stricter rule: '
              f'any name from your shell counts as inherited')
    leaks, notes = [], []
    for row in rows:
        pid, count, names, *command = row.split(' ', 3)
        for name in ([] if names == '-' else names.split(',')):
            if name in allowed:
                continue
            (leaks if name in inherited or PROVIDER.search(name) else notes).append(f'{name} (pid {pid}: {" ".join(command).strip()[:80]})')
        print(f'  {label} process {pid}: {count} variables; credential-like names: {names}  | {" ".join(command).strip()[:90]}')
    for note in notes:
        print(f'NOTE: {label}: a host set a token-like name inside the Session (not held by the Main process, or not in your shell when no Main was identified) and not a provider credential: {note}')
    if not read:
        print(f'FAIL: {label}: no descendant environment could be read ({len(rows)} rows in {out})')
        return 1
    if leaks:
        print(f'FAIL: {label}: credential names other than {sorted(allowed)} under the Session: {leaks}')
        return 1
    print(f'PASS: {label}: {len(read)} descendant environment(s) read; credential-like names only from {sorted(allowed)}')
    return 0


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[:1] == ['watch'] and len(a) == 3:
        sys.exit(watch(int(a[1]), a[2]))
    if a[:1] == ['judge'] and len(a) == 4:
        sys.exit(judge(a[1], a[2], a[3]))
    if a[:1] == ['creds'] and len(a) in (5, 6):
        sys.exit(creds(*a[1:]))
    if a == ['names']:
        print('\n'.join(sorted({m.group(1) for m in re.finditer(r'^([A-Za-z_][A-Za-z0-9_]*)=', sys.stdin.read(), re.M)
                                if CRED_RE.search(m.group(1))})))
        sys.exit(0)
    if a == ['pattern']:
        print(CRED)
        sys.exit(0)
    print(__doc__)
    sys.exit(2)
