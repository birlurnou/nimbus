import getpass
import platform
import threading
import time
import sys
import os
import configparser
import json
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import re
import secrets

def clear_console():
    os.system('cls' if platform.system() == 'Windows' else 'clear')

def inactivity_monitor():
    global AUTH, last_action_time, session_expired, MASTER_PASSWORD
    while True:
        time.sleep(1)
        if AUTH and (time.time() - last_action_time > time_to_inactivity):
            AUTH = False
            session_expired = True
            MASTER_PASSWORD = None
            clear_console()
            print('\nSession expired due to inactivity\n')

# -----------------------------------------------------------------
# config
# -----------------------------------------------------------------

MASTER_PASSWORD = None
AUTH = False
session_expired = False
last_action_time = time.time()
time_to_inactivity = 60
KEY_FILE = '.nimbus_key'
SALT_FILE = '.nimbus_salt'
SALT = None
# SALT = bytes.fromhex('')

# -----------------------------------------------------------------
# encryption
# -----------------------------------------------------------------

class EncryptionManager:
    def __init__(self, password, salt=None):
        if salt is None:
            salt = SALT
        self.salt = salt # SALT
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self.salt,
            iterations=391827
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        self.cipher = Fernet(key)

    def encrypt(self, data):
        return base64.urlsafe_b64encode(
            self.cipher.encrypt(data.encode())
        ).decode()

    def decrypt(self, data):
        return self.cipher.decrypt(
            base64.urlsafe_b64decode(data)
        ).decode()

# -----------------------------------------------------------------
# key storage
# -----------------------------------------------------------------

def get_master_password():
    global MASTER_PASSWORD, SALT

    if os.path.exists(KEY_FILE):
        return None

    else:
        print('You need to create a master password.\n')

        if os.path.exists(SALT_FILE):
            with open(SALT_FILE, 'rb') as f:
                SALT = f.read()
        else:
            SALT = secrets.token_bytes(16)
            with open(SALT_FILE, 'wb') as f:
                f.write(SALT)

        while True:
            password = getpass.getpass('Enter master password (min 4 chars): ')
            confirm = getpass.getpass('Confirm master password: ')

            if len(password) < 4:
                clear_console()
                print('Passwords too short. Try again.\n')
                continue

            if password != confirm:
                print('Passwords do not match. Try again.\n')
                clear_console()
                continue

            crypto = EncryptionManager(password, SALT)
            encrypted = crypto.encrypt(password)

            with open(KEY_FILE, 'w', encoding='utf-8') as f:
                f.write(encrypted)

            MASTER_PASSWORD = password
            clear_console()
            print('Master password set successfully.')
            return MASTER_PASSWORD

# -----------------------------------------------------------------
# storage
# -----------------------------------------------------------------

class Storage:
    def __init__(self, password):
        self.file = '.nimbus'
        self.crypto = EncryptionManager(password, SALT)
        self.data = self._load()

    def _load(self):
        if not os.path.exists(self.file):
            return []

        try:
            with open(self.file, 'r', encoding='utf-8') as f:
                encrypted = f.read().strip()
                if not encrypted:
                    return []
                return json.loads(self.crypto.decrypt(encrypted))
        except Exception:
            return []

    def _save(self):
        with open(self.file, 'w', encoding='utf-8') as f:
            f.write(self.crypto.encrypt(json.dumps(self.data, ensure_ascii=False)))

    def get_all(self):
        return self.data

    def add(self, record):
        self.data.append(record)
        self._save()

    def update(self, index, record):
        if 0 <= index < len(self.data):
            self.data[index] = record
            self._save()

    def delete(self, index):
        if 0 <= index < len(self.data):
            del self.data[index]
            self._save()

    def save(self):
        self._save()

    def export_to_file(self, filepath):
        try:
            full_path = os.path.expanduser(filepath)

            directory = os.path.dirname(full_path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory)
                print(f'Created directory: {directory}')

            if os.path.exists(full_path):
                if not os.access(full_path, os.W_OK):
                    return False, f'No write permission for: {full_path}'
            else:
                if directory and not os.access(directory, os.W_OK):
                    return False, f'No write permission in directory: {directory}'

            def clean_string(text):
                if not text:
                    return ''
                return text.replace('\n', ' ').replace('\r', ' ').replace('\r\n', ' ').strip()

            with open(full_path, 'w', encoding='utf-8') as f:
                for record in self.data:
                    service = clean_string(record.get('service', ''))
                    username = clean_string(record.get('username', ''))
                    password = clean_string(record.get('password', ''))
                    description = clean_string(record.get('description', ''))

                    line = f"{service};{username};{password};{description}\n"
                    f.write(line)

            return True, f'Successfully exported {len(self.data)} records to: {full_path}'
        except PermissionError as e:
            return False, f'Permission denied: {str(e)}'
        except Exception as e:
            return False, f'Export failed: {str(e)}'

    def import_from_file(self, filepath):
        try:
            full_path = os.path.expanduser(filepath)

            if not os.path.exists(full_path):
                return False, f'File not found: {full_path}'

            imported_count = 0
            errors = []

            with open(full_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    parts = line.split(';')

                    if len(parts) < 3:
                        errors.append(f'Line {line_num}: Invalid format (need at least 3 fields)')
                        continue

                    service = parts[0].strip()
                    username = parts[1].strip()
                    password = parts[2].strip()
                    description = parts[3].strip() if len(parts) > 3 else ''

                    if not service or not username or not password:
                        errors.append(f'Line {line_num}: Empty required fields')
                        continue

                    record = {
                        'service': service,
                        'username': username,
                        'password': password,
                        'description': description
                    }
                    self.data.append(record)
                    imported_count += 1

            if imported_count > 0:
                self._save()
                return True, f"Successfully imported {imported_count} records. Errors: {len(errors)}"
            else:
                return False, f"No records imported. Errors: {len(errors)}"

        except Exception as e:
            return False, f"Import failed: {str(e)}"

# -----------------------------------------------------------------
# auth
# -----------------------------------------------------------------

def auth():
    global AUTH, last_action_time, session_expired, MASTER_PASSWORD, SALT

    if MASTER_PASSWORD is None:
        if os.path.exists(KEY_FILE):
            if os.path.exists(SALT_FILE):
                with open(SALT_FILE, 'rb') as f:
                    SALT = f.read()
            else:
                SALT = secrets.token_bytes(16)
                with open(SALT_FILE, 'wb') as f:
                    f.write(SALT)

            with open(KEY_FILE, 'r', encoding='utf-8') as f:
                encrypted = f.read().strip()

            password = getpass.getpass('\nMaster password: ')

            crypto = EncryptionManager(password, SALT)

            try:
                MASTER_PASSWORD = crypto.decrypt(encrypted)
            except:
                print('Wrong password')
                return None
        else:
            MASTER_PASSWORD = get_master_password()
            if MASTER_PASSWORD is None:
                return None

    storage = Storage(MASTER_PASSWORD)
    AUTH = True
    last_action_time = time.time()
    session_expired = False
    return storage

# -----------------------------------------------------------------
# main func
# -----------------------------------------------------------------

def main(action, storage):

    clear_console()

    # storage
    if storage is None:
        print('Error: Storage not initialized')
        return

    # pass
    if not action:
        return print("Type 'help' for reference")

    action_splits = action.strip().split(' ')
    action_len = len(action_splits)

    # ---------- #
    #  show all  #
    # ---------- #

    if action_splits[0][0:2] == 'sh' and action_splits[1][0] == 'l':

        services = storage.get_all()
        i = 0
        for service in services:
            print(f'{i+1}. [{service['description'].replace('\n', '')}] {service['service'].replace('\n', '')} (username: {service['username'].replace('\n', '')})')
            i += 1
            if i % 10 == 0 and (action_len < 3 and action_splits[-1] != '-a'):
                inp = input()
                if inp == 'q':
                    return
                clear_console()

    # ---------- #
    #  show idx  #
    # ---------- #

    elif action_splits[0][0:2] == 'sh' and isinstance(int(action_splits[1]), int):

        service = storage.get_all()[int(action_splits[1])-1]
        print(
f'''
[ Idxs ]  {int(action_splits[1])}
[ Svcs ]  {service['service'].replace('\n', '')}
[ Logn ]  {service['username'].replace('\n', '')}
[ Pass ]  {service['password'].replace('\n', '')}
[ Desc ]  {service['description'].replace('\n', '')}''')

    # ------- #
    #   add   #
    # ------- #

    elif action.startswith('add '):
        if action_len > 3:
            service = action_splits[1]
            username = action_splits[2]
            password = action_splits[3]
        else:
            return print("Error. Type 'help' for reference")
        description = action_splits[4] if action_len > 4 else ''

        record = {'service': service, 'username': username, 'password': password, 'description': description}
        storage.add(record)
        clear_console()
        print(f'\nAdded successfully ({service})')
        # storage = Storage(password)
        # return storage

    # ------ #
    # update #
    # ------ #

    elif action.startswith('upd '):
        update_index = int(action_splits[1])-1
        update_item = storage.get_all()[update_index]

        # action_len == 2
        if action_len == 2:
            print(f'''Updated item:
[ Svcs ]  {update_item['service'].replace('\n', '')}
[ Logn ]  {update_item['username'].replace('\n', '')}
[ Pass ]  {update_item['password'].replace('\n', '')}
[ Desc ]  {update_item['description'].replace('\n', '')}
''')
            new_record = input('Enter new data in the format "SERVICE USER PASS [DESC]" :\n')
            clear_console()
            new_record_splits = new_record.strip().split(' ')
            new_record_len = len(new_record_splits)
            if new_record_len > 2:
                service = new_record_splits[0]
                username = new_record_splits[1]
                password = new_record_splits[2]
            else:
                return print("Error: invalid format")
            description = new_record_splits[3] if new_record_len > 3 else ''

            record = {'service': service, 'username': username, 'password': password, 'description': description}
            answer = input(f'''Are you sure you want to update index [{update_index+1}]?: 
            
[ Svcs ]  {update_item['service']}  ->  {record['service']}

[ Logn ]  {update_item['username']}  ->  {record['username']}

[ Pass ]  {update_item['password']}  ->  {record['password']}

[ Desc ]  {update_item['description']}  ->  {record['description']}

(y/n): ''')

            if answer == 'y':
                storage.update(update_index, record)
                print('\nUpdated successfully')

        # action_len == 3
        elif action_len == 3:

            # service
            if action_splits[-1][0:4] == 'serv' or int(action_splits[-1]) == 1:
                new_service = input(f'Enter new service for item {update_index+1}: ')
                record = {'service': new_service,
                          'username': update_item['username'],
                          'password': update_item['password'],
                          'description': update_item['description']}
                clear_console()
                answer = input(f'''
Are you sure you want to update index [{update_index + 1}]?

[ Svcs ]  {update_item['service']}  ->  {record['service']}
[ Logn ]  {update_item['username']}  ->  {update_item['username']}
[ Pass ]  {update_item['password']}  ->  {update_item['password']}
[ Desc ]  {update_item['description']}  ->  {update_item['description']}

(y/n): ''')
                if answer == 'y':
                    storage.update(update_index, record)
                    print('\nService updated successfully')
                else:
                    clear_console()
                    print('\nUpdate canceled')

            # username
            elif action_splits[-1][0:4] == 'user' or action_splits[-1][0:3] == 'log' or int(action_splits[-1]) == 2:
                new_username = input(f'Enter new username (login) for item {update_index + 1}: ')
                record = {'service': update_item['service'],
                          'username': new_username,
                          'password': update_item['password'],
                          'description': update_item['description']}
                clear_console()
                answer = input(f'''
Are you sure you want to update index [{update_index + 1}]?

[ Svcs ]  {update_item['service']}  ->  {update_item['service']}
[ Logn ]  {update_item['username']}  ->  {record['username']}
[ Pass ]  {update_item['password']}  ->  {update_item['password']}
[ Desc ]  {update_item['description']}  ->  {update_item['description']}

(y/n): ''')
                if answer == 'y':
                    storage.update(update_index, record)
                    print('\nUsername updated successfully')
                else:
                    clear_console()
                    print('\nUpdate canceled')

            # password
            elif action_splits[-1][0:4] == 'pass' or int(action_splits[-1]) == 3:
                new_password = input(f'Enter new password for item {update_index + 1}: ')
                record = {'service': update_item['service'],
                          'username': update_item['username'],
                          'password': new_password,
                          'description': update_item['description']}
                clear_console()
                answer = input(f'''
Are you sure you want to update index [{update_index + 1}]?

[ Svcs ]  {update_item['service']}  ->  {update_item['service']}
[ Logn ]  {update_item['username']}  ->  {update_item['username']}
[ Pass ]  {update_item['password']}  ->  {record['password']}
[ Desc ]  {update_item['description']}  ->  {update_item['description']}

(y/n): ''')
                if answer == 'y':
                    storage.update(update_index, record)
                    print('\nService updated successfully')
                else:
                    clear_console()
                    print('\nUpdate canceled')

            # description
            elif action_splits[-1][0:4] == 'desc' or int(action_splits[-1]) == 4:
                new_description = input(f'Enter new description for item {update_index + 1}: ')
                record = {'service': update_item['service'],
                          'username': update_item['username'],
                          'password': update_item['password'],
                          'description': new_description}
                clear_console()
                answer = input(f'''
Are you sure you want to update index [{update_index + 1}]?

[ Svcs ]  {update_item['service']}  ->  {update_item['service']}
[ Logn ]  {update_item['username']}  ->  {update_item['username']}
[ Pass ]  {update_item['password']}  ->  {update_item['password']}
[ Desc ]  {update_item['description']}  ->  {record['description']}

(y/n): ''')
                if answer == 'y':
                    storage.update(update_index, record)
                    print('\nDescription updated successfully')
                else:
                    clear_console()
                    print('\nUpdate canceled')

        else:
            return print("Error. Type 'help' for reference")

    # ------ #
    # delete #
    # ------ #

    elif action.startswith('del '):
        if action_len == 2:
            delete_index = int(action_splits[-1])-1
            delete_item = storage.get_all()[delete_index]
            answer = input(f'Are you sure you want to delete{' ' + delete_item['description'] if delete_item['description'] != '' else ''} [{delete_index+1}]?\n(y/n): ')
            if answer == 'y':
                storage.delete(delete_index)
                clear_console()
                print('Removal completed')
        else:
            return print("Error. Type 'help' for reference")


    elif action in ['help', '?', 'h']:
        print('''
    Commands:
    
      sh(-ow) l(-ist) [-a]          -  show all records
      
      sh(-ow) <index>               -  show a specific field of a record
      
      find <text>                   -  search
      
      add service user pass [desc]  -  add a record
      
      upd <index> [param]           -  update a record, param in [1, 2, 3, 4]
      
      del <index>                   -  delete a record
      
      export <path/to/file>         -  export all records to a text file
                                       Format: service;username;password;description
      
      import <path/to/file>         -  import records from a text file
                                       Format: service;username;password;description
      
      salt                          - show salt
      
      help / h / ?                  -  reference
      
      l!                            - log out
      
      exit / quit / q!              - exit''')

    # ---------- #
    #    find    #
    # ---------- #

    elif action.startswith('find '):
        query = action[5:].strip()
        if not query:
            print('Please specify search term')
            return

        services = storage.get_all()
        results = []
        for idx, service in enumerate(services):
            desc = service.get('description', '')
            srv = service.get('service', '')
            usr = service.get('username', '')
            if (query.lower() in desc.lower() or
                    query.lower() in srv.lower() or
                    query.lower() in usr.lower()):
                results.append((idx, service))

        if not results:
            print('No matches found')
            return

        clear_console()
        print(f"\nFound {len(results)} matching records\n")
        for idx, service in results:
            print(
                f"{idx + 1}. [{service['description'].replace('\n', '')}] {service['service'].replace('\n', '')} (username: {service['username'].replace('\n', '')})")
            print()

    # ---------- #
    #   export   #
    # ---------- #

    elif action.startswith('export '):
        export_path = action[7:].strip()

        if not export_path:
            print('Error: Please specify export path')
            print('Example: export ~/Desktop/backup.txt')
            print('Example: export /var/usr/backup.txt')
            print('Example: export D:/Users/backup.txt')
            return

        password = getpass.getpass('Enter master password to confirm: ')

        try:
            crypto = EncryptionManager(password)
            if os.path.exists(KEY_FILE):
                with open(KEY_FILE, 'r', encoding='utf-8') as f:
                    encrypted = f.read().strip()
                    crypto.decrypt(encrypted)
        except:
            clear_console()
            print('Wrong password! Export canceled.')
            return

        clear_console()
        success, message = storage.export_to_file(export_path)
        print(message)

    # ---------- #
    #   import   #
    # ---------- #

    elif action.startswith('import '):
        import_path = action[7:].strip()

        if not import_path:
            print('Error: Please specify import file path')
            print('Example: import ~/Desktop/backup.txt')
            return

        password = getpass.getpass('Enter master password to confirm: ')

        try:
            crypto = EncryptionManager(password)
            if os.path.exists(KEY_FILE):
                with open(KEY_FILE, 'r', encoding='utf-8') as f:
                    encrypted = f.read().strip()
                    crypto.decrypt(encrypted)
        except:
            clear_console()
            print('Wrong password! Import canceled.')
            return

        clear_console()

        print(f'Importing from: {import_path}')
        answer = input('This will add records to your storage. Continue?\n(y/n): ')

        clear_console()

        if answer.lower() != 'y':
            print('Import canceled.')
            return

        success, message = storage.import_from_file(import_path)
        print(message)

    # ---------- #
    #    salt    #
    # ---------- #

    elif 'salt' in action :

        password = getpass.getpass('Enter master password to confirm: ')

        try:
            crypto = EncryptionManager(password)
            if os.path.exists(KEY_FILE):
                with open(KEY_FILE, 'r', encoding='utf-8') as f:
                    encrypted = f.read().strip()
                    crypto.decrypt(encrypted)
        except:
            clear_console()
            print('Wrong password! Import canceled.')
            return

        clear_console()

        if os.path.exists(SALT_FILE):
            with open(SALT_FILE, 'rb') as f:
                salt = f.read()
            print(f'Salt (hex): {salt.hex()}')
            print(f'Salt (base64): {base64.b64encode(salt).decode()}')
            print(f'Salt length: {len(salt)} bytes')
        else:
            print('Salt file not found')

    # ---------- #
    #    exit    #
    # ---------- #

    elif action in ['exit', 'quit', 'q!']:
        return 'exit'

    # ---------- #
    #   logout   #
    # ---------- #

    elif action == 'l!':
        global AUTH, session_expired, MASTER_PASSWORD
        AUTH = False
        session_expired = False
        MASTER_PASSWORD = None
        return

    else: print(f"Unknown command: '{action}'. Type 'help' for reference")

# -----------------------------------------------------------------
# start
# -----------------------------------------------------------------

monitor_thread = threading.Thread(target=inactivity_monitor, daemon=True)
monitor_thread.start()

while True:
    if session_expired:
        session_expired = False
        continue
    if not AUTH:
        clear_console()
        storage = auth()
        clear_console()
        if storage is None:
            continue
        continue
    try:
        action = input('\n>> ')
        last_action_time = time.time()
        response = main(action, storage)
        if response == 'exit':
            break
    except:
        pass