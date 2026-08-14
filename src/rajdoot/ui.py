from __future__ import annotations

import discord

from rajdoot.database import Database


class HomeView(discord.ui.View):
    def __init__(self, database: Database) -> None:
        super().__init__(timeout=None)
        self.database = database

    @discord.ui.button(label="Embassy Directory", emoji="🏛️", style=discord.ButtonStyle.primary, custom_id="rajdoot:home:embassies")
    async def embassies(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        await interaction.edit_original_response(
            embed=await embassy_directory_embed(self.database),
            view=EmbassyDirectoryView(self.database),
        )

    @discord.ui.button(label="My Profile", emoji="👤", style=discord.ButtonStyle.secondary, custom_id="rajdoot:home:profile")
    async def profile(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            "✨ Your diplomatic profile will appear here as soon as your RAJDOOT profile is available.",
            ephemeral=True,
        )


class NavigationView(discord.ui.View):
    def __init__(self, database: Database) -> None:
        super().__init__(timeout=None)
        self.database = database

    @discord.ui.button(label="Home", emoji="🏠", style=discord.ButtonStyle.secondary, custom_id="rajdoot:navigation:home")
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(embed=home_embed(), view=HomeView(self.database))


class EmbassyDirectoryView(NavigationView):
    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, custom_id="rajdoot:embassies:refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        await interaction.edit_original_response(embed=await embassy_directory_embed(self.database), view=self)


def home_embed() -> discord.Embed:
    return discord.Embed(
        title="🏛️ RAJDOOT",
        description=(
            "Welcome to RAJDOOT, your diplomatic companion. 🌍\n\n"
            "Everything you need is only a click away. Take a look around, "
            "and let us take care of the diplomatic details. ✨"
        ),
        colour=discord.Colour.blurple(),
    )


async def embassy_directory_embed(database: Database) -> discord.Embed:
    embassies = await database.fetch_active_embassies()
    if not embassies:
        return discord.Embed(
            title="🏛️ Embassy Directory",
            description="🌱 The directory is ready, but no active embassies have been added yet.",
            colour=discord.Colour.blurple(),
        )

    lines = [f"**{index}.** {row['country_name']}" for index, row in enumerate(embassies, start=1)]
    description = (
        "Here are the active embassies, neatly arranged for you. 🌍\n\n"
        + "\n".join(lines[:25])
    )
    if len(lines) > 25:
        description += f"\n\n✨ Showing the first 25 of {len(lines)}. Pagination is coming with the full directory experience."
    return discord.Embed(
        title="🏛️ Embassy Directory",
        description=description,
        colour=discord.Colour.blurple(),
    )


async def ensure_dashboard_message(
    *,
    channel: discord.TextChannel,
    message_id: int | None,
    embed: discord.Embed,
    view: discord.ui.View,
) -> discord.Message:
    """Reuse one RAJDOOT dashboard message and clean duplicate RAJDOOT copies."""
    title = embed.title
    selected: discord.Message | None = None
    recent_matches: list[discord.Message] = []

    if message_id:
        try:
            selected = await channel.fetch_message(message_id)
        except (discord.NotFound, discord.HTTPException):
            selected = None

    # If the stored message is unavailable, inspect only a small recent window.
    # This avoids repeated broad history scans and keeps Discord API usage low.
    if selected is None or not _is_matching_dashboard(selected, title):
        async for message in channel.history(limit=25):
            if _is_matching_dashboard(message, title):
                recent_matches.append(message)

        if recent_matches:
            selected = next(
                (message for message in recent_matches if message.id == message_id),
                recent_matches[0],
            )
    else:
        # We still need one bounded scan to clean duplicates that may have been
        # created by earlier deployments before dashboard IDs were persisted.
        async for message in channel.history(limit=25):
            if _is_matching_dashboard(message, title):
                recent_matches.append(message)

    if selected is not None and _is_matching_dashboard(selected, title):
        await selected.edit(embed=embed, view=view)

        # Only delete duplicate RAJDOOT dashboard copies with the same title.
        # Legacy/unrelated messages are intentionally untouched.
        for duplicate in recent_matches:
            if duplicate.id == selected.id:
                continue
            try:
                await duplicate.delete()
            except (discord.NotFound, discord.HTTPException):
                pass
        return selected

    return await channel.send(embed=embed, view=view)


def _is_matching_dashboard(message: discord.Message, title: str | None) -> bool:
    if not message.author.bot or not message.embeds or not title:
        return False
    return message.embeds[0].title == title
