import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Optional
from models import Cell, Coord, Match, Player
from game.game import hex_distance, valid_placement_cells
from bot.capabilities import BwsV1AlphaCapability, Capabilities, Meta, default_capabilities


class PositionEvaluation:
    def __init__(self, heuristic: Optional[float] = None, win_in: Optional[int] = None):
        self.heuristic = heuristic
        self.win_in = win_in

    def to_wire(self) -> dict:
        d = {}
        if self.heuristic is not None:
            d["heuristic"] = self.heuristic
        if self.win_in is not None:
            d["win_in"] = self.win_in
        return d


class BaseBot(ABC):
    """
    Abstract WebSocket bot implementing bws-v1-alpha.

    One connection = one game session.
    Subclass and implement choose_move(). Optionally override:
      - capabilities()  to declare supported features
      - on_config()     to handle config packets
      - evaluate()      to support eval_request (declare evaluation=True in capabilities)
    """

    @classmethod
    def capabilities(cls) -> Capabilities:
        return default_capabilities(BwsV1AlphaCapability(
            move_time_limit=True,
        ))

    @abstractmethod
    def choose_move(
        self, cells: list[Cell], player: Player, match: Match
    ) -> tuple[Coord, Coord]:
        """Return two coords to place this turn."""
        ...

    def evaluate(
        self, cells: list[Cell], player: Player, match: Match
    ) -> PositionEvaluation:
        return PositionEvaluation()

    def on_config(self, depth: Optional[int], extras: dict) -> None:
        pass

    def _log(self, msg: str) -> None:
        print(f"[{self.__class__.__name__}] {msg}")

    async def handle(self, websocket) -> None:
        cells: list[Cell] = []
        match = Match()
        _processing = False

        caps = self.__class__.capabilities()
        bws = (
            caps.basic_websocket.versions.v1_alpha
            if caps.basic_websocket and caps.basic_websocket.versions.v1_alpha
            else BwsV1AlphaCapability()
        )

        try:
            async for raw in websocket:
                msg = json.loads(raw)
                mtype = msg.get("type")

                if mtype == "config":
                    self._log("config received")
                    self.on_config(
                        depth=msg.get("depth"),
                        extras={
                            k: v for k, v in msg.items()
                            if k not in ("type", "depth") and k.startswith("x-")
                        }
                    )

                elif mtype == "setup":
                    cells = [Cell.from_wire(c) for c in msg["board"]["cells"]]
                    self._log(f"game started — {len(cells)} cell(s) on board")

                elif mtype == "heartbeat":
                    if msg.get("waiting") and not _processing:
                        self._log("heartbeat: waiting=True but not processing — error state, closing")
                        await websocket.close()
                        return

                elif mtype == "move_request":
                    _processing = True
                    try:
                        for wire_move in msg.get("previous", []):
                            side = Player(wire_move["side"])
                            for p in wire_move["pieces"]:
                                cell = Cell(q=p["q"], r=p["r"], p=side)
                                if (cell.q, cell.r) not in {(c.q, c.r) for c in cells}:
                                    cells.append(cell)

                        if "board" in msg:
                            cells = [Cell.from_wire(c) for c in msg["board"]["cells"]]

                        player = Player(msg["side"])
                        time_limit: Optional[float] = msg.get("move_time_limit")
                        self._log(
                            f"move request for {player.value.upper()} "
                            f"— {len(cells)} cells on board"
                            + (f", time limit: {time_limit}s" if time_limit else "")
                        )

                        if bws.move_time_limit and time_limit:
                            a, b = await asyncio.wait_for(
                                asyncio.get_event_loop().run_in_executor(
                                    None, self.choose_move, cells, player, match
                                ),
                                timeout=time_limit,
                            )
                        else:
                            a, b = self.choose_move(cells, player, match)

                        cells.append(Cell(q=a.q, r=a.r, p=player))
                        cells.append(Cell(q=b.q, r=b.r, p=player))

                        await websocket.send(json.dumps({
                            "type": "move_response",
                            "move": {"pieces": [a.to_wire(), b.to_wire()]},
                        }))

                    except asyncio.TimeoutError:
                        self._log("move timed out — closing")
                        await websocket.close()
                        return
                    finally:
                        _processing = False

                elif mtype == "eval_request":
                    if not bws.evaluation:
                        self._log("eval_request received but evaluation not supported — closing")
                        await websocket.close()
                        return

                    player = Player(msg["side"])
                    time_limit = msg.get("evaluation_time_limit")
                    self._log(f"eval request for {player.value.upper()}")

                    if bws.evaluation_time_limit and time_limit:
                        result = await asyncio.wait_for(
                            asyncio.get_event_loop().run_in_executor(
                                None, self.evaluate, cells, player, match
                            ),
                            timeout=time_limit,
                        )
                    else:
                        result = self.evaluate(cells, player, match)

                    await websocket.send(json.dumps({
                        "type": "eval_response",
                        "evaluation": result.to_wire(),
                    }))

                elif mtype == "end":
                    winner = msg.get("winner")
                    reason = msg.get("reason")
                    self._log(f"game ended — {reason}, winner: {winner.upper() if winner else 'none'}")
                    break

                elif mtype == "nope":
                    self._log(f"nope: {msg.get('reason')}")
                    break

        except Exception as e:
            self._log(f"error: {e}")


class CenterBot(BaseBot):
    """Placeholder: places the two valid cells closest to (0,0)."""

    @classmethod
    def capabilities(cls) -> Capabilities:
        caps = default_capabilities(BwsV1AlphaCapability(
            move_time_limit=True,
        ))
        caps.meta = Meta(
            name="CenterBot",
            description="Places pieces closest to the origin. Placeholder implementation.",
            tags=["placeholder"],
        )
        return caps

    def choose_move(
        self, cells: list[Cell], player: Player, match: Match
    ) -> tuple[Coord, Coord]:
        candidates = valid_placement_cells(cells, match.view_distance)
        candidates.sort(key=lambda c: hex_distance(0, 0, c.q, c.r))
        return candidates[0], candidates[1]