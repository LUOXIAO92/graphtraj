#!/bin/zsh
# R2: emulate desktop-macos-adoption.yml steps in order (cwd/working-directory as in the workflow).
R=$1; G=$R/graphtraj
export npm_config_cache=$R/npm-cache electron_config_cache=$R/electron-cache PIP_CACHE_DIR=$R/pip-cache
set -x
cd $G || exit 1
git rev-parse HEAD; git status --porcelain --untracked-files=no
/Users/luoxiao/miniconda3/bin/python3.13 -m venv $R/venv-mac || exit 1
source $R/venv-mac/bin/activate
python --version
# step "Install the native GraphTraj tool" (working-directory: .)
python -m pip install --disable-pip-version-check ./graftling . || exit 2
which graphtraj-tool
python -c 'import graftling, graphtraj, importlib.metadata as m; print("graftling", m.version("graftling"), graftling.__file__); print("graphtraj", graphtraj.__file__)'
head -3 $R/venv-mac/bin/graphtraj-tool
$R/venv-mac/bin/python -c 'import importlib.metadata as m; print("graphtraj-tool interpreter resolves graftling", m.version("graftling"))'
graphtraj-tool --help 2>&1 | head -5
cd desktop
npm ci --no-audit --no-fund || exit 3
npm run build || exit 4
node --test tests/*.test.cjs 2>&1 | tail -15; echo "unit-exit=${pipestatus[1]}"
npm run package:mac || exit 5
ls -la dist-package
