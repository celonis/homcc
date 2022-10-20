import sys
from data import app
from table import Table

if __name__ == "__main__":

    Table.table.setWindowTitle("homcc Monitor")
    Table.table.resize(500, 200)
    Table.table.show()
    sys.exit(app.exec_())
