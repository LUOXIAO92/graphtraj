"""560: the graftling wheel of the new layout against a wheel built the old way. Read only.

usage: wheelcmp560.py <old-layout wheel> <new-layout wheel>

The old wheel is `pip wheel <git archive 9f962bc>/src/graftling` (package-dir {graftling = "."}); the new one is
`pip wheel <git archive of the release>` (root pyproject, package-dir {"" = "src"}). CHECK lines:

  layout files        the package files (everything under graftling/) are the same set, except the dropped documents
                      README.md and CHANGELOG.md, which the new wheel must NOT carry
  layout bytes        every shared code or data file has the same bytes, except the version files of the release
                      commit (__init__.py, dsh/package.json, pi/package.json; the plugin manifest is not packaged);
                      the shipped documents (PUBLIC_API.md, install/*.md) may differ only by their moved links
  layout entry points entry_points.txt is identical (agents, agents-mcp)
  layout metadata     METADATA headers are identical apart from Version (the long description is the README, which
                      moved; it is reported, not compared)
  layout shipped docs graftling/PUBLIC_API.md and graftling/install/*.md are shipped (GraphTraj's tests read the
                      installed copies: test_graphtraj_public_agents_api.py, test_codex_parent_uses_agents.py)
Exit 0 only when every CHECK passes.
"""
import sys
import zipfile

DROPPED = ('graftling/README.md', 'graftling/CHANGELOG.md')
VERSIONED = {'graftling/__init__.py', 'graftling/dsh/package.json', 'graftling/pi/package.json'}
SHIPPED_DOCS = ('graftling/PUBLIC_API.md', 'graftling/install/')


def load(path):
    archive = zipfile.ZipFile(path)
    info = next(n.split('/')[0] for n in archive.namelist() if n.endswith('.dist-info/METADATA'))
    files = {n: archive.read(n) for n in archive.namelist() if n.startswith('graftling/') and not n.endswith('/')}
    return archive, info, files


def headers(text):
    head = text.split('\n\n', 1)[0]
    return sorted(line for line in head.splitlines() if not line.startswith('Version:'))


def main() -> int:
    old_zip, old_info, old = load(sys.argv[1])
    new_zip, new_info, new = load(sys.argv[2])
    bad = 0

    def check(name, ok, detail=''):
        nonlocal bad
        bad += not ok
        print(f"CHECK 560 layout {name}: {'PASS' if ok else 'FAIL'}{' (' + detail + ')' if detail else ''}")

    dropped = sorted(n for n in old if n in DROPPED)
    left = sorted(n for n in new if n in DROPPED)
    only_old = sorted(set(old) - set(new) - set(dropped))
    only_new = sorted(set(new) - set(old))
    print(f'old wheel {sys.argv[1]}: {len(old)} package files | new wheel {sys.argv[2]}: {len(new)} package files')
    print(f'dropped documents (old only): {dropped}')
    check('files: same package files except the dropped documents',
          not only_old and not only_new and not left and len(dropped) == 2,
          f'only old: {only_old or "none"}; only new: {only_new or "none"}; documents still in new: {left or "none"}')
    differing = sorted(n for n in set(old) & set(new) if old[n] != new[n])
    docs = [n for n in differing if n.startswith(SHIPPED_DOCS)]
    print(f'shipped documents that differ (moved links): {docs or "none"}')
    unexpected = [n for n in differing if n not in VERSIONED and not n.startswith(SHIPPED_DOCS)]
    print(f'differing shared files: {differing}')
    check('bytes: shared files equal except the version files', not unexpected,
          f'unexpected: {unexpected or "none"}')
    old_ep = old_zip.read(f'{old_info}/entry_points.txt')
    new_ep = new_zip.read(f'{new_info}/entry_points.txt')
    print('entry points:', ' | '.join(line for line in new_ep.decode().splitlines() if '=' in line))
    check('entry points: identical', old_ep == new_ep)
    old_md = old_zip.read(f'{old_info}/METADATA').decode()
    new_md = new_zip.read(f'{new_info}/METADATA').decode()
    oh, nh = headers(old_md), headers(new_md)
    check('metadata: headers identical apart from Version', oh == nh,
          f'old only: {sorted(set(oh) - set(nh)) or "none"}; new only: {sorted(set(nh) - set(oh)) or "none"}')
    print('versions:', [l for l in old_md.splitlines() if l.startswith('Version:')],
          '->', [l for l in new_md.splitlines() if l.startswith('Version:')],
          '| long description (README) identical:', old_md.split('\n\n', 1)[-1] == new_md.split('\n\n', 1)[-1])
    guides = sorted(n for n in new if n.startswith('graftling/install/') and n.endswith('.md'))
    check('shipped docs: graftling/PUBLIC_API.md and install/*.md shipped',
          'graftling/PUBLIC_API.md' in new and len(new['graftling/PUBLIC_API.md']) > 1000 and len(guides) == 4
          and all(len(new[n]) > 500 for n in guides), f'install guides: {[n.split("/")[-1] for n in guides]}')
    print(f"RESULT 560 layout: {'PASS' if bad == 0 else 'FAIL'}")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
