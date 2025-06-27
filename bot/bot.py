# bot.py (Final version for full loop)
import discord
from discord.ext import commands
import config
from weechat_relay_client import WeeChatRelayClient
import uuid

ACTIVE_SEARCHES = {} # This state is shared with webhooks.py

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="", intents=intents)

@bot.event
async def on_ready():
    await bot.tree.sync(guild=discord.Object(id=config.DISCORD_SERVER_ID))
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    print('Web server should be running on http://0.0.0.0:8000')
    print('------')

@bot.tree.command(name="search", description="Search for a file.", guild=discord.Object(id=config.DISCORD_SERVER_ID))
async def search(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    session_id = str(uuid.uuid4())
    weechat_command = f"/autoxdcc_service_search {session_id} {query}"

    ACTIVE_SEARCHES[session_id] = interaction
    client = WeeChatRelayClient()
    try:
        await client.run_fire_and_forget_command(weechat_command)
        embed = discord.Embed(title="Search Initiated", description=f"🔍 Searching for: **`{query}`**", color=discord.Color.blue())
        await interaction.followup.send(embed=embed)
    except Exception as e:
        del ACTIVE_SEARCHES[session_id]
        embed = discord.Embed(title="Search Failed", description="Could not contact the backend.", color=discord.Color.red())
        embed.add_field(name="Error", value=f"```{e}```")
        await interaction.followup.send(embed=embed, ephemeral=True)
