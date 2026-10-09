# SSH keys: macOS, nothing extra

First read the rules and install the GitHub CLI: see [the setup index](README.md).

**For:** Mac users without a YubiKey or Bitwarden. **You need:**

- a Mac with Touch ID, or Apple Silicon or a T2 chip;
- macOS 26 for the built-in Secure Enclave key;
- [Homebrew](https://brew.sh) for the Secretive app.

You create **two keys**: `~/.ssh/id_github` for GitHub and `~/.ssh/id_text_analytics_ch` for our servers (`*.lan.text-analytics.ch`, the VMs on Hulk). Pick **one** of the three ways below. On an older Mac, use the fallback.

In this page, `<vm>` is a VM name such as `monitoring`. If your login on the VMs is not your Mac user name, write `<login>@<vm>` instead. `john.doe@hesge.ch` stands for your email.

## Day to day: what you are asked

What each option asks for when you use the keys. "On a LAN VM" means you are connected to the VM with `ssh` or VS Code, and the VM uses the GitHub key through your Mac.

### Option 1: built-in Secure Enclave key

| Where you are | What you want to do | What happens |
|---|---|---|
| This Mac | `ssh monitoring` | Touch ID: touch the sensor. |
| This Mac | `git pull` / `git push` / `git clone` with GitHub | Touch ID: touch the sensor. |
| This Mac | `scp` / `rsync` to a VM | Touch ID: touch the sensor. |
| This Mac | Open a VS Code Remote-SSH window, or reconnect after sleep | Touch ID, once for each SSH connection VS Code opens. |
| This Mac | Commit with SSH signing (if you set it up) | Touch ID, once per commit. |
| This Mac | First use after logging in or a reboot | Nothing extra. Open Terminal once: it puts the keys in the agent, which the VMs need. |
| On a LAN VM (through ssh) | `git pull` / `git push` | Touch ID on the Mac: touch the sensor there. |
| On a LAN VM (through ssh) | Commit with SSH signing (if you set it up there) | Touch ID on the Mac, once per commit. |

### Option 2: Secretive app

With **Require authentication** ticked, each use asks Touch ID (or your Apple Watch), and Secretive shows a notification.

| Where you are | What you want to do | What happens |
|---|---|---|
| This Mac | `ssh monitoring` | Touch ID: touch the sensor. |
| This Mac | `git pull` / `git push` / `git clone` with GitHub | Touch ID: touch the sensor. |
| This Mac | `scp` / `rsync` to a VM | Touch ID: touch the sensor. |
| This Mac | Open a VS Code Remote-SSH window, or reconnect after sleep | Touch ID, once for each SSH connection VS Code opens. |
| This Mac | Commit with SSH signing (if you set it up) | Touch ID, once per commit. |
| This Mac | First use after logging in or a reboot | Nothing extra: SecretAgent starts at login. |
| On a LAN VM (through ssh) | `git pull` / `git push` | Touch ID on the Mac: touch the sensor there. |
| On a LAN VM (through ssh) | Commit with SSH signing (if you set it up there) | Touch ID on the Mac, once per commit. |

### Fallback: ed25519 keys with a passphrase in Keychain

| Where you are | What you want to do | What happens |
|---|---|---|
| This Mac | `ssh monitoring` | Nothing: Keychain gives the passphrase. |
| This Mac | `git pull` / `git push` / `git clone` with GitHub | Nothing. |
| This Mac | `scp` / `rsync` to a VM | Nothing. |
| This Mac | Open a VS Code Remote-SSH window, or reconnect after sleep | Nothing. |
| This Mac | Commit with SSH signing (if you set it up) | Nothing. |
| This Mac | First use after logging in or a reboot | Nothing. You type the passphrase only once, during setup. Open Terminal once: it puts the keys in the agent, which the VMs need. |
| On a LAN VM (through ssh) | `git pull` / `git push` | Nothing. |
| On a LAN VM (through ssh) | Commit with SSH signing (if you set it up there) | Nothing. |

Good to know:

- Touch ID proves that someone is at the Mac now. The fallback passphrase only protects the key files: once the keys are in the agent, nothing is asked, so anyone using your unlocked Mac, or a VM you are connected to, can use them.
- One SSH connection is one prompt. A `git pull` is one. A rebase that signs commits is one per commit.
- A VM's request is shown on the Mac, so you must be at the Mac.
- Secretive can leave a key unlocked for a set time, so later uses ask nothing until then.

When it doesn't work:

- The Mac is locked or asleep, or you are away: nobody answers Touch ID, and the command waits.
- `git` on a VM says `Permission denied (publickey)` (Option 1 and fallback): the GitHub key is not in the agent yet. Open Terminal on the Mac once, then try again.
- With Secretive, nothing works if SecretAgent is not running. Open Secretive to start it.

Tip: SSH connection sharing lets later connections to the same VM reuse the first one, without a new prompt. VS Code's Remote-SSH docs suggest these lines (add them to the `Host *.lan.text-analytics.ch` block, then run `mkdir -p ~/.ssh/sockets`): `ControlMaster auto`, `ControlPath ~/.ssh/sockets/%r@%h-%p`, `ControlPersist 600`. It does not change the prompts for GitHub from a VM.

Status of this section: not tested, no Mac was available. Touch ID at each use (Option 1) is not described in Apple documentation. Sources: https://github.com/maxgoedjen/secretive (README and release notes), https://developer.apple.com/library/archive/technotes/tn2449/_index.html, https://code.visualstudio.com/docs/remote/troubleshooting, https://man.openbsd.org/ssh_config.

## Before you start

```sh
ls -a ~/.ssh 2>/dev/null | grep -E '^id_(github|text_analytics_ch)'
which ssh
```

- Expected: only `/usr/bin/ssh`.
- If file names are listed, you already have these keys. Stop and ask for help: the steps below must not replace them.
- If `which` shows a Homebrew path, ask for help: these steps need Apple's `ssh`.

## Option 1: built-in Secure Enclave key (macOS 26)

The private keys stay in the Secure Enclave. The two files in `~/.ssh` are only handles that point to them.

```sh
sc_auth list-ctk-identities
```

Expected: no identity listed. If one is listed (for example from an earlier attempt), ask for help, because the download below would pick it up too.

**Create the GitHub key:**

```sh
mkdir -p ~/.ssh && chmod 700 ~/.ssh
sc_auth create-ctk-identity -l id_github -k p-256-ne -t bio
d=$(mktemp -d) && cd "$d" && ssh-keygen -w /usr/lib/ssh-keychain.dylib -K -N ""
mv -n id_ecdsa_sk_rk ~/.ssh/id_github && mv -n id_ecdsa_sk_rk.pub ~/.ssh/id_github.pub
```

- Touch ID prompt: touch the sensor.
- `Enter PIN for authenticator:` press **Enter**. There is no PIN.
- If Touch ID asks again during the download, touch the sensor.

**Create the server key:**

```sh
sc_auth create-ctk-identity -l id_text_analytics_ch -k p-256-ne -t bio
d=$(mktemp -d) && cd "$d" && ssh-keygen -w /usr/lib/ssh-keychain.dylib -K -N ""
```

The same prompts appear. The download now finds both keys. If it asks `id_ecdsa_sk_rk already exists. Overwrite (y/n)?`, type **y**. Then keep the key that is not the GitHub key:

```sh
for f in "$d"/*.pub; do
  if ! grep -qF "$(cut -d' ' -f2 ~/.ssh/id_github.pub)" "$f"; then
    mv -n "${f%.pub}" ~/.ssh/id_text_analytics_ch && mv -n "$f" ~/.ssh/id_text_analytics_ch.pub
  fi
done
ls ~/.ssh/id_text_analytics_ch.pub
```

Expected: the path of the file. If you see `No such file or directory`, run the server-key download again (the `d=$(mktemp -d) ...` line only) and answer **n** this time, then run this loop again.

The comment in these keys is set by the tool, not your email.

**Agent: Apple's built-in agent.** It starts by itself. It must hold the GitHub key so that GitHub works from the VMs. This adds both keys at each login:

```sh
cat >> ~/.zprofile <<'EOF'

export SSH_SK_PROVIDER=/usr/lib/ssh-keychain.dylib
/usr/bin/ssh-add -q ~/.ssh/id_github ~/.ssh/id_text_analytics_ch 2>/dev/null
EOF
```

**`~/.ssh/config` block:**

```
CanonicalizeHostname yes
CanonicalDomains lan.text-analytics.ch
CanonicalizeMaxDots 1

Host *.lan.text-analytics.ch
    AddKeysToAgent yes
    ForwardAgent yes
    SecurityKeyProvider /usr/lib/ssh-keychain.dylib
    IdentityFile "~/.ssh/id_text_analytics_ch"

Host github.com
    AddKeysToAgent yes
    SecurityKeyProvider /usr/lib/ssh-keychain.dylib
    IdentityFile "~/.ssh/id_github"
```

This is the team's block plus `SecurityKeyProvider`, which tells `ssh` that the key is in the Secure Enclave. Add it as shown in [Write ~/.ssh/config](#write-sshconfig). If the file does not exist yet:

```sh
test -e ~/.ssh/config && echo "~/.ssh/config exists: merge by hand" || cat > ~/.ssh/config <<'EOF'
CanonicalizeHostname yes
CanonicalDomains lan.text-analytics.ch
CanonicalizeMaxDots 1

Host *.lan.text-analytics.ch
    AddKeysToAgent yes
    ForwardAgent yes
    SecurityKeyProvider /usr/lib/ssh-keychain.dylib
    IdentityFile "~/.ssh/id_text_analytics_ch"

Host github.com
    AddKeysToAgent yes
    SecurityKeyProvider /usr/lib/ssh-keychain.dylib
    IdentityFile "~/.ssh/id_github"
EOF
```

Each use asks for Touch ID, also when a VM uses the GitHub key through the forwarded agent.

## Option 2: Secretive app

**Create the keys:**

```sh
brew install --cask secretive
open -a Secretive
```

- Follow the setup assistant. Accept when it offers to start "SecretAgent" at login.
- Click **+**, name the key `id_github`, tick **Require authentication**, then click **Create**.
- Do the same for a second key named `id_text_analytics_ch`.

For each key, Secretive shows a **Public Key Path**. Copy each path into the matching line, then run:

```sh
mkdir -p ~/.ssh && chmod 700 ~/.ssh
cp -n "<Public Key Path of id_github>" ~/.ssh/id_github.pub
cp -n "<Public Key Path of id_text_analytics_ch>" ~/.ssh/id_text_analytics_ch.pub
```

There are no private key files. The `.pub` files tell `ssh` which Secretive key to use for each host.

**Agent: Secretive's own agent.** It starts at login and holds both keys.

```sh
printf '\nexport SSH_AUTH_SOCK="%s"\n' "$HOME/Library/Containers/com.maxgoedjen.Secretive.SecretAgent/Data/socket.ssh" >> ~/.zshrc
```

**`~/.ssh/config` block:**

```
CanonicalizeHostname yes
CanonicalDomains lan.text-analytics.ch
CanonicalizeMaxDots 1

Host *.lan.text-analytics.ch
    ForwardAgent yes
    IdentityAgent "~/Library/Containers/com.maxgoedjen.Secretive.SecretAgent/Data/socket.ssh"
    IdentityFile "~/.ssh/id_text_analytics_ch.pub"

Host github.com
    IdentityAgent "~/Library/Containers/com.maxgoedjen.Secretive.SecretAgent/Data/socket.ssh"
    IdentityFile "~/.ssh/id_github.pub"
```

Changes from the team's block: `IdentityAgent` points to Secretive for apps that do not read `~/.zshrc`; `IdentityFile` names the `.pub` files; `AddKeysToAgent` is gone, because the keys are already in Secretive's agent. Add it as shown in [Write ~/.ssh/config](#write-sshconfig). If the file does not exist yet:

```sh
test -e ~/.ssh/config && echo "~/.ssh/config exists: merge by hand" || cat > ~/.ssh/config <<'EOF'
CanonicalizeHostname yes
CanonicalDomains lan.text-analytics.ch
CanonicalizeMaxDots 1

Host *.lan.text-analytics.ch
    ForwardAgent yes
    IdentityAgent "~/Library/Containers/com.maxgoedjen.Secretive.SecretAgent/Data/socket.ssh"
    IdentityFile "~/.ssh/id_text_analytics_ch.pub"

Host github.com
    IdentityAgent "~/Library/Containers/com.maxgoedjen.Secretive.SecretAgent/Data/socket.ssh"
    IdentityFile "~/.ssh/id_github.pub"
EOF
```

Open a new terminal. `ssh-add -L` shows two `ecdsa-sha2-nistp256 ...` lines.

## Fallback: ed25519 keys with a passphrase in Keychain

```sh
mkdir -p ~/.ssh && chmod 700 ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/id_github -C "john.doe@hesge.ch"
ssh-keygen -t ed25519 -f ~/.ssh/id_text_analytics_ch -C "john.doe@hesge.ch"
```

- `Enter passphrase` (asked twice per key): type a real passphrase both times.
- If you see `... already exists. Overwrite (y/n)?`, answer **n**.

**Agent: Apple's built-in agent.** It starts by itself.

```sh
/usr/bin/ssh-add --apple-use-keychain ~/.ssh/id_github ~/.ssh/id_text_analytics_ch
cat >> ~/.zprofile <<'EOF'

/usr/bin/ssh-add --apple-load-keychain -q
EOF
```

- `Enter passphrase`: type each key's passphrase once. Keychain remembers it.
- The `~/.zprofile` line puts both keys in the agent at each login, so GitHub works from the VMs before you use it on the Mac.

**`~/.ssh/config` block:** the team's block for macOS, unchanged:

```
CanonicalizeHostname yes
CanonicalDomains lan.text-analytics.ch
CanonicalizeMaxDots 1

Host *.lan.text-analytics.ch
    AddKeysToAgent yes
    ForwardAgent yes
    UseKeychain yes
    IdentityFile "~/.ssh/id_text_analytics_ch"

Host github.com
    AddKeysToAgent yes
    UseKeychain yes
    IdentityFile "~/.ssh/id_github"
```

`UseKeychain` works only with Apple's `/usr/bin/ssh`. Add the block as shown in [Write ~/.ssh/config](#write-sshconfig). If the file does not exist yet:

```sh
test -e ~/.ssh/config && echo "~/.ssh/config exists: merge by hand" || cat > ~/.ssh/config <<'EOF'
CanonicalizeHostname yes
CanonicalDomains lan.text-analytics.ch
CanonicalizeMaxDots 1

Host *.lan.text-analytics.ch
    AddKeysToAgent yes
    ForwardAgent yes
    UseKeychain yes
    IdentityFile "~/.ssh/id_text_analytics_ch"

Host github.com
    AddKeysToAgent yes
    UseKeychain yes
    IdentityFile "~/.ssh/id_github"
EOF
```

`ssh-add -l` shows two `256 SHA256:... john.doe@hesge.ch (ED25519)` lines.

## Write ~/.ssh/config

If the command above printed `~/.ssh/config exists: merge by hand`, open the file with `open -e ~/.ssh/config` and add your block by hand:

- Put the three `Canonical...` lines at the very top, above every `Host` line. Below a `Host` line they would apply to that host only.
- Paste the two `Host` blocks above any `Host *` block. For most settings, `ssh` uses the first value it finds.
- Delete old `github.com` or `*.lan.text-analytics.ch` blocks, and `IdentityFile`, `IdentityAgent` or `IdentitiesOnly` lines under `Host *` left from an earlier key setup.
- End the file with a line break.

Then check what `ssh` will use:

```sh
ssh -G github.com | grep -E '^(identityfile|identityagent|forwardagent) '
ssh -G monitoring.lan.text-analytics.ch | grep -E '^(identityfile|identityagent|forwardagent) '
```

Expected: the first shows `forwardagent no` and one `identityfile` line ending in `id_github` (or `id_github.pub`). The second shows `forwardagent yes` and one ending in `id_text_analytics_ch` (or `.pub`). With Secretive, both also show its `identityagent`.

Forwarding lets the VMs use your keys while you are connected. A stricter option is described in [the secrets and keys guide](../secrets-and-keys.md#servers).

## Publish the public keys

**GitHub** gets `id_github` only, for login and for signing:

```sh
gh ssh-key add ~/.ssh/id_github.pub --type authentication --title "$(scutil --get ComputerName) id_github"
gh ssh-key add ~/.ssh/id_github.pub --type signing --title "$(scutil --get ComputerName) id_github"
```

To sign commits, follow "GitHub and commit signing" in [the secrets and keys guide](../secrets-and-keys.md#ssh-keys) with `KEY` = `id_github`.

**Each VM** gets `id_text_analytics_ch`. Run this once per VM:

```sh
ssh-copy-id -i ~/.ssh/id_text_analytics_ch.pub <vm>
```

- With Secretive, add `-f` after `ssh-copy-id`, because there is no private key file.
- The first time, `ssh` shows the VM's fingerprint and asks `Are you sure you want to continue connecting`. Compare it with the fingerprint the team publishes for that VM, or ask the admin. Type **yes** only if they match.
- `password:` type your VM password. Expected: `Number of key(s) added: 1`.

## Check

```sh
ssh -o IdentitiesOnly=yes -T git@github.com
```

- The first time, compare the fingerprint with [GitHub's published fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints). Type **yes** only if it matches.
- Touch ID prompt (not with the fallback): touch the sensor.
- Expected: `Hi <you>! You've successfully authenticated, but GitHub does not provide shell access.` The exit code is 1; that is normal.

```sh
ssh -o IdentitiesOnly=yes -o PreferredAuthentications=publickey <vm> hostname
```

Expected: Touch ID (not with the fallback), then the VM's name. No password prompt.

```sh
ssh -t <vm> ssh -T git@github.com
```

This uses the GitHub key on the VM, through the forwarded agent. Check GitHub's fingerprint the first time, as above. Expected: Touch ID on the Mac (not with the fallback), then `Hi <you>! ...`.

A clone with an `https://` remote keeps using HTTPS. `git remote -v` shows which one a clone uses.

## Status

- **Built-in Secure Enclave key:** Not tested: no Mac was available. Based on community write-ups, not on Apple documentation: https://gist.github.com/arianvp/5f59f1783e3eaf1a2d4cd8e952bb4acf and https://ewpratten.com/blog/ssh-secure-enclave/. Two keys, the file names `ssh-keygen -K` writes for them, and loading them into Apple's agent for forwarding are not documented there; the steps above handle both possible download behaviors.
- **Secretive:** Not tested: no Mac was available. Based on https://github.com/maxgoedjen/secretive and its FAQ, which says agent forwarding works with `ForwardAgent yes`.
- **Fallback:** Not tested: no Mac was available. Based on https://developer.apple.com/library/archive/technotes/tn2449/_index.html.
