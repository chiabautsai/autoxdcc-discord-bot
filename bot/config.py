import os
from dotenv import load_dotenv

load_dotenv()

# --- Discord Bot Configuration ---
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
DISCORD_SERVER_ID = int(os.getenv("DISCORD_SERVER_ID", "YOUR_SERVER_ID_HERE"))

# --- WeeChat Relay Configuration ---
WEECHAT_RELAY_HOST = os.getenv("WEECHAT_RELAY_HOST", "127.0.0.1")
WEECHAT_RELAY_PORT = int(os.getenv("WEECHAT_RELAY_PORT", 9001))
WEECHAT_RELAY_PASSWORD = os.getenv("WEECHAT_RELAY_PASSWORD")
