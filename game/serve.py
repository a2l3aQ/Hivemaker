import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
import uuid
import uvicorn
import websockets
import urllib.request
import urllib.parse
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState
from models import Cell, Coord, GameStatus, Match, NewGameRequest, Player, PlayerType
from game.game import evaluate_status, is_valid_placement, place_piece

app = FastAPI(title="HTTTX Game Server")
_games: dict[str, "GameSession"] = {}
_tokens: dict[str, tuple[str, Player]] = {}

DEFAULT_BWS_PATH = "bws/v1-alpha/game"


def _http_from_ws(ws_url: str) -> str:
    """ws://host → http://host, wss://host → https://host"""
    return ws_url.replace("ws://", "http://").replace("wss://", "https://")


def _ws_from_http(http_url: str) -> str:
    return http_url.replace("http://", "ws://").replace("https://", "wss://")


def _resolve_bot_ws_url(bot_url: str) -> str:
    """
    Fetch /capabilities.json from the bot's HTTP base URL and resolve
    the correct WebSocket path from basic_websocket.versions.v1-alpha.api_root.
    Falls back to DEFAULT_BWS_PATH if capabilities are unavailable.
    """
    # Derive HTTP base from whatever URL format was provided
    if bot_url.startswith("ws"):
        http_base = _http_from_ws(bot_url).rstrip("/")
    else:
        http_base = bot_url.rstrip("/")

    try:
        with urllib.request.urlopen(
            f"{http_base}/capabilities.json", timeout=3
        ) as resp:
            caps = json.loads(resp.read())

        bws_versions = (
            caps.get("basic_websocket", {})
                .get("versions", {})
                .get("v1-alpha", {})
        )
        api_root = bws_versions.get("api_root", DEFAULT_BWS_PATH).strip("/")
        return _ws_from_http(f"{http_base}/{api_root}/game")

    except Exception as e:
        print(f"[capabilities] could not fetch from {http_base}: {e} — using default path")
        return _ws_from_http(f"{http_base}/{DEFAULT_BWS_PATH}")


def _wire_board(cells: list[Cell]) -> dict:
    return {"cells": [c.to_wire() for c in cells]}


def _wire_move(side: Player, pieces: list[Coord]) -> dict:
    return {"side": side.value, "pieces": [p.to_wire() for p in pieces]}


class PlayerSlot:
    def __init__(self, is_bot: bool):
        self.is_bot = is_bot
        self.outgoing: asyncio.Queue = asyncio.Queue()
        self.incoming: asyncio.Queue = asyncio.Queue()
        self.connected: asyncio.Event = asyncio.Event()


class GameSession:
    def __init__(
        self, game_id: str, match: Match,
        config_x, config_o,
    ):
        self.game_id = game_id
        self.match = match
        self.slots = {
            Player.X: PlayerSlot(config_x.type == PlayerType.BOT),
            Player.O: PlayerSlot(config_o.type == PlayerType.BOT),
        }
        self.cells: list[Cell] = [Cell(q=0, r=0, p=Player.X)]
        self.to_move: Player = Player.O
        self.status = GameStatus.IN_PROGRESS
        self.turn_count = 0
        self._spectators: list[asyncio.Queue] = []

    def start(self):
        asyncio.create_task(self._loop())

    async def _send(self, player: Player, msg: dict):
        await self.slots[player].outgoing.put(json.dumps(msg))

    async def _recv(self, player: Player, timeout: float | None) -> dict | None:
        try:
            return await asyncio.wait_for(
                self.slots[player].incoming.get(), timeout=timeout
            )
        except asyncio.TimeoutError:
            return None

    async def _broadcast(self, msg: dict):
        pkt = json.dumps(msg)
        for q in self._spectators:
            await q.put(pkt)

    async def _loop(self):
        await asyncio.gather(
            self.slots[Player.X].connected.wait(),
            self.slots[Player.O].connected.wait(),
        )

        setup = {"type": "setup", "board": _wire_board(self.cells)}
        await self._send(Player.X, setup)
        await self._send(Player.O, setup)

        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        last_turn: dict | None = None

        try:
            while self.status == GameStatus.IN_PROGRESS:
                current = self.to_move
                previous = [last_turn] if last_turn else []

                if self.slots[current].is_bot:
                    placed = await self._bot_turn(current, previous)
                else:
                    placed = await self._human_turn(current, previous)

                if placed is None:
                    return

                last_turn = _wire_move(current, placed)
                self.turn_count += 1

                await self._broadcast({
                    "type": "board_update",
                    "board": _wire_board(self.cells),
                    "to_move": (Player.O if current == Player.X else Player.X).value,
                    "status": self.status.value,
                })

                if self.status != GameStatus.IN_PROGRESS:
                    break

                if self.match.turn_limit and self.turn_count >= self.match.turn_limit:
                    self.status = GameStatus.DRAW
                    break

                self.to_move = Player.O if current == Player.X else Player.X
        finally:
            heartbeat_task.cancel()

        winner = (
            Player.X if self.status == GameStatus.X_WINS
            else Player.O if self.status == GameStatus.O_WINS
            else None
        )
        await self._end(winner, "win" if winner else "draw")
        _games.pop(self.game_id, None)

    async def _bot_turn(
        self, player: Player, previous: list[dict]
    ) -> list[Coord] | None:
        time_limit = self.match.clock if self.match.clock_type == "turn" else None
        await self._send(player, {
            "type": "move_request",
            "side": player.value,
            "previous": previous,
            "board": _wire_board(self.cells),
            **({"move_time_limit": time_limit} if time_limit else {}),
        })

        response = await self._recv(player, timeout=(time_limit or 0) + 10 if time_limit else 60)
        if response is None:
            await self._forfeit(player)
            return None
        if response.get("type") != "move_response":
            await self._nope(player, "expected move_response")
            return None

        pieces_raw = response.get("move", {}).get("pieces", [])
        if len(pieces_raw) != 2:
            await self._nope(player, "bot must respond with exactly 2 pieces")
            return None

        placed: list[Coord] = []
        for p in pieces_raw:
            coord = Coord(q=p["q"], r=p["r"])
            ok, reason = is_valid_placement(self.cells, coord, self.match.view_distance)
            if not ok:
                await self._nope(player, reason)
                return None
            self.cells = place_piece(self.cells, coord, player)
            placed.append(coord)
            self.status = evaluate_status(self.cells, self.match.win_distance)
            if self.status != GameStatus.IN_PROGRESS:
                break

        return placed

    async def _human_turn(
        self, player: Player, previous: list[dict]
    ) -> list[Coord] | None:
        placed: list[Coord] = []

        for i in range(2):
            prev = previous if i == 0 else [_wire_move(player, placed)]
            await self._send(player, {
                "type": "move_request",
                "side": player.value,
                "previous": prev,
                "board": _wire_board(self.cells),
            })

            response = await self._recv(player, timeout=300)
            if response is None:
                await self._forfeit(player)
                return None
            if response.get("type") != "move_response":
                await self._nope(player, "expected move_response")
                return None

            pieces_raw = response.get("move", {}).get("pieces", [])
            if len(pieces_raw) != 1:
                await self._nope(player, "human must respond with exactly 1 piece")
                return None

            p = pieces_raw[0]
            coord = Coord(q=p["q"], r=p["r"])
            ok, reason = is_valid_placement(self.cells, coord, self.match.view_distance)
            if not ok:
                await self._nope(player, reason)
                return None

            self.cells = place_piece(self.cells, coord, player)
            placed.append(coord)
            self.status = evaluate_status(self.cells, self.match.win_distance)
            if self.status != GameStatus.IN_PROGRESS:
                break

        return placed

    async def _heartbeat_loop(self):
        while self.status == GameStatus.IN_PROGRESS:
            await asyncio.sleep(self.match.heartbeat / 1000)
            for player, slot in self.slots.items():
                if slot.connected.is_set():
                    await slot.outgoing.put(json.dumps({
                        "type": "heartbeat",
                        "waiting": self.to_move == player,
                    }))

    async def _end(self, winner: Player | None, reason: str):
        pkt = json.dumps({
            "type": "end",
            "winner": winner.value if winner else None,
            "reason": reason,
            "board": _wire_board(self.cells),
        })
        for slot in self.slots.values():
            await slot.outgoing.put(pkt)
            await slot.outgoing.put(None)
        for q in self._spectators:
            await q.put(pkt)
            await q.put(None)

    async def _nope(self, player: Player, reason: str):
        await self.slots[player].outgoing.put(
            json.dumps({"type": "nope", "reason": reason})
        )
        await self.slots[player].outgoing.put(None)
        other = Player.O if player == Player.X else Player.X
        await self._end(other, "forfeit")

    async def _forfeit(self, player: Player):
        other = Player.O if player == Player.X else Player.X
        await self._end(other, "forfeit")


async def _run_bot_slot(session: GameSession, player: Player, bot_url: str):
    slot = session.slots[player]
    # Resolve actual WS URL via capabilities (runs in thread to avoid blocking loop)
    ws_url = await asyncio.get_event_loop().run_in_executor(
        None, _resolve_bot_ws_url, bot_url
    )
    print(f"[bot {player.value}] connecting to {ws_url}")
    try:
        async with websockets.connect(ws_url) as ws:
            slot.connected.set()

            async def sender():
                while True:
                    msg = await slot.outgoing.get()
                    if msg is None:
                        await ws.close()
                        return
                    await ws.send(msg)

            async def receiver():
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("type") == "move_response":
                        await slot.incoming.put(msg)

            await asyncio.gather(sender(), receiver())
    except Exception as e:
        print(f"[bot {player.value}] {e}")
        if not slot.connected.is_set():
            slot.connected.set()
        await session._nope(player, f"bot connection error: {e}")


@app.post("/game/new")
async def new_game(req: NewGameRequest) -> dict:
    game_id = str(uuid.uuid4())
    session = GameSession(game_id, req.match_config, req.player_x, req.player_o)
    _games[game_id] = session
    result: dict = {"game_id": game_id}

    for player, config in [(Player.X, req.player_x), (Player.O, req.player_o)]:
        if config.type == PlayerType.BOT:
            asyncio.create_task(
                _run_bot_slot(session, player, config.bot_url or "http://localhost:8002")
            )
        else:
            token = str(uuid.uuid4())
            _tokens[token] = (game_id, player)
            result[f"token_{player.value}"] = token

    session.start()
    return result


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, token: str):
    await websocket.accept()

    if token not in _tokens:
        await websocket.send_text(json.dumps({"type": "nope", "reason": "invalid token"}))
        await websocket.close()
        return

    game_id, player = _tokens.pop(token)
    if game_id not in _games:
        await websocket.send_text(json.dumps({"type": "nope", "reason": "game not found"}))
        await websocket.close()
        return

    session = _games[game_id]
    slot = session.slots[player]
    slot.connected.set()

    async def sender():
        while True:
            msg = await slot.outgoing.get()
            if msg is None:
                if websocket.client_state != WebSocketState.DISCONNECTED:
                    await websocket.close()
                return
            await websocket.send_text(msg)

    async def receiver():
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            if msg.get("type") == "move_response":
                await slot.incoming.put(msg)

    try:
        await asyncio.gather(sender(), receiver())
    except WebSocketDisconnect:
        asyncio.create_task(session._forfeit(player))
    except Exception as e:
        print(f"[ws {player.value}] {e}")


@app.websocket("/spectate/{game_id}")
async def spectate_endpoint(websocket: WebSocket, game_id: str):
    await websocket.accept()

    if game_id not in _games:
        await websocket.send_text(json.dumps({"type": "nope", "reason": "game not found"}))
        await websocket.close()
        return

    session = _games[game_id]
    q: asyncio.Queue = asyncio.Queue()
    session._spectators.append(q)

    await websocket.send_text(json.dumps({
        "type": "setup",
        "board": _wire_board(session.cells),
    }))

    try:
        while True:
            msg = await q.get()
            if msg is None:
                await websocket.close()
                return
            await websocket.send_text(msg)
    except WebSocketDisconnect:
        pass
    finally:
        if q in session._spectators:
            session._spectators.remove(q)


if __name__ == "__main__":
    uvicorn.run("game.serve:app", host="0.0.0.0", port=8001, reload=True)