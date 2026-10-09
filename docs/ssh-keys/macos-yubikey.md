# SSH keys: macOS + YubiKey

First read the rules and install the GitHub CLI: see [the setup index](README.md).

**For:** Mac users with a YubiKey 5 (firmware 5.2.3 or later). **You need:** [Homebrew](https://brew.sh), the YubiKey and its FIDO2 PIN. Apple's own `ssh` cannot use USB security keys, so you must use the one from Homebrew.

You create **two keys** on the YubiKey: `~/.ssh/id_github` for GitHub and `~/.ssh/id_text_analytics_ch` for our servers (`*.lan.text-analytics.ch`, the VMs on Hulk). The private keys stay in the YubiKey. The two files are only handles that point to them.

In this page, `<vm>` is a VM name such as `monitoring`. If your login on the VMs is not your Mac user name, write `<login>@<vm>` instead. `john.doe@hesge.ch` stands for your email.

## Day to day: what you are asked

Each use of a key needs a **touch** of the YubiKey, no PIN. The PIN is asked only when you create the keys or download them to another Mac. The `~/.ssh/config` below also makes SSH keep each connection open for 10 minutes and reuse it, so one touch covers every command to the same host in that time.

| Where you are | What you want to do | What happens |
|---|---|---|
| This Mac | `ssh monitoring` | The YubiKey blinks: touch it. Within the next 10 minutes, more `ssh`, `scp` or `rsync` to `monitoring` ask nothing. |
| This Mac | `git pull` / `git push` / `git clone` with GitHub | Touch the YubiKey. More git commands with GitHub in the next 10 minutes ask nothing. |
| This Mac | `scp` / `rsync` to a VM | Touch the YubiKey, unless a connection to that VM is already open. |
| This Mac | Open a VS Code Remote-SSH window, or reconnect after sleep | Touch the YubiKey. |
| This Mac | Commit with SSH signing (if you set it up) | Touch the YubiKey, once per commit. Connection sharing does not help here. |
| This Mac | First use after logging in or a reboot | Nothing extra, if the YubiKey is plugged in. Open Terminal once: it starts the agent and adds the keys, which the VMs need. |
| On a LAN VM (through ssh) | `git pull` / `git push` | Your Mac's YubiKey blinks: touch it there. |
| On a LAN VM (through ssh) | Commit with SSH signing (if you set it up there) | Touch the YubiKey on the Mac, once per commit. |

Good to know:

- A touch proves that someone is at the YubiKey now. Malware on the Mac cannot use the keys without it.
- One SSH connection is one touch. A shared connection stays open 10 minutes after its last use; during that time, any program running as you can use it without a touch. That is the price of fewer touches.
- A VM's request makes the YubiKey on your Mac blink, so you must be at the Mac.
- Long-running AI agents or scripts should not use these keys at all: see [Automation and agents](README.md#automation-and-agents).

When it doesn't work:

- The YubiKey is not plugged in: nothing blinks and the command fails. Plug it in and try again.
- You do not touch it, or you are away when a VM asks: the command waits. Not tested: how long it waits before it fails.
- `git` on a VM says `Permission denied (publickey)`: the GitHub key is not in the agent. Open Terminal on the Mac once, then try again.
- Keys created with an earlier version of this page (server key with `-O verify-required`) keep asking the PIN. To stop that, create new keys and publish them again.

Status of this section: documented, not tested (no Mac was available). Sources: https://developers.yubico.com/SSH/Securing_SSH_with_FIDO2.html, https://man.openbsd.org/ssh-keygen, https://man.openbsd.org/ssh_config.

## Before you start

```sh
brew install openssh ykman
hash -r; which ssh ssh-keygen
ls -a ~/.ssh 2>/dev/null | grep -E '^id_(github|text_analytics_ch)'
```

- `which`: expected `/opt/homebrew/bin/ssh` (on Intel Macs, `/usr/local/bin/ssh`). If you see `/usr/bin/ssh`, add `eval "$(/opt/homebrew/bin/brew shellenv)"` to `~/.zprofile` and open a new terminal.
- `ls`: expected no output. If it lists files, you already have these keys. Stop and ask for help: the steps below must not replace them.
- If the YubiKey has no PIN yet, run `ykman fido access change-pin`.

## Create the keys

```sh
mkdir -p ~/.ssh && chmod 700 ~/.ssh
ssh-keygen -t ed25519-sk -O resident -O application=ssh:github -f ~/.ssh/id_github -C "john.doe@hesge.ch"
ssh-keygen -t ed25519-sk -O resident -O application=ssh:text_analytics_ch -f ~/.ssh/id_text_analytics_ch -C "john.doe@hesge.ch"
```

For each key:

- `Enter PIN for authenticator:` type the YubiKey PIN.
- `You may need to touch your authenticator`: touch the YubiKey when it blinks.
- `Enter passphrase` (asked twice): press **Enter** both times.
- If you see `... already exists. Overwrite key in token (y/n)?`, answer **n** and ask for help.

The two `application` names keep the keys apart on the YubiKey. Without them, the second key would replace the first.

Neither key has `-O verify-required`: in daily use a touch is enough, and the agent can hold both keys. Someone who has both your YubiKey and this Mac's handle files can use the keys without the PIN; keep the YubiKey with you.

**On another Mac:** do "Before you start", then:

```sh
mkdir -p ~/.ssh && chmod 700 ~/.ssh
d=$(mktemp -d) && cd "$d" && ssh-keygen -K
mv -n id_ed25519_sk_rk_github ~/.ssh/id_github
mv -n id_ed25519_sk_rk_github.pub ~/.ssh/id_github.pub
mv -n id_ed25519_sk_rk_text_analytics_ch ~/.ssh/id_text_analytics_ch
mv -n id_ed25519_sk_rk_text_analytics_ch.pub ~/.ssh/id_text_analytics_ch.pub
ls "$d"
```

- `Enter PIN for authenticator:` type the PIN. Touch the YubiKey if it blinks.
- `Enter passphrase` (asked twice): press **Enter** both times.
- Expected: the last `ls` prints nothing. If files are left, `~/.ssh` already had a file with that name: ask for help.

Then follow the agent and `~/.ssh/config` steps. The public keys are already on GitHub and the VMs.

## SSH agent: Homebrew's

Apple's agent cannot use security keys. This starts Homebrew's agent at login, if it is not running yet, and gives it both keys:

```sh
cat >> ~/.zprofile <<'EOF'

B=/opt/homebrew/bin; [ -x "$B/ssh-agent" ] || B=/usr/local/bin
export SSH_AUTH_SOCK="$HOME/.ssh/agent.sock"
"$B/ssh-add" -l >/dev/null 2>&1
if [ $? -eq 2 ]; then
    rm -f "$SSH_AUTH_SOCK"
    "$B/ssh-agent" -a "$SSH_AUTH_SOCK" >/dev/null
fi
"$B/ssh-add" -q ~/.ssh/id_github ~/.ssh/id_text_analytics_ch 2>/dev/null
EOF
```

Open a new terminal. `ssh-add -l` shows two lines `256 SHA256:... john.doe@hesge.ch (ED25519-SK)`.

## ~/.ssh/config

This is the team's block with two changes. `IdentityAgent` points to Homebrew's agent, so that this agent is the one forwarded to the VMs. The `Control...` lines keep each connection open 10 minutes and reuse it (one touch per host instead of per command); `ssh -O exit <host>` closes it early. Not tested against github.com. Create their private folder first:

```sh
mkdir -m 700 -p ~/.ssh/cm
```

If you have no `~/.ssh/config` yet, this creates it. It does not touch an existing file:

```sh
test -e ~/.ssh/config && echo "~/.ssh/config exists: merge by hand" || cat > ~/.ssh/config <<'EOF'
CanonicalizeHostname yes
CanonicalDomains lan.text-analytics.ch
CanonicalizeMaxDots 1

Host *.lan.text-analytics.ch
    AddKeysToAgent yes
    ForwardAgent yes
    IdentityAgent "~/.ssh/agent.sock"
    IdentityFile "~/.ssh/id_text_analytics_ch"
    ControlMaster auto
    ControlPath ~/.ssh/cm/%C
    ControlPersist 10m

Host github.com
    AddKeysToAgent yes
    IdentityAgent "~/.ssh/agent.sock"
    IdentityFile "~/.ssh/id_github"
    ControlMaster auto
    ControlPath ~/.ssh/cm/%C
    ControlPersist 10m
EOF
```

If it printed `~/.ssh/config exists: merge by hand`, open the file with `open -e ~/.ssh/config` and add the same lines (between `cat` and the final `EOF`) by hand:

- Put the three `Canonical...` lines at the very top, above every `Host` line. Below a `Host` line they would apply to that host only.
- Paste the two `Host` blocks above any `Host *` block. For most settings, `ssh` uses the first value it finds.
- Delete old `github.com` or `*.lan.text-analytics.ch` blocks, and `IdentityFile`, `IdentityAgent` or `IdentitiesOnly` lines under `Host *` left from an earlier key setup (for example `id_ed25519_sk`).
- End the file with a line break.

Then check what `ssh` will use:

```sh
ssh -G github.com | grep -E '^(identityfile|identityagent|forwardagent) '
ssh -G monitoring.lan.text-analytics.ch | grep -E '^(identityfile|identityagent|forwardagent) '
```

Expected: both show `identityagent` ending in `agent.sock`. The first shows `forwardagent no` and one `identityfile` ending in `id_github`. The second shows `forwardagent yes` and one ending in `id_text_analytics_ch`.

Forwarding lets the VMs use your GitHub key while you are connected. A stricter option is described in [the secrets and keys guide](../secrets-and-keys.md#servers).

## Publish the public keys

**GitHub** gets `id_github` only, for login and for signing:

```sh
gh ssh-key add ~/.ssh/id_github.pub --type authentication --title "YubiKey id_github"
gh ssh-key add ~/.ssh/id_github.pub --type signing --title "YubiKey id_github"
```

To sign commits, follow "GitHub and commit signing" in [the secrets and keys guide](../secrets-and-keys.md#ssh-keys) with `KEY` = `id_github`.

**Each VM** gets `id_text_analytics_ch`. The VM needs OpenSSH 8.2 or later. Run this once per VM:

```sh
ssh-copy-id -i ~/.ssh/id_text_analytics_ch.pub <vm>
```

- The first time, `ssh` shows the VM's fingerprint and asks `Are you sure you want to continue connecting`. Compare it with the fingerprint the team publishes for that VM, or ask the admin. Type **yes** only if they match.
- If the YubiKey blinks, touch it.
- `password:` type your VM password. Expected: `Number of key(s) added: 1`.

## Check

```sh
ssh -o IdentitiesOnly=yes -T git@github.com
```

- The first time, compare the fingerprint with [GitHub's published fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints). Type **yes** only if it matches.
- Touch the YubiKey when it blinks.
- Expected: `Hi <you>! You've successfully authenticated, but GitHub does not provide shell access.` The exit code is 1; that is normal.

```sh
ssh -o IdentitiesOnly=yes -o PreferredAuthentications=publickey <vm> hostname
```

Expected: a touch, then the VM's name. No password prompt.

```sh
ssh -t <vm> ssh -T git@github.com
```

This uses the GitHub key on the VM, through the forwarded agent. Check GitHub's fingerprint the first time, as above. Expected: the YubiKey blinks (touch it), then `Hi <you>! ...`.

A clone with an `https://` remote keeps using HTTPS. `git remote -v` shows which one a clone uses.

**Status:** Not tested: no Mac was available. Based on https://developers.yubico.com/SSH/Securing_SSH_with_FIDO2.html and https://man.openbsd.org/ssh-keygen. The downloaded file names come from the OpenSSH 10.2 source. Agent forwarding of the touch-only GitHub key is based on https://man.openbsd.org/ssh-agent; it is not tested.
