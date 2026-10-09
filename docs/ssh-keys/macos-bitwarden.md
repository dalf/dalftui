# SSH keys: macOS + Bitwarden

First read the rules and install the GitHub CLI: see [the setup index](README.md).

**For:** Mac users who want their keys synced through their Bitwarden vault. **You need:** the Bitwarden desktop app (from the App Store, or the .dmg from bitwarden.com) and a logged-in account.

You create **two keys**: `id_github` for GitHub and `id_text_analytics_ch` for our servers (`*.lan.text-analytics.ch`, the VMs on Hulk). The private keys stay in the vault. `~/.ssh` only gets the public keys, `~/.ssh/id_github.pub` and `~/.ssh/id_text_analytics_ch.pub`.

In this page, `<vm>` is a VM name such as `monitoring`. If your login on the VMs is not your Mac user name, write `<login>@<vm>` instead.

## Day to day: what you are asked

Bitwarden's setting **Ask for authorization when using SSH agent** decides how often it asks. The table is for **Always**: a "Confirm SSH key usage" window, where you click **Authorize**.

| Where you are | What you want to do | What happens |
|---|---|---|
| This Mac | `ssh monitoring` | Bitwarden asks: click **Authorize**. |
| This Mac | `git pull` / `git push` / `git clone` with GitHub | Bitwarden asks: click **Authorize**. |
| This Mac | `scp` / `rsync` to a VM | Bitwarden asks: click **Authorize**. |
| This Mac | Open a VS Code Remote-SSH window, or reconnect after sleep | Bitwarden asks, once for each SSH connection VS Code opens. |
| This Mac | Commit with SSH signing (if you set it up) | Bitwarden asks, once per commit. |
| This Mac | First use after logging in or a reboot | Bitwarden must be running. It asks you to unlock the vault (master password, or Touch ID if turned on), then to authorize. |
| On a LAN VM (through ssh) | `git pull` / `git push` | Bitwarden asks on the Mac: click **Authorize** there. |
| On a LAN VM (through ssh) | Commit with SSH signing (if you set it up there) | Bitwarden asks on the Mac, once per commit. |

The other choices:

- **Remember until vault is locked**: one **Authorize** per key and per server (GitHub, each VM; a VM's use of the GitHub key counts apart), then nothing until the vault locks.
- **Never**: nothing while the vault is unlocked.

Good to know:

- **Authorize** proves that someone at the Mac agreed to this use. Unlocking proves that person knows the master password (or has the Mac's Touch ID).
- One SSH connection is one prompt. A `git pull` is one. A rebase that signs commits is one per commit.
- A VM's request is shown on the Mac, so you must be at the Mac.
- With **Never**, a VM you are connected to can use your keys without asking, while the vault is unlocked.

When it doesn't work:

- Bitwarden is closed: there is no agent, so the keys cannot be used. GitHub refuses, and a VM asks for its password. Start Bitwarden.
- The vault is locked: Bitwarden shows "Please unlock your vault to approve the SSH key request." Unlock it within a minute, or Bitwarden shows "SSH key request timed out." and the command fails.
- You are away, or the Mac is locked or asleep: nobody clicks **Authorize**, and the command waits.

Tip: SSH connection sharing lets later connections to the same VM reuse the first one, without a new prompt. VS Code's Remote-SSH docs suggest these lines (add them to the `Host *.lan.text-analytics.ch` block, then run `mkdir -p ~/.ssh/sockets`): `ControlMaster auto`, `ControlPath ~/.ssh/sockets/%r@%h-%p`, `ControlPersist 600`. It does not change the prompts for GitHub from a VM.

Status of this section: documented, not tested (no Mac was available). Sources: https://bitwarden.com/help/ssh-agent/, the Bitwarden desktop app's English texts (https://github.com/bitwarden/clients, `apps/desktop/src/locales/en/messages.json` and `apps/desktop/src/autofill/services/ssh-agent.service.ts`), https://code.visualstudio.com/docs/remote/troubleshooting, https://man.openbsd.org/ssh_config.

## Before you start

```sh
ls -a ~/.ssh 2>/dev/null | grep -E '^id_(github|text_analytics_ch)'
```

Expected: no output. If it lists files, you already have these keys. Stop and ask for help: the steps below must not replace them.

## Create the keys

1. In Bitwarden, click **New** > **SSH key**, name it `id_github`, then click **Save**. Bitwarden creates an Ed25519 key and asks no questions.
2. Do the same for a second key named `id_text_analytics_ch`.

Open the `id_github` item, click copy on **Public key**, then run:

```sh
mkdir -p ~/.ssh && chmod 700 ~/.ssh && pbpaste > ~/.ssh/id_github.pub
```

Open the `id_text_analytics_ch` item, click copy on **Public key**, then run:

```sh
pbpaste > ~/.ssh/id_text_analytics_ch.pub
```

## Configure the agent

- In Bitwarden **Settings**, tick **Enable SSH agent**.
- To start Bitwarden at login: System Settings > General > Login Items > **+** > Bitwarden.

Run **only one** of the next two blocks: the first for the .dmg version, the second for the App Store version.

```sh
# .dmg version
S="$HOME/.bitwarden-ssh-agent.sock"
```

```sh
# App Store version
S="$HOME/Library/Containers/com.bitwarden.desktop/Data/.bitwarden-ssh-agent.sock"
```

Then, in the same terminal:

```sh
printf '\nexport SSH_AUTH_SOCK="%s"\n' "$S" >> ~/.zshrc
```

## ~/.ssh/config

This is the team's block with two changes. `IdentityAgent` points to Bitwarden for apps that do not read `~/.zshrc`. `IdentityFile` names the `.pub` files, because the private keys are in the vault. `AddKeysToAgent` is gone, because the keys are already in Bitwarden's agent.

If you have no `~/.ssh/config` yet, run this in the same terminal as the block above. It does not touch an existing file:

```sh
test -e ~/.ssh/config && echo "~/.ssh/config exists: merge by hand" || cat > ~/.ssh/config <<EOF
CanonicalizeHostname yes
CanonicalDomains lan.text-analytics.ch
CanonicalizeMaxDots 1

Host *.lan.text-analytics.ch
    ForwardAgent yes
    IdentityAgent "$S"
    IdentityFile "~/.ssh/id_text_analytics_ch.pub"

Host github.com
    IdentityAgent "$S"
    IdentityFile "~/.ssh/id_github.pub"
EOF
```

If it printed `~/.ssh/config exists: merge by hand`, open the file with `open -e ~/.ssh/config` and add the block by hand. Use this text, with the App Store socket path if you have that version:

```
CanonicalizeHostname yes
CanonicalDomains lan.text-analytics.ch
CanonicalizeMaxDots 1

Host *.lan.text-analytics.ch
    ForwardAgent yes
    IdentityAgent "~/.bitwarden-ssh-agent.sock"
    IdentityFile "~/.ssh/id_text_analytics_ch.pub"

Host github.com
    IdentityAgent "~/.bitwarden-ssh-agent.sock"
    IdentityFile "~/.ssh/id_github.pub"
```

- Put the three `Canonical...` lines at the very top, above every `Host` line. Below a `Host` line they would apply to that host only.
- Paste the two `Host` blocks above any `Host *` block. For most settings, `ssh` uses the first value it finds.
- Delete old `github.com` or `*.lan.text-analytics.ch` blocks, and `IdentityFile`, `IdentityAgent` or `IdentitiesOnly` lines under `Host *` left from an earlier key setup (for example `bitwarden.pub`).
- End the file with a line break.

Then check what `ssh` will use:

```sh
ssh -G github.com | grep -E '^(identityfile|identityagent|forwardagent) '
ssh -G monitoring.lan.text-analytics.ch | grep -E '^(identityfile|identityagent|forwardagent) '
```

Expected: both show Bitwarden's socket as `identityagent`. The first shows `forwardagent no` and one `identityfile` ending in `id_github.pub`. The second shows `forwardagent yes` and one ending in `id_text_analytics_ch.pub`.

Forwarding lets the VMs use your keys while you are connected. A stricter option is described in [the secrets and keys guide](../secrets-and-keys.md#servers).

With the vault unlocked, open a new terminal and run `ssh-add -L`. Expected: two `ssh-ed25519 AAAA...` lines, or more if the vault has other SSH keys.

## Publish the public keys

**GitHub** gets `id_github` only, for login and for signing:

```sh
gh ssh-key add ~/.ssh/id_github.pub --type authentication --title "bitwarden id_github"
gh ssh-key add ~/.ssh/id_github.pub --type signing --title "bitwarden id_github"
```

To sign commits, follow "GitHub and commit signing" in [the secrets and keys guide](../secrets-and-keys.md#ssh-keys) with `KEY` = `id_github`.

**Each VM** gets `id_text_analytics_ch`. Run this once per VM:

```sh
ssh-copy-id -f -i ~/.ssh/id_text_analytics_ch.pub <vm>
```

- `ssh-copy-id` needs `-f` because there is no private key file on disk.
- The first time, `ssh` shows the VM's fingerprint and asks `Are you sure you want to continue connecting`. Compare it with the fingerprint the team publishes for that VM, or ask the admin. Type **yes** only if they match.
- `password:` type your VM password. Expected: `Number of key(s) added: 1`.

## Check

Keep the vault unlocked. When Bitwarden asks, click **Authorize**.

```sh
ssh -o IdentitiesOnly=yes -T git@github.com
```

- The first time, compare the fingerprint with [GitHub's published fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints). Type **yes** only if it matches.
- Expected: `Hi <you>! You've successfully authenticated, but GitHub does not provide shell access.` The exit code is 1; that is normal.

```sh
ssh -o IdentitiesOnly=yes -o PreferredAuthentications=publickey <vm> hostname
```

Expected: the VM's name. No password prompt.

```sh
ssh -t <vm> ssh -T git@github.com
```

This uses the GitHub key on the VM, through the forwarded agent. Check GitHub's fingerprint the first time, as above. Expected: Bitwarden asks on the Mac, then `Hi <you>! ...`.

A clone with an `https://` remote keeps using HTTPS. `git remote -v` shows which one a clone uses.

**Status:** Not tested: no Mac was available. Based on https://bitwarden.com/help/ssh-agent/, which says agent forwarding works.
