# weechat/libautoxdcc/utils.py

import weechat

SCRIPT_NAME = "autoxdcc" # Use the new main script name for consistent logs

def log_info(message):
    """Prints an informational message to the WeeChat core buffer."""
    weechat.prnt("", f"{weechat.color('chat_prefix_weechat')}[{SCRIPT_NAME}] {message}")

def log_error(message):
    """Prints an error message to the WeeChat core buffer."""
    weechat.prnt("", f"{weechat.color('chat_prefix_error')}[{SCRIPT_NAME}] {message}")

# We will move regexes here later.
