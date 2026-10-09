# SSH keys: macOS + YubiKey

First read the rules and install the GitHub CLI: see [the setup index](README.md).

**For:** Mac users with a YubiKey 5 (firmware 5.2.3 or later). **You need:** [Homebrew](https://brew.sh), the YubiKey and its FIDO2 PIN. Apple's own `ssh` cannot use USB security keys, so you must use the one from Homebrew.

## Create the key

```sh
brew install openssh ykman
hash -r; which ssh ssh-keygen
```

- Expected: `/opt/homebrew/bin/ssh` (on Intel Macs, `/usr/local/bin/ssh`).
- If you see `/usr/bin/ssh`, add `eval "$(/opt/homebrew/bin/brew shellenv)"` to `~/.zprofile` and open a new terminal.
- If the YubiKey has no PIN yet, run `ykman fido access change-pin`.

```sh
ssh-keygen -t ed25519-sk -O resident -O verify-required -C "$(whoami)-yubikey"
```

- `Enter PIN for authenticator:` type the YubiKey PIN.
- `You may need to touch your authenticator`: touch the YubiKey when it blinks.
- `Enter file in which to save the key`: press **Enter**.
- `Enter passphrase` (asked twice): press **Enter** both times.

## SSH agent: not needed

Every connection asks for the PIN and a touch. Do not add this key to Apple's agent, because that agent cannot use security keys.

```sh
cat >> ~/.ssh/config <<'EOF'
Host *
    IdentityFile ~/.ssh/id_ed25519_sk
    IdentitiesOnly yes
EOF
```

## Check

```sh
ssh-keygen -Y sign -f ~/.ssh/id_ed25519_sk -n file ~/.ssh/id_ed25519_sk.pub
```

It asks for the PIN and a touch. Expected: `Write signature to .../id_ed25519_sk.pub.sig`.

## Publish the public key

```sh
gh ssh-key add ~/.ssh/id_ed25519_sk.pub --type authentication --title "YubiKey"
gh ssh-key add ~/.ssh/id_ed25519_sk.pub --type signing --title "YubiKey"
ssh-copy-id -i ~/.ssh/id_ed25519_sk.pub user@server
```

Then run `ssh -T git@github.com`. It asks for the PIN and a touch, then shows `Hi <you>! ...`.

**Status:** Not tested: no Mac was available. Based on https://developers.yubico.com/SSH/Securing_SSH_with_FIDO2.html and https://man.openbsd.org/ssh-keygen.
