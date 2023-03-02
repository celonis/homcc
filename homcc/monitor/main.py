#!/usr/bin/env python3
"""
homcc monitor
"""
import sys
import time
from pathlib import Path

from PySide2 import QtCore, QtWidgets
from PySide2.QtCore import Qt
from PySide2.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
)
from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer

from homcc.monitor.observer import StateFileObserver

""" HOMCC monitor: homccm"""

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
    MIN_TABLE_WIDTH: int = 438
    MIN_TABLE_HEIGHT: int = 200
    HEADER_SIZE: int = 18
    SUB_HEADER_SIZE: int = 12

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
        self.my_observer = Observer()
        self.my_observer.schedule(file_event_handler, str(path), recursive=True)

        self.my_observer.start()

        self.setWindowTitle('HOMCC Monitor')
        self.data = []

        self._create_layout()

        self.row_counters = {}  # to store time data
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_time)
        self.timer.start(1000)  # updates every second

        self.worker_thread = WorkerThread(self)
        self.worker_thread.row_ready.connect(self.add_row_to_table)  # connects to add_row_to_table when signal is ready
        self.worker_thread.start()

    @staticmethod
    def _create_text_widget(text: str, font_size: int) -> QtWidgets.QWidget:
        text_widget = QLabel(text)
        font = text_widget.font()
        font.setPointSize(font_size)
        text_widget.setFont(font)
        text_widget.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        return text_widget

    def _create_table_widget(self, col_header: list[str]) -> QtWidgets.QTableWidget:
        table = QtWidgets.QTableWidget()
        table.setColumnCount(len(col_header))
        table.setHorizontalHeaderLabels(col_header)
        table.setMinimumSize(self.MIN_TABLE_WIDTH, self.MIN_TABLE_HEIGHT)
        table_files_header = table.horizontalHeader()
        table_files_header.setMinimumSectionSize(int((self.MIN_TABLE_WIDTH - 2) / len(col_header)))
        return table

    def _create_layout(self):
        layout = QHBoxLayout()
        layout.addWidget(self._create_left_layout())
        layout.addWidget(self._create_right_layout())
        widget = QtWidgets.QWidget()
        widget.setLayout(layout)
        self.setCentralWidget(widget)

    def _create_left_layout(self) -> QtWidgets.QWidget:
        self.table_curr_jobs = self._create_table_widget(['Host', 'State', 'Source File', 'Time Elapsed'])
        curr_jobs = self._create_text_widget('Current Jobs', self.HEADER_SIZE)

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

    def _create_right_layout(self) -> QtWidgets.QWidget:
        summary = self._create_text_widget('Summary', self.HEADER_SIZE)
        files = self._create_text_widget('    Files', self.SUB_HEADER_SIZE)
        hosts = self._create_text_widget('    Hosts', self.SUB_HEADER_SIZE)

        self.reset = QPushButton('RESET')
        self.table_hosts = self._create_table_widget(['name', 'total', 'current', 'failed'])
        self.table_files = self._create_table_widget(['Compilation (top 5 max)', 'Preprocessing (top 5 max)'])

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

    def add_row_to_table(self, row):
        """sets the table widget rows to row data"""

        row_index = self.table_curr_jobs.rowCount()
        self.table_curr_jobs.insertRow(row_index)
        for i, item in enumerate(row):
            self.table_curr_jobs.setItem(row_index, i, QtWidgets.QTableWidgetItem(item))
        self.row_counters[row_index] = 0
        self.table_curr_jobs.verticalScrollBar().setValue(self.table_curr_jobs.verticalScrollBar().maximum())

    def update_time(self):
        """increments time column by 1 everytime it is called and sets time elapsed column"""

        for row_index in range(self.table_curr_jobs.rowCount()):
            self.row_counters[row_index] += 1
            count_item = QtWidgets.QTableWidgetItem(str(self.row_counters[row_index]) + 's')
            self.table_curr_jobs.setItem(row_index, 3, count_item)

    def __del__(self):
        self.my_observer.stop()
        self.my_observer.join()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    app.exec_()
