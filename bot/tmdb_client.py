# bot/tmdb_client.py

import aiohttp
import discord
from typing import Optional, Dict, Any

class TMDBClient:
    """
    A client to orchestrate fetching media information by:
    1. Parsing a release filename using an external parser API.
    2. Using the parsed data to make a targeted search on The Movie Database (TMDB).
    3. Building a rich Discord embed with the combined information.
    """
    PARSER_API_URL = "https://coruscating-gingersnap-21bc8c.netlify.app/.netlify/functions/parser"
    TMDB_API_URL = "https://api.themoviedb.org/3"
    TMDB_IMAGE_URL = "https://image.tmdb.org/t/p/w500"

    def __init__(self, tmdb_api_key: str):
        if not tmdb_api_key:
            raise ValueError("TMDB API key is required.")
        self._tmdb_api_key = tmdb_api_key
        # **FIX**: Initialize session to None. It will be created on first use.
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """
        Lazily creates and returns the aiohttp session.
        This ensures the session is created inside a running event loop.
        """
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        """Gracefully closes the aiohttp session if it exists."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get_parsed_release_info(self, release_name: str) -> Optional[Dict[str, Any]]:
        """
        Calls the external filename parser API to get structured data.
        """
        session = await self._get_session()
        payload = {"releaseName": release_name}
        try:
            async with session.post(self.PARSER_API_URL, json=payload, timeout=10) as response:
                if response.status == 200:
                    json_data = await response.json()
                    return json_data.get("data")
                else:
                    print(f"Parser API Error: Status {response.status} for {release_name}")
                    return None
        except aiohttp.ClientError as e:
            print(f"Parser API Request Error: {e}")
            return None

    async def _search_tmdb(self, parsed_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Uses structured data from the parser to perform a targeted search on TMDB.
        """
        session = await self._get_session()
        media_type = "movie" if parsed_info.get("type") == "Movie" else "tv"
        search_title = parsed_info.get("title")
        search_year = parsed_info.get("year")

        if not search_title:
            return None

        params = {
            "api_key": self._tmdb_api_key,
            "query": search_title,
        }
        if media_type == "movie" and search_year:
            params["primary_release_year"] = search_year
        elif media_type == "tv" and search_year:
            params["first_air_date_year"] = search_year

        search_url = f"{self.TMDB_API_URL}/search/{media_type}"

        try:
            async with session.get(search_url, params=params, timeout=10) as response:
                if response.status == 200:
                    json_data = await response.json()
                    if json_data.get("results"):
                        return json_data["results"][0]
                else:
                    print(f"TMDB API Error: Status {response.status} for {search_title}")
                    return None
        except aiohttp.ClientError as e:
            print(f"TMDB API Request Error: {e}")
            return None
        return None

    def _build_media_embed(self, parsed_info: Dict[str, Any], tmdb_data: Dict[str, Any]) -> discord.Embed:
        """
        Builds a rich Discord embed from the combined parser and TMDB data.
        """
        is_movie = parsed_info.get("type") == "Movie"
        title = tmdb_data.get("title") if is_movie else tmdb_data.get("name")
        
        release_date_str = tmdb_data.get("release_date") if is_movie else tmdb_data.get("first_air_date")
        year = release_date_str.split('-')[0] if release_date_str else parsed_info.get("year", "")
        
        embed_title = f"🎬 {title} ({year})" if is_movie else f"📺 {title} ({year})"
        
        embed = discord.Embed(
            title=embed_title,
            description=tmdb_data.get("overview", "No synopsis available."),
            color=discord.Color.blue()
        )

        if poster_path := tmdb_data.get("poster_path"):
            embed.set_thumbnail(url=f"{self.TMDB_IMAGE_URL}{poster_path}")

        embed.add_field(name="Rating", value=f"⭐ {tmdb_data.get('vote_average', 0):.1f}/10 (TMDB)", inline=True)
        if resolution := parsed_info.get("resolution"):
             embed.add_field(name="Resolution", value=resolution, inline=True)
        if source := parsed_info.get("source"):
             embed.add_field(name="Source", value=source, inline=True)
        if group := parsed_info.get("group"):
             embed.add_field(name="Release Group", value=group, inline=True)

        return embed

    async def fetch_and_build_embed(self, release_name: str) -> Optional[discord.Embed]:
        """
        Orchestrates the full process of fetching data and building the embed.
        """
        parsed_info = await self._get_parsed_release_info(release_name)
        if not parsed_info:
            return None 

        tmdb_data = await self._search_tmdb(parsed_info)
        if not tmdb_data:
            return None

        return self._build_media_embed(parsed_info, tmdb_data)
