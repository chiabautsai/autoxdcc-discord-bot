# weechat/libautoxdcc/irc_parser.py

import re
from typing import Optional, Dict

# --- REGEX CONSTANTS ---
# For !search results: ( 1x [2.3G] Some.File.Name.mkv ) (/msg Bot xdcc send #123)
# Group 1: grabs, Group 2: size, Group 3: filename, Group 4: command
RESULT_LINE_REGEX = re.compile(r'\(\s*(\d+)x\s*\[(.*?)]\s*(.*?)\s*\)\s*\(\s*(/msg\s+.*?xdcc\s+send\s+#\d+)\s*\).*')

# For !search end of results: ( 6 Results Found - 64 Gets )
END_OF_RESULTS_REGEX = re.compile(r'\( (\d+) Result(s)? Found - \d+ Gets \)')

# For !hot results header: #THE.SOURCE - ALL SECTIONS ¦ TOP GETS OF THE LAST 2 DAYS ¦ 536 NEW RELEASES, 4481 GETS
# Group 1: Left part of summary (e.g., "TOP GETS OF THE LAST 2 DAYS")
# Group 2: Right part of summary (e.g., "536 NEW RELEASES, 4481 GETS")
HOT_HEADER_REGEX = re.compile(r'#THE\.SOURCE.*?¦\s*(.*?)\s*¦\s*(.*)')

# For !hot result item: 68x | TV-X265 [564M] Squid.Game.S03E01.1080p.HEVC.x265-MeGusta
# Group 1: grabs, Group 2: category, Group 3: size, Group 4: filename
HOT_RESULT_LINE_REGEX = re.compile(r'(\d+)x\s*\|\s+([\w\.-]+)\s+\[(.*?)]\s+(.*)')


def parse_search_result_line(line: str) -> Optional[Dict[str, any]]:
    """
    Parses a single line from a '!search' command output.
    Returns a dictionary if matched, None otherwise.
    """
    match = RESULT_LINE_REGEX.search(line)
    if match:
        return {
            "grabs": int(match.group(1)),
            "size": match.group(2).strip(),
            "filename": match.group(3).strip(),
            "command": match.group(4).strip()
        }
    return None

def is_end_of_search_results(line: str) -> bool:
    """
    Checks if a line indicates the end of a '!search' command output.
    Returns True if matched, False otherwise.
    """
    return END_OF_RESULTS_REGEX.search(line) is not None

def parse_hot_header_line(line: str) -> Optional[str]:
    """
    Parses the header line from a '!hot' command output.
    Returns the formatted summary string if matched, None otherwise.
    """
    match = HOT_HEADER_REGEX.search(line)
    if match:
        return f"{match.group(1).strip()} ¦ {match.group(2).strip()}"
    return None

def parse_hot_item_line(line: str) -> Optional[Dict[str, any]]:
    """
    Parses a single item line from a '!hot' command output.
    Returns a dictionary if matched, None otherwise.
    """
    match = HOT_RESULT_LINE_REGEX.search(line)
    if match:
        return {
            "grabs": int(match.group(1)),
            "category": match.group(2).strip(),
            "size": match.group(3).strip(),
            "filename": match.group(4).strip()
        }
    return None
