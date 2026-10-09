# SSH keys: Linux, nothing extra

First read the rules and install the GitHub CLI: see [the setup index](README.md).

**For:** users of Fedora 44, Ubuntu 24.04/26.04 or Debian 13 without a YubiKey or Bitwarden. **You need:** a TPM chip. Run `ls /dev/tpmrm0`. If it says `No such file or directory`, use the **fallback** at the end of this page.

You create two keys: `id_github` for GitHub and `id_text_analytics_ch` for our LAN servers (`*.lan.text-analytics.ch`, the VMs on Hulk). Both are created inside the TPM and cannot leave this computer.

## Day to day: what you are asked

| Where you are | What you want to do | What happens |
|---|---|---|
| This computer | First use of each key after logging in or a reboot | A small window asks `Enter passphrase for (john.doe@hesge.ch):`. Type the PIN. Once per key, until you log out. |
| This computer | `ssh monitoring` | Nothing, once the PIN was typed for `id_text_analytics_ch`. |
| This computer | `git pull` / `git push` / `git clone` with GitHub | Nothing, once the PIN was typed for `id_github`. |
| This computer | `scp` / `rsync` to a VM | Nothing. |
| This computer | Open a VS Code Remote-SSH window, or reconnect after sleep | Nothing. |
| This computer | Commit with SSH signing (if you set it up) | Nothing. |
| On a LAN VM (through ssh) | `git pull` / `git push` | Nothing. If you have not typed the PIN for `id_github` yet, the PIN window opens on this computer. |
| On a LAN VM (through ssh) | Commit with SSH signing (if you set it up there) | Nothing, same as above. |

**Fallback (no TPM):** the same, except that the question is `Enter passphrase for key '/home/you/.ssh/id_github':` in the terminal, once per key per login session. A VM cannot use `id_github` until you have used it once on this computer: before that, GitHub refuses the login from the VM.

Good to know:

- The PIN unlocks the key inside the TPM. The agent keeps it unlocked until you log out, so anyone using your open session, or root on a VM you are connected to, can use the keys without the PIN.
- Requests forwarded from a VM are answered on this computer. If a PIN window is needed, it opens here.

When it doesn't work:

- Wrong PIN: `agent refused operation`, then `Permission denied (publickey...)`. The TPM counts wrong PINs and locks the key for a while after too many, so do not guess.
- No PIN window and no key: check that the agent runs, as in the agent section below.

## Install (once)

Ubuntu 26.04:

```sh
sudo apt install ssh-tpm-agent tpm-udev ssh-askpass-gnome
```

Fedora 44, Debian 13 and Ubuntu 24.04 have no package, so install the official release. Run the first line for your distro, then the rest:

```sh
sudo dnf install openssh-askpass                  # Fedora
sudo apt install tpm-udev ssh-askpass-gnome       # Debian / Ubuntu 24.04
cd /tmp && curl -fsSLO https://github.com/Foxboron/ssh-tpm-agent/releases/download/v0.9.0/ssh-tpm-agent-v0.9.0-linux-amd64.tar.gz
tar xzf ssh-tpm-agent-v0.9.0-linux-amd64.tar.gz
mkdir -p ~/.local/bin && install -m 755 ssh-tpm-agent/ssh-tpm-* ~/.local/bin/
```

All distros:

```sh
sudo usermod -aG tss "$USER"
```

On Fedora, `dnf` asks `Is this ok [y/N]:`. Type **y**.

**Log out and back in** (or reboot). Afterwards, `id -nG` must list `tss`. The agent runs under your systemd user manager, which keeps the old groups while any session of yours is still open; if the agent later cannot open the TPM, reboot.

## Create the keys

Ubuntu 26.04 users: type `ssh-tpm-keygen` in place of `~/.local/bin/ssh-tpm-keygen`. Replace `john.doe@hesge.ch` with your email.

```sh
~/.local/bin/ssh-tpm-keygen -f ~/.ssh/id_github -C "john.doe@hesge.ch"
~/.local/bin/ssh-tpm-keygen -f ~/.ssh/id_text_analytics_ch -C "john.doe@hesge.ch"
```

Each command asks:

- `Enter passphrase (empty for no passphrase):` type a **PIN** of your choice. The TPM blocks repeated guessing, so a short PIN is fine. Use the same PIN for both keys: the PIN window shows only the comment, which is your email for both.
- `Enter same passphrase again:` type the PIN again.
- If you see `... already exists.` and `Overwrite (y/n)?`, answer **n** and ask for help.
- Done when you see `Your identification has been saved in /home/you/.ssh/id_github.tpm` (then `id_text_analytics_ch.tpm`).

Each key gets a `.tpm` file and a `.pub` file. There is no file without an extension.

## Agent (starts at login)

Ubuntu 26.04 users: type `ssh-tpm-agent` in place of `~/.local/bin/ssh-tpm-agent` on the first line. The service records where the program is, so do not move it afterwards.

```sh
~/.local/bin/ssh-tpm-agent --install-user-units
systemctl --user enable --now ssh-tpm-agent.socket
grep -q ssh-tpm-agent.sock ~/.bashrc || printf '\nexport SSH_AUTH_SOCK="$XDG_RUNTIME_DIR/ssh-tpm-agent.sock"\n' >> ~/.bashrc
```

- The first command prints `Installed .../ssh-tpm-agent.service`, `Installed .../ssh-tpm-agent.socket` and `Enable with: ...`.
- The agent loads every `~/.ssh/*.tpm` key when it starts, so it holds both keys.
- The `.bashrc` line lets `ssh-add` and Git commit signing find the agent. Open a new terminal afterwards.
- The first time you use each key after logging in, a small window asks `Enter passphrase for (john.doe@hesge.ch):`. Type the PIN. The agent remembers it until you log out.
- A wrong PIN is refused (`agent refused operation`, then `Permission denied (publickey...)`). The TPM counts wrong PINs and locks the key for a while after too many, so do not guess.

Run `ssh-add -l`. Expected: two lines `256 SHA256:... john.doe@hesge.ch (ECDSA)`. If it says `The agent has no identities.` right after you enabled the agent, wait a second and run it again.

## ~/.ssh/config

Make a backup first:

```sh
mkdir -p ~/.ssh && touch ~/.ssh/config && chmod 600 ~/.ssh/config && cp ~/.ssh/config ~/.ssh/config.bak
```

Open `~/.ssh/config` in a text editor (for example `nano ~/.ssh/config`). Paste this block at the **very top** of the file, followed by an empty line:

```
CanonicalizeHostname yes
CanonicalDomains lan.text-analytics.ch
CanonicalizeMaxDots 1

Host *.lan.text-analytics.ch
    AddKeysToAgent yes
    ForwardAgent yes
    IdentityAgent "${XDG_RUNTIME_DIR}/ssh-tpm-agent.sock"
    IdentityFile "~/.ssh/id_text_analytics_ch"

Host github.com
    AddKeysToAgent yes
    IdentityAgent "${XDG_RUNTIME_DIR}/ssh-tpm-agent.sock"
    IdentityFile "~/.ssh/id_github"
```

- This is the team's block with one change: the two `IdentityAgent` lines. They send these hosts to the TPM agent, even when your desktop starts another agent. Other hosts are not affected.
- `IdentityFile` names a file that does not exist. SSH then reads the `.pub` file next to it and asks the agent for the matching key. `AddKeysToAgent` has no effect here, because the agent already holds both keys.
- Put the block at the top. SSH uses the first value it finds for each setting, so the block must come before any `Host *` block. The three `Canonicalize` lines must come before the first `Host` line.
- If the file already has a `Host github.com` or `Host *.lan.text-analytics.ch` block, merge it into the new one and delete the old one. Also delete a `Host *` block with `IdentityAgent` left by an earlier version of this page. Keep everything else.
- `ForwardAgent yes` lets you use GitHub from the VMs with the keys on this computer. While you are connected, root on that VM can use your keys too, but cannot copy them. A stricter option is described in [Servers](../secrets-and-keys.md#servers).

Check the result. Replace `<vm>` with a VM name such as `monitoring`:

```sh
ssh -G <vm> | grep -E '^(hostname|identityagent|identityfile|forwardagent) '
```

Expected: `hostname <vm>.lan.text-analytics.ch`, `identityagent /run/user/1000/ssh-tpm-agent.sock`, `identityfile ~/.ssh/id_text_analytics_ch` and `forwardagent yes`. If another `identityagent` or `identityfile` line comes first, an older setting is still above the block.

## Publish the public keys

The first connection to each host shows `... key fingerprint is SHA256:...` and asks `Are you sure you want to continue connecting (yes/no/[fingerprint])?`. Compare the fingerprint first: for github.com with [GitHub's published fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints); for a VM, with the fingerprint the admin gives you. Type **yes** only if it matches. Otherwise type **no** and tell the admin.

GitHub gets only `id_github`, for login and for signing:

```sh
gh ssh-key add ~/.ssh/id_github.pub --type authentication --title "$(hostname) TPM"
gh ssh-key add ~/.ssh/id_github.pub --type signing --title "$(hostname) TPM"
```

Each VM gets `id_text_analytics_ch`. Run this once per VM:

```sh
ssh-copy-id -f -i ~/.ssh/id_text_analytics_ch.pub <vm>
```

- It asks for your VM password once (`...'s password:`) and replies `Number of key(s) added: 1`.
- `ssh-copy-id` needs `-f`. Without it, it stops with `ERROR: failed to open ID file '.../id_text_analytics_ch'`.
- If your login on the VMs differs from your login here, write `login@<vm>` here and in the commands below.

## Check

One command per key. `IdentitiesOnly=yes` makes SSH use only the configured key, so success proves that key works.

```sh
ssh -o IdentitiesOnly=yes -T git@github.com
```

Expected: `Hi <you>! You've successfully authenticated, but GitHub does not provide shell access.` The command then exits with status 1. That is normal.

```sh
ssh -o IdentitiesOnly=yes -o PreferredAuthentications=publickey <vm> hostname
```

Expected: the VM's name, with no password question.

Then check GitHub from a VM, through the forwarded agent. Log in with `ssh <vm>`, then run on the VM:

```sh
ssh -T git@github.com
```

Expected: the same `Hi <you>! ...` line. The PIN window, if it appears, opens on this computer.

- Repositories cloned with an `https://` URL keep using HTTPS. Check with `git remote -v`.
- If your GitHub organization uses SSO, open https://github.com/settings/keys and click **Configure SSO** next to the key.
- To sign commits with `id_github`, follow "GitHub and commit signing" in [SSH keys](../secrets-and-keys.md#ssh-keys), with `KEY` replaced by `id_github`. The two `gh ssh-key add` lines are already done.

**Status:** Tested on 2026-10-09 in a Fedora 44 VM with an emulated TPM (OpenSSH 10.2p1, ssh-tpm-agent v0.9.0), as a normal user, with one key at the default name `~/.ssh/id_ecdsa`:

- the install steps, the `tss` group and a new login;
- `ssh-tpm-keygen` with a PIN, and its questions;
- `--install-user-units` and the systemd socket: the agent starts by itself and loads the `.tpm` key;
- `ssh-add -l`, a login, a second login without the PIN, `ssh-keygen -Y sign`, and a wrong PIN being refused;
- `ssh-copy-id`: the error without `-f`, and `Number of key(s) added: 1` with it.

Also tested on 2026-10-09 with the same VM and two Debian 13 test servers (OpenSSH 10.0p2), one standing in for a LAN VM and one for GitHub:

- both keys created with `-f` and `-C`; the agent loaded both, and asked each key's PIN once, naming the key by its comment;
- login to the LAN stand-in with `id_text_analytics_ch` only; from there, through the forwarded agent, login to the GitHub stand-in with `id_github`, with no further PIN;
- `AddKeysToAgent yes`: no error, no extra prompt.

That test used `IdentityFile`, `ForwardAgent` and `AddKeysToAgent` as above, with `SSH_AUTH_SOCK` pointing at the TPM agent, but without the `IdentityAgent` and `Canonicalize` lines. Checked separately with OpenSSH 10.2p1, a local test server and a plain `ssh-agent`: an `IdentityFile` with only a `.pub` file next to it uses the agent's key, also with `IdentitiesOnly=yes`; `ForwardAgent yes` forwards the agent named by `IdentityAgent`.

Not tested: this exact `~/.ssh/config` block, real LAN VMs, the PIN window itself (the VM had no desktop, so a script answered the PIN prompt), GitHub, and Ubuntu or Debian with a TPM.

Based on https://github.com/Foxboron/ssh-tpm-agent.

## Fallback (no TPM): ed25519 keys with a passphrase

Replace `john.doe@hesge.ch` with your email.

```sh
ssh-keygen -t ed25519 -f ~/.ssh/id_github -C "john.doe@hesge.ch"
ssh-keygen -t ed25519 -f ~/.ssh/id_text_analytics_ch -C "john.doe@hesge.ch"
```

Each command asks:

- `Enter passphrase for "/home/you/.ssh/id_github" (empty for no passphrase):` type a real passphrase. This file *can* be copied, so the passphrase is its only protection.
- `Enter same passphrase again:` type it again.
- If you see `... already exists.` and `Overwrite (y/n)?`, answer **n** and ask for help.

**Agent:** desktop sessions usually start one. If `ssh-add -l` says `Could not open a connection to your authentication agent`:

- Fedora: run `systemctl --user enable --now ssh-agent.socket`, then add `export SSH_AUTH_SOCK="$XDG_RUNTIME_DIR/ssh-agent.socket"` on its own line at the end of `~/.bashrc` and open a new terminal.
- Other distros: run `eval "$(ssh-agent -s)"`. It prints `Agent pid N`. This works only in this terminal, until you close it.

**~/.ssh/config:** follow the section above, but paste the block **without** the two `IdentityAgent` lines. That is exactly the team's block. `AddKeysToAgent yes` loads each key into the agent the first time you use it.

The first use of each key asks `Enter passphrase for key '/home/you/.ssh/id_github':`. After that, there is no prompt until you log out. The agent gets `id_github` only after you use it once on this computer, so run `ssh -T git@github.com` here before you use GitHub from a VM.

**Publish and check:** same commands as above. `ssh-copy-id` does not need `-f` for these keys.

**Status:** Tested on 2026-10-09 on Fedora 44 and Ubuntu 24.04, in containers, logging in to `localhost`, with one key at the default name `~/.ssh/id_ed25519`:

- the key creation questions;
- `ssh-copy-id`;
- `ssh-agent` with `ssh-add`;
- `AddKeysToAgent`: the passphrase was asked once, and the next login had no prompt.

Not tested: the two keys with `-f`, this `~/.ssh/config` block, forwarding to a real VM, and the agent started by a real desktop session. Fedora ships `ssh-agent.socket`; Ubuntu 24.04 does not.
