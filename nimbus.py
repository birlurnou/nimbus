import base64
import csv
import getpass
import json
import os
import platform
import secrets
import shlex
import shutil
import string
import sys
import tempfile
import threading
import time
from typing import Optional
import zipfile

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
except ImportError:
    print("Missing dependency: pip install cryptography")
    sys.exit(1)

try:
    import pyperclip
    HAS_CLIPBOARD = True
except ImportError:
    HAS_CLIPBOARD = False


# ---------------------------------------------------------------------------
# Legacy constants (CLI)
# ---------------------------------------------------------------------------

KEY_FILE = '.nimbus_key'
SALT_FILE = '.nimbus_salt'
DATA_FILE = '.nimbus'
META_FILE = '.nimbus_meta'

KDF_ITERATIONS_V1 = 391_827
KDF_ITERATIONS_V2 = 600_000
KDF_ITERATIONS = KDF_ITERATIONS_V2

STORAGE_VERSION = 2
META_VERSION = 2

MIN_MASTER_PASSWORD_LEN = 10
SESSION_TIMEOUT = 300
MAX_LOGIN_ATTEMPTS = 3
CLIPBOARD_CLEAR_SECONDS = 30

TOMBSTONE_TTL_SECONDS = 30 * 86400


# ---------------------------------------------------------------------------
# Multi-user paths
# ---------------------------------------------------------------------------

class UserPaths:
    def __init__(self, username: str, base_dir: str = '.'):
        self.username = username
        self.base_dir = base_dir
        self.user_dir = os.path.join(base_dir, username)
        self.data_file = os.path.join(self.user_dir, f'{username}.nimbus')
        self.key_file = os.path.join(self.user_dir, f'{username}.nimbus_key')
        self.salt_file = os.path.join(self.user_dir, f'{username}.nimbus_salt')
        self.meta_file = os.path.join(self.user_dir, f'{username}.nimbus_meta')
        self.settings_file = os.path.join(self.user_dir, f'{username}.nimbus_settings')
        self.lock_file = os.path.join(self.user_dir, f'{username}.nimbus.lock')
        self.backup_dir = os.path.join(self.user_dir, 'backup')

    def ensure_dir(self):
        os.makedirs(self.user_dir, exist_ok=True)
        if not os.path.exists(self.lock_file):
            try:
                _atomic_write_text(
                    self.lock_file,
                    f"created={time.ctime()}\n",
                )
            except Exception:
                pass

    def exists(self) -> bool:
        return os.path.exists(self.key_file)

    def all_files(self) -> list:
        return [
            self.data_file,
            self.key_file,
            self.salt_file,
            self.meta_file,
            self.settings_file,
            self.lock_file,
        ]

    def export_to_zip(self, dest_dir: str) -> tuple[bool, str]:
        zip_filename = f"{self.username}.zip"
        full_zip_path = os.path.join(dest_dir, zip_filename)

        try:
            tmp_fd, tmp_path = tempfile.mkstemp(
                prefix='.nimbus_zip_', dir=dest_dir, suffix='.zip'
            )
            os.close(tmp_fd)

            with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                added = 0
                skipped = []

                for src in self.all_files():
                    if not os.path.exists(src):
                        skipped.append(os.path.basename(src))
                        continue

                    arcname = f"{self.username}/{os.path.basename(src)}"
                    try:
                        zf.write(src, arcname)
                        added += 1
                    except PermissionError:
                        if src.endswith('.lock'):
                            try:
                                zf.writestr(arcname, "exported (original locked)\n")
                                added += 1
                            except Exception:
                                skipped.append(os.path.basename(src))
                        else:
                            skipped.append(os.path.basename(src))
                    except Exception:
                        skipped.append(os.path.basename(src))

            os.replace(tmp_path, full_zip_path)
            try:
                os.chmod(full_zip_path, 0o600)
            except Exception:
                pass

            msg = f'Exported {added} files to {full_zip_path}'
            if skipped:
                msg += f'\nSkipped: {", ".join(skipped)}'
            return True, msg

        except Exception as e:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            return False, f'Archive export failed: {e}'

    # ---------- backup ----------

    def backup_data_file(self, action: str, keep: int = 50) -> Optional[str]:
        if not os.path.exists(self.data_file):
            return None
        try:
            os.makedirs(self.backup_dir, exist_ok=True)
            ts = time.strftime('%y%m%d_%H%M%S')
            safe = ''.join(c if (c.isalnum() or c == '_') else '_'
                           for c in str(action))[:32] or 'snap'
            base = f"{self.username}_{ts}_{safe}"
            path = os.path.join(self.backup_dir, base + '.nimbus')
            i = 1
            while os.path.exists(path):
                path = os.path.join(self.backup_dir, f"{base}_{i}.nimbus")
                i += 1
            shutil.copy2(self.data_file, path)
            try:
                os.utime(path, None)
            except Exception:
                pass
            try:
                os.chmod(path, 0o600)
            except Exception:
                pass

            try:
                snaps = [
                    os.path.join(self.backup_dir, f)
                    for f in os.listdir(self.backup_dir)
                    if f.endswith('.nimbus') and f.startswith(f"{self.username}_")
                ]
                snaps.sort(key=lambda p: os.path.getmtime(p))
                for old in snaps[:-keep]:
                    try:
                        os.remove(old)
                    except Exception:
                        pass
            except Exception as e:
                print(f"[backup] retention failed: {e}")

            return path
        except Exception as e:
            print(f"[backup] failed: {e}")
            return None

    def list_backups(self) -> list:
        result = []
        if not os.path.isdir(self.backup_dir):
            return result
        prefix = f"{self.username}_"
        try:
            for f in os.listdir(self.backup_dir):
                if not f.endswith('.nimbus'):
                    continue
                path = os.path.join(self.backup_dir, f)
                if not os.path.isfile(path):
                    continue
                stem = f[:-len('.nimbus')]
                action = ''
                ts_label = ''
                if stem.startswith(prefix):
                    rest = stem[len(prefix):]
                    parts = rest.split('_', 2)
                    if len(parts) >= 2:
                        ts_label = f"{parts[0]}_{parts[1]}"
                        action = parts[2] if len(parts) > 2 else ''
                try:
                    mtime = os.path.getmtime(path)
                    size = os.path.getsize(path)
                except Exception:
                    mtime, size = 0, 0
                result.append({
                    'filename': f,
                    'path': path,
                    'action': action,
                    'ts': ts_label,
                    'mtime': mtime,
                    'size': size,
                })
        except Exception:
            pass
        result.sort(key=lambda x: x['mtime'], reverse=True)
        return result

    def restore_backup(self, filename: str, crypto=None) -> tuple:
        src = os.path.join(self.backup_dir, filename)
        if not os.path.isfile(src):
            return False, f"Backup not found: {filename}"
        if crypto is not None:
            try:
                with open(src, 'r', encoding='utf-8') as f:
                    enc = f.read().strip()
                if enc:
                    crypto.decrypt(enc)
            except Exception as e:
                return False, (
                    f"backup cannot be decrypted with current master "
                    f"password: {e}"
                )
        try:
            shutil.copy2(src, self.data_file)
            try:
                os.utime(self.data_file, None)
            except Exception:
                pass
            try:
                os.chmod(self.data_file, 0o600)
            except Exception:
                pass
            return True, filename
        except Exception as e:
            return False, str(e)


def list_existing_users(base_dir: str = '.') -> list:
    users = []
    try:
        for name in os.listdir(base_dir):
            path = os.path.join(base_dir, name)
            if not os.path.isdir(path):
                continue
            if os.path.exists(os.path.join(path, f'{name}.nimbus_key')):
                users.append(name)
    except Exception:
        pass
    return sorted(users)


def validate_username(username: str) -> Optional[str]:
    if not username:
        return 'empty'
    if len(username) < 2:
        return 'too_short'
    if len(username) > 32:
        return 'too_long'
    bad = set('/\\:*?"<>|\0\t\n\r .')
    if any(c in bad for c in username):
        return 'bad_chars'
    return None


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def clear_console() -> None:
    if platform.system() == 'Windows':
        os.system('cls')
    else:
        print('\033[2J\033[H', end='')


def safe_str(value) -> str:
    if value is None:
        return ''
    return str(value).replace('\r', ' ').replace('\n', ' ').strip()


def _atomic_write_bytes(path: str, data: bytes, mode: int = 0o600) -> None:
    parent = os.path.dirname(path) or '.'
    os.makedirs(parent, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(prefix='.nimbus_tmp_', dir=parent)
    try:
        with os.fdopen(tmp_fd, 'wb') as f:
            f.write(data)
        try:
            os.chmod(tmp_path, mode)
        except Exception:
            pass
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def _atomic_write_text(path: str, content: str, mode: int = 0o600) -> None:
    _atomic_write_bytes(path, content.encode('utf-8'), mode=mode)


# ---------------------------------------------------------------------------
# Password generator
# ---------------------------------------------------------------------------

def generate_password(length: int = 18) -> str:
    if length < 8:
        raise ValueError('Password length must be >= 8')

    specials = '!@#$%^&*()_+-=[]'
    all_chars = string.ascii_letters + string.digits + specials

    required = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice(specials),
    ]
    rest = [secrets.choice(all_chars) for _ in range(length - len(required))]
    chars = required + rest

    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]

    return ''.join(chars)


# ---------------------------------------------------------------------------
# KDF meta
# ---------------------------------------------------------------------------

def get_kdf_iterations(meta_file: str = META_FILE) -> int:
    if not os.path.exists(meta_file):
        return KDF_ITERATIONS_V1
    try:
        with open(meta_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        it = int(data.get('iterations', KDF_ITERATIONS_V1))
        return it if it > 0 else KDF_ITERATIONS_V1
    except Exception as e:
        print(f"[meta] read error: {e}; using legacy iterations")
        return KDF_ITERATIONS_V1


def save_meta(meta_file: str, iterations: int) -> None:
    payload = json.dumps(
        {"version": META_VERSION, "iterations": int(iterations)},
        indent=2,
    )
    _atomic_write_text(meta_file, payload)


# ---------------------------------------------------------------------------
# Encryption
# ---------------------------------------------------------------------------

class EncryptionManager:
    def __init__(self, password: str, salt: bytes, iterations: Optional[int] = None):
        if iterations is None:
            iterations = KDF_ITERATIONS_V2
        self.salt = salt
        self.iterations = iterations

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=iterations,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode('utf-8')))
        self.cipher = Fernet(key)
        del key

    def encrypt(self, data: str) -> str:
        return base64.urlsafe_b64encode(
            self.cipher.encrypt(data.encode('utf-8'))
        ).decode('ascii')

    def decrypt(self, data: str) -> str:
        return self.cipher.decrypt(
            base64.urlsafe_b64decode(data)
        ).decode('utf-8')


# ---------------------------------------------------------------------------
# Salt / key / verification
# ---------------------------------------------------------------------------

def load_or_create_salt(salt_file: str = SALT_FILE) -> bytes:
    if os.path.exists(salt_file):
        with open(salt_file, 'rb') as f:
            salt = f.read()
        if len(salt) != 16:
            raise RuntimeError(
                f'Corrupted {salt_file}: expected 16 bytes, got {len(salt)}'
            )
        return salt
    salt = secrets.token_bytes(16)
    _atomic_write_bytes(salt_file, salt)
    return salt


def save_key_file(key_file: str, encrypted: str) -> None:
    _atomic_write_text(key_file, encrypted)


def verify_master_password(password: str, salt: bytes,
                            key_file: Optional[str] = None) -> bool:
    if key_file is None:
        key_file = KEY_FILE
    if not os.path.exists(key_file):
        return False
    try:
        with open(key_file, 'r', encoding='utf-8') as f:
            encrypted = f.read().strip()
    except OSError as e:
        print(f"[verify] cannot read {key_file}: {e}")
        return False

    if not encrypted:
        return False

    try:
        crypto = EncryptionManager(password, salt)
        decrypted = crypto.decrypt(encrypted)
    except InvalidToken:
        return False
    except (ValueError, TypeError) as e:
        print(f"[verify] corrupted {key_file}: {e}")
        return False
    except Exception as e:
        print(f"[verify] unexpected error: {e}")
        return False

    return decrypted == password


# ---------------------------------------------------------------------------
# Storage (с поддержкой sync: updated_at, tombstones, merge)
# ---------------------------------------------------------------------------

class Storage:

    def __init__(self, crypto: EncryptionManager, data_file: str = DATA_FILE):
        self.file = data_file
        self.crypto = crypto
        self._raw_data: list = self._load()
        self._sync_data()

    # ---------- внутреннее ----------

    def _sync_data(self):
        self.data = [r for r in self._raw_data if not r.get("_deleted")]

    def _load(self) -> list:
        if not os.path.exists(self.file):
            return []
        with open(self.file, "r", encoding="utf-8") as f:
            encrypted = f.read().strip()
        if not encrypted:
            return []
        try:
            payload = json.loads(self.crypto.decrypt(encrypted))
        except Exception as e:
            print(f"\nFATAL: cannot decrypt {self.file}: {e}")
            print('Restore from backup or check master password / salt.')
            sys.exit(1)

        if isinstance(payload, dict) and "records" in payload:
            return list(payload["records"])
        if isinstance(payload, list):
            return list(payload)
        print(f"\nFATAL: unknown storage format in {self.file}")
        sys.exit(1)

    def _save(self) -> None:
        # выкидываем очень старые надгробия
        cutoff = time.time() - TOMBSTONE_TTL_SECONDS
        self._raw_data = [
            r for r in self._raw_data
            if not (r.get("_deleted") and (r.get("_deleted_at") or 0) < cutoff)
        ]
        payload = {
            "version": STORAGE_VERSION,
            "records": self._raw_data,
            "updated_at": time.time(),
        }
        encrypted = self.crypto.encrypt(
            json.dumps(payload, ensure_ascii=False)
        )
        _atomic_write_text(self.file, encrypted)

    # ---------- публичное ----------

    def get_all(self) -> list:
        return self.data

    def get(self, index: int) -> Optional[dict]:
        if 0 <= index < len(self.data):
            return self.data[index]
        return None

    def add(self, record: dict) -> None:
        record = dict(record)
        record["updated_at"] = time.time()
        self._raw_data.append(record)
        self._sync_data()
        try:
            self._save()
        except Exception:
            self._raw_data.pop()
            self._sync_data()
            raise

    def update(self, index: int, record: dict) -> bool:
        if not (0 <= index < len(self.data)):
            return False
        target = self.data[index]
        raw_idx = next(
            (i for i, r in enumerate(self._raw_data) if r is target), None
        )
        if raw_idx is None:
            return False
        record = dict(record)
        record["updated_at"] = time.time()
        old = self._raw_data[raw_idx]
        self._raw_data[raw_idx] = record
        self._sync_data()
        try:
            self._save()
        except Exception:
            self._raw_data[raw_idx] = old
            self._sync_data()
            raise
        return True

    def delete(self, index: int) -> bool:
        if not (0 <= index < len(self.data)):
            return False
        target = self.data[index]
        raw_idx = next(
            (i for i, r in enumerate(self._raw_data) if r is target), None
        )
        if raw_idx is None:
            return False
        old = self._raw_data[raw_idx]
        tombstone = dict(target)
        tombstone["_deleted"] = True
        tombstone["_deleted_at"] = time.time()
        self._raw_data[raw_idx] = tombstone
        self._sync_data()
        try:
            self._save()
        except Exception:
            self._raw_data[raw_idx] = old
            self._sync_data()
            raise
        return True

    def delete_all(self) -> int:
        n = len(self.data)
        now = time.time()
        for rec in self.data:
            rec["_deleted"] = True
            rec["_deleted_at"] = now
        self._sync_data()
        self._save()
        return n

    # ---------- merge ----------

    def merge_records(self, other_records: list) -> int:
        def key(r):
            return (
                safe_str(r.get("service", "")).lower(),
                safe_str(r.get("username", "")).lower(),
            )

        remote_map = {key(r): r for r in other_records}
        result, consumed = [], set()

        for local_rec in self._raw_data:
            k = key(local_rec)
            if k in consumed:
                continue
            consumed.add(k)
            remote_rec = remote_map.get(k)
            if remote_rec is None:
                result.append(local_rec)
                continue

            l_del = local_rec.get("_deleted_at") or 0
            r_del = remote_rec.get("_deleted_at") or 0
            l_upd = local_rec.get("updated_at") or 0
            r_upd = remote_rec.get("updated_at") or 0

            if l_del and r_del:
                result.append(local_rec if l_del >= r_del else remote_rec)
            elif l_del:
                result.append(remote_rec if r_upd > l_del else local_rec)
            elif r_del:
                result.append(local_rec if l_upd > r_del else remote_rec)
            else:
                result.append(local_rec if l_upd >= r_upd else remote_rec)

        for remote_rec in other_records:
            k = key(remote_rec)
            if k in consumed:
                continue
            consumed.add(k)
            result.append(remote_rec)

        self._raw_data = result
        self._sync_data()
        return len(self.data)

    # ---------- экспорт / импорт ----------

    def export_to_file(self, filepath: str) -> tuple[bool, str]:
        try:
            full_path = os.path.expanduser(filepath)
            directory = os.path.dirname(full_path) or '.'
            if not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)

            if not os.access(directory, os.W_OK):
                return False, f'No write permission in directory: {directory}'

            tmp_fd, tmp_path = tempfile.mkstemp(
                prefix='.nimbus_export_', dir=directory, text=True
            )
            try:
                with os.fdopen(tmp_fd, 'w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.writer(
                        f, delimiter=';', quoting=csv.QUOTE_MINIMAL,
                        lineterminator='\n'
                    )
                    for record in self.data:
                        writer.writerow([
                            safe_str(record.get('service', '')),
                            safe_str(record.get('username', '')),
                            safe_str(record.get('password', '')),
                            safe_str(record.get('description', '')),
                        ])
                try:
                    os.chmod(tmp_path, 0o600)
                except Exception:
                    pass
                os.replace(tmp_path, full_path)
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass

            return True, (
                f'Exported {len(self.data)} records to {full_path}\n'
                f'WARNING: file is plaintext — delete it after use.'
            )
        except PermissionError as e:
            return False, f'Permission denied: {e}'
        except Exception as e:
            return False, f'Export failed: {e}'

    def import_from_file(self, filepath: str) -> tuple[bool, str]:
        try:
            full_path = os.path.expanduser(filepath)
            if not os.path.exists(full_path):
                return False, f'File not found: {full_path}'

            new_records = []
            errors = []

            with open(full_path, 'r', encoding='utf-8-sig', newline='') as f:
                reader = csv.reader(f, delimiter=';')
                for line_num, parts in enumerate(reader, 1):
                    if not parts or all(not p.strip() for p in parts):
                        continue
                    if len(parts) < 3:
                        errors.append(f'Line {line_num}: need >= 3 fields')
                        continue
                    service = parts[0].strip()
                    username = parts[1].strip()
                    password = parts[2].strip()
                    description = parts[3].strip() if len(parts) > 3 else ''
                    if not service or not username or not password:
                        errors.append(f'Line {line_num}: empty required fields')
                        continue
                    new_records.append({
                        'service': service,
                        'username': username,
                        'password': password,
                        'description': description,
                    })

            if not new_records:
                return False, f'No records imported. Errors: {len(errors)}'

            existing_keys = {
                (safe_str(r.get('service', '')).lower().strip(),
                 safe_str(r.get('username', '')).lower().strip())
                for r in self._raw_data
                if not r.get('_deleted')
            }

            filtered = []
            skipped = 0
            seen_in_csv = set()
            for r in new_records:
                key = (r['service'].lower().strip(), r['username'].lower().strip())
                if key in existing_keys or key in seen_in_csv:
                    skipped += 1
                    continue
                seen_in_csv.add(key)
                filtered.append(r)

            if not filtered:
                return False, (
                    f'No new records (already have {skipped}, errors: {len(errors)})'
                )

            now = time.time()
            for r in filtered:
                r["updated_at"] = now

            n_before = len(self._raw_data)
            self._raw_data.extend(filtered)
            self._sync_data()
            try:
                self._save()
            except Exception as e:
                del self._raw_data[n_before:]
                self._sync_data()
                return False, f'Import failed (save): {e}'

            return True, (
                f'Imported {len(filtered)} new records, '
                f'skipped {skipped} existing. Errors: {len(errors)}'
            )
        except Exception as e:
            return False, f'Import failed: {e}'


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class Session:
    def __init__(self):
        self.auth = False
        self.crypto: Optional[EncryptionManager] = None
        self.storage: Optional[Storage] = None
        self.salt: Optional[bytes] = None
        self.paths: Optional[UserPaths] = None
        self.username: Optional[str] = None
        self.last_action = time.time()
        self.expired = False

    def touch(self):
        self.last_action = time.time()

    def logout(self):
        self.auth = False
        self.crypto = None
        self.storage = None
        self.paths = None
        self.username = None
        self.expired = False

    def is_idle(self) -> bool:
        return self.auth and (time.time() - self.last_action > SESSION_TIMEOUT)


def inactivity_monitor(session: Session) -> None:
    while True:
        time.sleep(1)
        if session.is_idle():
            session.logout()
            session.expired = True
            clear_console()
            print('\nSession expired due to inactivity\n')


# ---------------------------------------------------------------------------
# CLI Authentication (legacy)
# ---------------------------------------------------------------------------

def create_master_password(salt: bytes) -> Optional[str]:
    print('You need to create a master password.\n')
    print(f'Minimum {MIN_MASTER_PASSWORD_LEN} characters.\n')
    while True:
        password = getpass.getpass(
            f'Enter master password (min {MIN_MASTER_PASSWORD_LEN} chars): '
        )
        if len(password) < MIN_MASTER_PASSWORD_LEN:
            print(f'Too short (min {MIN_MASTER_PASSWORD_LEN}). Try again.\n')
            continue
        confirm = getpass.getpass('Confirm master password: ')
        if password != confirm:
            print('Passwords do not match. Try again.\n')
            continue

        try:
            save_meta(META_FILE, KDF_ITERATIONS_V2)
            crypto = EncryptionManager(password, salt, iterations=KDF_ITERATIONS_V2)
            encrypted = crypto.encrypt(password)
            save_key_file(KEY_FILE, encrypted)
        except Exception as e:
            print(f'FATAL: cannot save master key: {e}')
            return None

        clear_console()
        print('Master password set successfully.')
        return password


def auth(session: Session) -> bool:
    try:
        session.salt = load_or_create_salt(SALT_FILE)
    except RuntimeError as e:
        print(f'FATAL: {e}')
        sys.exit(1)

    if not os.path.exists(KEY_FILE):
        pw = create_master_password(session.salt)
        if pw is None:
            return False
    else:
        if not os.path.exists(SALT_FILE):
            print('FATAL: key exists but salt missing. Restore from backup.')
            sys.exit(1)

        pw = None
        for attempt in range(1, MAX_LOGIN_ATTEMPTS + 1):
            password = getpass.getpass('\nMaster password: ')
            if verify_master_password(password, session.salt, KEY_FILE):
                pw = password
                break
            print(f'Wrong password ({attempt}/{MAX_LOGIN_ATTEMPTS})')
            time.sleep(min(2 ** attempt, 8))
        else:
            print('Too many failed attempts.')
            return False

    try:
        iterations = get_kdf_iterations(META_FILE)
        crypto = EncryptionManager(pw, session.salt, iterations=iterations)
        storage = Storage(crypto, DATA_FILE)
    except SystemExit:
        raise
    except Exception as e:
        print(f'FATAL: cannot initialize storage: {e}')
        return False

    session.crypto = crypto
    session.storage = storage
    session.auth = True
    session.touch()
    return True


# ---------------------------------------------------------------------------
# Parsing / confirmations
# ---------------------------------------------------------------------------

def split_args(raw: str) -> list[str]:
    try:
        return shlex.split(raw, posix=(platform.system() != 'Windows'))
    except ValueError as e:
        print(f'Parse error: {e}')
        return []


def parse_index(token: str, total: int) -> tuple[Optional[int], Optional[str]]:
    try:
        idx = int(token) - 1
    except ValueError:
        return None, f'Index must be a number, got: {token!r}'
    if total == 0:
        return None, 'Storage is empty'
    if not 0 <= idx < total:
        return None, f'Index out of range (1..{total})'
    return idx, None


def confirm(prompt: str = '(y/n): ') -> bool:
    return input(prompt).strip().lower() == 'y'


def confirm_master_password(session: Session) -> bool:
    pw = getpass.getpass('Enter master password to confirm: ')
    return verify_master_password(pw, session.salt, KEY_FILE)


def copy_to_clipboard(text: str) -> None:
    if not HAS_CLIPBOARD:
        print('(install pyperclip to enable clipboard copying)')
        return
    try:
        pyperclip.copy(text)
        print(f'Password copied to clipboard (clears in {CLIPBOARD_CLEAR_SECONDS}s)')

        def _clear():
            try:
                if pyperclip.paste() == text:
                    pyperclip.copy('')
            except Exception:
                pass

        threading.Timer(CLIPBOARD_CLEAR_SECONDS, _clear).start()
    except Exception as e:
        print(f'Clipboard error: {e}')


# ---------------------------------------------------------------------------
# CLI commands (без изменений)
# ---------------------------------------------------------------------------

def cmd_show(args, session):
    storage = session.storage
    data = storage.get_all()
    if not args:
        print("Usage: sh l | sh <index> [copy]")
        return
    first = args[0].lower()
    if first in ('l', 'list', 'lst') or first.startswith('l'):
        if not data:
            print('Storage is empty')
            return
        for i, rec in enumerate(data, 1):
            print(
                f"{i}. [{safe_str(rec.get('description'))}] "
                f"{safe_str(rec.get('service'))} "
                f"(username: {safe_str(rec.get('username'))})"
            )
        return
    idx, err = parse_index(first, len(data))
    if err:
        print(err)
        return
    rec = data[idx]
    print(f'''
[ Idxs ]  {idx + 1} / {len(data)}
[ Svcs ]  {safe_str(rec.get('service'))}
[ Logn ]  {safe_str(rec.get('username'))}
[ Pass ]  {safe_str(rec.get('password'))}
[ Desc ]  {safe_str(rec.get('description'))}''')
    if 'copy' in args or '-c' in args:
        copy_to_clipboard(rec.get('password', ''))


def cmd_find(args, session):
    if not args:
        print('Please specify search term')
        return
    query = ' '.join(args).lower()
    results = []
    for i, rec in enumerate(session.storage.get_all()):
        hay = ' '.join([
            safe_str(rec.get('service')),
            safe_str(rec.get('username')),
            safe_str(rec.get('description')),
        ]).lower()
        if query in hay:
            results.append((i, rec))
    if not results:
        print('No matches found')
        return
    print(f'\nFound {len(results)} matching records\n')
    for i, rec in results:
        print(
            f"{i + 1}. [{safe_str(rec.get('description'))}] "
            f"{safe_str(rec.get('service'))} "
            f"(username: {safe_str(rec.get('username'))})"
        )


def cmd_add(args, session):
    if len(args) < 3:
        print('Usage: add <service> <username> <password|autogen> [description...]')
        return
    service, username, password = args[0], args[1], args[2]
    if password == 'autogen':
        password = generate_password()
        print(f'Generated password: {password}')
    description = ' '.join(args[3:]) if len(args) > 3 else ''
    session.storage.add({
        'service': service,
        'username': username,
        'password': password,
        'description': description,
    })
    print(f'Added successfully ({service})')


def _apply_update(session, idx, new_record, label):
    old = session.storage.get(idx)
    if old is None:
        print('Record not found')
        return
    print(f'''
Are you sure you want to update index [{idx + 1}]?

[ Svcs ]  {safe_str(old.get('service'))}  ->  {safe_str(new_record.get('service'))}
[ Logn ]  {safe_str(old.get('username'))}  ->  {safe_str(new_record.get('username'))}
[ Pass ]  {safe_str(old.get('password'))}  ->  {safe_str(new_record.get('password'))}
[ Desc ]  {safe_str(old.get('description'))}  ->  {safe_str(new_record.get('description'))}
''')
    if confirm():
        session.storage.update(idx, new_record)
        print(f'{label} updated successfully')
    else:
        print('Update canceled')


def cmd_update(args, session):
    if not args:
        print('Usage: upd <index> [1|2|3|4|service|login|password|description]')
        return
    data = session.storage.get_all()
    idx, err = parse_index(args[0], len(data))
    if err:
        print(err)
        return
    old = data[idx]
    base = {
        'service': old.get('service', ''),
        'username': old.get('username', ''),
        'password': old.get('password', ''),
        'description': old.get('description', ''),
    }
    if len(args) == 1:
        print(f'''Current:
[ Svcs ]  {safe_str(old.get('service'))}
[ Logn ]  {safe_str(old.get('username'))}
[ Pass ]  {safe_str(old.get('password'))}
[ Desc ]  {safe_str(old.get('description'))}
''')
        raw = input('Enter new data "SERVICE USER PASS [DESC]":\n')
        parts = split_args(raw)
        if len(parts) < 3:
            print('Error: invalid format')
            return
        new = dict(base)
        new['service'] = parts[0]
        new['username'] = parts[1]
        new['password'] = generate_password() if parts[2] == 'autogen' else parts[2]
        new['description'] = ' '.join(parts[3:]) if len(parts) > 3 else ''
        _apply_update(session, idx, new, 'Record')
        return
    param = args[1].lower()
    field_map = {
        '1': 'service', 'serv': 'service', 'service': 'service',
        '2': 'username', 'user': 'username', 'login': 'username', 'log': 'username',
        '3': 'password', 'pass': 'password', 'password': 'password',
        '4': 'description', 'desc': 'description', 'description': 'description',
    }
    field = field_map.get(param)
    if field is None:
        print(f'Unknown parameter: {param}')
        return
    prompt = f'Enter new {field} for item {idx + 1} (old: {safe_str(old.get(field))}): '
    value = input(prompt)
    if field == 'password' and value == 'autogen':
        value = generate_password()
        print(f'Generated password: {value}')
    new = dict(base)
    new[field] = value
    _apply_update(session, idx, new, field.capitalize())


def cmd_delete(args, session):
    if not args:
        print('Usage: del <index> | del all')
        return
    if args[0].lower() == 'all':
        total = len(session.storage.get_all())
        if total == 0:
            print('Storage is empty')
            return
        print(f'This will DELETE ALL {total} records.')
        if input('Type DELETE to confirm: ') != 'DELETE':
            print('Canceled')
            return
        session.storage.delete_all()
        print('All records deleted')
        return
    idx, err = parse_index(args[0], len(session.storage.get_all()))
    if err:
        print(err)
        return
    rec = session.storage.get(idx)
    label = safe_str(rec.get('description')) if rec else ''
    prompt = f"Delete {'[' + label + '] ' if label else ''}[{idx + 1}]?\n(y/n): "
    if confirm(prompt):
        session.storage.delete(idx)
        print('Removal completed')


def cmd_autogen(args, session):
    try:
        if len(args) == 0:
            print(generate_password())
        elif len(args) == 1:
            print(generate_password(int(args[0])))
        else:
            length = int(args[0])
            count = int(args[1])
            for _ in range(count):
                print(generate_password(length))
    except ValueError as e:
        print(f'Error: {e}')


def cmd_export(args, session):
    if not args:
        print('Usage: export <path>')
        return
    if not confirm_master_password(session):
        print('Wrong password! Export canceled.')
        return
    ok, msg = session.storage.export_to_file(args[0])
    print(msg)


def cmd_import(args, session):
    if not args:
        print('Usage: import <path>')
        return
    if not confirm_master_password(session):
        print('Wrong password! Import canceled.')
        return
    print(f'Importing from: {args[0]}')
    if not confirm('This will add records to your storage. Continue?\n(y/n): '):
        print('Import canceled.')
        return
    ok, msg = session.storage.import_from_file(args[0])
    print(msg)


def cmd_salt(args, session):
    if not confirm_master_password(session):
        print('Wrong password! Canceled.')
        return
    if not os.path.exists(SALT_FILE):
        print('Salt file not found')
        return
    with open(SALT_FILE, 'rb') as f:
        salt = f.read()
    print(f'Salt (hex):    {salt.hex()}')
    print(f'Salt (base64): {base64.b64encode(salt).decode()}')
    print(f'Salt length:   {len(salt)} bytes')


def cmd_stats(args, session):
    data = session.storage.get_all()
    size = os.path.getsize(DATA_FILE) if os.path.exists(DATA_FILE) else 0
    mtime = time.strftime(
        '%Y-%m-%d %H:%M:%S',
        time.localtime(os.path.getmtime(DATA_FILE))
    ) if os.path.exists(DATA_FILE) else 'n/a'
    print(f'''
Records:       {len(data)}
File size:     {size} bytes
Last modified: {mtime}
Storage ver:   {STORAGE_VERSION}
KDF iters:     {get_kdf_iterations(META_FILE)}
Clipboard:     {'available' if HAS_CLIPBOARD else 'unavailable (pip install pyperclip)'}
''')


HELP_TEXT = '''
Commands:

  sh l                          - show all records
  sh <index> [copy]             - show a record; 'copy' puts password to clipboard

  find <text>                   - search by service / username / description

  autogen [length] [count]      - password generator (default length 18)

  add <service> <user> <pass|autogen> [description...]

  upd <index>                   - update interactively
  upd <index> <field>           - update one field

  del <index>                   - delete a record
  del all                       - delete ALL records (requires 'DELETE')

  export <path>                 - export all records to plaintext CSV
  import <path>                 - import records from CSV

  stats                         - show storage statistics
  salt                          - show salt (hex / base64)

  help / h / ?                  - this reference

  l!                            - log out
  exit / quit / q!              - exit
'''.strip('\n')


def cmd_help(args, session):
    print(HELP_TEXT)


COMMANDS = {
    'sh': cmd_show, 'show': cmd_show,
    'find': cmd_find,
    'add': cmd_add,
    'upd': cmd_update, 'update': cmd_update,
    'del': cmd_delete, 'delete': cmd_delete,
    'autogen': cmd_autogen, 'ag': cmd_autogen,
    'export': cmd_export, 'import': cmd_import,
    'salt': cmd_salt, 'stats': cmd_stats,
    'help': cmd_help, 'h': cmd_help, '?': cmd_help,
}


def dispatch(raw: str, session: Session) -> Optional[str]:
    raw = raw.strip()
    if not raw:
        print("Type 'help' for reference")
        return None
    if raw in ('exit', 'quit', 'q!'):
        return 'exit'
    if raw == 'l!':
        session.logout()
        return None
    parts = split_args(raw)
    if not parts:
        return None
    cmd = parts[0].lower()
    handler = COMMANDS.get(cmd)
    if handler is None:
        print(f"Unknown command: '{cmd}'. Type 'help' for reference")
        return None
    try:
        handler(parts[1:], session)
    except KeyboardInterrupt:
        print('\n(canceled)')
    except Exception as e:
        print(f'Error while executing "{cmd}": {e}')
    return None


def main() -> None:
    session = Session()
    threading.Thread(
        target=inactivity_monitor, args=(session,), daemon=True
    ).start()
    while True:
        if session.expired:
            session.expired = False
            session.storage = None
            continue
        if not session.auth:
            clear_console()
            if not auth(session):
                input('\nPress Enter to retry, Ctrl+C to exit...')
                continue
            clear_console()
            continue
        try:
            raw = input('\n>> ')
        except (EOFError, KeyboardInterrupt):
            print('\nBye.')
            break
        session.touch()
        clear_console()
        if dispatch(raw, session) == 'exit':
            session.logout()
            print('Bye.')
            break


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nBye.')
        sys.exit(0)