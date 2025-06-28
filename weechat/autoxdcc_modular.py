# -*- coding: utf-8 -*-
#
# autoxdcc_modular.py - WeeChat backend service for XDCC searching and downloading.
#
# --- HISTORY ---
# 2023-10-30: Version 0.3. Added '/hot' command to fetch and parse trending files.
# 2023-10-30: Version 0.3.1. Bugfix - Re-added the 'send_download_status_to_frontend'
#             helper method that was accidentally removed in the v0.3 refactor.
#

import weechat
import re
import shlex
import json

# --- SCRIPT METADATA ---
SCRIPT_NAME = "autoxdcc_modular"
SCRIPT_AUTHOR = "Me"
SCRIPT_VERSION = "0.3.1" # Auto-bumped version
SCRIPT_LICENSE = "MIT"
SCRIPT_DESC = "Robust XDCC backend service with dynamic config, advanced parsing, locking, and comprehensive Discord feedback for search and hot lists."

# --- CONFIGURATION DEFAULTS ---
DEFAULT_CONFIG_VALUES = {
    "irc_server_name": "irc.example.org",
    "irc_search_channel": "#channel",
    "session_timeout": "300000",
    "discord_api_base_url": "http://localhost:8000/",
    "hot_list_completion_delay": "2000"
}

# --- REGEX CONSTANTS ---
RESULT_LINE_REGEX = re.compile(r'\(\s*(\d+)x\s*\[(.*?)]\s*(.*?)\s*\)\s*\(\s*(/msg\s+.*?xdcc\s+send\s+#\d+)\s*\).*')
END_OF_RESULTS_REGEX = re.compile(r'\( (\d+) Result(s)? Found - \d+ Gets \)')
HOT_HEADER_REGEX = re.compile(r'#THE\.SOURCE.*?¦\s*(.*?)\s*¦\s*(.*)')
HOT_RESULT_LINE_REGEX = re.compile(r'(\d+)x\s*\|\s+([\w\.-]+)\s+\[(.*?)]\s+(.*)')


def log_info(message):
    weechat.prnt("", f"{weechat.color('chat_prefix_weechat')}[{SCRIPT_NAME}] {message}")

def log_error(message):
    weechat.prnt("", f"{weechat.color('chat_prefix_error')}[{SCRIPT_NAME}] {message}")

# --- DATA CLASS ---
class XDCCSession:
    # ... (This class is unchanged) ...
    def __init__(self, session_id, query, session_type):
        self.id = session_id; self.query = query; self.type = session_type
        self.search_results = []; self.choices = []
        self.hot_summary = ""; self.hot_items = []
    def add_search_result(self, result_dict): self.search_results.append(result_dict)
    def add_hot_item(self, item_dict): self.hot_items.append(item_dict)
    def generate_choices(self):
        self.search_results.sort(key=lambda x: x['grabs'], reverse=True)
        unique_filenames = list(dict.fromkeys(r['filename'] for r in self.search_results))
        for i, filename in enumerate(unique_filenames):
            best_result = next(r for r in self.search_results if r['filename'] == filename)
            self.choices.append({"choice_id": i + 1, "filename": filename, "size": best_result['size']})
    def get_download_command(self, choice_id):
        try:
            choice_id = int(choice_id)
            target_choice = next((c for c in self.choices if c['choice_id'] == choice_id), None)
            if not target_choice: return None, None
            target_filename = target_choice['filename']
            self.search_results.sort(key=lambda x: x['grabs'], reverse=True)
            target_result = next((r for r in self.search_results if r['filename'] == target_filename), None)
            return target_result['command'] if target_result else None, target_filename
        except (ValueError, IndexError): return None, None

# --- MANAGER CLASS ---
class SessionManager:
    # ... (Most of this class is unchanged) ...
    def __init__(self):
        self._sessions = {}; self._hooks = {}; self.is_search_active = False
        self.irc_server_name = ""; self.irc_search_channel = ""; self.session_timeout = 0
        self.discord_api_base_url = ""; self.hot_list_completion_delay = 2000
    
    def load_config_values(self):
        self.irc_server_name = weechat.config_get_plugin("irc_server_name")
        self.irc_search_channel = weechat.config_get_plugin("irc_search_channel")
        self.discord_api_base_url = weechat.config_get_plugin("discord_api_base_url")
        try:
            self.session_timeout = int(weechat.config_get_plugin("session_timeout"))
            self.hot_list_completion_delay = int(weechat.config_get_plugin("hot_list_completion_delay"))
        except ValueError as e:
            log_error(f"Invalid integer in config: {e}. Using default values.")
            self.session_timeout = 300000; self.hot_list_completion_delay = 2000
        log_info(f"Configuration loaded. Timeout='{self.session_timeout}ms', HotListDelay='{self.hot_list_completion_delay}ms'")

    def start_new_session(self, session_id, query, session_type):
        session = XDCCSession(session_id, query, session_type)
        self._sessions[session_id] = session
        log_info(f"Starting new session. Type: '{session_type}', Query: '{query}', SID: {session_id}")
        server_buffer_ptr = weechat.info_get("irc_buffer", self.irc_server_name)
        if not server_buffer_ptr:
            log_error(f"Could not find server buffer for '{self.irc_server_name}'.")
            self.end_session(session_id, release_lock=True)
            self.send_error_to_frontend(session_id, f"Error: IRC server '{self.irc_server_name}' not found or connected.")
            return
        full_channel_name = f"{self.irc_server_name}.{self.irc_search_channel}"
        channel_buffer_ptr = weechat.buffer_search("irc", full_channel_name)
        if not channel_buffer_ptr:
            log_error(f"Could not find channel buffer '{full_channel_name}'.")
            self.end_session(session_id, release_lock=True)
            self.send_error_to_frontend(session_id, f"Error: IRC channel '{self.irc_search_channel}' not found or joined.")
            return
        self._hooks[session_id] = {'print_hook': weechat.hook_print(server_buffer_ptr, "irc_notice", "", 0, "global_print_cb", session_id)}
        if session_type == 'search':
            weechat.command(channel_buffer_ptr, f"!search {query}")
        elif session_type == 'hot':
            self._hooks[session_id]['completion_timer'] = weechat.hook_timer(self.hot_list_completion_delay, 0, 1, "global_final_processing_cb", session_id)
            weechat.command(channel_buffer_ptr, "!hot")

    def end_session(self, session_id, release_lock=False):
        if session_id in self._hooks:
            for hook_ptr in self._hooks[session_id].values():
                if hook_ptr: weechat.unhook(hook_ptr)
            self._hooks.pop(session_id)
        if session_id in self._sessions:
            log_info(f"Cleaning up data for session {session_id}.")
            self._sessions.pop(session_id)
        if release_lock: self.release_search_lock()

    def release_search_lock(self):
        if self.is_search_active:
            self.is_search_active = False; log_info("Search lock released.")

    def handle_print_callback(self, session_id, message):
        session = self._sessions.get(session_id)
        if not session: return weechat.WEECHAT_RC_OK
        clean_text = weechat.string_remove_color(message, "")
        if session.type == 'search':
            result_match = RESULT_LINE_REGEX.search(clean_text)
            end_match = END_OF_RESULTS_REGEX.search(clean_text)
            if result_match:
                session.add_search_result({"grabs": int(result_match.group(1)), "size": result_match.group(2).strip(), "filename": result_match.group(3).strip(), "command": result_match.group(4).strip()})
            if end_match:
                log_info(f"End of search results detected for session {session_id}.")
                if self._hooks[session_id].get('print_hook'): weechat.unhook(self._hooks[session_id].pop('print_hook'))
                self._hooks[session_id]['processing_timer'] = weechat.hook_timer(500, 0, 1, "global_final_processing_cb", session_id)
                self._hooks[session_id]['expiry_timer'] = weechat.hook_timer(self.session_timeout, 0, 1, "global_expiry_cb", session_id)
        elif session.type == 'hot':
            header_match = HOT_HEADER_REGEX.search(clean_text)
            result_match = HOT_RESULT_LINE_REGEX.search(clean_text)
            line_matched = False
            if header_match:
                session.hot_summary = f"{header_match.group(1).strip()} ¦ {header_match.group(2).strip()}"
                log_info(f"HOT PARSE: Matched header. Summary: '{session.hot_summary}'"); line_matched = True
            if result_match:
                item = {"grabs": int(result_match.group(1)), "category": result_match.group(2).strip(), "size": result_match.group(3).strip(), "filename": result_match.group(4).strip()}
                session.add_hot_item(item)
                log_info(f"HOT PARSE: Matched item. Grabs='{item['grabs']}', Cat='{item['category']}', Size='{item['size']}', File='{item['filename']}'"); line_matched = True
            if line_matched and self._hooks[session_id].get('completion_timer'):
                weechat.unhook(self._hooks[session_id]['completion_timer'])
                self._hooks[session_id]['completion_timer'] = weechat.hook_timer(self.hot_list_completion_delay, 0, 1, "global_final_processing_cb", session_id)
        return weechat.WEECHAT_RC_OK

    def handle_final_processing(self, session_id):
        session = self._sessions.get(session_id)
        if not session:
            log_error(f"handle_final_processing called for ended session {session_id}.")
            self.release_search_lock(); return weechat.WEECHAT_RC_OK
        if session.type == 'search' and self._hooks.get(session_id, {}).get('processing_timer'):
            weechat.unhook(self._hooks[session_id].pop('processing_timer'))
        elif session.type == 'hot' and self._hooks.get(session_id, {}).get('completion_timer'):
            weechat.unhook(self._hooks[session_id].pop('completion_timer'))
        if session.type == 'search':
            session.generate_choices()
            payload = {"session_id": session.id}
            if not session.choices:
                payload.update({"status": "no_results", "message": f"Search for '{session.query}' yielded no results."})
                self.end_session(session_id)
            else:
                payload.update({"status": "success", "message": f"Found {len(session.choices)} choices.", "choices": session.choices})
            self.send_webhook_to_frontend("search_results", payload)
        elif session.type == 'hot':
            payload = {"session_id": session.id}
            if not session.hot_items:
                payload.update({"status": "no_results", "message": "The '!hot' command returned no items."})
            else:
                payload.update({"status": "success", "summary": session.hot_summary, "items": session.hot_items})
            self.send_webhook_to_frontend("hot_results", payload)
            self.end_session(session_id)
        self.release_search_lock()
        return weechat.WEECHAT_RC_OK

    def send_webhook_to_frontend(self, endpoint, payload):
        if not self.discord_api_base_url:
            log_error("'discord_api_base_url' is not defined."); return
        api_url = f"{self.discord_api_base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        json_payload = json.dumps(payload)
        command = f"curl -X POST -H \"Content-Type: application/json\" --max-time 10 -d {shlex.quote(json_payload)} {api_url}"
        log_info(f"Sending webhook for session {payload.get('session_id', 'N/A')} to {api_url}")
        weechat.hook_process(command, 12000, "global_http_post_cb", payload.get('session_id', 'N/A'))

    def send_session_expired_to_frontend(self, session_id: str):
        payload = {"session_id": session_id, "status": "expired", "message": "This search session has expired due to inactivity."}
        self.send_webhook_to_frontend("session_expired", payload)

    # --- THIS IS THE FIX ---
    # Re-added the missing function
    def send_download_status_to_frontend(self, session_id: str, status: str, message: str):
        payload = {"session_id": session_id, "status": status, "message": message}
        self.send_webhook_to_frontend("download_status", payload)
    # --- END OF FIX ---

    def send_rejection_to_frontend(self, session_id: str):
        payload = {"session_id": session_id, "status": "rejected_busy", "message": "Another search is already in progress. Please try again."}
        self.send_webhook_to_frontend("search_results", payload)

    def send_error_to_frontend(self, session_id: str, error_message: str):
        payload = {"session_id": session_id, "status": "error", "message": error_message}
        self.send_webhook_to_frontend("search_results", payload)

    def handle_expiry(self, session_id):
        if session_id in self._sessions:
            log_info(f"Session '{session_id}' has expired and will be terminated.")
            self.send_session_expired_to_frontend(session_id)
            self.end_session(session_id)
        return weechat.WEECHAT_RC_OK
        
    def handle_http_post_callback(self, session_id, command, return_code, stdout, stderr):
        if return_code != 0:
            log_error(f"Failed to send webhook for session {session_id} (RC: {return_code}). Curl stderr: {stderr.strip()}")
        else:
            log_info(f"Webhook for session {session_id} sent successfully.")
        return weechat.WEECHAT_RC_OK

    def get_session(self, session_id):
        return self._sessions.get(session_id)

    def shutdown(self):
        log_info(f"Shutting down. Terminating {len(self._sessions)} active session(s)...")
        for session_id in list(self._sessions.keys()):
            self.end_session(session_id)
        self.release_search_lock()

SESSION_MANAGER = SessionManager()

def global_print_cb(data, buffer, date, tags, displayed, highlight, prefix, message): return SESSION_MANAGER.handle_print_callback(data, message)
def global_final_processing_cb(data, remaining_calls): return SESSION_MANAGER.handle_final_processing(data)
def global_expiry_cb(data, remaining_calls): return SESSION_MANAGER.handle_expiry(data)
def global_http_post_cb(data, cmd, rc, out, err): return SESSION_MANAGER.handle_http_post_callback(data, cmd, rc, out, err)

def service_search_cb(data, buffer, args):
    try: session_id, query = shlex.split(args)[0], " ".join(shlex.split(args)[1:])
    except (ValueError, IndexError):
        log_info("Usage: /autoxdcc_service_search <session_id> <query>"); return weechat.WEECHAT_RC_ERROR
    if SESSION_MANAGER.is_search_active:
        log_info(f"Rejecting search for '{query}' (SID: {session_id}). A search is already active.")
        SESSION_MANAGER.send_rejection_to_frontend(session_id); return weechat.WEECHAT_RC_OK
    SESSION_MANAGER.is_search_active = True
    log_info(f"Search lock acquired for search session {session_id}.")
    SESSION_MANAGER.start_new_session(session_id, query, session_type='search')
    return weechat.WEECHAT_RC_OK

def service_hot_cb(data, buffer, args):
    try: session_id = shlex.split(args)[0]
    except (ValueError, IndexError):
        log_info("Usage: /autoxdcc_service_hot <session_id>"); return weechat.WEECHAT_RC_ERROR
    if SESSION_MANAGER.is_search_active:
        log_info(f"Rejecting hot list request (SID: {session_id}). A search is already active.")
        SESSION_MANAGER.send_rejection_to_frontend(session_id); return weechat.WEECHAT_RC_OK
    SESSION_MANAGER.is_search_active = True
    log_info(f"Search lock acquired for hot list session {session_id}.")
    SESSION_MANAGER.start_new_session(session_id, query="", session_type='hot')
    return weechat.WEECHAT_RC_OK

def service_download_cb(data, buffer, args):
    try: parts = shlex.split(args); session_id, choice_id_str = parts[0], parts[1]
    except (ValueError, IndexError):
        log_info("Usage: /autoxdcc_service_download <session_id> <choice_id>"); return weechat.WEECHAT_RC_ERROR
    session = SESSION_MANAGER.get_session(session_id)
    if not session or session.type != 'search':
        msg = "Download failed: Session expired or is not a valid search session."
        log_info(f"Error: Session '{session_id}' is invalid for download request.")
        SESSION_MANAGER.send_download_status_to_frontend(session_id, "error", msg)
        return weechat.WEECHAT_RC_OK
    command, filename = session.get_download_command(choice_id_str)
    if command and filename:
        full_channel_name = f"{SESSION_MANAGER.irc_server_name}.{SESSION_MANAGER.irc_search_channel}"
        buffer_ptr = weechat.buffer_search("irc", full_channel_name)
        if buffer_ptr:
            weechat.command(buffer_ptr, command)
            SESSION_MANAGER.send_download_status_to_frontend(session_id, "success", f"Download command for **`{filename}`** sent.")
            SESSION_MANAGER.end_session(session_id)
        else:
            SESSION_MANAGER.send_download_status_to_frontend(session_id, "error", f"Download failed: WeeChat could not find the IRC channel buffer.")
    else:
        SESSION_MANAGER.send_download_status_to_frontend(session_id, "error", f"Download failed: Invalid choice ID '{choice_id_str}'.")
    return weechat.WEECHAT_RC_OK

def setup_plugin_config():
    log_info("Setting up plugin configuration options...")
    for name, default_value in DEFAULT_CONFIG_VALUES.items():
        if not weechat.config_is_set_plugin(name): weechat.config_set_plugin(name, default_value)
    log_info("Plugin configuration setup complete.")
    SESSION_MANAGER.load_config_values()

def shutdown_cb():
    SESSION_MANAGER.shutdown()
    log_info(f"{SCRIPT_NAME} unloaded."); return weechat.WEECHAT_RC_OK

if __name__ == "__main__":
    if weechat.register(SCRIPT_NAME, SCRIPT_AUTHOR, SCRIPT_VERSION, SCRIPT_LICENSE, SCRIPT_DESC, "shutdown_cb", ""):
        setup_plugin_config()
        weechat.hook_command("autoxdcc_service_search", "Starts an XDCC search", "", "", "", "service_search_cb", "")
        weechat.hook_command("autoxdcc_service_hot", "Starts a hot files listing", "", "", "", "service_hot_cb", "")
        weechat.hook_command("autoxdcc_service_download", "Downloads a file by choice ID", "", "", "", "service_download_cb", "")
        log_info(f"Autoxdcc WeeChat backend (v{SCRIPT_VERSION}) loaded and ready.")
