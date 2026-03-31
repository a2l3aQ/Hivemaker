# Hivemaker

I am still working on setting this repo up. It may not work.

Infinite hexagonal tic-tac-toe engine with a WebSocket bot API and PyQt5 test UI.

Partially implements the [HTTTX Bot API `basic_websocket` v1-alpha spec](https://github.com/hex-tic-tac-toe/htttx-bot-api/blob/main/definitions/basic_websocket/bws-v1-alpha.yaml).

---

## Architecture

```
game/serve.py   FastAPI + WebSocket game server      (port 8001)
bot/serve.py    Example bot server (CenterBot)       (port 8002)
ui/app.py       PyQt5 desktop client
models.py       Shared data types
game/game.py    Pure game logic (no IO)
```

The game server is the sole authority on board state. It connects **outward** to bot servers. The UI implements the same wire protocol as a bot. From the server's perspective, a human and a bot are identical.

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

Python version: 3.14.3

Install requirements.txt

```bash
python -m bot.serve    # port 8002
python -m game.serve   # port 8001
python -m ui.app
```

---

## Bot API

### Connection

The game server opens one WebSocket connection per game to the configured bot URL. One connection = one session. The bot may start a fresh session on connection, or wait for the `setup` packet to match against cached state.

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
  "board": {
    "cells": [...]
  }
}
```

| Field | Type | Description |
|---|---|---|
| `side` | `"x"` \| `"o"` | Side the bot is playing. Consistent across the session. |
| `previous` | `Move[]` | Ordered moves applied since the last `move_request`. Empty on the bot's first move. |
| `board` | `Board` | Authoritative full board state. Can be used instead of tracking `previous`. |

#### `heartbeat`
Sent every `heartbeat` ms (default: 5000). No response required. If `waiting` is `true` and the bot is not processing a `move_request`, an error state has occurred and the bot should terminate the connection.

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

#### `nope`
Sent on protocol violation. Connection is closed immediately after. The bot's player forfeits.

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
| `move.evaluation` | no | Position evaluation after this move |
| `considerations` | no | Additional moves considered, ordered best to worst |

`evaluation.heuristic`: any real number, positive = X advantage, negative = O advantage. Suggested range `[-1, 1]` but not enforced.  
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

## Python base class

Subclass `BaseBot` in `bot/bot.py` to skip all protocol handling:

```python
from bot.bot import BaseBot
from models import Cell, Coord, Match, Player
from game.game import valid_placement_cells

class MyBot(BaseBot):
    def choose_move(
        self,
        cells: list[Cell],   # current board
        player: Player,       # Player.X or Player.O
        match: Match,         # game config
    ) -> tuple[Coord, Coord]:
        candidates = valid_placement_cells(cells, match.view_distance)
        # ... your logic
        return candidates[0], candidates[1]
```

Serve it:

```python
import asyncio, websockets
from my_bot import MyBot

async def handler(ws):
    await MyBot().handle(ws)

async def main():
    async with websockets.serve(handler, "0.0.0.0", 8002):
        await asyncio.Future()

asyncio.run(main())
```

`BaseBot.handle()` applies `previous` moves, calls `choose_move`, sends the response, and handles `end`/`nope` termination. It creates no shared state — each call to `handle()` is independent, concurrent games work without any extra threading.

**`Match` fields:**

| Field | Default | Type |
|---|---|---|
| `view_distance` | 8 | `int` |
| `win_distance` | 6 | `int` |
| `heartbeat` | 5000 | `int` (ms) |
| `turn_limit` | `null` | `int \| None` |
| `clock_type` | `"none"` | `"none" \| "match" \| "turn" \| "incremental"` |
| `clock` | `null` | `float \| None` (seconds) |

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
  "player_x": { "type": "bot", "bot_url": "ws://localhost:8002" },
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

Spectate a running game (receives `board_update` and `end`, read-only):
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
| `move_response.considerations` | ✅ | Passed through; not populated by `CenterBot` |
| `move_response.evaluation` | ✅ | Passed through; not populated by `CenterBot` |
| `config` packet | ⚠️ | Received, silently ignored |
| `eval_request` / `eval_response` | ❌ | Not implemented |
| `move_time_limit` from packet | ⚠️ | Hardcoded 60s server-side; packet field ignored |
| Bot endpoint path | ⚠️ | Spec defines `/game`; implementation accepts on any path |
| `capabilities.json` | ❌ | Not implemented |

---

## Project structure

```
models.py                  Cell, Coord, Match, Player, PlayerConfig, GameStatus, NewGameRequest
game/
  game.py                  Stateless game logic
  serve.py                 Game server — manages sessions, drives turn loop
bot/
  bot.py                   BaseBot (ABC) + CenterBot (placeholder)
  serve.py                 Example bot server
ui/
  app.py                   Entry point
  main_window.py           Window layout, wires signals
  board_widget.py          Hex renderer, click → cell_clicked signal
  player_panel.py          Per-player config widget (type + bot URL)
  game_controller.py       Human player — implements bot protocol, drives UI updates
```