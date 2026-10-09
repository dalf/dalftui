# SSH keys: macOS, nothing extra

First read the rules and install the GitHub CLI: see [the setup index](README.md).

**For:** Mac users without a YubiKey or Bitwarden. **You need:**

- a Mac with Touch ID, or Apple Silicon or a T2 chip;
- macOS 26 for option 4a;
- [Homebrew](https://brew.sh) for option 4b.

Use option 4c on older Macs.

## Built-in Secure Enclave key (macOS 26)

**Create the key:**

```sh
sc_auth create-ctk-identity -l ssh -k p-256-ne -t bio
mkdir -p ~/.ssh && cd ~/.ssh && ssh-keygen -w /usr/lib/ssh-keychain.dylib -K -N ""
```

- Touch ID prompt: touch the sensor.
- `Enter PIN for authenticator:` press **Enter**. There is no PIN.
- This writes `id_ecdsa_sk_rk` (a pointer to the key, not the secret) and `id_ecdsa_sk_rk.pub`.

**Agent: not needed.** SSH asks the Secure Enclave directly.

```sh
echo 'export SSH_SK_PROVIDER=/usr/lib/ssh-keychain.dylib' >> ~/.zprofile
cat >> ~/.ssh/config <<'EOF'
Host *
    SecurityKeyProvider /usr/lib/ssh-keychain.dylib
    IdentityFile ~/.ssh/id_ecdsa_sk_rk
EOF
```

**Check:**

```sh
ssh-keygen -Y sign -w /usr/lib/ssh-keychain.dylib -f ~/.ssh/id_ecdsa_sk_rk -n file ~/.ssh/id_ecdsa_sk_rk.pub
```

It asks for Touch ID. Expected: `Write signature to .../id_ecdsa_sk_rk.pub.sig`.

**Publish:**

```sh
gh ssh-key add ~/.ssh/id_ecdsa_sk_rk.pub --type authentication --title "$(scutil --get ComputerName) SE"
gh ssh-key add ~/.ssh/id_ecdsa_sk_rk.pub --type signing --title "$(scutil --get ComputerName) SE"
ssh-copy-id -i ~/.ssh/id_ecdsa_sk_rk.pub user@server
```

Then run `ssh -T git@github.com`. It asks for Touch ID, then shows `Hi <you>! ...`.

**Status:** Not tested: no Mac was available. Based on community write-ups, not on Apple documentation: https://gist.github.com/arianvp/5f59f1783e3eaf1a2d4cd8e952bb4acf and https://ewpratten.com/blog/ssh-secure-enclave/.

## Secretive app

**Create the key:**

```sh
brew install --cask secretive
open -a Secretive
```

- Follow the setup assistant. Accept when it offers to start "SecretAgent" at login.
- Click **+**, give the key a name, tick **Require authentication**, then click **Create**.

**Agent: Secretive's own agent.** It starts at login.

```sh
mkdir -p ~/.ssh
cat >> ~/.ssh/config <<'EOF'
Host *
    IdentityAgent ~/Library/Containers/com.maxgoedjen.Secretive.SecretAgent/Data/socket.ssh
EOF
echo 'export SSH_AUTH_SOCK=~/Library/Containers/com.maxgoedjen.Secretive.SecretAgent/Data/socket.ssh' >> ~/.zshrc
```

**Check:** open a new terminal and run `ssh-add -L`. It shows one `ecdsa-sha2-nistp256 ...` line.

**Publish:** in Secretive, copy the **Public Key Path**. Use it in place of `<path>`:

```sh
gh ssh-key add <path> --type authentication --title "$(scutil --get ComputerName) Secretive"
gh ssh-key add <path> --type signing --title "$(scutil --get ComputerName) Secretive"
ssh-copy-id -f -i <path> user@server
```

`ssh-copy-id` needs `-f` because there is no private key file on disk.

**Status:** Not tested: no Mac was available. Based on https://github.com/maxgoedjen/secretive and its FAQ.

## Fallback: ed25519 key with a passphrase in Keychain

```sh
ssh-keygen -t ed25519 -C "$(whoami)@$(scutil --get LocalHostName)"
```

- `Enter file in which to save the key`: press **Enter**.
- `Enter passphrase` (asked twice): type a real passphrase both times.

**Agent: Apple's built-in agent.** It starts by itself.

```sh
cat >> ~/.ssh/config <<'EOF'
Host *
    UseKeychain yes
    AddKeysToAgent yes
    IdentityFile ~/.ssh/id_ed25519
EOF
ssh-add --apple-use-keychain ~/.ssh/id_ed25519
```

- `Enter passphrase`: type it once. Keychain remembers it after that.

**Check:** `ssh-add -l` shows `256 SHA256:... (ED25519)`.

**Publish:** use the 4a commands with `~/.ssh/id_ed25519.pub`.

**Status:** Not tested: no Mac was available. Based on https://developer.apple.com/library/archive/technotes/tn2449/_index.html.
