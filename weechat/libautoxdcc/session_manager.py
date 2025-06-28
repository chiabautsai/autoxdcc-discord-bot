# weechat/libautoxdcc/session_manager.py

import weechat
import shlex
from typing import Dict, Any, Optional

from . import utils
from . import models
from . import irc_parser
from . import webhook_sender


class SessionManager:
    """
    Manages all active XDCC search and hot list sessions.
    Handles session creation, termination, IRC message parsing,
    and delegation to webhook sending.
    """
    def __init__(self, irc_server_name: str, irc_search_channel: str, 
                 session_timeout: int, discord_api_base_url: str,
                 hot_list_completion_delay: int):
        
        self._sessions: Dict[str, models.XDCCSession] = {} # Stores active sessions
        self._hooks: Dict[str, Dict[str, Any]] = {}       # Stores WeeChat hook pointers per session
        self.is_search_active: bool = False                # Global lock for search/hot commands

        # Configuration loaded from WeeChat settings
        self.irc_server_name = irc_server_name
        self.irc_search_channel = irc_search_channel
        self.session_timeout = session_timeout
        self.hot_list_completion_delay = hot_list_completion_delay
        
        # Initialize the WebhookSender with the base URL
        self.webhook_sender = webhook_sender.WebhookSender(discord_api_base_url)

    def start_new_session(self, session_id: str, query: str, session_type: str):
        """
        Initiates a new search or hot list session.
        Registers WeeChat hooks and sends the initial IRC command.
        """
        session = models.XDCCSession(session_id, query, session_type)
        self._sessions[session_id] = session
        
        utils.log_info(f"Starting new session. Type: '{session_type}', Query: '{query}', SID: {session_id}")

        server_buffer_ptr = weechat.info_get("irc_buffer", self.irc_server_name)
        if not server_buffer_ptr:
            utils.log_error(f"Could not find server buffer for '{self.irc_server_name}'.")
            self.end_session(session_id, release_lock=True)
            self.webhook_sender.send_error(session_id, f"Error: IRC server '{self.irc_server_name}' not found or connected.")
            return

        full_channel_name = f"{self.irc_server_name}.{self.irc_search_channel}"
        channel_buffer_ptr = weechat.buffer_search("irc", full_channel_name)
        if not channel_buffer_ptr:
            utils.log_error(f"Could not find channel buffer '{full_channel_name}'.")
            self.end_session(session_id, release_lock=True)
            self.webhook_sender.send_error(session_id, f"Error: IRC channel '{self.irc_search_channel}' not found or joined.")
            return
        
        # Hook print messages on the server buffer to capture bot responses
        self._hooks[session_id] = {'print_hook': weechat.hook_print(server_buffer_ptr, "irc_notice", "", 0, "global_print_cb", session_id)}
        
        if session_type == 'search':
            weechat.command(channel_buffer_ptr, f"!search {query}")
            # Start expiry timer for search sessions immediately
            self._hooks[session_id]['expiry_timer'] = weechat.hook_timer(self.session_timeout, 0, 1, "global_expiry_cb", session_id)
        elif session_type == 'hot':
            # For 'hot' lists with no explicit end, start a timer that gets reset on each valid line.
            # When the timer finally fires, we assume the list is complete.
            self._hooks[session_id]['completion_timer'] = weechat.hook_timer(self.hot_list_completion_delay, 0, 1, "global_final_processing_cb", session_id)
            weechat.command(channel_buffer_ptr, "!hot")

    def end_session(self, session_id: str, release_lock: bool = False):
        """
        Cleans up a session by unhooking WeeChat hooks and removing session data.
        Optionally releases the global search lock.
        """
        if session_id in self._hooks:
            for hook_ptr in self._hooks[session_id].values():
                if hook_ptr: weechat.unhook(hook_ptr)
            self._hooks.pop(session_id)
        if session_id in self._sessions:
            utils.log_info(f"Cleaning up data for session {session_id}.")
            self._sessions.pop(session_id)
        if release_lock:
            self.release_search_lock()

    def release_search_lock(self):
        """Releases the global lock, allowing new search/hot commands."""
        if self.is_search_active:
            self.is_search_active = False
            utils.log_info("Search lock released.")

    def handle_print_callback(self, session_id: str, message: str) -> int:
        """
        Processes incoming IRC messages based on the session type.
        Delegates parsing to irc_parser module.
        """
        session = self._sessions.get(session_id)
        if not session: return weechat.WEECHAT_RC_OK # Session already ended or invalid

        clean_text = weechat.string_remove_color(message, "")
        
        if session.type == 'search':
            result_dict = irc_parser.parse_search_result_line(clean_text)
            is_end = irc_parser.is_end_of_search_results(clean_text)
            
            if result_dict:
                session.add_search_result(result_dict)
            
            if is_end:
                utils.log_info(f"End of search results detected for session {session_id}.")
                # Unhook print hook immediately for search sessions once end is detected
                if self._hooks[session_id].get('print_hook'): weechat.unhook(self._hooks[session_id].pop('print_hook'))
                # Trigger final processing via a short timer to allow all prints to finish
                self._hooks[session_id]['processing_timer'] = weechat.hook_timer(500, 0, 1, "global_final_processing_cb", session_id)

        elif session.type == 'hot':
            header_summary = irc_parser.parse_hot_header_line(clean_text)
            hot_item_dict = irc_parser.parse_hot_item_line(clean_text)
            
            line_matched = False
            if header_summary:
                session.hot_summary = header_summary
                utils.log_info(f"HOT PARSE: Matched header. Summary: '{session.hot_summary}'")
                line_matched = True
            if hot_item_dict:
                session.add_hot_item(hot_item_dict)
                utils.log_info(f"HOT PARSE: Matched item. Grabs='{hot_item_dict['grabs']}', Cat='{hot_item_dict['category']}', Size='{hot_item_dict['size']}', File='{hot_item_dict['filename']}'")
                line_matched = True
            
            # If any relevant line was matched, reset the completion timer
            if line_matched and self._hooks[session_id].get('completion_timer'):
                weechat.unhook(self._hooks[session_id]['completion_timer'])
                self._hooks[session_id]['completion_timer'] = weechat.hook_timer(self.hot_list_completion_delay, 0, 1, "global_final_processing_cb", session_id)

        return weechat.WEECHAT_RC_OK

    def handle_final_processing(self, session_id: str) -> int:
        """
        Finalizes a session after all IRC messages are received.
        Generates choices for search results or sends hot list items.
        """
        session = self._sessions.get(session_id)
        if not session:
            utils.log_error(f"handle_final_processing called for ended session {session_id}.")
            self.release_search_lock() # Ensure lock is released even if session vanished
            return weechat.WEECHAT_RC_OK
            
        # Clean up the timer that triggered this final processing.
        # This covers both 'processing_timer' for search and 'completion_timer' for hot.
        if self._hooks.get(session_id, {}).get('processing_timer'):
            weechat.unhook(self._hooks[session_id].pop('processing_timer'))
        if self._hooks.get(session_id, {}).get('completion_timer'):
            weechat.unhook(self._hooks[session_id].pop('completion_timer'))
        
        if session.type == 'search':
            session.generate_choices()
            if not session.choices:
                self.webhook_sender.send_search_results(session.id, "no_results", f"Search for '{session.query}' yielded no results.")
                self.end_session(session_id) # No expiry timer needed if no results
            else:
                self.webhook_sender.send_search_results(session.id, "success", f"Found {len(session.choices)} choices.", 
                                                         choices=[{"choice_id": c['choice_id'], "filename": c['filename'], "size": c['size']} for c in session.choices])
            
        elif session.type == 'hot':
            if not session.hot_items:
                self.webhook_sender.send_hot_results(session.id, "no_results", message="The '!hot' command returned no items.")
            else:
                # Send the raw items, frontend will handle filtering and top 5
                self.webhook_sender.send_hot_results(session.id, "success", summary=session.hot_summary, 
                                                     items=[{"grabs": item['grabs'], "category": item['category'], "size": item['size'], "filename": item['filename']} for item in session.hot_items])
            # A 'hot' session is considered complete after sending results, so terminate it.
            self.end_session(session_id)

        self.release_search_lock()
        return weechat.WEECHAT_RC_OK

    def handle_expiry(self, session_id: str) -> int:
        """Handles session expiry, sending a notification and cleaning up."""
        if session_id in self._sessions:
            utils.log_info(f"Session '{session_id}' has expired and will be terminated.")
            self.webhook_sender.send_session_expired(session_id, "This search session has expired due to inactivity.")
            self.end_session(session_id)
        return weechat.WEECHAT_RC_OK
        
    def handle_http_post_callback(self, session_id: str, command: str, return_code: int, stdout: str, stderr: str) -> int:
        """
        Callback for WeeChat's hook_process, used for HTTP POST results.
        Logs success or failure of webhook sending.
        """
        if return_code != 0:
            utils.log_error(f"Failed to send webhook for session {session_id} (RC: {return_code}). Curl stderr: {stderr.strip()}")
        else:
            utils.log_info(f"Webhook for session {session_id} sent successfully.")
        return weechat.WEECHAT_RC_OK

    def get_session(self, session_id: str) -> Optional[models.XDCCSession]:
        """Retrieves an active session by its ID."""
        return self._sessions.get(session_id)

    def shutdown(self):
        """Cleans up all active sessions during script unload."""
        utils.log_info(f"Shutting down. Terminating {len(self._sessions)} active session(s)...")
        for session_id in list(self._sessions.keys()): # Iterate over a copy as end_session modifies the dict
            self.end_session(session_id)
        self.release_search_lock()


# --- COMMAND HANDLER WRAPPERS ---
# These functions are called directly by WeeChat's hook_command.
# They accept the SESSION_MANAGER instance to call its methods.

def service_search_cb(data, buffer, args, session_manager_instance: SessionManager) -> int:
    """Wrapper for the /autoxdcc_service_search command."""
    try:
        parts = shlex.split(args)
        session_id, query = parts[0], " ".join(parts[1:])
    except (ValueError, IndexError):
        utils.log_info("Usage: /autoxdcc_service_search <session_id> <query>")
        return weechat.WEECHAT_RC_ERROR
    
    if session_manager_instance.is_search_active:
        utils.log_info(f"Rejecting search for '{query}' (SID: {session_id}). A search is already active.")
        session_manager_instance.webhook_sender.send_rejection(session_id, "Another search is already in progress. Please try again.")
        return weechat.WEECHAT_RC_OK
    
    session_manager_instance.is_search_active = True
    utils.log_info(f"Search lock acquired for search session {session_id}.")
    session_manager_instance.start_new_session(session_id, query, session_type='search')
    return weechat.WEECHAT_RC_OK

def service_hot_cb(data, buffer, args, session_manager_instance: SessionManager) -> int:
    """Wrapper for the /autoxdcc_service_hot command."""
    try:
        session_id = shlex.split(args)[0]
    except (ValueError, IndexError):
        utils.log_info("Usage: /autoxdcc_service_hot <session_id>")
        return weechat.WEECHAT_RC_ERROR
    
    if session_manager_instance.is_search_active:
        utils.log_info(f"Rejecting hot list request (SID: {session_id}). A search is already active.")
        # Rejection for /hot also uses search_results endpoint to ensure Discord frontend correctly handles it.
        session_manager_instance.webhook_sender.send_rejection(session_id, "Another search is already in progress. Please try again.")
        return weechat.WEECHAT_RC_OK

    session_manager_instance.is_search_active = True
    utils.log_info(f"Search lock acquired for hot list session {session_id}.")
    session_manager_instance.start_new_session(session_id, query="", session_type='hot')
    return weechat.WEECHAT_RC_OK

def service_download_cb(data, buffer, args, session_manager_instance: SessionManager) -> int:
    """Wrapper for the /autoxdcc_service_download command."""
    try:
        parts = shlex.split(args)
        session_id, choice_id_str = parts[0], parts[1]
    except (ValueError, IndexError):
        utils.log_info("Usage: /autoxdcc_service_download <session_id> <choice_id>");
        return weechat.WEECHAT_RC_ERROR
    
    session = session_manager_instance.get_session(session_id)
    if not session or session.type != 'search':
        msg = "Download failed: Session expired or is not a valid search session. Please search again."
        utils.log_info(f"Error: Session '{session_id}' is invalid for download request or expired.")
        session_manager_instance.webhook_sender.send_download_status(session_id, "error", msg)
        return weechat.WEECHAT_RC_OK
    
    command_to_run, target_filename = session.get_download_command(choice_id_str)
    if command_to_run and target_filename:
        full_channel_name = f"{session_manager_instance.irc_server_name}.{session_manager_instance.irc_search_channel}"
        channel_buffer_ptr = weechat.buffer_search("irc", full_channel_name)
        if channel_buffer_ptr:
            utils.log_info(f"Executing download for session {session_id}, choice {choice_id_str}: {command_to_run}")
            weechat.command(channel_buffer_ptr, command_to_run)
            session_manager_instance.webhook_sender.send_download_status(session_id, "success", f"Download command for **`{target_filename}`** (Choice #{choice_id_str}) sent to IRC.")
            session_manager_instance.end_session(session_id) # The search session is now complete.
        else:
            msg = f"Download failed: WeeChat could not find the IRC channel '{full_channel_name}' to send the command."
            utils.log_error(msg)
            session_manager_instance.webhook_sender.send_download_status(session_id, "error", msg)
    else:
        msg = f"Download failed: Invalid choice ID '{choice_id_str}' for session {session_id}. Please select from available options."
        utils.log_info(msg)
        session_manager_instance.webhook_sender.send_download_status(session_id, "error", msg)
    return weechat.WEECHAT_RC_OK
