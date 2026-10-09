# SSH keys: Windows + Bitwarden

First read the rules and install the GitHub CLI: see [the setup index](README.md).

**For:** people who want one SSH key synced to all their computers through their Bitwarden vault. Anyone who gets into your vault gets this key. **You need:** the Bitwarden **desktop** app (the browser extension cannot do this) and admin rights once.

## Create the key

In an **administrator** PowerShell, install Bitwarden and turn off the Windows SSH agent so Bitwarden can take its place:

```powershell
winget install Bitwarden.Bitwarden
Stop-Service ssh-agent -ErrorAction SilentlyContinue
Set-Service ssh-agent -StartupType Disabled
```

- If winget asks `Do you agree to all the source agreements terms?`, type **Y**.

Open Bitwarden and log in. Then:

1. Click **New** > **SSH key**, give it a name, then click **Save**. Bitwarden creates an Ed25519 key and asks nothing.
2. Open the item and copy the **Public key**.

Then, in a normal PowerShell:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.ssh" | Out-Null
Get-Clipboard | Set-Content -Encoding ascii "$env:USERPROFILE\.ssh\bitwarden.pub"
```

## Configure the agent

In Bitwarden **Settings**:

- **Enable SSH agent**: turn on.
- **Ask for authorization when using SSH agent**: leave on.
- **Start automatically on login**: turn on.

```powershell
Add-Content "$env:USERPROFILE\.ssh\config" "`nHost *`n  IdentityFile ~/.ssh/bitwarden.pub"
git config --global core.sshCommand C:/Windows/System32/OpenSSH/ssh.exe
```

The `IdentityFile` line points at the **public** key. It tells SSH which key in the agent to offer.

## Check

With the vault unlocked, run `ssh-add -L`. Expected: `ssh-ed25519 AAAA...`.

## Publish the public key

```powershell
gh ssh-key add "$env:USERPROFILE\.ssh\bitwarden.pub" --type authentication --title "bitwarden"
gh ssh-key add "$env:USERPROFILE\.ssh\bitwarden.pub" --type signing --title "bitwarden"
Get-Content "$env:USERPROFILE\.ssh\bitwarden.pub" | ssh user@server "umask 077; mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys"
```

Then run `ssh -T git@github.com`.

- If the vault is locked, Bitwarden asks you to unlock it.
- Bitwarden then asks you to authorize the request. Click **Authorize**.
- Expected: `Hi <you>! ...`

**Status:** Not tested: no Bitwarden test was run. Based on https://bitwarden.com/help/ssh-agent/ and https://bitwarden.com/help/app-settings/.
