from PySide2.QtWidgets import QTableWidgetItem, QTableWidget, QHeaderView, QApplication
from data import data


class Table:

    table = QTableWidget()
    table.setRowCount(len(data[0]))
    table.setColumnCount(4)
    table.setHorizontalHeaderLabels(["Host", "State", "Source File", "Time Elapsed"])
    table.verticalHeader().setVisible(0)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

    for i, host in enumerate(data[0]):
        item_host = QTableWidgetItem(host)
        table.setItem(i, 0, item_host)

    for i, state in enumerate(data[1]):
        item_state = QTableWidgetItem(state)
        table.setItem(i, 1, item_state)

    for i, sourceFile in enumerate(data[2]):
        item_source_file = QTableWidgetItem(sourceFile)
        table.setItem(i, 2, item_source_file)

    for i, timeElapsed in enumerate(data[3]):
        item_time_elapsed = QTableWidgetItem(timeElapsed)
        table.setItem(i, 3, item_time_elapsed)
