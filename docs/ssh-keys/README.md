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

| Setup | Keys live in | What you are asked | Synced | Tested? | Page |
|---|---|---|---|---|---|
| Windows, nothing extra | Windows Hello (TPM when the PC has one) | Windows PIN, every use | No | **Yes** (Windows 11 VM, 2026-10-09) | [windows.md](windows.md) |
| Windows + Bitwarden | Bitwarden vault | "Authorize" click, every use (default setting) | Yes | No | [windows-bitwarden.md](windows-bitwarden.md) |
| Windows + YubiKey (Bitwarden optional, for passwords only) | YubiKey | A touch, every use (no connection sharing on Windows) | Moves with the YubiKey | No | [windows-yubikey.md](windows-yubikey.md) |
| macOS, nothing extra | Mac's Secure Enclave | Touch ID, every use (fallback: nothing) | No | No | [macos.md](macos.md) |
| macOS + Bitwarden | Bitwarden vault | "Authorize" click, every use (default setting) | Yes | No | [macos-bitwarden.md](macos-bitwarden.md) |
| macOS + YubiKey | YubiKey | A touch, then nothing for 10 minutes to the same host | Moves with the YubiKey | No | [macos-yubikey.md](macos-yubikey.md) |
| Linux, nothing extra | PC's TPM | TPM PIN once per key per login, then nothing | No | **Yes** (Fedora 44 VM, 2026-10-09) | [linux.md](linux.md) |
| Linux + Bitwarden | Bitwarden vault | "Authorize" click, every use (default setting) | Yes | No | [linux-bitwarden.md](linux-bitwarden.md) |
| Linux + YubiKey | YubiKey | A touch, then nothing for 10 minutes to the same host | Moves with the YubiKey | No | [linux-yubikey.md](linux-yubikey.md) |

Each page has a section "Day to day: what you are asked": what each command asks you, on your computer and from a VM.

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

## Automation and agents

The keys on these pages are for **you, at the keyboard**. An AI coding agent (Claude Code, Codex, Copilot, Cursor…) or a script that works on its own for hours must not use them, nor your `gh` login token. Give it **its own credential**, limited to what it needs, and run it **apart from your account**.

Why:

- An agent that runs as your user can read what you can: `gh auth token` prints your GitHub token, which reaches every repository you can reach. Malware stole tokens this way in 2025 ([s1ngularity](https://www.wiz.io/blog/s1ngularity-supply-chain-attack), [Shai-Hulud](https://www.wiz.io/blog/shai-hulud-npm-supply-chain-attack)). Setting `GH_TOKEN` for the agent does not hide that token.
- While an SSH connection is shared (the 10-minute window on the YubiKey pages), any program running as you can use it without a touch. Stretching that window to cover hours of agent work removes the protection of the hardware key.
- An agent can be steered by what it reads (a web page, an issue, a file in a repository). Limit what it can reach, not only what it is told.

What to do:

1. **Run the agent apart from your account:** in a LAN VM you reach with `ssh -a` (no agent forwarding), in a separate user account, or in a container started without your `~/.ssh`, your `SSH_AUTH_SOCK` or your git credentials. A hosted agent (GitHub's Copilot agent, Claude Code on the web) is the simplest choice on any OS.
2. **Give it its own GitHub credential:**
   - A [fine-grained token](https://github.com/settings/personal-access-tokens/new): only the repositories it works on; permissions **Contents** and **Pull requests** read and write (Metadata read is added automatically); no Workflows or Administration permission; an expiry of 30 to 90 days. In the agent's environment: `export GH_TOKEN=github_pat_...` then `gh auth setup-git`.
   - Or a [deploy key](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys) for a single repository (a software SSH key that only reaches that repository; it never expires, so delete it when the work ends).
   - For several people or many repositories, a [GitHub App](https://docs.github.com/en/apps/creating-github-apps/about-creating-github-apps/about-creating-github-apps) gives tokens that expire after one hour and commits under the app's own name.
3. **Let GitHub limit the damage:** the agent pushes branches and opens pull requests; protect `main` with a rule that requires a pull request and blocks force-push and deletion. A pull request opened with your fine-grained token counts as yours, and you cannot approve your own pull request, so a second person reviews it, or the agent gets its own identity (a GitHub App or a separate account).
4. **Keep a list** of where each agent credential lives, and delete it when the work is done.

On your own computer, you can also narrow your `gh` token: `gh auth refresh --remove-scopes workflow` removes its right to change GitHub Actions workflows.

Sources: [GitHub: personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens), [GitHub: Copilot agent risks and mitigations](https://docs.github.com/en/copilot/concepts/agents/cloud-agent/risks-and-mitigations), [Anthropic: Claude Code in self-hosted environments](https://code.claude.com/docs/en/self-hosted-environments-deploy), [Anthropic: devcontainer](https://code.claude.com/docs/en/devcontainer), [Simon Willison: the lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/).

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
