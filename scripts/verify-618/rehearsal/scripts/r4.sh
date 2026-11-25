#!/bin/zsh
# R4: desktop-win-adoption.yml's pytest selection with its install recipe (pinned list + ./graftling + -e .), from the clone root.
R=$1; export PIP_USE_DEPRECATED=legacy-certs PIP_CACHE_DIR=$R/pip-cache PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONUTF8=1
cd $R/graphtraj || exit 1
/Users/luoxiao/miniconda3/bin/python3.13 -m venv $R/venv-win && source $R/venv-win/bin/activate || exit 1
python -m pip install -q --no-deps pip==25.3 setuptools==80.9.0 wheel==0.45.1 packaging==25.0 pytest==8.3.5 iniconfig==2.1.0 pluggy==1.6.0 colorama==0.4.6 click==8.1.8 PyYAML==6.0.2 websockets==15.0.1 || exit 2
python -m pip install -q --no-deps --no-build-isolation ./graftling || exit 3
python -m pip install -q --no-deps --no-build-isolation -e . || exit 4
python -m pip freeze
python -m pytest -p no:cacheprovider -q -rs tests/test_desktop_settings.py tests/test_windows_desktop.py tests/test_desktop_activity.py::test_windows_adoption_fixture_projects_retired_content_and_usage
echo "pytest-exit=$?"
git status --porcelain --untracked-files=no; echo "tracked-clean: $(git status --porcelain --untracked-files=no | wc -l) changed"
git status --porcelain --ignored | grep -v '^?? graftling/' | head
