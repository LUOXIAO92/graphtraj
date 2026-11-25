#!/bin/zsh
# R2 continued: unit checks and package:mac in a clean environment (venv on PATH as after setup-python + pip install).
R=$1; cd $R/graphtraj/desktop || exit 1
echo "env: $(env | cut -d= -f1 | sort | tr '\n' ' ')"
echo "node $(node --version) npm $(npm --version) python $(python --version 2>&1) tool $(which graphtraj-tool)"
node --test tests/*.test.cjs > $R/r2-unit.log 2>&1; echo "unit-exit=$?"
grep -E '^ℹ (tests|pass|fail|skipped|cancelled)' $R/r2-unit.log
npm run package:mac > $R/r2-package.log 2>&1; echo "package-exit=$?"
tail -5 $R/r2-package.log
ls -la dist-package
git -C $R/graphtraj status --porcelain --untracked-files=no; echo "tracked-clean-exit=$?"
