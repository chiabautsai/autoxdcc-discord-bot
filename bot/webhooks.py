from fastapi import FastAPI
from pydantic import BaseModel
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

class SessionStatusPayload(BaseModel):
    session_id: str
    status: str 
    message: str

class DownloadStatusPayload(BaseModel):
    session_id: str
    status: str
    message: str

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
        
        original_embed = interaction.message.embeds[0]
        new_embed = discord.Embed(
            title="⏳ Processing Download Request...",
            description=f"Sending request for choice **#{choice_id}** to the backend. Please wait for an update.",
            color=discord.Color.blue()
        )
        for field in original_embed.fields:
            new_embed.add_field(name=field.name, value=field.value, inline=field.inline)

        await interaction.edit_original_response(embed=new_embed, view=self.view)
        
        client = WeeChatRelayClient()
        try:
            await client.run_fire_and_forget_command(weechat_command)
        except Exception as e:
            error_embed = discord.Embed(
                title="❌ Bot Communication Error",
                description=f"Could not communicate with the backend service to send download command for choice #{choice_id}.",
                color=discord.Color.red()
            )
            error_embed.add_field(name="Error Details", value=f"```{e}```")
            await interaction.edit_original_response(embed=error_embed, view=self.view)
            self.view.stop()
            bot_module.ACTIVE_SESSIONS.pop(session_id, None)

class DownloadView(discord.ui.View):
    def __init__(self, session_id: str, choices: List[Choice]):
        super().__init__(timeout=305)
        self.session_id = session_id
        for choice in choices:
            self.add_item(DownloadButton(choice_id=choice.choice_id))

    async def on_timeout(self):
        print(f"DownloadView for session {self.session_id} timed out on Discord side.")
        interaction = bot_module.ACTIVE_SESSIONS.get(self.session_id)
        if not interaction:
            print(f"Session {self.session_id} already cleaned up or unknown when view timed out.")
            return

        try:
            # We use edit_original_response here because it targets the single message we've been updating.
            original_message = await interaction.original_response()
            new_embed = discord.Embed(
                title="⌛ Search Expired (UI Timeout)",
                description="This search session has expired due to inactivity. Please use `/search` to start a new one.",
                color=discord.Color.dark_orange()
            )
            await original_message.edit(embed=new_embed, view=None)
            print(f"Session {self.session_id} Discord message updated via on_timeout and buttons disabled.")
        except discord.errors.NotFound:
            print(f"Warning: Original message for session {self.session_id} not found on timeout.")
        except Exception as e:
            print(f"Error updating Discord message on timeout for session {self.session_id}: {e}")
        finally:
            bot_module.ACTIVE_SESSIONS.pop(self.session_id, None)


# --- FastAPI Server ---
app = FastAPI()

@app.post("/search_results")
async def receive_search_results(payload: SearchResultPayload):
    session_id = payload.session_id
    interaction = bot_module.ACTIVE_SESSIONS.get(session_id)
    
    if not interaction:
        print(f"Error: Received results for an unknown or expired session ID: {session_id}")
        return {"status": "error", "message": "Unknown session ID"}

    # We will now use interaction.edit_original_response for all cases to update the single message.
    # The original message is the one created by the initial `interaction.followup.send` in bot.py
    # NOTE: We can get this message via `await interaction.original_response()`

    try:
        if payload.status == "success" and payload.choices:
            embed = discord.Embed(
                title="✅ Search Complete",
                description=f"Click a button below to start your download.",
                color=discord.Color.green()
            )
            for choice in payload.choices:
                embed.add_field(name=f"Choice {choice.choice_id}: {choice.filename}", value=f"Size: {choice.size}", inline=False)
            
            view = DownloadView(session_id=session_id, choices=payload.choices)
            await interaction.edit_original_response(embed=embed, view=view) # <-- MODIFIED

        elif payload.status == "rejected_busy":
            embed = discord.Embed(
                title="⚠️ Search Service Busy",
                description=payload.message,
                color=discord.Color.orange()
            )
            await interaction.edit_original_response(embed=embed, view=None) # <-- MODIFIED
            bot_module.ACTIVE_SESSIONS.pop(session_id, None)

        else: # This handles "no_results" or other startup errors from WeeChat
            embed = discord.Embed(title="⚠️ No Results Found", description=payload.message, color=discord.Color.orange())
            await interaction.edit_original_response(embed=embed, view=None) # <-- MODIFIED
            bot_module.ACTIVE_SESSIONS.pop(session_id, None)

    except discord.errors.NotFound:
        print(f"Error editing original response for session {session_id}. Message was likely deleted by a user.")
        bot_module.ACTIVE_SESSIONS.pop(session_id, None) # Clean up the session anyway

    return {"status": "ok"}

@app.post("/session_expired")
async def receive_session_expired(payload: SessionStatusPayload):
    session_id = payload.session_id
    interaction = bot_module.ACTIVE_SESSIONS.get(session_id)

    if not interaction:
        print(f"Warning: Received expiry for unknown/already cleaned session ID: {session_id}")
        return {"status": "ignored", "message": "Session already handled or unknown."}

    try:
        new_embed = discord.Embed(
            title=f"⌛ Search Expired",
            description=f"{payload.message}\n\nPlease use `/search` to start a new one.",
            color=discord.Color.dark_orange()
        )
        await interaction.edit_original_response(embed=new_embed, view=None) # Correctly updates the single message and removes buttons
        print(f"Session {session_id} expired. Discord message updated and buttons disabled.")

    except discord.errors.NotFound:
        print(f"Warning: Original message for session {session_id} not found on Discord, likely already deleted or too old.")
    except Exception as e:
        print(f"Error updating Discord message for expired session {session_id}: {e}")
    finally:
        bot_module.ACTIVE_SESSIONS.pop(session_id, None)
    
    return {"status": "ok"}

@app.post("/download_status")
async def receive_download_status(payload: DownloadStatusPayload):
    session_id = payload.session_id
    interaction = bot_module.ACTIVE_SESSIONS.get(session_id)

    if not interaction:
        print(f"Warning: Received download status for unknown/already cleaned session ID: {session_id}")
        return {"status": "ignored", "message": "Session already handled or unknown."}
    
    try:
        original_message = await interaction.original_response()
        original_embed = original_message.embeds[0] if original_message.embeds else discord.Embed()

        if payload.status == "success":
            new_embed = discord.Embed(
                title="✅ Download Command Sent",
                description=f"{payload.message}",
                color=discord.Color.teal()
            )
        else: # status == "error"
            new_embed = discord.Embed(
                title="❌ Download Failed",
                description=f"{payload.message}",
                color=discord.Color.red()
            )
        
        for field in original_embed.fields:
            new_embed.add_field(name=field.name, value=field.value, inline=field.inline)

        await interaction.edit_original_response(embed=new_embed, view=None) # Correctly updates the single message and removes buttons
        print(f"Session {session_id} download status received: {payload.status}. Discord message updated.")

    except discord.errors.NotFound:
        print(f"Warning: Original message for session {session_id} not found on Discord.")
    except Exception as e:
        print(f"Error updating Discord message for download status {session_id}: {e}")
    finally:
        bot_module.ACTIVE_SESSIONS.pop(session_id, None)
    
    return {"status": "ok"}
