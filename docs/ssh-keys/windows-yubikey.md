# SSH keys: Windows + YubiKey

First read the rules and install the GitHub CLI: see [the setup index](README.md).

**For:** people who carry a YubiKey and use several PCs. If you also use Bitwarden, it only stores your passwords in this setup. **You need:**

- a YubiKey 5 with firmware 5.2.3 or later (older firmware: use `-t ecdsa-sk`);
- a FIDO2 PIN on the YubiKey;
- the SSH that comes with Windows, version 8.9 or later (check with `ssh -V`);
- to sit at the PC itself.

## Create the key (once, on the first PC)

YubiKeys work with the SSH that comes with Windows. No download is needed.

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.ssh" | Out-Null
ssh-keygen -t ed25519-sk -O resident -O verify-required -C "$env:USERNAME-yubikey" -f "$env:USERPROFILE\.ssh\id_ed25519_sk"
```

- If a **"Save your passkey"** window says `This will be saved to your Windows device`, click **Change**, choose **Security key**, then **Next**.
- Insert the YubiKey, enter its **PIN**, and **touch** it when it blinks.
- `Enter passphrase` (asked twice): press **Enter** both times. The secret stays on the YubiKey.

**On another PC:** open an **administrator** PowerShell and run:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.ssh" | Out-Null
cd "$env:USERPROFILE\.ssh"; ssh-keygen -K
Move-Item -Force id_ed25519_sk_rk id_ed25519_sk; Move-Item -Force id_ed25519_sk_rk.pub id_ed25519_sk.pub
```

It asks for the PIN and a touch. Press **Enter** at both passphrase prompts.

## SSH agent: not needed

The PIN and a touch are needed every time.

```powershell
Add-Content "$env:USERPROFILE\.ssh\config" "`nHost *`n  IdentityFile ~/.ssh/id_ed25519_sk"
git config --global core.sshCommand C:/Windows/System32/OpenSSH/ssh.exe
```

## Check

```powershell
ssh-keygen -Y sign -f "$env:USERPROFILE\.ssh\id_ed25519_sk" -n file "$env:USERPROFILE\.ssh\id_ed25519_sk.pub"
```

It asks for the PIN and a touch. Expected: `Write signature to ...id_ed25519_sk.pub.sig`.

## Publish the public key (once, from any PC)

```powershell
gh ssh-key add "$env:USERPROFILE\.ssh\id_ed25519_sk.pub" --type authentication --title "yubikey"
gh ssh-key add "$env:USERPROFILE\.ssh\id_ed25519_sk.pub" --type signing --title "yubikey"
Get-Content "$env:USERPROFILE\.ssh\id_ed25519_sk.pub" | ssh user@server "umask 077; mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys"
```

Then run `ssh -T git@github.com`. It asks for the PIN and a touch, then shows `Hi <you>! ...`.

**Status:** Not tested: no YubiKey was available. Based on https://developers.yubico.com/SSH/Securing_SSH_with_FIDO2.html. https://github.com/PowerShell/Win32-OpenSSH/issues/2040 reports that the built-in SSH creates YubiKey keys correctly.
