# bot/webhooks.py

from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import discord
import uuid

import bot as bot_module
from weechat_relay_client import WeeChatRelayClient

import config
from tmdb_client import TMDBClient

# --- Data Models (Unchanged) ---
class Choice(BaseModel):
    choice_id: int
    filename: str
    size: str

class SearchResultPayload(BaseModel):
    session_id: str
    status: str
    message: str
    choices: Optional[List[Choice]] = None

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

# --- Instantiate TMDB Client ---
TMDB_CLIENT = TMDBClient(config.TMDB_API_KEY)

# --- UI Components (with fixes) ---

class HotDetailsButton(discord.ui.Button):
    def __init__(self, filename: str, item_number: int, row: int):
        super().__init__(label=f"ℹ️ Details #{item_number}", style=discord.ButtonStyle.secondary, row=row)
        self.filename_to_search = filename

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        embed = await TMDB_CLIENT.fetch_and_build_embed(self.filename_to_search)
        if embed:
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(
                "No movie or TV show details found for this file. It might not be a recognized title.",
                ephemeral=True
            )

class SearchHotItemButton(discord.ui.Button):
    def __init__(self, filename: str, item_number: int, row: int):
        super().__init__(label=f"🔍 Search #{item_number}", style=discord.ButtonStyle.primary, row=row)
        self.filename_to_search = filename

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        # --- THE FIX: Stop the HotFilterView to prevent its on_timeout from firing later ---
        self.view.stop()

        for child in self.view.children:
            child.disabled = True
        
        new_embed = discord.Embed(
            title="🔍 Search Initiated",
            description=f"Handing off to search service for:\n**`{self.filename_to_search}`**\n\nI will edit this message with the results.",
            color=discord.Color.blue()
        )
        await interaction.edit_original_response(embed=new_embed, view=self.view)
        
        session_id = str(uuid.uuid4())
        weechat_command = f"/autoxdcc_service_search {session_id} {self.filename_to_search}"
        
        bot_module.ACTIVE_SESSIONS[session_id] = self.view.original_interaction
        
        client = WeeChatRelayClient()
        try:
            await client.run_fire_and_forget_command(weechat_command)
        except Exception as e:
            bot_module.ACTIVE_SESSIONS.pop(session_id, None)
            error_embed = discord.Embed(
                title="❌ Search Handoff Failed",
                description=f"Could not send the search command for `{self.filename_to_search}`.",
                color=discord.Color.red()
            )
            error_embed.add_field(name="Error Details", value=f"```{e}```")
            await interaction.edit_original_response(embed=error_embed, view=None)


class HotFilterView(discord.ui.View):
    def __init__(self, original_interaction: discord.Interaction, hot_items: List[HotItem]):
        super().__init__(timeout=300)
        self.original_interaction = original_interaction
        self.hot_items = hot_items
        self.current_category = "All Categories"
        self.update_components()

    def update_components(self):
        """Clears and rebuilds the UI components (buttons & dropdown) based on the current state."""
        self.clear_items()
        
        self.add_item(self.create_category_dropdown())

        display_items = self.get_display_items()
        
        for i, item in enumerate(display_items):
            button_row = i + 1
            if button_row > 4:
                break 

            self.add_item(SearchHotItemButton(filename=item.filename, item_number=i + 1, row=button_row))
            self.add_item(HotDetailsButton(filename=item.filename, item_number=i + 1, row=button_row))

    def get_display_items(self) -> List[HotItem]:
        """Filters and sorts items for the current category."""
        if self.current_category == "All Categories":
            filtered_list = self.hot_items
        else:
            filtered_list = [item for item in self.hot_items if item.category == self.current_category]
        
        return sorted(filtered_list, key=lambda x: x.grabs, reverse=True)[:4]

    def create_category_dropdown(self) -> discord.ui.Select:
        """Creates the dropdown menu."""
        all_categories = sorted(list(set(item.category for item in self.hot_items)))
        options = [discord.SelectOption(label="All Categories", default=self.current_category == "All Categories")] + [
            discord.SelectOption(label=cat, default=self.current_category == cat) for cat in all_categories
        ]
        
        dropdown = discord.ui.Select(
            placeholder="Filter by category...",
            options=options,
            custom_id="category_filter",
            row=0
        )
        dropdown.callback = self.on_category_select
        return dropdown
    
    def _build_embed_for_current_state(self) -> discord.Embed:
        """Constructs the embed with items for the currently selected category."""
        initial_embed = self.original_interaction.message.embeds[0] if self.original_interaction.message and self.original_interaction.message.embeds else None
        
        title = initial_embed.title if initial_embed else "🔥 Top Trending Files"
        
        summary_description_part = ""
        if initial_embed and initial_embed.description and "\n\n" in initial_embed.description:
            summary_description_part = initial_embed.description.split("\n\n")[0] + "\n\n"

        embed = discord.Embed(
            title=title,
            description=f"{summary_description_part}Click a search button to download, or 'Details' for media info.",
            color=discord.Color.green()
        )
        
        display_items = self.get_display_items()
        if not display_items:
            embed.add_field(name="No Results", value="No items found in this category.", inline=False)
        else:
            for i, item in enumerate(display_items):
                field_name = f"{i + 1}. {item.filename}"
                field_value = f"**Category:** {item.category} | **Size:** {item.size}"
                embed.add_field(name=field_name, value=field_value, inline=False)
        return embed

    async def on_category_select(self, interaction: discord.Interaction):
        """Callback for category selection."""
        await interaction.response.defer()
        self.current_category = interaction.data["values"][0]
        self.update_components()

        new_embed = self._build_embed_for_current_state()
        
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
            pass


class DownloadButton(discord.ui.Button):
    def __init__(self, choice_id: int):
        super().__init__(label=f"Download {choice_id}", style=discord.ButtonStyle.primary, custom_id=str(choice_id))
    
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
                description=f"Could not communicate with the backend service for choice #{choice_id}.",
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
        interaction = bot_module.ACTIVE_SESSIONS.get(self.session_id)
        if not interaction:
            return

        try:
            original_message = await interaction.original_response()
            new_embed = discord.Embed(
                title="⌛ Search Expired (UI Timeout)",
                description="This search session has expired. Please use `/search` to start a new one.",
                color=discord.Color.dark_orange()
            )
            await original_message.edit(embed=new_embed, view=None)
        except discord.errors.NotFound:
            pass
        finally:
            bot_module.ACTIVE_SESSIONS.pop(self.session_id, None)


# --- FastAPI Server ---
app = FastAPI()

@app.post("/hot_results")
async def receive_hot_results(payload: HotResultPayload):
    session_id = payload.session_id
    interaction = bot_module.ACTIVE_SESSIONS.pop(session_id, None)
    
    if not interaction:
        return {"status": "error", "message": "Unknown session ID"}

    try:
        if payload.status == "success" and payload.items:
            summary_description_part = ""
            if payload.summary:
                summary_description_part = payload.summary.replace(" ¦ ", "\n") + "\n\n"
            
            view = HotFilterView(original_interaction=interaction, hot_items=payload.items)
            
            initial_embed = view._build_embed_for_current_state()
            initial_embed.description = f"{summary_description_part}Click a search button to download, or 'Details' for media info."

            await interaction.edit_original_response(embed=initial_embed, view=view)
        else:
            embed = discord.Embed(
                title="⚠️ No Hot Files Found",
                description=payload.message or "The backend returned no trending files.",
                color=discord.Color.orange()
            )
            await interaction.edit_original_response(embed=embed, view=None)
    
    except discord.errors.NotFound:
        print(f"Error editing original response for hot session {session_id}.")

    return {"status": "ok"}


@app.post("/search_results")
async def receive_search_results(payload: SearchResultPayload):
    session_id = payload.session_id
    interaction = bot_module.ACTIVE_SESSIONS.get(session_id)
    
    if not interaction:
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
        bot_module.ACTIVE_SESSIONS.pop(session_id, None)

    return {"status": "ok"}

@app.post("/session_expired")
async def receive_session_expired(payload: SessionStatusPayload):
    session_id = payload.session_id
    interaction = bot_module.ACTIVE_SESSIONS.get(session_id)

    if not interaction:
        return {"status": "ignored"}

    try:
        new_embed = discord.Embed(
            title=f"⌛ Search Expired",
            description=f"{payload.message}\n\nPlease use `/search` to start a new one.",
            color=discord.Color.dark_orange()
        )
        await interaction.edit_original_response(embed=new_embed, view=None)
    except discord.errors.NotFound:
        pass
    finally:
        bot_module.ACTIVE_SESSIONS.pop(session_id, None)
    
    return {"status": "ok"}

@app.post("/download_status")
async def receive_download_status(payload: DownloadStatusPayload):
    session_id = payload.session_id
    interaction = bot_module.ACTIVE_SESSIONS.get(session_id)

    if not interaction:
        return {"status": "ignored"}
    
    try:
        original_message = await interaction.original_response()
        original_embed = original_message.embeds[0] if original_message.embeds else discord.Embed()

        if payload.status == "success":
            new_embed = discord.Embed(
                title="✅ Download Command Sent",
                description=f"{payload.message}",
                color=discord.Color.teal()
            )
        else:
            new_embed = discord.Embed(
                title="❌ Download Failed",
                description=f"{payload.message}",
                color=discord.Color.red()
            )
        
        for field in original_embed.fields:
            new_embed.add_field(name=field.name, value=field.value, inline=field.inline)

        await interaction.edit_original_response(embed=new_embed, view=None)
    except discord.errors.NotFound:
        pass
    finally:
        bot_module.ACTIVE_SESSIONS.pop(session_id, None)
    
    return {"status": "ok"}
