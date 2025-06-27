import asyncio
import uvicorn
import config
from bot import bot
from webhooks import app

async def run_services():
    """
    A coroutine to run both the bot and the web server.
    """
    server_config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
    server = uvicorn.Server(server_config)

    await asyncio.gather(
        bot.start(config.DISCORD_BOT_TOKEN),
        server.serve()
    )

if __name__ == "__main__":
    print("Launching bot and web server...")
    try:
        asyncio.run(run_services())
    except KeyboardInterrupt:
        print("Shutting down services.")
