# SSH keys: Linux + YubiKey

First read the rules and install the GitHub CLI: see [the setup index](README.md).

**For:** people with a YubiKey 5 (firmware 5.2.3 or later). **You need:** OpenSSH 8.4 or later. All the distros listed here have it. No udev rules are needed.

## Create the key

Set a FIDO2 PIN once per YubiKey:

```sh
sudo dnf install yubikey-manager      # Ubuntu/Debian: sudo apt install yubikey-manager
ykman fido info
```

If it shows `PIN: Not set`, run `ykman fido access change-pin` and type your new PIN at both prompts. Then:

```sh
ssh-keygen -t ed25519-sk -O resident -O verify-required -C "$USER YubiKey"
```

- `Enter PIN for authenticator:` type the FIDO2 PIN.
- `You may need to touch your authenticator again...`: touch the YubiKey.
- `Enter file in which to save the key (/home/you/.ssh/id_ed25519_sk):` press **Enter**.
- `Enter passphrase` (asked twice): press **Enter** both times.
- If you see `... already exists. Overwrite key in token (y/n)?`, answer **n** and ask for help.

**On another computer:**

```sh
mkdir -p ~/.ssh && cd ~/.ssh && ssh-keygen -K
mv id_ed25519_sk_rk id_ed25519_sk && mv id_ed25519_sk_rk.pub id_ed25519_sk.pub
```

It asks for the PIN and a touch. Press **Enter** at both passphrase prompts.

## SSH agent: not needed

The PIN and a touch are needed every time.

```sh
cat >> ~/.ssh/config <<'EOF'
Host *
    IdentityFile ~/.ssh/id_ed25519_sk
    IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config
```

## Check

```sh
ssh-keygen -Y sign -f ~/.ssh/id_ed25519_sk -n file ~/.ssh/id_ed25519_sk.pub
```

Expected: a PIN prompt, a touch request, then `Write signature to /home/you/.ssh/id_ed25519_sk.pub.sig`.

## Publish the public key

```sh
gh ssh-key add ~/.ssh/id_ed25519_sk.pub --type authentication --title "YubiKey"
gh ssh-key add ~/.ssh/id_ed25519_sk.pub --type signing --title "YubiKey"
ssh-copy-id -i ~/.ssh/id_ed25519_sk.pub user@server
```

Then run `ssh -T git@github.com`. You should see:

1. `Enter PIN for ED25519-SK key ...`: type the PIN.
2. `Confirm user presence...`: touch the YubiKey.
3. `Hi <you>! ...`

The server needs OpenSSH 8.2 or later.

**Status:** Not tested end to end, because creating the key needs the owner's PIN and a touch. On a Fedora 44 desktop on 2026-10-09, the YubiKey 5 (firmware 5.7.1) was detected for the normal user without extra udev rules. The prompts come from the OpenSSH 10.2 source. Based on https://developers.yubico.com/SSH/Securing_SSH_with_FIDO2.html.
