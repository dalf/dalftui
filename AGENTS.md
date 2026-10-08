# Local Codex guidance

## GitHub access

- Use the authenticated `gh` CLI to inspect GitHub issues and pull requests.
- Read an issue with `gh issue view <number-or-url> --json number,title,body,state,labels,comments,createdAt,updatedAt,closedAt,url`.
- If the sandbox blocks GitHub access, retry the command with scoped network approval.

## Editor bridge compatibility

The bridge contract and versioning rules live in [bridge_protocol.py](bridge_protocol.py).
They cover requests and responses, framing, authentication, endpoint syntax,
environment names, and SSH credential delivery and bootstrap behavior. Networking
and editor launch code live elsewhere, but changes there can still affect the contract.

When changing the contract or SSH bootstrap:

- Assess both old-remote/new-desktop and new-remote/old-desktop compatibility.
  Explain in the change summary whether a protocol bump is required and why.
- Add a compatibility test in [tests/test_bridge_protocol.py](tests/test_bridge_protocol.py)
  that exercises the affected behavior against a supported historical peer.
- If a previously supported pairing can no longer perform a valid operation
  correctly, increment `PROTOCOL_VERSION` and document the break in the module.
  Add the new version to `SUPPORTED_PROTOCOL_VERSIONS` only when the decoder
  implements it; retain older versions only while their behavior is supported.
- Preserve [tests/fixtures/bridge_protocol_v1.py](tests/fixtures/bridge_protocol_v1.py)
  and other historical fixtures. Do not rewrite an old peer to match the current
  implementation or construct both peers from current helpers. Add a new fixture
  for a new protocol version.
- Missing request version metadata is the known authenticated v1 wire format.
  Keep that explicit compatibility rule while v1 is supported. A remote checkout
  without a readable protocol declaration is different: it must not receive bridge
  credentials. Unsupported versions must not launch an editor.
- Pre-declaration peers ignore version metadata. A future breaking client must
  establish peer compatibility before sending an operation; detecting a version
  mismatch after a response cannot undo an editor launch on an old bridge.

Refactoring, logging, and fixes that preserve the existing contract usually do
not require a bump. Optional fields are compatible only when supported old peers
ignore them safely and new peers do not require them. Identical field shapes do
not establish compatibility when their meaning or bootstrap behavior changes.

## Implementation layout

- Shared SSH behavior belongs in [dalftui/ssh.py](dalftui/ssh.py): host/tag/login
  evaluation, picker dispatch, SSH arguments, and connection orchestration. Shared editor
  behavior belongs in [dalftui/vscode.py](dalftui/vscode.py): URIs, launching,
  both bridge transports, authentication, and lifecycle handling.
- Local operating-system integration belongs in `dalftui/linux/` or
  `dalftui/windows/`. Placement describes the target environment, not which
  operating systems may import portable helpers.
- [dalftui/linux/remote_bootstrap.py](dalftui/linux/remote_bootstrap.py) is portable
  Python generating Linux-server shell programs, also used by Windows desktops.
  [dalftui/linux/tmux-start.sh](dalftui/linux/tmux-start.sh) owns the canonical
  startup policy. `bin/tmux-start.sh` forwards local startup; remote execution
  embeds the canonical policy directly.
- The package runs from the checkout without pip installation. Keep `config/`,
  `vendor/`, and the flat `tests/` layout; do not add speculative platform directories.

## Filenames and public paths

- Importable Python modules and package directories use `snake_case`. Shell and
  PowerShell filenames use lowercase words with hyphens when needed.
- Prefer purpose-specific names such as `profile.ps1`, `ssh-tab.ps1`, and
  `terminal_settings.py`. Platform directories normally supply platform context;
  avoid redundant platform prefixes inside them.
- Tests use `test_<feature>.py`; Windows-focused launcher/integration suites may
  use `test_windows_<feature>.py`. Shared bridge tests have feature names without
  a Windows label. Historical fixtures retain versioned names and remain frozen.
- Python command launchers in `bin/` also use `snake_case`. Vendored upstream
  filenames remain unchanged. These conventions concern filenames, directories,
  and placement, not global renaming of functions, classes, variables, or clear files.

Keep installation entrypoints at the root: `install` is the Linux installer;
`install.cmd` invokes the Windows installer `install.ps1` with a process-scoped
execution-policy bypass. Runtime and maintenance launchers belong in `bin/`:
`reload`, `shortcuts.py`, `ssh_picker.py`, `vscode.py`, `terminal_settings.py`,
`profile.ps1`, `ssh-tab.ps1`, and `tmux-start.sh`. They forward to implementations
under `dalftui/` and resolve the checkout independently of the working directory.
Python launchers resolve symlinks before finding the checkout.
The previous root runtime paths were deliberately removed; do not add aliases
for them. Regenerate installed links, profiles, and Terminal actions by rerunning
installation when changing these paths. Remote discovery requires `bin/vscode.py`.
Root `bridge_protocol.py` contains the actual standalone contract and version
declaration; it remains importable without platform integrations.

## Verification

Commands are centralized in [mise.toml](mise.toml). Use `mise tasks` to list them.
Tasks use the existing Python and uv installations and run from the repository
root. `mise run check` runs spelling and Pylint before the current platform's
functionality suites; `mise run` defaults to the same check.

Run the pinned spelling check before the functionality suites:

```sh
mise run spellcheck
```

This invokes `uvx codespell==2.4.3`. Both Linux and Windows CI run this task using
`.codespellrc`. Vendored code, frozen historical fixtures, and local artifacts
are excluded. The same task works on Windows; uv manages the tool's isolated
environment automatically.

Run the pinned Python lint check before the functionality suites:

```sh
mise run pylint
```

This invokes Pylint 4.1.2 through uv, using the existing platform Python and
[.pylintrc](.pylintrc). It checks the package, Python entrypoints (including
`install` and `bin/reload`), standalone bridge contract, and tests; vendored code and
frozen historical fixtures are excluded. Documentation and size/layout rules
are relaxed while correctness checks remain enabled. Both CI workflows use this
task. Fix useful diagnostics; keep any additional suppression narrow and explain
it. `mise run lint` is an alias for the same task.

Full Linux discovery:

```sh
mise run test:linux
```

Native Windows CI's Python coverage is the union of the Windows-compatible
launcher/Terminal selection and shared bridge lifecycle/historical compatibility
selection, preserving platform and dependency skips:

```sh
mise run test:windows
```

This runs `test_windows*.py` and `test_bridge*.py` discovery. Those patterns select
`test_windows_launcher.py`, `test_windows_terminal.py`, `test_windows_ssh_cache.py`,
`test_windows_ssh_title.py`, `test_windows_host_picker.py`, `test_windows_ssh_actions.py`, and
`test_windows_bootstrap.py`,
then `test_bridge_lifecycle.py` and `test_bridge_protocol.py`, respectively.
Linux-targeted bootstrap/startup tests are in `tests/test_remote_bootstrap.py`
and `tests/test_ops_mode.py`.
macOS CI ([.github/workflows/macos.yml](.github/workflows/macos.yml)) runs
full discovery with Homebrew's GNU coreutils first on PATH, then an install,
tmux and zsh smoke test in a temporary home.
Run PowerShell setup/profile verification separately when the shell is available:

```powershell
mise run test:powershell
```

The PowerShell task defaults to Windows PowerShell 5.1; set
`DALFTUI_POWERSHELL=pwsh` to use PowerShell 7. CI sets this variable from its shell
matrix. `mise run test` selects full Linux discovery on Linux, or the Windows
Python and PowerShell suites on Windows. Direct commands remain available when
mise is absent: `python3 -m unittest discover -s tests -v` on Linux,
`python -m unittest discover -s tests -p "test_windows*.py" -v` and
`python -m unittest discover -s tests -p "test_bridge*.py" -v` on Windows, and
`.\tests\test_windows_setup.ps1` in PowerShell.

Check discovered IDs and selected-suite membership when renaming tests; a
successful discovery command can still match zero tests. See [docs/development.md](docs/development.md#verification)
for disposable-resource, mocked GUI/SSH, and historical compatibility coverage.
