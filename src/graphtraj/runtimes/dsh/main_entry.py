"""Profile patch that lets a DSH session the user starts become GraphTraj Main.

``python -m graphtraj.runtimes.dsh.main_entry patch --write <file>`` writes one
patch row loading this installation's ``tool.mjs`` with its ``python``. Pass it
for one invocation with ``dsh --profile <name> --patch <file>``; nothing is
installed into DSH and no profile is edited.
"""

import argparse
from pathlib import Path
import sys

import yaml


def main_patch(python: Path) -> list[dict]:
    """Return the DSH profile patch for a user-started GraphTraj Main.

    Parameters
    ----------
    python:
        The Python of the GraphTraj installation. ``tool.mjs`` starts its native
        entry and MCP server with it, so the venv need not be on ``PATH``.

    Returns
    -------
    list[dict]
        One ``insert`` patch with the row ``graphtraj-main``, which does not
        collide with graftling-dsh's ``agents-host`` row.
    """
    return [{'insert': [{
        'id':     'graphtraj-main',
        'name':   str(Path(__file__).with_name('tool.mjs')),
        'config': {'python': str(python)},
    }]}]


def main() -> None:
    """Print, or with ``--write`` write, this installation's Main patch."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['patch'])
    parser.add_argument('--write', type=Path, help='Write the patch to this file.')
    options = parser.parse_args()

    # absolute(), not resolve(): a venv's python is a symlink to the base Python,
    # and only the venv path imports this installation.
    text = yaml.safe_dump(main_patch(Path(sys.executable).absolute()), sort_keys=False)
    if options.write is None:
        print(text, end='')
        return
    options.write.parent.mkdir(parents=True, exist_ok=True)
    options.write.write_text(text, encoding='utf-8')
    print(options.write.absolute())


if __name__ == '__main__':
    main()
