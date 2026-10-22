<div align="center">

# ⚡ Nimbus

**Lightweight password manager with encryption, multi-user mode, and a sleek interface.**

Local storage · AES-128 · PBKDF2-600k · Light/Dark themes · RU/EN

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

## ✨ Features

### Security
- **AES-128 (Fernet)** — authenticated encryption of all data (HMAC-SHA256 + AES-CBC).
- **PBKDF2-HMAC-SHA256** with **600,000 iterations** — brute-force resistant master password key derivation.
- **Separate salt** (16 bytes from `secrets`) and **KDF meta-file** — for seamless upgrades without data loss.
- **Atomic writes** of all files via `mkstemp + os.replace` — a process crash won't corrupt the vault.
- **Clipboard auto-clear** after 30 seconds (configurable).
- **Session lock on inactivity** (5 minutes by default) — closes all open dialogs.
- **Failed login delay** — 3 attempts, then exponential backoff (2 → 4 → 8 → 16 → 30 sec).
- **Single-instance lock** — a second copy won't launch and overwrite the first.

### Multi-user mode
- Each user is stored in a **separate folder** `{username}/{username}.nimbus*`.
- **One-password login** — the app iterates through all users and logs into the one whose password matches.
- **«＋»** button on the login screen — quickly create a new user.
- Minimum **10 characters** for the master password.

### Interface
- **Light and dark themes** + automatic system theme detection.
- **Russian and English** languages (switches on the fly).
- **Modern tiles** with smooth hover effects and active row highlighting.
- **Status notifications** directly in the main window (no popups).
- **Tray icon** — app runs in the background, logs out on close, and restores on double-click.

### Data Management
- Create, edit, delete records (service / login / password / description).
- **Real-time search** by service, login, and description.
- **Password generator** (18 chars by default, configurable).
- **Copy any field** with a single click on the tile.
- **Reveal/hide password** on double-click.
- **Import from CSV** (`;` delimiter).
- **Export to CSV** with BOM marker — Excel opens Cyrillic correctly.
- **Export `.nimbus`** — ZIP archive with encrypted user files for backup.

### Convenience
- **Autostart on system boot** (Windows registry).
- **Start minimized to tray**.
- **Configurable password length, lock timeout, clipboard clear timeout**.
- **Localized confirmation dialogs** — no ugly `QMessageBox`.

---

## 📸 Screenshots

### Login Screen
Minimalist one-password login. The **＋** button in the top right creates a new user.

![login](docs/login.png)

### Main Window — Light Theme
Tiles with records, search, action panel, theme switcher.

![main-light](docs/main-light.png)

### Main Window — Dark Theme
Same interface in dark palette (black + yellow accent).

![main-dark](docs/main-dark.png)

### Create / Edit Record
Service, login, password with generator, and description fields.

![edit](docs/edit-dialog.png)

### Settings
Three sections — **GENERAL** (language, theme), **STARTUP** (autostart, minimized mode), **SECURITY** (password length, timeouts, delete confirmation).

![settings](docs/settings.png)

---

## 🛠 Dependencies

- **Python 3.10+** (3.11–3.13 recommended)
- **PyQt6 ≥ 6.5** — GUI
- **cryptography ≥ 41** — encryption (Fernet + PBKDF2)
- **pyperclip ≥ 1.8** — clipboard (optional, but required to copy passwords)
- **pyinstaller ≥ 6** — build only, not needed at runtime

`requirements.txt`:

```txt
PyQt6>=6.5
cryptography>=41.0
pyperclip>=1.8