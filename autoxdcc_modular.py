# -*- coding: utf-8 -*-
#
# autoxdcc_modular.py - WeeChat backend service for XDCC searching and downloading.
#
# --- HISTORY ---
# 2023-10-28: Version 9.0, Added API webhook for frontend communication.
#                        - On search completion, script now sends results via an HTTP POST request.
#                        - Added 'api_endpoint_url' to the configuration.
#                        - Implemented a non-blocking HTTP call using weechat.hook_process and curl.
#                        - Added a callback to log the success or failure of the API call.
# 2023-10-27: Version 8.3, Implemented automatic session expiry.
# 2023-10-27: Version 8.2, Fixed incomplete shutdown cleanup flaw.
# 2023-10-27: Version 8.1, Fixed ambiguous download flaw.
# 2023-10-27: Version 8.0, Fixed concurrency flaw by removing global state.
#

import weechat
import re
import shlex
import json

# --- SCRIPT METADATA ---
SCRIPT_NAME = "autoxdcc_modular"
SCRIPT_AUTHOR = "Me"
SCRIPT_VERSION = "9.0"
SCRIPT_LICENSE = "MIT"
SCRIPT_DESC = "Hardened backend service for XDCC search and download with API webhook"

# --- CONFIGURATION ---
SCRIPT_CONFIG = {
    "server_name": "YOURSERVERNAME",
    "search_channel": "YOURCHANNELNAME",
    "session_timeout": 300000,  # 300,000 ms = 5 minutes
    "api_endpoint_url": "http://localhost:8000/search_results"
}

# --- REGEX CONSTANTS ---
IRC_CODES_REGEX = re.compile(r'(\x03\d{0,2}(,\d{1,2})?|\x02|\x0f|\x1d|\x1f|\x16)')
RESULT_LINE_REGEX = re.compile(r'\(\s*(\d+)x\s*\[(.*?)]\s*(.*?)\s*\)\s*\(\s*(/msg\s+.*?xdcc\s+send\s+#\d+)\s*\)')
END_OF_RESULTS_REGEX = re.compile(r'(\d+)\s+Results\s+Found')

def log_info(message):
    weechat.prnt("", f"{weechat.color('chat_prefix_weechat')}[{SCRIPT_NAME}] {message}")

def log_error(message):
    weechat.prnt("", f"{weechat.color('chat_prefix_error')}[{SCRIPT_NAME}] {message}")

# --- DATA CLASS ---
class XDCCSearchSession:
    # ... (class code remains identical to version 8.3) ...
    def __init__(self, session_id, search_query, search_buffer_ptr):
        self.id = session_id; self.query = search_query; self.buffer_ptr = search_buffer_ptr; self.results = []; self.choices = []
    def add_result(self, result_dict): self.results.append(result_dict)
    def generate_choices(self):
        self.results.sort(key=lambda x: x['grabs'], reverse=True)
        unique_filenames = list(dict.fromkeys(r['filename'] for r in self.results))
        for i, filename in enumerate(unique_filenames):
            best_result = next(r for r in self.results if r['filename'] == filename)
            self.choices.append({ "choice_id": i + 1, "filename": filename, "size": best_result['size'] })
    def get_download_command(self, choice_id):
        try:
            choice_id = int(choice_id)
            target_choice = next((c for c in self.choices if c['choice_id'] == choice_id), None)
            if not target_choice: return None
            target_filename = target_choice['filename']
            self.results.sort(key=lambda x: x['grabs'], reverse=True)
            target_result = next((r for r in self.results if r['filename'] == target_filename), None)
            return target_result['command'] if target_result else None
        except (ValueError, IndexError): return None

# --- MANAGER CLASS ---
class SessionManager:
    def __init__(self): self._sessions = {}; self._hooks = {}

    def start_new_session(self, session_id, query, buffer_ptr):
        if session_id in self._sessions:
            log_info(f"Warning: A session with ID '{session_id}' already exists. It will be overwritten.")
            self.end_session(session_id)
        session = XDCCSearchSession(session_id, query, buffer_ptr)
        self._sessions[session_id] = session
        log_info(f"Starting search for: '{query}' (Session ID: {session_id})")
        signal_name = f"{SCRIPT_CONFIG['server_name']},irc_in2_NOTICE"
        self._hooks[session_id] = {
            'signal': weechat.hook_signal(signal_name, "global_signal_cb", session_id)
        }
        weechat.command(buffer_ptr, f"!search {query}")

    def end_session(self, session_id):
        if session_id in self._hooks:
            for hook_type, hook_ptr in self._hooks[session_id].items():
                weechat.unhook(hook_ptr)
            self._hooks.pop(session_id)
        if session_id in self._sessions:
            self._sessions.pop(session_id)

    def handle_signal(self, session_id, signal_data):
        session = self._sessions.get(session_id)
        if not session: return weechat.WEECHAT_RC_OK
        parsed_data = weechat.info_get_hashtable("irc_message_parse", {"message": signal_data})
        raw_text = parsed_data.get("text", "")
        if not raw_text: return weechat.WEECHAT_RC_OK
        clean_text = IRC_CODES_REGEX.sub('', raw_text)
        if END_OF_RESULTS_REGEX.search(clean_text):
            weechat.unhook(self._hooks[session_id].pop('signal'))
            self._hooks[session_id]['expiry_timer'] = weechat.hook_timer(
                SCRIPT_CONFIG['session_timeout'], 0, 1, "global_expiry_cb", session_id
            )
            self._hooks[session_id]['processing_timer'] = weechat.hook_timer(500, 0, 1, "global_final_processing_cb", session_id)
        result_match = RESULT_LINE_REGEX.search(clean_text)
        if result_match:
            session.add_result({ "grabs": int(result_match.group(1)), "size": result_match.group(2).strip(), "filename": result_match.group(3).strip(), "command": result_match.group(4).strip() })
        return weechat.WEECHAT_RC_OK

    # MODIFICATION: This function now sends the results to the frontend via HTTP POST
    def handle_final_processing(self, session_id):
        session = self._sessions.get(session_id)
        if not session: return weechat.WEECHAT_RC_OK
        
        session.generate_choices()
        
        # Unhook the processing timer, it has served its purpose
        if session_id in self._hooks and 'processing_timer' in self._hooks[session_id]:
            weechat.unhook(self._hooks[session_id].pop('processing_timer'))

        payload = { "session_id": session_id }
        if not session.choices:
            log_info(f"Search complete for session {session_id}. No results found.")
            payload["status"] = "no_results"
            payload["message"] = f"Search for '{session.query}' yielded no results."
            self.end_session(session_id) # End session immediately if no results
        else:
            timeout_min = SCRIPT_CONFIG['session_timeout'] / 60000
            log_info(f"Search complete for session {session_id}. Found {len(session.choices)} choices.")
            log_info(f"This session will expire in {timeout_min:.1f} minutes.")
            for choice in session.choices:
                log_info(f"  [Choice {choice['choice_id']}] [{choice['size']}] {choice['filename']}")
            
            payload["status"] = "success"
            payload["message"] = f"Search for '{session.query}' found {len(session.choices)} choices."
            payload["choices"] = session.choices

        self.send_results_to_frontend(session_id, payload)
        return weechat.WEECHAT_RC_OK

    # MODIFICATION: New function to handle the API call
    def send_results_to_frontend(self, session_id, payload):
        api_url = SCRIPT_CONFIG.get("api_endpoint_url")
        if not api_url:
            log_error("'api_endpoint_url' is not defined in the script configuration. Cannot send results.")
            return

        json_payload = json.dumps(payload)
        # Use shlex.quote for safety, although hook_process is generally safe.
        command = f"curl -X POST -H \"Content-Type: application/json\" --max-time 10 -d {shlex.quote(json_payload)} {api_url}"
        
        log_info(f"Sending results for session {session_id} to {api_url}")
        weechat.hook_process(command, 12000, "global_http_post_cb", session_id)


    def handle_expiry(self, session_id):
        if session_id in self._sessions:
            log_info(f"Session '{session_id}' has expired and will be terminated.")
            self.end_session(session_id)
        return weechat.WEECHAT_RC_OK
        
    # MODIFICATION: New handler for the HTTP process callback
    def handle_http_post_callback(self, session_id, command, return_code, stdout, stderr):
        if return_code == 0:
            log_info(f"Successfully sent results for session {session_id} to frontend.")
        else:
            log_error(f"Failed to send results for session {session_id} to frontend (RC: {return_code}).")
            if stderr:
                log_error(f"API call STDERR: {stderr}")
            if stdout:
                log_error(f"API call STDOUT: {stdout}")
        return weechat.WEECHAT_RC_OK


    def get_session(self, session_id): return self._sessions.get(session_id)
    def shutdown(self):
        log_info(f"Shutting down. Terminating {len(self._sessions)} active session(s)...")
        for session_id in list(self._sessions.keys()):
            self.end_session(session_id)

# --- SINGLETON INSTANCE ---
SESSION_MANAGER = SessionManager()

# --- GLOBAL CALLBACKS ---
def global_signal_cb(data, signal, signal_data): SESSION_MANAGER.handle_signal(data, signal_data); return weechat.WEECHAT_RC_OK
def global_final_processing_cb(data, rem): SESSION_MANAGER.handle_final_processing(data); return weechat.WEECHAT_RC_OK
def global_expiry_cb(data, remaining_calls): SESSION_MANAGER.handle_expiry(data); return weechat.WEECHAT_RC_OK
# MODIFICATION: New trampoline for the HTTP POST callback
def global_http_post_cb(data, command, return_code, stdout, stderr): SESSION_MANAGER.handle_http_post_callback(data, command, return_code, stdout, stderr); return weechat.WEECHAT_RC_OK


# --- WEECHAT COMMANDS ---
def find_buffer_case_insensitive(plugin, name):
    infolist = weechat.infolist_get("buffer", "", ""); ptr = None
    if infolist:
        while weechat.infolist_next(infolist):
            if weechat.infolist_string(infolist, "plugin_name") == plugin and \
               weechat.infolist_string(infolist, "name").lower() == name.lower():
                ptr = weechat.infolist_pointer(infolist, "pointer"); break
        weechat.infolist_free(infolist)
    return ptr

def service_search_cb(data, buffer, args):
    try: parts = shlex.split(args); session_id, query = parts[0], " ".join(parts[1:])
    except: log_info("Usage: /autoxdcc_service_search <session_id> <query>"); return weechat.WEECHAT_RC_ERROR
    target_buffer_name = f"{SCRIPT_CONFIG['server_name']}.{SCRIPT_CONFIG['search_channel']}"
    search_buffer_ptr = find_buffer_case_insensitive("irc", target_buffer_name)
    if not search_buffer_ptr: log_info(f"Error: Could not find '{target_buffer_name}'."); return weechat.WEECHAT_RC_ERROR
    SESSION_MANAGER.start_new_session(session_id, query, search_buffer_ptr)
    return weechat.WEECHAT_RC_OK

def service_download_cb(data, buffer, args):
    try: parts = shlex.split(args); session_id, choice_id = parts[0], parts[1]
    except: log_info("Usage: /autoxdcc_service_download <session_id> <choice_id>"); return weechat.WEECHAT_RC_ERROR
    session = SESSION_MANAGER.get_session(session_id)
    if not session: log_info(f"Error: Session '{session_id}' is invalid or has expired."); return weechat.WEECHAT_RC_ERROR
    command_to_run = session.get_download_command(choice_id)
    if command_to_run:
        log_info(f"Executing download for session {session_id}, choice {choice_id}: {command_to_run}")
        weechat.command(session.buffer_ptr, command_to_run)
        log_info(f"Session {session_id} has ended.")
        SESSION_MANAGER.end_session(session_id) # End session on successful download
    else: log_info(f"Error: Invalid choice_id '{choice_id}' for session {session_id}.")
    return weechat.WEECHAT_RC_OK

def shutdown_cb(): SESSION_MANAGER.shutdown(); return weechat.WEECHAT_RC_OK

if __name__ == "__main__":
    if weechat.register(SCRIPT_NAME, SCRIPT_AUTHOR, SCRIPT_VERSION, SCRIPT_LICENSE, SCRIPT_DESC, "shutdown_cb", ""):
        weechat.hook_command("autoxdcc_service_search", "Starts an XDCC search", "<session_id> <query>", "", "", "service_search_cb", "")
        weechat.hook_command("autoxdcc_service_download", "Downloads a file by choice ID", "<session_id> <choice_id>", "", "", "service_download_cb", "")
        log_info("Hardened backend service loaded with API webhook.")
