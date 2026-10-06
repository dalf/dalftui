# Manual configuration

dalftui's installers and reload commands set up Alacritty, tmux, PowerShell, and
Windows Terminal. This file records related machine settings that dalftui does
not apply, why they matter, and how to apply them by hand. Each entry says where
it applies, so it can be checked again when setting up a new machine.

## Windows: Git over SSH from Git Bash

**Applies to:** Windows desktops with Git for Windows and Windows OpenSSH, where
GitHub keys are loaded in the Windows `ssh-agent` service.

**Symptom:** `git push` works from PowerShell but fails from Git Bash, including
Claude Code's `!` commands and Bash tool:

```text
git@github.com: Permission denied (publickey).
```

**Cause:** Git runs the first `ssh` found on `PATH` unless `GIT_SSH`,
`GIT_SSH_COMMAND`, or `core.sshCommand` is set. In PowerShell this is
`C:\Program Files\OpenSSH\ssh.exe`, which uses the Windows agent. Git Bash puts
its bundled `/usr/bin/ssh` first; that client cannot reach the Windows agent
(`SSH_AUTH_SOCK` is empty) and may not read the Windows-style `IdentityFile`
paths in `~/.ssh/config`.

**Setting:** make Git use Windows OpenSSH in every shell:

```powershell
git config --global core.sshCommand "'C:/Program Files/OpenSSH/ssh.exe'"
```

For a single command without changing the configuration:

```sh
git -c core.sshCommand="'C:/Program Files/OpenSSH/ssh.exe'" push
```

**Check:** from Git Bash, `git ls-remote origin` succeeds. Plain
`ssh -T git@github.com` there still uses the bundled client, so it may keep failing.
