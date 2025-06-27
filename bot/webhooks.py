# webhooks.py (Corrected with a proper UI Button subclass)
from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import List, Optional
import discord

import bot as bot_module
from weechat_relay_client import WeeChatRelayClient

# --- Data Models for the webhook payload ---
class Choice(BaseModel):
    choice_id: int
    filename: str
    size: str

class SearchResultPayload(BaseModel):
    session_id: str
    status: str
    message: str
    choices: Optional[List[Choice]] = None

# --- Create a dedicated Button class ---
class DownloadButton(discord.ui.Button):
    def __init__(self, choice_id: int):
        """A custom button that holds the choice_id."""
        super().__init__(
            label=f"Download {choice_id}",
            style=discord.ButtonStyle.primary,
            custom_id=str(choice_id) # The custom_id is still the choice_id
        )
    
    # The callback is now a method of the button itself, which is the correct pattern.
    # The signature `async def callback(self, interaction: discord.Interaction)` is what discord.py expects.
    async def callback(self, interaction: discord.Interaction):
        # Acknowledge the button press immediately.
        await interaction.response.defer()

        # The view is accessible via `self.view`.
        session_id = self.view.session_id
        choice_id = self.custom_id
        
        weechat_command = f"/autoxdcc_service_download {session_id} {choice_id}"
        
        # Disable all buttons in the view after one is clicked.
        for child in self.view.children:
            child.disabled = True
        
        client = WeeChatRelayClient()
        try:
            await client.run_fire_and_forget_command(weechat_command)
            
            original_embed = interaction.message.embeds[0]
            new_embed = discord.Embed(
                title="✅ Download Started",
                description=f"The download command for choice **#{choice_id}** has been sent.",
                color=discord.Color.teal()
            )
            for field in original_embed.fields:
                new_embed.add_field(name=field.name, value=field.value, inline=field.inline)

            # Edit the original message with the new embed and the disabled buttons.
            await interaction.edit_original_response(embed=new_embed, view=self.view)

        except Exception as e:
            error_embed = discord.Embed(
                title="❌ Download Command Failed",
                description=f"Could not send the download command for choice #{choice_id}.",
                color=discord.Color.red()
            )
            error_embed.add_field(name="Error Details", value=f"```{e}```")
            await interaction.edit_original_response(embed=error_embed, view=self.view)
        
        # Stop the view from listening to further interactions.
        self.view.stop()

class DownloadView(discord.ui.View):
    def __init__(self, session_id: str, choices: List[Choice]):
        super().__init__(timeout=300)
        self.session_id = session_id
        # Add a DownloadButton for each choice.
        for choice in choices:
            self.add_item(DownloadButton(choice_id=choice.choice_id))

# --- FastAPI Server ---
app = FastAPI()

@app.post("/search_results")
async def receive_search_results(payload: SearchResultPayload):
    session_id = payload.session_id
    interaction = bot_module.ACTIVE_SEARCHES.pop(session_id, None)
    
    if not interaction:
        print(f"Error: Received results for an unknown session ID: {session_id}")
        return {"status": "error", "message": "Unknown session ID"}

    if payload.status == "success" and payload.choices:
        embed = discord.Embed(
            title="✅ Search Complete",
            description=f"Click a button below to start your download.",
            color=discord.Color.green()
        )
        for choice in payload.choices:
            embed.add_field(name=f"Choice {choice.choice_id}: {choice.filename}", value=f"Size: {choice.size}", inline=False)
        
        # Create our custom view, now passing the choices to it.
        view = DownloadView(session_id=session_id, choices=payload.choices)
        await interaction.followup.send(embed=embed, view=view)
    else:
        embed = discord.Embed(title="⚠️ No Results Found", description=payload.message, color=discord.Color.orange())
        await interaction.followup.send(embed=embed)

    return {"status": "ok"}
