# SSH keys: pick your setup

This page shows how to create SSH keys on your computer and get them working with GitHub and our servers. Find your setup in the table, open its page and follow the steps in order. Under each command you will find every question the tool asks and the answer to give. Replace the placeholders before you run a command.

## Two keys per device

Every setup creates two keys on each computer:

| Key | Used for | File |
|---|---|---|
| GitHub key | GitHub: clone, push, sign commits | `~/.ssh/id_github` |
| LAN key | The VMs on Hulk (`*.lan.text-analytics.ch`) | `~/.ssh/id_text_analytics_ch` |

Why two: one key for everything is a risk. If one key leaks, the other access stays safe, and you can revoke one without touching the other.

The file names are the same on every setup. On Windows they are `$env:USERPROFILE\.ssh\id_github` and `$env:USERPROFILE\.ssh\id_text_analytics_ch`. When the key lives in hardware (TPM, Secure Enclave, YubiKey), the file is only a handle: it points to the key but does not contain the secret. On Linux with a TPM the handle is `id_github.tpm`. With Bitwarden or Secretive there is no private file at all, only the `.pub`. The public keys are the same names with `.pub`.

Each key has a comment: your email, given with `-C`. The pages use `john.doe@hesge.ch`. Replace it with your own address.

## Rules for everyone

- **Keys stay on their device.** Never copy a private key to another computer, and never send one by email or chat.
- **Prefer a key that is locked to hardware.** That means the TPM chip in a Linux PC, Windows Hello, the Secure Enclave in a Mac, or a YubiKey. Someone who copies the file cannot use the key. Windows Hello uses the TPM when the PC has one; this was tested only in a Windows 11 VM, so we do not promise TPM protection on every PC.
- **Bitwarden** is only for people who want their software keys synced to all their computers. It is a deliberate exception to "keys stay on their device".
- Replace `<vm>` with a VM name such as `monitoring`. Replace `<you>` with your GitHub name.
- **Check the server's fingerprint the first time you connect.** SSH asks `Are you sure you want to continue connecting (yes/no/[fingerprint])?` and shows a fingerprint. For `github.com`, compare it with [GitHub's published fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints). For a VM, compare it with the fingerprint the team publishes, or ask the admin. Type **yes** only if it matches. If SSH later says the host key has changed, stop and tell the admin. Do not delete the line from `known_hosts`.
- Windows commands are for **Windows PowerShell**. macOS commands are for **Terminal** (zsh). Linux commands are for a normal terminal (bash). Commands that need administrator rights say so.

## Pick your setup

Each setup creates both keys.

| Setup | Keys live in | Prompt each time you use them | Synced | Tested? | Page |
|---|---|---|---|---|---|
| Windows, nothing extra | Windows Hello (TPM when the PC has one) | Windows PIN | No | **Yes** (Windows 11 VM, 2026-10-09) | [windows.md](windows.md) |
| Windows + Bitwarden | Bitwarden vault | "Authorize" click | Yes | No | [windows-bitwarden.md](windows-bitwarden.md) |
| Windows + YubiKey (Bitwarden optional, for passwords only) | YubiKey | YubiKey PIN + touch | Moves with the YubiKey | No | [windows-yubikey.md](windows-yubikey.md) |
| macOS, nothing extra | Mac's Secure Enclave | Touch ID | No | No | [macos.md](macos.md) |
| macOS + Bitwarden | Bitwarden vault | "Authorize" click | Yes | No | [macos-bitwarden.md](macos-bitwarden.md) |
| macOS + YubiKey | YubiKey | YubiKey PIN + touch (GitHub key: touch only) | Moves with the YubiKey | No | [macos-yubikey.md](macos-yubikey.md) |
| Linux, nothing extra | PC's TPM | TPM PIN (once per agent start) | No | **Yes** (Fedora 44 VM, 2026-10-09) | [linux.md](linux.md) |
| Linux + Bitwarden | Bitwarden vault | "Authorize" click | Yes | No | [linux-bitwarden.md](linux-bitwarden.md) |
| Linux + YubiKey | YubiKey | YubiKey PIN + touch | Moves with the YubiKey | No | [linux-yubikey.md](linux-yubikey.md) |

If your computer has no TPM chip or Windows Hello, [windows.md](windows.md), [macos.md](macos.md) and [linux.md](linux.md) each have a **fallback**: normal keys protected by a passphrase.

## SSH configuration (~/.ssh/config)

Every setup uses this block. On Windows the file is `$env:USERPROFILE\.ssh\config`; the `~/` paths work there too.

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

What it does:

- The first three lines let you type `ssh monitoring` instead of `ssh monitoring.lan.text-analytics.ch`.
- Each `Host` block sends one key to one place: the LAN key to the VMs, the GitHub key to GitHub.
- `AddKeysToAgent yes` loads the key into your agent the first time you use it.
- `ForwardAgent yes` lets you use your GitHub key from a VM, for example `git pull` on the VM, without copying the key there. While you are connected, root on that VM can use your agent, but cannot copy the key. Forward only to VMs you trust. A stricter option is described in [secrets-and-keys.md](../secrets-and-keys.md#servers).

Some setups change a line, for example to name their own agent (`IdentityAgent`) or to point `IdentityFile` to the `.pub` files. The setup page shows its version and says why.

How to add it:

- **No config file yet:** create it with the block as its content.
- **The file exists:** open it in a text editor. Do not just append the block at the end.
  - Put the three `Canonicalize` lines at the top, before the first `Host` line. Anything after a `Host` line belongs to that host only.
  - Put the two `Host` blocks before any `Host *` block. For most settings SSH uses the first value it finds, so a `Host *` block above them can override them.
  - If the file already has a `Host github.com` or `Host *.lan.text-analytics.ch` block, edit that block instead of adding a second one.
  - Remove `IdentityFile` lines that point to an old key for the same host. SSH tries every `IdentityFile` that matches.
  - Make sure the file ends with an empty line.

Check the result. This works the same in all three shells:

```sh
ssh -G github.com
```

Look for `identityfile ~/.ssh/id_github` (or `id_github.pub`, if your setup page uses it) in the output. Then run `ssh -G monitoring.lan.text-analytics.ch` and look for `identityfile ~/.ssh/id_text_analytics_ch` and `forwardagent yes`. If you see an error instead, fix the line it names.

## GitHub CLI (once per computer)

You need the GitHub CLI (`gh`) to publish the GitHub key. Install it:

- Windows: `winget install --id GitHub.cli`, then open a new PowerShell. The first time you use winget, it asks `Do you agree to all the source agreements terms?`. Type **Y**.
- macOS: `brew install gh`
- Fedora: `sudo dnf install gh`. Ubuntu/Debian: `sudo apt install gh`.

Then log in. This works the same in all three shells:

```sh
gh auth login -h github.com -p ssh --skip-ssh-key -w -s admin:public_key,admin:ssh_signing_key
```

- `First copy your one-time code: XXXX-XXXX` appears. Press **Enter**. Your browser opens. Paste the code and approve.
- Done when you see `Logged in as <you>`.

Each setup page then publishes `id_github.pub` twice: once for authentication, once for signing. Only the GitHub key goes to GitHub. The LAN key goes to the VMs.

After the setup:

- `ssh -T git@github.com` prints `Hi <you>! You've successfully authenticated, but GitHub does not provide shell access.` It exits with status 1. That is normal.
- Existing clones keep their remote. Run `git remote -v` in a clone. If it shows `https://github.com/...`, Git still uses HTTPS there. To switch it to SSH: `git remote set-url origin git@github.com:<owner>/<repo>.git`.
- If your organization uses single sign-on, authorize the key for it on GitHub (Settings → SSH and GPG keys → Configure SSO).
- To sign your commits with the GitHub key, follow "GitHub and commit signing" in [secrets-and-keys.md](../secrets-and-keys.md#ssh-keys), with `KEY` replaced by `id_github`.

## Sources

- https://infra.text-analytics.ch/devdoc/tools/ssh/
- https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints
- https://docs.github.com/en/authentication/connecting-to-github-with-ssh/testing-your-ssh-connection
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
- https://docs.github.com/en/get-started/git-basics/managing-remote-repositories
