import weechat

def poc_message():
    """Returns a simple message from the dummy module."""
    return "Hello from dummy_module!"

def print_from_dummy():
    """Prints a message directly from the dummy module using weechat.prnt."""
    weechat.prnt("", "Dummy module says: This message was printed from within libautoxdcc/dummy_module.py!")

dummy_variable = "I am a variable in dummy_module."
