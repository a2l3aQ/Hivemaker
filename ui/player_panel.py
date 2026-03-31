import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QLineEdit, QFrame,
)
from models import Player, PlayerConfig, PlayerType


class PlayerPanel(QWidget):
    config_changed = pyqtSignal(object)

    def __init__(self, player: Player, parent=None):
        super().__init__(parent)
        self.player = player
        self._collapsed = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._header = QPushButton(f"▾  Player {self.player.value.upper()}")
        self._header.clicked.connect(self._toggle)
        layout.addWidget(self._header)

        self._body = QFrame()
        self._body.setFrameShape(QFrame.StyledPanel)
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(8, 6, 8, 6)
        body_layout.setSpacing(4)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Type:"))
        self._type_combo = QComboBox()
        self._type_combo.addItems(["Human", "Bot"])
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_row.addWidget(self._type_combo)
        body_layout.addLayout(type_row)

        self._url_row = QWidget()
        url_layout = QHBoxLayout(self._url_row)
        url_layout.setContentsMargins(0, 0, 0, 0)
        url_layout.addWidget(QLabel("URL:"))
        self._url_edit = QLineEdit("http://localhost:8002")
        self._url_edit.editingFinished.connect(
            lambda: self.config_changed.emit(self.get_config())
        )
        url_layout.addWidget(self._url_edit)
        body_layout.addWidget(self._url_row)
        self._url_row.setVisible(False)

        layout.addWidget(self._body)

    def _toggle(self):
        self._collapsed = not self._collapsed
        self._body.setVisible(not self._collapsed)
        self._header.setText(
            f"{'▸' if self._collapsed else '▾'}  Player {self.player.value.upper()}"
        )

    def _on_type_changed(self):
        self._url_row.setVisible(self._type_combo.currentText() == "Bot")
        self.config_changed.emit(self.get_config())

    def get_config(self) -> PlayerConfig:
        is_bot = self._type_combo.currentText() == "Bot"
        return PlayerConfig(
            type=PlayerType.BOT if is_bot else PlayerType.HUMAN,
            bot_url=self._url_edit.text().strip() if is_bot else None,
        )