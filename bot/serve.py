import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import websockets
from bot.bot import CenterBot


async def handler(websocket):
    await CenterBot().handle(websocket)  # new instance per game


async def main():
    async with websockets.serve(handler, "0.0.0.0", 8002):
        print("Bot listening on ws://0.0.0.0:8002")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())