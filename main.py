import datetime
import difflib
import math
import os
import sys
import time
import webbrowser
from multiprocessing import Pool, freeze_support
from sys import argv, executable

import replace
import res
import table
import main_ui as design
import requests
from PyQt6 import QtWidgets, QtGui, QtCore
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QFontDatabase, QFont, QPalette, QColor
from PyQt6.QtWidgets import QMainWindow, QApplication, QDialog, QTableWidgetItem
from bs4 import BeautifulSoup

session = requests.Session()
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 '
                  'YaBrowser/23.1.3.949 Yowser/2.5 Safari/537.36',
}
url = 'http://notabenoid.org/'
url_book = ' '
login_text = ''
password_text = ''
num_with_plus_check = []
num_with_minus_check = []
check_tab = 0
line_number = 1
file_name_old = ' '
file_name_new = ' '
file_name_trans = ' '
file_name_save = ' '
f1_data = []
f2_data = []
log_box = True
insert_radio = True
entire_radio = True
comment_text = ' '
combo_box_index = 0
time_start = 0.0
error = False
count_text = 0
bar_int = 1
old_dialog = {}
new_dialog = {}
dialog_b = 10
ch_old = {}
count_delete = 0
count_swap = 0
count_add = 0
url_book_main = ''
word_text_orig = ''
word_replacement = ''


class Table(QDialog, table.Ui_Dialog):
    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.setWindowIcon(QtGui.QIcon(':/d/Untitled-12.png'))
        global ch_old
        ch_old = {}
        old = 0
        new = 1
        self.setWindowTitle(" ")
        self.setWindowFlags(self.windowFlags() |
                            QtCore.Qt.WindowType.WindowSystemMenuHint |
                            QtCore.Qt.WindowType.WindowMinMaxButtonsHint)

        self.tableWidget.setRowCount(len(new_dialog))

        u = 0
        for key, value in new_dialog.items():
            self.tableWidget.setVerticalHeaderItem(u, QtWidgets.QTableWidgetItem())
            self.tableWidget.verticalHeaderItem(u).setText(str(key))
            self.tableWidget.setItem(u, new, QTableWidgetItem(str(value)))
            self.tableWidget.item(u, new).setFlags(QtCore.Qt.ItemFlag.ItemIsEditable)
            u += 1

        u = 0
        for key, value in old_dialog.items():
            self.tableWidget.setItem(u, old, QTableWidgetItem(value))
            u += 1

        ret = self.exec()
        self.get_text()

        global dialog_b
        dialog_b = ret

    def get_text(self):
        global ch_old
        ch_old = {}
        for i in range(len(new_dialog)):
            try:
                item = self.tableWidget.item(i, 0)
                item2 = self.tableWidget.item(i, 1)
                if item and item.text() != '':

                    for key, value in new_dialog.items():

                        if item2.text() == value:
                            ch_old[key] = item2.text()

                    # ch_old[int(new_dialog.get(item2.text()))] = item2.text()
            except Exception:
                ...


class TaskThread(QThread):
    # Using class variables for signals to avoid re-creating them in each instance
    started = pyqtSignal(str)  # Signal emitted when a task starts
    progress_value = pyqtSignal(int)  # Signal for updating progress value
    dialog = pyqtSignal(bool)
    progress_text = pyqtSignal(str)  # Signal for updating progress text
    finished = pyqtSignal(str)  # Signal emitted when a task finishes

    def __init__(self, task_id=1, sleep_time=0.0):
        super().__init__()
        self.task_id = task_id
        self.sleep_time = sleep_time

    def stand_add_del(self, delete_add, arr_add, arr_add_str, delete_add_str):
        global count_text
        global bar_int
        global old_dialog
        global new_dialog
        global dialog_b
        global count_add
        global count_swap
        dialog_b = 10
        old_dialog = {}
        new_dialog = {}

        if len(arr_add) == len(delete_add):
            for i in range(len(delete_add)):
                if not log_box:
                    check_error = change_str(arr_add[i], arr_add_str[i])
                    if check_error == 'error':
                        return 'error'
                count_text += 1
                self.progress_text.emit('swap ' + str(count_text) + ') ' + str(arr_add[i]) + ': ' + arr_add_str[i])
                count_swap += 1

        elif len(arr_add) > len(delete_add):
            if len(delete_add) == 0:
                for i in range(len(arr_add)):
                    if not log_box:
                        check_error = add_str(arr_add[i], arr_add_str[i])
                        if check_error == 'error':
                            return 'error'
                    count_text += 1
                    self.progress_text.emit('add ' + str(count_text) + ') ' + str(arr_add[i]) + ': ' + arr_add_str[i])
                    count_add += 1

            elif len(delete_add) != 0:
                t_dict = {}
                t_dict_n = {}
                for i in range(len(delete_add)):
                    t_dict[delete_add[i]] = delete_add_str[i]
                    old_dialog = dict(sorted(t_dict.items()))
                for i in range(len(arr_add)):
                    t_dict_n[arr_add[i]] = arr_add_str[i]
                    new_dialog = dict(sorted(t_dict_n.items()))

                self.dialog.emit(True)
                while dialog_b == 10:
                    time.sleep(1)
                if dialog_b == 0:
                    return 'exit'
                for i in range(len(arr_add)):
                    if arr_add[i] in ch_old:
                        if not log_box:
                            check_error = change_str(arr_add[i], arr_add_str[i])
                            if check_error == 'error':
                                return 'error'
                        count_text += 1
                        self.progress_text.emit(
                            'swap ' + str(count_text) + ') ' + str(arr_add[i]) + ': ' + arr_add_str[i])
                        count_swap += 1
                    else:
                        if not log_box:
                            check_error = add_str(arr_add[i], arr_add_str[i])
                            if check_error == 'error':
                                return 'error'
                        count_text += 1
                        self.progress_text.emit(
                            'add ' + str(count_text) + ') ' + str(arr_add[i]) + ': ' + arr_add_str[i])
                        count_add += 1
        '''
        elif len(delete_add) > len(arr_add):
            for i in range(len(arr_add)):
                if not log_box:
                    change_str(arr_add[i], arr_add_str[i])
                count_text += 1
                self.progress_text.emit('swap ' + str(count_text) + ') ' + str(arr_add[i]) + ': ' + arr_add_str[i])
            delete_add.reverse()
            delete_add_str.reverse()
            for p in range(len(delete_add)-len(arr_add)):
                if not log_box:
                    delete_str(delete_add[p])
                self.progress_text.emit('delete ' + str(count_text) + ') ' + str(delete_add[p]) + ': ' 
                + delete_add_str[p])

            if not log_box:
                self.refresh_id1(delete_add[-1])
        '''

    def add_number_unidiff(self, s):
        global count_text
        global f1_data
        result = []
        count_del = 0

        for l in s:
            if l[-3:] == '@@\n':
                tmp = l[4:].split(' ')[0].split(',')
                delete_add = []
                arr_add = []
                arr_add_str = []
                str_del = []
                add_num_str = 0
                if len(tmp) > 1:
                    add_num_str = int(tmp[1])
                    for i in range(int(tmp[1])):
                        delete_add.append(int(tmp[0]) + i + count_del)
                        str_del.append(s[s.index(l) + 1 + i].removeprefix('-'))
                elif len(tmp) == 1:
                    add_num_str = 1
                    delete_add.append(int(tmp[0]) + count_del)
                    str_del.append(s[s.index(l) + 1].removeprefix('-'))

                tmp_add = l[4:].split(' ')[1].removeprefix('+').split(',')

                if len(tmp_add) > 1:
                    for i in range(int(tmp_add[1])):
                        arr_add.append(int(tmp_add[0]) + i)
                        arr_add_str.append(s[s.index(l) + add_num_str + 1 + i].removeprefix('+'))
                        result.append(int(tmp_add[0]) + i)
                elif len(tmp_add) == 1:
                    arr_add.append(int(tmp_add[0]))
                    arr_add_str.append(s[s.index(l) + add_num_str + 1].removeprefix('+'))
                    result.append(int(tmp_add[0]))

                check_exit = self.stand_add_del(delete_add, arr_add, arr_add_str, str_del)
                if check_exit == 'exit':
                    return 'exit'
                if check_exit == 'error':
                    return 'error'
                if not log_box:
                    # count_del += len(arr_add)-len(delete_add)
                    ...

        return result

    def delete_number_unidiff(self, s):
        global f1_data
        global count_delete
        result = {}
        for l in s:
            if l[-3:] == '@@\n':
                # check , in first number
                tmp = l[4:].split(' ')[0].split(',')
                delete_add = []
                arr_add = []
                str_del = []
                if len(tmp) > 1:
                    for i in range(int(tmp[1])):
                        delete_add.append(int(tmp[0]) + i)
                        str_del.append(s[s.index(l) + 1 + i].removeprefix('-'))
                elif len(tmp) == 1:
                    delete_add.append(int(tmp[0]))
                    str_del.append(s[s.index(l) + 1].removeprefix('-'))

                tmp_add = l[4:].split(' ')[1].removeprefix('+').split(',')

                if len(tmp_add) > 1:
                    for i in range(int(tmp_add[1])):
                        arr_add.append(int(tmp_add[0]) + i)
                elif len(tmp_add) == 1:
                    arr_add.append(int(tmp_add[0]))

                if len(delete_add) > len(arr_add):
                    # delete_add.reverse()
                    for p in range(len(arr_add), len(delete_add)):
                        result[delete_add[p]] = str_del[p]

        sorted_dict = {key: value for key, value in sorted(result.items(), key=lambda item: item[0], reverse=True)}

        # reverse_dict = dict(reversed(sorted_dict.items()))
        # result.reverse()

        if len(sorted_dict) > 0:
            for key, value in sorted_dict.items():
                if not log_box:
                    check_error = delete_str(int(key))
                    if check_error == 'error':
                        return 'error'
                f1_data.pop(int(key) - 1)

                self.progress_text.emit('Delete ' + str(key) + ': ' + str(value))
                count_delete += 1

            if not log_box:
                self.refresh_id1(list(sorted_dict.items())[-1][0])

    def refresh_id1(self, count_t, count_url_bar=1):
        try:
            time.sleep(self.sleep_time)
            page_last_number = int(last_page())
            int_url_id = math.ceil(int(count_t) / 50)
            count_id_urls = int_url_id * 50 - 49

            range_url_ids = page_last_number - int_url_id
            count_bar_refresh = ((range_url_ids + 1) * 50) // 100
            # parce pages

            count_url = 0
            for i in range(range_url_ids + 1):

                url_parce = url_book + '?Orig_page=' + str(i + int_url_id)

                number_chapter_id_str = create_list_ids(url_parce)

                for id_url_str in number_chapter_id_str:

                    data1 = {
                        'Orig[ord]': count_id_urls,
                        'ajax': '1',
                    }

                    session.post(url_book + '/' + id_url_str + '/edit', headers=headers, data=data1, verify=False)

                    count_id_urls += 1
                    count_url += 1
                    if count_url // count_url_bar == count_bar_refresh and count_url_bar != 100:
                        if check_tab != 0:
                            self.progress_value.emit(count_url_bar)
                            count_url_bar += 1
                    self.progress_text.emit('Refresh IDs: ' + str(count_url) + ' - ' + str(count_id_urls - 1))

        except Exception as v:
            exc = v
            self.progress_text.emit(str(exc) + ' refresh')
            return

    def add_comment(self, id_list, string):
        count = 1
        for count_t in id_list:
            page_number = math.ceil(int(count_t) / 50)
            url_parce = url_book + '?Orig_page=' + str(page_number)
            number_chapter_id_str = create_list_ids(url_parce)
            id_hash = number_chapter_id_str[(int(count_t) - 50 * (page_number - 1)) % 50 - 1]

            data1 = {
                'Comment[body]:': string,
                'Comment[pid]': '0',
                'ajax': '1',
            }

            session.post(url_book + '/' + id_hash + '/c0' + '/reply', headers=headers, data=data1, verify=False)
            # self.progress_text.emit(str(count))
            count += 1
        self.progress_text.emit(str(count))

    def compare(self):
        result_orig = list(difflib.unified_diff(f1_data, f2_data, n=0))
        if len(result_orig) > 0:

            check_error = self.delete_number_unidiff(result_orig)
            if check_error == 'error':
                return 'error'

            result_orig1 = list(difflib.unified_diff(f1_data, f2_data, n=0))

            comment_id_list = self.add_number_unidiff(result_orig1)
            if comment_id_list == 'exit':
                return 'exit'
            if comment_id_list == 'error':
                return 'error'
            if not log_box and comment_text != ' ':
                self.progress_text.emit('Add comments:')
                self.add_comment(comment_id_list, comment_text)
            self.progress_text.emit('Add: ' + str(count_add) + ', Swap: ' + str(count_swap) + ', Delete: '
                                    + str(count_delete))

    def all_str_c(self):
        try:
            time.sleep(self.sleep_time)
            self.progress_value.emit(1)
            page_last_number = int(last_page())
            self.progress_text.emit(str('start'))

            rt = []
            count = 1
            count_url_bar = 1
            count_bar_refresh = page_last_number * 50 // 100
            for i in range(page_last_number):
                url_parce = url_book + '?Orig_page=' + str(i + 1)

                page = session.get(url_parce, headers=headers)
                if page.status_code != 200:
                    while page.status_code != 200:
                        page = session.get(url_parce, headers=headers)
                soup = BeautifulSoup(page.text, "html.parser")
                # add title
                number_chapter = soup.find_all('tbody')[0].findAll('tr')

                for im in number_chapter:
                    rt.append(im.find('p', class_='text').get_text().rstrip())
                    if len(rt) // count_url_bar == count_bar_refresh and count_url_bar != 100:
                        self.progress_value.emit(count_url_bar)
                        count_url_bar += 1
            global file_name_save
            if not file_name_save:
                file_name_save = 'binary_orig_from_site.txt'

            with open(file_name_save, "w", encoding="utf-8") as t:
                for i in rt:
                    count += 1
                    t.write(str(i) + '\n')
            self.progress_text.emit(file_name_save)
        except Exception as m:
            exc = m
            self.progress_text.emit(str(exc))
            return

    def add_trans(self):
        try:
            page_last_number = int(last_page())
            ids_last_page = create_list_ids(url_book + '?Orig_page=' + str(page_last_number))

            with open(file_name_trans, "r", encoding="utf-8") as f1:
                all_file_str = f1.readlines()
            if len(ids_last_page) + 50 * (page_last_number - 1) != len(all_file_str):
                self.progress_text.emit('different string length:')
                self.progress_text.emit(
                    str(len(ids_last_page) + 50 * (page_last_number - 1)) + ' ' + str(len(all_file_str)))
                return 'error'

            for i in range(page_last_number):
                url_parce = url_book + '?Orig_page=' + str(i + 1)
                ids_orig = create_list_ids(url_parce)
                for id_o in range(len(ids_orig)):
                    text_add = all_file_str[id_o + 50 * i]

                    data1 = {
                        'Translation[body]:': text_add,
                        'ajax': '1',
                    }
                    self.progress_text.emit(str(id_o + 50 * i))

                    if text_add != '' and text_add:
                        session.post(url_book + '/' + ids_orig[id_o] + '/translate', headers=headers, data=data1,
                                     verify=False)
        except Exception as exc:
            self.progress_text.emit(str(exc))
            return 'error'

    def all_str_trans(self):
        try:
            page_last_number = int(last_page())
            self.progress_value.emit(1)
            self.progress_text.emit(str('start'))

            rt = []
            count_url_bar = 1
            count_bar_refresh = page_last_number * 50 // 100

            for i in range(page_last_number):
                url_parce = url_book + '?Orig_page=' + str(i + 1)

                page = session.get(url_parce, headers=headers)
                if page.status_code != 200:
                    while page.status_code != 200:
                        page = session.get(url_parce, headers=headers)
                soup = BeautifulSoup(page.text, "html.parser")

                number_chapter = soup.find_all('tbody')[0].findAll('tr')

                for im in number_chapter:
                    tt = im.find(class_='t').find_all('p', class_='text')
                    if len(tt) > 1:
                        rt.append(im.find(class_='t').find(class_='best').find(class_='text').get_text().rstrip())
                    else:
                        if tt:
                            rt.append(tt[0].text.rstrip())
                        elif insert_radio:
                            rt.append(im.find(class_='o').find('p', class_='text').get_text().rstrip())
                        else:
                            rt.append('')
                    if len(rt) // count_url_bar == count_bar_refresh and count_url_bar != 100:
                        self.progress_value.emit(count_url_bar)
                        count_url_bar += 1
            global file_name_save
            if not file_name_save:
                file_name_save = 'binary_trans_from_site.txt'
            with open(file_name_save, "w", encoding="utf-8") as t:
                for i in rt:
                    t.write(str(i) + '\n')
            self.progress_text.emit(file_name_save)
        except Exception as m:
            exc = m
            self.progress_text.emit(str(exc))
            return

    def compare_string_trans(self, str_translate, id_trans, id_str_original, id_book):
        try:
            if not entire_radio:
                if word_text_orig in str_translate:

                    text_repl = str_translate
                    count_replace = 0
                    start_index = 0

                    # count similar
                    for i in range(len(text_repl)):
                        j = text_repl.find(word_text_orig, start_index)
                        if j != -1:
                            start_index = j + 1
                            count_replace += 1

                    temp_rep = '#replace_temp_placeholder'
                    t = ''
                    for i in range(count_replace):
                        t = text_repl.replace(word_text_orig, temp_rep)
                    for i in range(count_replace):
                        text_repl = t.replace(temp_rep, word_replacement)

                    check_er = replace_site_text(id_trans, id_str_original, id_book, text_repl)

                    if check_er == 'error':
                        return check_er

                    return text_repl
            else:
                if str_translate == word_text_orig or str_translate.strip() == word_text_orig:

                    check_er = replace_site_text(id_trans, id_str_original, id_book, word_replacement)

                    if check_er == 'error':
                        return check_er

                    return word_replacement

        except Exception as exc:
            self.progress_text.emit(str(exc))

    def replace_text(self):
        try:
            if not word_text_orig or not word_replacement:
                return 'error'
            ids_books, name_books = id_books()

            if ids_books == 'error':
                return 'error'
            for id_book in ids_books:
                data_pool = []
                url_book_t = url_book_main + '/' + id_book
                all_links = get_all_links(url_book_t)
                for link in all_links:
                    data_pool.append({link: session})

                with Pool(10) as p:
                    data = p.map(replace.make_all, data_pool)

                for num_page, dic in enumerate(data):
                    for num_orig, id_str_original in enumerate(dic):
                        for dic_translate in dic[id_str_original]:
                            for key_dic_translate in dic_translate:
                                word_rep = self.compare_string_trans(dic_translate[key_dic_translate],
                                                                     key_dic_translate, id_str_original, id_book)
                                if word_rep == 'error':
                                    return word_rep
                                if word_rep:
                                    self.progress_text.emit(str(name_books[ids_books.index(id_book)])
                                                            + ' (' + str(id_book) + ') \n' + str(id_str_original)
                                                            + ':\n'
                                                            + str(dic_translate[key_dic_translate])
                                                            + ' => ' + word_rep + '\n')
                                    print(word_rep)
        except Exception as exc:
            self.progress_text.emit(str(exc))
            return 'error'

    def run(self):
        # Emit signal to notify the start of the task
        if check_tab == 0:
            self.started.emit(f"Task Add **** START.")
        elif check_tab == 1:
            self.started.emit(f"Task Refresh IDs **** START.")
        elif check_tab == 2:
            self.started.emit(f"Task Download Text **** START.")
        elif check_tab == 3:
            self.started.emit(f"Task Replace Text **** START.")
        elif check_tab == 4:
            self.started.emit(f"Task Add Translated Text **** START.")
        global count_text
        count_text = 0
        global count_add
        global count_swap
        global count_delete
        count_swap = 0
        count_add = 0
        count_delete = 0
        # Simulate work by updating progress signals
        # for i in range(100):
        # time.sleep(self.sleep_time)
        # self.progress_value.emit(i + 1)
        # self.progress_text.emit(f"Task {self.task_id} >>> {i + 1}")
        # function
        data = {
            'login[login]': login_text,
            'login[pass]': password_text,
        }

        if login_text != '' and password_text != '':
            result = session.post(url, headers=headers, data=data, verify=False)
            if result.status_code != requests.codes.ok:
                self.finished.emit(f"Error **** END.")
                return

        self.progress_value.emit(0)
        if check_tab == 0:
            check_exit = self.compare()
            if check_exit == 'exit':
                self.progress_text.emit('You clicked the cancel button.')
            elif check_exit == 'error':
                self.progress_text.emit('Error. You may have selected the wrong row in the table.')
            else:
                self.progress_value.emit(100)
        elif check_tab == 1:
            self.refresh_id1(line_number)
            self.progress_value.emit(100)
        elif check_tab == 2:
            if combo_box_index == 0:
                self.all_str_c()
            elif combo_box_index == 1:
                self.all_str_trans()
            self.progress_value.emit(100)
        elif check_tab == 3:
            check_er = self.replace_text()
            if check_er == 'error':
                self.progress_text.emit('Error.')
        elif check_tab == 4:
            check_er = self.add_trans()
            if check_er == 'error':
                self.progress_text.emit('Error.')

        global error
        global url_book_main
        global word_replacement
        global word_text_orig
        error = False
        url_book_main = ''
        word_text_orig = ''
        word_replacement = ''

        t = str(round(time.time() - time_start))
        if check_tab == 0:
            self.finished.emit(f"Task Add **** END." + '\n' + t + ' sec')
        elif check_tab == 1:
            self.finished.emit(f"Task Refresh IDs **** END." + '\n' + t + ' sec')
        elif check_tab == 2:
            self.finished.emit(f"Task Download Text **** END." + '\n' + t + ' sec')
        elif check_tab == 3:
            self.finished.emit(f"Task Replace Text **** END." + '\n' + t + ' sec')
        elif check_tab == 4:
            self.finished.emit(f"Task Add Translated Text **** END." + '\n' + t + ' sec')


class MainWindow(QMainWindow, design.Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)
        # Load the UI from the .ui file
        # self.ui = uic.loadUi('main.ui', self)
        self.open_login()
        self.open_pass()
        self.setWindowIcon(QtGui.QIcon(':/d/Untitled-12.png'))
        # Dictionary to store task threads
        self.threads = {}
        self.radioButton_insert.setVisible(False)
        # self.setWindowFlags(QtCore.Qt.WindowType.MaximizeUsingFullscreenGeometryHint)
        id1 = QFontDatabase.addApplicationFont(":/d/DINPro-CondensedMedium.ttf")
        self.logBoxAdd.setFont(QFont(QFontDatabase.applicationFontFamilies(id1)))
        self.logBoxRefresh.setFont(QFont(QFontDatabase.applicationFontFamilies(id1)))
        self.logBoxDownload.setFont(QFont(QFontDatabase.applicationFontFamilies(id1)))
        # self.logBoxDownload_5.setFont(QFont(QFontDatabase.applicationFontFamilies(id1)))

        self.logBoxDownload_5.setFontPointSize(13.0)

        self.logBoxDownload_5.setText(
            '«Добавить оригинал»:\n 1) Скачать текст оригинала с сайта\n (binary_orig_from_site.txt)\n '
            '2) Перейти во вкладку «Добавить оригинал»\n 3) Выбрать «Файл оригинала с сайта»\n '
            '(binary_orig_from_site.txt)\n '
            '4) Выбрать «Новый файл оригинала»\n 5) Добавить комментарий\n 6) Нажать кнопку «Начать»\n\n'

            "Таблица в «Добавить оригинал»:\n"
            "Нужно найти наиболее похожие строки в столбцах и сопоставить их.\n\n"
            "«Заменить»:\n"
            "Заменяет целую строку или её фрагмент во всех главах.")
        # Initialize progress bars
        self.progress_bars = [
            self.progressBarRefresh
        ]

        for progress_bar in self.progress_bars:
            progress_bar.setMaximum(100)
            progress_bar.setMinimum(0)
            progress_bar.setValue(0)

        # Initialize start buttons
        self.lineNumber.setText('1')
        self.sleep_times = [1, 0.1, 0.5]
        # Connect signals and slots
        self.login.setPlaceholderText("login")
        self.password.setPlaceholderText("password")
        self.urlBook.setPlaceholderText("http://notabenoid.org/book/12345/6789")
        self.tabWidget.setCurrentIndex(0)
        self.fileNameOld.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.fileNameNew.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.comment.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.lineNumber.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.progressBarRefresh.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.progressBarDownload.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.radioButton_replace.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.logBoxReplace.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.replacement_text.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.replace_text_orig.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.replacement_text_n.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.replace_text_orig_n.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.lineEdit_repl.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.url_main_text.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.radioButton.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.radioButton_insert.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.logBoxDownload_5.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 10))
        self.actionRestart.triggered.connect(restart)
        self.actionnotabenoid_org.triggered.connect(menu_site)
        self.actionQuit.triggered.connect(self.close)
        self.btnBrowseOld.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.btnBrowseNew.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.btnStartAdd.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 13))
        self.btnStartRefresh.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 13))
        self.btnStartDownload.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 13))
        self.btnStartReplace.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 13))
        self.btnBrowseTrans.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 13))
        self.btnStartTrans.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 13))
        self.fileNameTrans.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 13))
        self.logBoxTrans.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 13))
        self.refreshText.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 13))
        self.lineEditSave.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 13))
        self.btnBrowseSave.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 13))
        self.loginText.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.passwordText.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.urlBookText.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.comboBox.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.comboBox_replace.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.logBox.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.tabWidget.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.login.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.password.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.urlBook.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 12))
        self.menubar.setFont(QFont(QFontDatabase.applicationFontFamilies(id1), 11))
        self.lineNumber.setGeometry(QtCore.QRect(140, 17, 61, 20))
        self.logBox.clicked.connect(self.check_log_box)

        self.password.textEdited.connect(self.save_pass)
        self.login.textEdited.connect(self.save_login)

        self.comboBox.currentIndexChanged.connect(self.check_radio)
        self.tabWidget.currentChanged.connect(self.tab_widget3)
        self.init_signal_slot()
        self.file_signal()
        self.logBoxAdd.clear()
        self.menuFile.setStyleSheet("selection-color: rgb(85, 170, 255);")
        self.menuHelp.setStyleSheet("selection-color: rgb(85, 170, 255);")

        self.btnStartDownload.setStyleSheet("QPushButton::disabled""{""background-color: rgb(22, 23, 24);""}")
        self.btnStartAdd.setStyleSheet("QPushButton::disabled""{""background-color: rgb(22, 23, 24);""}")
        self.btnStartRefresh.setStyleSheet("QPushButton::disabled""{""background-color: rgb(22, 23, 24);""}")
        self.btnStartReplace.setStyleSheet("QPushButton::disabled""{""background-color: rgb(22, 23, 24);""}")
        self.logBoxAdd.setFontPointSize(15.0)
        self.logBoxRefresh.setFontPointSize(15.0)
        self.logBoxDownload.setFontPointSize(15.0)

        self.login.setStyleSheet("QLineEdit::active""{""background-color: rgb(23, 23, 23);""}" "QLineEdit::disabled""{"
                                 "background-color: rgb(34, 35, 36);""}")
        self.password.setStyleSheet(
            "QLineEdit::active""{""background-color: rgb(23, 23, 23);""}" "QLineEdit::disabled""{""background-color: "
            "rgb(34, 35, 36);""}")
        self.urlBook.setStyleSheet(
            "QLineEdit::active""{""background-color: rgb(23, 23, 23);""}" "QLineEdit::disabled""{""background-color: "
            "rgb(34, 35, 36);""}")
        p = self.palette()
        p.setColor(QPalette.ColorRole.Highlight, QColor(34, 35, 36))
        self.loginText.setPalette(p)
        self.passwordText.setPalette(p)
        self.urlBookText.setPalette(p)
        self.refreshText.setPalette(p)
        b = self.palette()
        b.setColor(QPalette.ColorRole.AlternateBase, QColor(234, 35, 36))

        # self.logBox.setStyleSheet("QCheckBox::indicator:checked""{""color: rgb(222, 73, 74);""}"
        # "QCheckBox::indicator:unchecked""{""background-color: rgb(72, 73, 74);""}")
        self.menubar.setStyleSheet("background-color: rgb(56, 57, 58);")

    def save_login(self):
        if self.radioButton.isChecked():
            with open("./lib/login", "w", encoding='utf-8') as f2:
                f2.write(self.login.text())

    def save_pass(self):
        if self.radioButton.isChecked():
            with open("./lib/pass", "w", encoding='utf-8') as f2:
                f2.write(self.password.text())

    def open_login(self):
        if os.path.isfile("./lib/login"):
            with open("./lib/login", "r", encoding='utf-8') as f2:
                decoded_text = f2.read()
                t = str(decoded_text).strip()
                self.login.setText(t)

    def open_pass(self):
        if os.path.isfile("./lib/pass"):
            with open("./lib/pass", "r", encoding='utf-8') as f2:
                decoded_text = f2.read()
                t = str(decoded_text).strip()
                self.password.setText(t)

    def tab_widget3(self):
        if self.tabWidget.currentIndex() == 3:
            self.urlBook.setVisible(False)

        else:
            self.urlBook.setVisible(True)

    def check_radio(self):
        if self.comboBox.currentIndex() == 0:
            self.radioButton_insert.setVisible(False)
            self.radioButton_insert.setDisabled(True)
        else:
            self.radioButton_insert.setVisible(True)
            self.radioButton_insert.setEnabled(True)

    def check_log_box(self):
        self.login.setEnabled(not self.logBox.isChecked())
        self.password.setEnabled(not self.logBox.isChecked())

        self.urlBook.setEnabled(not self.logBox.isChecked())

        self.btnStartRefresh.setDisabled(self.logBox.isChecked())
        self.btnStartDownload.setDisabled(self.logBox.isChecked())
        self.btnStartReplace.setDisabled(self.logBox.isChecked())
        self.btnStartTrans.setDisabled(self.logBox.isChecked())

        self.btnStartAdd.setDisabled(False)

    def file_old_button(self):
        global file_name_old
        file = QtWidgets.QFileDialog.getOpenFileName(self, "Select file")
        if file[0] != '':
            self.fileNameOld.setText(file[0])
            file_name_old = file[0]

    def file_new_button(self):
        global file_name_new
        file = QtWidgets.QFileDialog.getOpenFileName(self, "Select file")
        if file[0] != '':
            file_name_new = file[0]
            self.fileNameNew.setText(file[0])

    def file_add_trans(self):
        global file_name_trans
        file = QtWidgets.QFileDialog.getOpenFileName(self, "Select file")

        if file[0] != '':
            file_name_trans = file[0]
            self.fileNameTrans.setText(file[0])

    def file_save(self):
        global file_name_save
        file = QtWidgets.QFileDialog.getSaveFileName(self, "Save file")

        if file[0] != '':
            file_name_save = file[0]
            self.lineEditSave.setText(file[0])

    def file_signal(self):
        self.btnBrowseOld.clicked.connect(self.file_old_button)
        self.btnBrowseNew.clicked.connect(self.file_new_button)
        self.btnBrowseTrans.clicked.connect(self.file_add_trans)
        self.btnBrowseSave.clicked.connect(self.file_save)

    def init_signal_slot(self):
        self.btnStartAdd.clicked.connect(self.check_tab_widget)
        self.btnStartRefresh.clicked.connect(self.check_tab_widget)
        self.btnStartDownload.clicked.connect(self.check_tab_widget)
        self.btnStartReplace.clicked.connect(self.check_tab_widget)
        self.btnStartTrans.clicked.connect(self.check_tab_widget)

    def check_tab_widget(self):
        global check_tab
        global line_number
        global combo_box_index
        global word_text_orig
        global word_replacement
        global url_book_main
        global insert_radio
        global entire_radio
        global file_name_save
        global file_name_trans
        global file_name_new
        global file_name_old
        if self.tabWidget.currentIndex() == 0:
            check_tab = 0
            self.logBoxAdd.clear()
            file_name_new = self.fileNameNew.text()
            file_name_old = self.fileNameOld.text()

            self.start_task()
        elif self.tabWidget.currentIndex() == 1:
            check_tab = 1
            self.logBoxRefresh.clear()

            line_number = self.lineNumber.text()
            self.start_task()
        elif self.tabWidget.currentIndex() == 2:
            check_tab = 2
            self.logBoxDownload.clear()
            insert_radio = self.radioButton_insert.isChecked()
            combo_box_index = self.comboBox.currentIndex()
            file_name_save = self.lineEditSave.text()
            self.start_task()
        elif self.tabWidget.currentIndex() == 3:
            check_tab = 3
            self.logBoxReplace.clear()
            url_book_main = self.url_main_text.text()
            if url_book_main[-1] == '/':
                url_book_main = url_book_main[:-1]
            word_text_orig = self.replace_text_orig.toPlainText()
            entire_radio = self.radioButton_replace.isChecked()
            word_replacement = self.replacement_text.toPlainText()

            self.start_task()
        elif self.tabWidget.currentIndex() == 4:
            check_tab = 4
            file_name_trans = self.fileNameTrans.text()
            self.logBoxTrans.clear()
            self.start_task()

    # Update status in the list widget
    def update_status_add(self, text):
        log_write(text)
        if check_tab == 0:
            self.logBoxAdd.append(text)
        elif check_tab == 1:
            self.logBoxRefresh.append(text)
        elif check_tab == 2:
            self.logBoxDownload.append(text)
        elif check_tab == 3:
            self.logBoxReplace.append(text)
        elif check_tab == 4:
            self.logBoxTrans.append(text)

    # Update progress in the corresponding progress bar
    def update_progress_add(self, value):
        if check_tab == 0:
            ...
        elif check_tab == 1:
            self.progressBarRefresh.setValue(value)
        elif check_tab == 2:
            self.progressBarDownload.setValue(value)

    # Toggle the state of the start button based on the task state
    def toggle_button(self, enable=True):
        self.btnStartAdd.setDisabled(not enable)
        if not log_box:
            self.btnStartRefresh.setDisabled(not enable)
            self.btnStartDownload.setDisabled(not enable)
            self.btnStartReplace.setDisabled(not enable)
            self.btnStartTrans.setDisabled(not enable)
        self.logBox.setDisabled(not enable)

    def take_text(self):
        global url_book
        global login_text
        global password_text
        global log_box
        global comment_text
        if self.comment.text() != '':
            comment_text = self.comment.text()
        else:
            comment_text = ' '
        log_box = self.logBox.isChecked()
        url_book = self.urlBook.text()
        login_text = self.login.text()
        password_text = self.password.text()

    def redlines_files_old(self):
        try:
            global f1_data
            global f2_data
            f1_data = []
            f2_data = []
            if file_name_old != ' ':
                with open(file_name_old, "r", encoding="utf-8", errors="strict") as f1:
                    for i in f1:
                        f1_data_t = i.strip()
                        f1_data.append(f1_data_t)

            if file_name_new != ' ':
                with open(file_name_new, "r", encoding="utf-8", errors="strict") as f2:
                    for i in f2:
                        f2_data_t = i.strip()
                        f2_data.append(f2_data_t)

        except UnicodeError:
            self.update_status_add('UnicodeError, please recode the files to utf-8')
            return 'error'

    # Method to start a task
    def start_task(self):
        sleep_time = 0.1
        global error
        error = False

        if check_tab == 0:
            check_error = self.redlines_files_old()
            if check_error == 'error':
                return

        if not self.logBox.isChecked():
            self.take_text()
        else:
            global log_box
            log_box = True

        # Create a TaskThread instance for the selected task
        thread = TaskThread(sleep_time=sleep_time)

        # Connect signals and slots for the task
        global time_start
        time_start = time.time()
        self.update_status_add(str(datetime.datetime.now())[:19])

        thread.started.connect(self.update_status_add)
        thread.started.connect(lambda: self.toggle_button(enable=False))
        thread.progress_value.connect(lambda value: self.update_progress_add(value))
        thread.dialog.connect(dialog_write)
        thread.progress_text.connect(self.update_status_add)
        thread.finished.connect(self.update_status_add)
        thread.finished.connect(lambda: self.toggle_button(enable=True))

        # Store the thread in the dictionary and start it
        self.threads = thread
        thread.start()


def dialog_write(q):
    if q:
        Table()


def log_write(text):
    try:
        with open('notenaboid_log.txt', "a", encoding="utf-8") as f1:
            f1.write(text.rstrip() + '\n')
    except Exception:
        ...


def last_page_replace(url_id_book):
    page = session.get(url_id_book, headers=headers)
    soup = BeautifulSoup(page.text, "html.parser")
    number_chapter = soup.find_all('ul', class_='selectable')
    np = []
    for i in number_chapter:
        np = (i.find_all('a'))
    if len(np) > 0:
        return int(np[-1].get_text())
    else:
        return 1


def get_all_links(url_all):
    num_last = last_page_replace(url_all)
    links = []

    for i in range(num_last):
        links.append(url_all + '?Orig_page=' + str(i + 1))
    return links


def replace_site_text(id_line_t, id_str_original, id_book, str_repl):
    data1 = {
        'Translation[body]:': str_repl,
        'ajax': '1',
    }

    result = session.post(url_book_main + '/' + id_book + '/' + id_str_original + '/translate?tr_id=' + id_line_t,
                          headers=headers,
                          data=data1, verify=False)
    if result.status_code == requests.codes.ok:
        return '200'
    else:
        return 'error'


def id_books():
    try:
        temp_d = []
        temp_n = []
        page = session.get(url_book_main, headers=headers)

        while page.status_code != 200:
            page = session.get(url_book_main, headers=headers)
        soup = BeautifulSoup(page.text, "html.parser")
        # add title
        number_chapter = soup.find_all('tbody')[0].find_all('tr')

        for i_nc in number_chapter:
            temp_d.append(i_nc.get('data-id'))
        name_chapter = soup.find_all('tbody')[0].find_all('td', class_='t')
        for i_n in name_chapter:
            temp_n.append(i_n.text)

        return temp_d, temp_n
    except Exception:
        return 'error', 'error'


def restart():
    os.execl(executable, os.path.abspath(__file__), *argv)


def menu_site():
    webbrowser.open("http://notabenoid.org")


def add_str(id_hash, str_body):
    data1 = {
        'Orig[ord]': id_hash,
        'Orig[body]': str_body,
        'ajax': '1',
    }
    result = session.post(url_book + '/' + "0" + '/edit', headers=headers, data=data1, verify=False)
    if result.status_code == requests.codes.ok:
        return
    else:
        return 'error'


def change_str(id_hash, str_body):
    id_url_str = get_id(id_hash)
    if id_url_str == 'error':
        return 'error'
    data1 = {
        'Orig[ord]': id_hash,
        'Orig[body]': str_body,
        'ajax': '1',
    }

    result = session.post(url_book + '/' + id_url_str + '/edit', headers=headers, data=data1, verify=False)
    if result.status_code == requests.codes.ok:
        return
    else:
        return 'error'


def delete_str(id_hash):
    id_url_str = get_id(id_hash)
    if id_url_str == 'error':
        return 'error'
    result = session.post(url_book + '/' + id_url_str + '/remove', headers=headers, verify=False)
    if result.status_code == requests.codes.ok:
        return
    else:
        return 'error'


def get_id(id_hash):
    try:
        page = math.ceil(id_hash / 50)
        url_parce = url_book + '?Orig_page=' + str(page)
        list_ids = create_list_ids(url_parce)
        num_str = math.floor(id_hash - 50 * (page - 1))

        return list_ids[num_str - 1]
    except Exception:
        return 'error'


def last_page():
    page = session.get(url_book, headers=headers)

    while page.status_code != 200:
        page = session.get(url_book, headers=headers)
    soup = BeautifulSoup(page.text, "html.parser")
    number_chapter = soup.find_all('ul', class_='selectable')
    np = []
    for i in number_chapter:
        np = (i.find_all('a'))
    if len(np) > 0:
        return np[-1].get_text()
    else:
        return 1


def create_list_ids(url_parce):
    page = session.get(url_parce, headers=headers)
    while page.status_code != 200:
        page = session.get(url_parce, headers=headers)
    soup = BeautifulSoup(page.text, "html.parser")
    number_chapter_id = []
    # add title
    number_chapter = soup.find_all('tr')
    for i_nc in number_chapter:
        number_chapter_id.append(i_nc.get('id'))

    number_chapter_id.remove(None)
    number_chapter_id_str = []
    for i_nc_id in number_chapter_id:
        temp_str = str(i_nc_id)
        number_chapter_id_str.append(temp_str.replace("o", ""))
    if len(number_chapter_id_str) > 0:
        return number_chapter_id_str


# Application entry point
if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    freeze_support()
    # Create and show the main window
    window = MainWindow()
    window.show()

    # Start the application event loop
    sys.exit(app.exec())
