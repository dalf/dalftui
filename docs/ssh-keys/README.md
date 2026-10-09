# SSH keys: pick your setup

This page shows how to create an SSH key on your computer and get it working with GitHub and our servers. Find your setup in the table, open its page and follow the steps in order. You can copy and paste each command block as it is. Under each command you will find every question the tool asks and the answer to give.

Rules for everyone:

- **One key per device.** Never copy a private key to another computer, and never send one by email or chat.
- **Prefer a key that is locked to hardware.** That means the TPM chip in a Windows or Linux PC, the Secure Enclave in a Mac, or a YubiKey. Someone who steals the key file still cannot use it.
- **Bitwarden** is only for people who want one software key synced to all their computers. It is a deliberate exception to "one key per device".
- Replace `user@server` with your login and server name. Replace `<you>` with your GitHub name.
- The first time you connect to a server, SSH asks `Are you sure you want to continue connecting (yes/no/[fingerprint])?`. Type **yes**.
- Windows commands are for **Windows PowerShell**. macOS commands are for **Terminal** (zsh). Linux commands are for a normal terminal (bash). Commands that need administrator rights say so.

## Pick your setup

| Setup | Key lives in | Prompt each time you use it | Synced | Tested? | Page |
|---|---|---|---|---|---|
| Windows, nothing extra | PC's TPM (Windows Hello) | Windows PIN | No | **Yes** (Windows 11 VM, 2026-10-09) | [windows.md](windows.md) |
| Windows + Bitwarden | Bitwarden vault | "Authorize" click | Yes | No | [windows-bitwarden.md](windows-bitwarden.md) |
| Windows + YubiKey (Bitwarden optional, for passwords only) | YubiKey | YubiKey PIN + touch | Moves with the YubiKey | No | [windows-yubikey.md](windows-yubikey.md) |
| macOS, nothing extra | Mac's Secure Enclave | Touch ID | No | No | [macos.md](macos.md) |
| macOS + Bitwarden | Bitwarden vault | "Authorize" click | Yes | No | [macos-bitwarden.md](macos-bitwarden.md) |
| macOS + YubiKey | YubiKey | YubiKey PIN + touch | Moves with the YubiKey | No | [macos-yubikey.md](macos-yubikey.md) |
| Linux, nothing extra | PC's TPM | TPM PIN (the agent remembers it) | No | **Yes** (Fedora 44 VM, 2026-10-09) | [linux.md](linux.md) |
| Linux + Bitwarden | Bitwarden vault | "Authorize" click | Yes | No | [linux-bitwarden.md](linux-bitwarden.md) |
| Linux + YubiKey | YubiKey | YubiKey PIN + touch | Moves with the YubiKey | No | [linux-yubikey.md](linux-yubikey.md) |

If your computer has no TPM chip or Windows Hello, [windows.md](windows.md) and [linux.md](linux.md) each have a **fallback**: a normal key protected by a passphrase.

### GitHub CLI (once per computer)

You need the GitHub CLI (`gh`) to publish keys. Install it:

- Windows: `winget install --id GitHub.cli`, then open a new PowerShell. The first time you use winget, it asks `Do you agree to all the source agreements terms?`. Type **Y**.
- macOS: `brew install gh`
- Fedora: `sudo dnf install gh`. Ubuntu/Debian: `sudo apt install gh`.

Then log in. This works the same in all three shells:

```sh
gh auth login -h github.com -p ssh --skip-ssh-key -w -s admin:public_key,admin:ssh_signing_key
```

- `First copy your one-time code: XXXX-XXXX` appears. Press **Enter**. Your browser opens. Paste the code and approve.
- Done when you see `Logged in as <you>`.

## Sources

- https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_keymanagement
- https://github.com/PowerShell/Win32-OpenSSH/issues/2040
- https://github.com/PowerShell/Win32-OpenSSH/releases/download/10.0.0.0p2-Preview/OpenSSH-Win64.zip
- https://bitwarden.com/help/ssh-agent/
- https://bitwarden.com/help/app-settings/
- https://developers.yubico.com/SSH/Securing_SSH_with_FIDO2.html
- https://docs.yubico.com/software/yubikey/tools/ykman/FIDO_Commands.html
- https://gist.github.com/arianvp/5f59f1783e3eaf1a2d4cd8e952bb4acf
- https://ewpratten.com/blog/ssh-secure-enclave/
- https://github.com/maxgoedjen/secretive
- https://developer.apple.com/library/archive/technotes/tn2449/_index.html
- https://formulae.brew.sh/formula/openssh
- https://github.com/Foxboron/ssh-tpm-agent
- https://github.com/Foxboron/ssh-tpm-agent/releases/tag/v0.9.0
- https://man.openbsd.org/ssh-keygen
- https://man.openbsd.org/ssh_config
- https://cli.github.com/manual/gh_auth_login
- https://cli.github.com/manual/gh_ssh-key_add
