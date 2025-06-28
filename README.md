# AutoXDCC Discord Bot

A two-part system for searching and downloading files from XDCC bots via a Discord interface.

## Install

Follow these steps to get the AutoXDCC bot up and running:

1.  **Clone the Repository:**
    Start by cloning the project from its Git repository to your desired location:
    ```bash
    git clone https://github.com/chiabautsai/autoxdcc-discord-bot.git
    cd autoxdcc-discord-bot
    ```
2.  **Configure Environment Variables:**
    Create a `.env` file in the project's root directory based on the provided example. Fill in your Discord bot token, server ID, and WeeChat Relay connection details:
    ```bash
    cp .env.example .env
    # Now, open .env with a text editor and fill in your details
    ```

3.  **Set up Discord Bot Python Environment:**
    Navigate into the `bot/` directory, create a Python virtual environment, install the required dependencies, and then return to the project root:
    ```bash
    cd bot/
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    deactivate
    cd ..
    ```

4.  **Deploy WeeChat Plugin:**
    The WeeChat plugin needs to be symlinked into WeeChat's script directory. Run the provided setup script from the `scripts/` directory:
    ```bash
    ./scripts/setup_weechat_symlinks.sh
    ```
    This script will tell you the next steps to take inside WeeChat, including reloading the `autoxdcc` plugin.

5.  **Configure WeeChat Plugin Settings:**
    Inside WeeChat, you can inspect and modify the plugin's settings using the `/set` command. For example, to set your IRC server and search channel:
    ```    /set plugins.var.python.autoxdcc.irc_server_name your_irc_server
    /set plugins.var.python.autoxdcc.irc_search_channel #your_channel
    ```
    Refer to `weechat/libautoxdcc/config.py` for all available settings.

6.  **Run the Discord Bot Service:**
    For production, it's recommended to run the Discord bot as a systemd service. Copy the provided service file and enable it:
    ```bash
    sudo cp systemd/autoxd-bot.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable autoxd-bot.service
    sudo systemctl start autoxd-bot.service
    # You can check its status with: sudo systemctl status autoxd-bot.service
    ```
    **Important:** Edit `/etc/systemd/system/autoxd-bot.service` to update the `User`, `Group`, and `WorkingDirectory` paths to match your system.

## Usage

Once the bot and WeeChat plugin are running, you can interact with the bot in your Discord server:

*   **/search <query>**: Initiates a search for files matching your query on the configured IRC channel. The bot will respond with a list of choices and interactive buttons to download.
    *   *Example*: `/search "my favorite show s01"`

*   **/hot**: Fetches a list of the most trending files from the configured IRC channel. The bot will present an interactive menu allowing you to filter by category and then search for a specific hot item.

*   **Downloading Files**: After a successful `/search` or when selecting an item from `/hot` to search, the bot will provide buttons. Click the corresponding button (e.g., `Download 1`) to initiate the file transfer via IRC.

