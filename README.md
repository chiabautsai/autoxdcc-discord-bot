# AutoXDCC Discord Bot

A two-part system for searching and downloading files from XDCC bots via a Discord interface.

## Components

*   **/bot**: The Python-based Discord bot and webhook server.
*   **/weechat**: The backend script that runs in WeeChat to handle searches and downloads.
*   **/systemd**: A service file for running the bot as a persistent service on Linux.

## Setup

1.  Configure the WeeChat script.
2.  Set up the bot's virtual environment and install dependencies from `bot/requirements.txt`.
3.  Create a `.env` file based on the `.env.example` template.
4.  Configure and start the `systemd` service.
