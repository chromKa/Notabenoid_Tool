import datetime
import difflib
import math
import os
import sys
import time
import webbrowser
from multiprocessing import Pool, freeze_support
from sys import argv, executable
import hashlib
import json
from typing import Dict, List, Tuple, Optional

import replace
import res
import table
import main_ui as design
import requests
from PyQt6 import QtWidgets, QtGui, QtCore
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QFontDatabase, QFont, QPalette, QColor
from PyQt6.QtWidgets import QMainWindow, QApplication, QDialog, QTableWidgetItem, QMessageBox
from bs4 import BeautifulSoup

# Конфигурация
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 '
                  'YaBrowser/23.1.3.949 Yowser/2.5 Safari/537.36',
}
BASE_URL = 'http://notabenoid.org/'
CONFIG_FILE = './config.json'
LOG_FILE = 'notabenoid_log.txt'


class Config:
    def __init__(self):
        self.url_book = ''
        self.login = ''
        self.password_hash = ''
        self.last_url = ''

    def load(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.login = data.get('login', '')
                    self.password_hash = data.get('password_hash', '')
                    self.last_url = data.get('last_url', '')
        except Exception as e:
            self._log_error(f"Error loading config: {str(e)}")

    def save(self):
        try:
            data = {
                'login': self.login,
                'password_hash': self.password_hash,
                'last_url': self.last_url
            }
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._log_error(f"Error saving config: {str(e)}")

    def set_credentials(self, login: str, password: str):
        self.login = login
        self.password_hash = self._hash_password(password)
        self.save()

    def _hash_password(self, password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()

    def _log_error(self, message: str):
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{datetime.datetime.now()}: {message}\n")


class SessionManager:
    def __init__(self):
        self.session = requests.Session()
        self.headers = DEFAULT_HEADERS
        self.config = Config()
        self.config.load()

    def login(self, login: str, password: str, save_credentials: bool = False) -> bool:
        if save_credentials:
            self.config.set_credentials(login, password)

        data = {
            'login[login]': login,
            'login[pass]': password,
        }

        try:
            response = self.session.post(BASE_URL, headers=self.headers, data=data, verify=False)
            return response.status_code == requests.codes.ok
        except requests.RequestException as e:
            self._log_error(f"Login error: {str(e)}")
            return False

    def get_page(self, url: str, max_retries: int = 3) -> Optional[BeautifulSoup]:
        for _ in range(max_retries):
            try:
                response = self.session.get(url, headers=self.headers)
                if response.status_code == 200:
                    return BeautifulSoup(response.text, "html.parser")
            except requests.RequestException as e:
                self._log_error(f"Request error for {url}: {str(e)}")
                time.sleep(1)
        return None

    def post_data(self, url: str, data: dict) -> bool:
        try:
            response = self.session.post(url, headers=self.headers, data=data, verify=False)
            return response.status_code == 200
        except requests.RequestException as e:
            self._log_error(f"POST error for {url}: {str(e)}")
            return False

    def _log_error(self, message: str):
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{datetime.datetime.now()}: {message}\n")


class BookManager:
    def __init__(self, session_manager: SessionManager):
        self.sm = session_manager

    def get_last_page_number(self, book_url: str) -> int:
        soup = self.sm.get_page(book_url)
        if not soup:
            return 1

        pagination = soup.find_all('ul', class_='selectable')
        if not pagination:
            return 1

        pages = pagination[0].find_all('a')
        return int(pages[-1].text) if pages else 1

    def get_page_ids(self, page_url: str) -> List[str]:
        soup = self.sm.get_page(page_url)
        if not soup:
            return []

        rows = soup.find_all('tr')
        if not rows:
            return []

        return [row.get('id').replace("o", "") for row in rows if row.get('id')]

    def get_text_from_page(self, page_url: str) -> List[str]:
        soup = self.sm.get_page(page_url)
        if not soup:
            return []

        rows = soup.find_all('tbody')[0].findAll('tr')
        return [row.find('p', class_='text').get_text().rstrip() for row in rows if row.find('p', class_='text')]

    def get_translation_from_page(self, page_url: str) -> List[str]:
        soup = self.sm.get_page(page_url)
        if not soup:
            return []

        rows = soup.find_all('tbody')[0].findAll('tr')
        translations = []

        for row in rows:
            trans = row.find(class_='t').find_all('p', class_='text')
            if len(trans) > 1:
                translations.append(row.find(class_='t').find(class_='best').find(class_='text').get_text().rstrip())
            elif trans:
                translations.append(trans[0].text.rstrip())
            else:
                translations.append('')

        return translations


class TaskThread(QThread):
    started = pyqtSignal(str)
    progress_value = pyqtSignal(int)
    dialog = pyqtSignal(bool)
    progress_text = pyqtSignal(str)
    finished = pyqtSignal(str)

    def __init__(self, task_id: int = 1, sleep_time: float = 0.0):
        super().__init__()
        self.task_id = task_id
        self.sleep_time = sleep_time
        self.sm = SessionManager()
        self.bm = BookManager(self.sm)
        self.running = True

    def stop(self):
        self.running = False

    def run(self):
        try:
            self.started.emit(f"Task {self.task_id} started")

            if not self.running:
                return

            # Здесь должна быть основная логика задачи
            time.sleep(self.sleep_time)  # Пример задержки

            self.finished.emit(f"Task {self.task_id} completed")
        except Exception as e:
            self.progress_text.emit(f"Error in task {self.task_id}: {str(e)}")
            self.finished.emit(f"Task {self.task_id} failed")


class TableDialog(QDialog, table.Ui_Dialog):
    def __init__(self, old_data: Dict[int, str], new_data: Dict[int, str]):
        super().__init__()
        self.setupUi(self)
        self.setWindowIcon(QtGui.QIcon(':/d/Untitled-12.png'))
        self.result_data = {}

        self.initialize_table(old_data, new_data)

    def initialize_table(self, old_data: Dict[int, str], new_data: Dict[int, str]):
        self.tableWidget.setRowCount(len(new_data))

        for row, (key, value) in enumerate(new_data.items()):
            self.tableWidget.setVerticalHeaderItem(row, QtWidgets.QTableWidgetItem(str(key)))
            self.tableWidget.setItem(row, 1, QTableWidgetItem(str(value)))
            self.tableWidget.item(row, 1).setFlags(QtCore.Qt.ItemFlag.ItemIsEditable)

            if key in old_data:
                self.tableWidget.setItem(row, 0, QTableWidgetItem(old_data[key]))

    def get_results(self) -> Dict[int, str]:
        results = {}
        for row in range(self.tableWidget.rowCount()):
            key_item = self.tableWidget.verticalHeaderItem(row)
            value_item = self.tableWidget.item(row, 1)

            if key_item and value_item:
                try:
                    key = int(key_item.text())
                    results[key] = value_item.text()
                except ValueError:
                    continue
        return results


class MainWindow(QMainWindow, design.Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.sm = SessionManager()
        self.bm = BookManager(self.sm)
        self.current_task = None

        self.initialize_ui()
        self.connect_signals()

    def initialize_ui(self):
        self.setWindowIcon(QtGui.QIcon(':/d/Untitled-12.png'))
        self.setWindowFlags(self.windowFlags() |
                            QtCore.Qt.WindowType.WindowSystemMenuHint |
                            QtCore.Qt.WindowType.WindowMinMaxButtonsHint)

        # Инициализация шрифтов
        self.initialize_fonts()

        # Настройка элементов интерфейса
        self.setup_interface()

    def initialize_fonts(self):
        font_id = QFontDatabase.addApplicationFont(":/d/DINPro-CondensedMedium.ttf")
        font_family = QFontDatabase.applicationFontFamilies(font_id)[0]

        # Применение шрифта к элементам интерфейса
        widgets = [
            self.logBoxAdd, self.logBoxRefresh, self.logBoxDownload,
            self.fileNameOld, self.fileNameNew, self.comment,
            self.lineNumber, self.progressBarRefresh, self.progressBarDownload,
            self.radioButton_replace, self.logBoxReplace, self.replacement_text,
            self.replace_text_orig, self.replacement_text_n, self.replace_text_orig_n,
            self.lineEdit_repl, self.url_main_text, self.radioButton,
            self.radioButton_insert, self.btnBrowseOld, self.btnBrowseNew,
            self.btnStartAdd, self.btnStartRefresh, self.btnStartDownload,
            self.btnStartReplace, self.btnBrowseTrans, self.btnStartTrans,
            self.fileNameTrans, self.logBoxTrans, self.refreshText,
            self.lineEditSave, self.btnBrowseSave, self.loginText,
            self.passwordText, self.urlBookText, self.comboBox,
            self.comboBox_replace, self.logBox, self.tabWidget,
            self.login, self.password, self.urlBook, self.menubar
        ]

        for widget in widgets:
            if hasattr(widget, 'setFont'):
                widget.setFont(QFont(font_family, 12))

    def setup_interface(self):
        # Настройка прогресс-баров
        for progress_bar in [self.progressBarRefresh, self.progressBarDownload]:
            progress_bar.setRange(0, 100)
            progress_bar.setValue(0)

        # Настройка placeholder текста
        self.login.setPlaceholderText("login")
        self.password.setPlaceholderText("password")
        self.urlBook.setPlaceholderText("http://notabenoid.org/book/12345/6789")

        # Начальное состояние
        self.tabWidget.setCurrentIndex(0)
        self.radioButton_insert.setVisible(False)

        # Загрузка сохраненных данных
        self.load_saved_data()

    def load_saved_data(self):
        if self.sm.config.login:
            self.login.setText(self.sm.config.login)
        if self.sm.config.last_url:
            self.urlBook.setText(self.sm.config.last_url)

    def connect_signals(self):
        # Кнопки
        self.btnBrowseOld.clicked.connect(self.browse_old_file)
        self.btnBrowseNew.clicked.connect(self.browse_new_file)
        self.btnBrowseTrans.clicked.connect(self.browse_trans_file)
        self.btnBrowseSave.clicked.connect(self.browse_save_file)

        self.btnStartAdd.clicked.connect(self.start_add_task)
        self.btnStartRefresh.clicked.connect(self.start_refresh_task)
        self.btnStartDownload.clicked.connect(self.start_download_task)
        self.btnStartReplace.clicked.connect(self.start_replace_task)
        self.btnStartTrans.clicked.connect(self.start_trans_task)

        # Чекбоксы и радиокнопки
        self.logBox.clicked.connect(self.toggle_login_fields)
        self.radioButton.toggled.connect(self.toggle_save_credentials)

        # Комбо-боксы
        self.comboBox.currentIndexChanged.connect(self.toggle_translation_options)
        self.tabWidget.currentChanged.connect(self.tab_changed)

    def toggle_login_fields(self, checked: bool):
        self.login.setEnabled(not checked)
        self.password.setEnabled(not checked)
        self.urlBook.setEnabled(not checked)

        # Отключаем кнопки, если включен лог-бокс
        for btn in [self.btnStartRefresh, self.btnStartDownload,
                    self.btnStartReplace, self.btnStartTrans]:
            btn.setDisabled(checked)

        # Кнопка добавления всегда активна
        self.btnStartAdd.setDisabled(False)

    def toggle_save_credentials(self, checked: bool):
        if checked and self.login.text() and self.password.text():
            self.sm.config.set_credentials(self.login.text(), self.password.text())

    def toggle_translation_options(self, index: int):
        self.radioButton_insert.setVisible(index == 1)
        self.radioButton_insert.setEnabled(index == 1)

    def tab_changed(self, index: int):
        self.urlBook.setVisible(index != 3)

    def browse_old_file(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select Original File")
        if filename:
            self.fileNameOld.setText(filename)

    def browse_new_file(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select New File")
        if filename:
            self.fileNameNew.setText(filename)

    def browse_trans_file(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select Translation File")
        if filename:
            self.fileNameTrans.setText(filename)

    def browse_save_file(self):
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save File")
        if filename:
            self.lineEditSave.setText(filename)

    def validate_inputs(self) -> bool:
        # Проверка обязательных полей в зависимости от вкладки
        current_tab = self.tabWidget.currentIndex()

        if current_tab == 0:  # Добавить оригинал
            if not self.fileNameOld.text() or not self.fileNameNew.text():
                self.show_error("Please select both original and new files")
                return False
        elif current_tab == 1:  # Обновить ID
            if not self.lineNumber.text().isdigit():
                self.show_error("Please enter a valid line number")
                return False
        elif current_tab == 3:  # Заменить текст
            if not self.url_main_text.text():
                self.show_error("Please enter book URL")
                return False
            if not self.replace_text_orig.toPlainText():
                self.show_error("Please enter text to replace")
                return False
        elif current_tab == 4:  # Добавить перевод
            if not self.fileNameTrans.text():
                self.show_error("Please select translation file")
                return False

        return True

    def show_error(self, message: str):
        QMessageBox.critical(self, "Error", message)

    def start_add_task(self):
        if not self.validate_inputs():
            return

        self.logBoxAdd.clear()
        self.current_task = TaskThread(1)
        self.connect_task_signals(self.current_task, self.logBoxAdd)
        self.current_task.start()

    def start_refresh_task(self):
        if not self.validate_inputs():
            return

        self.logBoxRefresh.clear()
        self.current_task = TaskThread(2)
        self.connect_task_signals(self.current_task, self.logBoxRefresh)
        self.current_task.start()

    def start_download_task(self):
        if not self.validate_inputs():
            return

        self.logBoxDownload.clear()
        self.current_task = TaskThread(3)
        self.connect_task_signals(self.current_task, self.logBoxDownload)
        self.current_task.start()

    def start_replace_task(self):
        if not self.validate_inputs():
            return

        self.logBoxReplace.clear()
        self.current_task = TaskThread(4)
        self.connect_task_signals(self.current_task, self.logBoxReplace)
        self.current_task.start()

    def start_trans_task(self):
        if not self.validate_inputs():
            return

        self.logBoxTrans.clear()
        self.current_task = TaskThread(5)
        self.connect_task_signals(self.current_task, self.logBoxTrans)
        self.current_task.start()

    def connect_task_signals(self, task: TaskThread, log_widget):
        task.started.connect(lambda msg: log_widget.append(msg))
        task.progress_value.connect(self.update_progress)
        task.progress_text.connect(lambda msg: log_widget.append(msg))
        task.finished.connect(lambda msg: log_widget.append(msg))

        task.started.connect(self.disable_buttons)
        task.finished.connect(self.enable_buttons)

    def update_progress(self, value: int):
        current_tab = self.tabWidget.currentIndex()

        if current_tab == 1:  # Обновить ID
            self.progressBarRefresh.setValue(value)
        elif current_tab == 2:  # Скачать текст
            self.progressBarDownload.setValue(value)

    def disable_buttons(self):
        self.btnStartAdd.setDisabled(True)
        if not self.logBox.isChecked():
            for btn in [self.btnStartRefresh, self.btnStartDownload,
                        self.btnStartReplace, self.btnStartTrans]:
                btn.setDisabled(True)
        self.logBox.setDisabled(True)

    def enable_buttons(self):
        self.btnStartAdd.setDisabled(False)
        if not self.logBox.isChecked():
            for btn in [self.btnStartRefresh, self.btnStartDownload,
                        self.btnStartReplace, self.btnStartTrans]:
                btn.setDisabled(False)
        self.logBox.setDisabled(False)

    def closeEvent(self, event):
        if self.current_task and self.current_task.isRunning():
            self.current_task.stop()
            self.current_task.wait(2000)  # Даем потоку 2 секунды на завершение

        # Сохраняем последний URL
        if self.urlBook.text():
            self.sm.config.last_url = self.urlBook.text()
            self.sm.config.save()

        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    freeze_support()

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()