# weechat/libautoxdcc/models.py

from typing import Optional, List # <--- ADDED THIS IMPORT

class XDCCSession:
    """
    Represents an active search or hot list session for a Discord user.
    Stores session-specific data and results.
    """
    def __init__(self, session_id: str, query: str, session_type: str):
        self.id = session_id
        self.query = query
        self.type = session_type # 'search' or 'hot'
        
        # For 'search' type sessions
        self.search_results = [] # Raw parsed results from IRC for search
        self.choices = []        # Curated choices for Discord download buttons

        # For 'hot' type sessions
        self.hot_summary = ""    # The header line from the !hot output
        self.hot_items = []      # Parsed individual items from the !hot list

    def add_search_result(self, result_dict: dict):
        """Adds a parsed search result to the session."""
        self.search_results.append(result_dict)

    def add_hot_item(self, item_dict: dict):
        """Adds a parsed hot list item to the session."""
        self.hot_items.append(item_dict)

    def generate_choices(self):
        """
        Generates the curated choices for search results, sorting by grabs
        and ensuring unique filenames.
        """
        self.search_results.sort(key=lambda x: x['grabs'], reverse=True)
        unique_filenames = list(dict.fromkeys(r['filename'] for r in self.search_results))
        for i, filename in enumerate(unique_filenames):
            # Find the best result for this unique filename (highest grabs)
            best_result = next(r for r in self.search_results if r['filename'] == filename)
            self.choices.append({
                "choice_id": i + 1,
                "filename": filename,
                "size": best_result['size']
            })

    def get_download_command(self, choice_id: str) -> tuple[Optional[str], Optional[str]]:
        """
        Retrieves the IRC download command and filename for a given choice ID.
        Returns (command_string, filename) or (None, None) if not found.
        """
        try:
            choice_id_int = int(choice_id)
            target_choice = next((c for c in self.choices if c['choice_id'] == choice_id_int), None)
            if not target_choice:
                return None, None
            
            target_filename = target_choice['filename']
            # Re-sort to ensure we get the best (highest grabs) command for this filename
            self.search_results.sort(key=lambda x: x['grabs'], reverse=True)
            target_result = next((r for r in self.search_results if r['filename'] == target_filename), None)
            
            return target_result['command'] if target_result else None, target_filename
        except (ValueError, IndexError):
            return None, None
