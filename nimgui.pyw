import os
import sys
import json
import time
import platform
import threading
from typing import Optional

from PyQt6.QtCore import (
    Qt, QTimer, QSortFilterProxyModel, QAbstractTableModel,
    QModelIndex, pyqtSignal, QRect, QSize, QEvent, QRectF
)
from PyQt6.QtGui import (
    QColor, QPainter, QPen, QFont, QMouseEvent, QIcon, QPixmap,
    QAction, QIntValidator
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QLineEdit, QPushButton, QFrame,
    QDialog, QFormLayout, QButtonGroup, QMessageBox,
    QFileDialog, QTableView, QSystemTrayIcon, QMenu,
    QAbstractItemView, QStyledItemDelegate, QStyle,
    QHeaderView, QStackedWidget, QTabWidget, QPlainTextEdit
)

import nimbus
import nimbus_sync


try:
    if getattr(sys, "frozen", False):
        _SCRIPT_DIR = os.path.dirname(sys.executable)
    else:
        _SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    if _SCRIPT_DIR and os.path.isdir(_SCRIPT_DIR):
        os.chdir(_SCRIPT_DIR)
except Exception as e:
    print(f"[startup] chdir error: {e}")


_lock_file = None


def acquire_single_instance_lock() -> bool:
    global _lock_file
    try:
        _lock_file = open('.nimbus.lock', 'w')
        if platform.system() == "Windows":
            import msvcrt
            msvcrt.locking(_lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(_lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except (OSError, IOError) as e:
        print(f"[lock] {e}")
        return False


LAST_USER_FILE = ".nimbus_last_user"

DEFAULT_SETTINGS = {
    "language": "en",
    "theme": "system",
    "autostart": True,
    "start_minimized": True,
    "password_length": 18,
    "clipboard_timeout": 30,
    "session_timeout": 300,
    "confirm_delete": True,
    "minimize_to_tray": True,
    "github_url": "",
    "github_token": "",
    "github_enabled": False,
    "github_branch": "main",
    "github_sync_interval": 600,
}


def load_last_user():
    if os.path.exists(LAST_USER_FILE):
        try:
            with open(LAST_USER_FILE, 'r', encoding='utf-8') as f:
                return f.read().strip() or None
        except Exception:
            pass
    return None


def save_last_user(username):
    try:
        nimbus._atomic_write_text(LAST_USER_FILE, username)
    except Exception:
        pass


def load_settings(path):
    if not path or not os.path.exists(path):
        return dict(DEFAULT_SETTINGS)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        result = dict(DEFAULT_SETTINGS)
        for k, v in data.items():
            if k in DEFAULT_SETTINGS:
                result[k] = v
        return result
    except Exception:
        return dict(DEFAULT_SETTINGS)


def save_settings(path, data):
    if not path:
        return
    try:
        json_str = json.dumps(data, indent=2, ensure_ascii=False)
        nimbus._atomic_write_text(path, json_str)
    except Exception as e:
        print(f"[settings] save error: {e}")


class SettingsManager:
    def __init__(self, path=None):
        self.path = path
        self.data = load_settings(path) if path else dict(DEFAULT_SETTINGS)

    def reload_for_user(self, path):
        self.path = path
        self.data = load_settings(path) if path else dict(DEFAULT_SETTINGS)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        save_settings(self.path, self.data)

    def update(self, updates):
        self.data.update(updates)
        save_settings(self.path, self.data)


_init_last_user = load_last_user()
_init_settings_path = None
if _init_last_user:
    _candidate = nimbus.UserPaths(_init_last_user).settings_file
    if os.path.isdir(nimbus.UserPaths(_init_last_user).user_dir):
        _init_settings_path = _candidate

settings = SettingsManager(_init_settings_path)


STRINGS = {
    "login_hint_create": {"ru": "Придумайте мастер-пароль", "en": "Create a master password"},
    "login_hint_repeat": {"ru": "Повторите пароль", "en": "Repeat the password"},
    "login_wrong": {"ru": "Неверный пароль", "en": "Wrong password"},
    "login_mismatch": {"ru": "Пароли не совпали. Попробуйте снова.", "en": "Passwords don't match. Try again."},
    "login_min10": {"ru": "Минимум 10 символов", "en": "Minimum 10 characters"},
    "login_need_pw": {"ru": "Введите пароль", "en": "Password required"},
    "login_locked": {"ru": "Подождите {n} сек. перед следующей попыткой", "en": "Wait {n} sec. before next attempt"},
    "login_salt_err": {"ru": "Ошибка соли: {e}", "en": "Salt error: {e}"},
    "login_decrypt_err": {"ru": "Не удалось расшифровать хранилище", "en": "Failed to decrypt storage"},
    "login_err": {"ru": "Ошибка: {e}", "en": "Error: {e}"},
    "session_expired": {"ru": "Сессия истекла из-за неактивности", "en": "Session expired due to inactivity"},
    "btn_new_user_tip": {"ru": "Новый пользователь", "en": "New user"},

    "title_register": {"ru": "Создание пользователя", "en": "Create user"},
    "title_restore": {"ru": "Восстановить с GitHub", "en": "Restore from GitHub"},
    "field_username": {"ru": "Логин", "en": "Login"},
    "field_password_confirm": {"ru": "Повторите пароль", "en": "Repeat password"},
    "ph_username": {"ru": "например, alice", "en": "e.g. alice"},
    "ph_password_new": {"ru": "минимум 10 символов", "en": "at least 10 characters"},
    "ph_password_confirm": {"ru": "повторите пароль", "en": "repeat password"},
    "reg_err_empty": {"ru": "Введите логин", "en": "Enter login"},
    "reg_err_too_short": {"ru": "Логин слишком короткий (минимум 2)", "en": "Login too short (min 2)"},
    "reg_err_too_long": {"ru": "Логин слишком длинный (максимум 32)", "en": "Login too long (max 32)"},
    "reg_err_bad_chars": {"ru": "Недопустимые символы в логине", "en": "Invalid characters in login"},
    "reg_err_exists": {"ru": "Пользователь с таким логином уже существует", "en": "User with this login already exists"},
    "reg_err_generic": {"ru": "Не удалось создать пользователя: {e}", "en": "Failed to create user: {e}"},
    "reg_err_no_url": {"ru": "Укажите URL репозитория", "en": "Enter repository URL"},
    "reg_ok": {"ru": "Пользователь «{name}» создан", "en": "User «{name}» created"},
    "restore_ok": {"ru": "Данные восстановлены. Пользователь: {name}. Введите мастер-пароль.", "en": "Restored. User: {name}. Enter master password."},
    "reg_first_required": {"ru": "Создайте первого пользователя", "en": "Create the first user"},

    "reg_mode_new": {"ru": "Новый пользователь", "en": "New user"},
    "reg_mode_restore": {"ru": "Восстановить с GitHub", "en": "Restore from GitHub"},
    "label_github_url": {"ru": "GitHub URL", "en": "GitHub URL"},
    "ph_github_url": {"ru": "https://github.com/user/repo.git", "en": "https://github.com/user/repo.git"},
    "label_github_token": {"ru": "Personal Access Token", "en": "Personal Access Token"},
    "ph_github_token": {"ru": "github_pat_…", "en": "github_pat_…"},
    "gh_auth_help": {
        "ru": (
            "1. GitHub → Settings → Developer settings → Fine-grained tokens\n"
            "2. Generate new token → Repository access: Only select repositories\n"
            "3. Permissions: Contents → Read and write\n"
            "4. Скопируй токен (github_pat_…) и вставь сюда\n"
            "5. URL репозитория: https://github.com/user/repo.git"
        ),
        "en": (
            "1. GitHub → Settings → Developer settings → Fine-grained tokens\n"
            "2. Generate new token → Repository access: Only select repositories\n"
            "3. Permissions: Contents → Read and write\n"
            "4. Copy token (github_pat_…) and paste here\n"
            "5. Repository URL: https://github.com/user/repo.git"
        ),
    },

    "sync_ind_off": {"ru": "sync off", "en": "sync off"},
    "sync_ind_syncing": {"ru": "syncing", "en": "syncing"},
    "sync_ind_error": {"ru": "sync error", "en": "sync error"},

    "tab_general": {"ru": "Общие", "en": "General"},
    "tab_security": {"ru": "Безопасность", "en": "Security"},
    "tab_github": {"ru": "GitHub Sync", "en": "GitHub Sync"},

    "label_github_enabled": {"ru": "Включить синхронизацию", "en": "Enable sync"},
    "label_github_url_field": {"ru": "URL репозитория", "en": "Repository URL"},
    "label_github_branch": {"ru": "Ветка", "en": "Branch"},
    "label_github_interval": {"ru": "Интервал (сек)", "en": "Interval (sec)"},
    "btn_test_connection": {"ru": "Проверить подключение", "en": "Test connection"},
    "gh_test_need_url": {"ru": "Введите URL", "en": "Enter URL"},
    "gh_test_need_token": {"ru": "Введите токен", "en": "Enter token"},
    "gh_test_testing": {"ru": "Проверка…", "en": "Testing…"},
    "gh_test_ok": {"ru": "✓ Успешно", "en": "✓ Connection OK"},
    "gh_test_fail": {"ru": "✗ {err}", "en": "✗ {err}"},
    "gh_save_fail": {"ru": "Синхронизация не включена — сначала успешно пройди проверку подключения.",
                     "en": "Sync not enabled — pass connection test first."},

    "search_placeholder": {"ru": "Поиск…", "en": "Search…"},
    "btn_logout": {"ru": "Выйти", "en": "Log out"},
    "btn_settings": {"ru": "Настройки", "en": "Settings"},
    "btn_create": {"ru": "Создать", "en": "Create"},
    "btn_restore": {"ru": "Восстановить", "en": "Restore"},
    "btn_import": {"ru": "Импорт (text)", "en": "Import (text)"},
    "btn_export_text": {"ru": "Экспорт (text)", "en": "Export (text)"},
    "btn_export_archive": {"ru": "Экспорт (.nimbus)", "en": "Export (.nimbus)"},
    "btn_edit": {"ru": "Изменить", "en": "Edit"},
    "btn_copy_password": {"ru": "Копировать пароль", "en": "Copy password"},
    "btn_delete": {"ru": "Удалить", "en": "Delete"},
    "btn_cancel": {"ru": "Отмена", "en": "Cancel"},
    "btn_save": {"ru": "Сохранить", "en": "Save"},
    "btn_show": {"ru": "Показать", "en": "Show"},
    "btn_hide": {"ru": "Скрыть", "en": "Hide"},
    "btn_generate": {"ru": "Сгенерировать", "en": "Generate"},
    "btn_confirm": {"ru": "Подтвердить", "en": "Confirm"},
    "btn_ok": {"ru": "OK", "en": "OK"},
    "btn_delete_all": {"ru": "Удалить всё", "en": "Delete all"},
    "btn_copy_row": {"ru": "Копировать строку", "en": "Copy row"},
    "btn_change_master": {"ru": "Сменить мастер-пароль", "en": "Change master password"},
    "confirm_delete_all_title": {"ru": "Удалить ВСЕ записи?", "en": "Delete ALL records?"},
    "confirm_delete_all_msg": {"ru": "Все {n} записей будут удалены навсегда. Это действие нельзя отменить.",
                                "en": "All {n} records will be permanently deleted. This cannot be undone."},
    "status_deleted_all": {"ru": "Удалено записей: {n}", "en": "Deleted {n} records"},
    "status_copied_row": {"ru": "Строка скопирована", "en": "Row copied"},

    "change_pw_title": {"ru": "Смена мастер-пароля", "en": "Change master password"},
    "change_pw_current": {"ru": "Текущий пароль", "en": "Current password"},
    "change_pw_new": {"ru": "Новый пароль", "en": "New password"},
    "change_pw_confirm": {"ru": "Повторите новый пароль", "en": "Repeat new password"},
    "change_pw_next": {"ru": "Далее", "en": "Next"},
    "change_pw_wrong": {"ru": "Неверный текущий пароль", "en": "Wrong current password"},
    "change_pw_ok": {"ru": "Мастер-пароль изменён", "en": "Master password changed"},
    "change_pw_err": {"ru": "Ошибка смены пароля: {e}", "en": "Failed to change password: {e}"},
    "change_pw_busy": {"ru": "Идёт синхронизация, попробуйте чуть позже",
                       "en": "Sync is running, try again shortly"},

    "count_empty": {"ru": "пусто", "en": "empty"},
    "count_n": {"ru": "{n} записей", "en": "{n} records"},
    "count_filtered": {"ru": "{v} / {t} записей", "en": "{v} / {t} records"},

    "status_copied": {"ru": "{label} скопирован", "en": "{label} copied"},
    "status_added": {"ru": "«{s}» добавлен", "en": "«{s}» added"},
    "status_updated": {"ru": "Запись обновлена", "en": "Record updated"},
    "status_deleted": {"ru": "Запись удалена", "en": "Record deleted"},
    "status_cancelled": {"ru": "Операция отменена", "en": "Operation cancelled"},
    "status_select": {"ru": "Выберите запись", "en": "Select a record"},
    "status_save_failed": {"ru": "Не удалось сохранить: {e}", "en": "Failed to save: {e}"},
    "status_load_failed": {"ru": "Не удалось прочитать: {e}", "en": "Failed to load: {e}"},
    "status_sync_busy": {"ru": "Идёт синхронизация, попробуйте через секунду", "en": "Sync in progress, try again in a moment"},
    "status_sync_err": {"ru": "Синхронизация: {e}", "en": "Sync: {e}"},

    "col_service": {"ru": "СЕРВИС", "en": "SERVICE"},
    "col_login": {"ru": "ЛОГИН", "en": "LOGIN"},
    "col_password": {"ru": "ПАРОЛЬ", "en": "PASSWORD"},
    "col_description": {"ru": "ОПИСАНИЕ", "en": "DESCRIPTION"},

    "field_service": {"ru": "Сервис", "en": "Service"},
    "field_login": {"ru": "Логин", "en": "Login"},
    "field_password": {"ru": "Пароль", "en": "Password"},
    "field_description": {"ru": "Описание", "en": "Description"},

    "label_language": {"ru": "Язык", "en": "Language"},
    "label_theme": {"ru": "Тема", "en": "Theme"},
    "label_autostart": {"ru": "Открывать при запуске системы", "en": "Open at system startup"},
    "label_start_min": {"ru": "Запускать свёрнутым в трей", "en": "Start minimized to tray"},
    "label_pw_len": {"ru": "Длина пароля (генератор)", "en": "Password length (generator)"},
    "label_clip_timeout": {"ru": "Автоочистка буфера обмена (сек)", "en": "Clipboard auto-clear (sec)"},
    "label_session_timeout": {"ru": "Блокировка при неактивности (сек)", "en": "Lock on inactivity (sec)"},
    "label_confirm_delete": {"ru": "Подтверждать удаление записей", "en": "Confirm record deletion"},
    "label_minimize_tray": {"ru": "Сворачивать в трей при закрытии", "en": "Minimize to tray on close"},

    "ph_service": {"ru": "например, github.com", "en": "e.g. github.com"},
    "ph_login": {"ru": "имя пользователя или email", "en": "username or email"},
    "ph_password": {"ru": "пароль", "en": "password"},
    "ph_description": {"ru": "необязательное описание", "en": "optional description"},
    "ph_master": {"ru": "Мастер-пароль", "en": "Master password"},

    "title_new_record": {"ru": "Новая запись", "en": "New record"},
    "title_edit_record": {"ru": "Изменить запись", "en": "Edit record"},
    "title_settings": {"ru": "Настройки", "en": "Settings"},
    "title_confirm": {"ru": "Подтверждение", "en": "Confirmation"},
    "title_error": {"ru": "Ошибка", "en": "Error"},

    "section_appearance": {"ru": "ВНЕШНИЙ ВИД", "en": "APPEARANCE"},
    "section_startup": {"ru": "ЗАПУСК", "en": "STARTUP"},
    "section_security": {"ru": "БЕЗОПАСНОСТЬ", "en": "SECURITY"},
    "section_sync": {"ru": "СИНХРОНИЗАЦИЯ GITHUB", "en": "GITHUB SYNC"},

    "seg_lang_ru": {"ru": "Русский", "en": "Russian"},
    "seg_lang_en": {"ru": "English", "en": "English"},
    "seg_theme_system": {"ru": "Системная", "en": "System"},
    "seg_theme_light": {"ru": "Светлая", "en": "Light"},
    "seg_theme_dark": {"ru": "Тёмная", "en": "Dark"},

    "err_service_required": {"ru": "Введите сервис", "en": "Enter service"},
    "err_login_required": {"ru": "Введите логин", "en": "Enter login"},
    "err_password_required": {"ru": "Введите пароль", "en": "Enter password"},

    "confirm_delete_title": {"ru": "Удалить запись «{s}»?", "en": "Delete record «{s}»?"},
    "confirm_delete_msg": {"ru": "Запись будет удалена навсегда. Это действие нельзя отменить.",
                           "en": "The record will be permanently deleted."},

    "confirm_pw_action_default": {"ru": "продолжения", "en": "to continue"},
    "confirm_pw_action_import": {"ru": "импорта данных", "en": "to import data"},
    "confirm_pw_action_export": {"ru": "экспорта данных", "en": "to export data"},
    "confirm_pw_sub": {"ru": "Введите мастер-пароль для {a}.", "en": "Enter master password {a}."},
    "confirm_pw_err": {"ru": "Неверный пароль", "en": "Wrong password"},
    "confirm_pw_need": {"ru": "Введите пароль", "en": "Enter password"},

    "tray_open": {"ru": "Открыть Nimbus", "en": "Open Nimbus"},
    "tray_quit": {"ru": "Закрыть программу", "en": "Quit"},
    "tray_min_auth": {"ru": "Пароль сброшен. Программа свёрнута в трей.", "en": "Password reset. App minimized."},
    "tray_min": {"ru": "Программа свёрнута в трей.", "en": "App minimized."},
    "tray_min_hint": {"ru": " Двойной клик по иконке — открыть.", "en": " Double-click to open."},

    "dlg_import_title": {"ru": "Импорт из CSV", "en": "Import from CSV"},
    "dlg_export_title": {"ru": "Экспорт в CSV", "en": "Export to CSV"},
    "dlg_export_archive_title": {"ru": "Выберите папку для ZIP", "en": "Choose folder for ZIP"},
    "file_csv": {"ru": "CSV файлы (*.csv);;Все файлы (*)", "en": "CSV files (*.csv);;All files (*)"},
    "export_default_filename": {"ru": "exportdata.csv", "en": "exportdata.csv"},

    "msg_already_running_title": {"ru": "Nimbus уже запущен", "en": "Nimbus is already running"},
    "msg_already_running": {"ru": "Второй экземпляр не запущен.", "en": "A second instance was not started."},
}


class I18n:
    def __init__(self, lang="ru"):
        self.lang = lang if lang in ("ru", "en") else "ru"
        self._listeners = []

    def t(self, key, **kw):
        entry = STRINGS.get(key)
        if entry is None:
            return key
        s = entry.get(self.lang) or entry.get("en") or key
        if kw:
            try:
                return s.format(**kw)
            except Exception:
                return s
        return s

    def set_language(self, lang):
        if lang not in ("ru", "en") or lang == self.lang:
            return
        self.lang = lang
        for cb in list(self._listeners):
            try:
                cb()
            except RuntimeError:
                pass
            except Exception as e:
                print(f"[i18n] callback error: {e}")

    def subscribe(self, cb):
        self._listeners.append(cb)


i18n = I18n(settings.get("language", "ru"))


def t(key, **kw):
    return i18n.t(key, **kw)


def build_launch_command(include_minimized=True):
    if getattr(sys, "frozen", False):
        exe = sys.executable
        script = None
    else:
        script = os.path.abspath(__file__)
        if platform.system() == "Windows":
            if sys.executable.lower().endswith("python.exe"):
                pythonw = sys.executable[:-10] + "pythonw.exe"
                exe = pythonw if os.path.exists(pythonw) else sys.executable
            elif sys.executable.lower().endswith("pythonw.exe"):
                exe = sys.executable
            else:
                pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
                exe = pythonw if os.path.exists(pythonw) else sys.executable
        else:
            exe = sys.executable
    parts = [f'"{exe}"']
    if script:
        parts.append(f'"{script}"')
    if include_minimized and settings.get("start_minimized", False):
        parts.append("--minimized")
    return " ".join(parts)


def is_autostart_enabled():
    if platform.system() == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Run",
                                 0, winreg.KEY_READ)
            try:
                winreg.QueryValueEx(key, "Nimbus")
                winreg.CloseKey(key)
                return True
            except FileNotFoundError:
                winreg.CloseKey(key)
                return False
        except Exception:
            return False
    if platform.system() == "Linux":
        return os.path.exists(os.path.expanduser("~/.config/autostart/nimbus.desktop"))
    return False


def set_autostart(enabled):
    if platform.system() == "Windows":
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            except FileNotFoundError:
                key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            if enabled:
                winreg.SetValueEx(key, "Nimbus", 0, winreg.REG_SZ, build_launch_command(True))
            else:
                try:
                    winreg.DeleteValue(key, "Nimbus")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
            return True
        except Exception as e:
            with open("autostart_error.log", "a", encoding="utf-8") as f:
                f.write(f"Error: {e}\n")
            return False
    if platform.system() == "Linux":
        try:
            autostart_dir = os.path.expanduser("~/.config/autostart")
            path = os.path.join(autostart_dir, "nimbus.desktop")
            if enabled:
                os.makedirs(autostart_dir, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write("[Desktop Entry]\nType=Application\nName=Nimbus\n"
                            f"Exec={build_launch_command(True)}\n"
                            "X-GNOME-Autostart-enabled=true\n")
            else:
                if os.path.exists(path):
                    os.remove(path)
            return True
        except Exception as e:
            print(f"[autostart] error: {e}")
            return False
    return False


def detect_system_theme():
    app = QApplication.instance()
    if app:
        try:
            cs = app.styleHints().colorScheme()
            if cs == Qt.ColorScheme.Dark:
                return "dark"
            if cs == Qt.ColorScheme.Light:
                return "light"
        except Exception:
            pass
    return "light"


def get_icon_path():
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    for p in [os.path.join(base, "assets", "icon.ico"),
              os.path.join(base, "assets", "icon.png"),
              os.path.join(base, "icon.ico"),
              os.path.join(base, "icon.png")]:
        if os.path.exists(p):
            return p
    return ""


def make_default_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#6b5cb8"))
    p.drawRoundedRect(4, 4, 56, 56, 12, 12)
    p.setPen(QPen(QColor("white"), 0))
    f = p.font(); f.setPointSize(30); f.setBold(True)
    p.setFont(f)
    p.drawText(pixmap.rect(), int(Qt.AlignmentFlag.AlignCenter), "N")
    p.end()
    return QIcon(pixmap)


def load_app_icon():
    path = get_icon_path()
    if path:
        icon = QIcon(path)
        if not icon.isNull():
            return icon
    return make_default_icon()


def qc(color):
    if not color:
        return QColor(0, 0, 0, 0)
    color = color.strip()
    if color.startswith("rgba("):
        try:
            inner = color[5:-1]
            parts = [p.strip() for p in inner.split(",")]
            r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
            a_raw = parts[3]
            a = int(float(a_raw) * 255) if "." in a_raw else int(a_raw)
            return QColor(r, g, b, a)
        except Exception:
            return QColor(0, 0, 0, 0)
    if color.startswith("rgb("):
        try:
            inner = color[4:-1]
            parts = [p.strip() for p in inner.split(",")]
            return QColor(int(parts[0]), int(parts[1]), int(parts[2]))
        except Exception:
            return QColor(0, 0, 0, 0)
    return QColor(color)


LIGHT = {
    "name": "light", "window_bg": "#f0f0f3", "card": "#ffffff",
    "card_border": "rgba(0,0,0,18)", "top_panel": "rgba(255,255,255,235)",
    "tile": "rgba(255,255,255,180)", "tile_hover": "rgba(255,255,255,250)",
    "row_hover": "rgba(0,0,0,10)", "row_selected": "rgba(107,92,184,80)",
    "tile_border": "rgba(0,0,0,28)", "tile_border_hov": "rgba(0,0,0,70)",
    "text": "#1a1a1f", "text_sec": "#5a5a66", "text_muted": "#9090a0",
    "text_inv": "#ffffff", "accent": "#6b5cb8", "accent_hov": "#5a4da0",
    "accent_press": "#4a3e8a", "accent_soft": "rgba(107,92,184,35)",
    "btn_accent_hover_bg": "rgba(107,92,184,55)", "danger": "#d13838",
    "danger_hov": "#b82d2d", "danger_soft": "rgba(209,56,56,35)",
    "btn_danger_hover_bg": "rgba(209,56,56,50)", "icon_hover_bg": "rgba(0,0,0,22)",
    "danger_icon_hover_bg": "rgba(209,56,56,28)",
    "icon_hover_bg_on_selected": "rgba(255,255,255,235)",
    "danger_icon_hover_bg_on_selected": "rgba(255,220,220,235)",
    "btn_border": "rgba(0,0,0,40)", "input_bg": "#ffffff",
    "input_border": "rgba(0,0,0,30)", "input_focus": "#6b5cb8",
    "scroll": "rgba(0,0,0,60)", "scroll_hov": "rgba(0,0,0,110)",
}

DARK = {
    "name": "dark", "window_bg": "#121215", "card": "#1a1a1f",
    "card_border": "rgba(255,255,255,22)", "top_panel": "rgba(26,26,31,235)",
    "tile": "rgba(45,45,53,190)", "tile_hover": "rgba(60,60,70,240)",
    "row_hover": "rgba(255,255,255,10)", "row_selected": "rgba(255,140,40,130)",
    "tile_border": "rgba(255,255,255,30)", "tile_border_hov": "rgba(255,255,255,90)",
    "text": "#e8e8ed", "text_sec": "#a0a0aa", "text_muted": "#606068",
    "text_inv": "#121215", "accent": "#f5c842", "accent_hov": "#e5b530",
    "accent_press": "#cc9e20", "accent_soft": "rgba(245,200,66,45)",
    "btn_accent_hover_bg": "rgba(245,200,66,60)", "danger": "#ef5350",
    "danger_hov": "#d93a37", "danger_soft": "rgba(239,83,80,45)",
    "btn_danger_hover_bg": "rgba(239,83,80,55)", "icon_hover_bg": "rgba(255,255,255,22)",
    "danger_icon_hover_bg": "rgba(239,83,80,45)",
    "icon_hover_bg_on_selected": "rgba(50,50,50,220)",
    "danger_icon_hover_bg_on_selected": "rgba(70,30,30,220)",
    "btn_border": "rgba(255,255,255,45)", "input_bg": "#1a1a1f",
    "input_border": "rgba(255,255,255,35)", "input_focus": "#f5c842",
    "scroll": "rgba(255,255,255,55)", "scroll_hov": "rgba(255,255,255,110)",
}
THEMES = {"light": LIGHT, "dark": DARK}


def build_qss(t_):
    return f"""
    * {{ font-family: "Segoe UI", "SF Pro Text", -apple-system, "Roboto", sans-serif; }}
    QWidget {{ color: {t_['text']}; background: transparent; font-size: 14px; }}
    QMainWindow {{ background: {t_['window_bg']}; }}
    QLineEdit {{
        background: {t_['input_bg']}; border: 1px solid {t_['input_border']};
        border-radius: 6px; padding: 8px 12px; color: {t_['text']};
        font-size: 15px; selection-background-color: {t_['accent']};
        selection-color: {t_['text_inv']};
    }}
    QLineEdit:focus {{ border: 1px solid {t_['input_focus']}; }}
    QPushButton {{
        background: transparent; border: 1px solid {t_['btn_border']};
        border-radius: 4px; padding: 8px 18px; color: {t_['text']};
        font-size: 15px; font-weight: 500;
    }}
    QPushButton:hover {{ background: {t_['btn_accent_hover_bg']};
        border: 1px solid {t_['accent']}; color: {t_['accent']}; }}
    QPushButton:pressed {{ background: {t_['accent']};
        border: 1px solid {t_['accent']}; color: {t_['text_inv']}; }}
    QPushButton:disabled {{ color: {t_['text_muted']}; background: transparent;
        border: 1px solid {t_['card_border']}; }}
    QPushButton#danger {{ background: transparent; border: 1px solid {t_['btn_border']};
        color: {t_['danger']}; }}
    QPushButton#danger:hover {{ background: {t_['btn_danger_hover_bg']};
        border: 1px solid {t_['danger']}; color: {t_['danger']}; }}
    QPushButton#danger:pressed {{ background: {t_['danger']};
        border: 1px solid {t_['danger']}; color: {t_['text_inv']}; }}
    QPushButton#danger:disabled {{ color: {t_['text_muted']}; background: transparent;
        border: 1px solid {t_['card_border']}; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t_['scroll']}; border-radius: 5px;
        min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {t_['scroll_hov']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QTableView {{ background: transparent; border: none; outline: none;
        gridline-color: transparent; }}
    QTableView::item {{ border: none; padding: 0; }}
    QHeaderView::section {{ background: transparent; border: none;
        color: {t_['text_muted']}; font-size: 12px; font-weight: 600;
        padding: 10px 14px; text-align: left; letter-spacing: 0.4px; }}
    QDialog {{ background: {t_['window_bg']}; }}
    QMenu {{ background: {t_['card']}; color: {t_['text']};
        border: 1px solid {t_['card_border']}; border-radius: 6px; padding: 4px; }}
    QMenu::item {{ padding: 8px 18px; border-radius: 4px; font-size: 14px; }}
    QMenu::item:selected {{ background: {t_['accent']}; color: {t_['text_inv']}; }}
    QMenu::separator {{ height: 1px; background: {t_['card_border']};
        margin: 4px 8px; }}
    QTabWidget::pane {{ border: 1px solid {t_['card_border']};
        border-radius: 10px; background: {t_['card']}; top: -1px; }}
    QTabBar {{ background: transparent; qproperty-expanding: 0; }}
    QTabBar::tab {{ background: transparent; color: {t_['text_sec']};
        padding: 10px 22px; margin-right: 4px;
        border: 1px solid transparent;
        border-bottom: 2px solid transparent;
        font-size: 14px; font-weight: 500;
        border-top-left-radius: 8px; border-top-right-radius: 8px; }}
    QTabBar::tab:selected {{ color: {t_['accent']};
        border-bottom: 2px solid {t_['accent']}; }}
    QTabBar::tab:hover {{ color: {t_['text']};
        background: {t_['btn_accent_hover_bg']}; }}
    QTabBar::tab:disabled {{ color: {t_['text_muted']}; }}
    QFrame#settingsCard {{
        background: {t_['card']};
        border: 1px solid {t_['card_border']};
        border-radius: 10px;
    }}
    QLabel#settingsCardTitle {{
        font-size: 11px;
        font-weight: 700;
        color: {t_['text_muted']};
        letter-spacing: 1.5px;
        background: transparent;
    }}
    QPlainTextEdit {{
        background: {t_['input_bg']}; border: 1px solid {t_['input_border']};
        border-radius: 6px; color: {t_['text_sec']}; font-size: 11px;
        font-family: "Consolas", "Monaco", monospace; padding: 6px;
    }}
    """


def primary_btn_qss(t_):
    return f"""
    QPushButton {{
        background-color: {t_['accent']}; border: 1px solid {t_['accent']};
        border-radius: 6px; color: {t_['text_inv']}; font-size: 15px;
        font-weight: 600; padding: 10px 22px;
    }}
    QPushButton:hover {{ background-color: {t_['accent_hov']};
        border-color: {t_['accent_hov']}; }}
    QPushButton:pressed {{ background-color: {t_['accent_press']};
        border-color: {t_['accent_press']}; }}
    QPushButton:disabled {{ background-color: transparent;
        color: {t_['text_muted']}; border: 1px solid {t_['card_border']}; }}
    """


def danger_btn_qss(t_):
    return f"""
    QPushButton {{
        background-color: {t_['danger']}; border: 1px solid {t_['danger']};
        border-radius: 6px; color: #ffffff; font-size: 15px;
        font-weight: 600; padding: 10px 22px;
    }}
    QPushButton:hover {{ background-color: {t_['danger_hov']};
        border-color: {t_['danger_hov']}; }}
    """


class ThemeManager:
    def __init__(self):
        self.mode = "system"
        self.name = "light"
        self.t = LIGHT
        self._listeners = []
        self._apply_mode(notify=False)

    def current(self):
        return self.t

    def _apply_mode(self, notify=True):
        if self.mode == "system":
            self.name = detect_system_theme()
        else:
            self.name = self.mode
        self.t = THEMES[self.name]
        app = QApplication.instance()
        if app:
            try:
                app.setStyleSheet(build_qss(self.t))
            except Exception as e:
                print(f"[theme] {e}")
        if notify:
            for cb in list(self._listeners):
                try:
                    cb(self.t)
                except RuntimeError:
                    pass
                except Exception as e:
                    print(f"[theme] cb: {e}")

    def set_mode(self, mode, save=True):
        if mode not in ("system", "light", "dark"):
            mode = "system"
        self.mode = mode
        self._apply_mode(notify=True)
        if save:
            settings.set("theme", mode)

    def toggle(self):
        self.set_mode("dark" if self.name == "light" else "light")

    def on_system_color_scheme_changed(self, _):
        if self.mode == "system":
            self._apply_mode(notify=True)

    def subscribe(self, cb):
        self._listeners.append(cb)


theme = ThemeManager()


# ---------------------------------------------------------------------------
# Модель
# ---------------------------------------------------------------------------

class RecordModel(QAbstractTableModel):
    _COLUMN_KEYS = ["col_service", "col_login", "col_password", "col_description", ""]

    def __init__(self, storage):
        super().__init__()
        self.storage = storage
        self._data = list(storage.get_all())
        self._revealed = set()

    def refresh(self):
        self.beginResetModel()
        self._data = list(self.storage.get_all())
        live = {id(r) for r in self._data}
        self._revealed &= live
        self.endResetModel()

    def refresh_headers(self):
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(self._COLUMN_KEYS) - 1)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._COLUMN_KEYS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._data):
            return None
        rec = self._data[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0: return nimbus.safe_str(rec.get("service"))
            if col == 1: return nimbus.safe_str(rec.get("username"))
            if col == 2:
                if id(rec) in self._revealed:
                    return nimbus.safe_str(rec.get("password"))
                return "••••••••"
            if col == 3: return nimbus.safe_str(rec.get("description")) or "—"
            return None
        if role == Qt.ItemDataRole.UserRole:
            return rec
        return None

    def toggle_reveal(self, row):
        if not (0 <= row < len(self._data)):
            return
        rec = self._data[row]
        key = id(rec)
        self._revealed.symmetric_difference_update({key})
        idx = self.index(row, 2)
        self.dataChanged.emit(idx, idx)

    def get_record(self, row):
        if 0 <= row < len(self._data):
            return self._data[row]
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self._COLUMN_KEYS):
                key = self._COLUMN_KEYS[section]
                return t(key) if key else ""
        return None


class RecordFilterProxy(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.setDynamicSortFilter(True)
        self._needle = ""

    def set_filter_text(self, text):
        self._needle = text.strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        if not self._needle:
            return True
        model = self.sourceModel()
        for col in (0, 1, 3):
            idx = model.index(source_row, col, source_parent)
            text = (model.data(idx, Qt.ItemDataRole.DisplayRole) or "").lower()
            if self._needle in text:
                return True
        return False


# ---------------------------------------------------------------------------
# Таблица и делегат
# ---------------------------------------------------------------------------

class HoverTableView(QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self._hover_row = -1
        self._hover_col = -1
        self._hover_btn = -1

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.indexAt(event.pos())
            if not index.isValid():
                self.clearSelection()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        index = self.indexAt(event.pos())
        row = index.row() if index.isValid() else -1
        col = index.column() if index.isValid() else -1
        hover_btn = -1
        if index.isValid() and col == 4:
            rect = self.visualRect(index)
            btn, gap = 34, 8
            total = btn * 2 + gap
            sx = rect.center().x() - total // 2
            y = rect.center().y() - btn // 2
            if QRect(sx, y, btn, btn).contains(event.pos()):
                hover_btn = 0
            elif QRect(sx + btn + gap, y, btn, btn).contains(event.pos()):
                hover_btn = 1
        changed = False
        if row != self._hover_row or col != self._hover_col:
            self._hover_row, self._hover_col = row, col
            changed = True
        if hover_btn != self._hover_btn:
            self._hover_btn = hover_btn
            changed = True
        if changed:
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hover_row != -1 or self._hover_col != -1 or self._hover_btn != -1:
            self._hover_row = -1
            self._hover_col = -1
            self._hover_btn = -1
            self.viewport().update()
        super().leaveEvent(event)

    @property
    def hover_row(self): return self._hover_row
    @property
    def hover_col(self): return self._hover_col
    @property
    def hover_btn(self): return self._hover_btn


class TileDelegate(QStyledItemDelegate):
    def __init__(self, view, is_action_column=False, on_action=None):
        super().__init__(view)
        self.view = view
        self.is_action_column = is_action_column
        self.on_action = on_action

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        t_ = theme.current()
        row = index.row()
        col = index.column()
        row_hovered = (row == self.view.hover_row)
        tile_hovered = row_hovered and (col == self.view.hover_col)
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if is_selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(qc(t_["row_selected"]))
            painter.drawRect(option.rect)
        elif row_hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(qc(t_["row_hover"]))
            painter.drawRect(option.rect)
        if self.is_action_column:
            self._paint_actions(painter, option, row, is_selected)
        else:
            self._paint_tile(painter, option, index, tile_hovered)
        painter.restore()

    def _paint_tile(self, painter, option, index, hovered):
        t_ = theme.current()
        if hovered:
            rect = option.rect.adjusted(3, 4, -3, -4)
            bg, border = qc(t_["tile_hover"]), qc(t_["tile_border_hov"])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 20 if t_["name"] == "light" else 85))
            painter.drawRoundedRect(rect.adjusted(0, 2, 0, 2), 5, 5)
        else:
            rect = option.rect.adjusted(4, 5, -4, -5)
            bg, border = qc(t_["tile"]), qc(t_["tile_border"])
        painter.setPen(QPen(border, 1))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 4, 4)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        painter.setPen(qc(t_["text"]))
        f = painter.font(); f.setPointSize(11); f.setWeight(QFont.Weight.Normal)
        painter.setFont(f)
        painter.drawText(rect.adjusted(14, 0, -10, 0),
                         int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                         text)

    def _paint_actions(self, painter, option, row, is_selected):
        t_ = theme.current()
        rect = option.rect
        btn, gap = 34, 8
        total = btn * 2 + gap
        sx = rect.center().x() - total // 2
        y = rect.center().y() - btn // 2
        edit_rect = QRect(sx, y, btn, btn)
        del_rect = QRect(sx + btn + gap, y, btn, btn)
        hb = self.view.hover_btn if row == self.view.hover_row else -1
        if hb == 0:
            key = "icon_hover_bg_on_selected" if is_selected else "icon_hover_bg"
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(qc(t_[key]))
            painter.drawRoundedRect(edit_rect, 5, 5)
        painter.setPen(qc(t_["accent"] if hb == 0 else t_["text_sec"]))
        f = painter.font(); f.setPointSize(15); f.setWeight(QFont.Weight.Bold)
        painter.setFont(f)
        painter.drawText(edit_rect, int(Qt.AlignmentFlag.AlignCenter), "✎")
        if hb == 1:
            key = "danger_icon_hover_bg_on_selected" if is_selected else "danger_icon_hover_bg"
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(qc(t_[key]))
            painter.drawRoundedRect(del_rect, 5, 5)
        painter.setPen(qc(t_["danger"] if hb == 1 else t_["text_sec"]))
        painter.drawText(del_rect, int(Qt.AlignmentFlag.AlignCenter), "✕")

    def editorEvent(self, event, model, option, index):
        if self.is_action_column and event.type() == event.Type.MouseButtonRelease:
            rect = option.rect
            btn, gap = 34, 8
            total = btn * 2 + gap
            sx = rect.center().x() - total // 2
            y = rect.center().y() - btn // 2
            if QRect(sx, y, btn, btn).contains(event.pos()):
                if self.on_action: self.on_action("edit", index)
                return True
            if QRect(sx + btn + gap, y, btn, btn).contains(event.pos()):
                if self.on_action: self.on_action("delete", index)
                return True
        return super().editorEvent(event, model, option, index)

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 56)


# ---------------------------------------------------------------------------
# UI-элементы
# ---------------------------------------------------------------------------

class ThemeSwitch(QWidget):
    W, H, PAD = 52, 28, 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pos = 0.0 if theme.name == "light" else 1.0
        theme.subscribe(self._on_change)

    def _on_change(self, _):
        self._pos = 0.0 if theme.name == "light" else 1.0
        try:
            self.update()
        except RuntimeError:
            pass

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            theme.toggle()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        t_ = theme.current()
        rect = QRectF(1, 1, self.W - 2, self.H - 2)
        radius = rect.height() / 2
        p.setPen(QPen(qc(t_["tile_border"]), 1))
        p.setBrush(qc(t_["tile"]))
        p.drawRoundedRect(rect, radius, radius)
        d = rect.height() - 2 * self.PAD
        x = rect.left() + self.PAD + (rect.width() - 2 * self.PAD - d) * self._pos
        y = rect.top() + self.PAD
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qc(t_["accent"]))
        p.drawEllipse(QRectF(x, y, d, d))


class ToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)
    W, H, PAD = 46, 24, 3

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checked = bool(checked)
        self._pos = 1.0 if self._checked else 0.0
        self._anim_timer = None
        theme.subscribe(self._on_change)

    def _on_change(self, _):
        try:
            self.update()
        except RuntimeError:
            pass

    def isChecked(self):
        return self._checked

    def setChecked(self, value):
        value = bool(value)
        if value == self._checked:
            return
        self._checked = value
        self._animate()
        self.toggled.emit(value)

    def _animate(self):
        target = 1.0 if self._checked else 0.0
        self._start, self._target, self._step = self._pos, target, 0
        if self._anim_timer is None:
            self._anim_timer = QTimer()
            self._anim_timer.timeout.connect(self._tick)
        self._anim_timer.start(12)

    def _tick(self):
        self._step += 1
        f = min(1.0, self._step / 8.0)
        f = 1 - (1 - f) ** 2
        self._pos = self._start + (self._target - self._start) * f
        self.update()
        if f >= 1.0:
            self._anim_timer.stop()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.setChecked(not self._checked)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        t_ = theme.current()
        if not self.isEnabled():
            p.setOpacity(0.35)
        rect = QRectF(1, 1, self.W - 2, self.H - 2)
        radius = rect.height() / 2
        bg = qc(t_["accent"]) if self._checked else qc(t_["tile"])
        p.setPen(QPen(qc(t_["tile_border"]), 1))
        p.setBrush(bg)
        p.drawRoundedRect(rect, radius, radius)
        d = rect.height() - 2 * self.PAD
        x = rect.left() + self.PAD + (rect.width() - 2 * self.PAD - d) * self._pos
        y = rect.top() + self.PAD
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("white") if self._checked else qc(t_["text_muted"]))
        p.drawEllipse(QRectF(x, y, d, d))


class SegmentedControl(QWidget):
    value_changed = pyqtSignal(object)

    def __init__(self, option_keys, current_value, parent=None):
        super().__init__(parent)
        self._option_keys = [k for k, _ in option_keys]
        self._values = [v for _, v in option_keys]
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons = []
        n = len(option_keys)
        for i, (key, value) in enumerate(option_keys):
            btn = QPushButton(t(key))
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(40)
            btn.setMinimumWidth(110)
            if i == 0:
                pos = "first"
            elif i == n - 1:
                pos = "last"
            else:
                pos = "mid"
            btn.setProperty("seg_pos", pos)
            self._group.addButton(btn, i)
            self._buttons.append(btn)
            layout.addWidget(btn)
            if value == current_value:
                btn.setChecked(True)
            theme.subscribe(lambda _, b=btn: self._apply_btn_style(b))
        self._group.buttonClicked.connect(self._on_click)
        for b in self._buttons:
            self._apply_btn_style(b)
        i18n.subscribe(self._retranslate)

    def _retranslate(self):
        try:
            for btn, key in zip(self._buttons, self._option_keys):
                btn.setText(t(key))
        except RuntimeError:
            pass

    def _apply_btn_style(self, btn):
        t_ = theme.current()
        pos = btn.property("seg_pos")
        if pos == "first":
            corners = ("border-top-left-radius: 6px; border-bottom-left-radius: 6px;"
                       "border-top-right-radius: 0; border-bottom-right-radius: 0;"
                       "border-right: 0;")
        elif pos == "last":
            corners = ("border-top-right-radius: 6px; border-bottom-right-radius: 6px;"
                       "border-top-left-radius: 0; border-bottom-left-radius: 0;")
        else:
            corners = "border-radius: 0; border-right: 0;"
        if btn.isChecked():
            bg, fg, border, hover = t_["accent"], t_["text_inv"], t_["accent"], t_["accent_hov"]
        else:
            bg, fg, border, hover = (t_["input_bg"], t_["text"], t_["input_border"],
                                     t_["btn_accent_hover_bg"])
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {bg}; color: {fg}; border: 1px solid {border};
                {corners} padding: 8px 16px; font-size: 14px; font-weight: 500;
            }}
            QPushButton:hover {{ background: {hover}; }}
        """)

    def _on_click(self, btn):
        for b in self._buttons:
            self._apply_btn_style(b)
        idx = self._group.id(btn)
        if idx >= 0:
            self.value_changed.emit(self._values[idx])

    def value(self):
        idx = self._group.checkedId()
        return self._values[idx] if idx >= 0 else None


class SyncIndicator(QWidget):
    STATE_OFF, STATE_SYNCING, STATE_OK, STATE_ERROR = "off", "syncing", "ok", "error"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(160, 38)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._state = self.STATE_OFF
        self._last_sync_time = None
        self._err_text = ""
        self._blink_phase = 0
        self._dots_phase = 1
        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._tick_blink)
        self._dots_timer = QTimer(self)
        self._dots_timer.timeout.connect(self._tick_dots)
        theme.subscribe(lambda _: self._safe_update())
        i18n.subscribe(lambda: self._safe_update())

    def set_state(self, state, last_sync_time=None, err_text=None):
        self._state = state
        if last_sync_time is not None:
            self._last_sync_time = last_sync_time
        if err_text is not None:
            self._err_text = err_text or ""

        if state in (self.STATE_OK, self.STATE_ERROR):
            if not self._blink_timer.isActive():
                self._blink_timer.start(750)
        else:
            self._blink_timer.stop()
            self._blink_phase = 0

        if state == self.STATE_SYNCING:
            self._dots_phase = 1
            if not self._dots_timer.isActive():
                self._dots_timer.start(250)
        else:
            self._dots_timer.stop()
            self._dots_phase = 1

        try:
            if state == self.STATE_OK:
                if self._last_sync_time:
                    full = time.strftime("%Y-%m-%d %H:%M:%S",
                                         time.localtime(self._last_sync_time))
                    self.setToolTip(f"Synced {full}")
                else:
                    self.setToolTip("Synced")
            elif state == self.STATE_ERROR:
                tip = "Sync error"
                if self._err_text:
                    tip += f"\n{self._err_text}"
                self.setToolTip(tip)
            elif state == self.STATE_SYNCING:
                self.setToolTip("Syncing…")
            else:
                self.setToolTip("Sync disabled")
        except Exception:
            pass

        self._safe_update()

    def get_state(self):
        return self._state

    def _tick_blink(self):
        self._blink_phase = 1 - self._blink_phase
        self._safe_update()

    def _tick_dots(self):
        self._dots_phase = (self._dots_phase % 2) + 1
        self._safe_update()

    def _safe_update(self):
        try:
            self.update()
        except RuntimeError:
            pass

    def _colors(self):
        if theme.name == "dark":
            return {"ok": QColor("#22c55e"), "error": QColor("#ef4444"),
                    "syncing": QColor("#eab308"), "off": QColor("#4b5563"),
                    "text": QColor("#9ca3af")}
        return {"ok": QColor("#16a34a"), "error": QColor("#dc2626"),
                "syncing": QColor("#ca8a04"), "off": QColor("#6b7280"),
                "text": QColor("#4b5563")}

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c = self._colors()

        if self._state == self.STATE_OK:
            dot = c["ok"]
            text = self._fmt_time(self._last_sync_time)
        elif self._state == self.STATE_ERROR:
            dot = c["error"]
            text = t("sync_ind_error")
        elif self._state == self.STATE_SYNCING:
            dot = c["syncing"]
            sync_phase = ['/','\\']
            text =  sync_phase[self._dots_phase-1] + '  ' + t("sync_ind_syncing")
        else:
            dot = c["off"]
            text = t("sync_ind_off")

        if self._state in (self.STATE_OK, self.STATE_ERROR):
            alpha = 255 if self._blink_phase == 0 else 150
        else:
            alpha = 255
        dc = QColor(dot)
        dc.setAlpha(alpha)

        r, right_pad = 5, 10
        cx = self.width() - right_pad - r
        cy = self.height() // 2

        p.setPen(c["text"])
        f = p.font()
        f.setPointSize(10)
        p.setFont(f)
        fm = p.fontMetrics()

        gap = 16
        avail = max(0, cx - r - gap - 4)
        shown = fm.elidedText(text, Qt.TextElideMode.ElideRight, avail)

        tbr = fm.tightBoundingRect(shown)
        baseline_y = cy - tbr.center().y()

        text_x = cx - r - gap - fm.horizontalAdvance(shown)
        p.drawText(text_x, baseline_y, shown)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(dc)
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

    def _fmt_time(self, ts):
        if not ts:
            return "—"
        return time.strftime("%H:%M", time.localtime(ts))


class PasswordEdit(QLineEdit):
    submitted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEchoMode(QLineEdit.EchoMode.Password)
        self.setMinimumHeight(44)
        self.setMaximumHeight(44)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.returnPressed.connect(lambda: self.submitted.emit(self.text()))
        theme.subscribe(lambda _: self._restyle())
        self._restyle()

    def _restyle(self):
        try:
            t_ = theme.current()
            self.setStyleSheet(f"""
                QLineEdit {{
                    background: {t_['input_bg']}; border: 1px solid {t_['input_border']};
                    border-radius: 6px; padding: 0; color: {t_['text']};
                    font-size: 16px; letter-spacing: 6px;
                }}
                QLineEdit:focus {{ border: 1px solid {t_['input_focus']}; }}
            """)
        except RuntimeError:
            pass


# ---------------------------------------------------------------------------
# Login screen
# ---------------------------------------------------------------------------

class LoginView(QWidget):
    login_success = pyqtSignal(object, object, object)

    def __init__(self):
        super().__init__()
        self._attempts = 0
        self._lock_until = 0.0
        self._status_key = None
        self._status_text = None
        self._status_color = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(0)
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)
        self.switch = ThemeSwitch(self)
        top_bar.addWidget(self.switch, alignment=Qt.AlignmentFlag.AlignVCenter)
        top_bar.addStretch(1)
        self.add_user_btn = QPushButton("＋")
        self.add_user_btn.setFixedSize(38, 38)
        self.add_user_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_user_btn.clicked.connect(self._on_add_user)
        top_bar.addWidget(self.add_user_btn)
        outer.addLayout(top_bar)
        outer.addStretch(1)

        container = QWidget()
        container.setFixedWidth(440)
        layout = QVBoxLayout(container)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel("Nimbus")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)
        layout.addSpacing(20)

        self.pw_edit = PasswordEdit()
        self.pw_edit.submitted.connect(self._on_submit)
        layout.addWidget(self.pw_edit)
        layout.addSpacing(8)

        self.status = QLabel("")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(20)
        self.status.setMaximumHeight(80)
        layout.addWidget(self.status)

        self._status_clear_timer = QTimer(self)
        self._status_clear_timer.setSingleShot(True)
        self._status_clear_timer.timeout.connect(self._clear_status)

        outer.addWidget(container, alignment=Qt.AlignmentFlag.AlignCenter)
        outer.addStretch(1)
        theme.subscribe(lambda _: self._restyle())
        i18n.subscribe(lambda: self._on_lang_change())
        self._restyle()

    def _clear_status(self):
        try:
            self._status_key = None
            self._status_text = None
            self._apply_status("", theme.current()["text_muted"])
        except RuntimeError:
            pass

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            try:
                self.pw_edit.clearFocus()
            except RuntimeError:
                pass
        super().mousePressEvent(event)

    def show_text(self, text, color=None):
        self._status_key = None
        self._status_text = text
        self._status_color = color or theme.current()["text_muted"]
        self._apply_status(text, self._status_color)
        self._status_clear_timer.start(6000)

    def show_info(self, key):
        self._set_status_key(key, theme.current()["accent"])

    def reset(self):
        self.pw_edit.clear()
        self._attempts = 0
        self._lock_until = 0.0
        self.pw_edit.setEnabled(True)
        self._status_key = None
        self._status_text = None
        self._apply_status("", theme.current()["text_muted"])

    def _on_lang_change(self):
        try:
            self._restyle()
            self._reapply_status()
        except RuntimeError:
            pass

    def _restyle(self):
        try:
            t_ = theme.current()
            self.title.setStyleSheet(
                f"font-size: 44px; font-weight: 700; color: {t_['accent']}; "
                f"letter-spacing: -1.5px; background: transparent;")
            self.status.setStyleSheet(
                f"font-size: 18px; color: {t_['text_muted']}; background: transparent;")
            self.add_user_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; border: 1px solid {t_['btn_border']};
                    border-radius: 6px; color: {t_['text_sec']};
                    font-size: 20px; padding: 0;
                }}
                QPushButton:hover {{
                    background: {t_['btn_accent_hover_bg']};
                    border: 1px solid {t_['accent']}; color: {t_['accent']};
                }}
            """)
            self.add_user_btn.setToolTip(t("btn_new_user_tip"))
        except RuntimeError:
            pass

    def _reapply_status(self):
        if self._status_key:
            self._apply_status(t(self._status_key), self._status_color)
        elif self._status_text:
            self._apply_status(self._status_text, self._status_color)
        else:
            self._apply_status("", theme.current()["text_muted"])

    def _set_status_key(self, key, color=None):
        self._status_key = key
        self._status_text = None
        self._status_color = color
        if key is None:
            self._apply_status("", theme.current()["text_muted"])
            self._status_clear_timer.stop()
        else:
            self._apply_status(t(key), color)
            self._status_clear_timer.start(6000)

    def _apply_status(self, text, color=None):
        try:
            c = color or theme.current()["text_muted"]
            self.status.setText(text)
            self.status.setStyleSheet(
                f"font-size: 18px; color: {c}; background: transparent;")
        except RuntimeError:
            pass

    def _on_add_user(self):
        dlg = RegisterDialog(self.window())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if dlg.restore_mode and dlg.github_url:
            try:
                username = nimbus_sync.clone_from_github(
                    dlg.github_url, _SCRIPT_DIR, token=dlg.github_token or None)
            except Exception as e:
                self.show_text(t("status_sync_err", e=e), theme.current()["danger"])
                return
            paths = nimbus.UserPaths(username)
            s = load_settings(paths.settings_file)
            s["github_url"] = dlg.github_url
            s["github_enabled"] = True
            s["github_branch"] = "main"
            if dlg.github_token:
                s["github_token"] = dlg.github_token
            save_settings(paths.settings_file, s)
            self.show_text(t("restore_ok", name=username), theme.current()["accent"])
            return
        if dlg.username:
            self.show_text(t("reg_ok", name=dlg.username), theme.current()["accent"])

    def _on_submit(self, pw):
        if not pw:
            self._set_status_key("login_need_pw", "#cc8844")
            return
        now = time.time()
        if now < self._lock_until:
            remain = max(1, int(self._lock_until - now + 0.999))
            self._apply_status(t("login_locked", n=remain), theme.current()["danger"])
            return
        users = nimbus.list_existing_users()
        if not users:
            self.pw_edit.clear()
            self._set_status_key("reg_first_required", theme.current()["danger"])
            return
        matched_paths = None
        matched_salt = None
        for u in users:
            paths = nimbus.UserPaths(u)
            try:
                salt = nimbus.load_or_create_salt(paths.salt_file)
                if nimbus.verify_master_password(pw, salt, paths.key_file):
                    matched_paths, matched_salt = paths, salt
                    break
            except Exception:
                continue
        if not matched_paths:
            self._attempts += 1
            self.pw_edit.clear()
            if self._attempts >= 3:
                delay = min(2 ** (self._attempts - 2), 30)
                self._lock_until = now + delay
                self._lock_input(delay)
                self._apply_status(t("login_locked", n=delay), theme.current()["danger"])
            else:
                self._set_status_key("login_wrong", theme.current()["danger"])
            return
        self._attempts = 0
        self._finish(pw, matched_paths, matched_salt)

    def _lock_input(self, seconds):
        self.pw_edit.setEnabled(False)
        QTimer.singleShot(seconds * 1000, self._unlock_input)

    def _unlock_input(self):
        try:
            if self.isVisible():
                self.pw_edit.setEnabled(True)
                self.pw_edit.setFocus()
        except RuntimeError:
            pass

    def _finish(self, master_password, paths, salt):
        try:
            iterations = nimbus.get_kdf_iterations(paths.meta_file)
            crypto = nimbus.EncryptionManager(master_password, salt, iterations=iterations)
            storage = nimbus.Storage(crypto, paths.data_file)
        except SystemExit:
            self._set_status_key("login_decrypt_err", theme.current()["danger"])
            return
        except Exception as e:
            self._apply_status(t("login_err", e=e), theme.current()["danger"])
            return
        self.login_success.emit(crypto, storage, paths)


# ---------------------------------------------------------------------------
# Register dialog
# ---------------------------------------------------------------------------

class RegisterDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("title_register"))
        self.setMinimumWidth(580)
        self.setModal(True)
        self.username = None
        self.restore_mode = False
        self.github_url = None
        self.github_token = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(36, 28, 36, 24)
        self.title_label = QLabel(t("title_register"))
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)
        layout.addSpacing(6)
        self.mode_seg = SegmentedControl(
            [("reg_mode_new", "new"), ("reg_mode_restore", "restore")], "new")
        self.mode_seg.value_changed.connect(self._on_mode_changed)
        layout.addWidget(self.mode_seg, alignment=Qt.AlignmentFlag.AlignCenter)

        self.lbl_username = QLabel(t("field_username")); layout.addWidget(self.lbl_username)
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText(t("ph_username"))
        self.username_edit.setMinimumHeight(42)
        layout.addWidget(self.username_edit)

        self.lbl_pw = QLabel(t("field_password")); layout.addWidget(self.lbl_pw)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText(t("ph_password_new"))
        self.password_edit.setMinimumHeight(42)
        layout.addWidget(self.password_edit)

        self.lbl_pw_confirm = QLabel(t("field_password_confirm")); layout.addWidget(self.lbl_pw_confirm)
        self.confirm_edit = QLineEdit()
        self.confirm_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_edit.setPlaceholderText(t("ph_password_confirm"))
        self.confirm_edit.setMinimumHeight(42)
        layout.addWidget(self.confirm_edit)

        self.lbl_github = QLabel(t("label_github_url")); layout.addWidget(self.lbl_github)
        self.github_edit = QLineEdit()
        self.github_edit.setPlaceholderText(t("ph_github_url"))
        self.github_edit.setMinimumHeight(42)
        layout.addWidget(self.github_edit)

        self.lbl_github_token = QLabel(t("label_github_token")); layout.addWidget(self.lbl_github_token)
        self.github_token_edit = QLineEdit()
        self.github_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.github_token_edit.setPlaceholderText(t("ph_github_token"))
        self.github_token_edit.setMinimumHeight(42)
        layout.addWidget(self.github_token_edit)

        self.token_hint = QLabel(t("gh_auth_help"))
        self.token_hint.setWordWrap(True)
        self.token_hint.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.token_hint)

        self.err_label = QLabel("")
        self.err_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.err_label.setVisible(False)
        self.err_label.setWordWrap(True)
        layout.addWidget(self.err_label)
        layout.addSpacing(6)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(14)
        btn_row.addStretch(1)
        self.cancel_btn = QPushButton(t("btn_cancel"))
        self.cancel_btn.setFixedSize(170, 46)
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)
        self.create_btn = QPushButton(t("btn_create"))
        self.create_btn.setFixedSize(170, 46)
        self.create_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create_btn.clicked.connect(self._on_create)
        btn_row.addWidget(self.create_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        theme.subscribe(lambda _: self._restyle())
        i18n.subscribe(self._retranslate)
        self._restyle()
        self.confirm_edit.returnPressed.connect(self._on_create)
        QTimer.singleShot(0, self.username_edit.setFocus)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
        super().mousePressEvent(event)

    def _on_mode_changed(self, value):
        self.restore_mode = (value == "restore")
        show_new = not self.restore_mode
        for w in (self.lbl_username, self.username_edit,
                  self.lbl_pw, self.password_edit,
                  self.lbl_pw_confirm, self.confirm_edit):
            w.setVisible(show_new)
        if self.restore_mode:
            self.setWindowTitle(t("title_restore"))
            self.title_label.setText(t("title_restore"))
            self.create_btn.setText(t("btn_restore"))
        else:
            self.setWindowTitle(t("title_register"))
            self.title_label.setText(t("title_register"))
            self.create_btn.setText(t("btn_create"))
        self.adjustSize()

    def _retranslate(self):
        try:
            if self.restore_mode:
                self.setWindowTitle(t("title_restore"))
                self.title_label.setText(t("title_restore"))
                self.create_btn.setText(t("btn_restore"))
            else:
                self.setWindowTitle(t("title_register"))
                self.title_label.setText(t("title_register"))
                self.create_btn.setText(t("btn_create"))
            self.lbl_username.setText(t("field_username"))
            self.lbl_pw.setText(t("field_password"))
            self.lbl_pw_confirm.setText(t("field_password_confirm"))
            self.lbl_github.setText(t("label_github_url"))
            self.lbl_github_token.setText(t("label_github_token"))
            self.token_hint.setText(t("gh_auth_help"))
            self.username_edit.setPlaceholderText(t("ph_username"))
            self.password_edit.setPlaceholderText(t("ph_password_new"))
            self.confirm_edit.setPlaceholderText(t("ph_password_confirm"))
            self.github_edit.setPlaceholderText(t("ph_github_url"))
            self.github_token_edit.setPlaceholderText(t("ph_github_token"))
            self.cancel_btn.setText(t("btn_cancel"))
        except RuntimeError:
            pass

    def _restyle(self):
        try:
            t_ = theme.current()
            self.token_hint.setStyleSheet(f"""
                            QLabel {{
                                background: {t_['input_bg']};
                                border: 1px solid {t_['input_border']};
                                border-radius: 6px;
                                color: {t_['text_sec']};
                                font-size: 11px;
                                font-family: "Consolas", "Monaco", monospace;
                                padding: 6px;
                            }}
                        """)
            self.setStyleSheet(build_qss(t_))
            self.title_label.setStyleSheet(
                f"font-size: 22px; font-weight: 700; color: {t_['text']}; background: transparent;")
            self.err_label.setStyleSheet(
                f"font-size: 18px; color: {t_['danger']}; background: transparent; padding: 6px;")
            self.create_btn.setStyleSheet(primary_btn_qss(t_))
        except RuntimeError:
            pass

    def _show_err(self, key=None, text=None):
        self.err_label.setText(t(key) if key else (text or ""))
        self.err_label.setVisible(True)

    def _hide_err(self):
        self.err_label.setVisible(False)

    def _on_create(self):
        self._hide_err()
        if self.restore_mode:
            url = self.github_edit.text().strip()
            token = self.github_token_edit.text().strip()
            if not url:
                self._show_err("reg_err_no_url"); return
            if not url.lower().startswith("https://"):
                self._show_err(text="URL должен начинаться с https://"); return
            if not token:
                self._show_err(text="Personal Access Token обязателен"); return
            self.github_url = url
            self.github_token = token
            self.accept()
            return
        username = self.username_edit.text().strip()
        pw = self.password_edit.text()
        confirm = self.confirm_edit.text()
        err = nimbus.validate_username(username)
        if err:
            self._show_err(f"reg_err_{err}"); return
        paths = nimbus.UserPaths(username)
        if paths.exists():
            self._show_err("reg_err_exists"); return
        if len(pw) < nimbus.MIN_MASTER_PASSWORD_LEN:
            self._show_err("login_min10"); return
        if pw != confirm:
            self._show_err("login_mismatch"); return
        try:
            paths.ensure_dir()
            salt = nimbus.load_or_create_salt(paths.salt_file)
            nimbus.save_meta(paths.meta_file, nimbus.KDF_ITERATIONS_V2)
            crypto = nimbus.EncryptionManager(pw, salt, iterations=nimbus.KDF_ITERATIONS_V2)
            nimbus.save_key_file(paths.key_file, crypto.encrypt(pw))
            storage = nimbus.Storage(crypto, paths.data_file)
            storage._save()
            try:
                user_settings = dict(DEFAULT_SETTINGS)
                url = self.github_edit.text().strip()
                if url:
                    user_settings["github_url"] = url
                    user_settings["github_enabled"] = True
                    user_settings["github_branch"] = "main"
                    token = self.github_token_edit.text().strip()
                    if token:
                        user_settings["github_token"] = token
                with open(paths.settings_file, 'w', encoding='utf-8') as f:
                    json.dump(user_settings, f, indent=2, ensure_ascii=False)
            except Exception:
                pass
            self.username = username
            self.accept()
        except Exception as e:
            self._show_err(text=t("reg_err_generic", e=e))


# ---------------------------------------------------------------------------
# RecordDialog
# ---------------------------------------------------------------------------

class RecordDialog(QDialog):
    def __init__(self, parent, title_key, record=None):
        super().__init__(parent)
        self.setWindowTitle(t(title_key))
        self.setMinimumWidth(640)
        self.setModal(True)
        self.record = record or {}
        self._title_key = title_key
        self._form_labels = []
        layout = QVBoxLayout(self)
        layout.setSpacing(18)
        layout.setContentsMargins(32, 30, 32, 26)
        form = QFormLayout()
        form.setSpacing(16)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.service_edit = QLineEdit(self.record.get("service", ""))
        self.service_edit.setPlaceholderText(t("ph_service"))
        self.service_edit.setMinimumHeight(40)
        lbl = QLabel(t("field_service")); self._form_labels.append((lbl, "field_service"))
        form.addRow(lbl, self.service_edit)

        self.username_edit = QLineEdit(self.record.get("username", ""))
        self.username_edit.setPlaceholderText(t("ph_login"))
        self.username_edit.setMinimumHeight(40)
        lbl = QLabel(t("field_login")); self._form_labels.append((lbl, "field_login"))
        form.addRow(lbl, self.username_edit)

        pw_layout = QHBoxLayout()
        pw_layout.setSpacing(8)
        self.password_edit = QLineEdit(self.record.get("password", ""))
        self.password_edit.setPlaceholderText(t("ph_password"))
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setMinimumHeight(40)
        pw_layout.addWidget(self.password_edit, 1)
        self.show_pw_btn = QPushButton(t("btn_show"))
        self.show_pw_btn.setFixedSize(110, 40)
        self.show_pw_btn.setCheckable(True)
        self.show_pw_btn.toggled.connect(self._toggle_pw_visibility)
        pw_layout.addWidget(self.show_pw_btn)
        self.gen_btn = QPushButton(t("btn_generate"))
        self.gen_btn.setFixedSize(150, 40)
        self.gen_btn.clicked.connect(self._generate_pw)
        pw_layout.addWidget(self.gen_btn)
        lbl = QLabel(t("field_password")); self._form_labels.append((lbl, "field_password"))
        form.addRow(lbl, pw_layout)

        self.desc_edit = QLineEdit(self.record.get("description", ""))
        self.desc_edit.setPlaceholderText(t("ph_description"))
        self.desc_edit.setMinimumHeight(40)
        lbl = QLabel(t("field_description")); self._form_labels.append((lbl, "field_description"))
        form.addRow(lbl, self.desc_edit)

        layout.addLayout(form)
        layout.addSpacing(6)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(14)
        btn_row.addStretch(1)
        self.cancel_btn = QPushButton(t("btn_cancel"))
        self.cancel_btn.setFixedSize(170, 46)
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)
        self.save_btn = QPushButton(t("btn_save"))
        self.save_btn.setFixedSize(170, 46)
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setStyleSheet(primary_btn_qss(theme.current()))
        self.save_btn.clicked.connect(self._validate_and_accept)
        btn_row.addWidget(self.save_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        theme.subscribe(lambda _: self._restyle())
        i18n.subscribe(self._retranslate)
        self._restyle()
        QTimer.singleShot(0, self._clear_focus)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
        super().mousePressEvent(event)

    def _clear_focus(self):
        try:
            for e in (self.service_edit, self.username_edit, self.password_edit, self.desc_edit):
                e.deselect(); e.clearFocus()
            self.setFocus()
        except RuntimeError:
            pass

    def _retranslate(self):
        try:
            self.setWindowTitle(t(self._title_key))
            for lbl, key in self._form_labels:
                lbl.setText(t(key))
            self.show_pw_btn.setText(t("btn_hide") if self.show_pw_btn.isChecked() else t("btn_show"))
            self.gen_btn.setText(t("btn_generate"))
            self.cancel_btn.setText(t("btn_cancel"))
            self.save_btn.setText(t("btn_save"))
            self.service_edit.setPlaceholderText(t("ph_service"))
            self.username_edit.setPlaceholderText(t("ph_login"))
            self.password_edit.setPlaceholderText(t("ph_password"))
            self.desc_edit.setPlaceholderText(t("ph_description"))
        except RuntimeError:
            pass

    def _restyle(self):
        try:
            t_ = theme.current()
            self.setStyleSheet(build_qss(t_))
            self.save_btn.setStyleSheet(primary_btn_qss(t_))
        except RuntimeError:
            pass

    def _toggle_pw_visibility(self, checked):
        self.password_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password)
        self.show_pw_btn.setText(t("btn_hide") if checked else t("btn_show"))

    def _generate_pw(self):
        pw = nimbus.generate_password(settings.get("password_length", 18))
        self.password_edit.setText(pw)
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Normal)
        self.show_pw_btn.setChecked(True)
        QTimer.singleShot(3000, lambda: (
            self.password_edit.setEchoMode(QLineEdit.EchoMode.Password),
            self.show_pw_btn.setChecked(False)))

    def _validate_and_accept(self):
        if not self.service_edit.text().strip():
            self._err(t("err_service_required")); return
        if not self.username_edit.text().strip():
            self._err(t("err_login_required")); return
        if not self.password_edit.text().strip():
            self._err(t("err_password_required")); return
        self.accept()

    def _err(self, msg):
        d = MessageDialog(self, t("title_error"), msg, kind="danger",
                          confirm_text=t("btn_ok"), cancel_text=None)
        d.exec()

    def get_record(self):
        return {
            "service": self.service_edit.text().strip(),
            "username": self.username_edit.text().strip(),
            "password": self.password_edit.text().strip(),
            "description": self.desc_edit.text().strip(),
        }


# ---------------------------------------------------------------------------
# Message / Confirm dialogs
# ---------------------------------------------------------------------------

class MessageDialog(QDialog):
    def __init__(self, parent, title, message, kind="info", confirm_text="OK", cancel_text=None):
        super().__init__(parent)
        self.kind = kind
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(32, 28, 32, 26)
        self.title_label = QLabel(title); self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        self.msg_label = QLabel(message); self.msg_label.setWordWrap(True)
        layout.addWidget(self.msg_label)
        layout.addSpacing(12)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(14); btn_row.addStretch(1)
        self.cancel_btn = None
        if cancel_text is not None:
            self.cancel_btn = QPushButton(cancel_text)
            self.cancel_btn.setFixedSize(160, 44)
            self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.cancel_btn.clicked.connect(self.reject)
            btn_row.addWidget(self.cancel_btn)
        self.confirm_btn = QPushButton(confirm_text)
        self.confirm_btn.setFixedSize(160, 44)
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.confirm_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)
        theme.subscribe(lambda _: self._restyle())
        self._restyle()
        self.confirm_btn.setFocus()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
        super().mousePressEvent(event)

    def _restyle(self):
        try:
            t_ = theme.current()
            self.setStyleSheet(build_qss(t_))
            self.title_label.setStyleSheet(
                f"font-size: 20px; font-weight: 700; color: {t_['text']}; background: transparent;")
            self.msg_label.setStyleSheet(
                f"font-size: 14px; color: {t_['text_sec']}; background: transparent;")
            self.confirm_btn.setStyleSheet(
                danger_btn_qss(t_) if self.kind == "danger" else primary_btn_qss(t_))
        except RuntimeError:
            pass


class ConfirmMasterDialog(QDialog):
    def __init__(self, parent, salt, key_file, action_key="confirm_pw_action_default"):
        super().__init__(parent)
        self.salt = salt
        self.key_file = key_file
        self._action_key = action_key
        self._err_key = None
        self.setWindowTitle(t("title_confirm"))
        self.setMinimumWidth(440)
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(32, 30, 32, 26)
        self.title_label = QLabel(t("title_confirm"))
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)
        self.sub_label = QLabel(t("confirm_pw_sub", a=t(action_key)))
        self.sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sub_label.setWordWrap(True)
        layout.addWidget(self.sub_label)
        layout.addSpacing(8)
        self.pw_edit = QLineEdit()
        self.pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw_edit.setPlaceholderText(t("ph_master"))
        self.pw_edit.setMinimumHeight(44)
        self.pw_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.pw_edit)
        self.err_label = QLabel("")
        self.err_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.err_label.setVisible(False)
        layout.addWidget(self.err_label)
        layout.addSpacing(8)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(14); btn_row.addStretch(1)
        self.cancel_btn = QPushButton(t("btn_cancel"))
        self.cancel_btn.setFixedSize(160, 44)
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)
        self.ok_btn = QPushButton(t("btn_confirm"))
        self.ok_btn.setFixedSize(160, 44)
        self.ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ok_btn.clicked.connect(self._verify)
        btn_row.addWidget(self.ok_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)
        theme.subscribe(lambda _: self._restyle())
        i18n.subscribe(self._retranslate)
        self._restyle()
        self.pw_edit.returnPressed.connect(self._verify)
        self.pw_edit.textChanged.connect(lambda _: self._clear_err())
        self.pw_edit.setFocus()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
        super().mousePressEvent(event)

    def _retranslate(self):
        try:
            self.setWindowTitle(t("title_confirm"))
            self.title_label.setText(t("title_confirm"))
            self.sub_label.setText(t("confirm_pw_sub", a=t(self._action_key)))
            self.pw_edit.setPlaceholderText(t("ph_master"))
            self.cancel_btn.setText(t("btn_cancel"))
            self.ok_btn.setText(t("btn_confirm"))
            if self._err_key:
                self.err_label.setText(t(self._err_key))
        except RuntimeError:
            pass

    def _restyle(self):
        try:
            t_ = theme.current()
            self.setStyleSheet(build_qss(t_))
            self.title_label.setStyleSheet(
                f"font-size: 20px; font-weight: 700; color: {t_['text']}; background: transparent;")
            self.sub_label.setStyleSheet(
                f"font-size: 14px; color: {t_['text_sec']}; background: transparent;")
            self.err_label.setStyleSheet(
                f"font-size: 18px; color: {t_['danger']}; background: transparent; padding: 4px;")
            self.ok_btn.setStyleSheet(primary_btn_qss(t_))
        except RuntimeError:
            pass

    def _clear_err(self):
        if self._err_key:
            self._err_key = None
            self.err_label.setVisible(False)

    def _show_err(self, key):
        self._err_key = key
        self.err_label.setText(t(key))
        self.err_label.setVisible(True)

    def _verify(self):
        pw = self.pw_edit.text()
        if not pw:
            self._show_err("confirm_pw_need"); return
        if nimbus.verify_master_password(pw, self.salt, self.key_file):
            self.accept()
        else:
            self._show_err("confirm_pw_err")
            self.pw_edit.clear()
            self.pw_edit.setFocus()


# ---------------------------------------------------------------------------
# Settings — 3 вкладки, карточки, кнопка Test справа внизу
# ---------------------------------------------------------------------------

class SettingsDialog(QDialog):
    _test_finished = pyqtSignal(bool, str, str, str)

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(t("title_settings"))
        self.setMinimumSize(820, 660)
        self.setModal(True)
        self._label_widgets = []
        self._section_widgets = []
        self._tested_pair = None
        self._testing = False
        self._orig_lang = settings.get("language", "ru")
        self._orig_theme = settings.get("theme", "system")

        self._test_finished.connect(self._on_test_result)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(18)

        self.title_label = QLabel(t("title_settings"))
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)

        self.tabs = QTabWidget()
        try:
            self.tabs.tabBar().setExpanding(False)
        except Exception:
            pass
        self.tabs.addTab(self._build_general_tab(), t("tab_general"))
        self.tabs.addTab(self._build_security_tab(), t("tab_security"))
        self.tabs.addTab(self._build_github_tab(), t("tab_github"))
        layout.addWidget(self.tabs, 1)
        self.lang_seg.value_changed.connect(self._on_preview_language)
        self.theme_seg.value_changed.connect(self._on_preview_theme)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(14); btn_row.addStretch(1)
        self.cancel_btn = QPushButton(t("btn_cancel"))
        self.cancel_btn.setFixedSize(160, 44)
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)
        self.save_btn = QPushButton(t("btn_save"))
        self.save_btn.setFixedSize(160, 44)
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.clicked.connect(self._save)
        btn_row.addWidget(self.save_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        actual = is_autostart_enabled()
        if actual != settings.get("autostart"):
            settings.set("autostart", actual)
            self.autostart_toggle.setChecked(actual)
        self._on_autostart_toggle(self.autostart_toggle.isChecked())

        theme.subscribe(lambda _: self._restyle())
        i18n.subscribe(self._retranslate)
        self._restyle()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
        super().mousePressEvent(event)

    def _tab_container(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(16)
        return w, v

    def _make_card(self, title_key):
        card = QFrame()
        card.setObjectName("settingsCard")
        v = QVBoxLayout(card)
        v.setContentsMargins(24, 18, 24, 22)
        v.setSpacing(14)

        lbl = QLabel(t(title_key))
        lbl.setObjectName("settingsCardTitle")
        self._section_widgets.append((lbl, title_key))
        v.addWidget(lbl)

        grid = QGridLayout()
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(14)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)

        return card, grid

    def _center_in(self, widget, width):
        w = QWidget()
        w.setFixedWidth(width)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addStretch(1)
        lay.addWidget(widget)
        lay.addStretch(1)
        return w

    def _build_general_tab(self):
        w, v = self._tab_container()

        card1, grid1 = self._make_card("section_appearance")

        lbl = QLabel(t("label_language")); self._label_widgets.append((lbl, "label_language"))
        grid1.addWidget(lbl, 0, 0)
        self.lang_seg = SegmentedControl(
            [("seg_lang_ru", "ru"), ("seg_lang_en", "en")],
            settings.get("language", "ru"))
        grid1.addWidget(self.lang_seg, 0, 1, alignment=Qt.AlignmentFlag.AlignLeft)

        lbl = QLabel(t("label_theme")); self._label_widgets.append((lbl, "label_theme"))
        grid1.addWidget(lbl, 1, 0)
        self.theme_seg = SegmentedControl(
            [("seg_theme_system", "system"), ("seg_theme_light", "light"),
             ("seg_theme_dark", "dark")],
            settings.get("theme", "system"))
        grid1.addWidget(self.theme_seg, 1, 1, alignment=Qt.AlignmentFlag.AlignLeft)

        v.addWidget(card1)

        card2, grid2 = self._make_card("section_startup")

        lbl = QLabel(t("label_autostart")); self._label_widgets.append((lbl, "label_autostart"))
        grid2.addWidget(lbl, 0, 0)
        self.autostart_toggle = ToggleSwitch(settings.get("autostart", False))
        self.autostart_toggle.toggled.connect(self._on_autostart_toggle)
        grid2.addWidget(self.autostart_toggle, 0, 1, alignment=Qt.AlignmentFlag.AlignLeft)

        lbl = QLabel(t("label_start_min")); self._label_widgets.append((lbl, "label_start_min"))
        grid2.addWidget(lbl, 1, 0)
        self.start_min_toggle = ToggleSwitch(settings.get("start_minimized", False))
        grid2.addWidget(self.start_min_toggle, 1, 1, alignment=Qt.AlignmentFlag.AlignLeft)

        v.addWidget(card2)
        v.addStretch(1)
        return w

    def _build_security_tab(self):
        w, v = self._tab_container()
        card, grid = self._make_card("section_security")

        NUM_W = 100
        rows = [
            ("password_length", "label_pw_len", settings.get("password_length", 18), 8, 128),
            ("clipboard_timeout", "label_clip_timeout", settings.get("clipboard_timeout", 30), 5, 600),
            ("session_timeout", "label_session_timeout", settings.get("session_timeout", 300), 30, 7200),
        ]
        self._num_edits = {}
        for i, (key, label_key, value, min_v, max_v) in enumerate(rows):
            lbl = QLabel(t(label_key)); self._label_widgets.append((lbl, label_key))
            grid.addWidget(lbl, i, 0)
            edit = QLineEdit(str(value))
            edit.setValidator(QIntValidator(min_v, max_v, self))
            edit.setFixedWidth(NUM_W)
            edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            edit.setMinimumHeight(40)
            grid.addWidget(edit, i, 1, alignment=Qt.AlignmentFlag.AlignLeft)
            self._num_edits[key] = edit

        lbl = QLabel(t("label_confirm_delete")); self._label_widgets.append((lbl, "label_confirm_delete"))
        grid.addWidget(lbl, 3, 0)
        self.confirm_delete_toggle = ToggleSwitch(settings.get("confirm_delete", True))
        grid.addWidget(self._center_in(self.confirm_delete_toggle, NUM_W), 3, 1,
                       alignment=Qt.AlignmentFlag.AlignLeft)

        lbl = QLabel(t("label_minimize_tray")); self._label_widgets.append((lbl, "label_minimize_tray"))
        grid.addWidget(lbl, 4, 0)
        self.minimize_tray_toggle = ToggleSwitch(settings.get("minimize_to_tray", True))
        grid.addWidget(self._center_in(self.minimize_tray_toggle, NUM_W), 4, 1,
                       alignment=Qt.AlignmentFlag.AlignLeft)

        v.addWidget(card)
        v.addStretch(1)
        return w

    def _build_github_tab(self):
        w, v = self._tab_container()
        card, grid = self._make_card("section_sync")

        lbl = QLabel(t("label_github_enabled")); self._label_widgets.append((lbl, "label_github_enabled"))
        grid.addWidget(lbl, 0, 0)
        self.github_enabled_toggle = ToggleSwitch(settings.get("github_enabled", False))
        self.github_enabled_toggle.toggled.connect(self._on_github_toggle)
        grid.addWidget(self.github_enabled_toggle, 0, 1, alignment=Qt.AlignmentFlag.AlignLeft)

        lbl = QLabel(t("label_github_url_field")); self._label_widgets.append((lbl, "label_github_url_field"))
        grid.addWidget(lbl, 1, 0)
        self.github_url_edit = QLineEdit(settings.get("github_url", ""))
        self.github_url_edit.setPlaceholderText(t("ph_github_url"))
        self.github_url_edit.setMinimumHeight(40)
        grid.addWidget(self.github_url_edit, 1, 1)

        lbl = QLabel(t("label_github_token")); self._label_widgets.append((lbl, "label_github_token"))
        grid.addWidget(lbl, 2, 0)
        token_row = QHBoxLayout()
        token_row.setSpacing(8)
        self.github_token_edit = QLineEdit(settings.get("github_token", ""))
        self.github_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.github_token_edit.setPlaceholderText(t("ph_github_token"))
        self.github_token_edit.setMinimumHeight(40)
        token_row.addWidget(self.github_token_edit, 1)
        self.github_token_show = QPushButton(t("btn_show"))
        self.github_token_show.setCheckable(True)
        self.github_token_show.setFixedSize(110, 40)
        self.github_token_show.setCursor(Qt.CursorShape.PointingHandCursor)
        self.github_token_show.toggled.connect(self._toggle_token_show)
        token_row.addWidget(self.github_token_show)
        token_wrap = QWidget()
        token_wrap.setLayout(token_row)
        token_row.setContentsMargins(0, 0, 0, 0)
        grid.addWidget(token_wrap, 2, 1)

        FIELD_W = 140

        lbl = QLabel(t("label_github_branch")); self._label_widgets.append((lbl, "label_github_branch"))
        grid.addWidget(lbl, 3, 0)
        self.github_branch_edit = QLineEdit(settings.get("github_branch", "main"))
        self.github_branch_edit.setFixedWidth(FIELD_W)
        self.github_branch_edit.setMinimumHeight(40)
        self.github_branch_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.github_branch_edit, 3, 1, alignment=Qt.AlignmentFlag.AlignLeft)

        lbl = QLabel(t("label_github_interval")); self._label_widgets.append((lbl, "label_github_interval"))
        grid.addWidget(lbl, 4, 0)
        self.github_interval_edit = QLineEdit(str(settings.get("github_sync_interval", 600)))
        self.github_interval_edit.setValidator(QIntValidator(60, 86400, self))
        self.github_interval_edit.setFixedWidth(FIELD_W)
        self.github_interval_edit.setMinimumHeight(40)
        self.github_interval_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.github_interval_edit, 4, 1, alignment=Qt.AlignmentFlag.AlignLeft)

        lower = QWidget()
        lower_lay = QHBoxLayout(lower)
        lower_lay.setContentsMargins(0, 0, 0, 0)
        lower_lay.setSpacing(16)

        self._github_hint = QLabel(t("gh_auth_help"))
        self._github_hint.setWordWrap(True)
        self._github_hint.setMinimumHeight(90)
        self._github_hint.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        lower_lay.addWidget(self._github_hint, 1)

        right = QWidget()
        right.setFixedWidth(340)
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)
        right_lay.addStretch(1)

        status_row = QHBoxLayout()
        status_row.setSpacing(12)

        self.github_test_label = QLabel("")
        self.github_test_label.setWordWrap(True)
        self.github_test_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        status_row.addWidget(self.github_test_label, 1)

        self.github_test_btn = QPushButton(t("btn_test_connection"))
        self.github_test_btn.setMinimumHeight(38)
        self.github_test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.github_test_btn.clicked.connect(self._on_test_connection)
        status_row.addWidget(self.github_test_btn, 0)

        right_lay.addLayout(status_row)

        lower_lay.addWidget(right, 0)
        grid.addWidget(lower, 5, 0, 1, 2)

        grid.setRowStretch(6, 1)

        v.addWidget(card)
        v.addStretch(1)
        self._on_github_toggle(self.github_enabled_toggle.isChecked())
        return w

    def _toggle_token_show(self, checked):
        self.github_token_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password)
        self.github_token_show.setText(t("btn_hide") if checked else t("btn_show"))

    def _on_autostart_toggle(self, checked):
        self.start_min_toggle.setEnabled(checked)
        if not checked and self.start_min_toggle.isChecked():
            self.start_min_toggle.setChecked(False)

    def _on_github_toggle(self, checked):
        for w in (self.github_url_edit, self.github_token_edit,
                  self.github_branch_edit, self.github_interval_edit,
                  self.github_test_btn, self.github_token_show):
            w.setEnabled(checked)
        if not checked:
            self._tested_pair = None
            self.github_token_show.setChecked(False)

    def _on_test_connection(self):
        url = self.github_url_edit.text().strip()
        token = self.github_token_edit.text().strip()
        if not url:
            self._set_test_status(False, t("gh_test_need_url")); return
        if not token:
            self._set_test_status(False, t("gh_test_need_token")); return

        self._tested_pair = None
        self._testing = True
        self._set_test_status(None, t("gh_test_testing"))
        self.github_test_btn.setEnabled(False)

        def worker():
            try:
                ok, msg = nimbus_sync.test_connection(url, token, timeout=30)
            except Exception as e:
                ok, msg = False, f"exception: {e}"
            try:
                self._test_finished.emit(ok, msg, url, token)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()
        QTimer.singleShot(35000, lambda: self._hard_timeout(url, token))

    def _hard_timeout(self, url, token):
        try:
            if self._testing:
                self._on_test_result(False, "timeout 35s (UI)", url, token)
        except RuntimeError:
            pass

    def _on_test_result(self, ok, msg, url, token):
        try:
            self._testing = False
            self.github_test_btn.setEnabled(self.github_enabled_toggle.isChecked())
            if ok:
                self._tested_pair = (url, token)
                self._set_test_status(True, t("gh_test_ok"))
            else:
                self._set_test_status(False, t("gh_test_fail", err=msg))
        except RuntimeError:
            pass

    def _set_test_status(self, ok, text):
        try:
            t_ = theme.current()
            if ok is True:
                color = "#16a34a" if theme.name == "light" else "#22c55e"
            elif ok is False:
                color = t_["danger"]
            else:
                color = t_["text_muted"]
            self.github_test_label.setText(text)
            self.github_test_label.setStyleSheet(
                f"font-size: 12px; color: {color}; background: transparent;")
        except RuntimeError:
            pass

    def _retranslate(self):
        try:
            self.setWindowTitle(t("title_settings"))
            self.title_label.setText(t("title_settings"))
            self.tabs.setTabText(0, t("tab_general"))
            self.tabs.setTabText(1, t("tab_security"))
            self.tabs.setTabText(2, t("tab_github"))
            for lbl, key in self._label_widgets:
                lbl.setText(t(key))
            for lbl, key in self._section_widgets:
                lbl.setText(t(key))
            self.cancel_btn.setText(t("btn_cancel"))
            self.save_btn.setText(t("btn_save"))
            self.github_url_edit.setPlaceholderText(t("ph_github_url"))
            self.github_token_edit.setPlaceholderText(t("ph_github_token"))
            self.github_test_btn.setText(t("btn_test_connection"))
            self.github_token_show.setText(
                t("btn_hide") if self.github_token_show.isChecked() else t("btn_show"))
            self._github_hint.setText(t("gh_auth_help"))
        except RuntimeError:
            pass

    def _restyle(self):
        try:
            t_ = theme.current()
            self.setStyleSheet(build_qss(t_))
            self.title_label.setStyleSheet(
                f"font-size: 24px; font-weight: 700; color: {t_['text']}; background: transparent;")
            for lbl, _ in self._label_widgets:
                lbl.setStyleSheet(f"font-size: 15px; color: {t_['text']}; background: transparent;")
            for lbl, _ in self._section_widgets:
                lbl.setStyleSheet(
                    f"font-size: 11px; font-weight: 700; color: {t_['text_muted']}; "
                    f"letter-spacing: 1.5px; background: transparent;")
            try:
                self._github_hint.setStyleSheet(
                    f"font-size: 11px; color: {t_['text_muted']}; "
                    f"background: transparent; padding: 0;")
            except Exception:
                pass
            self.save_btn.setStyleSheet(primary_btn_qss(t_))
        except RuntimeError:
            pass

    def _save(self):
        lang = self.lang_seg.value() or "ru"
        theme_mode = self.theme_seg.value() or "system"
        autostart = self.autostart_toggle.isChecked()
        start_min = self.start_min_toggle.isChecked() and autostart
        try:
            pw_len = int(self._num_edits["password_length"].text() or "18")
        except ValueError:
            pw_len = 18
        pw_len = max(8, min(128, pw_len))
        try:
            clip_t = int(self._num_edits["clipboard_timeout"].text() or "30")
        except ValueError:
            clip_t = 30
        clip_t = max(5, min(600, clip_t))
        try:
            sess_t = int(self._num_edits["session_timeout"].text() or "300")
        except ValueError:
            sess_t = 300
        sess_t = max(30, min(7200, sess_t))
        confirm_delete = self.confirm_delete_toggle.isChecked()
        minimize_tray = self.minimize_tray_toggle.isChecked()
        github_enabled = self.github_enabled_toggle.isChecked()
        github_url = self.github_url_edit.text().strip()
        github_token = self.github_token_edit.text().strip()
        github_branch = self.github_branch_edit.text().strip() or "main"
        try:
            github_interval = int(self.github_interval_edit.text() or "600")
        except ValueError:
            github_interval = 600
        github_interval = max(60, min(86400, github_interval))

        if github_enabled:
            if not github_url:
                QMessageBox.warning(self, t("title_error"),
                                    t("gh_test_need_url") + "\n\n" + t("gh_save_fail"))
                return
            if not github_url.lower().startswith("https://"):
                QMessageBox.warning(self, t("title_error"),
                                    "URL должен начинаться с https://\n\n" + t("gh_save_fail"))
                return
            if not github_token:
                QMessageBox.warning(self, t("title_error"),
                                    t("gh_test_need_token") + "\n\n" + t("gh_save_fail"))
                return
            if self._tested_pair != (github_url, github_token):
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                try:
                    ok, msg = nimbus_sync.test_connection(github_url, github_token, timeout=30)
                finally:
                    QApplication.restoreOverrideCursor()
                if not ok:
                    QMessageBox.critical(self, t("title_error"),
                                         t("gh_test_fail", err=msg) + "\n\n" + t("gh_save_fail"))
                    return
                self._tested_pair = (github_url, github_token)

        old_auto = settings.get("autostart", False)
        old_min = settings.get("start_minimized", False)

        settings.update({
            "language": lang, "theme": theme_mode,
            "autostart": autostart, "start_minimized": start_min,
            "password_length": pw_len, "clipboard_timeout": clip_t,
            "session_timeout": sess_t, "confirm_delete": confirm_delete,
            "minimize_to_tray": minimize_tray,
            "github_enabled": github_enabled, "github_url": github_url,
            "github_token": github_token, "github_branch": github_branch,
            "github_sync_interval": github_interval,
        })
        theme.set_mode(theme_mode, save=False)
        i18n.set_language(lang)
        if autostart != old_auto or (autostart and start_min != old_min):
            set_autostart(autostart)
        nimbus.CLIPBOARD_CLEAR_SECONDS = clip_t
        nimbus.SESSION_TIMEOUT = sess_t
        self.accept()

    def _on_preview_language(self, lang):
        if lang in ("ru", "en"):
            i18n.set_language(lang)

    def _on_preview_theme(self, mode):
        if mode in ("system", "light", "dark"):
            theme.set_mode(mode, save=False)

    def reject(self):
        try:
            theme.set_mode(self._orig_theme, save=False)
            i18n.set_language(self._orig_lang)
        except Exception as e:
            print(f"[settings] revert: {e}")
        super().reject()


# ---------------------------------------------------------------------------
# MainWindow
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    _sync_trigger = pyqtSignal()
    _sync_reload = pyqtSignal()
    _sync_refresh = pyqtSignal()
    _sync_retry = pyqtSignal()
    _sync_status = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Nimbus")
        self.setWindowIcon(load_app_icon())
        self.setMinimumSize(1000, 640)
        self.resize(1200, 760)

        self.crypto = None
        self.storage = None
        self.session = nimbus.Session()
        self._last_activity = time.time()
        self._real_quit = False
        self._tray_hint_shown = False
        self._settings_btn = None
        self._top_frame = None
        self._add_btn = None

        self._git_sync = None
        self._sync_in_progress = False
        self._sync_pending = False
        self._sync_indicator = None
        self._sync_config = None
        self._sync_last_error = False
        self._sync_last_error_text = ""
        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self._trigger_sync)

        self._sync_trigger.connect(self._trigger_sync)
        self._sync_reload.connect(self._reload_from_disk)
        self._sync_refresh.connect(self._refresh_sync_indicator)
        self._sync_retry.connect(self._trigger_sync)
        self._sync_status.connect(self._show_status)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.login_view = LoginView()
        self.login_view.login_success.connect(self._on_login_success)
        self.stack.addWidget(self.login_view)

        self.main_widget = QWidget()
        self.main_layout = QVBoxLayout(self.main_widget)
        self.main_layout.setContentsMargins(24, 20, 24, 24)
        self.main_layout.setSpacing(16)
        self.stack.addWidget(self.main_widget)

        self._idle_timer = QTimer()
        self._idle_timer.timeout.connect(self._check_idle)
        self._idle_timer.start(5000)

        theme.subscribe(self._on_theme_changed)
        i18n.subscribe(self._on_lang_changed)
        self._apply_theme()
        try:
            QApplication.styleHints().colorSchemeChanged.connect(
                theme.on_system_color_scheme_changed)
        except Exception:
            pass
        QApplication.instance().installEventFilter(self)
        self._setup_tray()
        QTimer.singleShot(150, self._ensure_user)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            try:
                if hasattr(self, "table"):
                    self.table.clearSelection()
            except RuntimeError:
                pass
        super().mousePressEvent(event)

    def _ensure_user(self):
        if not nimbus.list_existing_users():
            self._initial_register()

    def _initial_register(self):
        dlg = RegisterDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            QApplication.instance().quit()
            return
        if dlg.restore_mode and dlg.github_url:
            try:
                username = nimbus_sync.clone_from_github(
                    dlg.github_url, _SCRIPT_DIR, token=dlg.github_token or None)
            except Exception as e:
                self.login_view.show_text(t("status_sync_err", e=e),
                                          theme.current()["danger"])
                return
            paths = nimbus.UserPaths(username)
            s = load_settings(paths.settings_file)
            s["github_url"] = dlg.github_url
            s["github_enabled"] = True
            s["github_branch"] = "main"
            if dlg.github_token:
                s["github_token"] = dlg.github_token
            save_settings(paths.settings_file, s)
            self.login_view.show_text(t("restore_ok", name=username),
                                      theme.current()["accent"])
            return
        if dlg.username:
            self.login_view.show_text(t("reg_ok", name=dlg.username),
                                      theme.current()["accent"])

    def eventFilter(self, obj, event):
        et = event.type()
        if et in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                  QEvent.Type.MouseMove, QEvent.Type.KeyPress, QEvent.Type.KeyRelease,
                  QEvent.Type.Wheel, QEvent.Type.TouchBegin, QEvent.Type.TouchUpdate):
            self._touch()
        return super().eventFilter(obj, event)

    def showEvent(self, e):
        self._touch()
        return super().showEvent(e)

    def _touch(self):
        self._last_activity = time.time()

    def _check_idle(self):
        if not self.session.auth:
            return
        if time.time() - self._last_activity > nimbus.SESSION_TIMEOUT:
            self._logout(expired=True)

    def _setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(load_app_icon())
        self.tray_icon.setToolTip("Nimbus")
        menu = QMenu()
        self._tray_open_action = QAction(t("tray_open"), self)
        self._tray_open_action.triggered.connect(self._show_from_tray)
        menu.addAction(self._tray_open_action)
        menu.addSeparator()
        self._tray_quit_action = QAction(t("tray_quit"), self)
        self._tray_quit_action.triggered.connect(self._quit_app)
        menu.addAction(self._tray_quit_action)
        self._tray_menu = menu
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self._show_from_tray()

    def _show_from_tray(self):
        self.showNormal(); self.raise_(); self.activateWindow()

    def _quit_app(self):
        if self.session.auth:
            try:
                self._logout(expired=False)
            except Exception:
                pass
        self._real_quit = True
        try:
            self.tray_icon.hide()
        except Exception:
            pass
        QApplication.instance().quit()

    def closeEvent(self, event):
        if self._real_quit:
            event.accept(); return
        if not settings.get("minimize_to_tray", True):
            if self.session.auth:
                try:
                    self._logout(expired=False)
                except Exception:
                    pass
            self._real_quit = True
            try:
                self.tray_icon.hide()
            except Exception:
                pass
            event.accept()
            QApplication.instance().quit()
            return
        event.ignore()
        was_auth = self.session.auth
        if was_auth:
            try:
                self._logout(expired=False)
            except Exception as e:
                print(f"[tray] logout error: {e}")
        self.hide()
        if not self._tray_hint_shown and self.tray_icon.supportsMessages():
            try:
                msg = t("tray_min_auth") if was_auth else t("tray_min")
                self.tray_icon.showMessage("Nimbus", msg + t("tray_min_hint"),
                                           QSystemTrayIcon.MessageIcon.Information, 4000)
                self._tray_hint_shown = True
            except Exception:
                pass

    def _on_theme_changed(self, _):
        try:
            self._apply_theme()
            self._restyle_main()
        except Exception as e:
            print(f"[main] theme: {e}")

    def _on_lang_changed(self):
        try:
            if self._tray_open_action:
                self._tray_open_action.setText(t("tray_open"))
            if self._tray_quit_action:
                self._tray_quit_action.setText(t("tray_quit"))
            self._retranslate_main()
        except Exception as e:
            print(f"[main] lang: {e}")

    def _apply_theme(self):
        t_ = theme.current()
        self.setStyleSheet(build_qss(t_) + f"QMainWindow {{ background: {t_['window_bg']}; }}")

    def _restyle_main(self):
        try:
            t_ = theme.current()
            if self._top_frame:
                self._top_frame.setStyleSheet(
                    f"QFrame {{ background: {t_['top_panel']}; "
                    f"border: 1px solid {t_['card_border']}; border-radius: 6px; }}")
            if self._add_btn:
                self._add_btn.setStyleSheet(primary_btn_qss(t_))
        except RuntimeError:
            pass

    def _retranslate_main(self):
        for attr, key in [("search_edit", None), ("_logout_btn", "btn_logout"),
                          ("_add_btn", "btn_create"), ("_import_btn", "btn_import"),
                          ("_export_text_btn", "btn_export_text"),
                          ("_export_archive_btn", "btn_export_archive"),
                          ("edit_btn", "btn_edit"), ("copy_btn", "btn_copy_password"),
                          ("delete_btn", "btn_delete")]:
            w = getattr(self, attr, None)
            if w is None:
                continue
            try:
                if attr == "search_edit":
                    w.setPlaceholderText(t("search_placeholder"))
                else:
                    w.setText(t(key))
            except (RuntimeError, AttributeError):
                pass
        try:
            self._settings_btn.setText(t("btn_settings"))
        except (RuntimeError, AttributeError):
            pass
        try:
            self.model.refresh_headers()
            self._update_count()
        except (RuntimeError, AttributeError):
            pass

    # --- sync ---

    def _setup_sync_after_login(self, paths):
        try:
            self._sync_timer.stop()
        except Exception:
            pass
        self._git_sync = None
        self._sync_in_progress = False
        self._sync_pending = False
        self._sync_last_error = False
        self._sync_last_error_text = ""

        if not (settings.get("github_enabled") and settings.get("github_url")
                and settings.get("github_token")):
            self._sync_config = None
            self._refresh_sync_indicator()
            return

        self._git_sync = nimbus_sync.GitSync(
            repo_dir=_SCRIPT_DIR,
            remote_url=settings.get("github_url"),
            username=paths.username,
            branch=settings.get("github_branch", "main"),
            token=settings.get("github_token") or None,
        )
        interval = max(60, int(settings.get("github_sync_interval", 600)))
        self._sync_timer.start(interval * 1000)
        self._sync_config = (
            settings.get("github_enabled"),
            settings.get("github_url"),
            settings.get("github_token"),
            settings.get("github_branch"),
            settings.get("github_sync_interval"),
        )
        self._refresh_sync_indicator()
        QTimer.singleShot(200, self._trigger_sync)

    def _refresh_sync_indicator(self):
        if not self._sync_indicator:
            return
        if not self._git_sync:
            self._sync_indicator.set_state(SyncIndicator.STATE_OFF);
            return
        if self._sync_in_progress:
            self._sync_indicator.set_state(SyncIndicator.STATE_SYNCING);
            return
        last = self._git_sync.get_last_sync_time()
        if self._sync_last_error:
            self._sync_indicator.set_state(
                SyncIndicator.STATE_ERROR, last,
                self._sync_last_error_text or None,
            )
        else:
            self._sync_indicator.set_state(SyncIndicator.STATE_OK, last)

    def _trigger_sync(self):
        if not self._git_sync or not self.storage:
            return
        if self._sync_in_progress:
            self._sync_pending = True
            return
        self._sync_in_progress = True
        self._sync_pending = False
        if self._sync_indicator:
            self._sync_indicator.set_state(SyncIndicator.STATE_SYNCING)
        threading.Thread(target=self._sync_worker, daemon=True).start()

    def _sync_worker(self):
        need_again = False
        try:
            res = self._git_sync.sync(self.storage, log=print)
            status = res.get("status", "")
            is_error = status.startswith("error")
            self._sync_last_error = is_error
            if is_error:
                self._sync_last_error_text = (
                    status[7:] if status.startswith("error: ") else status
                )
                print(f"[sync] {status}")
                self._sync_status.emit(
                    f"Sync: {self._sync_last_error_text[:80]}"
                )
            else:
                self._sync_last_error_text = ""
            if res.get("reload_needed") or res.get("merged") or res.get("pulled"):
                self._sync_reload.emit()
        except Exception as e:
            print(f"[sync] worker error: {e}")
            self._sync_last_error = True
            self._sync_last_error_text = str(e)
            self._sync_status.emit(f"Sync: {e!s}"[:80])
        finally:
            self._sync_in_progress = False
            need_again = self._sync_pending
            self._sync_pending = False
            self._sync_refresh.emit()
            if need_again:
                self._sync_retry.emit()

    def _reload_from_disk(self):
        if not self.storage:
            return
        try:
            self.storage._raw_data = self.storage._load()
            self.storage._sync_data()
            if hasattr(self, "model"):
                self.model.refresh()
            self._update_count()
            self._update_action_buttons()
        except Exception as e:
            print(f"[sync] reload: {e}")

    def _persist_mutation(self, fn, message):
        fn()
        if self._git_sync:
            threading.Thread(
                target=self._git_commit_worker,
                args=(message,),
                daemon=True,
            ).start()

    def _git_commit_worker(self, message):
        try:
            self._git_sync.do_and_commit(lambda: None, message)
        except Exception as e:
            print(f"[sync] commit: {e}")
        try:
            self._sync_trigger.emit()
        except Exception as e:
            print(f"[sync] trigger emit: {e}")

    # --- login ---

    def _on_login_success(self, crypto, storage, paths):
        self.crypto = crypto
        self.storage = storage
        self.session.auth = True
        self.session.crypto = crypto
        self.session.storage = storage
        self.session.paths = paths
        self.session.username = paths.username
        self.session.salt = nimbus.load_or_create_salt(paths.salt_file)
        save_last_user(paths.username)
        settings.reload_for_user(paths.settings_file)
        theme.set_mode(settings.get("theme", "system"), save=False)
        i18n.set_language(settings.get("language", "ru"))
        nimbus.CLIPBOARD_CLEAR_SECONDS = settings.get("clipboard_timeout", 30)
        nimbus.SESSION_TIMEOUT = settings.get("session_timeout", 300)
        try:
            paths.ensure_dir()
        except Exception:
            pass
        self._touch()
        self._build_main_view()
        self.stack.setCurrentIndex(1)
        self._setup_sync_after_login(paths)

    def _open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_cfg = (
            settings.get("github_enabled"),
            settings.get("github_url"),
            settings.get("github_token"),
            settings.get("github_branch"),
            settings.get("github_sync_interval"),
        )
        if new_cfg != self._sync_config:
            if self.session.paths:
                self._setup_sync_after_login(self.session.paths)
            else:
                self._refresh_sync_indicator()

    def _build_main_view(self):
        t_ = theme.current()
        while self.main_layout.count():
            item = self.main_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        self._top_frame = top = QFrame()
        tl = QHBoxLayout(top)
        tl.setContentsMargins(14, 8, 14, 8)
        tl.setSpacing(10)
        self.switch = ThemeSwitch(top)
        tl.addWidget(self.switch, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(t("search_placeholder"))
        self.search_edit.setMinimumHeight(38)
        self.search_edit.textChanged.connect(self._on_search)
        tl.addWidget(self.search_edit, 1)
        self._settings_btn = QPushButton(t("btn_settings"))
        self._settings_btn.setMinimumHeight(38)
        self._settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._settings_btn.clicked.connect(self._open_settings)
        tl.addWidget(self._settings_btn)
        self._logout_btn = QPushButton(t("btn_logout"))
        self._logout_btn.setObjectName("danger")
        self._logout_btn.clicked.connect(lambda: self._logout(expired=False))
        tl.addWidget(self._logout_btn)
        self.main_layout.addWidget(top)

        actions = QFrame(); actions.setStyleSheet("background: transparent;")
        al = QHBoxLayout(actions)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(8)
        self._add_btn = QPushButton(t("btn_create"))
        self._add_btn.setMinimumHeight(38)
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.setStyleSheet(primary_btn_qss(t_))
        self._add_btn.clicked.connect(self._add_record)
        al.addWidget(self._add_btn)
        self._import_btn = QPushButton(t("btn_import"))
        self._import_btn.setMinimumHeight(38)
        self._import_btn.clicked.connect(self._import_records)
        al.addWidget(self._import_btn)
        self._export_text_btn = QPushButton(t("btn_export_text"))
        self._export_text_btn.setMinimumHeight(38)
        self._export_text_btn.clicked.connect(self._export_text)
        al.addWidget(self._export_text_btn)
        self._export_archive_btn = QPushButton(t("btn_export_archive"))
        self._export_archive_btn.setMinimumHeight(38)
        self._export_archive_btn.clicked.connect(self._export_archive)
        al.addWidget(self._export_archive_btn)
        self._delete_all_btn = QPushButton(t("btn_delete_all"))
        self._delete_all_btn.setObjectName("danger")
        self._delete_all_btn.setMinimumHeight(38)
        self._delete_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._delete_all_btn.clicked.connect(self._delete_all)
        al.addWidget(self._delete_all_btn)
        al.addStretch()
        self.count_label = QLabel("")
        self.count_label.setStyleSheet(f"color: {t_['text_muted']}; font-size: 18px; background: transparent;")
        al.addWidget(self.count_label)
        self.main_layout.addWidget(actions)

        self.model = RecordModel(self.storage)
        self.proxy = RecordFilterProxy()
        self.proxy.setSourceModel(self.model)

        self.table = HoverTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(60)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setStyleSheet("background: transparent;")
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(2, 160)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(4, 100)
        header.setHighlightSections(False)
        td = TileDelegate(self.table)
        for col in (0, 1, 2, 3):
            self.table.setItemDelegateForColumn(col, td)
        ad = TileDelegate(self.table, is_action_column=True, on_action=self._on_row_action)
        self.table.setItemDelegateForColumn(4, ad)
        self.table.clicked.connect(self._on_cell_clicked)
        self.table.doubleClicked.connect(self._on_cell_dbl)
        self.table.selectionModel().selectionChanged.connect(
            lambda *_: self._update_action_btns())
        self.main_layout.addWidget(self.table, 1)

        bottom = QFrame(); bottom.setStyleSheet("background: transparent;")
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(8)
        self.edit_btn = QPushButton(t("btn_edit"))
        self.edit_btn.setMinimumHeight(36)
        self.edit_btn.clicked.connect(self._edit_selected)
        bl.addWidget(self.edit_btn)
        self.copy_btn = QPushButton(t("btn_copy_password"))
        self.copy_btn.setMinimumHeight(36)
        self.copy_btn.clicked.connect(self._copy_selected_pw)
        bl.addWidget(self.copy_btn)
        self.delete_btn = QPushButton(t("btn_delete"))
        self.delete_btn.setObjectName("danger")
        self.delete_btn.setMinimumHeight(36)
        self.delete_btn.clicked.connect(self._delete_selected)
        bl.addWidget(self.delete_btn)
        bl.addStretch()
        self._sync_indicator = SyncIndicator()
        bl.addWidget(self._sync_indicator, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.main_layout.addWidget(bottom)

        self._restyle_main()
        self._refresh_table()
        self._refresh_sync_indicator()

    def _refresh_table(self):
        self.model.refresh(); self._update_count(); self._update_action_btns()

    def _update_count(self):
        if not hasattr(self, "model"):
            return
        total = self.model.rowCount(); visible = self.proxy.rowCount()
        if total == 0:
            self.count_label.setText(t("count_empty"))
        elif visible == total:
            self.count_label.setText(t("count_n", n=total))
        else:
            self.count_label.setText(t("count_filtered", v=visible, t=total))

    def _update_action_btns(self):
        if not hasattr(self, "edit_btn"):
            return
        has = self._selected_row() is not None
        self.edit_btn.setEnabled(has)
        self.copy_btn.setEnabled(has)
        self.delete_btn.setEnabled(has)

    def _delete_all(self):
        if not self.storage:
            return
        n = len(self.storage.get_all())
        if n == 0:
            self._show_status(t("count_empty"))
            return
        dlg = MessageDialog(self, t("confirm_delete_all_title"),
                            t("confirm_delete_all_msg", n=n), kind="danger",
                            confirm_text=t("btn_delete"), cancel_text=t("btn_cancel"))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._persist_mutation(self.storage.delete_all, "nimbus: delete all")
        except Exception as e:
            QMessageBox.critical(self, t("title_error"), t("status_save_failed", e=e))
            return
        self._refresh_table()
        self._show_status(t("status_deleted_all", n=n))

    def _on_search(self, text):
        self.proxy.set_filter_text(text); self._update_count(); self._update_action_btns()

    def _selected_row(self):
        idxs = self.table.selectionModel().selectedRows()
        if not idxs:
            return None
        src = self.proxy.mapToSource(idxs[0])
        return src.row() if src.isValid() else None

    def _selected_record(self):
        row = self._selected_row()
        return self.model.get_record(row) if row is not None else None

    def _on_cell_clicked(self, idx):
        src = self.proxy.mapToSource(idx)
        if not src.isValid():
            return
        rec = self.model.get_record(src.row())
        if not rec:
            return
        col = src.column()
        if col == 0:
            self._copy(rec.get("service", ""), t("field_service"))
        elif col == 1:
            self._copy(rec.get("username", ""), t("field_login"))
        elif col == 2:
            self._copy(rec.get("password", ""), t("field_password"))
        elif col == 3:
            self._copy(rec.get("description", ""), t("field_description"))

    def _on_cell_dbl(self, idx):
        src = self.proxy.mapToSource(idx)
        if not src.isValid():
            return
        if src.column() == 2:
            self.model.toggle_reveal(src.row())
        elif src.column() != 4:
            self._edit_selected()

    def _on_row_action(self, action, idx):
        src = self.proxy.mapToSource(idx)
        if not src.isValid():
            return
        row = src.row()
        if action == "edit":
            self._edit_row(row)
        elif action == "delete":
            self._delete_row(row)

    def _copy(self, text, label):
        if not text or text == "—":
            return
        nimbus.copy_to_clipboard(text)
        self._show_status(t("status_copied", label=label))

    def _copy_selected_pw(self):
        rec = self._selected_record()
        if rec:
            self._copy(rec.get("password", ""), t("field_password"))

    def _add_record(self):
        dlg = RecordDialog(self, "title_new_record")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        rec = dlg.get_record()
        try:
            self._persist_mutation(lambda: self.storage.add(rec), "nimbus: add")
        except Exception as e:
            QMessageBox.critical(self, t("title_error"), t("status_save_failed", e=e))
            return
        self._refresh_table()
        self._show_status(t("status_added", s=rec["service"]))

    def _edit_selected(self):
        row = self._selected_row()
        if row is None:
            self._show_status(t("status_select")); return
        self._edit_row(row)

    def _edit_row(self, row):
        rec = self.model.get_record(row)
        if not rec:
            return
        dlg = RecordDialog(self, "title_edit_record", rec)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new = dlg.get_record()
        try:
            self._persist_mutation(lambda: self.storage.update(row, new), "nimbus: update")
        except Exception as e:
            QMessageBox.critical(self, t("title_error"), t("status_save_failed", e=e))
            return
        self._refresh_table()
        self._show_status(t("status_updated"))

    def _delete_selected(self):
        row = self._selected_row()
        if row is None:
            self._show_status(t("status_select")); return
        self._delete_row(row)

    def _delete_row(self, row):
        rec = self.model.get_record(row)
        if not rec:
            return
        if settings.get("confirm_delete", True):
            service = nimbus.safe_str(rec.get("service")) or "—"
            dlg = MessageDialog(self, t("confirm_delete_title", s=service),
                                t("confirm_delete_msg"), kind="danger",
                                confirm_text=t("btn_delete"), cancel_text=t("btn_cancel"))
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
        try:
            self._persist_mutation(lambda: self.storage.delete(row), "nimbus: delete")
        except Exception as e:
            QMessageBox.critical(self, t("title_error"), t("status_save_failed", e=e))
            return
        self._refresh_table()
        self._show_status(t("status_deleted"))

    def _confirm_master(self, action_key="confirm_pw_action_default"):
        if not self.session.paths:
            return False
        dlg = ConfirmMasterDialog(self, self.session.salt,
                                  self.session.paths.key_file, action_key)
        return dlg.exec() == QDialog.DialogCode.Accepted

    def _import_records(self):
        if not self._confirm_master("confirm_pw_action_import"):
            self._show_status(t("status_cancelled")); return
        path, _ = QFileDialog.getOpenFileName(self, t("dlg_import_title"), "", t("file_csv"))
        if not path:
            return
        try:
            if self._git_sync:
                ok, msg = self.storage.import_from_file(path)
                if ok:
                    threading.Thread(
                        target=self._git_commit_worker,
                        args=("nimbus: import",),
                        daemon=True,
                    ).start()
            else:
                ok, msg = self.storage.import_from_file(path)
            if ok:
                self._refresh_table()
            self._show_status(msg)
        except Exception as e:
            self._show_status(t("status_save_failed", e=e))

    def _export_text(self):
        if not self._confirm_master("confirm_pw_action_export"):
            self._show_status(t("status_cancelled")); return
        path, _ = QFileDialog.getSaveFileName(self, t("dlg_export_title"),
                                              t("export_default_filename"), t("file_csv"))
        if not path:
            return
        ok, msg = self.storage.export_to_file(path)
        self._show_status(msg)

    def _export_archive(self):
        if not self.session.paths:
            self._show_status(t("status_cancelled"));
            return
        dest = QFileDialog.getExistingDirectory(self, t("dlg_export_archive_title"), "")
        if not dest:
            return
        ok, msg = self.session.paths.export_to_zip(dest)
        self._show_status(msg)

    def _close_open_dialogs(self):
        app = QApplication.instance()
        if not app:
            return
        for w in list(app.topLevelWidgets()):
            if w is self:
                continue
            if isinstance(w, QDialog):
                try:
                    w.reject()
                except Exception:
                    pass
                try:
                    w.close()
                except Exception:
                    pass

    def _logout(self, expired=False):
        if expired:
            self._close_open_dialogs()
        last = self.session.username
        try:
            self._sync_timer.stop()
        except Exception:
            pass
        self._git_sync = None
        self._sync_in_progress = False
        self._sync_pending = False
        self._sync_config = None
        self._sync_last_error = False
        self._sync_last_error_text = ""
        if self._sync_indicator:
            try:
                self._sync_indicator.set_state(SyncIndicator.STATE_OFF)
            except RuntimeError:
                pass
        self._sync_indicator = None
        self.session.logout()
        self.crypto = None
        self.storage = None
        if last:
            save_last_user(last)
        self.login_view.reset()
        if expired:
            self.login_view.show_info("session_expired")
        self.stack.setCurrentIndex(0)

    def _show_status(self, text):
        if hasattr(self, "count_label"):
            self.count_label.setText(text)
            QTimer.singleShot(2500, self._update_count)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Nimbus")
    app.setWindowIcon(load_app_icon())
    app.setStyle("Fusion")
    theme.set_mode(settings.get("theme", "system"), save=False)
    app.setStyleSheet(build_qss(theme.current()))
    nimbus.CLIPBOARD_CLEAR_SECONDS = settings.get("clipboard_timeout", 30)
    nimbus.SESSION_TIMEOUT = settings.get("session_timeout", 300)
    if not acquire_single_instance_lock():
        QMessageBox.warning(None, t("msg_already_running_title"), t("msg_already_running"))
        sys.exit(1)
    app.setQuitOnLastWindowClosed(False)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("Warning: system tray is not available.")
    window = MainWindow()
    users = nimbus.list_existing_users()
    if "--minimized" not in sys.argv or not users:
        window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        with open("nimbus_crash.log", "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        try:
            QMessageBox.critical(None, "Nimbus Error",
                                 "Программа упала. Детали в nimbus_crash.log")
        except Exception:
            pass