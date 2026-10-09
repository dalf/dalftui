# SSH keys: Linux + Bitwarden

First read the rules and install the GitHub CLI: see [the setup index](README.md).

**For:** people who want one key synced through their Bitwarden vault. **You need:** a Bitwarden account and the **desktop** app.

## Create the key

Install the app:

- Fedora: `flatpak install flathub com.bitwarden.desktop`. Answer **y** to the install question. If it says the `flathub` remote is not found, first run `flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo`.
- Ubuntu: `sudo snap install bitwarden`
- Debian: install the `.deb` from bitwarden.com.

Log in, then:

1. Click **New** > **SSH key**, give it a name, then click **Save**. No questions are asked.
2. Copy the **Public key** field.
3. Run the line below, paste, press **Enter**, then press **Ctrl-D**.

```sh
mkdir -p ~/.ssh && cat > ~/.ssh/bitwarden.pub
```

## Configure the agent

In **Settings**:

- turn on **Enable SSH agent**;
- leave **Ask for authorization when using SSH agent** on;
- turn on **Start automatically on login**.

Then run **only the line** that matches how you installed Bitwarden:

```sh
S=~/.bitwarden-ssh-agent.sock                                       # .deb or AppImage
S=~/.var/app/com.bitwarden.desktop/data/.bitwarden-ssh-agent.sock   # Flatpak
S=~/snap/bitwarden/current/.bitwarden-ssh-agent.sock                # Snap
```

Then, in the same terminal:

```sh
cat >> ~/.ssh/config <<EOF
Host *
    IdentityAgent $S
    IdentityFile ~/.ssh/bitwarden.pub
    IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config
echo "export SSH_AUTH_SOCK=$S" >> ~/.bashrc
```

## Check

With the vault unlocked, open a new terminal and run `ssh-add -l`. Expected: `256 SHA256:... (ED25519)`.

## Publish the public key

```sh
gh ssh-key add ~/.ssh/bitwarden.pub --type authentication --title "bitwarden"
gh ssh-key add ~/.ssh/bitwarden.pub --type signing --title "bitwarden"
ssh-copy-id -f -i ~/.ssh/bitwarden.pub user@server
```

Then run `ssh -T git@github.com`. Bitwarden shows a request: click **Authorize**. Expected: `Hi <you>! ...`.

**Status:** Not tested: this needs a Bitwarden account and a desktop session. Based on https://bitwarden.com/help/ssh-agent/ and https://bitwarden.com/help/app-settings/.
