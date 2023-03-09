#!/usr/bin/env python3
"""
homcc monitor
"""
import os
import sys
from pathlib import Path
from typing import ClassVar, Dict, List

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
from watchdog.observers import Observer

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from homcc.common.statefile import StateFile  # pylint: disable=wrong-import-position
from homcc.monitor.event_handler import (  # pylint: disable=wrong-import-position
    StateFileEventHandler,
)


class MainWindow(QMainWindow):
    """MainWindow class where table activities are carried out"""

    MIN_TABLE_WIDTH: ClassVar[int] = 438
    MIN_TABLE_HEIGHT: ClassVar[int] = 200
    HEADER_SIZE: ClassVar[int] = 18
    SUB_HEADER_SIZE: ClassVar[int] = 12

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.state_file_event_handler = StateFileEventHandler(
            patterns=["*"], ignore_patterns=None, ignore_directories=False, case_sensitive=True
        )
        self.state_file_observer = Observer()
        self.state_file_observer.schedule(self.state_file_event_handler, str(StateFile.HOMCC_STATE_DIR), recursive=True)

        self.state_file_observer.start()

        self.setWindowTitle("HOMCC Monitor")

        self._create_layout()

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

        self.table_curr_jobs.setRowCount(0)
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
        row_index = self.table_curr_jobs.rowCount()
        self.table_curr_jobs.insertRow(row_index)

        for i, row in enumerate(row_data):
            self.table_curr_jobs.setItem(row_index, i, QtWidgets.QTableWidgetItem(row))

    def update_elapsed_times(self):
        """increments time column by 1 everytime it is called and sets time elapsed column"""

        for key in self.compilation_elapsed_times:
            self.compilation_elapsed_times[key] += 1

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
        layout.addWidget(self._create_curr_jobs_layout())
        layout.addWidget(self._create_summary_layout())
        widget = QtWidgets.QWidget()
        widget.setLayout(layout)
        self.setCentralWidget(widget)

    def _create_curr_jobs_layout(self) -> QtWidgets.QWidget:
        self.table_curr_jobs = self._create_table_widget(["Host", "State", "Source File", "Time Elapsed"])
        curr_jobs_text = self._create_text_widget("Current Jobs", self.HEADER_SIZE)

        curr_jobs_layout = QVBoxLayout()
        # needs to be created to have the same length of the linebreak as on the right side
        top_line_curr_jobs_layout = QHBoxLayout()

        top_line_curr_jobs_layout.addWidget(curr_jobs_text)
        top_line_curr_jobs_widget = QtWidgets.QWidget()
        top_line_curr_jobs_widget.setLayout(top_line_curr_jobs_layout)

        curr_jobs_layout.addWidget(top_line_curr_jobs_widget)
        curr_jobs_layout.addWidget(self.table_curr_jobs)

        curr_jobs_widget = QtWidgets.QWidget()
        curr_jobs_widget.setLayout(curr_jobs_layout)
        return curr_jobs_widget

    def _create_summary_layout(self) -> QtWidgets.QWidget:
        summary_text = self._create_text_widget("Summary", self.HEADER_SIZE)
        files_text = self._create_text_widget("    Files", self.SUB_HEADER_SIZE)
        hosts_text = self._create_text_widget("    Hosts", self.SUB_HEADER_SIZE)

        self.reset = QPushButton("RESET")
        self.table_hosts = self._create_table_widget(["name", "total", "current", "failed"])
        table_files = self._create_table_widget(["Compilation (top 5 max)", "Preprocessing (top 5 max)"])
        self.table_compiled_files = self._create_table_widget(["sec", "file-name"], int((self.MIN_TABLE_WIDTH - 2) / 2))
        self.table_preprocessed_files = self._create_table_widget(
            ["sec", "file-name"], int((self.MIN_TABLE_WIDTH - 2) / 2)
        )
        self.table_compiled_files.setSortingEnabled(True)
        self.table_preprocessed_files.setSortingEnabled(True)
        table_files.insertRow(0)
        table_files.setCellWidget(0, 0, self.table_compiled_files)
        table_files.setCellWidget(0, 1, self.table_preprocessed_files)
        table_files.verticalHeader().setVisible(False)

        summary_layout = QVBoxLayout()
        top_line_summary_layout = QHBoxLayout()
        top_line_summary_layout.addWidget(summary_text)
        top_line_summary_layout.addWidget(self.reset)
        top_line_summary_widget = QtWidgets.QWidget()
        top_line_summary_widget.setLayout(top_line_summary_layout)

        summary_layout.addWidget(top_line_summary_widget)
        summary_layout.addWidget(files_text)
        summary_layout.addWidget(table_files)
        summary_layout.addWidget(hosts_text)
        summary_layout.addWidget(self.table_hosts)

        summary_widget = QtWidgets.QWidget()
        summary_widget.setLayout(summary_layout)
        return summary_widget

    def __del__(self):
        self.state_file_observer.stop()
        self.state_file_observer.join()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    app.exec_()
