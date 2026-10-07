# Development reference

## Repository

On a new machine, clone your repository to a stable path and run `./install`
and `./bin/reload`, adding `--tmux-only` when installing on a server. For a local checkout without a remote, create an empty remote
repository and connect it once:

```sh
git remote add origin YOUR_REPOSITORY_URL
git push -u origin main
```

Once the remote exists, the [update commands](install.md#update-without-reinstalling) work on other installations.

## Layout and entrypoints

The Python package runs directly from the checkout; no pip installation is
needed. Representative layout:

```text
.
├── dalftui/
│   ├── ssh.py
│   ├── host_picker.py
│   ├── vscode.py
│   ├── linux/
│   │   ├── alacritty_config.py
│   │   ├── setup.py
│   │   ├── shortcuts.py
│   │   ├── ssh_picker.py
│   │   ├── tmux_editor.py
│   │   ├── remote_bootstrap.py
│   │   ├── ops.py
│   │   ├── package-status.sh
│   │   ├── system-status.sh
│   │   └── tmux-start.sh
│   └── windows/
│       ├── ssh.py
│       ├── host_picker.py
│       ├── vscode.py
│       ├── terminal_settings.py
│       ├── setup.ps1
│       ├── profile.ps1
│       └── ssh-tab.ps1
├── bridge_protocol.py
├── mise.toml
├── install
├── install.cmd
├── install.ps1
├── bin/
│   ├── reload
│   ├── shortcuts.py
│   ├── ssh_picker.py
│   ├── vscode.py
│   ├── terminal_settings.py
│   ├── profile.ps1
│   ├── ssh-tab.ps1
│   └── tmux-start.sh
├── config/
├── tests/
│   ├── test_windows_launcher.py
│   ├── test_windows_terminal.py
│   ├── test_bridge_protocol.py
│   ├── test_bridge_lifecycle.py
│   ├── test_remote_bootstrap.py
│   └── fixtures/
│       ├── bridge_protocol_v1.py
│       ├── bridge_protocol_v2.py
│       ├── ssh_bootstrap_v1.py
│       └── ssh_bootstrap_v2.py
└── vendor/
    └── catppuccin/
```

[dalftui/ssh.py](../dalftui/ssh.py) owns shared host/tag/login evaluation, picker dispatch,
SSH arguments, and connection orchestration. [dalftui/host_picker.py](../dalftui/host_picker.py)
owns the responsive grid, filtering, and navigation; platform adapters handle console I/O.
[dalftui/vscode.py](../dalftui/vscode.py)
owns URI construction, editor launching, both Unix and TCP bridge transports,
authentication, and lifecycle handling. Platform modules own local operating-system
integration. Directory placement describes the environment targeted by code;
portable helpers can be imported on other operating systems.
In particular, [dalftui/linux/remote_bootstrap.py](../dalftui/linux/remote_bootstrap.py)
generates Linux-server shell programs from portable Python and is also used by
Windows desktops. [dalftui/linux/ops.py](../dalftui/linux/ops.py) generates the
optional ops layout and bounded saved-check runner, embedding the read-only
checks from `dalftui/linux/package-status.sh` and `dalftui/linux/system-status.sh`.
[dalftui/linux/tmux-start.sh](../dalftui/linux/tmux-start.sh) is
the canonical startup policy: `bin/tmux-start.sh` forwards local startup, while
remote execution embeds the canonical policy directly.

Installation entrypoints stay at the root; runtime and maintenance commands
live in `bin/`:

| Path | Role |
| --- | --- |
| [install](../install) | Linux installation CLI |
| [install.cmd](../install.cmd) | Windows installation launcher with a process-scoped execution-policy bypass |
| [install.ps1](../install.ps1) | Windows PowerShell installation CLI |
| [bin/reload](../bin/reload) | Linux configuration reload CLI |
| [bin/shortcuts.py](../bin/shortcuts.py) | Shortcut-guide launcher |
| [bin/ssh_picker.py](../bin/ssh_picker.py) | Shared SSH launcher |
| [bin/vscode.py](../bin/vscode.py) | Shared editor launcher and remote discovery target |
| [bin/profile.ps1](../bin/profile.ps1) | PowerShell profile loader |
| [bin/ssh-tab.ps1](../bin/ssh-tab.ps1) | Terminal SSH-tab launcher |
| [bin/terminal_settings.py](../bin/terminal_settings.py) | Terminal settings CLI |
| [bin/tmux-start.sh](../bin/tmux-start.sh) | Local terminal startup target |
| [bridge_protocol.py](../bridge_protocol.py) | Canonical standalone contract and version declaration |

Each launcher resolves the checkout and forwards to the package implementation.
No pip installation or particular working directory is required. The previous
root runtime paths have been removed. After updating from that layout, rerun
`./install` and `./bin/reload` on Linux, or `.\install.cmd` on Windows, to
regenerate links, profile entries, and Terminal actions. `bridge_protocol.py`
contains the actual contract and version declaration; it is not a forwarding
wrapper.

## Filename conventions

These conventions apply to filenames, directories, and placement:

- Importable Python modules and package directories use `snake_case`.
- Python command launchers in `bin/` also use `snake_case`.
- Shell and PowerShell script filenames use lowercase words, with hyphens when
  needed. Prefer purpose-specific names such as `profile.ps1`, `ssh-tab.ps1`,
  and `terminal_settings.py`.
- Platform directories normally supply the platform context; avoid redundant
  platform prefixes within them.
- Tests stay flat and use `test_<feature>.py`. Windows-focused launcher and
  integration suites may use `test_windows_<feature>.py`; shared bridge tests
  use feature names without a Windows label.
- Historical fixtures keep their versioned names and remain frozen. Vendored
  upstream filenames remain unchanged.

Keep `config/`, `vendor/`, and the flat test layout. Apply these rules when adding
or moving files; they do not call for renaming functions, classes, variables,
already-clear files, or adding speculative platform directories.

## Repository tasks

[mise](https://mise.jdx.dev/getting-started.html) 2026.7.5+ runs the commands
defined in [mise.toml](../mise.toml). It uses your existing Python and uv installations;
tasks run from the repository root even when invoked from a subdirectory.
After installing mise, trust the checkout and list its tasks:

```sh
mise trust
mise tasks
```

| Task | Purpose |
| --- | --- |
| `mise run check` | Spelling, Pylint, then all tests for the current platform |
| `mise run spellcheck` | Pinned codespell check through uv |
| `mise run pylint` | Pinned Pylint check of Python source, entrypoints, and tests (alias: `lint`) |
| `mise run test` | Full Linux discovery, or Windows Python and PowerShell suites |
| `mise run test:linux` | Full Python discovery, including Linux integration tests |
| `mise run test:windows` | Windows launcher/Terminal and shared bridge Python suites |
| `mise run test:bridge` | Shared bridge lifecycle and historical compatibility tests |
| `mise run test:powershell` | Windows setup and profile integration |
| `mise run install:linux` | Linux installation through `./install` |
| `mise run install:windows` | Windows installation through `install.ps1` |
| `mise run uninstall:linux` | Linux uninstall through `./install --uninstall` |
| `mise run uninstall:windows` | Windows uninstall through `install.ps1 -Uninstall` |
| `mise run reload:linux` | Reload Linux settings through `./bin/reload` |
| `mise run ssh:list` | List SSH picker hosts without opening a connection |

`mise run` defaults to `check`. Use installation and reload tasks on their target
platform. They accept the existing scripts' options after `--`:

```sh
mise run install:linux -- --dry-run
mise run install:linux -- --tmux-only --dry-run
mise run reload:linux -- --socket /path/to/socket
```

Windows tasks use Windows PowerShell 5.1 by default. To install or test using
PowerShell 7 instead, set `DALFTUI_POWERSHELL` to `pwsh`:

```powershell
$env:DALFTUI_POWERSHELL = 'pwsh'
mise run test:powershell
mise run install:windows -- -VSCodePath 'C:\Tools\VS Code Portable'
```

The selected shell runs the installer; setup configures both installed PowerShell
versions unless `-ProfilePath` selects a single profile. The installers and
`bin/` launchers remain available for direct use. GitHub Actions uses these same tasks while
selecting Python and PowerShell versions through its existing matrix.

## Verification

Run spelling, Python lint, and functionality checks from the repository root with
[uv](https://docs.astral.sh/uv/getting-started/installation/) installed:

```sh
mise run check
mise run ssh:list
```

Codespell checks documentation, source, tests, configuration, and hidden files
such as CI workflows using [.codespellrc](../.codespellrc). Vendored code, frozen
historical fixtures, and local artifacts are excluded. The pinned version in the
`spellcheck` task keeps local and CI checks consistent. uv manages the tool's isolated
environment automatically.

`mise run pylint` runs Pylint 4.1.2 through uv using the current platform's
`python3` or `python` interpreter and [.pylintrc](../.pylintrc). It checks `dalftui/`,
the Python command entrypoints (including `install` and `bin/reload`), the standalone
bridge contract, and `tests/`. Vendored code and frozen historical fixtures are
excluded. The configuration targets Python 3.11, disables docstring requirements,
line-length and size heuristics, and recognizes the checkout's import/bootstrap
and resource-lifecycle patterns. Error and warning checks such as undefined names,
bad calls, unused imports, and unsafe defaults remain enabled. Output contains
diagnostics without reports or scores; any enabled diagnostic fails the task.
Both CI workflows run this same check before functionality tests. Use
`mise run pylint` or `mise run lint` to run it separately.

On Windows, the task exempts only the exact Unix API names listed in
`windows_lint_members` in [mise.toml](../mise.toml) from member inference. Those APIs
are used by Linux code or guarded tests and are unavailable to Windows Python.
Linux lint checks them normally; other missing-member checks remain enabled on
both platforms.

Tests use disposable directories, OpenSSH's configuration evaluator, and private
tmux sockets. They do not open SSH connections or touch your live tmux sessions.
They cover backups, rollback, repeated installation, updates through the link,
personal overrides, both shortcut guides, tag filtering, mode switching,
reloads that preserve pane processes and Claude status, and the clipboard and
mouse-selection bindings loaded into a real tmux server. The CLI is also tested
with Alacritty and SSH absent from PATH. Desktop picker tests are skipped when
OpenSSH's Tag directive is unavailable; it is not required by server mode.
Unix authentication tests include a deliberately mode-0666 socket in a
mode-0755 directory: they prove that reaching the endpoint does not authorize
editor launches. This is a same-account local test, not a cross-user or remote
sshd test. Remote credential scripts run locally with fake tmux clients to
check private/exclusive creation, consumption, failed setup, signal cleanup,
and resource isolation. SSH startup tests cover silent shell fallback, native
tmux without dalftui, installation detection with custom configuration paths,
and connections that never start or forward a bridge. Real tmux tests route
separate clients' endpoints and tokens even with deliberately stale server
environment values.
System overview tests use fake tools and local files to cover unavailable tools,
permission failures, timeouts, empty journal matches, overlay roots, disk/inode
warnings, and degraded software RAID without contacting an SSH server.
Bridge protocol tests exercise frozen v1 messages and historical peers in both
directions, reject unsupported versions without editor launches, and check the
remote declaration before credential setup.

The Windows-compatible launcher and Terminal suites run separately without tmux
or curses. In PowerShell, run spelling and Pylint before the Python suites:

```powershell
mise run spellcheck
mise run pylint
```

Run the launcher, Terminal, and shared bridge suites:

```sh
mise run test:windows
```

This runs `test_windows*.py` discovery, selecting
[tests/test_windows_launcher.py](../tests/test_windows_launcher.py)
and [tests/test_windows_terminal.py](../tests/test_windows_terminal.py), followed by
`test_bridge*.py` discovery.
Run the shared bridge lifecycle and historical compatibility suites separately:

```sh
mise run test:bridge
```

This selects [tests/test_bridge_lifecycle.py](../tests/test_bridge_lifecycle.py)
and [tests/test_bridge_protocol.py](../tests/test_bridge_protocol.py). Together,
the Windows and bridge selections cover native Windows CI's Python tests;
platform and dependency skips still apply. Linux-targeted startup and remote
bootstrap coverage lives in
[tests/test_remote_bootstrap.py](../tests/test_remote_bootstrap.py) and runs with
full Linux discovery.

Check the PowerShell setup and profile integration separately:

```powershell
mise run test:powershell
```

GitHub Actions runs the full Linux suite on Ubuntu with Python 3.11 and 3.14,
installing tmux, OpenSSH, Git, and less for the integration tests.
Both Linux and Windows CI run the same pinned spelling and Pylint checks before
the Python test suites. CI also runs native Windows tests with Python 3.11 and 3.14, in
PowerShell 5.1 and 7. They cover installation without package managers,
profile backups and repeated setup, safe VS Code discovery and portable-path
configuration, the `dssh` command, native picker rendering and navigation, SSH tag and login
resolution, TCP authentication, and connection token handling. Isolated bridge
tests also cover slow input deadlines, concurrent requests, capacity rejection
and recovery, shutdown races, and interruption of readers and editor CLI waits.
A harmless native executable probe verifies that a project-local `Code.exe` is not run;
another verifies the configured `Code.exe` + `cli.js` argument list and encoded
local and remote folder URIs. Linux runs the cross-platform suite and simulated
Windows launch tests. GUI launches and interactive SSH connections remain
mocked; no automated test opens the VS Code GUI or an SSH connection.
