"""503: exactly one graftling, installed from a wheel file, in a venv. Read only; run with THAT venv's python:

usage: <venv>/bin/python -I onegraft.py <venv prefix> <expected version>

CHECK lines (PASS/FAIL):
  one distribution  importlib.metadata sees exactly one 'graftling' distribution, of the expected version
  one package       site-packages holds one graftling/ directory and one graftling-*.dist-info, no egg-info/egg-link
  wheel install     INSTALLER is pip; direct_url.json, if present, names a .whl file (not a directory, not editable)
  no source link    no .pth line, __editable__ finder or egg-link names a graftling source checkout or a directory
                    holding graftling/; no sys.path entry outside the venv and its base Python holds graftling/
  imported here     graftling.__file__ lies in the venv's site-packages
  graphtraj clean   graphtraj's RECORD lists no graftling/ file (graphtraj no longer carries graftling)
"""
import importlib.metadata as md
import json
import sys
import sysconfig
from pathlib import Path

prefix, expected = Path(sys.argv[1]).resolve(), sys.argv[2]
site = Path(sysconfig.get_paths()['purelib']).resolve()
bad = 0


def check(name, ok, detail=''):
    global bad
    bad += not ok
    print(f"CHECK 503 layout {name}: {'PASS' if ok else 'FAIL'}{' (' + detail + ')' if detail else ''}")


print(f'python {sys.executable} prefix {sys.prefix} site-packages {site}')
check('python is the venv', Path(sys.prefix).resolve() == prefix, f'{sys.prefix} vs {prefix}')
dists = [d for d in md.distributions() if (d.metadata['Name'] or '').lower() == 'graftling']
check('one distribution', len(dists) == 1 and dists[0].version == expected,
      f"{len(dists)} found: {[(d.version, str(getattr(d, '_path', '?'))) for d in dists]}")
pkgs = sorted(p.name for p in site.iterdir() if p.name == 'graftling' or p.name.lower().startswith('graftling-')
              or p.name.lower().startswith('graftling.') or 'graftling' in p.name.lower() and p.suffix in ('.egg-link', '.pth'))
infos = [n for n in pkgs if n.endswith('.dist-info')]
others = [n for n in pkgs if n != 'graftling' and not n.endswith('.dist-info')]
check('one package', (site / 'graftling').is_dir() and len(infos) == 1 and not others,
      f'graftling dir: {(site / "graftling").is_dir()}; dist-info: {infos}; other graftling entries: {others or "none"}')
info = site / infos[0] if infos else None
installer = (info / 'INSTALLER').read_text().strip() if info and (info / 'INSTALLER').is_file() else None
direct = None
if info and (info / 'direct_url.json').is_file():
    direct = json.loads((info / 'direct_url.json').read_text())
url = (direct or {}).get('url', '')
editable = bool(((direct or {}).get('dir_info') or {}).get('editable'))
check('wheel install', installer == 'pip' and (direct is None or (url.endswith('.whl') and 'archive_info' in direct and not editable)),
      f'INSTALLER={installer!r} direct_url={url or "none"} editable={editable}')
links = []
for p in sorted(site.iterdir()):
    if p.suffix == '.pth' or p.name.startswith('__editable__') or p.suffix == '.egg-link':
        text = p.read_text(errors='replace') if p.is_file() else ''
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            target = Path(line) if not line.startswith('import ') else None
            hit = 'graftling' in line or (target is not None and target.is_dir() and (target / 'graftling').exists())
            if hit:
                links.append(f'{p.name}: {line[:160]}')
base = Path(sys.base_prefix).resolve()
outside = []
for entry in sys.path:
    if not entry:
        continue
    e = Path(entry).resolve()
    if e.is_relative_to(prefix) or e.is_relative_to(base):
        continue
    if (e / 'graftling').exists():
        outside.append(str(e))
check('no source link', not links and not outside, f'links {links or "none"}; sys.path entries with graftling outside the venv {outside or "none"}')
import graftling  # noqa: E402
gf = Path(graftling.__file__).resolve()
check('imported here', gf.is_relative_to(site) and graftling.__version__ == expected, f'{gf} version {graftling.__version__}')
try:
    record = md.distribution('graphtraj').read_text('RECORD') or ''
    carried = [l.split(',')[0] for l in record.splitlines() if l.startswith('graftling/')]
    check('graphtraj clean', not carried, f'{len(carried)} graftling/ files in graphtraj RECORD{": " + str(carried[:3]) if carried else ""}')
except md.PackageNotFoundError:
    check('graphtraj clean', False, 'graphtraj not installed')
print(f"503 layout: {'PASS' if bad == 0 else 'FAIL'} ({bad} failed)")
sys.exit(1 if bad else 0)
