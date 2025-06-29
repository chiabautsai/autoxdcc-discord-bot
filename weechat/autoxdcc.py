# -*- coding: utf-8 -*-
#
# autoxdcc.py - Main entry point for the modular AutoXDCC WeeChat backend.
#
# --- HISTORY ---
# 2023-10-31: Version 0.4.0. Major Refactor - Transitioned to modular design.
# 2025-06-29: Version 0.5.0. Added configurable logging levels.
#

import weechat
import sys
import os

# Add the directory containing libautoxdcc to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

# --- MODIFIED: Import logger instance directly ---
from libautoxdcc import config, models, webhook_sender, session_manager
from libautoxdcc.utils import logger

# --- SCRIPT METADATA ---
SCRIPT_NAME = "autoxdcc"
SCRIPT_AUTHOR = "Me"
SCRIPT_VERSION = "0.5.0" # Version bump for new feature
SCRIPT_LICENSE = "MIT"
SCRIPT_DESC = "Modular WeeChat backend with configurable logging."

# --- GLOBAL SESSION MANAGER INSTANCE ---
SESSION_MANAGER = None

# --- GLOBAL CALLBACKS ---
# These now just check if the session manager exists before delegating.
def global_print_cb(data, buffer, date, tags, displayed, highlight, prefix, message):
    if SESSION_MANAGER: return SESSION_MANAGER.handle_print_callback(data, message)
    return weechat.WEECHAT_RC_OK

def global_final_processing_cb(data, remaining_calls):
    if SESSION_MANAGER: return SESSION_MANAGER.handle_final_processing(data)
    return weechat.WEECHAT_RC_OK

def global_expiry_cb(data, remaining_calls):
    if SESSION_MANAGER: return SESSION_MANAGER.handle_expiry(data)
    return weechat.WEECHAT_RC_OK

def global_http_post_cb(data, cmd, rc, out, err):
    if SESSION_MANAGER: return SESSION_MANAGER.handle_http_post_callback(data, cmd, rc, out, err)
    return weechat.WEECHAT_RC_OK

# --- WEECHAT COMMAND HANDLERS ---
def service_search_cb(data, buffer, args):
    if SESSION_MANAGER: return session_manager.service_search_cb(data, buffer, args, SESSION_MANAGER)
    logger.error("SESSION_MANAGER not initialized for search command.")
    return weechat.WEECHAT_RC_ERROR

def service_hot_cb(data, buffer, args):
    if SESSION_MANAGER: return session_manager.service_hot_cb(data, buffer, args, SESSION_MANAGER)
    logger.error("SESSION_MANAGER not initialized for hot command.")
    return weechat.WEECHAT_RC_ERROR

def service_download_cb(data, buffer, args):
    if SESSION_MANAGER: return session_manager.service_download_cb(data, buffer, args, SESSION_MANAGER)
    logger.error("SESSION_MANAGER not initialized for download command.")
    return weechat.WEECHAT_RC_ERROR

# --- INITIALIZATION AND SHUTDOWN ---
def setup_plugin():
    """Initializes plugin configuration and the session manager."""
    # --- MODIFIED: Set up logger first ---
    logger.info("Setting up plugin configuration options...")
    for name, default_value in config.DEFAULT_CONFIG_VALUES.items():
        if not weechat.config_is_set_plugin(name):
            weechat.config_set_plugin(name, default_value)
            logger.debug(f"  Set default for '{name}' to: '{default_value}'")
    
    # --- MODIFIED: Set the logger's level based on the loaded config ---
    log_level_config = weechat.config_get_plugin("log_level")
    logger.set_level(log_level_config)

    global SESSION_MANAGER
    try:
        SESSION_MANAGER = session_manager.SessionManager(
            irc_server_name=weechat.config_get_plugin("irc_server_name"),
            irc_search_channel=weechat.config_get_plugin("irc_search_channel"),
            session_timeout=int(weechat.config_get_plugin("session_timeout")),
            discord_api_base_url=weechat.config_get_plugin("discord_api_base_url"),
            hot_list_completion_delay=int(weechat.config_get_plugin("hot_list_completion_delay"))
        )
        # --- MODIFIED: Use new logger ---
        logger.debug(f"SessionManager initialized.")
    except Exception as e:
        # --- MODIFIED: Use new logger ---
        logger.error(f"Failed to initialize SessionManager: {e}. Plugin will not function.")
        return weechat.WEECHAT_RC_ERROR

def shutdown_cb():
    """Callback when the script is unloaded by WeeChat."""
    if SESSION_MANAGER:
        SESSION_MANAGER.shutdown()
    # --- MODIFIED: Use new logger ---
    logger.info(f"{SCRIPT_NAME} unloaded.")
    return weechat.WEECHAT_RC_OK


if __name__ == "__main__":
    if weechat.register(SCRIPT_NAME, SCRIPT_AUTHOR, SCRIPT_VERSION, SCRIPT_LICENSE, SCRIPT_DESC, "shutdown_cb", ""):
        if setup_plugin() != weechat.WEECHAT_RC_ERROR:
            # Register commands only if initialization was successful
            weechat.hook_command("autoxdcc_service_search", "Starts an XDCC search", "", "", "", "service_search_cb", "")
            weechat.hook_command("autoxdcc_service_hot", "Starts a hot files listing", "", "", "", "service_hot_cb", "")
            weechat.hook_command("autoxdcc_service_download", "Downloads a file by choice ID", "", "", "", "service_download_cb", "")
            # --- MODIFIED: Use new logger ---
            logger.info(f"AutoXDCC WeeChat backend (v{SCRIPT_VERSION}) loaded and ready.")
            logger.info("You can view/change settings with: /set plugins.var.python.autoxdcc.*")
        else:
            # Use weechat.prnt directly here as the logger might be the cause of failure
            weechat.prnt("", f"{weechat.color('chat_prefix_error')}[{SCRIPT_NAME}] Plugin initialization failed. Check logs for details.")
