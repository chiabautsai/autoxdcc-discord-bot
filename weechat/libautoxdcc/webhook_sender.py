# weechat/libautoxdcc/webhook_sender.py

import weechat
import json
import shlex
from typing import Dict, Any, List, Optional # <--- ADDED THIS IMPORT

from . import utils # Import local utility functions

class WebhookSender:
    """
    Manages sending structured data via webhooks to the Discord bot's FastAPI server.
    """
    def __init__(self, discord_api_base_url: str):
        self.discord_api_base_url = discord_api_base_url

    def _send_webhook(self, endpoint: str, payload: Dict[str, Any], session_id: str = "N/A"):
        """
        Internal helper to send a generic webhook using curl via WeeChat's hook_process.
        """
        if not self.discord_api_base_url:
            utils.log_error("'discord_api_base_url' is not defined in WeeChat config. Cannot send webhook.")
            return

        api_url = f"{self.discord_api_base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        json_payload = json.dumps(payload)
        
        # Use shlex.quote to safely handle the JSON payload in the curl command
        command = f"curl -X POST -H \"Content-Type: application/json\" --max-time 10 -d {shlex.quote(json_payload)} {api_url}"
        
        utils.log_info(f"Sending webhook for session {session_id} to {api_url} with payload: {json_payload[:100]}...") # Log truncated payload
        
        # 'global_http_post_cb' is a global function in autoxdcc.py that WeeChat calls back to.
        # We pass the session_id as 'data' so the callback knows which session the webhook belongs to.
        weechat.hook_process(command, 12000, "global_http_post_cb", session_id)

    def send_search_results(self, session_id: str, status: str, message: str, choices: Optional[List[Dict[str, Any]]] = None):
        """Sends search results (success, no_results, rejected_busy, error) to the frontend."""
        payload = {
            "session_id": session_id,
            "status": status,
            "message": message,
            "choices": choices
        }
        self._send_webhook("search_results", payload, session_id)

    def send_hot_results(self, session_id: str, status: str, summary: Optional[str] = None, items: Optional[List[Dict[str, Any]]] = None):
        """Sends hot list results (success, no_results) to the frontend."""
        payload = {
            "session_id": session_id,
            "status": status,
            "summary": summary,
            "items": items
        }
        self._send_webhook("hot_results", payload, session_id)

    def send_download_status(self, session_id: str, status: str, message: str):
        """Sends download status (success, error) to the frontend."""
        payload = {
            "session_id": session_id,
            "status": status,
            "message": message
        }
        self._send_webhook("download_status", payload, session_id)

    def send_session_expired(self, session_id: str, message: str):
        """Notifies the frontend that a session has expired."""
        payload = {
            "session_id": session_id,
            "status": "expired",
            "message": message
        }
        self._send_webhook("session_expired", payload, session_id)

    def send_rejection(self, session_id: str, message: str):
        """Sends a rejection message, typically when service is busy."""
        payload = {
            "session_id": session_id,
            "status": "rejected_busy",
            "message": message
        }
        self._send_webhook("search_results", payload, session_id) # Using search_results endpoint for busy status

    def send_error(self, session_id: str, error_message: str):
        """Sends a generic error message to the frontend."""
        payload = {
            "session_id": session_id,
            "status": "error",
            "message": error_message
        }
        self._send_webhook("search_results", payload, session_id)
