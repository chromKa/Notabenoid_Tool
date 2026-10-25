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
import threading
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
from PyQt6.QtCore import (
    QThread, pyqtSignal, Qt, QAbstractTableModel, QModelIndex, QTimer,
)
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QMessageBox, QDialog,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableView, QHeaderView,
    QAbstractItemView, QPlainTextEdit,
)

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

# --------------------------------------------------------------------------- #
# Buffered, thread-safe logger
# --------------------------------------------------------------------------- #

_log_lock = threading.Lock()
_log_buffer: list[str] = []
_LOG_FLUSH_THRESHOLD = 32


def _flush_log_locked():
    global _log_buffer
    if not _log_buffer:
        return
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.writelines(_log_buffer)
    except OSError:
        pass
    finally:
        _log_buffer = []


def _write_log(text: str):
    line = text.rstrip() + "\n"
    with _log_lock:
        _log_buffer.append(line)
        is_worker = threading.current_thread() is not threading.main_thread()
        if is_worker or len(_log_buffer) >= _LOG_FLUSH_THRESHOLD:
            _flush_log_locked()


def _flush_log():
    with _log_lock:
        _flush_log_locked()


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
    WRITE_THROTTLE = 0.1

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.csrf_refresh_callback = None
        self.csrf_token: Optional[str] = None
        self._last_write_ts = 0.0

    def _throttle(self) -> None:
        """Не даёт write-запросам идти чаще, чем раз в WRITE_THROTTLE."""
        now = time.monotonic()
        delta = now - self._last_write_ts
        if delta < self.WRITE_THROTTLE:
            time.sleep(self.WRITE_THROTTLE - delta)
        self._last_write_ts = time.monotonic()

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
            self._throttle()
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
            self._throttle()
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

    def _find_text_p(self, rid: str, soup: BeautifulSoup):
        """Ищет <p class="text"> у строки с заданным rid в soup."""
        if soup is None:
            return None
        for tr in soup.find_all("tr"):
            if str(tr.get("id", "")) != f"o{rid}":
                continue
            p = tr.find("p", class_="text")
            if p is not None:
                return p
        return None

    def refresh_ids_from(
            self,
            start_line: int,
            log=None,
            should_stop=None,
    ) -> int:
        """Перенумеровывает ord всех строк начиная с start_line.

        Возвращает число строк, для которых POST не удался. Если >0 —
        нумерация могла сбиться, нужен повторный запуск.

        Если у строки не найден <p class="text"> — один раз перезагружаем
        страницу и ищем строку по rid. Если и во второй раз не нашли —
        прерываем refresh с ненулевым fail_count: продолжать бессмысленно,
        ord всех последующих строк всё равно сдвинуты.

        Если should_stop() вернёт True, обработка прерывается.
        """
        last = self.last_page()
        start_page = math.ceil(start_line / PAGE_SIZE)
        ordinal = start_page * PAGE_SIZE - (PAGE_SIZE - 1)

        if log:
            log(f"refresh: страницы {start_page}..{last}, начну с ord={ordinal}")

        ok_count = 0
        fail_count = 0
        consecutive_csrf_fails = 0
        consecutive_forbidden = 0

        for page in range(start_page, last + 1):
            if should_stop and should_stop():
                if log:
                    log("refresh: остановлено пользователем")
                return fail_count + 1

            soup = self.http.soup(self.page_url(page))
            if not soup:
                if log:
                    log(f"  страница {page}/{last} не загрузилась — пропускаю")
                fail_count += PAGE_SIZE
                ordinal += PAGE_SIZE
                continue
            tbody = soup.find_all("tbody")
            if not tbody:
                continue

            for row in tbody[0].find_all("tr"):
                if should_stop and should_stop():
                    if log:
                        log("refresh: остановлено пользователем")
                    return fail_count + 1

                rid_raw = row.get("id")
                if not rid_raw or not str(rid_raw).startswith("o"):
                    continue
                rid = str(rid_raw)[1:]

                p = row.find("p", class_="text")
                if p is None:
                    # Аномалия: либо неполный ответ, либо разметка изменилась.
                    # Перезапрашиваем страницу один раз и ищем строку по rid.
                    if log:
                        log(f"ord={ordinal} rid={rid} — "
                            f"<p class='text'> не найден, перезапрашиваю "
                            f"страницу {page}…")
                    retry_soup = self.http.soup(self.page_url(page))
                    p = self._find_text_p(rid, retry_soup)
                    if p is None:
                        if log:
                            log(f"ord={ordinal} rid={rid} — КРИТИЧНО: "
                                f"<p class='text'> не найден даже после "
                                f"повторной загрузки. Прерываю refresh — "
                                f"нумерация последующих строк могла сбиться.")
                        return fail_count + 1

                current_body = _extract_ptext(p).rstrip()

                url = f"{self.book_url}/{rid}/edit"
                data = {"ord": ordinal, "body": current_body}
                headers = {"HX-Request": "true", "HX-Target": f"o{rid}"}
                if self.http.csrf_token:
                    headers["X-CSRFToken"] = self.http.csrf_token

                try:
                    self.http._throttle()
                    r = self.http.session.post(
                        url, data=data, headers=headers,
                        timeout=TIMEOUT, verify=False,
                    )
                    if r.status_code in (419, 403):
                        if log:
                            log(f"ord={ordinal} rid={rid} — сессия протухла, "
                                f"обновляю токен…")
                        self.refetch_csrf()
                        if self.http.csrf_token:
                            headers["X-CSRFToken"] = self.http.csrf_token
                        self.http._throttle()
                        r = self.http.session.post(
                            url, data=data, headers=headers,
                            timeout=TIMEOUT, verify=False,
                        )

                    if r.status_code == 200:
                        status = "OK"
                        ok_count += 1
                        consecutive_csrf_fails = 0
                        consecutive_forbidden = 0
                    elif r.status_code == 403:
                        status = "ОТКАЗ (403): нет прав на редактирование"
                        fail_count += 1
                        consecutive_csrf_fails = 0
                        consecutive_forbidden += 1
                        if consecutive_forbidden >= 3:
                            if log:
                                log(f"ord={ordinal} rid={rid} — {status}")
                                log("⚠ 3×403 подряд — нет прав на "
                                    "редактирование. Прерываю refresh, "
                                    "чтобы не тратить время.")
                            return fail_count + 1
                    elif r.status_code == 404:
                        status = "НЕ НАЙДЕНО (404): строка удалена?"
                        fail_count += 1
                        consecutive_csrf_fails = 0
                        consecutive_forbidden = 0
                    elif r.status_code == 419:
                        status = "CSRF-ТОКЕН УСТАРЕЛ (419)"
                        fail_count += 1
                        consecutive_forbidden = 0
                        consecutive_csrf_fails += 1
                        if consecutive_csrf_fails >= 3:
                            if log:
                                log("⚠ 3×419 подряд — сессия потеряна. "
                                    "Прерываю refresh.")
                            return fail_count + 1
                    elif r.status_code >= 500:
                        status = f"ОШИБКА СЕРВЕРА ({r.status_code})"
                        fail_count += 1
                        consecutive_csrf_fails = 0
                        consecutive_forbidden = 0
                    else:
                        status = f"НЕОЖИДАННЫЙ ОТВЕТ ({r.status_code})"
                        fail_count += 1
                        consecutive_csrf_fails = 0
                        consecutive_forbidden = 0

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
                log("⚠ Некоторые строки не обновились — "
                    "запустите «Обновить ID» ещё раз.")
            else:
                log(f"refresh: готово. Все {ok_count} строк обновлены.")
        return fail_count

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

    # BOM (U+FEFF) в начале файла сломал бы сравнение первой строки
    # с сайтом и уехал бы на сайт при add/refresh. Срезаем.
    if content.startswith("\ufeff"):
        content = content[1:]

    try:
        data = json.loads(content)
        return [str(x) for x in flatten(data)]
    except json.JSONDecodeError:
        pass

    try:
        data = json.loads(content, strict=False)
        _write_log(f"WARN: {path} — невалидный JSON, распарсен мягко")
        return [str(x) for x in flatten(data)]
    except json.JSONDecodeError:
        pass

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


def _extract_ptext(p) -> str:
    """Текст из <p class="text">, где только <br> становится "\\n".

    get_text(separator="\\n") НЕЛЬЗЯ — он вставляет переводы строк вокруг
    любых inline-тегов. На странице с фильтром ?show=6&tt=... notabenoid
    подсвечивает совпадения в <span class="shl">, и в извлечённом тексте
    появляются лишние "\\n" вокруг искомого слова. При отправке обратно
    сервер превращает их в <br> — на сайте появляются лишние разрывы.
    """
    if p is None:
        return ""
    for br in p.find_all("br"):
        br.replace_with("\n")
    return p.get_text()

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
# Diff side-by-side preview
# --------------------------------------------------------------------------- #

def _compute_diff_stats(opcodes):
    total_blocks = adds = deletes = replaces = 0
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            continue
        total_blocks += 1
        old_len = i2 - i1
        new_len = j2 - j1
        if tag == "replace":
            replaces += min(old_len, new_len)
            if new_len > old_len:
                adds += new_len - old_len
            elif old_len > new_len:
                deletes += old_len - new_len
        elif tag == "insert":
            adds += new_len
        elif tag == "delete":
            deletes += old_len
    return total_blocks, adds, deletes, replaces


def _filter_opcodes_with_context(opcodes, context=3):
    if not opcodes:
        return opcodes
    result = []
    n = len(opcodes)
    for idx, op in enumerate(opcodes):
        tag = op[0]
        if tag != "equal":
            result.append(op)
            continue
        _, i1, i2, j1, j2 = op
        length = i2 - i1
        if length <= 2 * context:
            result.append(op)
            continue
        is_first = idx == 0
        is_last = idx == n - 1
        if is_first:
            result.append(("equal", i1, i1 + context, j1, j1 + context))
            result.append(("skip", i1 + context, i2, j1 + context, j2))
        elif is_last:
            result.append(("skip", i1, i2 - context, j1, j2 - context))
            result.append(("equal", i2 - context, i2, j2 - context, j2))
        else:
            result.append(("equal", i1, i1 + context, j1, j1 + context))
            result.append(("skip",
                           i1 + context, i2 - context,
                           j1 + context, j2 - context))
            result.append(("equal", i2 - context, i2, j2 - context, j2))
    return result


class DiffTableModel(QAbstractTableModel):
    """Плоская модель diff-таблицы.

    Каждая строка хранится как кортеж (tag, onum, otext, nnum, ntext),
    где tag — одно из: "skip", "equal", "delete", "insert",
    "replace:rep", "replace:del", "replace:ins".
    """

    HEADERS = ["№", "Старый файл", "№", "Новый файл"]

    C_EQ_BG = QColor(23, 23, 23)
    C_DEL_BG = QColor(74, 31, 31)
    C_DEL_FG = QColor(255, 153, 153)
    C_INS_BG = QColor(31, 74, 31)
    C_INS_FG = QColor(153, 255, 153)
    C_REP_L_BG = QColor(74, 66, 32)
    C_REP_L_FG = QColor(255, 221, 136)
    C_REP_R_BG = QColor(92, 82, 40)
    C_REP_R_FG = QColor(255, 238, 153)
    C_SKIP_BG = QColor(42, 42, 42)
    C_SKIP_FG = QColor(136, 136, 136)
    C_NUM_FG = QColor(102, 102, 102)
    C_TEXT = QColor(220, 220, 220)

    def __init__(self, old_lines, new_lines, opcodes, parent=None):
        super().__init__(parent)
        total_lines = max(len(old_lines), len(new_lines))
        ops = (_filter_opcodes_with_context(opcodes)
               if total_lines > 300 else opcodes)
        self._rows = self._build_rows(old_lines, new_lines, ops)

    @staticmethod
    def _build_rows(old_lines, new_lines, ops):
        rows = []
        for item in ops:
            tag = item[0]

            if tag == "skip":
                _, i1, i2, j1, j2 = item
                rows.append(("skip",
                             f"… пропущено {i2 - i1} строк без изменений …",
                             "", "", ""))

            elif tag == "equal":
                _, i1, i2, j1, j2 = item
                for k in range(i2 - i1):
                    o = old_lines[i1 + k] if i1 + k < len(old_lines) else ""
                    n = new_lines[j1 + k] if j1 + k < len(new_lines) else ""
                    rows.append(("equal",
                                 str(i1 + k + 1), o,
                                 str(j1 + k + 1), n))

            elif tag == "delete":
                _, i1, i2, j1, j2 = item
                for k in range(i2 - i1):
                    rows.append(("delete",
                                 str(i1 + k + 1), old_lines[i1 + k],
                                 "", ""))

            elif tag == "insert":
                _, i1, i2, j1, j2 = item
                for k in range(j2 - j1):
                    rows.append(("insert",
                                 "", "",
                                 str(j1 + k + 1), new_lines[j1 + k]))

            elif tag == "replace":
                _, i1, i2, j1, j2 = item
                old_len = i2 - i1
                new_len = j2 - j1
                for k in range(max(old_len, new_len)):
                    has_old = k < old_len
                    has_new = k < new_len
                    o = old_lines[i1 + k] if has_old else ""
                    onum = str(i1 + k + 1) if has_old else ""
                    n = new_lines[j1 + k] if has_new else ""
                    nnum = str(j1 + k + 1) if has_new else ""
                    if has_old and has_new:
                        sub = "replace:rep"
                    elif has_old:
                        sub = "replace:del"
                    else:
                        sub = "replace:ins"
                    rows.append((sub, onum, o, nnum, n))

        return rows

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 4

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        tag = row[0]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return row[col + 1]

        if role == Qt.ItemDataRole.BackgroundRole:
            return self._bg(tag, col)

        if role == Qt.ItemDataRole.ForegroundRole:
            return self._fg(tag, col)

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if tag == "skip":
                return int(Qt.AlignmentFlag.AlignCenter.value)
            align = Qt.AlignmentFlag.AlignTop
            if col in (0, 2):
                align |= Qt.AlignmentFlag.AlignRight
            else:
                align |= Qt.AlignmentFlag.AlignLeft
            return int(align.value)

        return None

    def headerData(self, section, orientation,
                   role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal \
                and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def _bg(self, tag, col):
        if tag == "skip":
            return self.C_SKIP_BG
        if tag == "equal":
            return self.C_EQ_BG
        if tag == "delete":
            return self.C_DEL_BG
        if tag == "insert":
            return self.C_INS_BG
        sub = tag.split(":", 1)[1]
        if sub == "rep":
            return self.C_REP_L_BG if col < 2 else self.C_REP_R_BG
        if sub == "del":
            return self.C_DEL_BG
        return self.C_INS_BG

    def _fg(self, tag, col):
        if tag == "skip":
            return self.C_SKIP_FG
        if col in (0, 2):
            return self.C_NUM_FG
        if tag == "equal":
            return self.C_TEXT
        if tag == "delete":
            return self.C_DEL_FG if col == 1 else self.C_TEXT
        if tag == "insert":
            return self.C_TEXT if col == 1 else self.C_INS_FG
        sub = tag.split(":", 1)[1]
        if sub == "rep":
            return self.C_REP_L_FG if col < 2 else self.C_REP_R_FG
        if sub == "del":
            return self.C_DEL_FG if col == 1 else self.C_TEXT
        return self.C_TEXT if col == 1 else self.C_INS_FG

    def is_skip_row(self, row: int) -> bool:
        return 0 <= row < len(self._rows) and self._rows[row][0] == "skip"

    def cell_text(self, row: int, col: int) -> str:
        if not (0 <= row < len(self._rows)):
            return ""
        return self._rows[row][col + 1] if col < 4 else ""


class DiffPreviewDialog(QDialog):
    """Side-by-side diff.

    confirm_mode=False — обычное окно-отчёт (dry-run), кнопка «Закрыть».
    confirm_mode=True  — диалог подтверждения перед изменениями на сайте.
                         «Применить» → accept(), «Отмена»/Esc/X → reject().
    """

    def __init__(self, old_lines, new_lines, opcodes, parent=None, *,
                 confirm_mode: bool = False):
        super().__init__(parent)
        self._confirm_mode = confirm_mode
        self._base_title = (
            "Подтверждение изменений на сайте"
            if confirm_mode
            else "Пробный прогон — сравнение файлов"
        )
        self.setWindowTitle(self._base_title)
        self.resize(1400, 900)
        self.setWindowIcon(QtGui.QIcon(":/d/Untitled-12.png"))
        self.setStyleSheet(
            "background-color: rgb(34, 35, 36); color: rgb(247, 247, 247);"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        total, adds, deletes, replaces = _compute_diff_stats(opcodes)
        total_lines = adds + deletes + replaces

        header = QHBoxLayout()
        header.setSpacing(16)
        lbl_total = QLabel(
            f"<b>Участков изменений:</b> {total} "
            f"<span style='color:#888'>(блоков)</span>"
        )
        lbl_lines = QLabel(
            f"<b>Всего строк затронуто:</b> {total_lines}"
        )
        lbl_rep = QLabel(
            f"<b style='color:#ffdd88'>⇄ Заменено пар:</b> {replaces}"
        )
        lbl_adds = QLabel(
            f"<b style='color:#99ff99'>+ Добавлено строк:</b> {adds}"
        )
        lbl_dels = QLabel(
            f"<b style='color:#ff9999'>− Удалено строк:</b> {deletes}"
        )
        for lbl in (lbl_total, lbl_lines, lbl_rep, lbl_adds, lbl_dels):
            header.addWidget(lbl)
        header.addStretch()

        if self._confirm_mode:
            cancel_btn = QPushButton("Отмена")
            cancel_btn.clicked.connect(self.reject)
            header.addWidget(cancel_btn)

            apply_btn = QPushButton("Применить")
            apply_btn.setStyleSheet(
                "QPushButton {"
                " background-color: rgb(46, 125, 50);"
                " color: rgb(247, 247, 247);"
                " padding: 4px 18px;"
                " border: 1px solid rgb(70, 160, 75);"
                " border-radius: 3px;"
                "}"
                "QPushButton:hover { background-color: rgb(56, 142, 60); }"
                "QPushButton:pressed { background-color: rgb(36, 105, 40); }"
            )
            apply_btn.setDefault(True)
            apply_btn.setAutoDefault(True)
            apply_btn.clicked.connect(self.accept)
            header.addWidget(apply_btn)
        else:
            close_btn = QPushButton("Закрыть")
            close_btn.clicked.connect(self.accept)
            header.addWidget(close_btn)

        layout.addLayout(header)

        self._model = DiffTableModel(old_lines, new_lines, opcodes, self)

        table = QTableView()
        table.setStyleSheet(
            "QTableView {"
            " background-color: rgb(23, 23, 23);"
            " color: rgb(220, 220, 220);"
            " gridline-color: rgb(50, 50, 50);"
            " border: 1px solid rgb(60, 60, 60);"
            "}"
            "QTableView::item { padding: 0px 4px; }"
            "QHeaderView::section {"
            " background-color: rgb(42, 42, 42);"
            " color: rgb(220, 220, 220);"
            " padding: 4px 8px;"
            " border: none;"
            " border-bottom: 1px solid rgb(80, 80, 80);"
            "}"
        )
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectItems
        )
        table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        table.setWordWrap(False)
        table.setFont(QFont("Consolas", 10))
        table.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        table.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )

        table.setUpdatesEnabled(False)
        table.blockSignals(True)
        try:
            table.setModel(self._model)
            for r in range(self._model.rowCount()):
                if self._model.is_skip_row(r):
                    table.setSpan(r, 0, 1, 4)
        finally:
            table.blockSignals(False)
            table.setUpdatesEnabled(True)

        hv = table.horizontalHeader()
        hv.setMinimumSectionSize(40)
        for col in range(4):
            hv.setSectionResizeMode(
                col, QHeaderView.ResizeMode.Interactive
            )
        hv.setStretchLastSection(False)

        table.setColumnWidth(0, 60)
        table.setColumnWidth(2, 60)
        table.setColumnWidth(1, 400)
        table.setColumnWidth(3, 400)

        layout.addWidget(table, 1)
        self._table = table

        table.doubleClicked.connect(self._on_cell_double_clicked)
        table.setFocus()

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_initial_sizing_done", False):
            return
        self._initial_sizing_done = True
        try:
            total = self._table.viewport().width()
        except (RuntimeError, AttributeError):
            return
        text_space = max(total - 140, 200)
        half = text_space // 2
        self._table.setColumnWidth(1, half)
        self._table.setColumnWidth(3, half)

    def keyPressEvent(self, event):
        if event.matches(QtGui.QKeySequence.StandardKey.Copy):
            self._copy_selection()
            event.accept()
            return
        super().keyPressEvent(event)

    def _copy_selection(self):
        try:
            indexes = self._table.selectedIndexes()
            if not indexes:
                return

            rows: dict[int, dict[int, str]] = {}
            for idx in indexes:
                text = self._model.cell_text(idx.row(), idx.column())
                if "\x00" in text:
                    text = text.replace("\x00", "")
                rows.setdefault(idx.row(), {})[idx.column()] = text

            lines = []
            for row in sorted(rows):
                cols = rows[row]
                cells = [cols.get(c, "") for c in sorted(cols)]
                lines.append("\t".join(cells))

            payload = "\n".join(lines)
            if len(payload) > 5_000_000:
                payload = payload[:5_000_000] + "\n… (обрезано)"

            QApplication.clipboard().setText(payload)
            base = self._base_title
            self.setWindowTitle(f"{base}  ✓ скопировано")
            QTimer.singleShot(
                1200, lambda: self.setWindowTitle(base)
            )
        except Exception as exc:
            _write_log(f"copy selection error: {exc}")

    def _on_cell_double_clicked(self, index: QModelIndex):
        if not index.isValid():
            return
        text = self._model.cell_text(index.row(), index.column())

        dlg = QDialog(self)
        dlg.setWindowTitle("Содержимое ячейки")
        dlg.resize(900, 400)
        dlg.setStyleSheet(
            "background-color: rgb(34, 35, 36);"
            " color: rgb(247, 247, 247);"
        )

        dlg_layout = QVBoxLayout(dlg)
        dlg_layout.setContentsMargins(10, 10, 10, 10)
        dlg_layout.setSpacing(8)

        editor = QPlainTextEdit()
        editor.setPlainText(text)
        editor.setReadOnly(True)
        editor.setFont(QFont("Consolas", 11))
        editor.setStyleSheet(
            "QPlainTextEdit {"
            " background-color: rgb(23, 23, 23);"
            " color: rgb(220, 220, 220);"
            " border: 1px solid rgb(60, 60, 60);"
            "}"
        )
        dlg_layout.addWidget(editor, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_copy_all = QPushButton("Копировать всё")
        btn_copy_all.clicked.connect(
            lambda: QApplication.clipboard().setText(text)
        )
        btn_row.addWidget(btn_copy_all)
        btn_close = QPushButton("Закрыть")
        btn_close.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_close)
        dlg_layout.addLayout(btn_row)

        editor.setFocus()
        editor.selectAll()
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.exec()

# --------------------------------------------------------------------------- #
# Replace preview (для вкладки «Заменить»)
# --------------------------------------------------------------------------- #

class ReplaceTableModel(QAbstractTableModel):
    """Плоская модель таблицы замен.

    Каждая строка — dict: {chapter, chapter_url, orig_id, tr_id, old, new}.
    """

    HEADERS = ["Глава", "orig", "tr", "Было", "Стало"]

    C_BG = QColor(23, 23, 23)
    C_OLD_BG = QColor(74, 31, 31)
    C_OLD_FG = QColor(255, 153, 153)
    C_NEW_BG = QColor(31, 74, 31)
    C_NEW_FG = QColor(153, 255, 153)
    C_TEXT = QColor(220, 220, 220)
    C_NUM_FG = QColor(102, 102, 102)
    C_CHAPTER_FG = QColor(142, 203, 255)

    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self._rows = list(entries)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 5

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return row["chapter"]
            if col == 1:
                return row["orig_id"]
            if col == 2:
                return row["tr_id"]
            if col == 3:
                return row["old"]
            if col == 4:
                return row["new"]
            return None

        if role == Qt.ItemDataRole.ToolTipRole:
            if col == 0:
                return row.get("chapter_url", "")
            return None

        if role == Qt.ItemDataRole.BackgroundRole:
            if col == 3:
                return self.C_OLD_BG
            if col == 4:
                return self.C_NEW_BG
            return self.C_BG

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == 0:
                return self.C_CHAPTER_FG
            if col in (1, 2):
                return self.C_NUM_FG
            if col == 3:
                return self.C_OLD_FG
            if col == 4:
                return self.C_NEW_FG
            return self.C_TEXT

        if role == Qt.ItemDataRole.TextAlignmentRole:
            align = Qt.AlignmentFlag.AlignTop
            if col in (1, 2):
                align |= Qt.AlignmentFlag.AlignRight
            else:
                align |= Qt.AlignmentFlag.AlignLeft
            return int(align.value)

        return None

    def headerData(self, section, orientation,
                   role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal \
                and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def cell_text(self, row: int, col: int) -> str:
        if not (0 <= row < len(self._rows)):
            return ""
        r = self._rows[row]
        return [r["chapter"], r["orig_id"], r["tr_id"],
                r["old"], r["new"]][col]


class ReplacePreviewDialog(QDialog):
    """Таблица планируемых замен для вкладки «Заменить».

    confirm_mode=False — информационное окно (dry-run).
    confirm_mode=True  — с кнопками «Применить/Отмена»; на сайт ничего
                         не уходит до нажатия «Применить».
    """

    def __init__(self, entries, parent=None, *, confirm_mode: bool = False):
        super().__init__(parent)
        self._confirm_mode = confirm_mode
        self._base_title = (
            "Подтверждение замен на сайте"
            if confirm_mode
            else "Пробный прогон — список замен"
        )
        self.setWindowTitle(self._base_title)
        self.resize(1400, 900)
        self.setWindowIcon(QtGui.QIcon(":/d/Untitled-12.png"))
        self.setStyleSheet(
            "background-color: rgb(34, 35, 36); color: rgb(247, 247, 247);"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        chapters = len({e.get("chapter_url", "") for e in entries})
        total = len(entries)

        header = QHBoxLayout()
        header.setSpacing(16)
        lbl_total = QLabel(f"<b>Замен найдено:</b> {total}")
        lbl_chapters = QLabel(
            f"<b>Глав затронуто:</b> {chapters}"
        )
        header.addWidget(lbl_total)
        header.addWidget(lbl_chapters)

        if confirm_mode:
            hint = QLabel(
                "<span style='color:#ffdd88'>"
                "Изменения на сайте НЕ отправлены. "
                "Нажмите «Применить», чтобы выполнить замену."
                "</span>"
            )
        else:
            hint = QLabel(
                "<span style='color:#888'>"
                "DRY-RUN — на сайт ничего не отправляется."
                "</span>"
            )
        header.addWidget(hint)
        header.addStretch()

        if self._confirm_mode:
            cancel_btn = QPushButton("Отмена")
            cancel_btn.clicked.connect(self.reject)
            header.addWidget(cancel_btn)

            apply_btn = QPushButton("Применить")
            apply_btn.setStyleSheet(
                "QPushButton {"
                " background-color: rgb(46, 125, 50);"
                " color: rgb(247, 247, 247);"
                " padding: 4px 18px;"
                " border: 1px solid rgb(70, 160, 75);"
                " border-radius: 3px;"
                "}"
                "QPushButton:hover { background-color: rgb(56, 142, 60); }"
                "QPushButton:pressed { background-color: rgb(36, 105, 40); }"
            )
            apply_btn.setDefault(True)
            apply_btn.setAutoDefault(True)
            apply_btn.clicked.connect(self.accept)
            header.addWidget(apply_btn)
        else:
            close_btn = QPushButton("Закрыть")
            close_btn.clicked.connect(self.accept)
            header.addWidget(close_btn)

        layout.addLayout(header)

        self._model = ReplaceTableModel(entries, self)

        table = QTableView()
        table.setStyleSheet(
            "QTableView {"
            " background-color: rgb(23, 23, 23);"
            " color: rgb(220, 220, 220);"
            " gridline-color: rgb(50, 50, 50);"
            " border: 1px solid rgb(60, 60, 60);"
            "}"
            "QTableView::item { padding: 0px 4px; }"
            "QHeaderView::section {"
            " background-color: rgb(42, 42, 42);"
            " color: rgb(220, 220, 220);"
            " padding: 4px 8px;"
            " border: none;"
            " border-bottom: 1px solid rgb(80, 80, 80);"
            "}"
        )
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectItems
        )
        table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        table.setWordWrap(True)
        table.setFont(QFont("Consolas", 10))
        table.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        table.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        table.setModel(self._model)

        hv = table.horizontalHeader()
        hv.setMinimumSectionSize(40)
        for col in range(5):
            hv.setSectionResizeMode(
                col, QHeaderView.ResizeMode.Interactive
            )
        hv.setStretchLastSection(False)

        table.setColumnWidth(0, 220)
        table.setColumnWidth(1, 70)
        table.setColumnWidth(2, 70)
        table.setColumnWidth(3, 380)
        table.setColumnWidth(4, 380)

        vh = table.verticalHeader()
        vh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        # потолок: если одна ячейка — на 20 строк текста, не растягиваем
        # её на весь экран. Полный текст по-прежнему доступен через
        # двойной клик по ячейке.
        vh.setMaximumSectionSize(300)

        layout.addWidget(table, 1)
        self._table = table

        table.doubleClicked.connect(self._on_cell_double_clicked)
        table.setFocus()

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_initial_sizing_done", False):
            return
        self._initial_sizing_done = True
        try:
            total = self._table.viewport().width()
        except (RuntimeError, AttributeError):
            return
        # 0=220 (глава), 1=70, 2=70, плюс запас под скроллбар
        text_space = max(total - 380, 200)
        half = text_space // 2
        self._table.setColumnWidth(3, half)
        self._table.setColumnWidth(4, half)
        # после смены ширины колонок высоты надо пересчитать:
        # с ResizeToContents оно произойдёт автоматически, но
        # форсируем на случай, если Qt поленится
        self._table.resizeRowsToContents()

    def keyPressEvent(self, event):
        if event.matches(QtGui.QKeySequence.StandardKey.Copy):
            self._copy_selection()
            event.accept()
            return
        super().keyPressEvent(event)

    def _copy_selection(self):
        try:
            indexes = self._table.selectedIndexes()
            if not indexes:
                return

            rows: dict[int, dict[int, str]] = {}
            for idx in indexes:
                text = self._model.cell_text(idx.row(), idx.column())
                if "\x00" in text:
                    text = text.replace("\x00", "")
                rows.setdefault(idx.row(), {})[idx.column()] = text

            lines = []
            for row in sorted(rows):
                cols = rows[row]
                cells = [cols.get(c, "") for c in sorted(cols)]
                lines.append("\t".join(cells))

            payload = "\n".join(lines)
            if len(payload) > 5_000_000:
                payload = payload[:5_000_000] + "\n… (обрезано)"

            QApplication.clipboard().setText(payload)
            base = self._base_title
            self.setWindowTitle(f"{base}  ✓ скопировано")
            QTimer.singleShot(1200, lambda: self.setWindowTitle(base))
        except Exception as exc:
            _write_log(f"copy selection error: {exc}")

    def _on_cell_double_clicked(self, index: QModelIndex):
        if not index.isValid():
            return
        text = self._model.cell_text(index.row(), index.column())

        dlg = QDialog(self)
        dlg.setWindowTitle("Содержимое ячейки")
        dlg.resize(900, 400)
        dlg.setStyleSheet(
            "background-color: rgb(34, 35, 36);"
            " color: rgb(247, 247, 247);"
        )
        dlg_layout = QVBoxLayout(dlg)
        dlg_layout.setContentsMargins(10, 10, 10, 10)
        dlg_layout.setSpacing(8)

        editor = QPlainTextEdit()
        editor.setPlainText(text)
        editor.setReadOnly(True)
        editor.setFont(QFont("Consolas", 11))
        editor.setStyleSheet(
            "QPlainTextEdit {"
            " background-color: rgb(23, 23, 23);"
            " color: rgb(220, 220, 220);"
            " border: 1px solid rgb(60, 60, 60);"
            "}"
        )
        dlg_layout.addWidget(editor, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_copy_all = QPushButton("Копировать всё")
        btn_copy_all.clicked.connect(
            lambda: QApplication.clipboard().setText(text)
        )
        btn_row.addWidget(btn_copy_all)
        btn_close = QPushButton("Закрыть")
        btn_close.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_close)
        dlg_layout.addLayout(btn_row)

        editor.setFocus()
        editor.selectAll()
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.exec()


# --------------------------------------------------------------------------- #
# TaskThread
# --------------------------------------------------------------------------- #

class TaskThread(QThread):
    task_started = pyqtSignal(str)
    task_finished = pyqtSignal(str)
    progress_value = pyqtSignal(int)
    progress_text = pyqtSignal(str)
    request_diff_preview = pyqtSignal(object)
    request_replace_preview = pyqtSignal(object)

    def __init__(self, state: RunState, parent=None):
        super().__init__(parent)
        self.state = state
        self.http = Http()
        csrf_url = state.book_url or state.main_url or BASE_URL
        self.client = SiteClient(self.http, state.book_url, csrf_url=csrf_url)
        self._stop = False
        self.http.csrf_refresh_callback = self.client.refetch_csrf
        # прогресс для вкладки ADD
        self._op_total = 0
        self._op_done = 0

    def stop(self):
        self._stop = True

    def _can_skip_site_access(self) -> bool:
        """True, когда dry-run не обращается к сайту — логин не нужен."""
        if not self.state.dry_run:
            return False
        if self.state.tab == Tab.ADD:
            # f1_data уже загружен пользователем → скачивать нечего
            return bool(self.state.f1_data)
        if self.state.tab == Tab.REFRESH:
            # dry-run REFRESH ничего не делает
            return True
        return False

    def _tick_progress(self):
        self._op_done += 1
        if self._op_total > 0:
            self.progress_value.emit(
                int(100 * self._op_done / self._op_total)
            )

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
        self._tick_progress()

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
        self._tick_progress()

    def _delete(self, ordinal: int, text: str):
        if self.state.dry_run:
            self.state.del_count += 1
            self.progress_text.emit(f"delete {ordinal}: {text}")
            if 0 <= ordinal - 1 < len(self.state.f1_data):
                self.state.f1_data.pop(ordinal - 1)
            self._tick_progress()
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
        self._tick_progress()

    def run(self):
        self.task_started.emit(f"Task {self.state.tab.name} START")
        start = time.time()
        try:
            if self._can_skip_site_access():
                self.progress_text.emit(
                    "Dry-run: сайт не нужен — логин и CSRF пропущены"
                )
            else:
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
                        self.progress_text.emit(
                            "Логин и пароль не заданы — нельзя работать "
                            "с приватной книгой"
                        )
                        return
                    self.progress_text.emit(
                        "⚠ Логин/пароль не заданы. Для приватной книги "
                        "скачивание оригинала не сработает."
                    )
                self.client.refetch_csrf()

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
            _flush_log()
            self.task_finished.emit(
                f"Task {self.state.tab.name} END "
                f"({round(time.time() - start)}s)"
            )

    # ---------------- Tab 0: ADD ----------------
    def _ensure_f1_data(self) -> bool:
        if self.state.f1_data:
            return True
        if not self.state.book_url:
            self.progress_text.emit(
                "Выберите старый файл или укажите URL книги, "
                "чтобы скачать её текущее состояние"
            )
            return False

        self.progress_text.emit("Скачиваю текущий оригинал с сайта…")
        saved = self.state.only_untranslated
        self.state.only_untranslated = False
        try:
            lines, failed = self._download_originals()
        finally:
            self.state.only_untranslated = saved

        if failed > 0:
            self.progress_text.emit(
                f"⚠ {failed} страниц(ы) не скачались — прерываю.\n"
                f"Иначе сравнение будет некорректным "
                f"и на сайте пропадут строки.\n"
                f"Проверьте соединение и повторите."
            )
            return False
        if not lines:
            self.progress_text.emit(
                "Не удалось скачать оригинал с сайта. Проверьте:\n"
                "  • URL книги верный и книга существует;\n"
                "  • логин/пароль верные (книга приватная);\n"
                "  • вы имеете доступ к этой книге на notabenoid.org"
            )
            return False
        self.state.f1_data = lines
        self.progress_text.emit(f"Скачано {len(lines)} строк")
        return True

    def _task_add(self):
        if not self._ensure_f1_data():
            return

        if self._stop:
            self.progress_text.emit(
                "Отменено до сравнения — сайт не тронут."
            )
            return

        sm = difflib.SequenceMatcher(
            None, self.state.f1_data, self.state.f2_data, autojunk=False,
        )
        opcodes = sm.get_opcodes()
        if all(tag == "equal" for tag, *_ in opcodes):
            self.progress_text.emit("Files are identical")
            return

        self._op_total = sum(
            max(i2 - i1, j2 - j1)
            for tag, i1, i2, j1, j2 in opcodes
            if tag != "equal"
        )
        self._op_done = 0
        self.progress_value.emit(0)

        payload = {
            "old": list(self.state.f1_data),
            "new": list(self.state.f2_data),
            "opcodes": list(opcodes),
        }

        if self._stop:
            return

        if self.state.dry_run:
            # Dry-run ничего не меняет — превью информативное, не блокирует.
            self.progress_text.emit(
                "--- DRY-RUN preview (# = позиция в новом файле) ---"
            )
            self.request_diff_preview.emit(payload)
        else:
            # Боевой режим: показываем таблицу и ЖДЁМ решения пользователя.
            self.progress_text.emit(
                "Ожидание подтверждения — проверьте таблицу изменений…"
            )
            evt = threading.Event()
            holder = {"confirmed": False}
            payload["event"] = evt
            payload["result"] = holder
            self.request_diff_preview.emit(payload)

            while not evt.wait(0.1):
                if self._stop:
                    self.progress_text.emit(
                        "Отменено до начала изменений — сайт не тронут."
                    )
                    return

            if not holder["confirmed"]:
                self.progress_text.emit(
                    "Отменено пользователем — сайт не тронут."
                )
                return
            self.progress_text.emit(
                "Подтверждено — начинаю изменения на сайте."
            )

        inserted = self._apply_diff()
        if self.state.dry_run:
            self.state.f1_data = []
            self.progress_value.emit(100)
            return
        if inserted and self.state.comment.strip():
            for ordinal in inserted:
                if self._stop:
                    break
                self.client.add_comment(ordinal, self.state.comment)

        self.progress_text.emit(
            f"Add: {self.state.add_count}, "
            f"Swap: {self.state.swap_count}, "
            f"Delete: {self.state.del_count}"
        )
        self.progress_value.emit(100)

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
            fail = self.client.refresh_ids_from(
                min(to_delete),
                log=lambda m: self.progress_text.emit(m),
                should_stop=lambda: self._stop,
            )
            if fail > 0:
                self.progress_text.emit(
                    f"\n⛔⛔⛔ ВНИМАНИЕ ⛔⛔⛔\n"
                    f"Refresh ID: {fail} строк не обновилось.\n"
                    f"\n"
                    f"«Добавить оригинал» прерван, чтобы не испортить "
                    f"нумерацию.\n"
                    f"\n"
                    f"ВАЖНО: нумерация на сайте может быть ЧАСТИЧНО "
                    f"обновлена — часть строк получила новый ord, часть нет.\n"
                    f"\n"
                    f"НЕ ЗАПУСКАЙТЕ другие операции (Добавить оригинал, "
                    f"Заменить, Добавить перевод), пока не выровняете ID:\n"
                    f"  1. Откройте вкладку «Обновить ID» (вкладка 2).\n"
                    f"  2. Номер строки: 1.\n"
                    f"  3. Нажмите «Начать» и дождитесь «Все N строк "
                    f"обновлены».\n"
                    f"  4. Если снова «⚠ Некоторые строки не обновились» — "
                    f"повторяйте, пока не выйдет полностью.\n"
                    f"\n"
                    f"Только после этого можно повторять «Добавить оригинал» "
                    f"с очищенным полем «Файл оригинала с сайта»."
                )
                self._stop = True
                return []
            if self._stop:
                return []

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

    def _optimal_pairs(
            self, old_lines: list[str], new_lines: list[str],
    ) -> dict[int, int]:
        """Монотонное назначение ВСЕХ old на подмножество new
        (максимум similarity)."""
        n, m = len(old_lines), len(new_lines)
        if n == 0 or m == 0 or n > m:
            return {}

        sim = [
            [difflib.SequenceMatcher(
                None, old_lines[i], new_lines[j], autojunk=False
            ).ratio()
             for j in range(m)]
            for i in range(n)
        ]

        NEG = float('-inf')
        dp = [[NEG] * (m + 1) for _ in range(n + 1)]
        choice = [[''] * (m + 1) for _ in range(n + 1)]

        for j in range(m + 1):
            dp[0][j] = 0.0
            choice[0][j] = 'base'

        for i in range(1, n + 1):
            for j in range(1, m + 1):
                if dp[i - 1][j - 1] > NEG:
                    cand = dp[i - 1][j - 1] + sim[i - 1][j - 1]
                    if cand > dp[i][j]:
                        dp[i][j] = cand
                        choice[i][j] = 'match'
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
        """Возвращает ord всех ИЗМЕНЁННЫХ строк (insert + swap) — для комментария."""
        sm = difflib.SequenceMatcher(
            None, self.state.f1_data, self.state.f2_data, autojunk=False,
        )
        touched: list[int] = []
        shift = 0

        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue

            if tag == "insert":
                for k in range(j2 - j1):
                    ordinal = i1 + 1 + shift + k
                    if self._stop:
                        return touched
                    self._add(ordinal, self.state.f2_data[j1 + k])
                    touched.append(ordinal)
                shift += (j2 - j1)

            elif tag == "replace":
                old_n = i2 - i1
                new_n = j2 - j1

                if old_n == new_n:
                    for k in range(new_n):
                        ordinal = i1 + 1 + shift + k
                        if self._stop:
                            return touched
                        self._swap(ordinal, self.state.f2_data[j1 + k])
                        touched.append(ordinal)

                elif old_n < new_n:
                    old_lines = self.state.f1_data[i1:i2]
                    new_lines = self.state.f2_data[j1:j2]
                    pairs = self._optimal_pairs(old_lines, new_lines)

                    for ni in sorted(pairs.keys(), key=lambda n: pairs[n]):
                        oi = pairs[ni]
                        if old_lines[oi] == new_lines[ni]:
                            continue
                        ordinal = i1 + 1 + oi + shift
                        if self._stop:
                            return touched
                        self._swap(ordinal, new_lines[ni])
                        touched.append(ordinal)

                    cur = i1 + shift
                    for ni in range(new_n):
                        if ni in pairs:
                            cur += 1
                        else:
                            ordinal = cur + 1
                            if self._stop:
                                return touched
                            self._add(ordinal, new_lines[ni])
                            touched.append(ordinal)
                            cur += 1

                    shift += (new_n - old_n)

        return touched

    # ---------------- Tab 1: REFRESH ----------------
    def _task_refresh(self):
        if self.state.dry_run:
            self.progress_text.emit("Dry-run: skipping refresh")
            return
        self.client.refresh_ids_from(
            self.state.start_line,
            log=lambda msg: self.progress_text.emit(msg),
            should_stop=lambda: self._stop,
        )
        self.progress_value.emit(100)

    # ---------------- Tab 2: DOWNLOAD ----------------
    def _task_download(self):
        if self.state.download_kind == DownloadKind.ORIGINAL:
            lines, failed = self._download_originals()
            default = "binary_orig_from_site.txt"
        else:
            lines, failed = self._download_translations()
            default = "binary_trans_from_site.txt"

        if not self.state.save_path:
            self.progress_text.emit(
                f"Путь не указан — сохраняю в {os.path.abspath(default)}"
            )
        path = self.state.save_path or default
        write_lines(path, lines, self.state.json_template)
        self.progress_text.emit(f"Saved {len(lines)} lines -> {path}")
        if failed:
            self.progress_text.emit(
                f"⚠ {failed} страниц(ы) не скачались — файл неполный"
            )

    def _download_originals(self) -> tuple[list[str], int]:
        last = self.client.last_page(
            not_translated=self.state.only_untranslated
        )
        result: list[str] = []
        failed = 0
        for page in range(1, last + 1):
            if self._stop:
                break
            soup = self.http.soup(
                self.client.page_url(
                    page, not_translated=self.state.only_untranslated
                )
            )
            if not soup:
                failed += 1
                self.progress_text.emit(f"  page {page}/{last}: not fetched")
                continue
            tbody = soup.find_all("tbody")
            if not tbody:
                continue
            for row in tbody[0].find_all("tr"):
                rid_raw = row.get("id")
                if not rid_raw or not str(rid_raw).startswith("o"):
                    continue
                p = row.find("p", class_="text")
                if p:
                    result.append(_extract_ptext(p).rstrip())
            self.progress_value.emit(int(100 * page / last))
        return result, failed

    def _download_translations(self) -> tuple[list[str], int]:
        last = self.client.last_page()
        result: list[str] = []
        failed = 0
        for page in range(1, last + 1):
            if self._stop:
                break
            soup = self.http.soup(self.client.page_url(page))
            if not soup:
                failed += 1
                self.progress_text.emit(f"  page {page}/{last}: not fetched")
                continue
            tbody = soup.find_all("tbody")
            if not tbody:
                continue
            for row in tbody[0].find_all("tr"):
                rid_raw = row.get("id")
                if not rid_raw or not str(rid_raw).startswith("o"):
                    continue
                t_cell = row.find(class_="t")
                if t_cell is None:
                    continue
                texts = t_cell.find_all("p", class_="text")
                if len(texts) > 1:
                    best = t_cell.find(class_="best")
                    if best:
                        p = best.find("p", class_="text")
                        if p:
                            result.append(_extract_ptext(p).rstrip())
                            continue
                if texts:
                    result.append(_extract_ptext(texts[0]).rstrip())
                elif self.state.insert_from_original:
                    o_cell = row.find(class_="o")
                    p = o_cell.find("p", class_="text") if o_cell else None
                    if p:
                        result.append(_extract_ptext(p).rstrip())
                else:
                    result.append("")
            self.progress_value.emit(int(100 * page / last))
        return result, failed

    # ---------------- Tab 4: ADD TRANS ----------------
    def _task_add_trans(self):
        not_tr = self.state.only_untranslated

        last = self.client.last_page(not_translated=not_tr)
        if last < 1:
            self.progress_text.emit("Cannot determine last page")
            return

        try:
            texts = read_lines(self.state.translation_file)
        except (OSError, ValueError) as exc:
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
                    f"Перевод НЕ загружен — иначе rid/text "
                    f"рассинхронизируются."
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
                f"--- DRY-RUN: применилось бы {non_empty}/{len(texts)} "
                f"переводов ({len(texts) - non_empty} пустых пропущено) ---"
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
            self.progress_text.emit(
                "--- DRY-RUN: изменения НЕ отправляются ---"
            )

        filter_text = (
            self.state.search_text
            if len(self.state.search_text) >= 2
            else None
        )

        # ---------- Фаза 1: собрать все замены ----------
        planned: list[dict] = []
        for idx, chapter_url in enumerate(urls, start=1):
            if self._stop:
                return
            self.progress_text.emit(f"\n[{idx}/{len(urls)}] {chapter_url}")

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

            short = chapter_url.rsplit("/", 2)
            chapter_label = (
                chapter_title
                or "/".join(short[-2:]) if len(short) >= 2 else chapter_url
            )

            for orig_id, tr_id, text in entries:
                if self._stop:
                    return
                new_text = self._replace_in_text(text)
                if new_text is None or new_text == text:
                    continue
                planned.append({
                    "chapter": chapter_label,
                    "chapter_url": chapter_url,
                    "orig_id": orig_id,
                    "tr_id": tr_id,
                    "old": text,
                    "new": new_text,
                })

        if not planned:
            self.progress_text.emit(
                "\nСовпадений не найдено — нечего применять."
            )
            return

        self.progress_text.emit(f"\nНайдено замен: {len(planned)}")

        if self._stop:
            return

        # ---------- Фаза 2: preview + подтверждение ----------
        payload = {"entries": list(planned)}

        if self.state.dry_run:
            self.progress_text.emit(
                "--- DRY-RUN: см. таблицу замен ---"
            )
            self.request_replace_preview.emit(payload)
            self.progress_text.emit(
                f"\nDRY-RUN: нашлось {len(planned)} совпадений — "
                f"на сайт ничего не отправлено."
            )
            return

        self.progress_text.emit(
            "Ожидание подтверждения — проверьте таблицу замен…"
        )
        evt = threading.Event()
        holder = {"confirmed": False}
        payload["event"] = evt
        payload["result"] = holder
        self.request_replace_preview.emit(payload)

        while not evt.wait(0.1):
            if self._stop:
                self.progress_text.emit(
                    "Отменено до начала изменений — сайт не тронут."
                )
                return

        if not holder["confirmed"]:
            self.progress_text.emit(
                "Отменено пользователем — сайт не тронут."
            )
            return
        self.progress_text.emit(
            "Подтверждено — начинаю замену на сайте."
        )

        # ---------- Фаза 3: применить ----------
        total = len(planned)
        total_ok = total_fail = 0
        for i, item in enumerate(planned, start=1):
            if self._stop:
                break
            if i % 20 == 0 or i == total:
                self.progress_text.emit(f"{i}/{total}")
            if self.client.replace_translation(
                item["chapter_url"], item["orig_id"], item["tr_id"],
                item["new"],
            ):
                total_ok += 1
                self.progress_text.emit(
                    f"  ✓ {item['orig_id']}/{item['tr_id']}"
                )
            else:
                total_fail += 1
                self.progress_text.emit(
                    f"  ✗ {item['orig_id']}/{item['tr_id']} failed"
                )

        self.progress_text.emit(
            f"\nDone: replaced={total_ok}, failed={total_fail}, "
            f"matched={total}"
        )

    def _replace_in_text(self, text: str) -> Optional[str]:
        if self.state.replace_entire:
            return (self.state.replacement
                    if text == self.state.search_text else None)
        if self.state.search_text not in text:
            return None
        return text.replace(self.state.search_text, self.state.replacement)

    def _resolve_targets(self, url: str) -> list[str]:
        # URL может прийти с ?from=feed или #comment из адресной строки
        url = url.split("?", 1)[0].split("#", 1)[0].rstrip("/")
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
        soup = self.http.soup(f"{host}/book/{book_id}")
        if not soup:
            return []

        urls: list[str] = []
        seen: set[str] = set()

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

        if not urls:
            # Fallback: если таблицы #chapters нет — ищем <a> по href.
            # Принимаем и относительные, и абсолютные URL, и с трейлингом.
            pattern = re.compile(
                rf"^(?:https?://[^/]+)?/book/{book_id}/(\d+)/?$"
            )
            for a in soup.find_all("a", href=True):
                m = pattern.match(a["href"])
                if not m:
                    continue
                chapter_id = m.group(1)
                if chapter_id in seen:
                    continue
                seen.add(chapter_id)
                urls.append(f"{host}/book/{book_id}/{chapter_id}")
        return urls

    def _scan_chapter_translations(
            self, chapter_url: str,
            search_text: Optional[str] = None,
    ) -> tuple[str, list[tuple[str, str, str]]]:
        if search_text:
            base = f"{chapter_url}?show=6&tt={quote(search_text, safe='')}"
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
                             _extract_ptext(p).rstrip())
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
        self._diff_preview_dlg: Optional[DiffPreviewDialog] = None
        self._replace_preview_dlg: Optional[ReplacePreviewDialog] = None

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
        self.urlBook.setPlaceholderText(
            "https://notabenoid.org/book/12345/6789"
        )
        self.fileNameOld.setPlaceholderText(
            "Пусто = скачать текущий оригинал с сайта"
        )
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
        self.replaceDryCheck = QtWidgets.QCheckBox(
            "Пробный прогон — на сайт ничего не отправляется"
        )
        self.replaceDryCheck.setFont(self.logBox.font())
        if replace_tab is not None:
            layout = replace_tab.layout()
            if layout is not None:
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
            "<p>Все книги на notabenoid <b>приватные</b> — без логина и пароля "
            "программа не работает, даже в dry-run. "
            "Введите логин/пароль и URL книги сверху. "
            "Галки «Сохранить логин и пароль» / «Сохранить Url» "
            "хранят данные в папке lib/ между запусками.</p>"

            "<p>Галка <b>«Сравнить файлы без замены»</b> (вкладка "
            "«Добавить оригинал») и галка <b>«Пробный прогон»</b> "
            "(вкладка «Заменить») — это одно и то же состояние: "
            "включая одну, включаете обе. "
            "В dry-run POST-запросы на изменение не отправляются, "
            "только читаются страницы.</p>"

            "<p><b>=== Добавить оригинал ===</b></p>"
            "<p>1. Выберите «Новый файл оригинала» — это новое состояние книги.<br/>"
            "2. «Файл оригинала с сайта» можно не указывать — программа "
            "сама скачает текущее состояние с сайта и сравнит.<br/>"
            "3. Комментарий (необязательно) — добавится к новым и заменённым строкам.<br/>"
            "4. Нажмите «Начать». Всегда открывается окно side-by-side diff:<br/>"
            "   • в dry-run — информационное, изменения не отправляются;<br/>"
            "   • без dry-run — с кнопками «Применить» / «Отмена»; на сайт "
            "ничего не уходит, пока вы не нажмёте «Применить».</p>"

            "<p><b>Как работает сравнение:</b><br/>"
            "• Совпавшие строки не трогаются.<br/>"
            "• Удалённые — удаляются с конца (чтобы номера не съезжали), "
            "затем автоматически Refresh ID.<br/>"
            "• Вставленные — добавляются на нужные позиции.<br/>"
            "• Изменённые 1→1 — заменяются (текст обновляется, "
            "перевод сохраняется).<br/>"
            "• Блоки N→M — программа сама находит наиболее похожие пары, "
            "чтобы сохранить привязанные переводы.</p>"

            "<p>После успешного прогона кэш старого файла сбрасывается — "
            "следующий запуск перекачает свежее состояние с сайта. "
            "Очищать поле «Файл оригинала с сайта» вручную не нужно.</p>"

            "<p><b>Если задача упала</b> (сеть, протух CSRF) — на сайте "
            "состояние может быть частично изменено. "
            "Очистите «Файл оригинала с сайта» и перезапустите — "
            "программа перекачает актуальное состояние.</p>"

            "<p><b>=== Обновить ID ===</b></p>"
            "<p>Убирает дыры в нумерации строк (обычно после удалений). "
            "Укажите номер строки, с которой начать — обычно 1. "
            "В dry-run ничего не делает.</p>"
            "<p style=\"color:#ff6b6b\"><b>⚠ ВАЖНО: после обновления "
            "проверьте ID на сайте!</b><br/>"
            "1. Откройте книгу на notabenoid.org в браузере.<br/>"
            "2. Нумерация строк должна идти <b>#1, #2, #3…</b> подряд — "
            "без пропусков и дублей.<br/>"
            "3. В логе программы последняя строка — «Все N строк обновлены». "
            "Если увидели «⚠ Некоторые строки не обновились» — "
            "нажмите «Обновить ID» ещё раз.<br/>"
            "4. Порядковые номера (ord) — это основа всех операций. "
            "Если они сбились, добавление и замена будут ориентироваться "
            "не на те строки. Не запускайте «Добавить оригинал» или "
            "«Заменить», пока ID не выровнены.</p>"

            "<p><b>=== Скачать текст ===</b></p>"
            "<p>Сохраняет оригинал или перевод книги в файл.<br/>"
            "• .txt — по строкам, каждая строка файла = фрагмент сайта.<br/>"
            "• .json — можно указать шаблон, структура сохранится.<br/>"
            "• «Непереведённое» — фильтр: только строки без перевода "
            "(работает только для «Оригинал»).<br/>"
            "• «Заменять пустые строки оригиналом» — если перевода нет, "
            "подставить текст оригинала.</p>"

            "<p>При скачивании перевода: если у фрагмента несколько вариантов, "
            "берётся <b>лучший</b> (class=«best»). Если лучшего нет — "
            "первый по порядку.</p>"

            "<p><b>=== Заменить ===</b></p>"
            "<p>Замена перевода. Укажите URL <b>главы</b> "
            "(https://notabenoid.org/book/NNN/MMM) — заменит только в ней, "
            "или URL <b>книги</b> (https://notabenoid.org/book/NNN) — "
            "обойдёт все главы книги.<br/>"
            "• «Только целые строки» — заменять, только если перевод "
            "полностью совпадает с искомым текстом.<br/>"
            "• Без галки — заменять вхождения подстроки внутри более "
            "длинных переводов (все вхождения).<br/>"
            "• <b>Поиск регистрозависим:</b> «Hello» и «hello» — "
            "разные строки.<br/>"
            "• <b>Ищется по тексту перевода,</b> а не по CSS-классу. "
            "Если у div «class=«best»», но текст «defddd», программа его "
            "не найдёт при поиске «best».<br/>"
            "• Фильтр сервера `?show=6&tt=` применяется автоматически "
            "для запросов длиной 2+ символов — это в 100+ раз быстрее "
            "на больших книгах (скачиваются только страницы с совпадениями).<br/>"
            "• В dry-run в логе будет список всех планируемых замен "
            "без отправки на сайт.</p>"

            "<p><b>=== Добавить перевод ===</b></p>"
            "<p>Загрузка перевода из файла. Количество строк в файле "
            "должно <b>точно</b> совпадать с числом фрагментов на сайте "
            "(с галкой «Непереведённое» — только с числом непереведённых). "
            "При несовпадении появится «Length mismatch». "
            "Пустые строки файла пропускаются.</p>"

            "<p><b>=== Форматы файлов ===</b></p>"
            "<p>Файлы должны быть в кодировке <b>UTF-8</b>. "
            "Сохраняйте в блокноте через «Сохранить как → UTF-8».<br/>"
            "• .txt — читается построчно. Каждый перенос = отдельная строка. "
            "Пустые строки в середине файла сохраняются.<br/>"
            "• .json — плоский список строк: [«строка 1», «строка 2», ...]. "
            "Перенос внутри строки пишется как <b>\\n</b> "
            "(два символа: обратный слэш и n), на сайте станет &lt;br&gt;.</p>"

            "<p><b>=== Полезно знать ===</b><br/>"
            "• CSRF-токен обновляется автоматически. Если сессия протухла — "
            "программа подтянет новый и повторит запрос.<br/>"
            "• Закрытие окна во время работы пытается прервать задачу, "
            "но 1-2 запроса могут не успеть. На сайте останется частично "
            "изменённое состояние — очистите «Файл оригинала с сайта» "
            "и перезапустите.<br/>"
            "• Для замены в нескольких книгах: запустите «Заменить» "
            "несколько раз, каждый раз с URL новой книги.</p>"

            "</body></html>"
        )

    def _connect(self):
        self.actionRestart.triggered.connect(restart)
        self.actionnotabenoid_org.triggered.connect(self._open_site)
        self.actionGithub_com.triggered.connect(
            lambda: webbrowser.open(GITHUB_URL)
        )
        self.actionQuit.triggered.connect(self.close)

        self.login.textEdited.connect(self._on_login_edit)
        self.password.textEdited.connect(self._on_password_edit)
        self.urlBook.textEdited.connect(self._on_url_edit)

        self.comboBox.currentIndexChanged.connect(self._on_combo)
        self.tabWidget.currentChanged.connect(self._on_tab)
        self.logBox.toggled.connect(self._on_dry_run)
        self.logBox.toggled.connect(self.replaceDryCheck.setChecked)
        self.replaceDryCheck.toggled.connect(self.logBox.setChecked)

        self.btnBrowseOld.clicked.connect(
            lambda: self._pick_file(self.fileNameOld)
        )
        self.btnBrowseNew.clicked.connect(
            lambda: self._pick_file(self.fileNameNew)
        )
        self.btnBrowseTrans.clicked.connect(
            lambda: self._pick_file(self.fileNameTrans)
        )
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
        current = self.tabWidget.currentIndex()
        if current in (int(Tab.ADD), int(Tab.REPLACE)):
            self._dry_run_saved = dry

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
        except OSError as exc:
            QMessageBox.critical(
                self, "File error",
                f"Не удалось прочитать файл:\n{exc}",
            )
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
        self.thread.task_finished.connect(
            lambda _: self._set_running_ui(False)
        )
        self.thread.finished.connect(self._cleanup_thread)
        self.thread.progress_text.connect(self._log)
        self.thread.progress_value.connect(self._progress)
        self.thread.request_diff_preview.connect(
            self._on_request_diff_preview
        )
        self.thread.request_replace_preview.connect(
            self._on_request_replace_preview
        )
        try:
            self.thread.start()
        except Exception as exc:
            self._set_running_ui(False)
            QMessageBox.critical(self, "Thread error", str(exc))

    def _cleanup_thread(self):
        t = self.sender()
        if t is not None:
            t.deleteLater()
        if self.thread is t:
            self.thread = None

    def _on_request_diff_preview(self, payload):
        # Если почему-то открыт предыдущий диалог — закрываем как «отмену»,
        # чтобы его воркер не висел на ожидании Event.
        if self._diff_preview_dlg is not None:
            try:
                self._diff_preview_dlg.reject()
            except RuntimeError:
                pass
            self._diff_preview_dlg = None

        confirm_mode = "event" in payload

        try:
            dlg = DiffPreviewDialog(
                payload["old"], payload["new"], payload["opcodes"], self,
                confirm_mode=confirm_mode,
            )
        except Exception as exc:
            _write_log(f"diff preview error: {exc}")
            self._log(f"Не удалось открыть preview: {exc}")
            # Разбудить воркер как «отменено», чтобы он не висел.
            evt = payload.get("event")
            if evt is not None:
                payload["result"]["confirmed"] = False
                evt.set()
            return

        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.finished.connect(
            lambda code, p=payload: self._on_diff_finished(p, code)
        )
        dlg.showMaximized()
        self._diff_preview_dlg = dlg

    def _on_diff_finished(self, payload, code):
        self._diff_preview_dlg = None
        evt = payload.get("event")
        if evt is None:
            return
        payload["result"]["confirmed"] = (
            int(code) == int(QDialog.DialogCode.Accepted)
        )
        evt.set()

    def _on_request_replace_preview(self, payload):
        if self._replace_preview_dlg is not None:
            try:
                self._replace_preview_dlg.reject()
            except RuntimeError:
                pass
            self._replace_preview_dlg = None

        confirm_mode = "event" in payload

        try:
            dlg = ReplacePreviewDialog(
                payload["entries"], self, confirm_mode=confirm_mode,
            )
        except Exception as exc:
            _write_log(f"replace preview error: {exc}")
            self._log(f"Не удалось открыть preview: {exc}")
            evt = payload.get("event")
            if evt is not None:
                payload["result"]["confirmed"] = False
                evt.set()
            return

        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.finished.connect(
            lambda code, p=payload: self._on_replace_finished(p, code)
        )
        dlg.showMaximized()
        self._replace_preview_dlg = dlg

    def _on_replace_finished(self, payload, code):
        self._replace_preview_dlg = None
        evt = payload.get("event")
        if evt is None:
            return
        payload["result"]["confirmed"] = (
            int(code) == int(QDialog.DialogCode.Accepted)
        )
        evt.set()

    def _build_state(self, tab: Tab) -> Optional[RunState]:
        dry = self.logBox.isChecked()
        state = RunState(
            tab=tab,
            dry_run=dry,
            login=self.login.text(),
            password=self.password.text(),
        )

        url = self.urlBook.text().strip()
        url = url.split("?", 1)[0].split("#", 1)[0].rstrip("/")
        if url.startswith("http://notabenoid.org"):
            url = url.replace(
                "http://notabenoid.org", "https://notabenoid.org", 1
            )
        if url != self.urlBook.text().strip():
            self.urlBook.setText(url)
        state.book_url = url

        if tab == Tab.ADD:
            old_path = self.fileNameOld.text().strip()
            new_path = self.fileNameNew.text().strip()
            if not new_path:
                raise ValueError("Выберите новый файл оригинала")
            if not url and not (old_path and new_path):
                raise ValueError(
                    "Введите URL книги — он нужен, чтобы скачать "
                    "текущий оригинал с сайта"
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
            state.search_text = self.replace_text_orig.toPlainText().strip()
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
        if self._diff_preview_dlg is not None:
            try:
                self._diff_preview_dlg.close()
            except RuntimeError:
                pass
            self._diff_preview_dlg = None
        if self._replace_preview_dlg is not None:
            try:
                self._replace_preview_dlg.close()
            except RuntimeError:
                pass
            self._replace_preview_dlg = None
        if self.thread and self.thread.isRunning():
            self.thread.stop()
            self.thread.wait(2000)
        if self.radioButton_url.isChecked() and self.urlBook.text().strip():
            self.config.save_url(self.urlBook.text().strip())
        _flush_log()
        event.accept()


# --------------------------------------------------------------------------- #
# misc
# --------------------------------------------------------------------------- #

def restart():
    if getattr(sys, "frozen", False):
        os.execl(sys.executable, sys.executable, *sys.argv[1:])
    else:
        os.execl(sys.executable, sys.executable,
                 os.path.abspath(__file__), *sys.argv[1:])


if __name__ == "__main__":
    freeze_support()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())