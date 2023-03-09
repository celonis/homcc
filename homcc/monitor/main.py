#!/usr/bin/env python3
"""
homcc monitor
"""
import os
import sys
from pathlib import Path
from typing import Dict, List

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
        self.state_file_observer = Observer()
        self.state_file_observer.schedule(self.state_file_event_handler, str(StateFile.HOMCC_STATE_DIR), recursive=True)

        self.state_file_observer.start()

        column_headers = ["Host", "State", "Source File", "Time Elapsed"]

        self.table_widget = QtWidgets.QTableWidget()
        self.table_widget.setColumnCount(4)
        self.setCentralWidget(self.table_widget)
        self.table_widget.setHorizontalHeaderLabels(column_headers)
        self.table_widget.setMinimumSize(438, 200)

        # trigger these update methods every second
        def update():
            self.update_elapsed_times()
            self.update_compilation_table_data()

        self.compilation_elapsed_times: Dict[Path, int] = {}  # to store time data
        self.update_timer = QtCore.QTimer(self)
        self.update_timer.timeout.connect(update)
        self.update_timer.start(1000)  # updates every second

        self.show()

    def update_compilation_table_data(self):
        """updates the Current Jobs table"""

        self.table_widget.setRowCount(0)
        for key, value in self.state_file_event_handler.table_info.items():
            if key not in self.compilation_elapsed_times:
                self.compilation_elapsed_times[key] = 0
            row = [
                value.hostname,
                value.phase,
                value.filename,
                f"{self.compilation_elapsed_times[key]}s",
            ]
            self.add_row_to_table(row)

    def add_row_to_table(self, row_data: List[str]):
        """sets the table widget rows to row data"""

        # get last row_index
        row_index = self.table_widget.rowCount()
        self.table_widget.insertRow(row_index)

        for i, row in enumerate(row_data):
            self.table_widget.setItem(row_index, i, QtWidgets.QTableWidgetItem(row))

    def update_elapsed_times(self):
        """increments time column by 1 everytime it is called and sets time elapsed column"""

        for key in self.compilation_elapsed_times:
            self.compilation_elapsed_times[key] += 1

    def __del__(self):
        self.state_file_observer.stop()
        self.state_file_observer.join()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    app.exec_()
