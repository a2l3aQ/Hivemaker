import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication
from ui.main_window import MainWindow

if __name__ == "__main__":
    qapp = QApplication(sys.argv)
    window = MainWindow(game_url="http://localhost:8001")
    window.show()
    sys.exit(qapp.exec_())