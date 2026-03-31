import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
import http
import websockets
import websockets.asyncio.server
from websockets.http11 import Response
from websockets.datastructures import Headers
from bot.bot import BaseBot, CenterBot

# ---------------------------------------------------------------------------
# Swap bot here
# ---------------------------------------------------------------------------
BOT_CLASS: type[BaseBot] = CenterBot

_capabilities_json: bytes = b""


async def _process_request(connection, request):
    if request.path == "/capabilities.json":
        return Response(
            status_code=200,
            reason_phrase="OK",
            headers=Headers([
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(_capabilities_json))),
            ]),
            body=_capabilities_json,
        )
    return None


async def _handler(websocket):
    bot = BOT_CLASS()
    try:
        await bot.handle(websocket)
    except Exception as e:
        print(f"[serve] {e}")


async def main():
    global _capabilities_json
    _capabilities_json = json.dumps(BOT_CLASS.capabilities().model_dump()).encode()

    async with websockets.asyncio.server.serve(
        _handler,
        "0.0.0.0",
        8002,
        process_request=_process_request,
    ):
        print(f"Bot server listening on 0.0.0.0:8002")
        print(f"  capabilities: http://localhost:8002/capabilities.json")
        print(f"  websocket:    ws://localhost:8002/bws/v1-alpha/game")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())