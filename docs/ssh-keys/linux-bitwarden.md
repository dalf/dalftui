# SSH keys: Linux + Bitwarden

First read the rules and install the GitHub CLI: see [the setup index](README.md).

**For:** people who want their keys synced through their Bitwarden vault. **You need:** a Bitwarden account and the **desktop** app.

You create two keys: `id_github` for GitHub and `id_text_analytics_ch` for our LAN servers (`*.lan.text-analytics.ch`, the VMs on Hulk). Both stay in the vault. On disk you keep only their public keys, `~/.ssh/id_github.pub` and `~/.ssh/id_text_analytics_ch.pub`.

## Create the keys

Install the app:

- Fedora: `flatpak install flathub com.bitwarden.desktop`. Answer **y** to the install question. If it says the `flathub` remote is not found, first run `flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo`.
- Ubuntu: `sudo snap install bitwarden`
- Debian: install the `.deb` from bitwarden.com.

Log in, then do this twice, first with the name `id_github`, then with `id_text_analytics_ch`:

1. Click **New** > **SSH key**, type the name, then click **Save**. No questions are asked.
2. Copy the **Public key** field.
3. Run the line for that key, paste, press **Enter**, then press **Ctrl-D**.

```sh
mkdir -p ~/.ssh && cat > ~/.ssh/id_github.pub
```

```sh
cat > ~/.ssh/id_text_analytics_ch.pub
```

Bitwarden does not let you set the key comment, so the email does not appear in these keys.

## Configure the agent

In **Settings**:

- turn on **Enable SSH agent**;
- leave **Ask for authorization when using SSH agent** on;
- turn on **Start automatically on login**.

The agent holds both keys whenever the vault is unlocked.

So that `ssh-add` and Git commit signing find the agent, run **only the line** that matches how you installed Bitwarden, then open a new terminal:

```sh
grep -q bitwarden-ssh-agent ~/.bashrc || printf '\nexport SSH_AUTH_SOCK="$HOME/.bitwarden-ssh-agent.sock"\n' >> ~/.bashrc                                      # .deb or AppImage
grep -q bitwarden-ssh-agent ~/.bashrc || printf '\nexport SSH_AUTH_SOCK="$HOME/.var/app/com.bitwarden.desktop/data/.bitwarden-ssh-agent.sock"\n' >> ~/.bashrc  # Flatpak
grep -q bitwarden-ssh-agent ~/.bashrc || printf '\nexport SSH_AUTH_SOCK="$HOME/snap/bitwarden/current/.bitwarden-ssh-agent.sock"\n' >> ~/.bashrc               # Snap
```

With the vault unlocked, run `ssh-add -l`. Expected: two lines `256 SHA256:... (ED25519)`.

## ~/.ssh/config

Make a backup first:

```sh
touch ~/.ssh/config && chmod 600 ~/.ssh/config && cp ~/.ssh/config ~/.ssh/config.bak
```

Open `~/.ssh/config` in a text editor (for example `nano ~/.ssh/config`). Paste this block at the **very top** of the file, followed by an empty line:

```
CanonicalizeHostname yes
CanonicalDomains lan.text-analytics.ch
CanonicalizeMaxDots 1

Host *.lan.text-analytics.ch
    AddKeysToAgent yes
    ForwardAgent yes
    IdentityAgent "~/.bitwarden-ssh-agent.sock"
    IdentityFile "~/.ssh/id_text_analytics_ch"

Host github.com
    AddKeysToAgent yes
    IdentityAgent "~/.bitwarden-ssh-agent.sock"
    IdentityFile "~/.ssh/id_github"
```

- Flatpak: in both `IdentityAgent` lines, write `"~/.var/app/com.bitwarden.desktop/data/.bitwarden-ssh-agent.sock"`. Snap: write `"~/snap/bitwarden/current/.bitwarden-ssh-agent.sock"`.
- This is the team's block with one change: the two `IdentityAgent` lines. They send these hosts to Bitwarden, even when your desktop starts another agent. Other hosts are not affected.
- `IdentityFile` names a file that does not exist. SSH then reads the `.pub` file next to it and asks Bitwarden for the matching key. `AddKeysToAgent` has no effect here, because Bitwarden already holds both keys.
- Put the block at the top. SSH uses the first value it finds for each setting, so the block must come before any `Host *` block. The three `Canonicalize` lines must come before the first `Host` line.
- If the file already has a `Host github.com` or `Host *.lan.text-analytics.ch` block, merge it into the new one and delete the old one. Also delete a `Host *` block with `IdentityAgent` or `IdentityFile ~/.ssh/bitwarden.pub` left by an earlier version of this page. Keep everything else.
- `ForwardAgent yes` lets you use GitHub from the VMs with the keys in your vault. While you are connected, root on that VM can use your keys too, but cannot copy them. Bitwarden still asks you to authorize each use. A stricter option is described in [Servers](../secrets-and-keys.md#servers).

Check the result. Replace `<vm>` with a VM name such as `monitoring`:

```sh
ssh -G <vm> | grep -E '^(hostname|identityagent|identityfile|forwardagent) '
```

Expected: `hostname <vm>.lan.text-analytics.ch`, `identityagent /home/you/...bitwarden-ssh-agent.sock`, `identityfile ~/.ssh/id_text_analytics_ch` and `forwardagent yes`. If another `identityagent` or `identityfile` line comes first, an older setting is still above the block.

## Publish the public keys

The first connection to each host shows `... key fingerprint is SHA256:...` and asks `Are you sure you want to continue connecting (yes/no/[fingerprint])?`. Compare the fingerprint first: for github.com with [GitHub's published fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints); for a VM, with the fingerprint the admin gives you. Type **yes** only if it matches. Otherwise type **no** and tell the admin.

GitHub gets only `id_github`, for login and for signing:

```sh
gh ssh-key add ~/.ssh/id_github.pub --type authentication --title "bitwarden"
gh ssh-key add ~/.ssh/id_github.pub --type signing --title "bitwarden"
```

Each VM gets `id_text_analytics_ch`. Run this once per VM:

```sh
ssh-copy-id -f -i ~/.ssh/id_text_analytics_ch.pub <vm>
```

- It asks for your VM password once (`...'s password:`) and replies `Number of key(s) added: 1`.
- `ssh-copy-id` needs `-f`, because the private key is not on disk.
- If your login on the VMs differs from your login here, write `login@<vm>` here and in the commands below.

## Check

With the vault unlocked. Bitwarden shows a request for each use: click **Authorize**. `IdentitiesOnly=yes` makes SSH use only the configured key, so success proves that key works.

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

Expected: Bitwarden asks for authorization on this computer, then the same `Hi <you>! ...` line.

- Repositories cloned with an `https://` URL keep using HTTPS. Check with `git remote -v`.
- If your GitHub organization uses SSO, open https://github.com/settings/keys and click **Configure SSO** next to the key.
- To sign commits with `id_github`, follow "GitHub and commit signing" in [SSH keys](../secrets-and-keys.md#ssh-keys), with `KEY` replaced by `id_github`. The two `gh ssh-key add` lines are already done.

**Status:** Not tested with Bitwarden: this needs a Bitwarden account and a desktop session. Bitwarden documents agent forwarding. Checked on 2026-10-09 with OpenSSH 10.2p1, a local test server and a plain `ssh-agent`: an `IdentityFile` with only a `.pub` file next to it uses the agent's key, also with `IdentitiesOnly=yes`; `ForwardAgent yes` forwards the agent named by `IdentityAgent`. Based on https://bitwarden.com/help/ssh-agent/ and https://bitwarden.com/help/app-settings/.
