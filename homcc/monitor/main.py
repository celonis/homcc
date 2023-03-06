#!/usr/bin/env python3
"""
homcc monitor
"""
import sys
from typing import List

from PySide2 import QtCore, QtWidgets
from PySide2.QtWidgets import QApplication, QMainWindow, QPushButton
from watchdog.observers import Observer

from homcc.common.statefile import StateFile
from homcc.monitor.event_handler import StateFileEventHandler


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
        self.table_widget.setMinimumSize(520, 200)

        self.row_counters = {}  # to store time data
        self.elapsed_time_timer = QtCore.QTimer(self)
        self.elapsed_time_timer.timeout.connect(self.update_time)
        self.elapsed_time_timer.start(1000)  # updates every second

        self.add_row_timer = QtCore.QTimer(self)
        self.add_row_timer.timeout.connect(self.update_compilation_table_data)
        self.add_row_timer.start(1000)  # updates every second

        self.button = QPushButton("Toggle Mode", self)
        self.button.clicked.connect(self.toggle_mode)
        self.button.setGeometry(405, 0, 100, 22)

        self.table_widget.setStyleSheet("QTableWidget { background-color: white; color: black; }")

        self.show()

    def toggle_mode(self):
        if self.table_widget.styleSheet() == "QTableWidget { background-color: white; color: black; }":
            self.table_widget.setStyleSheet("QTableWidget { background-color: black; color: white; }")
            self.table_widget.update()

        else:
            self.table_widget.setStyleSheet("QTableWidget { background-color: white; color: black; }")
            self.table_widget.update()

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
