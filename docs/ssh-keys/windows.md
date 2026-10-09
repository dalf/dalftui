# SSH keys: Windows, nothing extra

First read the rules and install the GitHub CLI: see [the setup index](README.md).

**For:** Windows 11 users with a Windows Hello PIN or fingerprint. **You need:**

- Windows Hello turned on (Settings > Accounts > Sign-in options);
- Windows PowerShell;
- to sit at the PC itself. These steps do not work over SSH.

You create two keys on this PC: `id_github` for GitHub and `id_text_analytics_ch` for our LAN servers (`*.lan.text-analytics.ch`, the VMs on Hulk). Windows Hello keeps the private keys. The files in `.ssh` only point to them, so a copy of those files is useless on another PC. On a PC with a TPM chip, Windows Hello normally keeps keys in the TPM, but Windows can also keep them in software. We tested that the keys work; we did not check where Windows stored them.

## Day to day: what you are asked

| Where you are | What you want to do | What happens |
|---|---|---|
| This computer | `ssh monitoring` | A **"Sign in with a passkey"** window asks your Windows PIN. |
| This computer | `git pull` / `git push` / `git clone` with GitHub | The same PIN window, once per command. |
| This computer | `scp` to a VM | The same PIN window. |
| This computer | Open a VS Code Remote-SSH window, or reconnect after sleep | The same PIN window, each time it connects (not tested). |
| This computer | Commit with SSH signing (if you set it up) | The same PIN window, once per commit. |
| This computer | First use after logging in or a reboot | Same as any other time: the PIN window. |
| On a LAN VM (through ssh) | `git pull` / `git push` | The PIN window opens on this computer: type the PIN there. |
| On a LAN VM (through ssh) | Commit with SSH signing (if you set it up there) | The same, once per commit (not tested). |

**Fallback (ed25519 with a passphrase):** nothing is asked once `ssh-add` has loaded the keys. Not tested: whether they are still loaded after a reboot. If `ssh` asks `Enter passphrase for key ...`, type the passphrase; `AddKeysToAgent` loads the key again.

Good to know:

- The PIN proves that you are at this PC, now. Windows asks it for every signature, also through the agent: it never remembers it.
- One SSH connection is one PIN. A `git pull` is one connection; a `git rebase` with signing asks once per commit.
- Requests forwarded from a VM are answered on this PC, so you must be at it.

When it doesn't work:

- A VM gets `Permission denied (publickey)`: the key is not in the agent yet. Use it once on this PC (for example `ssh -T git@github.com`), then try again.
- The PC is locked or you are away: nobody can type the PIN, so the command on the VM waits. Not tested: how long it waits before it fails.

The Windows SSH cannot share one connection between commands to cut prompts: Win32-OpenSSH lists the client `ControlMaster` among the features that "will not work on Windows yet".

## Create the keys

The SSH that comes with Windows (9.5p2) **cannot create** these keys. It fails with `Key enrollment failed: invalid format`. The block below downloads OpenSSH 10.0 Preview to a temporary folder, uses it to create both keys, then deletes it. Replace `john.doe@hesge.ch` with your email address.

```powershell
$d = "$env:TEMP\openssh10"
New-Item -ItemType Directory -Force $d, "$env:USERPROFILE\.ssh" | Out-Null
curl.exe -L -o "$d\o.zip" https://github.com/PowerShell/Win32-OpenSSH/releases/download/10.0.0.0p2-Preview/OpenSSH-Win64.zip
Expand-Archive "$d\o.zip" $d -Force
$env:SSH_SK_HELPER = "$d\OpenSSH-Win64\ssh-sk-helper.exe"
& "$d\OpenSSH-Win64\ssh-keygen.exe" -t ecdsa-sk -C "john.doe@hesge.ch" -f "$env:USERPROFILE\.ssh\id_github"
& "$d\OpenSSH-Win64\ssh-keygen.exe" -t ecdsa-sk -C "john.doe@hesge.ch" -f "$env:USERPROFILE\.ssh\id_text_analytics_ch"
Remove-Item Env:SSH_SK_HELPER; Remove-Item -Recurse -Force $d
```

The download takes about 20 seconds. Then, for **each** of the two keys:

- The window shows `You may need to touch your authenticator to authorize key generation.`
- A **"Windows Security – Save your passkey"** window opens. Click **Continue**. When it asks **Enter your PIN**, type your Windows PIN.
- `Enter passphrase for "C:\Users\...\id_github" (empty for no passphrase):` press **Enter**.
- `Enter same passphrase again:` press **Enter**.
- Done when you see `Your identification has been saved in ...id_github` (then `...id_text_analytics_ch`).

Do not add `-N ""`, because Windows PowerShell 5.1 drops empty arguments.

## SSH agent

The agent lets the LAN servers use your keys: from a VM, `git` reaches GitHub through your PC. Windows still asks for your PIN every time a key is used, also when the request comes from a VM: the PIN window opens on your PC. A key that is not in the agent yet cannot be used from a VM, so load both keys now.

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

- `ssh-add` replies `Identity added: ...` for each key without asking anything.
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
- Remove older `IdentityFile` lines for `github.com`, the LAN servers or `Host *` (for example `IdentityFile ~/.ssh/id_ecdsa_sk_hello` from an earlier version of this page). `IdentityFile` lines add up, so old ones stay active.
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

Expected: two lines, `256 SHA256:... john.doe@hesge.ch (ECDSA-SK)`.

```powershell
ssh-keygen -Y sign -f "$env:USERPROFILE\.ssh\id_github" -n file "$env:USERPROFILE\.ssh\id_github.pub"
```

A **"Sign in with a passkey"** window asks for your PIN. Expected: `Write signature to ...id_github.pub.sig`. Repeat with `id_text_analytics_ch` to check the second key.

## Publish the public keys

**GitHub:** `id_github` only, for login and for commit signing:

```powershell
gh ssh-key add "$env:USERPROFILE\.ssh\id_github.pub" --type authentication --title "$env:COMPUTERNAME hello"
gh ssh-key add "$env:USERPROFILE\.ssh\id_github.pub" --type signing --title "$env:COMPUTERNAME hello"
```

**LAN servers:** `id_text_analytics_ch` only. Run this once for each VM you use:

```powershell
Get-Content "$env:USERPROFILE\.ssh\id_text_analytics_ch.pub" | ssh monitoring "umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys; chmod go-w ~ ~/.ssh ~/.ssh/authorized_keys; (echo; cat) >> ~/.ssh/authorized_keys"
```

- It asks for your VM password once. You need a working password login on the VM; the VM must run Linux with OpenSSH 8.2 or later.
- The command removes write access for others from `~/.ssh` (SSH ignores the key otherwise) and starts the key on a new line. Empty lines in `authorized_keys` are harmless.
- The first connection to a server asks `Are you sure you want to continue connecting (yes/no/[fingerprint])?`. Type **yes** only if the fingerprint shown matches the real one. For GitHub, compare with https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints. For a LAN VM, compare with the fingerprint the admin publishes, or ask the admin. If SSH later prints `REMOTE HOST IDENTIFICATION HAS CHANGED`, stop and tell the admin.

Then test each key. Each command asks for your PIN once.

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

Windows asks for your PIN twice: once for the VM, once for GitHub. Expected: `Hi <you>! ...`. VS Code Remote-SSH reads the same config. If the agent is missing in a VS Code terminal, or if you see `chan_shutdown_read: shutdown() failed ... Not a socket`, see the troubleshooting sections at the end of the [SSH page](https://infra.text-analytics.ch/devdoc/tools/ssh/).

**Git:** repositories cloned with an `https://` URL keep using HTTPS; `git remote -v` shows it. If a GitHub organization uses single sign-on, authorize `id_github` for it at https://github.com/settings/keys (**Configure SSO**). To sign commits with `id_github`, follow [GitHub and commit signing](../secrets-and-keys.md#ssh-keys) and also run `git config --global gpg.ssh.program C:/Windows/System32/OpenSSH/ssh-keygen.exe`.

**Status:** Tested on 2026-10-09 on a Windows 11 LTSC VM (build 26100.9457) with a Windows Hello PIN, in Windows PowerShell 5.1:

- creating both keys with 10.0 Preview, as above;
- logging in with the built-in 9.5p2 and the built-in agent: `id_text_analytics_ch` to a Debian VM standing in for a LAN server, `id_github` to a second Debian VM standing in for GitHub. The PIN was asked on every connection;
- from the first VM, logging in to the second through the forwarded agent. The PIN window opened on the Windows desktop;
- `AddKeysToAgent yes` adding each key to the agent on first use, with no extra prompt. Before that, the forwarded login failed with `Permission denied (publickey)`.

Earlier the same day, with one key (then named `id_ecdsa_sk_hello`): signing with the built-in 9.5p2, and `ssh-add`. The test config had the same `IdentityFile`, `ForwardAgent` and `AddKeysToAgent` lines as the block above, but no `Canonical...` lines and no real host names. Not tested: the block above as written, GitHub itself, `core.sshCommand`, `gh ssh-key add`, the `Get-Content | ssh` line and VS Code. The steps follow https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_keymanagement.

## Fallback (no Windows Hello or TPM): ed25519 keys with a passphrase

**For:** old PCs, VMs without a TPM, or when the steps above fail. Replace `john.doe@hesge.ch` with your email address.

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.ssh" | Out-Null
ssh-keygen -t ed25519 -C "john.doe@hesge.ch" -f "$env:USERPROFILE\.ssh\id_github"
ssh-keygen -t ed25519 -C "john.doe@hesge.ch" -f "$env:USERPROFILE\.ssh\id_text_analytics_ch"
```

For each key:

- `Enter passphrase (empty for no passphrase):` type a **real passphrase**. Do not leave it empty.
- `Enter same passphrase again:` type it again.

Then start the agent and load both keys as in [SSH agent](#ssh-agent) above. `ssh-add` asks `Enter passphrase for C:\Users\...\id_github:` and then for `id_text_analytics_ch`; type each passphrase. Expected reply: `Identity added: ...`.

Use the same [~/.ssh/config](#sshconfig) block.

**Check:** `ssh-add -l` shows two lines, `256 SHA256:... john.doe@hesge.ch (ED25519)`.

**Publish:** use the commands above. After that, `ssh -T git@github.com` prints `Hi <you>! ...` with no passphrase prompt.

**Status:** Tested on 2026-10-09 on the same VM, against `localhost`, with one key (then named `id_ed25519`):

- key creation;
- `ssh-add`;
- login through the agent without a passphrase prompt.

Not tested: two keys, whether the keys are still in the agent after a reboot, forwarding, and GitHub.
