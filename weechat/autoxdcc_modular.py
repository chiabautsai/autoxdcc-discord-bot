# -*- coding: utf-8 -*-
#
# autoxdcc_modular.py - WeeChat backend service for XDCC searching and downloading.
#
# --- HISTORY ---
# 2023-10-29: Version 9.9, Integrated WeeChat's built-in config system for adaptability.
#             Replaced hardcoded values with configurable options and applied redactions.
#

import weechat
import re
import shlex
import json

# --- SCRIPT METADATA ---
SCRIPT_NAME = "autoxdcc_modular"
SCRIPT_AUTHOR = "Me"
SCRIPT_VERSION = "9.9" # Updated version for config system integration
SCRIPT_LICENSE = "MIT"
SCRIPT_DESC = "Final hardened backend service with robust parsing and locking, now configurable."

# --- CONFIGURATION DEFAULTS ---
# These are the default values for the plugin's configuration options.
# Users can change these via /set plugins.var.python.autoxdcc_modular.<option_name> <value>
DEFAULT_CONFIG_VALUES = {
    "irc_server_name": "irc.example.org", # Placeholder for the IRC server
    "irc_search_channel": "#channel",     # Placeholder for the IRC channel where search is performed
    "session_timeout": "300000",          # Session timeout in milliseconds (5 minutes)
    "api_endpoint_url": "http://localhost:8000/search_results" # URL for the Discord bot's webhook
}

# --- REGEX CONSTANTS (FINAL, CORRECTED VERSIONS) ---
RESULT_LINE_REGEX = re.compile(r'\(\s*(\d+)x\s*\[(.*?)]\s*(.*?)\s*\)\s*\(\s*(/msg\s+.*?xdcc\s+send\s+#\d+)\s*\).*')
END_OF_RESULTS_REGEX = re.compile(r'\( (\d+) Result(s)? Found - \d+ Gets \)')

def log_info(message):
    weechat.prnt("", f"{weechat.color('chat_prefix_weechat')}[{SCRIPT_NAME}] {message}")

def log_error(message):
    weechat.prnt("", f"{weechat.color('chat_prefix_error')}[{SCRIPT_NAME}] {message}")

# --- DATA CLASS ---
class XDCCSearchSession:
    def __init__(self, session_id, search_query):
        self.id = session_id
        self.query = search_query
        self.results = []
        self.choices = []

    def add_result(self, result_dict):
        self.results.append(result_dict)

    def generate_choices(self):
        # Sort by grabs (descending) to prioritize more popular files
        self.results.sort(key=lambda x: x['grabs'], reverse=True)
        # Use a dict to preserve order and get unique filenames
        unique_filenames = list(dict.fromkeys(r['filename'] for r in self.results))
        for i, filename in enumerate(unique_filenames):
            # Find the best result (most grabs) for this unique filename
            best_result = next(r for r in self.results if r['filename'] == filename)
            self.choices.append({
                "choice_id": i + 1,
                "filename": filename,
                "size": best_result['size']
            })

    def get_download_command(self, choice_id):
        try:
            choice_id = int(choice_id)
            target_choice = next((c for c in self.choices if c['choice_id'] == choice_id), None)
            if not target_choice:
                return None # Choice ID not found
            
            target_filename = target_choice['filename']
            # Find the original result with the highest grabs for this filename
            # (assuming results are still sorted or re-sort if necessary)
            self.results.sort(key=lambda x: x['grabs'], reverse=True) # Ensure sorted
            target_result = next((r for r in self.results if r['filename'] == target_filename), None)
            
            return target_result['command'] if target_result else None
        except (ValueError, IndexError):
            return None # Invalid choice_id format or out of range

# --- MANAGER CLASS ---
class SessionManager:
    def __init__(self):
        self._sessions = {} # Stores active XDCCSearchSession objects
        self._hooks = {}    # Stores WeeChat hook pointers (print, timers) for each session
        self.is_search_active = False # Global lock for search
        self.irc_server_name = ""
        self.irc_search_channel = ""
        self.session_timeout = 0
        self.api_endpoint_url = ""
    
    def load_config_values(self):
        """Loads configuration values from WeeChat's config system."""
        self.irc_server_name = weechat.config_get_plugin("irc_server_name")
        self.irc_search_channel = weechat.config_get_plugin("irc_search_channel")
        # Ensure session_timeout is an integer
        try:
            self.session_timeout = int(weechat.config_get_plugin("session_timeout"))
        except ValueError:
            log_error("Invalid 'session_timeout' config value. Using default 300000ms.")
            self.session_timeout = 300000 # Fallback default
        self.api_endpoint_url = weechat.config_get_plugin("api_endpoint_url")
        log_info(f"Configuration loaded: Server='{self.irc_server_name}', Channel='{self.irc_search_channel}', Timeout='{self.session_timeout}ms'")


    def start_new_session(self, session_id, query):
        session = XDCCSearchSession(session_id, query)
        self._sessions[session_id] = session
        log_info(f"Starting search for: '{query}' (Session ID: {session_id})")

        server_buffer_ptr = weechat.info_get("irc_buffer", self.irc_server_name)
        if not server_buffer_ptr:
            log_error(f"Could not find server buffer for '{self.irc_server_name}'. Please check server name in config.")
            self.end_session(session_id)
            self.release_search_lock() # Release lock if server not found
            self.send_error_to_frontend(session_id, f"Error: IRC server '{self.irc_server_name}' not found or connected.")
            return

        full_channel_name = f"{self.irc_server_name}.{self.irc_search_channel}"
        channel_buffer_ptr = weechat.buffer_search("irc", full_channel_name)
        if not channel_buffer_ptr:
            log_error(f"Could not find channel buffer '{full_channel_name}'. Please ensure you are joined to the channel.")
            self.end_session(session_id)
            self.release_search_lock() # Release lock if channel not found
            self.send_error_to_frontend(session_id, f"Error: IRC channel '{self.irc_search_channel}' not found or joined.")
            return
        
        # Hook print for the server buffer to catch notices from the XDCC bot
        self._hooks[session_id] = {'print_hook': weechat.hook_print(server_buffer_ptr, "irc_notice", "", 0, "global_print_cb", session_id)}
        weechat.command(channel_buffer_ptr, f"!search {query}")

    def end_session(self, session_id):
        if session_id in self._hooks:
            for hook_ptr in self._hooks[session_id].values():
                if hook_ptr: # Ensure hook_ptr is not None before unhooking
                    weechat.unhook(hook_ptr)
            self._hooks.pop(session_id)
        if session_id in self._sessions:
            log_info(f"Cleaning up data for session {session_id}.")
            self._sessions.pop(session_id)

    def release_search_lock(self):
        if self.is_search_active:
            self.is_search_active = False
            log_info("Search lock released. Ready for new search.")

    def handle_print_callback(self, session_id, message):
        session = self._sessions.get(session_id)
        if not session:
            # If session is already ended, just ignore.
            return weechat.WEECHAT_RC_OK

        clean_text = weechat.string_remove_color(message, "")
        result_match_obj = RESULT_LINE_REGEX.search(clean_text)
        end_match_obj = END_OF_RESULTS_REGEX.search(clean_text)

        if result_match_obj:
            session.add_result({
                "grabs": int(result_match_obj.group(1)),
                "size": result_match_obj.group(2).strip(),
                "filename": result_match_obj.group(3).strip(),
                "command": result_match_obj.group(4).strip()
            })
        
        if end_match_obj:
            log_info(f"End of results detected for session {session_id}.")
            # Unhook the print hook immediately
            if 'print_hook' in self._hooks[session_id] and self._hooks[session_id]['print_hook']:
                weechat.unhook(self._hooks[session_id].pop('print_hook'))
            
            # Set up a short timer for final processing to ensure all lines are received
            self._hooks[session_id]['processing_timer'] = weechat.hook_timer(500, 0, 1, "global_final_processing_cb", session_id)
            # Set up an expiry timer for the session
            self._hooks[session_id]['expiry_timer'] = weechat.hook_timer(self.session_timeout, 0, 1, "global_expiry_cb", session_id)
        
        return weechat.WEECHAT_RC_OK

    def handle_final_processing(self, session_id):
        # Release the lock as soon as search results parsing is complete
        self.release_search_lock() 
        
        session = self._sessions.get(session_id)
        if not session:
            log_error(f"handle_final_processing called for ended session {session_id}.");
            return weechat.WEECHAT_RC_OK
            
        # Unhook the processing timer immediately after it fires
        if 'processing_timer' in self._hooks.get(session_id, {}):
            if self._hooks[session_id]['processing_timer']:
                weechat.unhook(self._hooks[session_id].pop('processing_timer'))
        
        session.generate_choices()
        
        payload = {"session_id": session_id}
        if not session.choices:
            payload.update({"status": "no_results", "message": f"Search for '{session.query}' yielded no results."})
            self.end_session(session_id) # End session immediately if no results
        else:
            payload.update({"status": "success", "message": f"Found {len(session.choices)} choices.", "choices": session.choices})
        
        self.send_results_to_frontend(payload)
        return weechat.WEECHAT_RC_OK

    def send_rejection_to_frontend(self, session_id):
        payload = {"session_id": session_id, "status": "rejected_busy", "message": "Another search is already in progress. Please try again."}
        self.send_results_to_frontend(payload)

    def send_error_to_frontend(self, session_id, error_message):
        payload = {"session_id": session_id, "status": "error", "message": error_message}
        self.send_results_to_frontend(payload)

    def send_results_to_frontend(self, payload):
        if not self.api_endpoint_url:
            log_error("'api_endpoint_url' is not defined in WeeChat configuration. Cannot send results.")
            return

        json_payload = json.dumps(payload)
        # Using shlex.quote to properly quote the JSON payload for the shell command
        command = f"curl -X POST -H \"Content-Type: application/json\" --max-time 10 -d {shlex.quote(json_payload)} {self.api_endpoint_url}"
        log_info(f"Sending payload for session {payload['session_id']} to {self.api_endpoint_url}")
        weechat.hook_process(command, 12000, "global_http_post_cb", payload['session_id'])

    def handle_expiry(self, session_id):
        if session_id in self._sessions:
            log_info(f"Session '{session_id}' has expired and will be terminated.");
            # Send an expiration message to frontend if desired, before ending session
            # self.send_error_to_frontend(session_id, "Session expired due to inactivity.")
            self.end_session(session_id)
        return weechat.WEECHAT_RC_OK
        
    def handle_http_post_callback(self, session_id, command, return_code, stdout, stderr):
        if return_code != 0:
            log_error(f"Failed to send results for session {session_id} to frontend (RC: {return_code}).")
            log_error(f"Curl stderr: {stderr.strip()}") # Log stderr for debugging
        else:
            log_info(f"Results for session {session_id} sent successfully.")
        return weechat.WEECHAT_RC_OK

    def get_session(self, session_id):
        """Helper to retrieve a session."""
        return self._sessions.get(session_id)

    def shutdown(self):
        log_info(f"Shutting down. Terminating {len(self._sessions)} active session(s)...")
        for session_id in list(self._sessions.keys()):
            self.end_session(session_id)
        # Ensure lock is released on shutdown
        self.release_search_lock()

# Instantiate the SessionManager globally
SESSION_MANAGER = SessionManager()

# --- Global Callbacks (proxies to SessionManager methods) ---
def global_print_cb(data, buffer, date, tags, displayed, highlight, prefix, message):
    return SESSION_MANAGER.handle_print_callback(data, message)

def global_final_processing_cb(data, remaining_calls):
    return SESSION_MANAGER.handle_final_processing(data)

def global_expiry_cb(data, remaining_calls):
    return SESSION_MANAGER.handle_expiry(data)

def global_http_post_cb(data, cmd, rc, out, err):
    return SESSION_MANAGER.handle_http_post_callback(data, cmd, rc, out, err)

# --- WeeChat Command Callbacks ---
def service_search_cb(data, buffer, args):
    try:
        parts = shlex.split(args)
        session_id, query = parts[0], " ".join(parts[1:])
    except (ValueError, IndexError):
        log_info("Usage: /autoxdcc_service_search <session_id> <query>")
        return weechat.WEECHAT_RC_ERROR
    
    if SESSION_MANAGER.is_search_active:
        log_info(f"Rejecting search for '{query}' (SID: {session_id}). Another search is active.")
        SESSION_MANAGER.send_rejection_to_frontend(session_id)
        return weechat.WEECHAT_RC_OK
    
    SESSION_MANAGER.is_search_active = True
    log_info(f"Search lock acquired for session {session_id}.")
    SESSION_MANAGER.start_new_session(session_id, query)
    return weechat.WEECHAT_RC_OK

def service_download_cb(data, buffer, args):
    try:
        parts = shlex.split(args)
        session_id, choice_id_str = parts[0], parts[1]
    except (ValueError, IndexError):
        log_info("Usage: /autoxdcc_service_download <session_id> <choice_id>");
        return weechat.WEECHAT_RC_ERROR
    
    session = SESSION_MANAGER.get_session(session_id)
    if not session:
        log_info(f"Error: Session '{session_id}' is invalid or has expired for download request.");
        # Potentially send error back to frontend if session is truly gone
        return weechat.WEECHAT_RC_OK
    
    command_to_run = session.get_download_command(choice_id_str) # Pass as string, method handles int conversion
    if command_to_run:
        full_channel_name = f"{SESSION_MANAGER.irc_server_name}.{SESSION_MANAGER.irc_search_channel}"
        channel_buffer_ptr = weechat.buffer_search("irc", full_channel_name)
        if channel_buffer_ptr:
            log_info(f"Executing download for session {session_id}, choice {choice_id_str}: {command_to_run}")
            weechat.command(channel_buffer_ptr, command_to_run)
            SESSION_MANAGER.end_session(session_id) # End session after sending download command
        else:
            log_error(f"Could not find channel buffer '{full_channel_name}' to send download for session {session_id}.")
            SESSION_MANAGER.send_error_to_frontend(session_id, f"Error: WeeChat could not find the IRC channel '{full_channel_name}' to send download command.")
    else:
        log_info(f"Error: Invalid choice_id '{choice_id_str}' for session {session_id} (or command not found).")
        SESSION_MANAGER.send_error_to_frontend(session_id, f"Error: Invalid choice ID '{choice_id_str}' for session '{session_id}'.")
    return weechat.WEECHAT_RC_OK

# --- Script Initialization ---

def setup_plugin_config():
    """
    Initializes and sets default values for plugin options if they don't exist.
    """
    log_info("Setting up plugin configuration options...")
    for name, default_value in DEFAULT_CONFIG_VALUES.items():
        if not weechat.config_is_set_plugin(name):
            weechat.config_set_plugin(name, default_value)
            log_info(f"  Set default for '{name}' to: '{default_value}'")
        else:
            log_info(f"  Option '{name}' already exists with value: '{weechat.config_get_plugin(name)}'")
    log_info("Plugin configuration setup complete.")
    
    # After setting up defaults, load them into the SessionManager
    SESSION_MANAGER.load_config_values()


def shutdown_cb():
    """
    Callback called when the script is unloaded.
    Ensures all active sessions are terminated cleanly.
    """
    SESSION_MANAGER.shutdown()
    log_info(f"{SCRIPT_NAME} unloaded.")
    return weechat.WEECHAT_RC_OK

# --- Script Registration ---
if __name__ == "__main__":
    if weechat.register(
        SCRIPT_NAME,
        SCRIPT_AUTHOR,
        SCRIPT_VERSION,
        SCRIPT_LICENSE,
        SCRIPT_DESC,
        "shutdown_cb", # Function called on script unload
        "" # No extra data for shutdown callback
    ):
        # 1. Setup plugin configuration options (with defaults if not set)
        setup_plugin_config()

        # 2. Hook WeeChat commands
        weechat.hook_command(
            "autoxdcc_service_search",
            "Starts an XDCC search via the Discord bot. Usage: /autoxdcc_service_search <session_id> <query>",
            "<session_id> <query>", # Arguments
            "", # Arguments description (empty as usage describes it)
            "", # Completion
            "service_search_cb", # Callback function name
            "" # Callback data
        )
        weechat.hook_command(
            "autoxdcc_service_download",
            "Downloads a file by choice ID via the Discord bot. Usage: /autoxdcc_service_download <session_id> <choice_id>",
            "<session_id> <choice_id>", # Arguments
            "", # Arguments description
            "", # Completion
            "service_download_cb", # Callback function name
            "" # Callback data
        )
        log_info("Autoxdcc WeeChat backend (v9.9) loaded. Configuration is now managed via WeeChat's config system.")
        log_info("You can view/change settings with: /set plugins.var.python.autoxdcc_modular.*")
