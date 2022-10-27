#!/usr/bin/env python3
"""
homcc monitor
"""
import sys
from PySide2.QtWidgets import QApplication
from table import Table


def main():

    app: QApplication = QApplication()
    table: Table = Table(Table.column_headers, Table.data)
    table.table.setWindowTitle("homcc Monitor")
    table.table.resize(500, 200)
    table.render()
    table.table.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
