import base64
import csv
import getpass
import json
import os
import platform
import secrets
import shlex
import string
import sys
import tempfile
import threading
import time
from typing import Optional

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
# Constants
# ---------------------------------------------------------------------------

KEY_FILE = '.nimbus_key'
SALT_FILE = '.nimbus_salt'
DATA_FILE = '.nimbus'
AUDIT_FILE = '.nimbus_audit.log'

KDF_ITERATIONS = 391827
SESSION_TIMEOUT = 300
MAX_LOGIN_ATTEMPTS = 3
CLIPBOARD_CLEAR_SECONDS = 30
STORAGE_VERSION = 2


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


def audit(action: str, detail: str = '') -> None:
    try:
        ts = time.strftime('%Y-%m-%d %H:%M:%S')
        with open(AUDIT_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{ts}\t{action}\t{detail}\n")
    except Exception:
        pass


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
# Encryption
# ---------------------------------------------------------------------------

class EncryptionManager:
    def __init__(self, password: str, salt: bytes, iterations: int = KDF_ITERATIONS):
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

    def encrypt(self, data: str) -> str:
        return base64.urlsafe_b64encode(
            self.cipher.encrypt(data.encode('utf-8'))
        ).decode('ascii')

    def decrypt(self, data: str) -> str:
        return self.cipher.decrypt(
            base64.urlsafe_b64decode(data)
        ).decode('utf-8')


# ---------------------------------------------------------------------------
# Key/salt
# ---------------------------------------------------------------------------

def load_or_create_salt() -> bytes:
    if os.path.exists(SALT_FILE):
        with open(SALT_FILE, 'rb') as f:
            salt = f.read()
        if len(salt) != 16:
            raise RuntimeError(
                f'Corrupted {SALT_FILE}: expected 16 bytes, got {len(salt)}'
            )
        return salt
    salt = secrets.token_bytes(16)
    with open(SALT_FILE, 'wb') as f:
        f.write(salt)
    try:
        os.chmod(SALT_FILE, 0o600)
    except Exception:
        pass
    return salt


def verify_master_password(password: str, salt: bytes) -> Optional[str]:
    if not os.path.exists(KEY_FILE):
        return None
    try:
        with open(KEY_FILE, 'r', encoding='utf-8') as f:
            encrypted = f.read().strip()
        if not encrypted:
            return None
        crypto = EncryptionManager(password, salt)
        return crypto.decrypt(encrypted)
    except (InvalidToken, ValueError, Exception):
        return None


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

class Storage:
    def __init__(self, crypto: EncryptionManager):
        self.file = DATA_FILE
        self.crypto = crypto
        self.data: list = self._load()

    def _load(self) -> list:
        if not os.path.exists(self.file):
            return []
        with open(self.file, 'r', encoding='utf-8') as f:
            encrypted = f.read().strip()
        if not encrypted:
            return []
        try:
            payload = json.loads(self.crypto.decrypt(encrypted))
        except Exception as e:
            print(f'\nFATAL: cannot decrypt {self.file}: {e}')
            print('Restore from backup or check master password / salt.')
            sys.exit(1)

        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and 'records' in payload:
            return payload['records']
        print(f'\nFATAL: unknown storage format in {self.file}')
        sys.exit(1)

    def _save(self) -> None:
        payload = {'version': STORAGE_VERSION, 'records': self.data}
        encrypted = self.crypto.encrypt(
            json.dumps(payload, ensure_ascii=False)
        )
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix='.nimbus_tmp_', dir='.', text=True
        )
        try:
            with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
                f.write(encrypted)
            try:
                os.chmod(tmp_path, 0o600)
            except Exception:
                pass
            os.replace(tmp_path, self.file)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    def get_all(self) -> list:
        return self.data

    def get(self, index: int) -> Optional[dict]:
        if 0 <= index < len(self.data):
            return self.data[index]
        return None

    def add(self, record: dict) -> None:
        self.data.append(record)
        self._save()
        audit('add', record.get('service', ''))

    def update(self, index: int, record: dict) -> bool:
        if 0 <= index < len(self.data):
            self.data[index] = record
            self._save()
            audit('update', record.get('service', ''))
            return True
        return False

    def delete(self, index: int) -> bool:
        if 0 <= index < len(self.data):
            name = self.data[index].get('service', '')
            del self.data[index]
            self._save()
            audit('delete', name)
            return True
        return False

    def delete_all(self) -> int:
        count = len(self.data)
        self.data = []
        self._save()
        audit('delete_all', str(count))
        return count

    def export_to_file(self, filepath: str) -> tuple[bool, str]:
        try:
            full_path = os.path.expanduser(filepath)
            directory = os.path.dirname(full_path) or '.'
            if not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
                print(f'Created directory: {directory}')

            if not os.access(directory, os.W_OK):
                return False, f'No write permission in directory: {directory}'

            tmp_fd, tmp_path = tempfile.mkstemp(
                prefix='.nimbus_export_', dir=directory, text=True
            )
            try:
                with os.fdopen(tmp_fd, 'w', encoding='utf-8', newline='') as f:
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

            audit('export', f'{len(self.data)} records -> {full_path}')
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

            with open(full_path, 'r', encoding='utf-8', newline='') as f:
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

            self.data.extend(new_records)
            self._save()
            audit('import', f'{len(new_records)} records')
            return True, (
                f'Imported {len(new_records)} records. '
                f'Errors: {len(errors)}'
            )
        except Exception as e:
            return False, f'Import failed: {e}'


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class Session:
    def __init__(self):
        self.auth = False
        self.master_password: Optional[str] = None
        self.storage: Optional[Storage] = None
        self.salt: Optional[bytes] = None
        self.last_action = time.time()
        self.expired = False

    def touch(self):
        self.last_action = time.time()

    def logout(self):
        self.auth = False
        self.master_password = None
        self.storage = None
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
# Authentication
# ---------------------------------------------------------------------------

def create_master_password(salt: bytes) -> Optional[str]:
    print('You need to create a master password.\n')
    while True:
        password = getpass.getpass('Enter master password (min 4 chars): ')
        if len(password) < 4:
            print('Too short. Try again.\n')
            continue
        confirm = getpass.getpass('Confirm master password: ')
        if password != confirm:
            print('Passwords do not match. Try again.\n')
            continue

        crypto = EncryptionManager(password, salt)
        encrypted = crypto.encrypt(password)
        with open(KEY_FILE, 'w', encoding='utf-8') as f:
            f.write(encrypted)
        try:
            os.chmod(KEY_FILE, 0o600)
        except Exception:
            pass

        clear_console()
        print('Master password set successfully.')
        audit('master_password_created')
        return password


def auth(session: Session) -> bool:
    try:
        session.salt = load_or_create_salt()
    except RuntimeError as e:
        print(f'FATAL: {e}')
        sys.exit(1)

    if not os.path.exists(KEY_FILE):
        pw = create_master_password(session.salt)
        if pw is None:
            return False
        session.master_password = pw
    else:
        if not os.path.exists(SALT_FILE):
            print('FATAL: key exists but salt missing. Restore from backup.')
            sys.exit(1)

        for attempt in range(1, MAX_LOGIN_ATTEMPTS + 1):
            password = getpass.getpass('\nMaster password: ')
            verified = verify_master_password(password, session.salt)
            if verified is not None:
                session.master_password = verified
                break
            print(f'Wrong password ({attempt}/{MAX_LOGIN_ATTEMPTS})')
            time.sleep(min(2 ** attempt, 8))
        else:
            print('Too many failed attempts.')
            audit('auth_failed')
            return False

    try:
        crypto = EncryptionManager(session.master_password, session.salt)
        session.storage = Storage(crypto)
    except SystemExit:
        raise
    except Exception as e:
        print(f'FATAL: cannot initialize storage: {e}')
        return False

    session.auth = True
    session.touch()
    audit('auth_ok')
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
    return verify_master_password(pw, session.salt) is not None


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
# Commands
# ---------------------------------------------------------------------------

def cmd_show(args: list[str], session: Session) -> None:
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


def cmd_find(args: list[str], session: Session) -> None:
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


def cmd_add(args: list[str], session: Session) -> None:
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


def _apply_update(session: Session, idx: int, new_record: dict, label: str) -> None:
    old = session.storage.get(idx)
    assert old is not None
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


def cmd_update(args: list[str], session: Session) -> None:
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


def cmd_delete(args: list[str], session: Session) -> None:
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


def cmd_autogen(args: list[str], session: Session) -> None:
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


def cmd_export(args: list[str], session: Session) -> None:
    if not args:
        print('Usage: export <path>')
        return
    if not confirm_master_password(session):
        print('Wrong password! Export canceled.')
        return
    ok, msg = session.storage.export_to_file(args[0])
    print(msg)


def cmd_import(args: list[str], session: Session) -> None:
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


def cmd_salt(args: list[str], session: Session) -> None:
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


def cmd_stats(args: list[str], session: Session) -> None:
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
Clipboard:     {'available' if HAS_CLIPBOARD else 'unavailable (pip install pyperclip)'}
''')


HELP_TEXT = '''
Commands:

  sh l                          - show all records
  sh <index> [copy]             - show a record; 'copy' puts password to clipboard

  find <text>                   - search by service / username / description

  autogen [length] [count]      - password generator (default length 18)

  add <service> <user> <pass|autogen> [description...]
                                - add a record ('autogen' generates a password)

  upd <index>                   - update interactively
  upd <index> <field>           - update one field:
                                    field = 1|service | 2|login | 3|pass | 4|desc
                                  (password field supports 'autogen')

  del <index>                   - delete a record
  del all                       - delete ALL records (requires 'DELETE')

  export <path>                 - export all records to plaintext CSV (semicolon)
                                  file is created with 0600 permissions
                                  examples:
                                    export backup.txt
                                    export ~/Desktop/backup.txt
                                    export /var/usr/backup.txt
                                    export D:/Users/backup.txt

  import <path>                 - import records from CSV (semicolon)

  stats                         - show storage statistics
  salt                          - show salt (hex / base64)

  help / h / ?                  - this reference

  l!                            - log out
  exit / quit / q!              - exit
'''.strip('\n')


def cmd_help(args: list[str], session: Session) -> None:
    print(HELP_TEXT)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

COMMANDS = {
    'sh': cmd_show,
    'show': cmd_show,
    'find': cmd_find,
    'add': cmd_add,
    'upd': cmd_update,
    'update': cmd_update,
    'del': cmd_delete,
    'delete': cmd_delete,
    'autogen': cmd_autogen,
    'ag': cmd_autogen,
    'export': cmd_export,
    'import': cmd_import,
    'salt': cmd_salt,
    'stats': cmd_stats,
    'help': cmd_help,
    'h': cmd_help,
    '?': cmd_help,
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

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