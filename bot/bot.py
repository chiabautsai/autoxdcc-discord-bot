import discord
from discord.ext import commands
import config
from weechat_relay_client import WeeChatRelayClient
import uuid

# This dictionary will hold our active search sessions.
# Key: session_id (str)
# Value: discord.Interaction object
ACTIVE_SESSIONS = {}

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="", intents=intents)

@bot.event
async def on_ready():
    await bot.tree.sync(guild=discord.Object(id=config.DISCORD_SERVER_ID))
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    print('Web server should be running on http://0.0.0.0:8000')
    print('------')

@bot.tree.command(
    name="search",
    description="Search for a file using the XDCC service.",
    guild=discord.Object(id=config.DISCORD_SERVER_ID)
)
async def search(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    session_id = str(uuid.uuid4())
    weechat_command = f"/autoxdcc_service_search {session_id} {query}"

    # Store the interaction object so we can respond to it later
    ACTIVE_SESSIONS[session_id] = interaction
    client = WeeChatRelayClient()
    try:
        await client.run_fire_and_forget_command(weechat_command)
        embed = discord.Embed(
            title="Search Initiated",
            description=f"🔍 Searching for: **`{query}`**\n\nI will post the results here when they are ready.",
            color=discord.Color.blue()
        )
        await interaction.followup.send(embed=embed)

    except Exception as e:
        del ACTIVE_SESSIONS[session_id]
        embed = discord.Embed(
            title="Search Command Failed",
            description="Could not send the search command to the backend service.",
            color=discord.Color.red()
        )
        embed.add_field(name="Error Details", value=f"```{e}```")
        await interaction.followup.send(embed=embed, ephemeral=True)
