# Hivemaker

HTTTX game engine, bot framework, and test UI for infinite hexagonal tic-tac-toe.

Partially implements the [HTTTX Bot API `basic_websocket` v1-alpha spec](https://github.com/hex-tic-tac-toe/htttx-bot-api/blob/main/definitions/basic_websocket/bws-v1-alpha.yaml). See [Spec compliance](#spec-compliance) for details.

---

## Architecture

```
game/serve.py        FastAPI + WebSocket game server       (port 8001)
bot/serve.py         Bot server — websockets + HTTP        (port 8002)
bot/bot.py           BaseBot (ABC) + CenterBot (example)
bot/capabilities.py  Capabilities schema + builder
ui/app.py            PyQt5 desktop client
models.py            Shared data types
game/game.py         Pure game logic (no IO)
```

The game server is the sole authority on board state. It connects **outward** to bot servers — bots do not initiate connections to the game server. The UI implements the same wire protocol as a bot. From the server's perspective, a human and a bot are identical.

Bot servers serve both HTTP (`GET /capabilities.json`) and WebSocket (`/bws/v1-alpha/game`) on the same port. The game server fetches capabilities before connecting to resolve the correct WebSocket path.

---

## Rules

- Two players: **X** and **O**. X's first piece is auto-placed at the origin `(0,0)`.
- Each turn a player places **2 pieces**. Turns alternate after both are placed.
- New pieces must be placed within `view_distance` (default: 8) hex steps of any occupied cell.
- Win condition: `win_distance` (default: 6) or more consecutive same-color pieces on any of the three hex axes.
- A player forfeits on disconnect or timeout.

### Coordinate system

Axial `(q, r)`. `+q` right, `+r` top-right. Third cube axis: `s = -q - r`.

```
hex_distance(q1,r1, q2,r2) = max(|q1-q2|, |r1-r2|, |(-q1-r1)-(-q2-r2)|)
```

---

## Setup

python version: 3.14.3

```
pip install fastapi uvicorn websockets pydantic PyQt5
```

```bash
python -m bot.serve    # port 8002
python -m game.serve   # port 8001
python -m ui.app
```

---

## Bot API

### Connection

The game server fetches `GET /capabilities.json` from the bot's HTTP base URL, resolves the WebSocket path from `basic_websocket.versions.v1-alpha.api_root` (default: `bws/v1-alpha/game`), then opens one WebSocket connection per game session.

One connection = one session. Concurrent games = concurrent connections. Session ends when the connection closes.

All messages are JSON, discriminated by `type`.

---

### Server → Bot packets

#### `setup`
Sent once before the first `move_request`. X's piece at `(0,0)` is already present.

```json
{
  "type": "setup",
  "board": {
    "cells": [{ "q": 0, "r": 0, "p": "x" }]
  }
}
```

#### `move_request`
Sent when it is the bot's turn. The bot must respond with exactly one `move_response`.

```json
{
  "type": "move_request",
  "side": "o",
  "previous": [
    {
      "side": "x",
      "pieces": [{ "q": 1, "r": 0 }, { "q": -1, "r": 0 }]
    }
  ],
  "board": { "cells": [...] },
  "move_time_limit": 5.0
}
```

| Field | Type | Description |
|---|---|---|
| `side` | `"x"` \| `"o"` | Side the bot is playing. Consistent across the session. |
| `previous` | `Move[]` | Ordered moves applied since the last `move_request`. Empty on the bot's first move. |
| `board` | `Board` | Authoritative full board state. Prefer this over tracking `previous`. |
| `move_time_limit` | `float \| null` | Seconds the bot has to respond. Only sent if bot declares `move_time_limit: true` in capabilities. |

#### `heartbeat`
Sent every `heartbeat` ms (default: 5000). No response required. If `waiting` is `true` and the bot is not processing a `move_request`, an error state has occurred — the bot must terminate the connection immediately.

```json
{ "type": "heartbeat", "waiting": true }
```

#### `end`
Sent when the game ends for any reason.

```json
{
  "type": "end",
  "winner": "x",
  "reason": "win",
  "board": { "cells": [...] }
}
```

| `reason` | `winner` |
|---|---|
| `"win"` | `"x"` or `"o"` |
| `"draw"` | `null` |
| `"forfeit"` | the non-forfeiting player |

`board` in the `end` packet is a Hivemaker extension — not in the base spec.

#### `nope`
Sent on protocol violation. Connection is closed immediately after.

```json
{ "type": "nope", "reason": "string" }
```

Triggers: invalid placement, malformed packet, wrong number of pieces, move sent without a pending request.

---

### Bot → Server packets

#### `move_response`
Must be sent in response to `move_request`, and only then. Contains exactly 2 pieces.

```json
{
  "type": "move_response",
  "move": {
    "pieces": [
      { "q": 1, "r": 1 },
      { "q": -1, "r": 2 }
    ],
    "evaluation": {
      "heuristic": 0.3,
      "win_in": null
    }
  },
  "considerations": []
}
```

| Field | Required | Description |
|---|---|---|
| `move.pieces` | yes | Exactly 2 unoccupied coords within `view_distance` of any existing piece |
| `move.evaluation` | no | Position evaluation after this move is applied |
| `considerations` | no | Additional moves considered, ordered best to worst |

`evaluation.heuristic`: real number, positive = X advantage, negative = O advantage. Suggested range `[-1, 1]`, not enforced.
`evaluation.win_in`: integer. Positive = X wins in N moves, negative = O wins in N moves. One move = 2 pieces placed.

---

### Data types

```
Board   { cells: Cell[] }
Cell    { q: int, r: int, p: "x" | "o" }
Coord   { q: int, r: int }
Move    { side: "x" | "o", pieces: [Coord, Coord] }
```

---

## Capabilities

Bot servers must serve `GET /capabilities.json`. The game server fetches this before connecting.

Minimal example declaring bws v1-alpha support:

```json
{
  "meta": {
    "name": "MyBot",
    "tags": ["minimax"]
  },
  "basic_websocket": {
    "versions": {
      "v1-alpha": {}
    }
  }
}
```

With optional features declared:

```json
{
  "basic_websocket": {
    "versions": {
      "v1-alpha": {
        "api_root": "bws/v1-alpha",
        "move_time_limit": true,
        "evaluation": true,
        "config": {}
      }
    }
  }
}
```

---

## Python base class

Subclass `BaseBot` in `bot/bot.py`. It handles all protocol details — config, setup, heartbeat, move timing, eval, end/nope termination.

```python
from bot.bot import BaseBot, PositionEvaluation
from bot.capabilities import BwsV1AlphaCapability, Capabilities, Meta, default_capabilities
from models import Cell, Coord, Match, Player
from game.game import valid_placement_cells

class MyBot(BaseBot):

    @classmethod
    def capabilities(cls) -> Capabilities:
        caps = default_capabilities(BwsV1AlphaCapability(
            move_time_limit=True,
            evaluation=True,
        ))
        caps.meta = Meta(name="MyBot", tags=["minimax"])
        return caps

    def choose_move(
        self,
        cells: list[Cell],
        player: Player,
        match: Match,
    ) -> tuple[Coord, Coord]:
        candidates = valid_placement_cells(cells, match.view_distance)
        # ... your logic
        return candidates[0], candidates[1]

    def evaluate(
        self,
        cells: list[Cell],
        player: Player,
        match: Match,
    ) -> PositionEvaluation:
        # only needed if evaluation=True in capabilities
        return PositionEvaluation(heuristic=0.0)

    def on_config(self, depth: int | None, extras: dict) -> None:
        # only needed if config={} in capabilities
        if depth is not None:
            self.depth = depth
```

Serve it by setting `BOT_CLASS` in `bot/serve.py`:

```python
from my_bot import MyBot
BOT_CLASS: type[BaseBot] = MyBot
```

**`Match` fields available in `choose_move`:**

| Field | Default | Type |
|---|---|---|
| `view_distance` | 8 | `int` — max hex steps from any piece for placement |
| `win_distance` | 6 | `int` — pieces in a row to win |
| `heartbeat` | 5000 | `int` — ms between heartbeats |
| `turn_limit` | `null` | `int \| None` |
| `clock_type` | `"none"` | `"none" \| "match" \| "turn" \| "incremental"` |
| `clock` | `null` | `float \| None` — seconds |

**Helpers in `game/game.py`:**

```python
valid_placement_cells(cells: list[Cell], view_distance: int) -> list[Coord]
hex_distance(q1, r1, q2, r2) -> int
check_win(cells, player, win_distance) -> bool
evaluate_status(cells, win_distance) -> GameStatus
place_piece(cells, coord, player) -> list[Cell]  # returns new list, does not mutate
```

---

## Starting a game via HTTP

```
POST http://localhost:8001/game/new
Content-Type: application/json
```

```json
{
  "player_x": { "type": "bot", "bot_url": "http://localhost:8002" },
  "player_o": { "type": "human" },
  "match_config": {
    "heartbeat": 5000,
    "view_distance": 8,
    "win_distance": 6,
    "turn_limit": null,
    "clock_type": "none",
    "clock": null
  }
}
```

Response:
```json
{
  "game_id": "...",
  "token_o": "..."
}
```

Token is returned only for human player slots. Connect as human:
```
ws://localhost:8001/ws?token=<token>
```

Spectate a running game (read-only, receives `board_update` and `end`):
```
ws://localhost:8001/spectate/<game_id>
```

---

## Spec compliance

Implements [bws-v1-alpha](https://github.com/hex-tic-tac-toe/htttx-bot-api/blob/main/definitions/basic_websocket/bws-v1-alpha.yaml).

| Feature | Status | Notes |
|---|---|---|
| `setup` packet | ✅ | |
| `move_request` / `move_response` | ✅ | |
| `heartbeat` with `waiting` | ✅ | |
| `nope` on violation | ✅ | |
| `end` packet | ✅ | Non-standard `board` field added |
| `capabilities.json` endpoint | ✅ | Served on same port as WebSocket |
| `capabilities` schema | ✅ | `meta`, `basic_websocket.versions.v1-alpha` |
| `api_root` resolution | ✅ | Game server fetches and follows `api_root` |
| `move_time_limit` from packet | ✅ | Respected if declared in capabilities |
| `config` packet | ✅ | `on_config()` override, `dynamic` not enforced |
| `move_response.considerations` | ✅ | Passed through; not populated by `CenterBot` |
| `move_response.evaluation` | ✅ | Passed through; not populated by `CenterBot` |
| `eval_request` / `eval_response` | ✅ | `evaluate()` override, declare `evaluation: true` |
| `evaluation_time_limit` | ✅ | Respected if declared in capabilities |
| `move_skips` | ❌ | Not declared; bot applies own move immediately |
| `dual_sided` | ❌ | Not implemented |
| `free_move_order` | ❌ | Not implemented |
| `free_setup` | ❌ | Setup always contains exactly X at origin |
| `resettable_state` | ❌ | Setup may only be sent once |
| `interruptible` | ❌ | Not implemented |

---

## Project structure

```
models.py                  Cell, Coord, Match, Player, PlayerConfig, GameStatus, NewGameRequest
game/
  game.py                  Stateless game logic
  serve.py                 Game server — manages sessions, drives turn loop, fetches bot capabilities
bot/
  bot.py                   BaseBot (ABC) + CenterBot (placeholder)
  capabilities.py          Capabilities schema (Pydantic) + default builder
  serve.py                 Bot server — websockets + HTTP on one port
ui/
  app.py                   Entry point
  main_window.py           Window layout, wires signals
  board_widget.py          Hex renderer, click → cell_clicked signal
  player_panel.py          Per-player config widget (type + bot URL)
  game_controller.py       Human player — implements bot protocol, drives UI updates
```
