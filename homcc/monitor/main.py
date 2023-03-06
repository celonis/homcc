#!/usr/bin/env python3
"""
homcc monitor
"""
import sys
import time
from pathlib import Path

from PySide2 import QtCore, QtWidgets
from PySide2.QtWidgets import QApplication, QMainWindow
from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer
from observer import StateFileObserver

"""HOMCC monitor: homccm"""

__version__: str = "0.0.1"


class WorkerThread(QtCore.QThread):
    """thread that sleeps for one second and emits row_ready signal to alert QMainWindow when new data arrives"""

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        while True:
            time.sleep(1)
            if len(StateFileObserver.table_info) != 0:
                for data in StateFileObserver.table_info:
                    row = [data.state_hostname, data.phase_name, data.source_base_filename, "0"]
                    self.row_ready.emit(row)
                StateFileObserver.table_info.clear()

    row_ready = QtCore.Signal(list)


class MainWindow(QMainWindow):
    """MainWindow class where table activities are carried out"""

    def __init__(self, *args, **kwargs):
        super(MainWindow, self).__init__(*args, **kwargs)

        file_event_handler = PatternMatchingEventHandler(
            patterns=["*"], ignore_patterns=None, ignore_directories=False, case_sensitive=True
        )

        state_file_observer = StateFileObserver(file_event_handler)
        file_event_handler.on_created = state_file_observer.on_created
        file_event_handler.on_deleted = state_file_observer.on_deleted
        file_event_handler.on_modified = state_file_observer.on_modified
        file_event_handler.on_moved = state_file_observer.on_moved

        path = Path.home() / ".distcc" / "state"
        file_observer = Observer()
        file_observer.schedule(file_event_handler, str(path), recursive=True)

        file_observer.start()

        column_headers = ["Host", "State", "Source File", "Time Elapsed"]

        self.table_widget = QtWidgets.QTableWidget()
        self.table_widget.setColumnCount(4)
        self.setCentralWidget(self.table_widget)
        self.table_widget.setHorizontalHeaderLabels(column_headers)
        self.table_widget.setMinimumSize(438, 200)

        self.row_counters = {}  # to store time data
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_time)
        self.timer.start(1000)  # updates every second

        self.worker_thread = WorkerThread(self)
        self.worker_thread.row_ready.connect(self.add_row_to_table)  # connects to add_row_to_table when signal is ready
        self.worker_thread.start()

    def add_row_to_table(self, row):
        """sets the table widget rows to row data"""

        row_index = self.table_widget.rowCount()
        self.table_widget.insertRow(row_index)
        for i, item in enumerate(row):
            self.table_widget.setItem(row_index, i, QtWidgets.QTableWidgetItem(item))
        self.row_counters[row_index] = 0
        self.table_widget.verticalScrollBar().setValue(self.table_widget.verticalScrollBar().maximum())

    def update_time(self):
        """increments time column by 1 everytime it is called and sets time elapsed column"""

        for row_index in range(self.table_widget.rowCount()):
            self.row_counters[row_index] += 1
            count_item = QtWidgets.QTableWidgetItem(str(self.row_counters[row_index]) + 's')
            self.table_widget.setItem(row_index, 3, count_item)

    def __del__(self):
        self.my_observer.stop()
        self.my_observer.join()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    app.exec_()
