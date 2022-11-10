"""Table for currently running compilation jobs"""
from dataclasses import dataclass
from typing import ClassVar, List

from PySide2.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem


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

    def __init__(self, data: List[RowData]):

        self.data = data
        self.table = QTableWidget()
        self.table.setRowCount(len(data))
        self.table.setColumnCount(len(Table.column_headers))
        self.table.setHorizontalHeaderLabels(Table.column_headers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

    def render(self):
        for row in range(len(self.data)):
            for col in range(4):
                self.table.setItem(row, col, QTableWidgetItem(self.data[row][col]))
