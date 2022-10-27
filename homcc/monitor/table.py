from dataclasses import dataclass
from typing import ClassVar, List
from PySide2.QtWidgets import QTableWidgetItem, QTableWidget, QHeaderView
from data import data_info


@dataclass
class RowData:
    host: str
    state: str
    source_file: str
    time_elapsed: str


class Table:
    """Table class to abstract over a QTableWidget and provide utility and render methods"""

    column_headers: ClassVar[List[str]] = ["Host", "State", "Source File", "Time Elapsed"]
    """Relevant compilation attributes."""

    data = List[RowData]
    """Data structure of the table."""

    def __init__(self, column_headers, data):

        self.data = data_info
        self.table = QTableWidget()
        self.table.setRowCount(len(data_info))
        self.table.setColumnCount(len(column_headers))
        self.table.setHorizontalHeaderLabels(column_headers)
        self.table.verticalHeader().setVisible(0)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

    def render(self):
        for row in range(len(data_info)):
            for col in range(4):
                self.table.setItem(row, col, QTableWidgetItem(data_info[row][col]))
