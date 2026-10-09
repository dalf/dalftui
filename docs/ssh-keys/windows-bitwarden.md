# SSH keys: Windows + Bitwarden

First read the rules and install the GitHub CLI: see [the setup index](README.md).

**For:** people who want their SSH keys synced to all their computers through their Bitwarden vault. Anyone who gets into your vault gets these keys. **You need:** the Bitwarden **desktop** app (the browser extension cannot do this) and admin rights once.

You create two keys: one for GitHub and one for our LAN servers (`*.lan.text-analytics.ch`, the VMs on Hulk). Bitwarden keeps both private keys. Your `.ssh` folder only holds the public keys `id_github.pub` and `id_text_analytics_ch.pub`.

## Day to day: what you are asked

Bitwarden's **Ask for authorization when using SSH agent** setting decides how often it asks. The table shows **Always**, the default: a **"Confirm SSH key usage"** window, where you click **Authorize**. With **Remember until vault is locked**, Bitwarden asks once per key and per server, then not again until the vault locks. With **Never**, it asks nothing while the vault is unlocked. Documented, not tested.

| Where you are | What you want to do | What happens |
|---|---|---|
| This computer | `ssh monitoring` | Bitwarden asks: click **Authorize**. |
| This computer | `git pull` / `git push` / `git clone` with GitHub | Bitwarden asks, once per command: click **Authorize**. |
| This computer | `scp` to a VM | Bitwarden asks: click **Authorize**. |
| This computer | Open a VS Code Remote-SSH window, or reconnect after sleep | Bitwarden asks each time VS Code connects: click **Authorize**. |
| This computer | Commit with SSH signing (if you set it up) | Bitwarden asks, once per commit: click **Authorize**. |
| This computer | First use after logging in or a reboot | Bitwarden asks you to unlock the vault, then to authorize. |
| On a LAN VM (through ssh) | `git pull` / `git push` | Bitwarden asks on this computer: click **Authorize** there. |
| On a LAN VM (through ssh) | Commit with SSH signing (if you set it up there) | The same, once per commit. |

Good to know:

- **Authorize** proves that you, at this PC, accept this use of the key. Anyone who can click it in your unlocked session can use the keys.
- One SSH connection is one request. A `git pull` is one connection; a `git rebase` with signing asks once per commit.
- Requests forwarded from a VM are answered on this PC, so you must be at it.

When it doesn't work:

- The vault is locked: Bitwarden comes to the front and asks you to unlock it. If you do not unlock it within 60 seconds, it shows `SSH key request timed out.` and refuses the request.
- Bitwarden is closed: there is no agent, so SSH cannot use the keys. Start Bitwarden.
- You are away when a VM asks: the command waits until you come back and answer.

The Windows SSH cannot share one connection between commands to cut prompts: Win32-OpenSSH lists the client `ControlMaster` among the features that "will not work on Windows yet".

## Create the keys

In an **administrator** PowerShell, install Bitwarden and turn off the Windows SSH agent so Bitwarden can take its place:

```powershell
winget install Bitwarden.Bitwarden
Stop-Service ssh-agent -ErrorAction SilentlyContinue
Set-Service ssh-agent -StartupType Disabled
```

- If winget asks `Do you agree to all the source agreements terms?`, type **Y**.

Open Bitwarden and log in. Then create the GitHub key:

1. Click **New** > **SSH key**, name it `id_github`, then click **Save**. Bitwarden creates an Ed25519 key and asks nothing.
2. Open the item and copy the **Public key**.
3. In a normal PowerShell:

   ```powershell
   New-Item -ItemType Directory -Force "$env:USERPROFILE\.ssh" | Out-Null
   Get-Clipboard | Set-Content -Encoding ascii "$env:USERPROFILE\.ssh\id_github.pub"
   ```

Then the LAN key: repeat steps 1 and 2 with the name `id_text_analytics_ch`, and save it with:

```powershell
Get-Clipboard | Set-Content -Encoding ascii "$env:USERPROFILE\.ssh\id_text_analytics_ch.pub"
```

## Configure the agent

In Bitwarden **Settings**:

- **Enable SSH agent**: turn on.
- **Ask for authorization when using SSH agent**: keep **Always**, the default.
- **Start automatically on login**: turn on.

```powershell
git config --global core.sshCommand C:/Windows/System32/OpenSSH/ssh.exe
```

This makes Git use the SSH that comes with Windows, which talks to Bitwarden's agent.

## ~/.ssh/config

This is the block from the team's [SSH page](https://infra.text-analytics.ch/devdoc/tools/ssh/), without the switch.ch part. One change: `IdentityFile` points to the **public** keys (`.pub`), because Bitwarden keeps the private keys. SSH then offers the matching key from the agent. `AddKeysToAgent` does nothing here, since Bitwarden already holds both keys.

```
CanonicalizeHostname yes
CanonicalDomains lan.text-analytics.ch
CanonicalizeMaxDots 1

Host *.lan.text-analytics.ch
    AddKeysToAgent yes
    ForwardAgent yes
    IdentityFile "~/.ssh/id_text_analytics_ch.pub"

Host github.com
    AddKeysToAgent yes
    IdentityFile "~/.ssh/id_github.pub"
```

Open the file in Notepad. The first line creates an empty file if you have none; it never changes an existing one.

```powershell
if (-not (Test-Path "$env:USERPROFILE\.ssh\config")) { New-Item -ItemType File "$env:USERPROFILE\.ssh\config" | Out-Null }
notepad "$env:USERPROFILE\.ssh\config"
```

Paste the block at the **top** of the file, followed by an empty line, then save. If the file already had content:

- SSH uses the first value it finds for most settings. Keep any `Host *` block **below** the new blocks.
- Remove older `IdentityFile` lines for `github.com`, the LAN servers or `Host *` (for example `IdentityFile ~/.ssh/bitwarden.pub` from an earlier version of this page). `IdentityFile` lines add up, so old ones stay active.
- Do not paste the block twice.

`ForwardAgent yes` lets the LAN servers ask Bitwarden to sign, so `git` on a VM reaches GitHub through your PC. It applies only to `*.lan.text-analytics.ch`.

Check the result. Replace `monitoring` with one of your VMs, here and below:

```powershell
ssh -G github.com | Select-String '^identityfile '
ssh -G monitoring | Select-String '^(hostname|identityfile|forwardagent) '
```

Expected: `identityfile ~/.ssh/id_github.pub` first, then `hostname monitoring.lan.text-analytics.ch`, `forwardagent yes` and `identityfile ~/.ssh/id_text_analytics_ch.pub` first. The second command works only on the LAN or VPN.

## Check

With the vault unlocked, run `ssh-add -L`. Expected: one `ssh-ed25519 AAAA...` line for each SSH key in your vault, including these two. Listing keys does not ask for authorization.

## Publish the public keys

**GitHub:** `id_github` only, for login and for commit signing:

```powershell
gh ssh-key add "$env:USERPROFILE\.ssh\id_github.pub" --type authentication --title "bitwarden"
gh ssh-key add "$env:USERPROFILE\.ssh\id_github.pub" --type signing --title "bitwarden"
```

**LAN servers:** `id_text_analytics_ch` only. Run this once for each VM you use:

```powershell
Get-Content "$env:USERPROFILE\.ssh\id_text_analytics_ch.pub" | ssh monitoring "umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys; chmod go-w ~ ~/.ssh ~/.ssh/authorized_keys; (echo; cat) >> ~/.ssh/authorized_keys"
```

- It asks for your VM password once. You need a working password login on the VM; the VM must run Linux.
- The command removes write access for others from `~/.ssh` (SSH ignores the key otherwise) and starts the key on a new line. Empty lines in `authorized_keys` are harmless.
- The first connection to a server asks `Are you sure you want to continue connecting (yes/no/[fingerprint])?`. Type **yes** only if the fingerprint shown matches the real one. For GitHub, compare with https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints. For a LAN VM, compare with the fingerprint the admin publishes, or ask the admin. If SSH later prints `REMOTE HOST IDENTIFICATION HAS CHANGED`, stop and tell the admin.

Then test each key. If the vault is locked, Bitwarden first asks you to unlock it. Then it asks you to authorize the request: click **Authorize**.

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

Bitwarden asks twice: once for the VM, once for GitHub. Expected: `Hi <you>! ...`. VS Code Remote-SSH reads the same config. If the agent is missing in a VS Code terminal, or if you see `chan_shutdown_read: shutdown() failed ... Not a socket`, see the troubleshooting sections at the end of the [SSH page](https://infra.text-analytics.ch/devdoc/tools/ssh/).

**Git:** repositories cloned with an `https://` URL keep using HTTPS; `git remote -v` shows it. If a GitHub organization uses single sign-on, authorize `id_github` for it at https://github.com/settings/keys (**Configure SSO**). To sign commits with `id_github`, follow [GitHub and commit signing](../secrets-and-keys.md#ssh-keys) and also run `git config --global gpg.ssh.program C:/Windows/System32/OpenSSH/ssh-keygen.exe`, as Bitwarden's page says.

**Status:** Not tested: no Bitwarden test was run, and neither was forwarding. Bitwarden documents agent forwarding (`ssh -A`) and an approval prompt for forwarded requests. Based on https://bitwarden.com/help/ssh-agent/ and https://bitwarden.com/help/app-settings/.
