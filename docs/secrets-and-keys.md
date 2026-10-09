# Secrets & keys guide

Oct 8, 2026 · @Alex

Every secret has one home: your hardware for proving who you are, Bitwarden for what must be remembered or shared, and the machine itself only for keys made for that machine. A lost laptop then means revoking its keys, never restoring files.

## The rule

Ask of every secret: does it prove who I am, must it be remembered, or does one machine need it to work alone? Each answer has exactly one home.

| Kind of secret | Home | Examples |
| --- | --- | --- |
| Proves it is you, right now | Hardware you carry: the laptop's secure chip (Touch ID, Windows Hello, TPM) or a YubiKey | SSH login keys, git commit signing, passkeys |
| Must be remembered, recovered or shared | Bitwarden | Passwords, 2FA recovery codes, admin and root credentials, shared team secrets |
| One machine needs it to work alone | That machine only: made for it, narrow, revocable | GitHub CLI login, one S3 key per laptop or server |

Three consequences:

- No private key file is ever copied between machines, sent in chat or stored in Bitwarden "just in case".
- A secret on a machine must be replaceable by logging in again or by issuing a new key.
- Nobody shares a personal credential; a shared secret lives in the team's Bitwarden collection.

## Bitwarden

Bitwarden holds what you must **remember** (one master password) and what the team must **share** (service passwords). It does not hold SSH keys or S3 keys meant for one machine.

### What each member sets up (free individual account)

| Step | What to do |
| --- | --- |
| 1. Master password | A passphrase of several random words, at least 12 characters (Bitwarden's minimum). Bitwarden **cannot recover or reset it**. Write it on paper and keep it at home until you know it by heart. |
| 2. Two-step login | Free: FIDO2/passkey, authenticator app, email. Duo and YubiKey OTP need Premium. |
| 3. Recovery code | Web app: **Settings → Security → Two-step login → View recovery code**. Print it or keep it on paper, **outside** Bitwarden. Using it turns off all two-step methods and creates a new code. |
| 4. Unlock with your laptop | Desktop app, **Settings → Security** (macOS: **Bitwarden → Settings**; Windows/Linux: **File → Settings**): turn on **Touch ID**, **Windows Hello** or system authentication (Linux, through polkit). Then in the browser extension: **Settings → Account security → Unlock with biometrics**. |

**Which two-step method on which laptop:**

- **Windows 11:** add Windows Hello as a FIDO2 key (free). Add an authenticator app as a second method.
- **macOS:** Bitwarden says: "On macOS, non-security keys like TouchID are not currently supported." Use an **authenticator app** on your phone.
- **Linux:** use an authenticator app.
- YubiKey owner: register the YubiKey as FIDO2, plus an authenticator app as backup.
- Free accounts can register up to 5 FIDO2 keys.

**Log in with a passkey (optional):** works in the web app and in the extension for Chromium browsers (on Linux, pop out the extension first). Up to 5 passkeys. A passkey login **skips two-step login**. It unlocks the vault only when browser and authenticator both support PRF; otherwise you still need another unlock method. On macOS, PRF passkeys in the web app need a Chromium browser. Windows Hello cannot use one passkey for both login and two-step login.

**Install notes:**

- Windows: install the desktop app from bitwarden.com/download. The Microsoft Store build has **no** Windows Hello unlock.
- Linux: use the Flatpak or Snap build; both support biometrics.
- Browser biometrics need the desktop app running, logged in, with biometrics already on. Some browsers also need "Allow access to file URLs" in the extension settings.

### Team side

| Plan | Price | Fits 5-10 people? |
| --- | --- | --- |
| Free organization | $0 | **No**: 2 users, 2 collections |
| Teams | $4/user/month, billed annually (about $240-480 a year) | **Yes**: unlimited users and collections, groups, event logs, Premium features for members |
| Enterprise | $6/user/month, billed annually | Not needed |

- **Discount:** pricing pages list none. A Bitwarden blog says sales handles pricing for "nonprofits/educational institutions". Ask sales before buying.
- **Collections** (suggested): `Infrastructure` (MinIO root user, server console/IPMI, DNS registrar; admins only) and `Shared services` (team accounts for shared web services; all members). Do **not** put personal S3 keys, SSH private keys or GitHub tokens there.
- **Emergency access** comes with Teams. Each member names a trusted contact, picks **View** or **Takeover** and sets a wait time. Takeover replaces the master password and removes two-step login.
- Bitwarden suggests a second **Owner**; have at least two, so the team never depends on one person.

### Sending a secret to someone: Bitwarden Send

Never paste a password or key into email, chat or a ticket: it stays there forever. Send it as a Bitwarden **Send** instead, an encrypted link that deletes itself. The recipient needs no Bitwarden account.

1. In the web app, desktop app or browser extension, open **Send → New**.
2. Choose **Text** (any account, up to 1,000 characters) or **File** (needs Premium or a paid organization such as Teams; up to 500 MB).
3. Give it a name, paste the secret, and set:
   - **Deletion date**: 1 day is enough (default 7, maximum 30).
   - **Maximum views**: 1 or 2.
   - **Password**, or **Specific people** (the recipient confirms their email).
   - **Hide text by default**.
4. Save, copy the link, and send it. Give the password through **another channel**, for example by phone or in person.

The recipient then stores the secret in its proper home (their own vault, the team collection, or the machine it is for); the link expires on its own. From a terminal: `bw send -n "MinIO key" -d 1 "…"`. Sources: [Bitwarden: Create a Send](https://bitwarden.com/help/create-send/).

## SSH keys

Rule: **one key per laptop, created in the laptop's own hardware**. Never copy key files between machines. Add each laptop's *public* key to GitHub and the servers. If you lose a laptop, delete its key everywhere. Step-by-step procedures for each setup (Windows, macOS, Linux; with or without Bitwarden or a YubiKey): [ssh-keys/](ssh-keys/README.md).

| OS | Option | Key leaves device? | Per-use prompt | Synced? |
| --- | --- | --- | --- | --- |
| macOS 26 | **Built-in Secure Enclave key** (recommended) | No | Touch ID | No |
| macOS 15+ | Secretive app (Secure Enclave) | No | Touch ID (optional) | No |
| Windows 11 | **Windows Hello `ecdsa-sk`** (recommended) | No, stays in the TPM | Hello (PIN) | No |
| Windows 11 | Bitwarden SSH agent (fallback) | Yes, encrypted in the vault | Configurable | Yes |
| Linux | **ssh-tpm-agent** (recommended) | No | PIN (optional) | No |
| Any | `ed25519` file with passphrase | Yes, the file can be copied | Passphrase at load | No |
| YubiKey | `ed25519-sk` resident key | No | Touch (+PIN) | You carry it |

**macOS 26 Tahoe**: Apple's ssh can use the Secure Enclave. Apple does not document this yet, so try it on one Mac before rolling it out:

```sh
sc_auth create-ctk-identity -l ssh -k p-256-ne -t bio   # press Touch ID
cd ~/.ssh && ssh-keygen -w /usr/lib/ssh-keychain.dylib -K -N ""
echo 'export SSH_SK_PROVIDER=/usr/lib/ssh-keychain.dylib' >> ~/.zshrc
```

Only `p-256-ne` works. The written file is a reference to the key, not the secret. On Sequoia, or if you prefer an app: `brew install --cask secretive` (v4.0, needs macOS 15+), then follow its setup screen. Apple's ssh does not support USB FIDO keys, so a YubiKey user needs `brew install openssh`.

**Windows 11**: Use a Windows Hello key. The private key stays in the TPM; the file `~/.ssh/id_ecdsa_sk_hello` is only a handle, not the secret. Windows' built-in OpenSSH (9.5) cannot create this key (a bug open since 2023), so create it once with OpenSSH 10.0 from GitHub. Run the block below in PowerShell on the desktop, not over SSH. When Windows shows "Save your passkey", choose Continue and enter your PIN, then press Enter at both passphrase prompts. Add `id_ecdsa_sk_hello.pub` to GitHub and your servers; replace `*.example.org` with your hosts. After that, the built-in `ssh` and `ssh-keygen` use the key; `ssh host` asks for your PIN each time. Tested with a PIN on build 26100.9457 (September 2026 update) in a VM; not tested: fingerprint, face, a physical laptop, `ssh-add`.

```powershell
$ProgressPreference = 'SilentlyContinue'
$zip = "$env:TEMP\OpenSSH-Win64.zip"
$dir = "$env:TEMP\openssh10"
Invoke-WebRequest -UseBasicParsing https://github.com/PowerShell/Win32-OpenSSH/releases/download/10.0.0.0p2-Preview/OpenSSH-Win64.zip -OutFile $zip
Expand-Archive $zip $dir -Force
$env:SSH_SK_HELPER = "$dir\OpenSSH-Win64\ssh-sk-helper.exe"
New-Item -ItemType Directory -Force "$HOME\.ssh" | Out-Null
& "$dir\OpenSSH-Win64\ssh-keygen.exe" -t ecdsa-sk -f "$HOME\.ssh\id_ecdsa_sk_hello"
Remove-Item Env:SSH_SK_HELPER
Add-Content -Encoding ascii "$HOME\.ssh\config" "`nHost *.example.org`n    IdentityFile ~/.ssh/id_ecdsa_sk_hello"
Remove-Item -Recurse -Force $dir, $zip
git config --global core.sshCommand "C:/Windows/System32/OpenSSH/ssh.exe"
git config --global gpg.ssh.program "C:/Windows/System32/OpenSSH/ssh-keygen.exe"
```

If this fails, use the Bitwarden SSH agent. In an admin PowerShell: `Stop-Service ssh-agent; Set-Service ssh-agent -StartupType Disabled`. In Bitwarden desktop, turn on Settings → **Enable SSH agent**, then create an SSH key item. Run only the two `git config` lines of the block. This key is protected by software and synced, so it is weaker than a hardware key.

**Linux**: Ubuntu 26.04: `sudo apt install ssh-tpm-agent`. Fedora has no package, so use the release binary from GitHub. Then:

```sh
ssh-tpm-agent --install-user-units
systemctl --user enable --now ssh-tpm-agent.socket
ssh-tpm-keygen                     # ECDSA P-256, bound to this TPM
export SSH_AUTH_SOCK="$(ssh-tpm-agent --print-socket)"   # add to ~/.bashrc
```

No TPM: `ssh-keygen -t ed25519` with a strong passphrase.

**YubiKey**: `ssh-keygen -t ed25519-sk -O resident -O verify-required`. Enroll two keys and keep one as a spare.

**GitHub and commit signing**: to use one key for both, upload it twice:

```sh
gh ssh-key add ~/.ssh/KEY.pub --type authentication
gh ssh-key add ~/.ssh/KEY.pub --type signing
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/KEY.pub
git config --global commit.gpgsign true
```

With Bitwarden, first copy the public key from the vault item into `KEY.pub`. Signing needs Git 2.34 or newer.

## GitHub and S3 on each machine

### GitHub

```sh
gh auth login --web     # browser login; token goes to Keychain / Credential Manager / Secret Service
gh auth setup-git       # git over HTTPS uses gh as its credential helper
gh auth status          # shows where the token is stored
```

- Do not put personal access tokens (PATs) on laptops. If gh finds no credential store, as on many servers, it **saves the token to a plain-text file**. So do not log in to gh on shared servers.
- For automation only, use a fine-grained PAT that covers only the repositories it needs. GitHub lets you choose "no expiration", but always set an expiry (366 days at most).

**What `gh auth login` creates.** An OAuth token for the "GitHub CLI" app, starting with `gho_`. By default it has the scopes `repo`, `read:org` and `gist`: `repo` covers **every** repository you can reach, private ones included. Add a scope only when a command asks for it, for example `gh auth refresh -s workflow` to edit GitHub Actions files. `gh auth status` lists the scopes and where the token is stored.

**On a machine without a browser** (a VM, a server over SSH): run `gh auth login`, choose *GitHub.com*, *HTTPS*, *Login with a web browser*. It prints a one-time code. On your laptop open [github.com/login/device](https://github.com/login/device), type the code and approve. The token lands on the remote machine; without a keyring there, it is a plain-text file (`~/.config/gh/hosts.yml`).

**A limited token for one VM or job.** When a machine needs only a few repositories, do not log in with your full account there. Create a fine-grained token instead:

1. [github.com/settings/personal-access-tokens/new](https://github.com/settings/personal-access-tokens/new).
2. *Resource owner*: the team organization. *Expiration*: the shortest that works.
3. *Repository access*: **Only select repositories**. *Permissions*: `Contents` read-only (read and write only if it pushes).
4. On the machine, give it to gh and git through the environment: `export GH_TOKEN=github_pat_…` (gh recommends `GH_TOKEN` rather than `--with-token` for fine-grained tokens).

The prefix tells you what a token is: `gho_` = gh login, `github_pat_` = fine-grained, `ghp_` = classic personal token (avoid). To cut off gh everywhere at once: *Settings → Applications → Authorized OAuth Apps → GitHub CLI → Revoke*. `gh auth logout` only deletes the local copy.

### S3 (s3.text-analytics.ch)

**Admin, once per person:** create a normal user (not an admin) and give it a policy that covers only the team buckets.

```sh
mc admin policy create tas team-rw team-rw.json
mc admin user add tas alice '<long random password>'   # send the password through Bitwarden
mc admin policy attach tas team-rw --user alice
```

**One access key per machine, each with an expiry date:**

```sh
mc admin accesskey create tas alice --name alice-macbook --expiry-duration 180d
#   optional: --policy narrow.json  (it can only reduce the user's rights)
mc admin accesskey rm tas <ACCESSKEY>                  # laptop lost or replaced
```

Users can create their own keys in the web console under **Access Keys**, or with `mc admin accesskey create <their-alias>/` when `mc` is logged in as themselves. The secret is shown only once.

**Store the key on the machine** as one line of JSON: `{"Version":1,"AccessKeyId":"…","SecretAccessKey":"…"}`

| OS | Store it (paste the JSON when asked) | `credential_process =` |
| --- | --- | --- |
| macOS | `security add-generic-password -s s3.text-analytics.ch -a laptop -U -w` | `/usr/bin/security find-generic-password -s s3.text-analytics.ch -a laptop -w` |
| Linux desktop | `secret-tool store --label=S3 service s3.text-analytics.ch account laptop` | `/usr/bin/secret-tool lookup service s3.text-analytics.ch account laptop` |
| Windows | `uv tool install keyring`, then `keyring set s3.text-analytics.ch laptop` | `"C:\Users\alice\.local\bin\keyring.exe" get s3.text-analytics.ch laptop` (run `uv tool dir --bin` to find the real folder) |
| Server | put `[tas]` with both keys in `~/.aws/credentials`, then run `chmod 600` on it | (none) |

In `~/.aws/config`, write full paths. Do not use `~`, `$HOME` or `%USERPROFILE%`:

```ini
[profile tas]
endpoint_url = https://s3.text-analytics.ch
region = us-east-1
credential_process = /usr/bin/security find-generic-password -s s3.text-analytics.ch -a laptop -w
```

DVC (everyone uses the same profile name, so you can commit this):

```sh
dvc remote modify storage endpointurl https://s3.text-analytics.ch
dvc remote modify storage profile tas
```

rclone ignores `endpoint_url`, so it needs its own `endpoint` (`rclone config file` shows where its config is):

```ini
[tas]
type = s3
provider = Minio
env_auth = true
profile = tas
endpoint = https://s3.text-analytics.ch
```

Test it: `aws --profile tas s3 ls`.

**What the keychain protects, and what it does not.** On macOS, the program that creates an item is trusted to read it. So any program running as you can run `security` and read the key without a prompt. Linux and Windows work the same way. The keychain keeps the key out of plain files and backups. The real protection is that each key is narrow, expires, and can be revoked for one machine. Adding `-T ""` makes macOS ask every time. The AWS CLI does not cache credentials, so you would be asked for every single command.

**Never** name the profile `default`. **Never** put `export AWS_PROFILE=…` in a shell startup file. Either one hands the team key to every tool and script.

## Servers

Shared Debian/Ubuntu servers hold **no personal private keys**. Anyone with root on a server can read every file on it.

**Reaching other hosts.** Use `ProxyJump`. Your key stays on your laptop. In `~/.ssh/config`:

```
Host gpu1
  HostName gpu1.internal
  ProxyJump gateway.example.org
```

Turn on `ForwardAgent yes` only for hosts you trust. While you are connected, root on that host can use your agent to log in as you. Root cannot copy the key itself. To limit this, make the agent ask before each use: `ssh-add -c <key>`. This needs a graphical `ssh-askpass` program. Keys that need a Touch ID or YubiKey touch for each use also limit it.

**Git on servers.** Pick one:

- HTTPS with a fine-grained personal access token (PAT). Choose the organization as *Resource owner*, set an expiry date, select only the repositories you need, and grant only `Contents: Read-only`.
- A read-only deploy key for each repository (read-only is the default). Deploy keys never expire. They stay active after the person who added them leaves, because they belong to the repository, not the person.

**S3 jobs.** Give each server its own narrow MinIO access key. Put it in `~/.aws/credentials`, readable only by its owner:

```
chmod 600 ~/.aws/credentials
```

**authorized\_keys.** One line per person per device. The comment names both:

```
ssh-ed25519 AAAA... alice@macbook-2025
```

You can then delete one lost laptop's line and everything else keeps working.

## Lost laptop or someone leaves

Do these on the same day. For a lost laptop, the owner does the account steps and an admin does the server and MinIO steps.

- [ ] **Servers:** remove the person's or the lost device's lines from every `~/.ssh/authorized_keys`. Find them with `grep -n alice ~/.ssh/authorized_keys`.
- [ ] **GitHub SSH keys:** the person opens *Settings → SSH and GPG keys* and clicks **Delete** next to the device's key.
- [ ] **GitHub sessions:** *Settings → Sessions → See more → Revoke session*.
- [ ] **GitHub CLI and apps:** *Settings → Applications → Authorized OAuth Apps*, click **…** next to "GitHub CLI", then **Revoke**. Also delete any PATs used on that device.
- [ ] **MinIO keys:** list them with `mc admin accesskey ls ALIAS USERNAME`, then remove each one with `mc admin accesskey rm ALIAS ACCESSKEY`.
- [ ] **MinIO user (if the person leaves):** `mc admin user disable ALIAS USERNAME`. Also remove the access keys: the docs do not say whether disabling a user stops them.
- [ ] **Bitwarden (if the person leaves):** Admin Console → *Members* → select the person → options menu → **Remove**. Then **change every shared password they could see**. Offline clients may keep a read-only copy for a short time, and they may have copied entries earlier.
- [ ] **GitHub organization (if the person leaves):** *People* → select them → **Remove from organization**. Then check the team repositories' deploy keys: they stay active.
- [ ] **Wipe the lost device:** Mac: icloud.com/find → select the Mac → **Erase This Device** (only if Find My was on before the loss; an offline Mac is erased when it next connects). Windows 11: *Find My Device* at account.microsoft.com/devices can locate and lock, not erase. To check encryption, open Settings → Privacy & security → Device encryption (on Pro, search Start for "Manage BitLocker"); the default setup unlocks the disk by itself at startup and someone holding the laptop can get around it, so treat the disk as readable. A PIN or password asked before Windows starts helps (BitLocker with a startup PIN on Pro, VeraCrypt on Home), but only if the laptop was shut down, not asleep; either way, if it is lost, revoke everything per this checklist. Linux: no remote wipe; rely on full-disk encryption (LUKS).

Keys stored in hardware (Secure Enclave, TPM, YubiKey) cannot be copied off a stolen laptop. Still remove them, so the device can no longer log in.

## Sources

Pages opened while writing this guide (October 2026). Not yet tested by the team: the built-in macOS Secure Enclave commands, the Windows `keyring` helper, rclone with `credential_process`, and whether MinIO AIStor Free has every `mc admin accesskey` option shown.

- [Bitwarden - Set up two-step login](https://bitwarden.com/help/setup-two-step-login/)
- [Bitwarden - Two-step login via FIDO2 WebAuthn](https://bitwarden.com/help/setup-two-step-login-fido/)
- [Bitwarden - Recovery code](https://bitwarden.com/help/two-step-recovery-code/)
- [Bitwarden - Log in with passkeys](https://bitwarden.com/help/login-with-passkeys/)
- [Bitwarden - Unlock with biometrics](https://bitwarden.com/help/biometrics/)
- [Bitwarden - Master password](https://bitwarden.com/help/master-password/)
- [Bitwarden - Organizations overview](https://bitwarden.com/help/about-organizations/)
- [Bitwarden - Groups](https://bitwarden.com/help/about-groups/)
- [Bitwarden - Organizations quick start](https://bitwarden.com/help/getting-started-organizations/)
- [Bitwarden - Password Manager plans](https://bitwarden.com/help/password-manager-plans/)
- [Bitwarden - Business pricing](https://bitwarden.com/pricing/business/)
- [Bitwarden - Emergency access](https://bitwarden.com/help/emergency-access/)
- [Bitwarden blog - Secure password management for MSPs (nonprofit/education pricing via sales)](https://bitwarden.com/blog/secure-password-management-for-msps/)
- [Bitwarden - SSH agent](https://bitwarden.com/help/ssh-agent/)
- [Bitwarden - About SSH](https://bitwarden.com/help/about-ssh/)
- [Bitwarden - Revoke & remove members](https://bitwarden.com/help/remove-users/)
- [arianvp: Native Secure Enclave SSH keys on macOS (gist)](https://gist.github.com/arianvp/5f59f1783e3eaf1a2d4cd8e952bb4acf)
- [Evan Pratten: SSH keys in the Secure Enclave](https://ewpratten.com/blog/ssh-secure-enclave/)
- [openssh-unix-dev: Apple's SSH x OpenSSH (brew) x CTK x Security Key types](https://lists.mindrot.org/pipermail/openssh-unix-dev/2024-July/041451.html)
- [FIDO2 SSH auth using macOS (Durham, June 2026)](https://eamonnbell.webspace.durham.ac.uk/2026/06/09/fido2-ssh-auth-using-macos/)
- [Homebrew formula: openssh](https://formulae.brew.sh/formula/openssh)
- [Homebrew cask: secretive](https://formulae.brew.sh/cask/secretive)
- [Secretive 4.0.0 release](https://github.com/maxgoedjen/secretive/releases/tag/v4.0.0)
- [Win32-OpenSSH #2408: Windows Hello ecdsa-sk signing failures reported since 25H2 (not reproduced on 26100.9457 with a PIN)](https://github.com/PowerShell/Win32-OpenSSH/issues/2408)
- [Win32-OpenSSH #2040: Cannot create ecdsa-sk key with Windows Hello](https://github.com/PowerShell/Win32-OpenSSH/issues/2040)
- [Win32-OpenSSH 10.0.0.0p2-Preview release](https://github.com/PowerShell/Win32-OpenSSH/releases/tag/10.0.0.0p2-Preview)
- [ssh-tpm-agent](https://github.com/Foxboron/ssh-tpm-agent)
- [Ubuntu packages: ssh-tpm-agent](https://packages.ubuntu.com/search?keywords=ssh-tpm-agent&searchon=names&suite=all&section=all)
- [Fedora packages search: ssh-tpm-agent](https://packages.fedoraproject.org/search?query=ssh-tpm-agent)
- [ssh\_config(5): ForwardAgent, ProxyJump](https://man.openbsd.org/ssh_config)
- [ssh-add(1): -c option](https://man.openbsd.org/ssh-add)
- [gh ssh-key add](https://cli.github.com/manual/gh_ssh-key_add)
- [gh auth login](https://cli.github.com/manual/gh_auth_login)
- [gh auth setup-git](https://cli.github.com/manual/gh_auth_setup-git)
- [GitHub: Adding a new SSH key](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/adding-a-new-ssh-key-to-your-github-account)
- [GitHub: Telling Git about your signing key](https://docs.github.com/en/authentication/managing-commit-signature-verification/telling-git-about-your-signing-key)
- [GitHub: About commit signature verification](https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification)
- [GitHub: Managing personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
- [GitHub: Managing deploy keys](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys)
- [GitHub: Reviewing your SSH keys](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/reviewing-your-ssh-keys)
- [GitHub: Viewing and managing your sessions](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/viewing-and-managing-your-sessions)
- [GitHub: Reviewing your authorized OAuth apps](https://docs.github.com/en/apps/oauth-apps/using-oauth-apps/reviewing-your-authorized-oauth-apps)
- [GitHub: Removing a member from your organization](https://docs.github.com/en/organizations/managing-membership-in-your-organization/removing-a-member-from-your-organization)
- [AIStor: mc admin accesskey create](https://docs.min.io/enterprise/aistor-object-store/reference/cli/admin/mc-admin-accesskey/mc-admin-accesskey-create/)
- [AIStor: mc admin accesskey](https://docs.min.io/aistor/reference/cli/admin/mc-admin-accesskey/)
- [AIStor: mc admin accesskey ls](https://docs.min.io/aistor/reference/cli/admin/mc-admin-accesskey/mc-admin-accesskey-list/)
- [AIStor: mc admin accesskey rm](https://docs.min.io/aistor/reference/cli/admin/mc-admin-accesskey/mc-admin-accesskey-remove/)
- [AIStor: mc admin user add](https://docs.min.io/enterprise/aistor-object-store/reference/cli/admin/mc-admin-user/mc-admin-user-add/)
- [AIStor: mc admin user disable](https://docs.min.io/aistor/reference/cli/admin/mc-admin-user/mc-admin-user-disable/)
- [AIStor: mc admin policy attach](https://docs.min.io/enterprise/aistor-object-store/reference/cli/admin/mc-admin-policy/mc-admin-policy-attach/)
- [AIStor: mc admin policy create](https://docs.min.io/enterprise/aistor-object-store/reference/cli/admin/mc-admin-policy/mc-admin-policy-create/)
- [MinIO blog: AIStor Free, Enterprise Lite and Enterprise tiers](https://www.min.io/blog/introducing-new-subscription-tiers-for-minio-aistor-free-enterprise-lite-and-enterprise)
- [AWS CLI v2: Sourcing credentials with an external process](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sourcing-external.html)
- [security(1)](https://keith.github.io/xcode-man-pages/security.1.html)
- [secret-tool(1)](https://man.archlinux.org/man/secret-tool.1.en)
- [keyring on PyPI](https://pypi.org/project/keyring/)
- [uv storage reference](https://docs.astral.sh/uv/reference/storage/)
- [rclone S3](https://rclone.org/s3/)
- [DVC Amazon S3 remote](https://doc.dvc.org/user-guide/data-management/remote-storage/amazon-s3)
- [Apple: Erase a device](https://support.apple.com/guide/icloud/erase-a-device-mmfc0ef36f/icloud)
- [Apple: If your Mac is lost or stolen](https://support.apple.com/en-us/102481)
- [Microsoft: Find and lock a lost Windows device](https://support.microsoft.com/en-us/windows/find-and-lock-a-lost-windows-device-890bf25e-b8ba-d3fe-8253-e98a12f26316)
