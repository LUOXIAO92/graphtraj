# Task 621 local rehearsal (Engineer sandbox, 2026-11-25)

Scratch: `$TMPDIR/r621b` (= /tmp/claude-501/r621b), clone of e941ba53 (dev 4b71012c merged into the Task branch) with
graftling v0.10.1 (82e9d12b) cloned into `graftling/`. No /Applications, no real HOME/.graphtraj, no provider credential.

| Step | Command | Outcome | Log |
|---|---|---|---|
| install, npm ci, build, unit | `zsh scripts/verify-621/rehearsal/scripts/build-mac.sh $TMPDIR/r621b` (first run, before the NODE_USE_ENV_PROXY/GRAPHTRAJ_ELECTRON_CACHE lines were added) | pip install, npm ci, `npm run build` passed; unit 95/97; `package:mac` failed: `getaddrinfo ENOTFOUND github.com` (Node fetch ignores the proxy without NODE_USE_ENV_PROXY) | build-mac-1.log, unit.log |
| package | `NODE_USE_ENV_PROXY=1 GRAPHTRAJ_ELECTRON_CACHE=$R/electron-cache npm run package:mac` | passed: dist-package/GraphTraj-darwin-arm64.zip (+ .json) | package-mac-2.log |
| boundary probe | `PATH=$R/venv/bin:$PATH node tests/probe-boundary.mjs $R/bnd` (scripts/probe-boundary.mjs, GRAPHTRAJ_CLI_CONNECTION and GRAPHTRAJ_PARENT_ALIAS unset) | see boundary-probe.txt | boundary-probe.txt |
| packaged GUI | `scripts/probe-electron.mjs` via Playwright, and the binary directly | BLOCKED by the sandbox | sandbox-gui.txt |
| renderer fallback | `scripts/probe-chrome.mjs` with system Chrome; Playwright Chromium download | BLOCKED | sandbox-gui.txt |

Unit failures (2/97) are caused by this Engineer environment, not by the port:
- tests/projects.test.cjs:47 and tests/settings.test.cjs:26 both fail in `fixtures.cjs:11 operate` → `makeProject`
  with `{"failed":true,"error":"Agent Runner must be invoked from the Harness Project Root or this Session's Worktree."}`.
- Emitted by src/graphtraj/interfaces/hosted_cli.py:89-92 (`invalid-config`): graphtraj-tool took the hosted path because this
  Agent Session's environment carries its hosted-connection markers. The boundary probe with GRAPHTRAJ_CLI_CONNECTION and
  GRAPHTRAJ_PARENT_ALIAS unset ran the same fixtures without error. CI has no such markers (adoption.mjs:640-641 also refuses them),
  so CI is not affected; that last point is an inference.
