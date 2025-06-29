import asyncio
import uvicorn
import config
from bot import bot
# **FIX**: Import app and the TMDB_CLIENT instance for shutdown
from webhooks import app, TMDB_CLIENT

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
        print("Shutting down services due to KeyboardInterrupt.")
    finally:
        # **FIX**: Ensure the TMDB client's session is closed on shutdown.
        # We need to run this cleanup in a new asyncio event loop
        # as the previous one was closed by asyncio.run().
        print("Closing TMDB client session...")
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(TMDB_CLIENT.close())
            else:
                asyncio.run(TMDB_CLIENT.close())
            print("TMDB client session closed.")
        except Exception as e:
            print(f"Error closing TMDB client session: {e}")
