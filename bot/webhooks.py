from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional, Dict
import discord
import uuid # Needed for creating new search sessions from the hot view

import bot as bot_module
from weechat_relay_client import WeeChatRelayClient

# --- Existing Data Models ---
class Choice(BaseModel):
    choice_id: int
    filename: str
    size: str

class SearchResultPayload(BaseModel):
    session_id: str
    status: str
    message: str
    choices: Optional[List[Choice]] = None

# --- NEW Data Models for the '/hot_results' payload ---
class HotItem(BaseModel):
    grabs: int
    category: str
    size: str
    filename: str

class HotResultPayload(BaseModel):
    session_id: str
    status: str
    summary: Optional[str] = ""
    items: Optional[List[HotItem]] = None

class SessionStatusPayload(BaseModel):
    session_id: str
    status: str 
    message: str

class DownloadStatusPayload(BaseModel):
    session_id: str
    status: str
    message: str


# --- NEW Interactive UI for Hot Files ---
class HotFilterView(discord.ui.View):
    def __init__(self, original_interaction: discord.Interaction, hot_items: List[HotItem]):
        super().__init__(timeout=300)
        self.original_interaction = original_interaction
        self.hot_items = hot_items
        self.current_category = "All Categories" # Default selection
        self.update_components()

    def update_components(self):
        """Clears and rebuilds the UI components based on the current state."""
        self.clear_items() # Remove all old buttons and dropdowns
        
        # 1. Create and add the category dropdown
        self.add_item(self.create_category_dropdown())

        # 2. Filter, sort, and get the top 5 items for the selected category
        display_items = self.get_display_items()
        
        # 3. Create and add a search button for each of the top items
        for item in display_items:
            self.add_item(SearchHotItemButton(filename=item.filename))

    def get_display_items(self) -> List[HotItem]:
        """Filters and sorts the items to find the top 5 for the current category."""
        if self.current_category == "All Categories":
            filtered_list = self.hot_items
        else:
            filtered_list = [item for item in self.hot_items if item.category == self.current_category]
        
        # Sort by grabs (descending) and return the top 5
        return sorted(filtered_list, key=lambda x: x.grabs, reverse=True)[:5]

    def create_category_dropdown(self) -> discord.ui.Select:
        """Creates the dropdown menu with all unique categories."""
        all_categories = sorted(list(set(item.category for item in self.hot_items)))
        options = [discord.SelectOption(label="All Categories")] + [
            discord.SelectOption(label=cat) for cat in all_categories
        ]
        
        dropdown = discord.ui.Select(
            placeholder="Filter by category...",
            options=options,
            custom_id="category_filter"
        )
        dropdown.callback = self.on_category_select
        return dropdown
    
    async def on_category_select(self, interaction: discord.Interaction):
        """Callback for when a user selects a new category from the dropdown."""
        await interaction.response.defer()
        self.current_category = interaction.data["values"][0]
        self.update_components() # Rebuild the UI with new buttons

        # Create the new embed for the selected category
        new_embed = discord.Embed(
            title=f"🔥 Top Files in `{self.current_category}`",
            description="Select another category or click a button to search for a file.",
            color=discord.Color.green()
        )
        
        display_items = self.get_display_items()
        if not display_items:
            new_embed.add_field(name="No Results", value="No items found in this category.")
        else:
            for item in display_items:
                field_name = f"`({item.grabs} grabs)` {item.filename}"
                field_value = f"**Category:** {item.category} | **Size:** {item.size}"
                new_embed.add_field(name=field_name, value=field_value, inline=False)
        
        # Edit the original message with the updated embed and view
        await self.original_interaction.edit_original_response(embed=new_embed, view=self)

    async def on_timeout(self):
        """Disables the view when it expires."""
        try:
            message = await self.original_interaction.original_response()
            new_embed = discord.Embed(
                title="⌛ Hot List Expired",
                description="This interactive session has expired. Please use `/hot` to start a new one.",
                color=discord.Color.dark_orange()
            )
            await message.edit(embed=new_embed, view=None)
        except discord.errors.NotFound:
            pass # Message was likely deleted, nothing to do.


class SearchHotItemButton(discord.ui.Button):
    def __init__(self, filename: str):
        # Button label is truncated to fit Discord's 80-char limit
        super().__init__(label=f"🔍 {filename}"[:80], style=discord.ButtonStyle.secondary)
        self.filename_to_search = filename

    async def callback(self, interaction: discord.Interaction):
        """Callback for when a user clicks a button to search for a specific file."""
        await interaction.response.defer()
        
        # Disable all components in the view to prevent further interaction
        for child in self.view.children:
            child.disabled = True
        
        new_embed = discord.Embed(
            title="🔍 Search Initiated",
            description=f"Handing off to search service for:\n**`{self.filename_to_search}`**\n\nI will edit this message with the results.",
            color=discord.Color.blue()
        )
        await interaction.edit_original_response(embed=new_embed, view=self.view)
        
        # --- Handoff to the existing search logic ---
        session_id = str(uuid.uuid4())
        weechat_command = f"/autoxdcc_service_search {session_id} {self.filename_to_search}"
        
        # We need to use the *original* interaction from the view to ensure we can edit the message later.
        bot_module.ACTIVE_SESSIONS[session_id] = self.view.original_interaction
        
        client = WeeChatRelayClient()
        try:
            await client.run_fire_and_forget_command(weechat_command)
        except Exception as e:
            bot_module.ACTIVE_SESSIONS.pop(session_id, None)
            error_embed = discord.Embed(
                title="❌ Search Handoff Failed",
                description=f"Could not send the search command for `{self.filename_to_search}` to the backend.",
                color=discord.Color.red()
            )
            error_embed.add_field(name="Error Details", value=f"```{e}```")
            await interaction.edit_original_response(embed=error_embed, view=None)


# --- Existing UI Components ---
class DownloadButton(discord.ui.Button):
    def __init__(self, choice_id: int):
        super().__init__(label=f"Download {choice_id}", style=discord.ButtonStyle.primary, custom_id=str(choice_id))
    # ... (rest of this class is unchanged) ...
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
    # ... (this class is unchanged) ...
    def __init__(self, session_id: str, choices: List[Choice]):
        super().__init__(timeout=305)
        self.session_id = session_id
        for choice in choices:
            self.add_item(DownloadButton(choice_id=choice.choice_id))
    async def on_timeout(self):
        print(f"DownloadView for session {self.session_id} timed out on Discord side.")
        interaction = bot_module.ACTIVE_SESSIONS.get(self.session_id)
        if not interaction:
            return
        try:
            original_message = await interaction.original_response()
            new_embed = discord.Embed(
                title="⌛ Search Expired (UI Timeout)",
                description="This search session has expired due to inactivity. Please use `/search` to start a new one.",
                color=discord.Color.dark_orange()
            )
            await original_message.edit(embed=new_embed, view=None)
        except discord.errors.NotFound:
            print(f"Warning: Original message for session {self.session_id} not found on timeout.")
        finally:
            bot_module.ACTIVE_SESSIONS.pop(self.session_id, None)

# --- FastAPI Server ---
app = FastAPI()

# --- NEW Endpoint to handle hot file results ---
@app.post("/hot_results")
async def receive_hot_results(payload: HotResultPayload):
    session_id = payload.session_id
    interaction = bot_module.ACTIVE_SESSIONS.pop(session_id, None) # Pop the session, its job is done.
    
    if not interaction:
        print(f"Error: Received hot results for an unknown or expired session ID: {session_id}")
        return {"status": "error", "message": "Unknown session ID"}

    try:
        if payload.status == "success" and payload.items:
            summary_text = f"Found **{len(payload.items)}** total items."
            if payload.summary:
                # Format the summary from the backend nicely.
                summary_text = payload.summary.replace(" ¦ ", "\n")
            
            embed = discord.Embed(
                title="🔥 Top Trending Files",
                description=f"{summary_text}\n\nPlease select a category to begin.",
                color=discord.Color.green()
            )
            # The view will be created with the initial state (dropdown only)
            view = HotFilterView(original_interaction=interaction, hot_items=payload.items)
            await interaction.edit_original_response(embed=embed, view=view)

        else: # Handles "no_results" or other errors from WeeChat
            embed = discord.Embed(
                title="⚠️ No Hot Files Found",
                description=payload.message or "The backend returned no trending files.",
                color=discord.Color.orange()
            )
            await interaction.edit_original_response(embed=embed, view=None)
    
    except discord.errors.NotFound:
        print(f"Error editing original response for hot session {session_id}. Message was likely deleted.")

    return {"status": "ok"}


@app.post("/search_results")
async def receive_search_results(payload: SearchResultPayload):
    # ... (this endpoint handler is unchanged) ...
    session_id = payload.session_id
    interaction = bot_module.ACTIVE_SESSIONS.get(session_id)
    if not interaction:
        print(f"Error: Received results for an unknown or expired session ID: {session_id}")
        return {"status": "error", "message": "Unknown session ID"}
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
            await interaction.edit_original_response(embed=embed, view=view)
        elif payload.status == "rejected_busy":
            embed = discord.Embed(
                title="⚠️ Search Service Busy",
                description=payload.message,
                color=discord.Color.orange()
            )
            await interaction.edit_original_response(embed=embed, view=None)
            bot_module.ACTIVE_SESSIONS.pop(session_id, None)
        else:
            embed = discord.Embed(title="⚠️ No Results Found", description=payload.message, color=discord.Color.orange())
            await interaction.edit_original_response(embed=embed, view=None)
            bot_module.ACTIVE_SESSIONS.pop(session_id, None)
    except discord.errors.NotFound:
        print(f"Error editing original response for session {session_id}. Message was likely deleted by a user.")
        bot_module.ACTIVE_SESSIONS.pop(session_id, None)
    return {"status": "ok"}


@app.post("/session_expired")
async def receive_session_expired(payload: SessionStatusPayload):
    # ... (this endpoint handler is unchanged) ...
    session_id = payload.session_id
    interaction = bot_module.ACTIVE_SESSIONS.get(session_id)
    if not interaction:
        return {"status": "ignored", "message": "Session already handled or unknown."}
    try:
        new_embed = discord.Embed(
            title=f"⌛ Search Expired",
            description=f"{payload.message}\n\nPlease use `/search` to start a new one.",
            color=discord.Color.dark_orange()
        )
        await interaction.edit_original_response(embed=new_embed, view=None)
    except discord.errors.NotFound:
        print(f"Warning: Original message for session {session_id} not found on Discord.")
    finally:
        bot_module.ACTIVE_SESSIONS.pop(session_id, None)
    return {"status": "ok"}


@app.post("/download_status")
async def receive_download_status(payload: DownloadStatusPayload):
    # ... (this endpoint handler is unchanged) ...
    session_id = payload.session_id
    interaction = bot_module.ACTIVE_SESSIONS.get(session_id)
    if not interaction:
        return {"status": "ignored", "message": "Session already handled or unknown."}
    try:
        original_message = await interaction.original_response()
        original_embed = original_message.embeds[0] if original_message.embeds else discord.Embed()
        if payload.status == "success":
            new_embed = discord.Embed(title="✅ Download Command Sent", description=f"{payload.message}", color=discord.Color.teal())
        else:
            new_embed = discord.Embed(title="❌ Download Failed", description=f"{payload.message}", color=discord.Color.red())
        for field in original_embed.fields:
            new_embed.add_field(name=field.name, value=field.value, inline=field.inline)
        await interaction.edit_original_response(embed=new_embed, view=None)
    except discord.errors.NotFound:
        print(f"Warning: Original message for session {session_id} not found on Discord.")
    finally:
        bot_module.ACTIVE_SESSIONS.pop(session_id, None)
    return {"status": "ok"}
