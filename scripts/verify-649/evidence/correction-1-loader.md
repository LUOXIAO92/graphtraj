# 649 correction 1: why graftling-dsh was missing from dsh_plugin_packages on Windows (run 45996884900)

Read on macOS arm64 with Node v26.5.0, from the phase A read-only install of DSH 0.2.2-rc.5 and from the installed
DSH 0.2.2-rc.5. Facts are marked **F**, inferences **I**.

## Source (DSH 0.2.2-rc.5's dependencies)

- **F** `@deepseek-ai/cordis-plugin-loader` 1.1.0, `lib/index.js`:
  - **338-352**: `EntryTree.import(name)` imports a name that does not start with `cordis:` or `.` with
    `import(resolve ? resolve(name) : name)`. That is, the name is an ES module specifier.
  - **581-586**: `Entry._init` catches an import error, only logs it (`this.ctx.logger.error(error)`) and returns,
    so the entry gets no fiber.
- **F** `@deepseek-ai/dsh-plugin-package-inventory-deepseek`, `lib/index.js`:
  - **98-103**: `activeEntries` keeps only entries with `entry.fiber?.state === 2`.
  - **88-90**: for an absolute path or a URL it finds the nearest `package.json` (`graftling-dsh` here).
  - So an entry that never loaded is simply absent from `dsh_plugin_packages`.
- **F** `tests/fixtures/dsh_mcp_plugin.mjs` gave the Loader `name: pluginPath`, a filesystem path. On the runner that
  was `D:\a\graftling\graftling\src\graftling\dsh\plugin.mjs`.
- **F** graftling's own child rows did the same (`dsh/execution.py`: `agents-mcp`, `agents-review`:
  `str(Path(__file__).with_name(...))`).

## Checks on this machine

- **F** `node -e "await import('D:\\a\\x\\plugin.mjs')"` gives `ERR_UNSUPPORTED_ESM_URL_SCHEME - Only URLs with a
  scheme in: file, data, and node are supported by the default ESM loader. Received protocol 'd:'`. A `file:` URL of
  an existing module imports.
- **F** `tests/fixtures/dsh_mcp_plugin.mjs`, changed only to `name: pathToFileURL(pluginPath).href`, was run against
  the installed DSH 0.2.2-rc.5 (`/opt/homebrew/lib/node_modules/@deepseek-ai/dsh/lib/bin.js`) with graftling
  `5b7bd91d`'s `plugin.mjs`. It printed
  `{"tools":["mcp__graftling__subagents"],"nativeSession":"native-parent","childSourcePreserved":true,"browserEntry":"graftling-dsh"}`:
  the Loader, the inventory assertion, the client module and both MCP calls pass with a `file:` URL name.
- **I** On the runner the Loader logged the same import error, which the fixture does not print. The cause is
  graftling's (and the fixture's) name, not DSH: DSH documents and implements the name as a module specifier.

## Fix (graftling `0e5c92a6`)

- `dsh/execution.py _module_name`: graftling's rows name their module as a file URL on Windows and as the path
  elsewhere (POSIX unchanged).
- The fixture names the plugin the same way.
- `test_dsh_standalone_child` expects that form.
- `tests/test_dsh_windows_649.py::test_profile_patch_rows_name_graftling_modules_as_file_urls_on_windows` checks the
  form on every platform, with the Windows branch patched in.
- The Windows proof is the two delivered-plugin tests in the must-pass list, which load the plugin into the real
  DSH's Loader on the runner.
