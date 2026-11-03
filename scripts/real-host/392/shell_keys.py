"""The credential-named variables the user's shell holds, read in both forms ~/.zshrc can give them.

A plain `source ~/.zshrc` misses keys loaded only under `[[ -o interactive ]]`, so the listing is the union of
that form and an interactive shell's. Values stay in this process's memory: on no command line, in no file,
and never printed.

  python -I shell_keys.py names    prints the NAMES of variables in this environment that a step must drop:
                                   any of those names, or any value equal to one of those values,
                                   except DEEPSEEK_API_KEY.
"""
import os
import re
import subprocess
import sys

CREDENTIAL_NAME = re.compile('KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL', re.IGNORECASE)
SHORTEST_VALUE = 16
FORMS = {
    'source ~/.zshrc': ['/bin/zsh', '-c', 'source ~/.zshrc >/dev/null 2>&1; /usr/bin/env -0'],
    # The interactive shell's own output is discarded; only env -0 reaches descriptor 3, which is the pipe.
    'zsh -i': ['/bin/zsh', '-c', 'exec 3>&1; /bin/zsh -i -c "/usr/bin/env -0 >&3" >/dev/null 2>&1 </dev/null'],
}


def listing(command: list[str]) -> list[tuple[str, bytes]] | None:
    """Return one form's credential-named variables; ``None`` if that shell gave no listing."""
    try:
        done = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if not done.stdout:
        return None
    found = []
    for entry in done.stdout.split(b'\0'):
        name, separator, value = entry.partition(b'=')
        text = name.decode(errors='replace')
        if separator and len(value) >= SHORTEST_VALUE and CREDENTIAL_NAME.search(text):
            found.append((text, value))
    return found


def shell_values() -> tuple[list[tuple[str, bytes]] | None, list[str]]:
    """Return the union of both forms, and the forms that gave no listing; the union is ``None`` if any failed."""
    union, failed = set(), []
    for form, command in FORMS.items():
        found = listing(command)
        if found is None:
            failed.append(form)
        else:
            union.update(found)
    return (None if failed else sorted(union)), failed


def names_to_drop() -> list[str]:
    """Return the names in this environment that hold a shell key, by name or by value, except DeepSeek's."""
    found, _ = shell_values()
    found = found or []
    own = os.environ.get('DEEPSEEK_API_KEY', '').encode()
    names = {name for name, _ in found}
    values = {value for _, value in found if value != own}
    present = ((key.decode(errors='replace'), value) for key, value in os.environb.items())
    return sorted(key for key, value in present
                  if key != 'DEEPSEEK_API_KEY' and (key in names or value in values))


if __name__ == '__main__':
    if sys.argv[1:] == ['names']:
        print(' '.join(names_to_drop()))
    else:
        raise SystemExit('usage: shell_keys.py names')
