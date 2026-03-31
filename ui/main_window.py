import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout,
    QLabel, QPushButton, QTextEdit, QGroupBox, QSplitter,
)
from models import GameStatus, Player
from ui.board_widget import BoardWidget
from ui.player_panel import PlayerPanel
from ui.game_controller import GameController


class MainWindow(QMainWindow):
    def __init__(self, game_url: str = "http://localhost:8001"):
        super().__init__()
        self.setWindowTitle("HTTTX")
        self.setMinimumSize(900, 620)

        self._controller = GameController(game_url=game_url)
        self._controller.state_updated.connect(self._on_state_updated)
        self._controller.error_occurred.connect(lambda m: self._log(f"ERROR: {m}"))
        self._controller.waiting_for_human.connect(
            lambda: self._status.setText("Your turn — click a cell")
        )
        self._controller.heartbeat_received.connect(
            lambda waiting: self._hb.setText(f"♥ {'waiting' if waiting else 'idle'}")
        )
        self._controller.log_message.connect(self._log)

        self._match = None
        self._build_ui()

    def _build_ui(self):
        splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)

        self._board = BoardWidget()
        self._board.cell_clicked.connect(self._controller.human_cell_clicked)
        splitter.addWidget(self._board)

        side = QWidget()
        side.setFixedWidth(220)
        layout = QVBoxLayout(side)
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        ctrl = QGroupBox("Game")
        ctrl_layout = QVBoxLayout(ctrl)
        btn = QPushButton("New Game")
        btn.clicked.connect(self._start_game)
        ctrl_layout.addWidget(btn)
        self._status = QLabel("—")
        self._status.setAlignment(Qt.AlignCenter)
        ctrl_layout.addWidget(self._status)
        self._hb = QLabel("♥ —")
        self._hb.setAlignment(Qt.AlignCenter)
        ctrl_layout.addWidget(self._hb)
        layout.addWidget(ctrl)

        self._panel_x = PlayerPanel(Player.X)
        self._panel_o = PlayerPanel(Player.O)
        layout.addWidget(self._panel_x)
        layout.addWidget(self._panel_o)

        log_box = QGroupBox("Log")
        log_layout = QVBoxLayout(log_box)
        self._log_edit = QTextEdit()
        self._log_edit.setReadOnly(True)
        log_layout.addWidget(self._log_edit)
        layout.addWidget(log_box)

        splitter.addWidget(side)
        splitter.setSizes([680, 220])

    def _start_game(self):
        self._log_edit.clear()
        self._board.clear()
        self._status.setText("Connecting…")
        self._controller.start_game(
            player_x=self._panel_x.get_config(),
            player_o=self._panel_o.get_config(),
        )

    def _on_state_updated(self, payload):
        cells, status, match, my_player = payload
        if match:
            self._match = match
        vd = self._match.view_distance if self._match else 8
        self._board.update_board(cells, view_distance=vd)

        if status != GameStatus.IN_PROGRESS:
            labels = {
                GameStatus.X_WINS: "X wins!",
                GameStatus.O_WINS: "O wins!",
                GameStatus.DRAW: "Draw",
                GameStatus.FORFEIT: "Forfeit",
            }
            self._status.setText(labels.get(status, "—"))

    def _log(self, msg: str):
        self._log_edit.append(msg)
        self._log_edit.verticalScrollBar().setValue(
            self._log_edit.verticalScrollBar().maximum()
        )