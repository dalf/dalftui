# SSH keys: Linux, nothing extra

First read the rules and install the GitHub CLI: see [the setup index](README.md).

**For:** users of Fedora 44, Ubuntu 24.04/26.04 or Debian 13 without a YubiKey or Bitwarden. **You need:** a TPM chip. Run `ls /dev/tpmrm0`. If it says `No such file or directory`, use the **fallback** at the end of this page.

The key is created inside the TPM and cannot leave this computer.

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

**Log out and back in.** Afterwards, `id -nG` must list `tss`.

## Create the key

Ubuntu 26.04 users: type `ssh-tpm-keygen` in place of `~/.local/bin/ssh-tpm-keygen`.

```sh
~/.local/bin/ssh-tpm-keygen
```

- `Enter file in which to save the key (/home/you/.ssh/id_ecdsa):` press **Enter**.
- `Enter passphrase (empty for no passphrase):` type a **PIN** of your choice. The TPM blocks repeated guessing, so a short PIN is fine.
- `Enter same passphrase again:` type the PIN again.
- Done when you see `Your identification has been saved in /home/you/.ssh/id_ecdsa.tpm`.

## Agent (starts at login)

Ubuntu 26.04 users: type `ssh-tpm-agent` in place of `~/.local/bin/ssh-tpm-agent` on the first line. The service records where the program is, so do not move it afterwards.

```sh
~/.local/bin/ssh-tpm-agent --install-user-units
systemctl --user enable --now ssh-tpm-agent.socket
cat >> ~/.ssh/config <<'EOF'
Host *
    IdentityAgent ${XDG_RUNTIME_DIR}/ssh-tpm-agent.sock
EOF
chmod 600 ~/.ssh/config
echo 'export SSH_AUTH_SOCK="$XDG_RUNTIME_DIR/ssh-tpm-agent.sock"' >> ~/.bashrc
```

- The first command prints `Installed .../ssh-tpm-agent.service`, `Installed .../ssh-tpm-agent.socket` and `Enable with: ...`.
- Open a new terminal afterwards.
- The first time you use the key after logging in, a small window asks `Enter passphrase for (<key comment>):`. Type your PIN. The agent remembers it until you log out; it does not ask again for the next connections.
- A wrong PIN is refused (`agent refused operation`, then `Permission denied (publickey...)`). The TPM counts wrong PINs and locks the key for a while after too many, so do not guess.

## Check

Run `ssh-add -l`. Expected: `256 SHA256:... you@yourpc (ECDSA)`. If it says `The agent has no identities.` right after you enabled the agent, wait a second and run it again.

## Publish the public key

```sh
gh ssh-key add ~/.ssh/id_ecdsa.pub --type authentication --title "$(hostname) TPM"
gh ssh-key add ~/.ssh/id_ecdsa.pub --type signing --title "$(hostname) TPM"
ssh-copy-id -f -i ~/.ssh/id_ecdsa.pub user@server
```

- `ssh-copy-id` needs `-f`. Without it, it stops with `ERROR: failed to open ID file '.../id_ecdsa'`.
- Then run `ssh -T git@github.com`. Expected: `Hi <you>! ...`

**Status:** Tested on 2026-10-09 in a Fedora 44 VM with an emulated TPM (OpenSSH 10.2p1, ssh-tpm-agent v0.9.0), as a normal user, following this page:

- the install steps, the `tss` group and a new login;
- `ssh-tpm-keygen` with a PIN, and the questions shown above;
- `--install-user-units` and the systemd socket: the agent starts by itself and loads `~/.ssh/id_ecdsa.tpm`;
- `ssh-add -l`, a login, a second login without the PIN, `ssh-keygen -Y sign`, and a wrong PIN being refused;
- `ssh-copy-id`: the error without `-f`, and `Number of key(s) added: 1` with it.

Not tested: the PIN window itself (the VM had no desktop, so a script answered the PIN prompt), GitHub, and Ubuntu or Debian with a TPM.

Based on https://github.com/Foxboron/ssh-tpm-agent.

## Fallback (no TPM): ed25519 key with a passphrase

```sh
ssh-keygen -t ed25519 -C "$USER@$(hostname)"
```

- `Enter file in which to save the key (/home/you/.ssh/id_ed25519):` press **Enter**.
- `Enter passphrase ... (empty for no passphrase):` type a real passphrase. This file *can* be copied, so the passphrase is its only protection.
- `Enter same passphrase again:` type it again.

**Agent:** desktop sessions already start one. Tell SSH to load your key into it:

```sh
printf 'Host *\n    AddKeysToAgent yes\n    IdentityFile ~/.ssh/id_ed25519\n' >> ~/.ssh/config
chmod 600 ~/.ssh/config
```

The first `ssh` asks `Enter passphrase for key '/home/you/.ssh/id_ed25519':`. After that, there is no prompt until you log out.

If `ssh-add -l` says `Could not open a connection to your authentication agent`:

- Fedora: run `systemctl --user enable --now ssh-agent.socket`, then add `export SSH_AUTH_SOCK="$XDG_RUNTIME_DIR/ssh-agent.socket"` to `~/.bashrc` and open a new terminal.
- Other distros: run `eval "$(ssh-agent -s)"` in this terminal. It prints `Agent pid N`.

**Check:** after your first `ssh`, `ssh-add -l` shows `256 SHA256:... (ED25519)`.

**Publish:** use the commands above with `~/.ssh/id_ed25519.pub`, and drop the `-f` for this key. `ssh-copy-id` asks `user@server's password:` once and replies `Number of key(s) added: 1`.

**Status:** Tested on 2026-10-09 on Fedora 44 and Ubuntu 24.04, in containers, logging in to `localhost`:

- the key creation questions;
- `ssh-copy-id`;
- `ssh-agent` with `ssh-add`;
- `AddKeysToAgent`: the passphrase was asked once, and the next login had no prompt.

Not tested: the agent started by a real desktop session. Fedora ships `ssh-agent.socket`; Ubuntu 24.04 does not.
