import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math
from PyQt5.QtCore import Qt, pyqtSignal, QPointF
from PyQt5.QtGui import QPainter, QColor, QPen, QPolygonF, QFont
from PyQt5.QtWidgets import QWidget
from models import Cell, Coord, Player
from game.game import valid_placement_cells

_C_BG        = QColor("#111827")
_C_EMPTY     = QColor("#1f2937")
_C_HOVER     = QColor("#374151")
_C_VALID     = QColor("#1a2e1a")
_C_VALID_HO  = QColor("#254825")
_C_BORDER    = QColor("#374151")
_C_X         = QColor("#ef4444")
_C_O         = QColor("#3b82f6")
_C_PENDING   = QColor("#a3e635")
_C_TEXT      = QColor("#f9fafb")


def _hex_to_px(q: int, r: int, size: float) -> QPointF:
    return QPointF(size * 1.5 * q, size * (math.sqrt(3) / 2 * q + math.sqrt(3) * r))


def _px_to_hex(x: float, y: float, size: float) -> tuple[int, int]:
    q = (2 / 3 * x) / size
    r = (-1 / 3 * x + math.sqrt(3) / 3 * y) / size
    s = -q - r
    rq, rr, rs = round(q), round(r), round(s)
    if abs(rq - q) > abs(rr - r) and abs(rq - q) > abs(rs - s):
        rq = -rr - rs
    elif abs(rr - r) > abs(rs - s):
        rr = -rq - rs
    return rq, rr


def _corners(center: QPointF, size: float) -> QPolygonF:
    poly = QPolygonF()
    for i in range(6):
        a = math.pi / 180 * (60 * i)
        poly.append(QPointF(center.x() + size * math.cos(a),
                            center.y() + size * math.sin(a)))
    return poly


class BoardWidget(QWidget):
    cell_clicked = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cells: list[Cell] = []
        self._valid: set[tuple[int, int]] = set()
        self._render: list[tuple[int, int]] = []
        self._pending: Coord | None = None
        self._hover: tuple[int, int] | None = None
        self._view_distance: int = 8
        self.setMouseTracking(True)
        self.setMinimumSize(500, 500)

    def update_board(
        self,
        cells: list[Cell],
        view_distance: int = 8,
        pending: Coord | None = None,
    ):
        self._cells = cells
        self._view_distance = view_distance
        self._pending = pending
        self._valid = {
            (c.q, c.r) for c in valid_placement_cells(cells, view_distance)
        }
        self._render = list(
            {(c.q, c.r) for c in cells} | self._valid
        )
        self.update()

    def clear(self):
        self._cells = []
        self._valid = set()
        self._render = []
        self._pending = None
        self.update()

    def _cell_size(self) -> float:
        if not self._render:
            return 30.0
        pts = [_hex_to_px(q, r, 1.0) for q, r in self._render]
        sx = max(p.x() for p in pts) - min(p.x() for p in pts) + 2
        sy = max(p.y() for p in pts) - min(p.y() for p in pts) + 2
        if sx == 0 or sy == 0:
            return 30.0
        return min(self.width() / sx, self.height() / sy) * 0.88

    def _origin(self, size: float) -> QPointF:
        if not self._render:
            return QPointF(self.width() / 2, self.height() / 2)
        pts = [_hex_to_px(q, r, size) for q, r in self._render]
        cx = (max(p.x() for p in pts) + min(p.x() for p in pts)) / 2
        cy = (max(p.y() for p in pts) + min(p.y() for p in pts)) / 2
        return QPointF(self.width() / 2 - cx, self.height() / 2 - cy)

    def _center(self, q: int, r: int, size: float, origin: QPointF) -> QPointF:
        pt = _hex_to_px(q, r, size)
        return QPointF(origin.x() + pt.x(), origin.y() + pt.y())

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), _C_BG)

        if not self._cells and not self._valid:
            painter.setPen(_C_TEXT)
            painter.drawText(self.rect(), Qt.AlignCenter, "Start a game")
            return

        size = self._cell_size()
        origin = self._origin(size)
        occupied = {(c.q, c.r): c.p for c in self._cells}
        pending_key = (self._pending.q, self._pending.r) if self._pending else None

        for q, r in self._render:
            key = (q, r)
            center = self._center(q, r, size, origin)
            poly = _corners(center, size - 1.5)
            player = occupied.get(key)
            is_valid = key in self._valid
            is_hover = self._hover == key
            is_pending = key == pending_key

            if is_pending:
                fill = _C_PENDING
            elif player == Player.X:
                fill = _C_X
            elif player == Player.O:
                fill = _C_O
            elif is_hover and is_valid:
                fill = _C_VALID_HO
            elif is_hover:
                fill = _C_HOVER
            elif is_valid:
                fill = _C_VALID
            else:
                fill = _C_EMPTY

            painter.setBrush(fill)
            painter.setPen(QPen(_C_BORDER, 1.0))
            painter.drawPolygon(poly)

            if player:
                font = QFont()
                font.setPixelSize(max(7, int(size * 0.45)))
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(_C_TEXT)
                painter.drawText(
                    int(center.x() - size / 2), int(center.y() - size / 2),
                    int(size), int(size),
                    Qt.AlignCenter,
                    player.value.upper(),
                )

    def mouseMoveEvent(self, event):
        size = self._cell_size()
        origin = self._origin(size)
        q, r = _px_to_hex(event.x() - origin.x(), event.y() - origin.y(), size)
        new_hover = (q, r) if (q, r) in set(self._render) else None
        if self._hover != new_hover:
            self._hover = new_hover
            self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or not self._cells:
            return
        size = self._cell_size()
        origin = self._origin(size)
        q, r = _px_to_hex(event.x() - origin.x(), event.y() - origin.y(), size)
        if (q, r) in self._valid:
            self.cell_clicked.emit(q, r)