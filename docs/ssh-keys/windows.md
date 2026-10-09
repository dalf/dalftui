# SSH keys: Windows, nothing extra

First read the rules and install the GitHub CLI: see [the setup index](README.md).

**For:** Windows 11 users with a Windows Hello PIN or fingerprint. **You need:**

- Windows Hello turned on (Settings > Accounts > Sign-in options);
- Windows PowerShell;
- to sit at the PC itself. These steps do not work over SSH.

The key lives in the PC's TPM chip. The file in `.ssh` only points to it, so a copy of that file is useless.

## Create the key

The SSH that comes with Windows (9.5p2) **cannot create** this key. It fails with `Key enrollment failed: invalid format`. The block below downloads OpenSSH 10.0 Preview to a temporary folder, uses it to create the key, then deletes it.

```powershell
$d = "$env:TEMP\openssh10"
New-Item -ItemType Directory -Force $d, "$env:USERPROFILE\.ssh" | Out-Null
curl.exe -L -o "$d\o.zip" https://github.com/PowerShell/Win32-OpenSSH/releases/download/10.0.0.0p2-Preview/OpenSSH-Win64.zip
Expand-Archive "$d\o.zip" $d -Force
$env:SSH_SK_HELPER = "$d\OpenSSH-Win64\ssh-sk-helper.exe"
& "$d\OpenSSH-Win64\ssh-keygen.exe" -t ecdsa-sk -C "$env:USERNAME@$env:COMPUTERNAME" -f "$env:USERPROFILE\.ssh\id_ecdsa_sk_hello"
Remove-Item Env:SSH_SK_HELPER; Remove-Item -Recurse -Force $d
```

- The download takes about 20 seconds. Then the window shows `You may need to touch your authenticator to authorize key generation.`
- A **"Windows Security – Save your passkey"** window opens. Click **Continue**. When it asks **Enter your PIN**, type your Windows PIN.
- `Enter passphrase for "C:\Users\...\id_ecdsa_sk_hello" (empty for no passphrase):` press **Enter**.
- `Enter same passphrase again:` press **Enter**.
- Done when you see `Your identification has been saved in ...id_ecdsa_sk_hello`.

Do not add `-N ""`, because Windows PowerShell 5.1 drops empty arguments.

## SSH agent: not needed

Windows asks for your PIN every time the key is used, and an agent cannot change that. One config line tells SSH which key to use:

```powershell
Add-Content "$env:USERPROFILE\.ssh\config" "`nHost *`n  IdentityFile ~/.ssh/id_ecdsa_sk_hello"
git config --global core.sshCommand C:/Windows/System32/OpenSSH/ssh.exe
```

- Use `Add-Content`, not `>`. `Add-Content` writes the file in an encoding SSH can read.
- The second line makes Git use the SSH that comes with Windows instead of the one bundled with Git. Skip it if Git is not installed.

If you prefer to use the agent:

1. In an **administrator** PowerShell, run `Get-Service ssh-agent | Set-Service -StartupType Automatic; Start-Service ssh-agent`.
2. In a normal PowerShell, run `ssh-add $HOME\.ssh\id_ecdsa_sk_hello`. It replies `Identity added: ...` without asking anything.

Windows still asks for the PIN on every connection.

## Check

```powershell
ssh-keygen -Y sign -f "$env:USERPROFILE\.ssh\id_ecdsa_sk_hello" -n file "$env:USERPROFILE\.ssh\id_ecdsa_sk_hello.pub"
```

A **"Sign in with a passkey"** window asks for your PIN. Expected: `Write signature to ...id_ecdsa_sk_hello.pub.sig`.

## Publish the public key

```powershell
gh ssh-key add "$env:USERPROFILE\.ssh\id_ecdsa_sk_hello.pub" --type authentication --title "$env:COMPUTERNAME hello"
gh ssh-key add "$env:USERPROFILE\.ssh\id_ecdsa_sk_hello.pub" --type signing --title "$env:COMPUTERNAME hello"
Get-Content "$env:USERPROFILE\.ssh\id_ecdsa_sk_hello.pub" | ssh user@server "umask 077; mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys"
```

- The last line asks for your server password once. The server needs OpenSSH 8.2 or later.
- Then run `ssh -T git@github.com`. It prints `Confirm user presence for key ECDSA-SK SHA256:...`, and a "Sign in with a passkey" window asks for your PIN. Expected: `User presence confirmed`, then `Hi <you>! You've successfully authenticated, but GitHub does not provide shell access.`

**Status:** Tested on 2026-10-09 on a Windows 11 LTSC VM (build 26100.9457) with a Windows Hello PIN, in Windows PowerShell 5.1:

- creating the key with 10.0 Preview;
- signing with the built-in 9.5p2;
- logging in with the built-in 9.5p2 through the `IdentityFile` line;
- logging in through the built-in agent, with the PIN asked on every connection.

The logins were tested against `localhost`. Not tested: GitHub, `core.sshCommand`, `gh ssh-key add` and the `Get-Content | ssh` line. These follow https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_keymanagement.

## Fallback (no Windows Hello or TPM): ed25519 key with a passphrase

**For:** old PCs, VMs without a TPM, or when the steps above fail.

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.ssh" | Out-Null
ssh-keygen -t ed25519 -C "$env:USERNAME@$env:COMPUTERNAME" -f "$env:USERPROFILE\.ssh\id_ed25519"
```

- `Enter passphrase (empty for no passphrase):` type a **real passphrase**. Do not leave it empty.
- `Enter same passphrase again:` type it again.

Make the agent start at boot. Run this once in an **administrator** PowerShell. As shipped, the service is Stopped and Disabled.

```powershell
Get-Service ssh-agent | Set-Service -StartupType Automatic
Start-Service ssh-agent
```

Then, in a normal PowerShell:

```powershell
ssh-add "$env:USERPROFILE\.ssh\id_ed25519"
git config --global core.sshCommand C:/Windows/System32/OpenSSH/ssh.exe
```

- `Enter passphrase for C:\Users\...\id_ed25519:` type your passphrase. Expected reply: `Identity added: ...`

**Check:** `ssh-add -l` shows `256 SHA256:... (ED25519)`.

**Publish:** use the commands above with `id_ed25519.pub`. After that, `ssh -T git@github.com` prints `Hi <you>! ...` with no passphrase prompt.

**Status:** Tested on 2026-10-09 on the same VM, against `localhost`:

- key creation;
- `ssh-add`;
- login through the agent without a passphrase prompt.

Not tested: whether the key is still in the agent after a reboot, and GitHub.
