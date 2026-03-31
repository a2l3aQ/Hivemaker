import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from abc import ABC, abstractmethod
from models import Cell, Coord, Match, Player
from game.game import hex_distance, valid_placement_cells


class BaseBot(ABC):
    """
    Abstract WS bot. One connection = one game. Stateless between games.
    Game server connects to the bot (not the other way around).
    """

    @abstractmethod
    def choose_move(
        self, cells: list[Cell], player: Player, match: Match
    ) -> tuple[Coord, Coord]:
        """Return two coords to place this turn."""
        ...

    async def handle(self, websocket):
        cells: list[Cell] = []
        match = Match()

        try:
            async for raw in websocket:
                msg = json.loads(raw)
                mtype = msg.get("type")

                if mtype == "config":
                    pass  # extend as needed

                elif mtype == "setup":
                    cells = [Cell.from_wire(c) for c in msg["board"]["cells"]]

                elif mtype == "heartbeat":
                    pass  # server-initiated keepalive, no response required

                elif mtype == "move_request":
                    # Apply moves that happened since last request
                    for wire_move in msg.get("previous", []):
                        side = Player(wire_move["side"])
                        for p in wire_move["pieces"]:
                            cells.append(Cell(q=p["q"], r=p["r"], p=side))

                    player = Player(msg["side"])

                    # Use board from extension field if provided
                    if "board" in msg:
                        cells = [Cell.from_wire(c) for c in msg["board"]["cells"]]

                    a, b = self.choose_move(cells, player, match)

                    # Apply our move to local state
                    cells.append(Cell(q=a.q, r=a.r, p=player))
                    cells.append(Cell(q=b.q, r=b.r, p=player))

                    await websocket.send(json.dumps({
                        "type": "move_response",
                        "move": {"pieces": [a.to_wire(), b.to_wire()]},
                    }))

                elif mtype in ("end", "nope"):
                    break

        except Exception as e:
            print(f"[{self.__class__.__name__}] {e}")


class CenterBot(BaseBot):
    """Placeholder: places the two valid cells closest to (0,0)."""

    def choose_move(self, cells: list[Cell], player: Player, match: Match) -> tuple[Coord, Coord]:
        candidates = valid_placement_cells(cells, match.view_distance)
        candidates.sort(key=lambda c: hex_distance(0, 0, c.q, c.r))
        return candidates[0], candidates[1]
