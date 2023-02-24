#!/usr/bin/env python3
"""
homcc monitor
"""
import sys
from datetime import datetime
import time
from pathlib import Path

from PySide2 import QtCore, QtWidgets
from PySide2.QtWidgets import QApplication, QMainWindow
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

        self.data = []

        column_headers = ["Host", "State", "Source File", "Time Elapsed"]

        self.table_widget = QtWidgets.QTableWidget()
        self.table_widget.setColumnCount(4)
        self.setCentralWidget(self.table_widget)
        self.table_widget.setHorizontalHeaderLabels(column_headers)
        self.table_widget.setMinimumSize(438, 200)
        # self.table_widget.verticalHeader().setVisible(False)

        self.row_counters = {}  # to store time data
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_time)
        self.timer.start(1000)  # updates every second

        self.worker_thread = WorkerThread(self)
        self.worker_thread.row_ready.connect(self.add_row_to_table)  # connects to add_row_to_table when signal is ready
        self.worker_thread.start()

    def add_row_to_table(self, row):  # sets the table widget rows to row data
        row_index = self.table_widget.rowCount()
        self.table_widget.insertRow(row_index)
        for i, item in enumerate(row):
            self.table_widget.setItem(row_index, i, QtWidgets.QTableWidgetItem(item))
        self.row_counters[row_index] = 0
        self.table_widget.verticalScrollBar().setValue(self.table_widget.verticalScrollBar().maximum())

    def update_time(self):  # increments time column by 1 everytime it is called and sets time elapsed column
        for row_index in range(self.table_widget.rowCount()):
            self.row_counters[row_index] += 1
            count_item = QtWidgets.QTableWidgetItem(str(self.row_counters[row_index]) + 's')
            self.table_widget.setItem(row_index, 3, count_item)

    def __del__(self):  # destructor
        self.my_observer.stop()
        self.my_observer.join()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    app.exec_()
