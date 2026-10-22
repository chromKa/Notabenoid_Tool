"""Notabenoid Tool 2.0

Запуск: python main.py
Зависимости: PyQt6, requests, beautifulsoup4.
Файлы рядом: main.py, main_ui.py, res.py, папка lib/.
replace.py, table.py и refresh_id.py больше не нужны (можно удалить).
"""
from __future__ import annotations

import datetime
import difflib
import json
import math
import os
import re
import sys
import time
import webbrowser

from dataclasses import dataclass, field
from enum import IntEnum
from multiprocessing import freeze_support
from typing import Optional
from urllib.parse import quote
import requests
import urllib3
from bs4 import BeautifulSoup
from PyQt6 import QtGui, QtWidgets
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox

import main_ui as design
import res  # noqa: F401  (Qt resources)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://notabenoid.org/"
GITHUB_URL = "https://github.com/chromKa/Notabenoid_Tool"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/108.0.0.0 YaBrowser/23.1.3.949 "
        "Yowser/2.5 Safari/537.36"
    )
}
TIMEOUT = (5, 30)
PAGE_SIZE = 50
LIB_DIR = "./lib"
LOG_FILE = "notabenoid_log.txt"


class Tab(IntEnum):
    ADD = 0
    REFRESH = 1
    DOWNLOAD = 2
    REPLACE = 3
    ADD_TRANS = 4


class DownloadKind(IntEnum):
    ORIGINAL = 0
    TRANSLATION = 1


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

class Config:
    def __init__(self):
        self.login = ""
        self.password = ""
        self.book_url = ""

    def load(self):
        self.login = self._read("login")
        self.password = self._read("pass")
        self.book_url = self._read("url")

    def save_login(self, value: str):
        self.login = value
        self._write("login", value)

    def save_password(self, value: str):
        self.password = value
        self._write("pass", value)

    def save_url(self, value: str):
        self.book_url = value
        self._write("url", value)

    @staticmethod
    def _read(name: str) -> str:
        os.makedirs(LIB_DIR, exist_ok=True)
        path = os.path.join(LIB_DIR, name)
        if not os.path.isfile(path):
            return ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return ""

    @staticmethod
    def _write(name: str, value: str):
        os.makedirs(LIB_DIR, exist_ok=True)
        try:
            with open(os.path.join(LIB_DIR, name), "w", encoding="utf-8") as f:
                f.write(value)
        except OSError as exc:
            _write_log(f"config write error: {exc}")


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

class Http:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.csrf_refresh_callback = None
        self.csrf_token: Optional[str] = None

    def login(self, login: str, password: str) -> bool:
        login_url = "https://notabenoid.org/login"
        try:
            page = self.session.get(login_url, timeout=TIMEOUT, verify=False)
            if page.status_code != 200:
                _write_log(f"login page status {page.status_code}")
                return False

            soup = BeautifulSoup(page.text, "html.parser")
            token_input = soup.find("input", {"name": "_csrf_token"})
            if not token_input or not token_input.get("value"):
                _write_log("login: _csrf_token not found")
                return False
            token = token_input["value"]

            data = {
                "_csrf_token": token,
                "remember": "1",
                "login": login,
                "password": password,
            }
            headers = {
                "Referer": login_url,
                "Origin": "https://notabenoid.org",
                "Content-Type": "application/x-www-form-urlencoded",
            }
            resp = self.session.post(
                login_url, data=data, headers=headers,
                timeout=TIMEOUT, verify=False, allow_redirects=True,
            )
            if resp.url.rstrip("/").endswith("/login"):
                _write_log(f"login failed: still on {resp.url}")
                return False
            _write_log(f"login ok: redirected to {resp.url}")
            return True
        except requests.RequestException as exc:
            _write_log(f"login error: {exc}")
            return False

    def get(self, url: str) -> Optional[requests.Response]:
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=TIMEOUT, verify=False)
                if r.status_code == 200:
                    return r
            except requests.RequestException as exc:
                _write_log(f"GET {url}: {exc}")
            if attempt < 2:
                time.sleep(0.5)
        return None

    def post(self, url: str, data=None, extra_headers=None) -> bool:
        for attempt in range(2):
            headers = {}
            if self.csrf_token:
                headers["X-CSRFToken"] = self.csrf_token
            if extra_headers:
                headers.update(extra_headers)
            try:
                r = self.session.post(
                    url, data=data, headers=headers,
                    timeout=TIMEOUT, verify=False,
                )
                if r.status_code in (403, 419) and attempt == 0:
                    self._on_csrf_expired()
                    continue
                return r.ok
            except requests.RequestException as exc:
                _write_log(f"POST {url}: {exc}")
                return False
        return False

    def delete(self, url: str, extra_headers=None) -> bool:
        for attempt in range(2):
            headers = {}
            if self.csrf_token:
                headers["X-CSRFToken"] = self.csrf_token
            if extra_headers:
                headers.update(extra_headers)
            try:
                r = self.session.delete(
                    url, headers=headers,
                    timeout=TIMEOUT, verify=False,
                )
                if r.status_code in (403, 419) and attempt == 0:
                    self._on_csrf_expired()
                    continue
                return r.ok
            except requests.RequestException as exc:
                _write_log(f"DELETE {url}: {exc}")
                return False
        return False

    def _on_csrf_expired(self):
        if self.csrf_refresh_callback:
            self.csrf_refresh_callback()

    def soup(self, url: str) -> Optional[BeautifulSoup]:
        r = self.get(url)
        return BeautifulSoup(r.text, "html.parser") if r else None


# --------------------------------------------------------------------------- #
# SiteClient
# --------------------------------------------------------------------------- #

class SiteClient:
    def __init__(self, http: Http, book_url: str = "", csrf_url: str = ""):
        self.http = http
        self.book_url = book_url.rstrip("/")
        self.csrf_url = (csrf_url or self.book_url or BASE_URL).rstrip("/")

    def page_url(self, page: int, *, not_translated: bool = False) -> str:
        suffix = "?show=1&page=" if not_translated else "?page="
        return f"{self.book_url}{suffix}{page}"

    def last_page(self, *, not_translated: bool = False) -> int:
        url = self.book_url + ("?show=1" if not_translated else "")
        soup = self.http.soup(url)
        if not soup:
            return 1
        pages = 0
        for ul in soup.find_all("ul", class_="selectable"):
            links = ul.find_all("a")
            if links:
                try:
                    pages = max(pages, int(links[-1].get_text().strip()))
                except (TypeError, ValueError):
                    pass
        return pages or 1

    def page_ids(self, url: str) -> list[str]:
        soup = self.http.soup(url)
        if not soup:
            return []
        ids = []
        for row in soup.find_all("tr"):
            rid = row.get("id")
            if rid and str(rid).startswith("o"):
                ids.append(str(rid)[1:])
        return ids

    def get_row_id(self, ordinal: int) -> Optional[str]:
        try:
            page = math.ceil(ordinal / PAGE_SIZE)
            ids = self.page_ids(self.page_url(page))
            index = math.floor(ordinal - PAGE_SIZE * (page - 1)) - 1
            return ids[index]
        except (IndexError, ValueError):
            return None

    def add_str(self, ordinal: int, body: str) -> bool:
        url = f"{self.book_url}/0/edit"
        data = {"ord": ordinal, "body": body}
        headers = {"HX-Request": "true", "HX-Target": "o0"}
        return self.http.post(url, data=data, extra_headers=headers)

    def change_str(self, ordinal: int, body: str) -> bool:
        rid = self.get_row_id(ordinal)
        if rid is None:
            return False
        url = f"{self.book_url}/{rid}/edit"
        data = {"ord": ordinal, "body": body}
        headers = {"HX-Request": "true", "HX-Target": f"o{rid}"}
        return self.http.post(url, data=data, extra_headers=headers)

    def delete_str(self, ordinal: int) -> bool:
        rid = self.get_row_id(ordinal)
        if rid is None:
            return False
        url = f"{self.book_url}/{rid}/remove"
        headers = {"HX-Request": "true", "HX-Target": f"o{rid}"}
        return self.http.delete(url, extra_headers=headers)

    def refresh_ids_from(self, start_line: int, log=None) -> None:
        last = self.last_page()
        start_page = math.ceil(start_line / PAGE_SIZE)
        ordinal = start_page * PAGE_SIZE - (PAGE_SIZE - 1)

        if log:
            log(f"refresh: страницы {start_page}..{last}, начну с ord={ordinal}")

        ok_count = 0
        fail_count = 0

        for page in range(start_page, last + 1):
            soup = self.http.soup(self.page_url(page))
            if not soup:
                if log:
                    log(f"  страница {page}/{last} не загрузилась — пропускаю")
                fail_count += PAGE_SIZE
                continue
            tbody = soup.find_all("tbody")
            if not tbody:
                continue

            for row in tbody[0].find_all("tr"):
                rid_raw = row.get("id")
                if not rid_raw or not str(rid_raw).startswith("o"):
                    continue
                rid = str(rid_raw)[1:]

                p = row.find("p", class_="text")
                current_body = p.get_text(separator="\n").rstrip() if p else ""

                url = f"{self.book_url}/{rid}/edit"
                data = {"ord": ordinal, "body": current_body}
                headers = {"HX-Request": "true", "HX-Target": f"o{rid}"}
                if self.http.csrf_token:
                    headers["X-CSRFToken"] = self.http.csrf_token

                try:
                    r = self.http.session.post(
                        url, data=data, headers=headers,
                        timeout=TIMEOUT, verify=False,
                    )
                    if r.status_code in (419, 403):
                        if log:
                            log(f"ord={ordinal} rid={rid} — сессия протухла, обновляю токен…")
                        self.refetch_csrf()
                        if self.http.csrf_token:
                            headers["X-CSRFToken"] = self.http.csrf_token
                        r = self.http.session.post(
                            url, data=data, headers=headers,
                            timeout=TIMEOUT, verify=False,
                        )

                    if r.status_code == 200:
                        status = "OK"
                        ok_count += 1
                    elif r.status_code == 403:
                        status = "ОТКАЗ (403): нет прав на редактирование"
                        fail_count += 1
                    elif r.status_code == 404:
                        status = "НЕ НАЙДЕНО (404): строка удалена?"
                        fail_count += 1
                    elif r.status_code == 419:
                        status = "CSRF-ТОКЕН УСТАРЕЛ (419)"
                        fail_count += 1
                    elif r.status_code >= 500:
                        status = f"ОШИБКА СЕРВЕРА ({r.status_code})"
                        fail_count += 1
                    else:
                        status = f"НЕОЖИДАННЫЙ ОТВЕТ ({r.status_code})"
                        fail_count += 1

                    if log:
                        log(f"ord={ordinal} rid={rid} — {status}")
                    if r.status_code != 200 and log:
                        log(f"   ответ сервера: {r.text[:300]!r}")
                except requests.RequestException as exc:
                    fail_count += 1
                    if log:
                        log(f"ord={ordinal} rid={rid} — СЕТЬ: {exc}")

                ordinal += 1

        if log:
            if fail_count:
                log(f"refresh: готово. Успешно: {ok_count}, ошибок: {fail_count}")
                log("⚠ Некоторые строки не обновились — запустите «Обновить ID» ещё раз.")
            else:
                log(f"refresh: готово. Все {ok_count} строк обновлены.")

    def add_comment(self, ordinal: int, text: str) -> bool:
        rid = self.get_row_id(ordinal)
        if rid is None:
            return False
        url = f"{self.book_url}/{rid}/comments/reply"
        data = {"pid": "0", "body": text}
        headers = {
            "HX-Request": "true",
            "HX-Current-URL": f"{self.book_url}/{rid}",
        }
        return self.http.post(url, data=data, extra_headers=headers)

    def add_translation(self, row_id: str, text: str) -> bool:
        url = f"{self.book_url}/{row_id}/translate"
        data = {"body": text}
        headers = {
            "HX-Request": "true",
            "HX-Current-URL": f"{self.book_url}/{row_id}",
        }
        return self.http.post(url, data=data, extra_headers=headers)

    def replace_translation(
            self, chapter_url: str, orig_id: str, tr_id: str, body: str,
    ) -> bool:
        """chapter_url = 'https://notabenoid.org/book/NNN/MMM'"""
        url = f"{chapter_url}/{orig_id}/translate?tr_id={tr_id}"
        data = {"body": body}
        headers = {
            "HX-Request": "true",
            "HX-Current-URL": chapter_url,
        }
        return self.http.post(url, data=data, extra_headers=headers)

    def refetch_csrf(self) -> None:
        soup = self.http.soup(self.csrf_url)
        if not soup:
            return
        meta = soup.find("meta", {"name": "csrf-token"})
        if meta and meta.get("content"):
            self.http.csrf_token = meta["content"]
            return
        inp = soup.find("input", {"name": "_csrf_token"})
        if inp and inp.get("value"):
            self.http.csrf_token = inp["value"]


# --------------------------------------------------------------------------- #
# Files
# --------------------------------------------------------------------------- #

def flatten(data) -> list:
    if isinstance(data, dict):
        out = []
        for v in data.values():
            out.extend(flatten(v))
        return out
    if isinstance(data, list):
        out = []
        for item in data:
            out.extend(flatten(item))
        return out
    return [data]


def read_lines(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Строгий JSON
    try:
        data = json.loads(content)
        return [str(x) for x in flatten(data)]
    except json.JSONDecodeError:
        pass

    # 2. Мягкий JSON: разрешает raw newline/tab внутри строк
    try:
        data = json.loads(content, strict=False)
        _write_log(f"WARN: {path} — невалидный JSON, распарсен мягко")
        return [str(x) for x in flatten(data)]
    except json.JSONDecodeError:
        pass

    # 3. Текст
    lines = content.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    return [line.rstrip("\r") for line in lines]


def write_lines(path: str, lines: list[str], json_template: str = "") -> None:
    if path.lower().endswith(".json"):
        indent, template = 4, {}
        if json_template and os.path.isfile(json_template):
            with open(json_template, "r", encoding="utf-8") as f:
                template = json.load(f)
            try:
                with open(json_template, "r", encoding="utf-8") as f:
                    second = f.readlines()[1]
                m = re.match(r"^(\s+)", second)
                if m:
                    indent = len(m.group(1))
            except (OSError, IndexError):
                pass
        key = next((k for k, v in template.items() if isinstance(v, list)), None)
        payload = {**template, key: lines} if key else lines
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=indent, ensure_ascii=False)
    else:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(f"{line}\n" for line in lines)


# --------------------------------------------------------------------------- #
# RunState
# --------------------------------------------------------------------------- #

@dataclass
class RunState:
    tab: Tab
    book_url: str = ""
    dry_run: bool = False
    login: str = ""
    password: str = ""

    f1_data: list = field(default_factory=list)
    f2_data: list = field(default_factory=list)
    comment: str = ""

    start_line: int = 1

    download_kind: DownloadKind = DownloadKind.ORIGINAL
    only_untranslated: bool = False
    insert_from_original: bool = False
    save_path: str = ""
    json_template: str = ""

    main_url: str = ""
    search_text: str = ""
    replacement: str = ""
    replace_entire: bool = True

    translation_file: str = ""

    add_count: int = 0
    swap_count: int = 0
    del_count: int = 0


# --------------------------------------------------------------------------- #
# TaskThread
# --------------------------------------------------------------------------- #

class TaskThread(QThread):
    task_started = pyqtSignal(str)
    task_finished = pyqtSignal(str)
    progress_value = pyqtSignal(int)
    progress_text = pyqtSignal(str)

    def __init__(self, state: RunState, parent=None):
        super().__init__(parent)
        self.state = state
        self.http = Http()
        csrf_url = state.book_url or state.main_url or BASE_URL
        self.client = SiteClient(self.http, state.book_url, csrf_url=csrf_url)
        self._stop = False
        self.http.csrf_refresh_callback = self.client.refetch_csrf

    def stop(self):
        self._stop = True

    # --- обёртки над операциями (dry_run) ---
    def _add(self, ordinal: int, text: str):
        if not self.state.dry_run:
            ok = self.client.add_str(ordinal, text)
            if not ok:
                self.progress_text.emit(
                    f"add {ordinal}: {text} — FAILED\n"
                    f"⚠ Задача прервана. На сайте состояние частично изменено.\n"
                    f"⚠ Очистите поле «Файл оригинала с сайта» и перезапустите."
                )
                self._stop = True
                return
        self.state.add_count += 1
        self.progress_text.emit(f"add {self.state.add_count}) {ordinal}: {text}")

    def _swap(self, ordinal: int, text: str):
        if not self.state.dry_run:
            ok = self.client.change_str(ordinal, text)
            if not ok:
                self.progress_text.emit(
                    f"swap {ordinal}: {text} — FAILED\n"
                    f"⚠ Задача прервана. На сайте состояние частично изменено.\n"
                    f"⚠ Очистите поле «Файл оригинала с сайта» и перезапустите."
                )
                self._stop = True
                return
        self.state.swap_count += 1
        self.progress_text.emit(f"swap {self.state.swap_count}) {ordinal}: {text}")

    def _delete(self, ordinal: int, text: str):
        if self.state.dry_run:
            self.state.del_count += 1
            self.progress_text.emit(f"delete {ordinal}: {text}")
            if 0 <= ordinal - 1 < len(self.state.f1_data):
                self.state.f1_data.pop(ordinal - 1)
            return

        if not self.client.delete_str(ordinal):
            self.progress_text.emit(
                f"delete {ordinal}: {text} — FAILED\n"
                f"⚠ Задача прервана. Часть удалений ДО этого могла пройти успешно.\n"
                f"⚠ Проверьте книгу на сайте и запустите «Обновить ID» (вкладка 2), "
                f"затем повторите «Добавить оригинал» с очищенным старым файлом."
            )
            self._stop = True
            return

        self.state.del_count += 1
        if 0 <= ordinal - 1 < len(self.state.f1_data):
            self.state.f1_data.pop(ordinal - 1)
        self.progress_text.emit(f"delete {ordinal}: {text}")

    def run(self):
        self.task_started.emit(f"Task {self.state.tab.name} START")
        start = time.time()
        try:
            if self.state.login and self.state.password:
                if not self.http.login(self.state.login, self.state.password):
                    self.progress_text.emit(
                        "Login failed — проверьте логин/пароль. "
                        "Все книги приватные, без авторизации работать не будет."
                    )
                    return
                self.progress_text.emit("Login OK")
            else:
                if not self.state.dry_run:
                    self.progress_text.emit("Логин и пароль не заданы — нельзя работать с приватной книгой")
                    return
                self.progress_text.emit(
                    "⚠ Логин/пароль не заданы. Для приватной книги скачивание оригинала не сработает."
                )
            self.client.refetch_csrf()
            # self.progress_text.emit("CSRF token refreshed")
            self.progress_value.emit(0)
            {
                Tab.ADD: self._task_add,
                Tab.REFRESH: self._task_refresh,
                Tab.DOWNLOAD: self._task_download,
                Tab.REPLACE: self._task_replace,
                Tab.ADD_TRANS: self._task_add_trans,
            }[self.state.tab]()
        except Exception as exc:
            self.progress_text.emit(f"Error: {exc}")
        finally:
            self.task_finished.emit(
                f"Task {self.state.tab.name} END ({round(time.time() - start)}s)"
            )

    # ---------------- Tab 0: ADD ----------------
    def _ensure_f1_data(self) -> bool:
        """Если старый файл не выбран — тянем текущее состояние книги с сайта."""
        if self.state.f1_data:
            return True
        if not self.state.book_url:
            self.progress_text.emit(
                "Выберите старый файл или укажите URL книги, чтобы скачать её текущее состояние"
            )
            return False

        self.progress_text.emit("Скачиваю текущий оригинал с сайта…")
        saved = self.state.only_untranslated
        self.state.only_untranslated = False
        try:
            self.state.f1_data = self._download_originals()
        finally:
            self.state.only_untranslated = saved

        if not self.state.f1_data:
            self.progress_text.emit(
                "Не удалось скачать оригинал с сайта. Проверьте:\n"
                "  • URL книги верный и книга существует;\n"
                "  • логин/пароль верные (книга приватная);\n"
                "  • вы имеете доступ к этой книге на notabenoid.org"
            )
            return False
        self.progress_text.emit(f"Скачано {len(self.state.f1_data)} строк")
        return True

    def _task_add(self):
        if not self._ensure_f1_data():
            return

        sm = difflib.SequenceMatcher(
            None, self.state.f1_data, self.state.f2_data, autojunk=False,
        )
        opcodes = sm.get_opcodes()
        if all(tag == "equal" for tag, *_ in opcodes):
            self.progress_text.emit("Files are identical")
            return

        if self.state.dry_run:
            self.progress_text.emit("--- DRY-RUN preview (# = позиция в новом файле) ---")

        added = self._apply_diff()
        if self.state.dry_run:
            self.state.f1_data = []
            return
        if added:
            if self.state.comment.strip():
                for ordinal in added:
                    if self._stop:
                        break
                    self.client.add_comment(ordinal, self.state.comment)

        self.progress_text.emit(
            f"Add: {self.state.add_count}, "
            f"Swap: {self.state.swap_count}, "
            f"Delete: {self.state.del_count}"
        )

        # Сбрасываем скачанный f1_data — следующий запуск гарантированно перекачает
        self.state.f1_data = []

    def _apply_diff(self) -> list[int]:
        to_delete = self._plan_deletions()
        for ordinal in sorted(to_delete, reverse=True):
            if self._stop:
                return []
            self._delete(ordinal, to_delete[ordinal])

        if self._stop:
            return []

        if to_delete and not self.state.dry_run:
            self.client.refresh_ids_from(min(to_delete))

        return self._plan_additions()

    def _plan_deletions(self) -> dict[int, str]:
        sm = difflib.SequenceMatcher(
            None, self.state.f1_data, self.state.f2_data, autojunk=False,
        )
        to_delete: dict[int, str] = {}
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "delete":
                for i in range(i1, i2):
                    to_delete[i + 1] = self.state.f1_data[i]
            elif tag == "replace" and (i2 - i1) > (j2 - j1):
                for k in range(j2 - j1, i2 - i1):
                    to_delete[i1 + 1 + k] = self.state.f1_data[i1 + k]
        return to_delete

    def _optimal_pairs(self, old_lines: list[str], new_lines: list[str]) -> dict[int, int]:
        """Монотонное назначение ВСЕХ old на подмножество new (максимум similarity).

        Возвращает {new_idx: old_idx}. Требует len(old) <= len(new).
        Гарантирует монотонность: если i1 < i2 — то new_idx(i1) < new_idx(i2).
        """
        n, m = len(old_lines), len(new_lines)
        if n == 0 or m == 0 or n > m:
            return {}

        sim = [
            [difflib.SequenceMatcher(None, old_lines[i], new_lines[j], autojunk=False).ratio()
             for j in range(m)]
            for i in range(n)
        ]

        NEG = float('-inf')
        dp = [[NEG] * (m + 1) for _ in range(n + 1)]
        choice = [[''] * (m + 1) for _ in range(n + 1)]

        # 0 old matched = 0 score для любого j
        for j in range(m + 1):
            dp[0][j] = 0.0
            choice[0][j] = 'base'

        for i in range(1, n + 1):
            for j in range(1, m + 1):
                # match old[i-1] с new[j-1]
                if dp[i - 1][j - 1] > NEG:
                    cand = dp[i - 1][j - 1] + sim[i - 1][j - 1]
                    if cand > dp[i][j]:
                        dp[i][j] = cand
                        choice[i][j] = 'match'
                # пропустить new[j-1] (skip_old НЕ разрешён — все old обязаны matched)
                if dp[i][j - 1] > dp[i][j]:
                    dp[i][j] = dp[i][j - 1]
                    choice[i][j] = 'skip_new'

        if dp[n][m] == NEG:
            return {}

        pairs: dict[int, int] = {}
        i, j = n, m
        while i > 0 and j > 0:
            ch = choice[i][j]
            if ch == 'match':
                pairs[j - 1] = i - 1
                i -= 1
                j -= 1
            elif ch == 'skip_new':
                j -= 1
            else:
                break
        return pairs

    def _plan_additions(self) -> list[int]:
        sm = difflib.SequenceMatcher(
            None, self.state.f1_data, self.state.f2_data, autojunk=False,
        )
        added: list[int] = []
        shift = 0  # сколько строк уже вставлено до текущего opcode

        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue

            if tag == "insert":
                for k in range(j2 - j1):
                    ordinal = i1 + 1 + shift + k
                    if self._stop:
                        return added
                    self._add(ordinal, self.state.f2_data[j1 + k])
                    added.append(ordinal)
                shift += (j2 - j1)

            elif tag == "replace":
                old_n = i2 - i1
                new_n = j2 - j1

                if old_n == new_n:
                    for k in range(new_n):
                        ordinal = i1 + 1 + shift + k
                        if self._stop:
                            return added
                        self._swap(ordinal, self.state.f2_data[j1 + k])
                        added.append(ordinal)

                elif old_n < new_n:
                    old_lines = self.state.f1_data[i1:i2]
                    new_lines = self.state.f2_data[j1:j2]
                    pairs = self._optimal_pairs(old_lines, new_lines)

                    # 1. swap для пар, где текст реально изменился
                    for ni in sorted(pairs.keys(), key=lambda n: pairs[n]):
                        oi = pairs[ni]
                        if old_lines[oi] == new_lines[ni]:
                            continue  # текст совпадает — POST не нужен
                        ordinal = i1 + 1 + oi + shift
                        if self._stop:
                            return added
                        self._swap(ordinal, new_lines[ni])
                        added.append(ordinal)

                    # 2. insert для новых строк без пары
                    cur = i1 + shift  # 0-based позиция в f1_data
                    for ni in range(new_n):
                        if ni in pairs:
                            cur += 1  # matched — уже на своём месте
                        else:
                            ordinal = cur + 1  # 1-based
                            if self._stop:
                                return added
                            self._add(ordinal, new_lines[ni])
                            added.append(ordinal)
                            cur += 1

                    shift += (new_n - old_n)

                # old_n > new_n — уже удалено в фазе 1

        return added
    # ---------------- Tab 1: REFRESH ----------------
    def _task_refresh(self):
        if self.state.dry_run:
            self.progress_text.emit("Dry-run: skipping refresh")
            return
        self.client.refresh_ids_from(
            self.state.start_line,
            log=lambda msg: self.progress_text.emit(msg),
        )
        self.progress_value.emit(100)

    # ---------------- Tab 2: DOWNLOAD ----------------
    def _task_download(self):
        if self.state.download_kind == DownloadKind.ORIGINAL:
            lines = self._download_originals()
            default = "binary_orig_from_site.txt"
        else:
            lines = self._download_translations()
            default = "binary_trans_from_site.txt"

        path = self.state.save_path or default
        write_lines(path, lines, self.state.json_template)
        self.progress_text.emit(f"Saved {len(lines)} lines -> {path}")

    def _download_originals(self) -> list[str]:
        last = self.client.last_page(not_translated=self.state.only_untranslated)
        result: list[str] = []
        failed = 0
        for page in range(1, last + 1):
            if self._stop:
                break
            soup = self.http.soup(
                self.client.page_url(page, not_translated=self.state.only_untranslated)
            )
            if not soup:
                failed += 1
                self.progress_text.emit(f"  page {page}/{last}: not fetched")
                continue
            tbody = soup.find_all("tbody")
            if not tbody:
                continue
            for row in tbody[0].find_all("tr"):
                p = row.find("p", class_="text")
                if p:
                    result.append(p.get_text(separator="\n").rstrip())
            self.progress_value.emit(int(100 * page / last))
        if failed:
            self.progress_text.emit(f"⚠ {failed} page(s) failed to download")
        return result

    def _download_translations(self) -> list[str]:
        last = self.client.last_page()
        result: list[str] = []
        for page in range(1, last + 1):
            if self._stop:
                break
            soup = self.http.soup(self.client.page_url(page))
            if not soup:
                continue
            tbody = soup.find_all("tbody")
            if not tbody:
                continue
            for row in tbody[0].find_all("tr"):
                t_cell = row.find(class_="t")
                if t_cell is None:
                    continue
                texts = t_cell.find_all("p", class_="text")
                if len(texts) > 1:
                    best = t_cell.find(class_="best")
                    if best:
                        p = best.find("p", class_="text")
                        if p:
                            result.append(p.get_text(separator="\n").rstrip())
                            continue
                if texts:
                    result.append(texts[0].get_text(separator="\n").rstrip())
                elif self.state.insert_from_original:
                    o_cell = row.find(class_="o")
                    p = o_cell.find("p", class_="text") if o_cell else None
                    if p:
                        result.append(p.get_text(separator="\n").rstrip())
                else:
                    result.append("")
            self.progress_value.emit(int(100 * page / last))
        return result

    # ---------------- Tab 4: ADD TRANS ----------------
    def _task_add_trans(self):
        not_tr = self.state.only_untranslated

        last = self.client.last_page(not_translated=not_tr)
        if last < 1:
            self.progress_text.emit("Cannot determine last page")
            return

        try:
            texts = read_lines(self.state.translation_file)
        except Exception as exc:
            self.progress_text.emit(f"File error: {exc}")
            return

        if not texts:
            self.progress_text.emit("Файл перевода пуст")
            return

        all_ids: list[str] = []
        for page in range(1, last + 1):
            if self._stop:
                return
            ids = self.client.page_ids(
                self.client.page_url(page, not_translated=not_tr)
            )
            if not ids:
                self.progress_text.emit(
                    f"⚠ Страница {page}/{last} вернула 0 ID — прерываю.\n"
                    f"Перевод НЕ загружен. Проверьте соединение и повторите."
                )
                return
            if page < last and len(ids) != PAGE_SIZE:
                self.progress_text.emit(
                    f"⚠ Страница {page}/{last}: {len(ids)} строк "
                    f"(ожидалось {PAGE_SIZE}) — прерываю.\n"
                    f"Перевод НЕ загружен — иначе rid/text рассинхронизируются."
                )
                return
            all_ids.extend(ids)

        if len(all_ids) != len(texts):
            self.progress_text.emit(
                f"Length mismatch: site={len(all_ids)} file={len(texts)}"
            )
            return

        if self.state.dry_run:
            non_empty = sum(1 for t in texts if t)
            self.progress_text.emit(
                f"--- DRY-RUN: применилось бы {non_empty}/{len(texts)} переводов "
                f"({len(texts) - non_empty} пустых пропущено) ---"
            )
            return

        added = 0
        failed = 0
        empty = 0
        for i, (rid, text) in enumerate(zip(all_ids, texts), start=1):
            if self._stop:
                return
            if i % 50 == 0 or i == len(all_ids):
                self.progress_text.emit(f"{i}/{len(all_ids)}")
            if not text:
                empty += 1
                continue
            if self.client.add_translation(rid, text):
                added += 1
            else:
                failed += 1
                self.progress_text.emit(f"  ✗ row {i} (rid={rid}) failed")

        self.progress_text.emit(
            f"Done: added={added}, failed={failed}, empty_skipped={empty}"
        )

    # ---------------- Tab 3: REPLACE ----------------
    def _task_replace(self):
        if not self.state.search_text:
            self.progress_text.emit("Empty search text")
            return
        if not self.state.main_url:
            self.progress_text.emit("Main URL is empty")
            return

        urls = self._resolve_targets(self.state.main_url)
        if not urls:
            return

        self.progress_text.emit(f"Целей: {len(urls)} глава/глав")
        if self.state.dry_run:
            self.progress_text.emit("--- DRY-RUN: изменения НЕ отправляются ---")

        total_ok = total_fail = total_found = 0
        for idx, chapter_url in enumerate(urls, start=1):
            if self._stop:
                break
            self.progress_text.emit(f"\n[{idx}/{len(urls)}] {chapter_url}")

            filter_text = (
                self.state.search_text
                if len(self.state.search_text) >= 2
                else None
            )

            chapter_title, entries = self._scan_chapter_translations(
                chapter_url, search_text=filter_text,
            )
            if chapter_title:
                self.progress_text.emit(f"название: {chapter_title}")
            if filter_text:
                self.progress_text.emit(
                    f"  фильтр сервера: tt={filter_text!r} "
                    f"(вариантов перевода в выдаче: {len(entries)})"
                )
            else:
                self.progress_text.emit(
                    f"  без фильтра (search_text короче 2 символов), "
                    f"вариантов: {len(entries)}"
                )

            if not entries:
                self.progress_text.emit("  (нет переводов)")
                continue

            for orig_id, tr_id, text in entries:
                if self._stop:
                    break
                new_text = self._replace_in_text(text)
                if new_text is None or new_text == text:
                    continue
                total_found += 1
                if self.state.dry_run:
                    self.progress_text.emit(
                        f"  would replace {orig_id}/{tr_id}: "
                        f"{text[:60]!r} => {new_text[:60]!r}"
                    )
                    continue
                if self.client.replace_translation(
                        chapter_url, orig_id, tr_id, new_text,
                ):
                    total_ok += 1
                    self.progress_text.emit(f"  ✓ {orig_id}/{tr_id}")
                else:
                    total_fail += 1
                    self.progress_text.emit(f"  ✗ {orig_id}/{tr_id} failed")

        if self.state.dry_run:
            self.progress_text.emit(f"\nDRY-RUN: нашлось {total_found} совпадений")
        else:
            self.progress_text.emit(
                f"\nDone: replaced={total_ok}, failed={total_fail}, "
                f"matched={total_found}"
            )

    def _replace_in_text(self, text: str) -> Optional[str]:
        if self.state.replace_entire:
            return self.state.replacement if text == self.state.search_text else None
        if self.state.search_text not in text:
            return None
        return text.replace(self.state.search_text, self.state.replacement)

    def _resolve_targets(self, url: str) -> list[str]:
        """Понимает /book/NNN (вся книга) и /book/NNN/MMM (одна глава)."""
        m = re.match(r"^(https?://[^/]+)/book/(\d+)(?:/(\d+))?/?$", url)
        if not m:
            self.progress_text.emit(
                "URL не распознан. Ожидается https://notabenoid.org/book/NNN "
                "или https://notabenoid.org/book/NNN/MMM"
            )
            return []
        host, book_id, chapter_id = m.groups()
        if chapter_id:
            return [f"{host}/book/{book_id}/{chapter_id}"]
        urls = self._chapter_urls(host, book_id)
        if not urls:
            self.progress_text.emit(
                f"В книге {book_id} не найдено глав — "
                f"проверьте, что страница /book/{book_id} открывается"
            )
        return urls

    def _chapter_urls(self, host: str, book_id: str) -> list[str]:
        """Собирает URL всех глав книги со страницы оглавления."""
        soup = self.http.soup(f"{host}/book/{book_id}")
        if not soup:
            return []

        urls: list[str] = []
        seen: set[str] = set()

        # Основной путь — <tr data-id> в таблице глав (стабильнее, чем href)
        table = soup.find("table", id="chapters")
        if table is not None:
            tbody = table.find("tbody")
            if tbody is not None:
                for tr in tbody.find_all("tr"):
                    chapter_id = tr.get("data-id")
                    if not chapter_id or not str(chapter_id).isdigit():
                        continue
                    if chapter_id in seen:
                        continue
                    seen.add(chapter_id)
                    urls.append(f"{host}/book/{book_id}/{chapter_id}")

        # Fallback — по href, если таблицы нет
        if not urls:
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if re.match(rf"^/book/{book_id}/\d+$", href):
                    if href in seen:
                        continue
                    seen.add(href)
                    urls.append(f"{host}{href}")
        return urls

    def _scan_chapter_translations(
            self, chapter_url: str,
            search_text: Optional[str] = None,
    ) -> tuple[str, list[tuple[str, str, str]]]:
        """Все переводы одной главы.

        Если передан search_text — используем серверный фильтр notabenoid
        ?show=6&tt=SEARCH, который вернёт только страницы, где в переводе
        встречается подстрока. Это в 10–100 раз быстрее.
        """
        if search_text:
            base = f"{chapter_url}?show=6&tt={quote(search_text)}"
            page_sep = "&"
        else:
            base = chapter_url
            page_sep = "?"

        first = self.http.soup(base)
        if not first:
            self.progress_text.emit("  не удалось открыть главу")
            return "", []

        title = ""
        h1 = first.find("h1")
        if h1:
            a = h1.find("a")
            if a and a.next_sibling:
                title = str(a.next_sibling).strip().lstrip(":").strip()
            if not title:
                title = h1.get_text(separator=" ").strip()

        last = 1
        for ul in first.find_all("ul", class_="selectable"):
            links = ul.find_all("a")
            if links:
                try:
                    last = max(last, int(links[-1].get_text().strip()))
                except (TypeError, ValueError):
                    pass

        result: list[tuple[str, str, str]] = []
        for page in range(1, last + 1):
            if self._stop:
                return title, result
            if page == 1:
                soup = first
            else:
                soup = self.http.soup(f"{base}{page_sep}page={page}")
            if not soup:
                self.progress_text.emit(f"  page {page}/{last}: not fetched")
                continue
            tbody = soup.find_all("tbody")
            if not tbody:
                continue
            for row in tbody[0].find_all("tr"):
                rid_raw = row.get("id")
                if not rid_raw or not str(rid_raw).startswith("o"):
                    continue
                orig_id = str(rid_raw)[1:]
                t_cell = row.find("td", class_="t")
                if t_cell is None:
                    continue
                for div in t_cell.find_all("div"):
                    div_id = div.get("id") or ""
                    if not (div_id.startswith("t") and div_id[1:].isdigit()):
                        continue
                    p = div.find("p", class_="text")
                    if p:
                        result.append(
                            (orig_id, div_id[1:],
                             p.get_text(separator="\n").rstrip())
                        )
        return title, result
# --------------------------------------------------------------------------- #
# MainWindow
# --------------------------------------------------------------------------- #

class MainWindow(QMainWindow, design.Ui_MainWindow):
    FONT_MAP = {
        "fileNameOld": 12, "fileNameNew": 12, "comment": 12, "lineNumber": 12,
        "progressBarRefresh": 12, "progressBarDownload": 12,
        "radioButton_replace": 12, "logBoxReplace": 12,
        "replacement_text": 12, "replace_text_orig": 12,
        "replacement_text_n": 12, "replace_text_orig_n": 12,
        "lineEdit_repl": 12, "url_main_text": 12,
        "radioButton": 12, "radioButton_insert": 12,
        "logBoxDownload_5": 10,
        "btnBrowseOld": 12, "btnBrowseNew": 12,
        "btnStartAdd": 13, "btnStartRefresh": 13, "btnStartDownload": 13,
        "btnStartReplace": 13, "btnBrowseTrans": 13, "btnStartTrans": 13,
        "btnFormat": 13, "lineEditFormat": 12,
        "fileNameTrans": 13, "logBoxTrans": 13, "refreshText": 13,
        "lineEditSave": 13, "btnBrowseSave": 13,
        "loginText": 12, "passwordText": 12, "urlBookText": 12,
        "comboBox": 12, "comboBox_replace": 12, "logBox": 12,
        "tabWidget": 12, "login": 12, "password": 12, "urlBook": 12,
        "radioButton_non_trans": 12, "radioButton_url": 12,
    }

    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.setWindowIcon(QtGui.QIcon(":/d/Untitled-12.png"))
        self.config = Config()
        self.config.load()
        self.thread: Optional[TaskThread] = None
        self.running_tab: Optional[Tab] = None
        self._dry_run_saved = False

        self._init_fonts()
        self._init_state()
        self._connect()

    def _init_fonts(self):
        fid = QFontDatabase.addApplicationFont(":/d/DINPro-CondensedMedium.ttf")
        families = QFontDatabase.applicationFontFamilies(fid)
        family = families[0] if families else "Arial"
        for name, size in self.FONT_MAP.items():
            w = getattr(self, name, None)
            if w is not None:
                w.setFont(QFont(family, size))
        self.menubar.setFont(QFont(family, 11))

        for name, size in (("logBoxAdd", 15.0), ("logBoxRefresh", 15.0),
                           ("logBoxDownload", 15.0)):
            w = getattr(self, name, None)
            if w is not None and hasattr(w, "setFontPointSize"):
                try:
                    w.setFontPointSize(size)
                except Exception:
                    pass

        dis = "QPushButton::disabled{background-color: rgb(22, 23, 24);}"
        for n in ("btnStartAdd", "btnStartRefresh",
                  "btnStartDownload", "btnStartReplace", "btnStartTrans"):
            getattr(self, n).setStyleSheet(dis)

        edit_qss = ("QLineEdit::active{background-color: rgb(23, 23, 23);}"
                    "QLineEdit::disabled{background-color: rgb(34, 35, 36);}")
        for n in ("login", "password", "urlBook"):
            getattr(self, n).setStyleSheet(edit_qss)

        p = self.palette()
        p.setColor(QPalette.ColorRole.Highlight, QColor(34, 35, 36))
        for n in ("loginText", "passwordText", "urlBookText", "refreshText"):
            getattr(self, n).setPalette(p)
        self.menubar.setStyleSheet(
            "QMenuBar {"
            "  background-color: rgb(56, 57, 58);"
            "  color: rgb(247, 247, 247);"
            "}"
            "QMenuBar::item {"
            "  background: transparent;"
            "  padding: 4px 10px;"
            "}"
            "QMenuBar::item:selected {"
            "  background-color: rgb(85, 170, 255);"
            "  color: rgb(20, 20, 20);"
            "}"
            "QMenuBar::item:pressed {"
            "  background-color: rgb(60, 130, 200);"
            "  color: rgb(20, 20, 20);"
            "}"
            "QMenu {"
            "  background-color: rgb(45, 45, 45);"
            "  color: rgb(247, 247, 247);"
            "  border: 1px solid rgb(80, 80, 80);"
            "}"
            "QMenu::item {"
            "  padding: 6px 24px;"
            "  background: transparent;"
            "}"
            "QMenu::item:selected {"
            "  background-color: rgb(85, 170, 255);"
            "  color: rgb(20, 20, 20);"
            "}"
            "QMenu::item:disabled {"
            "  color: rgb(120, 120, 120);"
            "}"
            "QMenu::separator {"
            "  height: 1px;"
            "  background: rgb(70, 70, 70);"
            "  margin: 4px 8px;"
            "}"
        )
        self.radioButton_non_trans.setStyleSheet(
            "QRadioButton:disabled { color: rgb(90, 90, 90); }"
        )

    def _init_state(self):
        self.login.setPlaceholderText("login")
        self.password.setPlaceholderText("password")
        self.urlBook.setPlaceholderText("https://notabenoid.org/book/12345/6789")
        self.fileNameOld.setPlaceholderText("Пусто = скачать текущий оригинал с сайта")
        self.login.setText(self.config.login)
        self.password.setText(self.config.password)
        self.urlBook.setText(self.config.book_url)
        self.lineNumber.setText("1")
        self.tabWidget.setCurrentIndex(0)
        self.radioButton_insert.setVisible(False)
        for bar in (self.progressBarRefresh, self.progressBarDownload):
            bar.setRange(0, 100)
            bar.setValue(0)

        replace_tab = self.tabWidget.widget(int(Tab.REPLACE))
        if replace_tab is not None:
            replace_tab.setEnabled(True)
        self.btnStartReplace.setEnabled(True)
        # Отдельная галка dry-run на вкладке «Заменить».
        # Состояние синхронизируется с self.logBox (см. _connect).
        self.replaceDryCheck = QtWidgets.QCheckBox(
            "Пробный прогон — на сайт ничего не отправляется"
        )
        self.replaceDryCheck.setFont(self.logBox.font())
        if replace_tab is not None:
            layout = replace_tab.layout()
            if layout is not None:
                # рядом с кнопкой «Начать» (11, 1), занимаем (11, 2..4)
                layout.addWidget(self.replaceDryCheck, 11, 2, 1, 3)
        self._update_nt_state()
        self._on_tab(self.tabWidget.currentIndex())
        self.logBoxDownload_5.setHtml(
            "<html><head><style>"
            "p { white-space: pre-wrap; margin: 6px 0; }"
            "b { color: #8ecbff; }"
            "</style></head><body "
            "style=\"font-family:'JetBrains Mono',monospace; color:#ffffff;\">"

            "<p><b>=== Общее ===</b></p>"
            "<p>Все книги на notabenoid <b>приватные</b> — без логина и пароля программа не работает, даже в dry-run. "
            "Введите логин/пароль и URL книги сверху. Галки «Сохранить логин и пароль» / «Сохранить Url» "
            "хранят данные в папке lib/ между запусками.</p>"

            "<p>Галка <b>«Сравнить файлы без замены»</b> (вкладка «Добавить оригинал») и галка "
            "<b>«Пробный прогон»</b> (вкладка «Заменить») — это одно и то же состояние: включая одну, включаете обе. "
            "В dry-run POST-запросы на изменение не отправляются, только читаются страницы.</p>"

            "<p><b>=== Добавить оригинал ===</b></p>"
            "<p>1. Выберите «Новый файл оригинала» — это новое состояние книги.<br/>"
            "2. «Файл оригинала с сайта» можно не указывать — программа сама скачает текущее состояние с сайта и сравнит.<br/>"
            "3. Комментарий (необязательно) — добавится к новым строкам.<br/>"
            "4. Нажмите «Начать». В dry-run покажет план, без dry-run применит на сайте.</p>"

            "<p><b>Как работает сравнение:</b><br/>"
            "• Совпавшие строки не трогаются.<br/>"
            "• Удалённые — удаляются с конца (чтобы номера не съезжали), затем автоматически Refresh ID.<br/>"
            "• Вставленные — добавляются на нужные позиции.<br/>"
            "• Изменённые 1→1 — заменяются (текст обновляется, перевод сохраняется).<br/>"
            "• Блоки N→M — программа сама находит наиболее похожие пары, чтобы сохранить привязанные переводы.</p>"

            "<p>После успешного прогона кэш старого файла сбрасывается — следующий запуск перекачает свежее состояние "
            "с сайта. Очищать поле «Файл оригинала с сайта» вручную не нужно.</p>"

            "<p><b>Если задача упала</b> (сеть, протух CSRF) — на сайте состояние может быть частично изменено. "
            "Очистите «Файл оригинала с сайта» и перезапустите — программа перекачает актуальное состояние.</p>"

            "<p><b>=== Обновить ID ===</b></p>"
            "<p>Убирает дыры в нумерации строк (обычно после удалений). Укажите номер строки, с которой начать — обычно 1. "
            "В dry-run ничего не делает.</p>"
            "<p style=\"color:#ff6b6b\"><b>⚠ ВАЖНО: после обновления проверьте ID на сайте!</b><br/>"
            "1. Откройте книгу на notabenoid.org в браузере.<br/>"
            "2. Нумерация строк должна идти <b>#1, #2, #3…</b> подряд — без пропусков и дублей.<br/>"
            "3. В логе программы последняя строка — «Все N строк обновлены». "
            "Если увидели «⚠ Некоторые строки не обновились» — нажмите «Обновить ID» ещё раз.<br/>"
            "4. Порядковые номера (ord) — это основа всех операций. Если они сбились, "
            "добавление и замена будут ориентироваться не на те строки. "
            "Не запускайте «Добавить оригинал» или «Заменить», пока ID не выровнены.</p>"

            "<p><b>=== Скачать текст ===</b></p>"
            "<p>Сохраняет оригинал или перевод книги в файл.<br/>"
            "• .txt — по строкам, каждая строка файла = фрагмент сайта.<br/>"
            "• .json — можно указать шаблон, структура сохранится.<br/>"
            "• «Непереведённое» — фильтр: только строки без перевода (работает только для «Оригинал»).<br/>"
            "• «Заменять пустые строки оригиналом» — если перевода нет, подставить текст оригинала.</p>"

            "<p>При скачивании перевода: если у фрагмента несколько вариантов, берётся <b>лучший</b> "
            "(class=«best»). Если лучшего нет — первый по порядку.</p>"

            "<p><b>=== Заменить ===</b></p>"
            "<p>Замена перевода. Укажите URL <b>главы</b> (https://notabenoid.org/book/NNN/MMM) — "
            "заменит только в ней, или URL <b>книги</b> (https://notabenoid.org/book/NNN) — "
            "обойдёт все главы книги.<br/>"
            "• «Только целые строки» — заменять, только если перевод полностью совпадает с искомым текстом.<br/>"
            "• Без галки — заменять вхождения подстроки внутри более длинных переводов (все вхождения).<br/>"
            "• <b>Поиск регистрозависим:</b> «Hello» и «hello» — разные строки.<br/>"
            "• <b>Ищется по тексту перевода,</b> а не по CSS-классу. Если у div «class=«best»», "
            "но текст «defddd», программа его не найдёт при поиске «best».<br/>"
            "• Фильтр сервера `?show=6&tt=` применяется автоматически для запросов длиной 2+ символов — "
            "это в 100+ раз быстрее на больших книгах (скачиваются только страницы с совпадениями).<br/>"
            "• В dry-run в логе будет список всех планируемых замен без отправки на сайт.</p>"

            "<p><b>=== Добавить перевод ===</b></p>"
            "<p>Загрузка перевода из файла. Количество строк в файле должно <b>точно</b> совпадать "
            "с числом фрагментов на сайте (с галкой «Непереведённое» — только с числом непереведённых). "
            "При несовпадении появится «Length mismatch». Пустые строки файла пропускаются.</p>"

            "<p><b>=== Форматы файлов ===</b></p>"
            "<p>Файлы должны быть в кодировке <b>UTF-8</b>. Сохраняйте в блокноте через «Сохранить как → UTF-8».<br/>"
            "• .txt — читается построчно. Каждый перенос = отдельная строка. Пустые строки в середине файла сохраняются.<br/>"
            "• .json — плоский список строк: [«строка 1», «строка 2», ...]. Перенос внутри строки пишется как <b>\\n</b> "
            "(два символа: обратный слэш и n), на сайте станет &lt;br&gt;.</p>"

            "<p><b>=== Полезно знать ===</b><br/>"
            "• CSRF-токен обновляется автоматически. Если сессия протухла — программа подтянет новый и повторит запрос.<br/>"
            "• Закрытие окна во время работы пытается прервать задачу, но 1-2 запроса могут не успеть. "
            "На сайте останется частично изменённое состояние — очистите «Файл оригинала с сайта» и перезапустите.<br/>"
            "• Для замены в нескольких книгах: запустите «Заменить» несколько раз, каждый раз с URL новой книги.</p>"

            "</body></html>"
        )

    def _connect(self):
        self.actionRestart.triggered.connect(restart)
        self.actionnotabenoid_org.triggered.connect(self._open_site)
        self.actionGithub_com.triggered.connect(lambda: webbrowser.open(GITHUB_URL))
        self.actionQuit.triggered.connect(self.close)

        self.login.textEdited.connect(self._on_login_edit)
        self.password.textEdited.connect(self._on_password_edit)
        self.urlBook.textEdited.connect(self._on_url_edit)

        self.comboBox.currentIndexChanged.connect(self._on_combo)
        self.tabWidget.currentChanged.connect(self._on_tab)
        self.logBox.toggled.connect(self._on_dry_run)
        self.logBox.toggled.connect(self.replaceDryCheck.setChecked)
        self.replaceDryCheck.toggled.connect(self.logBox.setChecked)

        self.btnBrowseOld.clicked.connect(lambda: self._pick_file(self.fileNameOld))
        self.btnBrowseNew.clicked.connect(lambda: self._pick_file(self.fileNameNew))
        self.btnBrowseTrans.clicked.connect(lambda: self._pick_file(self.fileNameTrans))
        self.btnBrowseSave.clicked.connect(self._pick_save)

        self.btnFormat.clicked.connect(
            lambda: self._pick_file(
                self.lineEditFormat,
                "JSON files (*.json);;All files (*)",
            )
        )

        self.btnStartAdd.clicked.connect(self._start)
        self.btnStartRefresh.clicked.connect(self._start)
        self.btnStartDownload.clicked.connect(self._start)
        self.btnStartReplace.clicked.connect(self._start)
        self.btnStartTrans.clicked.connect(self._start)

    def _open_site(self):
        url = self.urlBook.text().strip()
        if url:
            webbrowser.open(url)

    def _on_login_edit(self, value):
        if self.radioButton.isChecked():
            self.config.save_login(value)

    def _on_password_edit(self, value):
        if self.radioButton.isChecked():
            self.config.save_password(value)

    def _on_url_edit(self, value):
        if self.radioButton_url.isChecked():
            self.config.save_url(value)

    def _on_tab(self, index):
        is_replace = index == int(Tab.REPLACE)
        self.urlBook.setEnabled(not is_replace)
        self.urlBookText.setEnabled(not is_replace)

        # На вкладках, где dry-run имеет смысл (ADD, REPLACE) — восстанавливаем
        # сохранённое состояние. На остальных — автоматически снимаем галку,
        # чтобы кнопки «Начать» были активны.
        if index in (int(Tab.ADD), int(Tab.REPLACE)):
            if self._dry_run_saved and not self.logBox.isChecked():
                self.logBox.setChecked(True)
        else:
            if self.logBox.isChecked():
                self._dry_run_saved = True
                self.logBox.setChecked(False)

        self._update_nt_state()

    def _on_combo(self, index):
        is_orig = index == int(DownloadKind.ORIGINAL)
        self.radioButton_insert.setVisible(not is_orig)
        self.radioButton_insert.setDisabled(is_orig)
        self._update_nt_state()

    def _update_nt_state(self):
        """«Непереведённое» активно только там, где реально используется.
        Disabled, а не hidden — чтобы layout не сдвигался."""
        tab = self.tabWidget.currentIndex()
        if tab == int(Tab.DOWNLOAD):
            enabled = self.comboBox.currentIndex() == int(DownloadKind.ORIGINAL)
        elif tab == int(Tab.ADD_TRANS):
            enabled = True
        else:
            enabled = False
        self.radioButton_non_trans.setEnabled(enabled)

    def _on_dry_run(self):
        dry = self.logBox.isChecked()

        # Запоминаем состояние только когда мы на подходящей вкладке.
        # На REFRESH/DOWNLOAD/ADD_TRANS галка снимается через _on_tab,
        # но не должна затирать сохранённое значение.
        current = self.tabWidget.currentIndex()
        if current in (int(Tab.ADD), int(Tab.REPLACE)):
            self._dry_run_saved = dry

        # Кнопки блокируются только на время работы задачи.
        # В dry-run кнопки на «неподходящих» вкладках уже будут
        # разблокированы через _on_tab (галка снята).
        running = self.thread is not None and self.thread.isRunning()
        for n in ("btnStartRefresh", "btnStartDownload", "btnStartTrans"):
            getattr(self, n).setDisabled(running)
        self.btnStartAdd.setDisabled(running)
        self.btnStartReplace.setDisabled(running)

    def _pick_file(self, line_edit, name_filter=None):
        if name_filter is None:
            name_filter = (
                "Data files (*.txt *.json);;"
                "Text files (*.txt);;"
                "JSON files (*.json);;"
                "All files (*)"
            )
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select file", "", name_filter
        )
        if path:
            line_edit.setText(path)

    def _pick_save(self):
        dialog = QtWidgets.QFileDialog(self, "Save file")
        dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptMode.AcceptSave)
        dialog.setNameFilters([
            "Text file (*.txt)",
            "JSON file (*.json)",
            "All files (*)",
        ])
        if not dialog.exec():
            return
        files = dialog.selectedFiles()
        if not files:
            return
        path = files[0]
        if not os.path.splitext(path)[1]:
            chosen = dialog.selectedNameFilter().lower()
            path += ".json" if "json" in chosen else ".txt"
        self.lineEditSave.setText(path)

    def _start(self):
        if self.thread is not None and self.thread.isRunning():
            return

        try:
            tab = Tab(self.tabWidget.currentIndex())
        except ValueError:
            return

        try:
            state = self._build_state(tab)
        except ValueError as exc:
            QMessageBox.critical(self, "Input error", str(exc))
            return
        if state is None:
            return

        self.running_tab = tab
        self._clear_log(tab)
        self._log(str(datetime.datetime.now())[:19])
        self._set_running_ui(True)

        self.thread = TaskThread(state)
        self.thread.task_started.connect(self._log)
        self.thread.task_finished.connect(self._log)
        self.thread.task_finished.connect(lambda _: self._set_running_ui(False))
        self.thread.progress_text.connect(self._log)
        self.thread.progress_value.connect(self._progress)
        try:
            self.thread.start()
        except Exception as exc:
            self._set_running_ui(False)
            QMessageBox.critical(self, "Thread error", str(exc))

    def _build_state(self, tab: Tab) -> Optional[RunState]:
        dry = self.logBox.isChecked()
        state = RunState(
            tab=tab,
            dry_run=dry,
            login=self.login.text(),
            password=self.password.text(),
        )

        url = self.urlBook.text().strip()
        state.book_url = url

        if tab == Tab.ADD:
            old_path = self.fileNameOld.text().strip()
            new_path = self.fileNameNew.text().strip()
            if not new_path:
                raise ValueError("Выберите новый файл оригинала")
            if not url and not (old_path and new_path):
                raise ValueError(
                    "Введите URL книги — он нужен, чтобы скачать текущий оригинал с сайта"
                )
            state.f1_data = read_lines(old_path) if old_path else []
            state.f2_data = read_lines(new_path)
            state.comment = self.comment.text()
            return state

        if tab == Tab.REPLACE:
            main_url = self.url_main_text.text().strip().rstrip("/")
            if main_url.startswith("http://notabenoid.org"):
                main_url = main_url.replace("http://notabenoid.org",
                                            "https://notabenoid.org", 1)
            state.main_url = main_url
            # strip снимает случайные пробелы и переносы с концов
            state.search_text = self.replace_text_orig.toPlainText().strip()
            # replacement НЕ strip'им — пользователь может специально
            # вставить пустую строку или строку с отступами
            state.replacement = self.replacement_text.toPlainText()
            state.replace_entire = self.radioButton_replace.isChecked()
            if not state.main_url:
                raise ValueError(
                    "Введите URL книги или главы: "
                    "https://notabenoid.org/book/NNN "
                    "или https://notabenoid.org/book/NNN/MMM"
                )
            if not state.search_text:
                raise ValueError("Введите текст для замены")
            return state

        if not url:
            raise ValueError("Введите URL книги")

        if tab == Tab.REFRESH:
            try:
                state.start_line = int(self.lineNumber.text() or "1")
            except ValueError:
                state.start_line = 1
        elif tab == Tab.DOWNLOAD:
            state.download_kind = DownloadKind(self.comboBox.currentIndex())
            state.only_untranslated = self.radioButton_non_trans.isChecked()
            state.insert_from_original = self.radioButton_insert.isChecked()
            state.save_path = self.lineEditSave.text().strip()
            state.json_template = self.lineEditFormat.text().strip()
        elif tab == Tab.ADD_TRANS:
            state.translation_file = self.fileNameTrans.text().strip()
            state.only_untranslated = self.radioButton_non_trans.isChecked()
            if not state.translation_file:
                raise ValueError("Выберите файл перевода")
        return state

    def _clear_log(self, tab: Tab):
        {
            Tab.ADD: self.logBoxAdd, Tab.REFRESH: self.logBoxRefresh,
            Tab.DOWNLOAD: self.logBoxDownload, Tab.REPLACE: self.logBoxReplace,
            Tab.ADD_TRANS: self.logBoxTrans,
        }[tab].clear()

    def _log(self, text: str):
        _write_log(text)
        if self.running_tab is None:
            return
        box = {
            Tab.ADD: self.logBoxAdd, Tab.REFRESH: self.logBoxRefresh,
            Tab.DOWNLOAD: self.logBoxDownload, Tab.REPLACE: self.logBoxReplace,
            Tab.ADD_TRANS: self.logBoxTrans,
        }.get(self.running_tab)
        if box:
            box.append(text)

    def _progress(self, value: int):
        if self.running_tab == Tab.REFRESH:
            self.progressBarRefresh.setValue(value)
        elif self.running_tab == Tab.DOWNLOAD:
            self.progressBarDownload.setValue(value)

    def _set_running_ui(self, running: bool):
        self.btnStartAdd.setDisabled(running)
        for n in ("btnStartRefresh", "btnStartDownload",
                  "btnStartTrans", "btnStartReplace"):
            getattr(self, n).setDisabled(running)
        self.logBox.setDisabled(running)
        if hasattr(self, "replaceDryCheck"):
            self.replaceDryCheck.setDisabled(running)

    def closeEvent(self, event):
        if self.thread and self.thread.isRunning():
            self.thread.stop()
            self.thread.wait(2000)
        if self.radioButton_url.isChecked() and self.urlBook.text().strip():
            self.config.save_url(self.urlBook.text().strip())
        event.accept()


# --------------------------------------------------------------------------- #
# misc
# --------------------------------------------------------------------------- #

def _write_log(text: str):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(text.rstrip() + "\n")
    except OSError:
        pass


def restart():
    os.execl(sys.executable, os.path.abspath(__file__), *sys.argv)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    freeze_support()
    window = MainWindow()
    window.show()
    sys.exit(app.exec())