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

# --- Custom Discord UI Component Classes ---
class DownloadButton(discord.ui.Button):
    def __init__(self, choice_id: int):
        super().__init__(
            label=f"Download {choice_id}",
            style=discord.ButtonStyle.primary,
            custom_id=str(choice_id)
        )
    
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

        session_id = self.view.session_id
        choice_id = self.custom_id
        
        weechat_command = f"/autoxdcc_service_download {session_id} {choice_id}"
        
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

            await interaction.edit_original_response(embed=new_embed, view=self.view)

        except Exception as e:
            error_embed = discord.Embed(
                title="❌ Download Command Failed",
                description=f"Could not send the download command for choice #{choice_id}.",
                color=discord.Color.red()
            )
            error_embed.add_field(name="Error Details", value=f"```{e}```")
            await interaction.edit_original_response(embed=error_embed, view=self.view)
        
        self.view.stop()

class DownloadView(discord.ui.View):
    def __init__(self, session_id: str, choices: List[Choice]):
        super().__init__(timeout=300)
        self.session_id = session_id
        for choice in choices:
            self.add_item(DownloadButton(choice_id=choice.choice_id))

# --- FastAPI Server ---
app = FastAPI()

@app.post("/search_results")
async def receive_search_results(payload: SearchResultPayload):
    session_id = payload.session_id
    interaction = bot_module.ACTIVE_SESSIONS.get(session_id)
    
    if not interaction:
        print(f"Error: Received results for an unknown or expired session ID: {session_id}")
        return {"status": "error", "message": "Unknown session ID"}

    if payload.status == "success" and payload.choices:
        embed = discord.Embed(
            title="✅ Search Complete",
            description=f"Click a button below to start your download.",
            color=discord.Color.green()
        )
        for choice in payload.choices:
            embed.add_field(name=f"Choice {choice.choice_id}: {choice.filename}", value=f"Size: {choice.size}", inline=False)
        
        view = DownloadView(session_id=session_id, choices=payload.choices)
        await interaction.followup.send(embed=embed, view=view)
    else:
        embed = discord.Embed(title="⚠️ No Results Found", description=payload.message, color=discord.Color.orange())
        await interaction.followup.send(embed=embed)
        # Clean up the session if there were no results
        bot_module.ACTIVE_SESSIONS.pop(session_id, None)

    return {"status": "ok"}
