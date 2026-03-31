from __future__ import annotations
from typing import Optional
from pydantic import BaseModel
from enum import Enum


class Player(str, Enum):
    X = "x"
    O = "o"


class Coord(BaseModel):
    q: int
    r: int

    def __hash__(self): return hash((self.q, self.r))
    def __eq__(self, other): return self.q == other.q and self.r == other.r
    def to_wire(self) -> dict: return {"q": self.q, "r": self.r}

    @classmethod
    def from_wire(cls, d: dict) -> Coord: return cls(q=d["q"], r=d["r"])


class Cell(BaseModel):
    q: int
    r: int
    p: Player

    def __hash__(self): return hash((self.q, self.r))
    def to_wire(self) -> dict: return {"q": self.q, "r": self.r, "p": self.p.value}

    @classmethod
    def from_wire(cls, d: dict) -> Cell: return cls(q=d["q"], r=d["r"], p=Player(d["p"]))


class Match(BaseModel):
    heartbeat: int = 5000
    view_distance: int = 8
    win_distance: int = 6
    turn_limit: Optional[int] = None
    clock_type: str = "none"
    clock: Optional[float] = None


class GameStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    X_WINS = "x_wins"
    O_WINS = "o_wins"
    DRAW = "draw"
    FORFEIT = "forfeit"


class PlayerType(str, Enum):
    HUMAN = "human"
    BOT = "bot"


class PlayerConfig(BaseModel):
    type: PlayerType = PlayerType.HUMAN
    bot_url: Optional[str] = "ws://localhost:8002"


class NewGameRequest(BaseModel):
    player_x: PlayerConfig = PlayerConfig()
    player_o: PlayerConfig = PlayerConfig()
    match_config: Match = Match()