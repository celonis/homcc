#!/usr/bin/env python3
"""
homcc monitor
"""
import sys
from PySide2.QtWidgets import QApplication
# type: ignore
from table import Table

data_info = [
        ("foo", "Sending", "foo.cpp", "13sec"),
        ("bar", "Compiling", "bar.cpp", "4sec"),
]


def main():

    app: QApplication = QApplication()
    table: Table = Table(data_info)
    # table.table.setWindowTitle("homcc Monitor")
    table.table.resize(500, 200)
    table.render()
    table.table.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
