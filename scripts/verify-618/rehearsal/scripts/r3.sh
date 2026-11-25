#!/bin/zsh
# R3: the pip wheel call shared by package-linux.mjs and package-win.mjs, on the graftling root.
R=$1; export PIP_USE_DEPRECATED=legacy-certs PIP_CACHE_DIR=$R/pip-cache
/Users/luoxiao/miniconda3/bin/python3.13 -m venv $R/venv-wheel && $R/venv-wheel/bin/python -m pip install -q setuptools==80.9.0 wheel==0.45.1 || exit 1
W=$R/venv-wheel/bin/python
rm -rf $R/wheels-real $R/wheels-stub $R/graftling-stub
echo '$ pip wheel --no-deps --no-build-isolation <graftling root (archive v0.10.1)> <graphtraj clone e96adbb2>'
$W -m pip wheel -q --no-deps --no-build-isolation --wheel-dir $R/wheels-real $R/graftling $R/graphtraj || exit 2
ls $R/wheels-real
$W - $R/wheels-real <<'PY'
import sys, zipfile, pathlib
for whl in sorted(pathlib.Path(sys.argv[1]).glob('graftling-*.whl')):
    z = zipfile.ZipFile(whl)
    for i in z.infolist():
        if i.filename.endswith('PUBLIC_API.md') or '/install/' in i.filename:
            print(f'  {i.file_size:7d}  {i.filename}')
PY
echo '$ git -c core.symlinks=false clone --branch v0.10.1 <graftling repo> graftling-stub'
git -c core.symlinks=false clone -q --branch v0.10.1 /Users/luoxiao/workspace/you-are-a-product-architect-delivery/graftling $R/graftling-stub 2>&1 | grep -v detached
ls -la $R/graftling-stub/src/graftling/PUBLIC_API.md $R/graftling-stub/src/graftling/install; echo "stub content: $(cat $R/graftling-stub/src/graftling/PUBLIC_API.md)"
$W -m pip wheel -q --no-deps --no-build-isolation --wheel-dir $R/wheels-stub $R/graftling-stub; echo "stub wheel exit=$?"
$W - $R/wheels-stub <<'PY'
import sys, zipfile, pathlib
for whl in sorted(pathlib.Path(sys.argv[1]).glob('graftling-*.whl')):
    z = zipfile.ZipFile(whl); print(whl.name)
    hits = [i for i in z.infolist() if i.filename.endswith('PUBLIC_API.md') or 'install' in i.filename.split('/')[1:2]]
    for i in hits: print(f'  {i.file_size:7d}  {i.filename}')
    print('  install/*.md entries:', sum('/install/' in i.filename for i in z.infolist()))
PY
