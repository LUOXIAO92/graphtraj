#!/bin/zsh
# Local rehearsal (Engineer only): the desktop-macos-adoption.yml build steps in a scratch clone.
# Usage: zsh build-mac.sh <scratch dir holding graphtraj/ (with graftling/ at v0.10.1 inside)>
# Caches stay under the scratch dir; no provider credential is passed; nothing is installed in /Applications.
R=$1; G=$R/graphtraj
# pip's macOS trust-store path fails inside the Engineer sandbox (SSLCertVerificationError OSStatus -26276);
# the certifi bundle works through the same proxy.
export PIP_USE_DEPRECATED=legacy-certs
# Node's fetch uses the sandbox proxy only with NODE_USE_ENV_PROXY; the default Electron cache is under the real HOME.
export NODE_USE_ENV_PROXY=1 GRAPHTRAJ_ELECTRON_CACHE=$R/electron-cache
export npm_config_cache=$R/npm-cache electron_config_cache=$R/electron-cache PIP_CACHE_DIR=$R/pip-cache
set -x
cd $G || exit 1
git rev-parse HEAD; git -C graftling rev-parse HEAD
[[ -d $R/venv ]] || /Users/luoxiao/miniconda3/bin/python3.13 -m venv $R/venv || exit 1
source $R/venv/bin/activate
python -m pip install --disable-pip-version-check ./graftling . || exit 2
which graphtraj-tool
cd desktop
npm ci --no-audit --no-fund || exit 3
npm run build || exit 4
node --test tests/*.test.cjs > $R/unit.log 2>&1; echo "unit-exit=$?"
grep -E '^ℹ (tests|pass|fail)' $R/unit.log
npm run package:mac || exit 5
ls -la dist-package
