from __future__ import annotations

import discord

from rajdoot.database import Database


class HomeView(discord.ui.View):
    def __init__(self, database: Database) -> None:
        super().__init__(timeout=None); self.database = database
    @discord.ui.button(label="Embassy Directory", emoji="🏛️", style=discord.ButtonStyle.primary, custom_id="rajdoot:home:embassies")
    async def embassies(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(); await interaction.edit_original_response(embed=await embassy_directory_embed(self.database), view=EmbassyDirectoryView(self.database))
    @discord.ui.button(label="My Profile", emoji="👤", style=discord.ButtonStyle.secondary, custom_id="rajdoot:home:profile")
    async def profile(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message("✨ Your diplomatic profile will appear here as soon as your RAJDOOT profile is available.", ephemeral=True)


class NavigationView(discord.ui.View):
    def __init__(self, database: Database) -> None:
        super().__init__(timeout=None); self.database = database
    @discord.ui.button(label="Home", emoji="🏠", style=discord.ButtonStyle.secondary, custom_id="rajdoot:navigation:home")
    async def home(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(embed=home_embed(), view=HomeView(self.database))


class EmbassyDirectoryView(NavigationView):
    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, custom_id="rajdoot:embassies:refresh")
    async def refresh(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(); await interaction.edit_original_response(embed=await embassy_directory_embed(self.database), view=self)


def home_embed() -> discord.Embed:
    return discord.Embed(title="🏛️ RAJDOOT", description="Welcome to RAJDOOT, your diplomatic companion. 🌍\n\nEverything you need is only a click away.", colour=discord.Colour.blurple())


async def embassy_directory_embed(database: Database) -> discord.Embed:
    embassies = await database.fetch_active_embassies()
    if not embassies:
        return discord.Embed(title="🏛️ Embassy Directory", description="🌱 The directory is ready, but no active embassies have been added yet.", colour=discord.Colour.blurple())
    lines = [f"**{index}.** {row['country_name']}" for index, row in enumerate(embassies, start=1)]
    description = "Here are the active embassies, neatly arranged for you. 🌍\n\n" + "\n".join(lines[:25])
    if len(lines) > 25: description += f"\n\n✨ Showing the first 25 of {len(lines)}."
    return discord.Embed(title="🏛️ Embassy Directory", description=description, colour=discord.Colour.blurple())


async def ensure_dashboard_message(*, channel: discord.TextChannel, message_id: int | None, embed: discord.Embed, view: discord.ui.View) -> discord.Message:
    """Return the single canonical dashboard message and remove nearby duplicates."""
    title = embed.title
    selected: discord.Message | None = None
    matches: list[discord.Message] = []
    if message_id:
        try:
            selected = await channel.fetch_message(message_id)
        except (discord.NotFound, discord.HTTPException):
            selected = None
    try:
        async for message in channel.history(limit=100, oldest_first=True):
            if _is_matching_dashboard(message, title): matches.append(message)
    except discord.HTTPException:
        pass
    if selected is None or not _is_matching_dashboard(selected, title):
        selected = next((m for m in matches if m.id == message_id), None) or (matches[0] if matches else None)
    if selected is not None:
        await selected.edit(embed=embed, view=view)
        for duplicate in matches:
            if duplicate.id == selected.id: continue
            try: await duplicate.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException): pass
        return selected
    return await channel.send(embed=embed, view=view)


def _is_matching_dashboard(message: discord.Message, title: str | None) -> bool:
    return bool(message.author.bot and message.embeds and title and message.embeds[0].title == title)
