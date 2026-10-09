# SSH keys: macOS + Bitwarden

First read the rules and install the GitHub CLI: see [the setup index](README.md).

**For:** Mac users who want one key synced through their Bitwarden vault. **You need:** the Bitwarden desktop app (from the App Store, or the .dmg from bitwarden.com) and a logged-in account.

## Create the key

1. In Bitwarden, click **New** > **SSH key**, give it a name, then click **Save**. Bitwarden creates an Ed25519 key and asks no questions.
2. Open the item and click copy on **Public key**.

Then run:

```sh
mkdir -p ~/.ssh && pbpaste > ~/.ssh/bitwarden.pub
```

## Configure the agent

- In Bitwarden **Settings**, tick **Enable SSH agent**.
- To start Bitwarden at login: System Settings > General > Login Items > **+** > Bitwarden.

Run **only one** of the next two blocks: the first for the .dmg version, the second for the App Store version.

```sh
# .dmg version
S=~/.bitwarden-ssh-agent.sock
```

```sh
# App Store version
S=~/Library/Containers/com.bitwarden.desktop/Data/.bitwarden-ssh-agent.sock
```

Then, in the same terminal:

```sh
cat >> ~/.ssh/config <<EOF
Host *
    IdentityAgent $S
    IdentityFile ~/.ssh/bitwarden.pub
    IdentitiesOnly yes
EOF
echo "export SSH_AUTH_SOCK=$S" >> ~/.zshrc
```

## Check

With the vault unlocked, open a new terminal and run `ssh-add -L`. Expected: `ssh-ed25519 AAAA...`.

## Publish the public key

```sh
gh ssh-key add ~/.ssh/bitwarden.pub --type authentication --title "bitwarden"
gh ssh-key add ~/.ssh/bitwarden.pub --type signing --title "bitwarden"
ssh-copy-id -f -i ~/.ssh/bitwarden.pub user@server
```

- `ssh-copy-id` needs `-f` because there is no private key file on disk.
- Then run `ssh -T git@github.com`. When Bitwarden asks, click **Authorize**. Expected: `Hi <you>! ...`

**Status:** Not tested: no Mac was available. Based on https://bitwarden.com/help/ssh-agent/.
