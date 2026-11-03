"""Dry check of save_step.py with planted values. Nothing here reads a real ~/.zshrc: HOME is a temporary one."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent.parent
DEEPSEEK = 'sk-deepseek-planted-0123456789'
OTHER = 'planted-other-token-value-0123456789'
SHORT = 'short-value'
NOT_NAMED = 'not-a-credential-name-0123456789'
GUARDED = 'planted-guarded-interactive-0123456789'


def run(root: Path, zshrc: str, files: dict, key: str = DEEPSEEK, make_home: bool = True) -> tuple[Path, str]:
    """Save one evidence directory under a temporary HOME; return the destination and all that was printed."""
    home, evidence = root / 'home', root / 'out'
    home.mkdir(exist_ok=not make_home)
    evidence.mkdir()
    (home / '.zshrc').write_text(zshrc)
    for name, text in files.items():
        (evidence / name).write_text(text)
    environment = {'HOME': str(home), 'PATH': '/usr/bin:/bin', 'DEEPSEEK_API_KEY': key}
    done = subprocess.run([sys.executable, '-I', str(HERE / 'save_step.py'), str(evidence), str(root / 'saved'), str(root / 'answer')],
                          env=environment, capture_output=True, text=True)
    return root / 'saved', done.stdout + done.stderr + (root / 'answer').read_text()


def written(path: Path) -> bytes:
    """Return every saved byte."""
    return b''.join(item.read_bytes() for item in path.rglob('*') if item.is_file())


def main() -> int:
    """Run the cases and print one line each, naming no value."""
    results = {}
    exports = (f'export OTHER_TOKEN={OTHER}\nexport SHORT_KEY={SHORT}\nexport PLAIN_NAME={NOT_NAMED}\n'
               f'export DEEPSEEK_API_KEY={DEEPSEEK}\n')
    with tempfile.TemporaryDirectory() as directory:
        saved, printed = run(Path(directory), exports, {
            'summary.txt': 'PASS one\n', 'run.txt': 'step s code c started 20261102T000000\n', 'clean.txt': 'nothing here\n',
            'holds-other.txt': f'x={OTHER}\n', 'holds-deepseek.txt': f'y={DEEPSEEK}\n', 'holds-short.txt': f'{SHORT}\n',
            'holds-plain.txt': f'{NOT_NAMED}\n'})
        data, summary = written(saved), (saved / 'summary.txt').read_text()
        results['a file holding another key is left out, its name and variable named'] = (
            not (saved / 'holds-other.txt').exists() and 'OTHER_TOKEN' in summary and 'holds-other.txt' in summary)
        results['neither value is in any saved byte, the summary or the output'] = (
            OTHER.encode() not in data and DEEPSEEK.encode() not in data and OTHER not in printed and DEEPSEEK not in printed)
        results['the DeepSeek rule is unchanged'] = (
            not (saved / 'holds-deepseek.txt').exists() and '1 files hold the DeepSeek value' in summary)
        results['the DeepSeek value in ~/.zshrc is not reported twice'] = 'DEEPSEEK_API_KEY' not in summary
        results['a short value does not count'] = (saved / 'holds-short.txt').exists()
        results['a name not like a credential does not count'] = (saved / 'holds-plain.txt').exists()
        results['a clean file is saved'] = (saved / 'clean.txt').exists()
    with tempfile.TemporaryDirectory() as directory:
        saved, printed = run(Path(directory), exports, {'summary.txt': f'PASS leaked {OTHER}\n', 'run.txt': 'step s code c started t\n'})
        results['a summary holding a value is replaced by the lines saying why'] = (
            OTHER.encode() not in written(saved) and 'OTHER_TOKEN' in (saved / 'summary.txt').read_text())
    with tempfile.TemporaryDirectory() as directory:
        saved, printed = run(Path(directory), exports, {'run.txt': 'step s code c started t\n', 'clean.txt': 'x\n'}, key='')
        results['with no key loaded, the value in ~/.zshrc is still looked for'] = 'DEEPSEEK_API_KEY' in (saved / 'summary.txt').read_text()
    with tempfile.TemporaryDirectory() as directory:
        saved, printed = run(Path(directory), 'exit 0\n', {'summary.txt': 'PASS one\n', 'run.txt': 'step s code c started t\n',
                                                           'finished.txt': 'finished\n', 'data.txt': f'{OTHER}\n'})
        results['if the shell gives no listing, only run.txt, finished.txt and the reason are saved'] = (
            sorted(item.name for item in saved.iterdir()) == ['finished.txt', 'run.txt', 'summary.txt']
            and 'could not be looked for' in (saved / 'summary.txt').read_text())
    guarded = ('if [[ -o interactive ]]; then\n  for f in ~/.api_keys/*.sh; do source $f; done\nfi\n'
               f'export DEEPSEEK_API_KEY={DEEPSEEK}\n')
    with tempfile.TemporaryDirectory() as directory:
        keys = Path(directory) / 'home' / '.api_keys'
        keys.mkdir(parents=True)
        (keys / 'fake.sh').write_text(f'export GUARDED_API_KEY={GUARDED}\n')
        saved, printed = run(Path(directory), guarded, {
            'summary.txt': 'PASS one\n', 'run.txt': 'step s code c started t\n', 'holds-guarded.txt': f'{GUARDED}\n',
            'clean.txt': 'x\n'}, make_home=False)
        summary = (saved / 'summary.txt').read_text()
        results['a key loaded only in an interactive shell is found and its file left out'] = (
            not (saved / 'holds-guarded.txt').exists() and 'GUARDED_API_KEY' in summary and (saved / 'clean.txt').exists())
        results['the guarded value is in no saved byte, the summary or the output'] = (
            GUARDED.encode() not in written(saved) and GUARDED not in printed)
    for name, passed in results.items():
        print(('PASS ' if passed else 'FAIL ') + name)
    return 0 if all(results.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
