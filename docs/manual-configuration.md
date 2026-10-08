# Manual configuration

dalftui's installers and reload commands set up Alacritty, tmux, PowerShell, and
Windows Terminal. This file records related machine settings, mostly ones
dalftui does not apply, why they matter, and how to apply them by hand. Each entry says where
it applies, so it can be checked again when setting up a new machine.

## Windows: SSH agent and forwarding

**Applies to:** Windows desktops using Windows OpenSSH with keys that have a
passphrase, and `ForwardAgent` to reach GitHub from remote servers.

**Applied by bootstrap:** the `ssh-agent` service set to start automatically,
and Git's `core.sshCommand` (see [install](install.md#new-machine-windows)).
Without bootstrap, in an administrator PowerShell:

```powershell
Set-Service ssh-agent -StartupType Automatic; Start-Service ssh-agent
```

**Setting:** load each key once, from your normal session (not an SSH login
into Windows, where the agent refuses new keys):

```powershell
ssh-add "$env:USERPROFILE\.ssh\id_github"
```

The Windows agent keeps keys across reboots (encrypted in your registry), so
this is not repeated after a restart; the passphrase is not asked again either.
`ssh-add -c` and `-t` are not supported. In `~/.ssh/config`, add
`ForwardAgent yes` to the hosts that should see your keys.

**Old Windows:** Windows 10 (OpenSSH 8.1) and Windows 11 up to 23H2 (8.6) ship
an agent older than OpenSSH 8.9. With servers running 8.9 or later (Ubuntu
22.04, Debian 12), forwarded keys are listed by `ssh-add -L` but `git` fails.
Windows 11 24H2 ships 9.5 and is not affected. The fix is the newer client,
replacing the built-in one so the agent service changes too. In an
administrator PowerShell, then reboot:

```powershell
Remove-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0
```

After the reboot, still as administrator:

```powershell
winget install --exact --id Microsoft.OpenSSH.Preview --source winget --override "ADDLOCAL=Client"
```

`ADDLOCAL=Client` installs no SSH server. The installer adds
`C:\Program Files\OpenSSH` first on `PATH`, takes over the `ssh-agent` service
and keeps the keys already added. Its releases are labeled previews.

**Check:** on a remote host, `ssh-add -l` lists your keys and
`ssh -T git@github.com` authenticates.

## Windows: Git over SSH

**Applies to:** Windows desktops with Git for Windows or Scoop's git and keys in
the Windows `ssh-agent` service. Bootstrap applies this setting when it is unset.

**Symptom:** `git push` fails with:

```text
git@github.com: Permission denied (publickey).
```

**Cause:** Scoop's git, and Git for Windows installed with its default bundled
OpenSSH, run their own `ssh` unless `GIT_SSH`, `GIT_SSH_COMMAND`, or
`core.sshCommand` is set, from PowerShell as from Git Bash. That client cannot
reach the Windows agent (`SSH_AUTH_SOCK` is empty) and may not read the
Windows-style `IdentityFile` paths in `~/.ssh/config`.

**Setting:** make Git use Windows OpenSSH, the built-in client or the one in
`C:\Program Files\OpenSSH` when it replaced it:

```powershell
# Built-in client:
git config --global core.sshCommand C:/Windows/System32/OpenSSH/ssh.exe
# Or the replacement in Program Files:
git config --global core.sshCommand "'C:/Program Files/OpenSSH/ssh.exe'"
```

**Check:** `git ls-remote origin` succeeds, from Git Bash too. Plain
`ssh -T git@github.com` in Git Bash still uses the bundled client, so it may keep failing.
