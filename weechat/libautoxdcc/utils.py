# weechat/libautoxdcc/utils.py

import weechat

SCRIPT_NAME = "autoxdcc"

class Logger:
    """
    A simple logger class that respects WeeChat's configured log level.
    """
    LEVELS = {
        "none": -1,
        "error": 0,
        "warning": 1,
        "info": 2,
        "debug": 3,
    }

    def __init__(self):
        # We will set the log level after the config has been loaded.
        self.configured_level = self.LEVELS["info"] # Default to 'info'

    def set_level(self, level_str: str):
        """Sets the current logging level from a string."""
        level_str = level_str.lower()
        self.configured_level = self.LEVELS.get(level_str, self.LEVELS["info"])
        # Provide feedback on successful level change
        self.info(f"Log level set to '{level_str}'.")

    def _log(self, level: str, message: str, color_prefix: str):
        """Internal log method that checks the configured level."""
        if self.LEVELS.get(level, -1) <= self.configured_level:
            weechat.prnt("", f"{color_prefix}[{SCRIPT_NAME}] {message}")

    def debug(self, message: str):
        """Logs a debug message."""
        self._log("debug", message, weechat.color("chat_prefix_weechat"))

    def info(self, message: str):
        """Logs an informational message."""
        self._log("info", message, weechat.color("chat_prefix_weechat"))

    def warning(self, message: str):
        """Logs a warning message."""
        self._log("warning", message, weechat.color("chat_prefix_error"))

    def error(self, message: str):
        """Logs an error message."""
        self._log("error", message, weechat.color("chat_prefix_error"))

# Create a single, global logger instance to be used by all modules
logger = Logger()
