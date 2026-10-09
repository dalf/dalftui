# SSH keys: Windows + YubiKey

First read the rules and install the GitHub CLI: see [the setup index](README.md).

**For:** people who carry a YubiKey and use several PCs. If you also use Bitwarden, it only stores your passwords in this setup. **You need:**

- a YubiKey 5 with firmware 5.2.3 or later (older firmware: use `-t ecdsa-sk`);
- a FIDO2 PIN on the YubiKey;
- the SSH that comes with Windows, version 8.9 or later (check with `ssh -V`);
- to sit at the PC itself.

You create two keys on the YubiKey: `id_github` for GitHub and `id_text_analytics_ch` for our LAN servers (`*.lan.text-analytics.ch`, the VMs on Hulk). The private keys stay on the YubiKey. The files with these names in `.ssh` are only handles: they are useless without the YubiKey.

## Day to day: what you are asked

Each use of a key needs a **touch** of the YubiKey. The keys are created without `-O verify-required`, so OpenSSH does not ask for the PIN in daily use; the PIN is needed to create the keys and to download them to another PC. Windows handles the YubiKey through its own security-key windows and may still show a PIN prompt; not tested. Documented by Yubico, not tested.

| Where you are | What you want to do | What happens |
|---|---|---|
| This computer | `ssh monitoring` | The YubiKey blinks: touch it. |
| This computer | `git pull` / `git push` / `git clone` with GitHub | A touch, once per command. |
| This computer | `scp` to a VM | A touch. |
| This computer | Open a VS Code Remote-SSH window, or reconnect after sleep | A touch, each time VS Code connects. |
| This computer | Commit with SSH signing (if you set it up) | A touch, once per commit. |
| This computer | First use after logging in or a reboot | Same as any other time: a touch. |
| On a LAN VM (through ssh) | `git pull` / `git push` | Your YubiKey on this PC blinks: touch it here. |
| On a LAN VM (through ssh) | Commit with SSH signing (if you set it up there) | The same, once per commit. |

Good to know:

- The touch proves that someone is at the YubiKey. Malware on this PC cannot use the keys without it.
- One SSH connection is one touch. A `git pull` is one connection; a `git rebase` with signing asks once per commit.
- The Windows SSH cannot share one connection between commands: Win32-OpenSSH lists the client `ControlMaster` among the features that "will not work on Windows yet". So each command needs its own touch, unlike on Linux and macOS.
- Requests forwarded from a VM are answered on this PC, so you must be at it with the YubiKey plugged in.
- Long-running AI agents or scripts should not use these keys at all: see [Automation and agents](README.md#automation-and-agents).

When it doesn't work:

- The YubiKey is unplugged: the key cannot sign. Plug it in and run the command again.
- You do not touch it, or you are away when a VM asks: the command waits. Not tested: how long it waits before it fails.
- Wrong PIN (when creating or downloading keys): after 3 in a row, unplug and replug the YubiKey. After 8, its FIDO2 function is blocked until a reset, which deletes these keys. Do not guess.
- Keys created with an earlier version of this page (`-O verify-required`) keep asking the PIN at each use. To stop that, create new keys with the commands below and publish them again.

## Create the keys (once, on the first PC)

YubiKeys work with the SSH that comes with Windows. No download is needed. Replace `john.doe@hesge.ch` with your email address.

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.ssh" | Out-Null
ssh-keygen -t ed25519-sk -O resident -O application=ssh:github -C "john.doe@hesge.ch" -f "$env:USERPROFILE\.ssh\id_github"
ssh-keygen -t ed25519-sk -O resident -O application=ssh:text_analytics_ch -C "john.doe@hesge.ch" -f "$env:USERPROFILE\.ssh\id_text_analytics_ch"
```

For **each** of the two keys:

- If a **"Save your passkey"** window says `This will be saved to your Windows device`, click **Change**, choose **Security key**, then **Next**.
- Insert the YubiKey, enter its **PIN**, and **touch** it when it blinks.
- `Enter passphrase` (asked twice): press **Enter** both times. The secret stays on the YubiKey.

There is no `-O verify-required`: in daily use a touch is enough. `-O application=...` gives each key its own name on the YubiKey, so the second key cannot replace the first, and another PC can tell them apart.

**On another PC**, you need the four handle files again: `id_github`, `id_github.pub`, `id_text_analytics_ch` and `id_text_analytics_ch.pub`. Never overwrite files that already exist in `.ssh`: they may point to another key.

- **Simplest:** copy the four files from your first PC into `$env:USERPROFILE\.ssh` (for example with a USB stick). They are handles, not private keys.
- **Or** download them from the YubiKey. The SSH that comes with Windows can do this only in an **administrator** PowerShell; in a normal one it fails with `Unable to load resident keys: invalid format` (https://github.com/PowerShell/Win32-OpenSSH/issues/2427). If the administrator account is not your own account, use the copy instead. In the administrator PowerShell:

  ```powershell
  $t = "$env:USERPROFILE\.ssh\yubikey-download"
  New-Item -ItemType Directory $t | Out-Null
  cd $t; ssh-keygen -K
  ```

  - `Enter PIN for authenticator:` type the YubiKey PIN, then **touch** it.
  - `Enter passphrase` (asked twice): press **Enter** both times.
  - Done when you see `Saved ED25519-SK key ssh:github to id_ed25519_sk_rk_github` and the same for `text_analytics_ch`.

  Then move the files into place. `Move-Item` without `-Force` stops with an error if a file already exists; then keep the old file and ask for help.

  ```powershell
  Move-Item id_ed25519_sk_rk_github ..\id_github
  Move-Item id_ed25519_sk_rk_github.pub ..\id_github.pub
  Move-Item id_ed25519_sk_rk_text_analytics_ch ..\id_text_analytics_ch
  Move-Item id_ed25519_sk_rk_text_analytics_ch.pub ..\id_text_analytics_ch.pub
  cd ..; Remove-Item $t
  ```

  With `-t ecdsa-sk`, the downloaded names start with `id_ecdsa_sk_rk_` instead.

## SSH agent

The agent lets the LAN servers use your keys: from a VM, `git` reaches GitHub through your PC. A touch is still needed every time a key is used.

1. In an **administrator** PowerShell (as shipped, the service is Stopped and Disabled):

   ```powershell
   Get-Service ssh-agent | Set-Service -StartupType Automatic
   Start-Service ssh-agent
   ```

2. In a normal PowerShell:

   ```powershell
   ssh-add "$env:USERPROFILE\.ssh\id_github" "$env:USERPROFILE\.ssh\id_text_analytics_ch"
   git config --global core.sshCommand C:/Windows/System32/OpenSSH/ssh.exe
   ```

- `ssh-add` replies `Identity added: ...` for each key.
- The `git config` line makes Git use the SSH that comes with Windows instead of the one bundled with Git. Skip it if Git is not installed.

## ~/.ssh/config

This is the block from the team's [SSH page](https://infra.text-analytics.ch/devdoc/tools/ssh/), without the switch.ch part. Windows' SSH accepts the `~/` paths.

```
CanonicalizeHostname yes
CanonicalDomains lan.text-analytics.ch
CanonicalizeMaxDots 1

Host *.lan.text-analytics.ch
    AddKeysToAgent yes
    ForwardAgent yes
    IdentityFile "~/.ssh/id_text_analytics_ch"

Host github.com
    AddKeysToAgent yes
    IdentityFile "~/.ssh/id_github"
```

Open the file in Notepad. The first line creates an empty file if you have none; it never changes an existing one.

```powershell
if (-not (Test-Path "$env:USERPROFILE\.ssh\config")) { New-Item -ItemType File "$env:USERPROFILE\.ssh\config" | Out-Null }
notepad "$env:USERPROFILE\.ssh\config"
```

Paste the block at the **top** of the file, followed by an empty line, then save. If the file already had content:

- SSH uses the first value it finds for most settings. Keep any `Host *` block **below** the new blocks.
- Remove older `IdentityFile` lines for `github.com`, the LAN servers or `Host *` (for example `IdentityFile ~/.ssh/id_ed25519_sk` from an earlier version of this page). `IdentityFile` lines add up, so old ones stay active.
- Do not paste the block twice.

`ForwardAgent yes` lets the LAN servers ask your agent to sign; it applies only to `*.lan.text-analytics.ch`.

Check the result. Replace `monitoring` with one of your VMs, here and below:

```powershell
ssh -G github.com | Select-String '^identityfile '
ssh -G monitoring | Select-String '^(hostname|identityfile|forwardagent) '
```

Expected: `identityfile ~/.ssh/id_github` first, then `hostname monitoring.lan.text-analytics.ch`, `forwardagent yes` and `identityfile ~/.ssh/id_text_analytics_ch` first. The second command works only on the LAN or VPN.

## Check

```powershell
ssh-add -l
```

Expected: two lines, `256 SHA256:... (ED25519-SK)`.

```powershell
ssh-keygen -Y sign -f "$env:USERPROFILE\.ssh\id_github" -n file "$env:USERPROFILE\.ssh\id_github.pub"
```

It asks for a touch. Expected: `Write signature to ...id_github.pub.sig`. Repeat with `id_text_analytics_ch` to check the second key.

## Publish the public keys (once, from any PC)

**GitHub:** `id_github` only, for login and for commit signing:

```powershell
gh ssh-key add "$env:USERPROFILE\.ssh\id_github.pub" --type authentication --title "yubikey"
gh ssh-key add "$env:USERPROFILE\.ssh\id_github.pub" --type signing --title "yubikey"
```

**LAN servers:** `id_text_analytics_ch` only. Run this once for each VM you use:

```powershell
Get-Content "$env:USERPROFILE\.ssh\id_text_analytics_ch.pub" | ssh monitoring "umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys; chmod go-w ~ ~/.ssh ~/.ssh/authorized_keys; (echo; cat) >> ~/.ssh/authorized_keys"
```

- It asks for your VM password once. You need a working password login on the VM; the VM must run Linux with OpenSSH 8.2 or later.
- The command removes write access for others from `~/.ssh` (SSH ignores the key otherwise) and starts the key on a new line. Empty lines in `authorized_keys` are harmless.
- The first connection to a server asks `Are you sure you want to continue connecting (yes/no/[fingerprint])?`. Type **yes** only if the fingerprint shown matches the real one. For GitHub, compare with https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints. For a LAN VM, compare with the fingerprint the admin publishes, or ask the admin. If SSH later prints `REMOTE HOST IDENTIFICATION HAS CHANGED`, stop and tell the admin.

Then test each key. Each command asks for a touch.

```powershell
ssh -T git@github.com
```

Expected: `Hi <you>! You've successfully authenticated, but GitHub does not provide shell access.` The command exits with code 1; that is normal.

```powershell
ssh -o PreferredAuthentications=publickey monitoring hostname
```

Expected: the VM's name. `PreferredAuthentications=publickey` makes sure the key, not a password, logged you in.

Test the forwarding, from the VM to GitHub:

```powershell
ssh -t monitoring ssh -T git@github.com
```

It asks for a touch twice: once for the VM, once for GitHub. Expected: `Hi <you>! ...`. VS Code Remote-SSH reads the same config. If the agent is missing in a VS Code terminal, or if you see `chan_shutdown_read: shutdown() failed ... Not a socket`, see the troubleshooting sections at the end of the [SSH page](https://infra.text-analytics.ch/devdoc/tools/ssh/).

**Git:** repositories cloned with an `https://` URL keep using HTTPS; `git remote -v` shows it. If a GitHub organization uses single sign-on, authorize `id_github` for it at https://github.com/settings/keys (**Configure SSO**). To sign commits with `id_github`, follow [GitHub and commit signing](../secrets-and-keys.md#ssh-keys) and also run `git config --global gpg.ssh.program C:/Windows/System32/OpenSSH/ssh-keygen.exe`.

**Status:** Not tested: no YubiKey was available. Based on https://developers.yubico.com/SSH/Securing_SSH_with_FIDO2.html. https://github.com/PowerShell/Win32-OpenSSH/issues/2040 reports that the built-in SSH creates YubiKey keys correctly. Win32-OpenSSH issue #2427 reports that keys created with `-O application=...` work on Windows, and that `ssh-keygen -K` works only as administrator. Not tested either: holding YubiKey keys in the Windows agent and forwarding them. The same agent and forwarding were tested with Windows Hello keys on 2026-10-09 (see [Windows](windows.md)): the PIN window opened on the Windows desktop for a forwarded request.
