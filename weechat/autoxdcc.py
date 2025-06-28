# -*- coding: utf-8 -*-
#
# autoxdcc.py - Main entry point for the modular AutoXDCC WeeChat backend.
#
# --- HISTORY ---
# 2023-10-30: Version 0.3.1. Bugfix - Re-added the 'send_download_status_to_frontend'.
# 2023-10-31: Version 0.4.0. Major Refactor - Transitioned to modular design with libautoxdcc.
#             This file now acts as a thin wrapper, delegating most logic to imported modules.
#

import weechat
import sys
import os

# --- IMPORTANT: Add the directory containing libautoxdcc to sys.path ---
# This ensures that our sub-modules can be imported.
# It assumes autoxdcc.py and libautoxdcc/ are siblings within the
# directory that is symlinked to WeeChat's python script path.
script_dir = os.path.dirname(os.path.abspath(__file__))
# Check if script_dir is already in sys.path to avoid duplicates
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

# --- Import core modules from our new library ---
# These imports will be unresolved until you create the files in libautoxdcc/
# This is expected for now.
from libautoxdcc import config, utils, models, irc_parser, webhook_sender, session_manager

# --- SCRIPT METADATA ---
SCRIPT_NAME = "autoxdcc" # New script name, without "_modular"
SCRIPT_AUTHOR = "Me"
SCRIPT_VERSION = "0.4.0" # Major version bump for modularization
SCRIPT_LICENSE = "MIT"
SCRIPT_DESC = "Modular WeeChat backend service for XDCC searching, hot lists, and downloading."

# --- GLOBAL SESSION MANAGER INSTANCE ---
# This will be instantiated after config is loaded.
# It's defined here globally as WeeChat's callbacks need a consistent reference.
SESSION_MANAGER = None

# --- GLOBAL CALLBACKS ---
# These functions are called by WeeChat directly, so they must be global.
# They will delegate their actual logic to the SESSION_MANAGER instance.

def global_print_cb(data, buffer, date, tags, displayed, highlight, prefix, message):
    """WeeChat print hook callback for IRC messages."""
    return SESSION_MANAGER.handle_print_callback(data, message)

def global_final_processing_cb(data, remaining_calls):
    """Timer callback for processing search/hot list results."""
    return SESSION_MANAGER.handle_final_processing(data)

def global_expiry_cb(data, remaining_calls):
    """Timer callback for session expiry."""
    return SESSION_MANAGER.handle_expiry(data)

def global_http_post_cb(data, cmd, rc, out, err):
    """Process hook callback for curl HTTP POST requests."""
    return SESSION_MANAGER.handle_http_post_callback(data, cmd, rc, out, err)


# --- WEECHAT COMMAND HANDLERS ---
# These functions are called by WeeChat when a command is typed.
# They will delegate their actual logic to the SESSION_MANAGER instance.

def service_search_cb(data, buffer, args):
    """Handles the /autoxdcc_service_search command."""
    return session_manager.service_search_cb(data, buffer, args, SESSION_MANAGER)

def service_hot_cb(data, buffer, args):
    """Handles the /autoxdcc_service_hot command."""
    return session_manager.service_hot_cb(data, buffer, args, SESSION_MANAGER)

def service_download_cb(data, buffer, args):
    """Handles the /autoxdcc_service_download command."""
    return session_manager.service_download_cb(data, buffer, args, SESSION_MANAGER)


# --- INITIALIZATION AND SHUTDOWN ---

def setup_plugin():
    """Initializes plugin configuration and loads settings into the session manager."""
    utils.log_info("Setting up plugin configuration options...")
    for name, default_value in config.DEFAULT_CONFIG_VALUES.items():
        if not weechat.config_is_set_plugin(name):
            weechat.config_set_plugin(name, default_value)
            utils.log_info(f"  Set default for '{name}' to: '{default_value}'")
    utils.log_info("Plugin configuration setup complete.")

    global SESSION_MANAGER
    SESSION_MANAGER = session_manager.SessionManager(
        irc_server_name=weechat.config_get_plugin("irc_server_name"),
        irc_search_channel=weechat.config_get_plugin("irc_search_channel"),
        session_timeout=int(weechat.config_get_plugin("session_timeout")),
        discord_api_base_url=weechat.config_get_plugin("discord_api_base_url"),
        hot_list_completion_delay=int(weechat.config_get_plugin("hot_list_completion_delay"))
    )
    utils.log_info(f"SessionManager initialized with config. Timeout='{SESSION_MANAGER.session_timeout}ms', HotListDelay='{SESSION_MANAGER.hot_list_completion_delay}ms'")


def shutdown_cb():
    """Callback when the script is unloaded by WeeChat."""
    if SESSION_MANAGER:
        SESSION_MANAGER.shutdown()
    utils.log_info(f"{SCRIPT_NAME} unloaded.")
    return weechat.WEECHAT_RC_OK


if __name__ == "__main__":
    if weechat.register(SCRIPT_NAME, SCRIPT_AUTHOR, SCRIPT_VERSION, SCRIPT_LICENSE, SCRIPT_DESC, "shutdown_cb", ""):
        setup_plugin()
        # Register commands
        weechat.hook_command("autoxdcc_service_search", "Starts an XDCC search", "", "", "", "service_search_cb", "")
        weechat.hook_command("autoxdcc_service_hot", "Starts a hot files listing", "", "", "", "service_hot_cb", "")
        weechat.hook_command("autoxdcc_service_download", "Downloads a file by choice ID", "", "", "", "service_download_cb", "")
        utils.log_info(f"AutoXDCC WeeChat backend (v{SCRIPT_VERSION}) loaded and ready.")
        utils.log_info("You can view/change settings with: /set plugins.var.python.autoxdcc.*") # Note the name change
