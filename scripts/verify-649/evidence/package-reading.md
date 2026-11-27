# Task 649 phase A: DSH package reading (before the Windows CI probe)

Read 2026-11-27 by the Engineer on macOS arm64 (Node 26.5.0, npm 12.2.1), from the npm registry
(`npm view`) and from an install made only for reading (`npm install --ignore-scripts
@deepseek-ai/dsh@0.2.2-rc.5` into a scratch directory outside the Harness, 674 packages). No install
script was run and no DSH process was given a credential. The registry was reachable only with this
session's sandbox allowing `registry.npmjs.org`; the first attempt without it failed with
`npm error code E403 ... 403 not in this command's allowed_domains` (emitted by the sandbox proxy).

Facts are marked **F**, inferences **I**. The Windows answer itself comes from the CI probe
(`.github/dsh_windows_probe.py`, job `dsh-windows-probe`); this file is what can be read without Windows.

## 1. Which DSH graftling supports

- **F** `src/graftling/dsh/settings.py:18` at graftling eb5ad8e: `MINIMUM_VERSION = '0.2.0-rc.2'`; older or
  unreadable versions are refused (`dsh_version_refusal`), newer ones are not.
- **F** graftling `README.md` (eb5ad8e) names DSH 0.2.2-rc.5 as the version its provider sources and launch
  preparation were shown against ("an installed DSH 0.2.2-rc.5, without a model turn"); `docs/install/dsh.md`
  says "The sources and real runs are DSH `0.2.2-alpha.2`" and records a 569 walk with 0.2.2-rc.5.
- **F** Task 608's rehearsal output records an installed DSH 0.2.2-rc.5; Task 613's records name no other DSH
  version (a search of both Tasks' team records for `0.2.x` versions finds only 0.2.2-rc.5).
- Probed: **0.2.2-rc.5** (README's tested version; the registry's `latest` and `next`).

## 2. Registry (`npm view`, 2026-11-27)

| | 0.2.2-rc.5 | 0.2.3-alpha.2 (newest published) |
|---|---|---|
| dist-tag | `latest`, `next` | `alpha` |
| published | 2026-11-18T13:17:23Z | 2026-11-22T09:57:12Z |
| `engines.node` | `>=24.9.0` | `^24.22.3 \|\| >=26.13.1` |
| `os` / `cpu` | none | none |
| `optionalDependencies` | none | none |
| `scripts` | `{}` | `{}` |
| `bin` | `dsh: lib/bin.js` | `dsh: lib/bin.js` |
| files / unpacked | 536 / 6,230,712 B | 652 / 6,699,211 B |

**F** 0.2.3-alpha.2 against 0.2.2-rc.5 adds the dependencies `@deepseek-ai/dsh-cua-mcp`,
`dsh-session-persistence-sqlite` and `dsh-timeline`, and drops `dsh-personalized-recommendations`.
**F** Node 24.22.3 (nodejs.org dist index: 2026-11-10, LTS "Krypton", ships `win-x64-zip`/`-msi`/`-exe`) satisfies
both `engines` ranges; the CI job pins it.

## 3. Installed tree (0.2.2-rc.5, read only)

**Install scripts (F).** `@deepseek-ai/dsh` itself has none. In its tree: `node-pty@1.2.0-beta.15`
(`install: node scripts/prebuild.js || node-gyp rebuild`, `postinstall`), `koffi@3.1.1` (`install: node
./cnoke.cjs ... --prebuild`), `protobufjs@7.6.6` (`postinstall`), `@deepseek-ai/dsh-subprocess-local`
(`postinstall: node scripts/ensure-spawn-helper.mjs`, which only `chmod 0755`s node-pty's
`prebuilds/<platform>-<arch>/spawn-helper` when that file exists). **I** On win32-x64 node-pty's prebuild
exists, so `node-gyp` should not be needed, and the spawn-helper script finds no file and does nothing.

**Native code with a win32-x64 build in the package (F).** `node-pty/prebuilds/win32-x64/conpty.node`,
`conpty_console_list.node`, `conpty/conpty.dll`, `conpty/OpenConsole.exe`;
`@deepseek-ai/libreoffice-kit/frame-forwarding/prebuilds/win32-x64/frame-forwarding.node`.

**Optional platform sets with a win32-x64 member (F).** `@vscode/ripgrep` (`-win32-x64`), `koffi`
(`@koromix/koffi-win32-x64`), `sherpa-onnx-node` (`sherpa-onnx-win-x64`), `node-addon-require-builtin`
(`-win32-x64-msvc`), `sharp` (`@img/sharp-win32-x64`), `@deepseek-ai/libreoffice-kit` (`-win32-x64`).

**Optional platform sets with no Windows member (F).**
- `@deepseek-ai/node-addon-system@0.1.2` ("Prebuilt system primitives: a Linux Landlock launcher and
  asynchronous POSIX flock"): darwin-arm64/x64 and linux-x64/arm64 only. Its `lib/flock.js` is lazy ("importing
  it does not load a native addon") and throws `ERR_FLOCK_UNSUPPORTED_PLATFORM` when called on any platform other
  than linux or darwin. Used by `dsh-session-persistence-jsonl` (flock), `dsh-sandbox-local` (landlock-run) and
  `dsh-bash-sandbox`.
- `@deepseek-ai/dsh-cua-bundle` -> `dsh-experimental-cua-macos` (darwin only).

**Windows branches in DSH's own packages (F).** 44 of the 340 `@deepseek-ai/*` packages in the tree contain
`win32` or `process.platform` in their JavaScript; most: libreoffice-kit 71, dsh-session-persistence-jsonl 43,
dsh-subprocess-local 33, dsh-host-open-in-app 32, dsh-win32-process 30, dsh-native-command 24, dsh-fs-local 23,
dsh-sandbox-windows-acl 21, dsh-plugin-manager 16. Windows-only packages are dependencies of 0.2.2-rc.5:
`dsh-win32-process` ("Shared low-level Win32 process, stdio, and Job Object primitives"),
`dsh-sandbox-windows-acl` ("Windows ACL write-restriction sandbox backend (restricted-token spawn with
capability-SID write allowlist)"), `dsh-pwsh-local` ("Local PowerShell implementation of the ... bash executor
seam"), `dsh-pwsh-sandbox`, `dsh-tool-pwsh`. `dsh-session-persistence-jsonl` takes its session lock on win32
through `CreateSemaphoreW`/`MoveFileExW` instead of flock, with the source comment "native Windows coverage
exercises this platform branch". `lib/bin.js` resolves its own entry with `realpathSync.native` on win32.

**Unix sockets (F, limited search).** A search for `.sock` file names, `listen({path ...})` and `\\.\pipe` in
`@deepseek-ai/*` JavaScript found only `dsh-experimental-cua-macos` (`<runtimeKey>.sock`).

**I (from the above).** DSH 0.2.2-rc.5 is written to run on native Windows: it ships Win32 process/Job Object,
Windows ACL sandbox and PowerShell executor packages, and Windows prebuilds for every native module except the
Linux/POSIX-only `node-addon-system`, whose callers either branch on win32 (session persistence) or belong to
the Linux sandbox. Whether it installs and starts on a Windows runner is what the probe shows.

## 4. Starting it without a credential (macOS, this session)

- **F** `node lib/bin.js --version` printed `0.2.2-rc.5`, exit 0, with `DSH_HOME` an empty scratch directory and
  no provider variable.
- **F** `dsh web --no-open --port 0` in the same environment: every plugin started except the web server, which
  failed `listen EPERM: operation not permitted 127.0.0.1` ("dsh: startup failed: 2 required plugins did not
  activate"). The EPERM comes from this session's sandbox (local port binding is not permitted here), not DSH.
  **I** No login or key is needed to reach the point where `dsh web` listens; whether it then prints its launch
  link on Windows is the probe's `web-raw` and `service`.
- **F** The probe script's macOS smoke run (temp npm prefix, `npm_config_ignore_scripts=true`, a fake
  `GITHUB_TOKEN`): exit 0; 12 of 12 probes recorded; `runner`..`preflight` exit 0 (preflight: graftling's derived
  `package.json` exists on macOS, no refusal, `prepare` accepts, the pi-ai catalog lists 42 providers); `web-raw`,
  `service` and `owner-death` exit 1 on the same sandbox EPERM; `GITHUB_TOKEN` removed by name, its value in no
  output.

## 5. graftling code to watch on Windows (reading of eb5ad8e)

- **F** `settings.prepare` (`settings.py:190-193`), `driver.py:115` and `tests/conftest.py:113-116` find DSH's
  `package.json` as `Path(shutil.which('dsh')).resolve().parent.parent / 'package.json'`. **I** On Windows npm puts
  the `dsh.cmd` shim in the global prefix and the package in `<prefix>\node_modules\@deepseek-ai\dsh`, so this
  path is outside the package and graftling would refuse an installed DSH as "installed unknown"; the probe's
  `preflight` records `derived_package_json`, `derived_exists` and both refusals.
- **F** `service.py` already starts `dsh web` in `OwnedTree(kill_on_close=True)` and starts the watcher only off
  Windows (W3, 635), as decision 3 asks; the probe's `web-raw`, `service` and `owner-death` exercise exactly that.
- **F** 629 advice M10 (`dsh/plugin.mjs` looked for Python only at `<prefix>/bin/python3`) is already handled at
  eb5ad8e by 638: on win32 the plugin tries `<prefix>\Scripts\python.exe` and `<prefix>\python.exe`
  (`plugin.mjs:61-64`). Not run on Windows with a real DSH yet (phase B / 650).
