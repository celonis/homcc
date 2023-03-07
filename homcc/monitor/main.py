#!/usr/bin/env python3
"""
homcc monitor
"""
import os
import sys
from typing import List

from PySide2 import QtCore, QtWidgets
from PySide2.QtWidgets import QApplication, QMainWindow
from watchdog.observers import Observer

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from homcc.common.statefile import StateFile  # pylint: disable=wrong-import-position
from homcc.monitor.event_handler import (  # pylint: disable=wrong-import-position
    StateFileEventHandler,
)


class MainWindow(QMainWindow):
    """MainWindow class where table activities are carried out"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.state_file_event_handler = StateFileEventHandler(
            patterns=["*"], ignore_patterns=None, ignore_directories=False, case_sensitive=True
        )
        file_observer = Observer()
        file_observer.schedule(self.state_file_event_handler, str(StateFile.HOMCC_STATE_DIR), recursive=True)

        file_observer.start()

        column_headers = ["Host", "State", "Source File", "Time Elapsed"]

        self.table_widget = QtWidgets.QTableWidget()
        self.table_widget.setColumnCount(4)
        self.setCentralWidget(self.table_widget)
        self.table_widget.setHorizontalHeaderLabels(column_headers)
        self.table_widget.setMinimumSize(438, 200)

        # trigger these update methods every second
        def update():
            self.update_time()
            self.update_compilation_table_data()

        self.row_counters = {}  # to store time data
        self.update_timer = QtCore.QTimer(self)
        self.update_timer.timeout.connect(update)
        self.update_timer.start(1000)  # updates every second

        self.show()

    def update_compilation_table_data(self):
        """updates row data on table every second"""
        if self.state_file_event_handler.table_info:
            for data in self.state_file_event_handler.table_info:
                row = [data.hostname, data.phase, data.file_path, "0"]
                self.add_row_to_table(row)
            self.state_file_event_handler.table_info.clear()

    def add_row_to_table(self, row: List):
        """sets the table widget rows to row data"""

        row_index = self.table_widget.rowCount()
        self.table_widget.insertRow(row_index)
        for i, item in enumerate(row):
            self.table_widget.setItem(row_index, i, QtWidgets.QTableWidgetItem(item))
        self.row_counters[row_index] = 0

    def update_time(self):
        """increments time column by 1 everytime it is called and sets time elapsed column"""

        for row_index in range(self.table_widget.rowCount()):
            self.row_counters[row_index] += 1
            count_item = QtWidgets.QTableWidgetItem(str(self.row_counters[row_index]) + "s")
            self.table_widget.setItem(row_index, 3, count_item)

    def __del__(self):
        self.my_observer.stop()
        self.my_observer.join()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    app.exec_()
