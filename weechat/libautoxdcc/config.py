# weechat/libautoxdcc/config.py

# --- CONFIGURATION DEFAULTS ---
# These are the default values for the WeeChat plugin's settings.
# They can be overridden by the user using /set plugins.var.python.autoxdcc.*
DEFAULT_CONFIG_VALUES = {
    "irc_server_name": "irc.example.org",
    "irc_search_channel": "#channel",
    "session_timeout": "300000",        # milliseconds
    "discord_api_base_url": "http://localhost:8000/",
    "hot_list_completion_delay": "2000", # milliseconds
    "log_level": "info"                 # NEW: Log verbosity (debug, info, warning, error, none)
}
