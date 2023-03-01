#!/usr/bin/env python3
"""
homcc monitor
"""
import sys
import time
from pathlib import Path
from datetime import datetime
from PySide2 import QtCore, QtWidgets
from PySide2.QtCore import Qt
from PySide2.QtWidgets import QApplication, QMainWindow, QLabel
from PySide2.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout
from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer
from homcc.common.statefile import StateFile


table_info = []


def on_created(event):  # tracks the creation of a state file and reads its data into table_info
    data_list = []

    try:
        file = open(event.src_path, "rb")
    except FileNotFoundError:
        return

    file_bytes = file.read()
    if len(file_bytes) == 0:
        return

    state: StateFile = StateFile.from_bytes(file_bytes)

    data_list.append(event.src_path)
    data_list.append(state.hostname.decode("utf-8"))
    data_list.append(StateFile.ClientPhase(state.phase).name)
    data_list.append(state.source_base_filename)

    table_info.append(data_list)

    print(" ")
    print("These are for tests")
    print(state.hostname.decode("utf-8"))
    print(StateFile.ClientPhase(state.phase).name)
    print(state.source_base_filename)
    print("--------------------------------")

    print(f"{datetime.now().strftime('%d/%m/%Y %H:%M:%S')} - {event.src_path} has been created!")
    # file.close


def on_deleted(event):  # tracks deletion of a state file - not actively used
    for e in table_info:
        if e[0] == event.src_path:
            table_info.remove(e)

    print(f"{datetime.now().strftime('%d/%m/%Y %H:%M:%S')} - {event.src_path} has been deleted!")


def on_modified(event):  # tracks modification of a state file - not actively used
    print(f"{datetime.now().strftime('%d/%m/%Y %H:%M:%S')} - {event.src_path} has been modified!")


def on_moved(event):  # tracks path movement of a state file - not actively used
    print(f"{datetime.now().strftime('%d/%m/%Y %H:%M:%S')} - {event.src_path} to {event.dest_path} has been moved!")


# thread that sleeps for one second and emits row_ready signal to alert QMainWindow when new data arrives
class WorkerThread(QtCore.QThread):
    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        while True:
            time.sleep(1)
            if len(table_info) != 0:
                for data in table_info:
                    row = [data[1], data[2], data[3], "0"]
                    self.row_ready.emit(row)
                table_info.clear()

    row_ready = QtCore.Signal(list)


# MainWindow class where table activities are carried out
class MainWindow(QMainWindow):
    def __init__(self, *args, **kwargs):
        super(MainWindow, self).__init__(*args, **kwargs)

        patterns = ["*"]
        ignore_patterns = None
        ignore_directories = False
        case_sensitive = True
        my_event_handler = PatternMatchingEventHandler(patterns, ignore_patterns, ignore_directories, case_sensitive)

        my_event_handler.on_created = on_created
        my_event_handler.on_deleted = on_deleted
        my_event_handler.on_modified = on_modified
        my_event_handler.on_moved = on_moved

        path = Path.home() / ".distcc" / "state"
        go_recursively = True
        self.my_observer = Observer()
        self.my_observer.schedule(my_event_handler, str(path), recursive=go_recursively)

        self.my_observer.start()

        self.setWindowTitle("HOMCC")

        self.data = []

        self.__create_layout()

        self.row_counters = {}  # to store time data
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_time)
        self.timer.start(1000)  # updates every second

        self.worker_thread = WorkerThread(self)
        self.worker_thread.row_ready.connect(self.add_row_to_table)  # connects to add_row_to_table when signal is ready
        self.worker_thread.start()

    def __create_text_widget(self, text, font_size):
        text_widget = QLabel(text)
        font = text_widget.font()
        font.setPointSize(font_size)
        text_widget.setFont(font)
        text_widget.setAlignment(Qt.AlignLeft|Qt.AlignTop)
        return text_widget

    def __create_table_widget(self, col_header):
        table = QtWidgets.QTableWidget()
        table.setColumnCount(len(col_header))
        table.setHorizontalHeaderLabels(col_header)
        table.setMinimumSize(438, 200)
        table_files_header = table.horizontalHeader()
        table_files_header.setMinimumSectionSize(436/len(col_header))
        return table

    def __create_layout(self):
        layout = QHBoxLayout()
        layout.addWidget(self.__create_left_layout())
        layout.addWidget(self.__create_right_layout())
        widget = QtWidgets.QWidget()
        widget.setLayout(layout)
        self.setCentralWidget(widget)

    def __create_left_layout(self):
        self.table_curr_jobs = self.__create_table_widget(['Host', 'State', 'Source File', 'Time Elapsed'])
        curr_jobs = self.__create_text_widget('Current Jobs', 18)

        left_layout_1 = QVBoxLayout()
        left_layout_2 = QHBoxLayout()

        left_layout_2.addWidget(curr_jobs)
        left_top_line = QtWidgets.QWidget()
        left_top_line.setLayout(left_layout_2)

        left_layout_1.addWidget(left_top_line)
        left_layout_1.addWidget(self.table_curr_jobs)

        left_side = QtWidgets.QWidget()
        left_side.setLayout(left_layout_1)
        return left_side

    def __create_right_layout(self):
        summary = self.__create_text_widget('Summary', 12)
        files = self.__create_text_widget('    Files', 12)
        hosts = self.__create_text_widget('    Hosts', 12)

        self.reset = QPushButton('RESET')
        self.table_hosts = self.__create_table_widget(['name', 'total', 'current', 'failed'])
        self.table_files = self.__create_table_widget(['Compilation (top 5 max)', 'Preprocessing (top 5 max)'])

        right_layout_1 = QVBoxLayout()
        right_layout_2 = QHBoxLayout()
        right_layout_2.addWidget(summary)
        right_layout_2.addWidget(self.reset)
        top_right_line = QtWidgets.QWidget()
        top_right_line.setLayout(right_layout_2)

        right_layout_1.addWidget(top_right_line)
        right_layout_1.addWidget(files)
        right_layout_1.addWidget(self.table_files)
        right_layout_1.addWidget(hosts)
        right_layout_1.addWidget(self.table_hosts)

        right_side = QtWidgets.QWidget()
        right_side.setLayout(right_layout_1)
        return right_side

    def add_row_to_table(self, row):  # sets the table widget rows to row data
        row_index = self.table_curr_jobs.rowCount()
        self.table_curr_jobs.insertRow(row_index)
        for i, item in enumerate(row):
            self.table_curr_jobs.setItem(row_index, i, QtWidgets.QTableWidgetItem(item))
        self.row_counters[row_index] = 0
        self.table_curr_jobs.verticalScrollBar().setValue(self.table_curr_jobs.verticalScrollBar().maximum())

    def update_time(self):  # increments time column by 1 everytime it is called and sets time elapsed column
        for row_index in range(self.table_curr_jobs.rowCount()):
            self.row_counters[row_index] += 1
            count_item = QtWidgets.QTableWidgetItem(str(self.row_counters[row_index]) + 's')
            self.table_curr_jobs.setItem(row_index, 3, count_item)

    def __del__(self):  # destructor
        self.my_observer.stop()
        self.my_observer.join()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    app.exec_()
