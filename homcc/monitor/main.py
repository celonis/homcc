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
    QTableWidget,
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
            self.update_current_jobs_table()
            self.update_elapsed_times()
            self.update_summary_hosts_table()

        self.compilation_elapsed_times: Dict[Path, int] = {}  # to store time data
        self.update_timer = QtCore.QTimer(self)
        self.update_timer.timeout.connect(update)
        self.update_timer.start(1000)  # updates every second

        self.show()

    @staticmethod
    def add_row_to_table(table: QTableWidget, row_data: List[str]):
        """sets the table widget rows to row data"""

        # get last row_index
        row_index = table.rowCount()
        table.insertRow(row_index)

        for i, row in enumerate(row_data):
            table.setItem(row_index, i, QtWidgets.QTableWidgetItem(row))

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
        col_header: List[str], width: int = MIN_TABLE_WIDTH, height: int = MIN_TABLE_HEIGHT
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
        self.table_curr_jobs = self._create_table_widget(["Host", "State", "Source File", "Time Elapsed"])
        curr_jobs = self._create_text_widget("Current Jobs", self.HEADER_SIZE)

        left_layout = QVBoxLayout()
        left_layout_topline = QHBoxLayout()

        left_layout_topline.addWidget(curr_jobs)
        left_top_line = QtWidgets.QWidget()
        left_top_line.setLayout(left_layout_topline)

        left_layout.addWidget(left_top_line)
        left_layout.addWidget(self.table_curr_jobs)

        left_side = QtWidgets.QWidget()
        left_side.setLayout(left_layout)
        return left_side

    def _create_right_layout(self) -> QtWidgets.QWidget:
        summary = self._create_text_widget("Summary", self.HEADER_SIZE)
        files = self._create_text_widget("    Files", self.SUB_HEADER_SIZE)
        hosts = self._create_text_widget("    Hosts", self.SUB_HEADER_SIZE)

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

        right_layout = QVBoxLayout()
        right_layout_file_line = QHBoxLayout()
        right_layout_file_line.addWidget(summary)
        right_layout_file_line.addWidget(self.reset)
        top_right_line = QtWidgets.QWidget()
        top_right_line.setLayout(right_layout_file_line)

        right_layout.addWidget(top_right_line)
        right_layout.addWidget(files)
        right_layout.addWidget(table_files)
        right_layout.addWidget(hosts)
        right_layout.addWidget(self.table_hosts)

        right_side = QtWidgets.QWidget()
        right_side.setLayout(right_layout)
        return right_side

    def update_current_jobs_table(self):
        """updates row data on table every second"""

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
            self.add_row_to_table(self.table_curr_jobs, row)

    def update_summary_hosts_table(self):
        """updates row data on hosts table every second"""

        self.table_hosts.setRowCount(0)
        for host_stat in self.state_file_event_handler.summary.host_stats.values():
            # failed column set to 0 for now
            row = [
                host_stat.name,
                f"{host_stat.total_compilations}",
                f"{host_stat.current_compilations}",
                "0",
            ]
            self.add_row_to_table(self.table_hosts, row)

    def __del__(self):
        self.state_file_observer.stop()
        self.state_file_observer.join()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    app.exec_()
