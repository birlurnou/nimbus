<div align="center">

# ⚡ Nimbus

**Lightweight offline password manager with AES encryption, multi-user mode, automatic encrypted backups, and optional GitHub sync.**

Local storage · AES-128 · PBKDF2-600k · Auto-backups · GitHub Sync · RU/EN · Light/Dark

[![EN](https://img.shields.io/badge/🇺🇸_English-blue?style=flat-square)](readme.md)
[![RU](https://img.shields.io/badge/🇷🇺_Русский-gray?style=flat-square)](readme.ru.md)

[![Release](https://img.shields.io/github/v/release/birlurnou/nimbus?style=flat-square&color=success)](https://github.com/birlurnou/nimbus/releases/latest)
[![Build](https://img.shields.io/github/actions/workflow/status/birlurnou/nimbus/build.yaml?style=flat-square&label=build)](https://github.com/birlurnou/nimbus/actions/workflows/build.yaml)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.5+-41CD52?style=flat-square&logo=qt&logoColor=white)](https://pypi.org/project/PyQt6/)
[![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?style=flat-square&logo=windows&logoColor=white)](https://www.microsoft.com/windows)

</div>

![Main window — light theme](docs/main-light.png)

---

## Table of contents

- [What is Nimbus?](#what-is-nimbus)
- [Key features](#key-features)
- [Installation](#installation)
  - [Requirements](#requirements)
  - [From source](#from-source)
  - [Prebuilt binaries](#prebuilt-binaries)
- [Guides](#guides)
  - [1. First launch — create a user](#1-first-launch--create-a-user)
  - [2. Managing records](#2-managing-records)
  - [3. GitHub Sync — multi-device setup](#3-github-sync--multi-device-setup)
  - [4. Backups — local and remote](#4-backups--local-and-remote)
  - [5. Import / Export](#5-import--export)
  - [6. Change master password](#6-change-master-password)
  - [7. Settings](#7-settings)
  - [8. Tray & autostart](#8-tray--autostart)
- [Security](#security)
- [FAQ](#faq)
- [Project structure](#project-structure)
- [Contributing](#contributing)
- [License](#license)
- [Screenshots](#-screenshots)

---

## What is Nimbus?

Nimbus is a **local-first** password manager: your encrypted vault never leaves
your machine unless you explicitly enable GitHub sync. It is designed for people
who want full control over their secrets without relying on a cloud provider,
but who still want to keep multiple devices in sync.

- **No telemetry. No cloud. No accounts.** — everything is a local file.
- **Encrypted backups on every change** — accidental deletion is recoverable.
- **Optional GitHub sync** — bring your own private repository as transport.
- **Multi-user** — family / team can share one machine, each with their own vault.

---

## Key features

| Area | What you get |
|---|---|
| **Security** | AES-128 (Fernet) · PBKDF2-SHA256 600k iterations · per-user salt · atomic writes · clipboard auto-clear · session timeout · exponential backoff on wrong password |
| **Backups** | Auto-snapshot on every mutation · 50-snapshot rolling retention · encrypted with the same master key · one-click restore · synced to GitHub (optional) |
| **Sync** | Git-based · PAT auth · per-record merge by `updated_at` · tombstones for deletions (30 days) · background push & pull · visual status indicator |
| **Users** | Multi-user vaults in `{user}/` folders · one-password login · instant user switch |
| **Data** | Create / edit / delete · real-time search · password generator · one-click copy per field · copy full row · bulk delete · CSV import (with dedup) · CSV / ZIP export |
| **UI** | Light / dark / system themes · EN / RU · live preview of settings · tray icon · autostart |

---

## Installation

### Requirements

- **Python 3.10+** (3.11–3.13 recommended)
- **Git** available in `PATH` — only required for GitHub Sync
- Tested on **Windows 10/11**

### From source

```bash
git clone https://github.com/birlurnou/nimbus.git
cd nimbus
pip install -r requirements.txt
python nimgui.pyw
```

`requirements.txt`:

```txt
PyQt6>=6.5
cryptography>=41.0
pyperclip>=1.8
```

### Prebuilt binaries

Download the latest `.zip` from the [Releases](https://github.com/birlurnou/nimbus/releases/latest) page — no Python install required.

---

## Guides

### 1. First launch — create a user

On first start Nimbus asks you to create a user:

1. Choose a **login**.
2. Choose a **master password** (min 10 chars). **There is no password recovery** — write it down.
3. Optionally configure **GitHub Sync** right away (**can be configured later**, see [section 3](#3-github-sync--multi-device-setup)).
4. Click **Create**.

The vault is created at `{login}/{login}.nimbus` alongside `…_key`, `…_salt`, `…_meta`. All files are encrypted — only the salt and meta are plaintext.

To add another user later, click **＋** on the login screen.

### 2. Managing records

The main window shows tiles (one per record) with **Service · Login · Password · Description**.

- **Single click** on a field → copy that field to the clipboard (auto-clears after 30s - default value, configurable).
- **Double click** on the password field → reveal / hide.
- **Double click** on any other cell → open the record for editing.
- Hovering a row reveals **3 action icons**:
  - **⧉ Copy row** — copies `service;login;password;description` as one line.
  - **✎ Edit** — open the editor.
  - **✕ Delete** — remove (with confirmation if enabled in settings).

Bottom action bar (mirrors the same actions for the currently selected row):

- **Edit** · **Copy row** · **Copy password** · **Delete**

Top action bar:

- **Create** — add a new record.
- **Import (CSV)** — see [section 5](#5-import--export).
- **Export (text)** — export to plaintext CSV (asks for master password).
- **Export (.nimbus)** — export a ZIP archive of the entire user folder (asks for master password).
- **Restore from backup** — see [section 4](#4-backups--local-and-remote).
- **Delete all** — wipes every record (two-step confirmation).

Search box filters in real time across **service / login / description**.

### 3. GitHub Sync — multi-device setup

Nimbus can use **any private Git repository** as a transport for your encrypted vault. Files are pushed as-is (already encrypted) — GitHub never sees plaintext.

#### Setup on the first device (e.g. home PC)

1. Create a **private** repo on GitHub, e.g. `your-name/nimbus-data`. No files needed — Nimbus will create them.
2. Create a **Fine-grained Personal Access Token**:
   - GitHub → Settings → Developer settings → **Fine-grained tokens** → Generate new token.
   - **Repository access:** Only select repositories → pick your vault repo.
   - **Permissions:** Contents → **Read and write**.
   - Copy the token (`github_pat_…`).
3. In Nimbus → **Settings → GitHub Sync**:
   - Enable sync.
   - Paste repo URL: `https://github.com/user/repo.git`.
   - Paste the PAT.
   - Branch: `main` (or your default).
   - Sync interval: 600 s (default — 10 min).
4. Click **Test connection** → **Save**.

The initial push happens automatically within a second.

#### Setup on the second device (e.g. work PC)

1. Open Nimbus → **＋** on the login screen → **Restore from GitHub** tab.
2. Paste the same repo URL and PAT, optionally specify the exact `username`.
3. Click **Restore**. Nimbus clones the repo into your working directory.
4. Log in with the **original master password**.
5. Open **Settings → GitHub Sync**, paste URL + PAT again (they are per-machine), test, save.

#### How conflict resolution works

- Every record stores `updated_at` (last modification timestamp).
- Deletions are not physically removed — they become **tombstones** (`_deleted=true`, `_deleted_at=<ts>`) kept for **30 days**.
- On pull, Nimbus merges remote and local records **per `(service, username)` key**, picking the newer side by `updated_at` / `_deleted_at`.
- Removed-on-one, edited-on-another: latest timestamp wins.
- Two different users (different `nimbus_key`) with the same login are refused — restore the correct vault or pick another username.

#### What gets pushed

The whole `{username}/` folder: `.nimbus`, `.nimbus_key`, `.nimbus_salt`, `.nimbus_meta`, `.nimbus_settings`, and **`backup/`**. The following is **not** synced:

- `*.lock` files (single-instance locks)
- `.nimbus_sync_state.json` (local sync checkpoint)
- other users' folders (each commit only stages `{username}/`, `.gitignore`, `README.md`)

> **Migration note from v1.2.x:** your existing `.gitignore` may contain `**/backup/`. Nimbus 1.3.0 no longer adds it, but it also doesn't strip old entries — delete that line manually once if you want backups to sync.

### 4. Backups — local and remote

Every mutating action creates an encrypted snapshot in `{user}/backup/`:

| Trigger | Snapshot name |
|---|---|
| User created | `alice_YYMMDD_HHMMSS_initial.nimbus` |
| Add record | `…_add.nimbus` |
| Edit record | `…_update.nimbus` |
| Delete record | `…_delete.nimbus` |
| Delete all | `…_delete_all.nimbus` |
| Import CSV | `…_import.nimbus` |
| Change master password | `…_chpw.nimbus` |
| Restore from backup | `…_restorebackup.nimbus` |

- **Retention:** only the last **50** snapshots per user are kept. Older ones are pruned automatically.
- **Format:** the snapshot is a byte-for-byte copy of `{user}.nimbus`, **encrypted with the master password in effect at that moment**.

> ⚠️ **Important — changing the master password does NOT re-encrypt old snapshots.** They stay encrypted with the previous password and cannot be restored with the new one. Before changing your master password, export a `.nimbus` ZIP (see [section 5](#5-import--export)) if you want to keep a restorable emergency copy.

#### Restore flow

1. Main window → **Restore from backup**.
2. Dialog lists snapshots (date / time / action).
3. Select one → **Restore** → confirm.
4. Nimbus verifies the snapshot can be decrypted with the current password, replaces `{user}.nimbus`, reloads the in-memory store.
5. A `…_restorebackup.nimbus` snapshot of the *pre-restore* state is also created — you can undo a restore.

### 5. Import / Export

#### Import from CSV

- Delimiter: `;` · Encoding: UTF-8 with or without BOM.
- Columns: `service;login;password;description` (description optional).
- **Duplicates are skipped** by `(service, login)` — both against existing records and within the same CSV. The status line reports how many were skipped.
- Import requires the master password (extra confirmation prompt).

#### Export to CSV

- Plaintext file, `;` delimiter, UTF-8 with BOM — opens correctly in Excel with Cyrillic.
- **Requires master password.** After export Nimbus shows a warning: *"file is plaintext — delete it after use."*

#### Export to ZIP (`.nimbus` archive)

- Packages the whole `{user}/` folder: vault, key, salt, meta, settings (skips the lock file).
- **Requires master password.**
- Useful as an off-machine cold backup (e.g. copy the ZIP to a USB stick).

### 6. Change master password

**Settings → Security → Change master password.**

Two-step dialog:

1. Enter the current password (verified).
2. Enter the new password twice. A green checkmark appears as soon as both match and meet the 10-char minimum; a red ✕ if not.
3. Click **Save**.

After the change:

- `{user}.nimbus` is re-encrypted with the new key.
- `{user}.nimbus_key` is rewritten.
- A `…_chpw.nimbus` backup of the pre-change vault is created (encrypted with the **old** password).
- If GitHub Sync is enabled, the change is pushed immediately.
- **All existing backups remain encrypted with the previous password** and cannot be restored with the new one.
- You are logged out automatically — log in again with the new password.

### 7. Settings

| Tab | What's there |
|---|---|
| **General** | Language (EN/RU), theme (System/Light/Dark) — both apply as live preview |
| **Security** | Password length (default 18), clipboard clear timeout, session timeout, confirm-before-delete toggle, minimize-to-tray toggle, **Change master password** |
| **GitHub Sync** | Enable, repo URL, PAT, branch, sync interval, **Test connection** |

All settings are stored per-user in `{user}.nimbus_settings` (not synced).

### 8. Tray & autostart

- Closing the window sends Nimbus to the **system tray** (configurable). The session is logged out automatically — this is intentional: leaving the app unattended shouldn't keep the vault decrypted.
- **Double click** on the tray icon → open.
- **Right click** → Open / Quit.
- **Autostart**: register Nimbus in `HKCU\…\CurrentVersion\Run` (Windows) — launched minimized if enabled.

---

## Security

- **Encryption:** Fernet (AES-128-CBC + HMAC-SHA256), a symmetric authenticated scheme from `cryptography`.
- **Key derivation:** PBKDF2-HMAC-SHA256, **600 000 iterations**, 32-byte output, per-user 16-byte salt (`secrets.token_bytes`).
- **Verification:** `{user}.nimbus_key` stores an encrypted copy of the master password — the login decrypts it and compares; this proves the key without exposing it.
- **Atomic writes:** every file write goes through `mkstemp` in the same directory + `os.replace`.
- **Fail-safe on decrypt error:** if a vault cannot be decrypted, Nimbus refuses to start that user instead of overwriting with an empty vault.
- **Clipboard hygiene:** copied values are cleared after 30 s (default), only if the clipboard still contains the same value.
- **Session timeout:** after 5 min of inactivity all open dialogs are closed and the session logs out.
- **Backoff:** 3 wrong-password attempts → exponential delay (2 → 4 → 8 → 16 → 30 s).
- **Git credentials:** PAT is used only inside per-command environment variables — never written to `.git/config`, never logged (error messages are sanitized with `***`).

---

## FAQ

**I forgot my master password. Can I recover it?**
No. There is no recovery mechanism — that's the point of a zero-knowledge design. Restore from a backup with the password the backup was encrypted with, or restore the whole user folder from your GitHub repo (which is still encrypted with that password).

**I changed the master password and now backups won't open.**
Old backups were encrypted with the old password. That's expected. To keep a working emergency backup, export a `.nimbus` ZIP **before** changing the password.

**My GitHub repo already had `**/backup/` in `.gitignore` — sync doesn't push backups.**
Nimbus 1.3.0 stopped adding that line, but preserves pre-existing entries. Open the repo, remove the line, commit, push.

**Sync says "user already exists with a different master password".**
The remote repo has a `{username}/` folder belonging to someone else (different `nimbus_key`). Either restore the correct vault via *Restore from GitHub* or pick a different username.

**Git says "authentication failed".**
PAT must have `Contents: Read and write` on that repo. Fine-grained tokens expire — regenerate if older than the configured lifetime.

**Can I use a public repo?**
Technically yes — the vault is encrypted — but the presence of `.nimbus_key` and salt is metadata leakage. Use a **private** repo.

**Where are my files stored?**
Everything is relative to the Nimbus program directory:

```
nimbus/
├── alice/
│   ├── alice.nimbus          ← encrypted vault
│   ├── alice.nimbus_key      ← encrypted master-pw check
│   ├── alice.nimbus_salt     ← 16-byte salt (plaintext)
│   ├── alice.nimbus_meta     ← KDF params (plaintext)
│   ├── alice.nimbus_settings ← per-user settings (plaintext JSON)
│   ├── alice.nimbus.lock     ← single-instance marker
│   └── backup/               ← encrypted snapshots
└── bob/ …
```

---

## Project structure

```
nimbus.py       ← encryption, storage, CLI (legacy), backups
nimbus_sync.py  ← GitSync, clone, test_connection
nimgui.pyw      ← PyQt6 GUI
```

---

## Contributing

Issues and PRs welcome. Please run the app on your own machine before opening a PR; there is currently no test suite.

## License

MIT — see [LICENSE](LICENSE).

## Screenshots

### Login Screen
Minimalist one-password login. The **＋** button in the top right creates a new user.

![login](docs/login.png)

### Main Window — Light Theme
Tiles with records, search, action panel, and the sync indicator at the bottom right.

![main-light](docs/main-light.png)

### Main Window — Dark Theme
Same interface in dark palette (black + yellow accent).

![main-dark](docs/main-dark.png)

### Create / Edit Record
Service, login, password with generator, and description fields.

![edit-dialog](docs/edit-dialog.png)

### Settings
Three tabs — **General** (language, theme, startup), **Security** (password length, timeouts), and **GitHub Sync** (repo URL, PAT, interval).

![settings-general](docs/settings-general.png)

![settings-security](docs/settings-security.png)

![settings-sync](docs/settings-sync.png)