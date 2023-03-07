#!/usr/bin/env python3
"""
homcc monitor
"""
import os
import sys
from typing import List

from PySide2 import QtCore, QtWidgets
from PySide2.QtWidgets import QApplication, QMainWindow, QPushButton
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

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from homcc.common.statefile import StateFile  # pylint: disable=wrong-import-position
from homcc.monitor.event_handler import (  # pylint: disable=wrong-import-position
    StateFileEventHandler,
)


class MainWindow(QMainWindow):
    """MainWindow class where table activities are carried out"""

    MIN_TABLE_WIDTH: int = 438
    MIN_TABLE_HEIGHT: int = 200
    HEADER_SIZE: int = 18
    SUB_HEADER_SIZE: int = 12

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.state_file_event_handler = StateFileEventHandler(
            patterns=["*"], ignore_patterns=None, ignore_directories=False, case_sensitive=True
        )
        file_observer = Observer()
        file_observer.schedule(self.state_file_event_handler, str(StateFile.HOMCC_STATE_DIR), recursive=True)

        file_observer.start()

        self.setWindowTitle('HOMCC Monitor')

        self._create_layout()

        # trigger these update methods every second
        def update():
            self.update_time()
            self.update_compilation_table_data()

        self.row_counters = {}  # to store time data
        self.update_timer = QtCore.QTimer(self)
        self.update_timer.timeout.connect(update)
        self.update_timer.start(1000)  # updates every second

        self.show()

    @staticmethod
    def _create_text_widget(text: str, font_size: int) -> QtWidgets.QWidget:
        text_widget = QLabel(text)
        font = text_widget.font()
        font.setPointSize(font_size)
        text_widget.setFont(font)
        text_widget.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        return text_widget

    @staticmethod
    def _create_table_widget(
        col_header: list[str], width: int = MIN_TABLE_WIDTH, height: int = MIN_TABLE_HEIGHT
    ) -> QtWidgets.QTableWidget:
        table = QtWidgets.QTableWidget()
        table.setColumnCount(len(col_header))
        table.setHorizontalHeaderLabels(col_header)
        table.setMinimumSize(width, height)
        table_files_header = table.horizontalHeader()
        table_files_header.setMinimumSectionSize(int((width - 2) / len(col_header)))
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
        table_files = self._create_table_widget(['Compilation (top 5 max)', 'Preprocessing (top 5 max)'])
        self.table_compiled_files = self._create_table_widget(['sec', 'file-name'], int((self.MIN_TABLE_WIDTH - 3) / 2))
        self.table_preprocessed_files = self._create_table_widget(
            ['sec', 'file-name'], int((self.MIN_TABLE_WIDTH - 2) / 2)
        )
        self.table_compiled_files.setSortingEnabled(True)
        self.table_preprocessed_files.setSortingEnabled(True)
        table_files.insertRow(0)
        table_files.setCellWidget(0, 0, self.table_compiled_files)
        table_files.setCellWidget(0, 1, self.table_preprocessed_files)
        table_files.verticalHeader().setVisible(False)

        right_layout_1 = QVBoxLayout()
        right_layout_2 = QHBoxLayout()
        right_layout_2.addWidget(summary)
        right_layout_2.addWidget(self.reset)
        top_right_line = QtWidgets.QWidget()
        top_right_line.setLayout(right_layout_2)

        right_layout_1.addWidget(top_right_line)
        right_layout_1.addWidget(files)
        right_layout_1.addWidget(table_files)
        right_layout_1.addWidget(hosts)
        right_layout_1.addWidget(self.table_hosts)

        right_side = QtWidgets.QWidget()
        right_side.setLayout(right_layout_1)
        return right_side

    def update_compilation_table_data(self):
        """updates row data on table every second"""
        if self.state_file_event_handler.table_info:
            for data in self.state_file_event_handler.table_info:
                row = [data.hostname, data.phase, data.file_path, "0"]
                self.add_row_to_table(row)
            self.state_file_event_handler.table_info.clear()

            self.table_compiled_files.setRowCount(0)
            self.table_preprocessed_files.setRowCount(0)
            for file_stat in self.state_file_event_handler.summary.file_stats.values():
                compilation_time = file_stat.get_compilation_time()
                if compilation_time >= 0:
                    row = [compilation_time, file_stat.filepath]
                    self.add_row(self.table_compiled_files, row, True)
                preprocessing_time = file_stat.get_preprocessing_time()
                if preprocessing_time >= 0:
                    row = [preprocessing_time, file_stat.filepath]
                    self.add_row(self.table_preprocessed_files, row, True)

    @staticmethod
    def add_row(table: QtWidgets.QTableWidget, row: List[str], is_file_table: bool = False):
        """sets the table widget rows to row data"""

        row_index = table.rowCount()
        table.insertRow(row_index)
        if is_file_table:
            item = QtWidgets.QTableWidgetItem()
            item.setData(0, row[0])
            table.setItem(row_index, 0, item)
            table.setItem(row_index, 1, QtWidgets.QTableWidgetItem(row[1]))
        else:
            for i, item in enumerate(row):
                table.setItem(row_index, i, QtWidgets.QTableWidgetItem(item))

    def add_row_to_table(self, row):
        """sets the table widget rows to row data"""

        row_index = self.table_curr_jobs.rowCount()
        self.table_curr_jobs.insertRow(row_index)
        for i, item in enumerate(row):
            self.table_curr_jobs.setItem(row_index, i, QtWidgets.QTableWidgetItem(item))
        self.row_counters[row_index] = 0

    def update_time(self):
        """increments time column by 1 everytime it is called and sets time elapsed column"""

        for row_index in range(self.table_curr_jobs.rowCount()):
            self.row_counters[row_index] += 1
            count_item = QtWidgets.QTableWidgetItem(str(self.row_counters[row_index]) + 's')
            self.table_curr_jobs.setItem(row_index, 3, count_item)

    #def __del__(self):
    #    self.my_observer.stop()
    #    self.my_observer.join()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    app.exec_()
