import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
import urllib.request
from PyQt5.QtCore import QObject, QThread, pyqtSignal
from models import Cell, Coord, GameStatus, Match, NewGameRequest, Player, PlayerConfig, PlayerType


class _WsWorker(QThread):
    """One WebSocket connection. Thread-safe send via asyncio queue."""
    message_received = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, url: str):
        super().__init__()
        self.url = url
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue | None = None
        self._running = True

    def send(self, data: dict):
        if self._loop and self._queue:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, json.dumps(data))

    def stop(self):
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    def run(self):
        self._loop = asyncio.new_event_loop()
        self._queue = asyncio.Queue()
        try:
            self._loop.run_until_complete(self._connect())
        except RuntimeError as e:
            if "Event loop stopped" not in str(e):
                self.error.emit(str(e))
        except Exception as e:
            import websockets
            if not isinstance(e, websockets.exceptions.ConnectionClosedOK):
                self.error.emit(str(e))
        finally:
            self._loop.close()

    async def _connect(self):
        import websockets
        async with websockets.connect(self.url) as ws:
            async def sender():
                while self._running:
                    try:
                        msg = await asyncio.wait_for(self._queue.get(), timeout=0.1)
                        await ws.send(msg)
                    except asyncio.TimeoutError:
                        pass

            async def receiver():
                async for raw in ws:
                    msg = json.loads(raw)
                    self.message_received.emit(msg)
                    if msg.get("type") in ("end", "nope"):
                        self._running = False
                        return

            await asyncio.gather(sender(), receiver())


class GameController(QObject):
    """
    Human player — implements the same protocol as a bot.
    Each click = one move_response with 1 piece.
    Spectator mode: connects to /spectate/{game_id}, receives board_update only.
    """
    state_updated = pyqtSignal(object)      # (list[Cell], GameStatus, Match | None, Player | None)
    error_occurred = pyqtSignal(str)
    log_message = pyqtSignal(str)
    waiting_for_human = pyqtSignal()
    heartbeat_received = pyqtSignal(bool)   # waiting: bool

    def __init__(self, game_url: str = "http://localhost:8001", parent=None):
        super().__init__(parent)
        self.game_url = game_url.rstrip("/")
        self.ws_url = (
            self.game_url
            .replace("http://", "ws://")
            .replace("https://", "wss://")
        )
        self._workers: list[_WsWorker] = []
        self._cells: list[Cell] = []
        self._match: Match | None = None
        self._my_player: Player | None = None
        self._game_over = False
        self._awaiting_move = False

    def start_game(self, player_x: PlayerConfig, player_o: PlayerConfig):
        for w in self._workers:
            w.stop()
        self._workers.clear()
        self._cells = []
        self._match = None
        self._my_player = None
        self._game_over = False
        self._awaiting_move = False

        payload = json.dumps(
            NewGameRequest(player_x=player_x, player_o=player_o).model_dump()
        ).encode()
        req = urllib.request.Request(
            f"{self.game_url}/game/new",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                result = json.loads(resp.read())
        except Exception as e:
            self.error_occurred.emit(str(e))
            return

        game_id = result.get("game_id")
        has_token = False

        for key, player in (("token_x", Player.X), ("token_o", Player.O)):
            token = result.get(key)
            if token:
                has_token = True
                if self._my_player is None:
                    self._my_player = player
                self._spawn_worker(f"{self.ws_url}/ws?token={token}")

        if not has_token and game_id:
            self.log_message.emit("Spectating — bot vs bot")
            self._spawn_worker(f"{self.ws_url}/spectate/{game_id}")

    def _spawn_worker(self, url: str):
        worker = _WsWorker(url)
        worker.message_received.connect(lambda msg, w=worker: self._on_message(msg, w))
        worker.error.connect(self.error_occurred)
        worker.finished.connect(
            lambda w=worker: self._workers.remove(w) if w in self._workers else None
        )
        self._workers.append(worker)
        worker.start()

    def human_cell_clicked(self, q: int, r: int):
        if self._game_over or not self._awaiting_move:
            return
        self._awaiting_move = False
        if self._workers:
            self._workers[0].send({
                "type": "move_response",
                "move": {"pieces": [{"q": q, "r": r}]},
            })

    def _on_message(self, msg: dict, worker: _WsWorker):
        mtype = msg.get("type")

        if mtype == "setup":
            self._cells = [Cell.from_wire(c) for c in msg["board"]["cells"]]
            self.state_updated.emit(
                (self._cells, GameStatus.IN_PROGRESS, self._match, self._my_player)
            )

        elif mtype == "heartbeat":
            self.heartbeat_received.emit(msg.get("waiting", False))

        elif mtype == "move_request":
            if "board" in msg:
                self._cells = [Cell.from_wire(c) for c in msg["board"]["cells"]]
            self._awaiting_move = True
            self.state_updated.emit(
                (self._cells, GameStatus.IN_PROGRESS, self._match, self._my_player)
            )
            self.waiting_for_human.emit()
            self.log_message.emit(
                f"Your turn ({msg.get('side','?').upper()}) — click a cell"
            )

        elif mtype == "board_update":
            self._cells = [Cell.from_wire(c) for c in msg["board"]["cells"]]
            self.state_updated.emit(
                (self._cells, GameStatus.IN_PROGRESS, self._match, self._my_player)
            )

        elif mtype == "end":
            self._game_over = True
            self._awaiting_move = False
            if "board" in msg:
                self._cells = [Cell.from_wire(c) for c in msg["board"]["cells"]]
            winner = msg.get("winner")
            reason = msg.get("reason", "")
            status = {
                ("win", "x"): GameStatus.X_WINS,
                ("win", "o"): GameStatus.O_WINS,
                ("draw", None): GameStatus.DRAW,
            }.get((reason, winner), GameStatus.FORFEIT)
            self.state_updated.emit(
                (self._cells, status, self._match, self._my_player)
            )
            w = winner.upper() if winner else "nobody"
            self.log_message.emit(f"Game over — {reason}, winner: {w}")

        elif mtype == "nope":
            self.error_occurred.emit(f"Nope: {msg.get('reason')}")