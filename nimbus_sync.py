import os
import json
import time
import shutil
import tempfile
import threading
import platform
import subprocess
import urllib.parse
from typing import Optional, Callable


class SyncError(Exception):
    pass


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _auth_url(url: str, token: Optional[str]) -> str:
    if not token or not url.lower().startswith("https://"):
        return url
    rest = url[8:]
    if "@" in rest.split("/", 1)[0]:
        return url
    return f"https://x-access-token:{urllib.parse.quote(token, safe='')}@{rest}"


def _git_env() -> dict:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    env.pop("GIT_ASKPASS", None)
    env.pop("SSH_ASKPASS", None)
    env.pop("GIT_SSH_COMMAND", None)
    return env


def _sanitize(text: str, token: Optional[str]) -> str:
    if token and token in text:
        return text.replace(token, "***")
    return text


def _kill_tree(proc: subprocess.Popen):
    if platform.system() == "Windows":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True, check=False, timeout=5,
            )
            return
        except Exception:
            pass
    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=3)
    except Exception:
        pass


def _run_git(args, timeout, env, cwd=None):
    """Popen + tempfiles + kill-tree on timeout. Возвращает (rc, stdout, stderr)."""
    creationflags = 0
    if platform.system() == "Windows":
        try:
            creationflags = subprocess.CREATE_NO_WINDOW
        except AttributeError:
            creationflags = 0x08000000

    fd_out, out_path = tempfile.mkstemp(prefix="nimbus_git_out_")
    fd_err, err_path = tempfile.mkstemp(prefix="nimbus_git_err_")
    os.close(fd_out)
    os.close(fd_err)

    try:
        with open(out_path, "wb") as out_f, open(err_path, "wb") as err_f:
            try:
                proc = subprocess.Popen(
                    args,
                    stdin=subprocess.DEVNULL,
                    stdout=out_f, stderr=err_f,
                    env=env, cwd=cwd,
                    creationflags=creationflags,
                )
            except FileNotFoundError:
                raise SyncError("git не найден в PATH")

            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill_tree(proc)
                raise SyncError(f"git timeout {timeout}s")

        with open(out_path, "rb") as f:
            stdout = f.read().decode("utf-8", errors="replace")
        with open(err_path, "rb") as f:
            stderr = f.read().decode("utf-8", errors="replace")
        return proc.returncode, stdout, stderr
    finally:
        for p in (out_path, err_path):
            try:
                os.unlink(p)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# GitSync
# ---------------------------------------------------------------------------

class GitSync:
    STATE_FILE = ".nimbus_sync_state.json"

    def __init__(self, repo_dir: str, remote_url: str, username: str,
                 branch: str = "main", token: Optional[str] = None):
        self.repo_dir = repo_dir
        self.remote_url = remote_url
        self.username = username
        self.branch = branch
        self._token = token or None
        self._lock = threading.RLock()
        self._state_path = os.path.join(repo_dir, username, self.STATE_FILE)
        self._last_sync_time: Optional[float] = None
        self._last_synced_sha = self._load_state()

    def _load_state(self):
        try:
            with open(self._state_path, "r", encoding="utf-8") as f:
                d = json.load(f)
            self._last_sync_time = d.get("last_sync_time")
            return d.get("last_synced_sha")
        except Exception:
            self._last_sync_time = None
            return None

    def _save_state(self):
        try:
            os.makedirs(os.path.dirname(self._state_path), exist_ok=True)
            with open(self._state_path, "w", encoding="utf-8") as f:
                json.dump({
                    "last_synced_sha": self._last_synced_sha,
                    "last_sync_time": self._last_sync_time,
                }, f)
        except Exception:
            pass

    def get_last_sync_time(self):
        return self._last_sync_time

    def _mark_synced(self):
        self._last_synced_sha = self._current_sha()
        self._last_sync_time = time.time()
        self._save_state()

    # --- git plumbing ---

    def _run(self, *args, check=True, timeout=60):
        cmd = ["git", "-c", "credential.helper="] + list(args)
        rc, out, err = _run_git(cmd, timeout=timeout, env=_git_env(),
                                cwd=self.repo_dir)
        if check and rc != 0:
            msg = _sanitize((err or out).strip(), self._token)
            raise SyncError(f"git {' '.join(args)} → {rc}: {msg[:300]}")
        return type("R", (), {"returncode": rc, "stdout": out, "stderr": err})()

    def _current_sha(self):
        r = self._run("rev-parse", "HEAD", check=False)
        return r.stdout.strip() if r.returncode == 0 else None

    def _dirty(self):
        r = self._run("status", "--porcelain", check=False)
        return bool(r.stdout.strip())

    def _commit_all(self, msg):
        user_dir = os.path.join(self.repo_dir, self.username)
        if os.path.isdir(user_dir):
            self._run("add", "-A", "--", self.username, check=False)
        for fname in (".gitignore", "README.md"):
            if os.path.exists(os.path.join(self.repo_dir, fname)):
                self._run("add", "--", fname, check=False)

        r = self._run("status", "--porcelain", check=False)
        if not r.stdout.strip():
            return False
        self._run("commit", "-m", msg)
        return True

    def _push(self):
        auth = _auth_url(self.remote_url, self._token)
        rc, out, err = _run_git(
            ["git", "-c", "credential.helper=", "push", auth,
             f"HEAD:refs/heads/{self.branch}"],
            timeout=120, env=_git_env(), cwd=self.repo_dir,
        )
        if rc != 0:
            msg = _sanitize((err or out).strip(), self._token)
            raise SyncError(f"push failed: {msg[:300]}")

    def _probe_remote(self, auth_url):
        rc, out, err = _run_git(
            ["git", "-c", "credential.helper=", "ls-remote",
             "--heads", auth_url, self.branch],
            timeout=30, env=_git_env(), cwd=self.repo_dir,
        )
        if rc != 0:
            msg = _sanitize((err or out).strip(), self._token)
            raise SyncError(msg[:300] or f"ls-remote exit {rc}")
        for line in out.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) == 2 and parts[1].endswith(f"refs/heads/{self.branch}"):
                return True
        return False

    # --- repo init ---

    def _write_gitignore(self):
        path = os.path.join(self.repo_dir, ".gitignore")
        user_line = f"!/{self.username}/"

        existing = ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = f.read()
        except Exception:
            pass

        lines = [l for l in existing.splitlines() if l.strip()]

        # базовые правила, если ещё нет
        if "/*" not in lines:
            lines = [
                        "# Nimbus sync",
                        "/*",
                        "!/.gitignore",
                        "!/README.md",
                    ] + lines

        for pat in ("*.lock", "*.nimbus_settings", ".nimbus_sync_state.json", #"**/backup/"
                ):
            if pat not in lines:
                lines.append(pat)

        if user_line not in lines:
            lines.append(user_line)

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def _write_readme(self):
        path = os.path.join(self.repo_dir, "README.md")
        if os.path.exists(path):
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                "# Nimbus password data\n\n"
                "Encrypted password storage. Do not edit manually.\n\n"
                "## Restore on another computer\n\n"
                "1. Clone or download this repository.\n"
                "2. Copy the user folder (e.g. `alice/`) into your Nimbus "
                "program folder.\n"
                "3. Open Nimbus and log in with your master password.\n"
                "4. Settings → GitHub Sync → test connection and save.\n"
            )

    def ensure_repo(self):
        if not os.path.isdir(os.path.join(self.repo_dir, ".git")):
            self._run("init", "-b", self.branch)
        self._run("config", "user.email", "nimbus@local", check=False)
        self._run("config", "user.name", "Nimbus", check=False)
        self._write_gitignore()
        self._write_readme()
        self._run("remote", "remove", "origin", check=False)
        self._run("remote", "add", "origin", self.remote_url)

    # --- public API ---

    def do_and_commit(self, action_fn: Callable[[], None], message: str) -> bool:
        with self._lock:
            try:
                self.ensure_repo()
            except Exception as e:
                print(f"[sync] ensure_repo: {e}")
            action_fn()
            try:
                return self._commit_all(message)
            except Exception as e:
                print(f"[sync] commit: {e}")
                return False

    def sync(self, storage, log: Callable[[str], None] = print) -> dict:
        out = {"status": "ok", "pulled": False, "pushed": False,
               "merged": False, "reload_needed": False}

        with self._lock:
            try:
                self.ensure_repo()
            except Exception as e:
                out["status"] = f"error: ensure_repo: {_sanitize(str(e), self._token)}"
                return out

            auth = _auth_url(self.remote_url, self._token)

            try:
                remote_exists = self._probe_remote(auth)
            except SyncError as e:
                out["status"] = f"error: {e}"
                return out

            if not remote_exists:
                try:
                    if self._dirty():
                        self._commit_all("nimbus: initial snapshot")
                    if self._current_sha() is None:
                        self._commit_all("nimbus: initial snapshot")
                    if self._current_sha() is None:
                        out["status"] = "error: nothing to push"
                        return out
                    self._push()
                    out["pushed"] = True
                except Exception as e:
                    out["status"] = f"error: {_sanitize(str(e), self._token)}"
                    return out
                self._mark_synced()
                return out

            try:
                self._run(
                    "fetch", auth,
                    f"+refs/heads/{self.branch}:refs/remotes/origin/{self.branch}",
                    timeout=60,
                )
            except Exception as e:
                out["status"] = f"error: fetch: {_sanitize(str(e), self._token)}"
                return out

            r = self._run("rev-parse", f"origin/{self.branch}", check=False)
            remote_sha = r.stdout.strip() if r.returncode == 0 else None
            if not remote_sha:
                out["status"] = "error: cannot resolve origin branch"
                return out

            local_sha = self._current_sha()
            if local_sha is None:
                self._commit_all("nimbus: initial snapshot")
                local_sha = self._current_sha()
            if self._dirty():
                self._commit_all("nimbus: local changes")
                if self._dirty():
                    out["status"] = "error: cannot commit local changes"
                    return out
                local_sha = self._current_sha()

            last = self._last_synced_sha

            if remote_sha == local_sha:
                self._mark_synced()
                return out

            if remote_sha == last:
                try:
                    self._push()
                    out["pushed"] = True
                except Exception as e:
                    out["status"] = f"error: {_sanitize(str(e), self._token)}"
                    return out
                self._mark_synced()
                return out

            if local_sha == last:
                try:
                    self._run("reset", "--hard", f"origin/{self.branch}")
                    out["pulled"] = True
                    out["reload_needed"] = True
                except Exception as e:
                    out["status"] = f"error: pull: {_sanitize(str(e), self._token)}"
                    return out
                self._mark_synced()
                return out

            rel_key = f"{self.username}/{self.username}.nimbus_key"
            r_key = self._run("show", f"origin/{self.branch}:{rel_key}", check=False)
            if r_key.returncode == 0 and r_key.stdout.strip():
                try:
                    local_key_path = os.path.join(
                        self.repo_dir, self.username, f"{self.username}.nimbus_key"
                    )
                    with open(local_key_path, "r", encoding="utf-8") as f:
                        local_key = f.read().strip()
                    if local_key != r_key.stdout.strip():
                        out["status"] = (
                            f"error: пользователь «{self.username}» уже существует "
                            f"в репозитории с другим мастер-паролем/солью. "
                            f"Восстановите его через «Restore from GitHub» "
                            f"или используйте другое имя пользователя."
                        )
                        return out
                except Exception:
                    pass

            log("[sync] merging remote changes")
            rel = f"{self.username}/{os.path.basename(storage.file)}"
            r = self._run("show", f"origin/{self.branch}:{rel}", check=False)
            if r.returncode == 0 and r.stdout.strip():
                try:
                    payload = json.loads(storage.crypto.decrypt(r.stdout.strip()))
                    remote_records = (payload.get("records", [])
                                      if isinstance(payload, dict) else payload)
                    storage.merge_records(remote_records)
                    storage._save()
                    out["merged"] = True
                    self._commit_all("nimbus: merge records")
                except Exception as e:
                    out["status"] = f"error: merge records: {e}"
                    return out

            merge = self._run(
                "merge", "-X", "ours", "--no-edit",
                "--allow-unrelated-histories",
                f"origin/{self.branch}", check=False,
            )
            if merge.returncode != 0:
                self._run("checkout", "--ours", ".", check=False)
                self._run("add", "-A", check=False)
                self._run("commit", "-m", "nimbus: merge (ours)", check=False)

            try:
                self._push()
                out["pushed"] = True
            except Exception as e:
                out["status"] = f"error: push: {_sanitize(str(e), self._token)}"
                return out

            self._mark_synced()
            out["status"] = "merged"
            out["reload_needed"] = True
            return out


# ---------------------------------------------------------------------------
# clone / test
# ---------------------------------------------------------------------------

def clone_from_github(url: str, base_dir: str = ".",
                      branch: str = "main",
                      token: Optional[str] = None,
                      username: Optional[str] = None) -> str:
    if not token:
        raise SyncError("Personal Access Token обязателен")
    if not url.lower().startswith("https://"):
        raise SyncError("URL должен начинаться с https://")

    tmp = tempfile.mkdtemp(prefix="nimbus_clone_")
    try:
        auth = _auth_url(url, token)
        rc, out, err = _run_git(
            ["git", "-c", "credential.helper=", "clone", auth, tmp],
            timeout=90, env=_git_env(),
        )
        if rc != 0:
            msg = _sanitize((err or out).strip(), token)
            raise SyncError(f"git clone failed: {msg[:300]}")

        if username:
            src = os.path.join(tmp, username)
            if not os.path.isdir(src):
                raise SyncError(f"Папка «{username}» не найдена в репозитории")
            if not any(f.endswith(".nimbus_key") for f in os.listdir(src)):
                raise SyncError(f"В папке «{username}» нет *.nimbus_key")
            candidates = [username]
        else:
            candidates = []
            for name in os.listdir(tmp):
                if name in (".git", ".gitignore", "README.md"):
                    continue
                p = os.path.join(tmp, name)
                if os.path.isdir(p):
                    try:
                        if any(f.endswith(".nimbus_key") for f in os.listdir(p)):
                            candidates.append(name)
                    except Exception:
                        pass
            if not candidates:
                raise SyncError("В репозитории нет папки с *.nimbus_key")
            if len(candidates) > 1:
                raise SyncError(
                    f"Несколько пользователей: {', '.join(candidates)}. "
                    f"Укажите имя пользователя явно."
                )

        username = candidates[0]
        target = os.path.join(base_dir, username)
        if os.path.exists(target):
            raise SyncError(f"Папка {username}/ уже существует локально")

        shutil.move(os.path.join(tmp, username), target)

        git_src = os.path.join(tmp, ".git")
        git_dst = os.path.join(base_dir, ".git")
        if os.path.isdir(git_src) and not os.path.exists(git_dst):
            shutil.move(git_src, git_dst)
            try:
                subprocess.run(
                    ["git", "remote", "set-url", "origin", url],
                    cwd=base_dir, capture_output=True, check=False,
                    env=_git_env(), timeout=10,
                )
            except Exception:
                pass

        return username
    finally:
        if os.path.exists(tmp):
            shutil.rmtree(tmp, ignore_errors=True)


def test_connection(url: str, token: Optional[str], timeout: int = 30) -> tuple:
    if not url:
        return False, "URL не задан"
    if not url.lower().startswith("https://"):
        return False, "URL должен начинаться с https://"
    if not token:
        return False, "Personal Access Token обязателен"

    auth = _auth_url(url, token)
    t0 = time.time()
    print(f"[test] start url={url} timeout={timeout}")
    try:
        rc, out, err = _run_git(
            ["git", "-c", "credential.helper=", "ls-remote", "--heads", auth],
            timeout=timeout, env=_git_env(),
        )
    except SyncError as e:
        print(f"[test] SyncError after {time.time()-t0:.1f}s: {e}")
        return False, str(e)[:300]
    except Exception as e:
        print(f"[test] Exception after {time.time()-t0:.1f}s: {e}")
        return False, str(e)[:300]

    elapsed = time.time() - t0
    print(f"[test] done rc={rc} in {elapsed:.1f}s")

    if rc == 0:
        return True, "OK"

    msg = _sanitize((err or out).strip(), token)
    low = msg.lower()
    if "authentication failed" in low or "401" in msg:
        return False, "Неверный токен или нет прав (Contents: Read/Write)"
    if "not found" in low or "404" in msg:
        return False, "Репозиторий не найден или токен не имеет доступа"
    if "could not read username" in low or "could not read password" in low:
        return False, "Токен не принят — проверь права Contents: Read/Write"
    if "permission denied" in low:
        return False, "Доступ запрещён — проверь права токена"
    if "timeout" in low:
        return False, f"timeout после {elapsed:.0f}s — медленная сеть?"
    if not msg:
        return False, f"git ls-remote exit {rc}"
    return False, msg[:300]