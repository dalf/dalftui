# SSH keys: Linux + YubiKey

First read the rules and install the GitHub CLI: see [the setup index](README.md).

**For:** people with a YubiKey 5 (firmware 5.2.3 or later). **You need:** OpenSSH 8.4 or later. All the distros listed here have it. No udev rules are needed.

You create two keys on the YubiKey: `id_github` for GitHub and `id_text_analytics_ch` for our LAN servers (`*.lan.text-analytics.ch`, the VMs on Hulk). The files `~/.ssh/id_github` and `~/.ssh/id_text_analytics_ch` are only handles: they are useless without the YubiKey.

## Create the keys

Set a FIDO2 PIN once per YubiKey:

```sh
sudo dnf install yubikey-manager openssh-askpass      # Ubuntu/Debian: sudo apt install yubikey-manager ssh-askpass-gnome
ykman fido info
```

If it shows `PIN: Not set`, run `ykman fido access change-pin` and type your new PIN at both prompts. Then, replacing `john.doe@hesge.ch` with your email:

```sh
ssh-keygen -t ed25519-sk -O resident -O verify-required -O application=ssh:github -f ~/.ssh/id_github -C "john.doe@hesge.ch"
ssh-keygen -t ed25519-sk -O resident -O verify-required -O application=ssh:text_analytics_ch -f ~/.ssh/id_text_analytics_ch -C "john.doe@hesge.ch"
```

The two `application=` names keep the two keys apart on the YubiKey. Each command asks:

- `You may need to touch your authenticator to authorize key generation.`, then `Enter PIN for authenticator:` type the FIDO2 PIN.
- `You may need to touch your authenticator again to authorize key generation.`: touch the YubiKey.
- `Enter passphrase for "/home/you/.ssh/id_github" (empty for no passphrase):` and `Enter same passphrase again:` press **Enter** both times.
- If you see `A resident key scoped to 'ssh:github' ... already exists. Overwrite key in token (y/n)?` or `... already exists. Overwrite (y/n)?`, answer **n** and ask for help.

**On another computer:** download the handles into a new empty folder, then move them only where no file exists yet:

```sh
mkdir -p ~/.ssh && d=$(mktemp -d) && cd "$d" && ssh-keygen -K && ls
```

- It asks for the PIN and a touch, then `Enter passphrase ...` twice: press **Enter** both times.
- Expected: `Saved ED25519-SK key ssh:github to id_ed25519_sk_rk_github`, the same for `ssh:text_analytics_ch`, and `ls` lists those files and their `.pub` files. Other keys on the YubiKey give other names; leave them.

```sh
for k in github text_analytics_ch; do
  if [ -e ~/.ssh/id_$k ] || [ -e ~/.ssh/id_$k.pub ]; then
    echo "~/.ssh/id_$k already exists: not replaced. Ask for help."
  else
    mv "id_ed25519_sk_rk_$k" ~/.ssh/id_$k && mv "id_ed25519_sk_rk_$k.pub" ~/.ssh/id_$k.pub
  fi
done
```

## Agent

`AddKeysToAgent yes` in the next section puts each handle into your desktop's SSH agent the first time you use it. That is what lets you use GitHub from the VMs. The private key stays on the YubiKey: each use, also from a VM, still needs a touch, and the agent asks for the PIN in a small window on this computer.

The agent gets `id_github` only after you use it once on this computer, so run `ssh -T git@github.com` here before you use GitHub from a VM.

If SSH fails with `agent refused operation`, your agent cannot handle the YubiKey or cannot show the PIN window. Run `ssh-add -d ~/.ssh/id_github ~/.ssh/id_text_analytics_ch` and delete the `AddKeysToAgent yes` lines. Then the YubiKey works on this computer (PIN and touch each time), but GitHub from the VMs does not.

## ~/.ssh/config

Make a backup first:

```sh
touch ~/.ssh/config && chmod 600 ~/.ssh/config && cp ~/.ssh/config ~/.ssh/config.bak
```

Open `~/.ssh/config` in a text editor (for example `nano ~/.ssh/config`). Paste this block at the **very top** of the file, followed by an empty line. It is the team's block, unchanged:

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

- Put the block at the top. SSH uses the first value it finds for each setting, so the block must come before any `Host *` block. The three `Canonicalize` lines must come before the first `Host` line.
- If the file already has a `Host github.com` or `Host *.lan.text-analytics.ch` block, merge it into the new one and delete the old one. Also delete a `Host *` block with `IdentityFile ~/.ssh/id_ed25519_sk` left by an earlier version of this page. Keep everything else.
- `ForwardAgent yes` lets you use GitHub from the VMs. While you are connected, root on that VM can ask your agent to use your keys, but each use still needs your touch. A stricter option is described in [Servers](../secrets-and-keys.md#servers).

Check the result. Replace `<vm>` with a VM name such as `monitoring`:

```sh
ssh -G <vm> | grep -E '^(hostname|identityfile|forwardagent) '
```

Expected: `hostname <vm>.lan.text-analytics.ch`, `identityfile ~/.ssh/id_text_analytics_ch` and `forwardagent yes`. If another `identityfile` line comes first, an older setting is still above the block.

## Publish the public keys

The first connection to each host shows `... key fingerprint is SHA256:...` and asks `Are you sure you want to continue connecting (yes/no/[fingerprint])?`. Compare the fingerprint first: for github.com with [GitHub's published fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints); for a VM, with the fingerprint the admin gives you. Type **yes** only if it matches. Otherwise type **no** and tell the admin.

GitHub gets only `id_github`, for login and for signing:

```sh
gh ssh-key add ~/.ssh/id_github.pub --type authentication --title "YubiKey"
gh ssh-key add ~/.ssh/id_github.pub --type signing --title "YubiKey"
```

Each VM gets `id_text_analytics_ch`. Run this once per VM:

```sh
ssh-copy-id -i ~/.ssh/id_text_analytics_ch.pub <vm>
```

- It asks for your VM password once (`...'s password:`) and replies `Number of key(s) added: 1`.
- The VM needs OpenSSH 8.2 or later.
- If your login on the VMs differs from your login here, write `login@<vm>` here and in the commands below.

## Check

One command per key. `IdentitiesOnly=yes` makes SSH use only the configured key, so success proves that key works.

```sh
ssh -o IdentitiesOnly=yes -T git@github.com
```

You should see:

1. `Enter PIN for ED25519-SK key ...` (in the terminal, or in a window if the agent already holds the key): type the PIN.
2. `Confirm user presence...`: touch the YubiKey.
3. `Hi <you>! You've successfully authenticated, but GitHub does not provide shell access.` The command then exits with status 1. That is normal.

```sh
ssh -o IdentitiesOnly=yes -o PreferredAuthentications=publickey <vm> hostname
```

Expected: the PIN, a touch, then the VM's name, with no password question.

Then check GitHub from a VM, through the forwarded agent. Log in with `ssh <vm>`, then run on the VM:

```sh
ssh -T git@github.com
```

Expected: the PIN window on this computer, a touch, then the same `Hi <you>! ...` line.

- Repositories cloned with an `https://` URL keep using HTTPS. Check with `git remote -v`.
- If your GitHub organization uses SSO, open https://github.com/settings/keys and click **Configure SSO** next to the key.
- To sign commits with `id_github`, follow "GitHub and commit signing" in [SSH keys](../secrets-and-keys.md#ssh-keys), with `KEY` replaced by `id_github`. The two `gh ssh-key add` lines are already done.

**Status:** Not tested end to end, because creating the keys needs the owner's PIN and a touch. On a Fedora 44 desktop on 2026-10-09, the YubiKey 5 (firmware 5.7.1) was detected for the normal user without extra udev rules. The prompts and the `id_ed25519_sk_rk_<name>` file names come from the OpenSSH 10.2 source; OpenSSH's own `ssh-agent` can sign with these keys for forwarded connections and asks for the PIN through its askpass window. Not tested: the agent your desktop starts (GNOME starts its own) with a YubiKey key, and forwarding to a real VM. Based on https://developers.yubico.com/SSH/Securing_SSH_with_FIDO2.html.
