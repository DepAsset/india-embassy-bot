from __future__ import annotations

import discord

from embassy.registry import Embassy, EmbassyRegistry


class EmbassySelect(discord.ui.Select):
    def __init__(self, registry: EmbassyRegistry, embassies: list[Embassy], on_select):
        self.registry = registry
        self.on_select_callback = on_select
        options = [
            discord.SelectOption(
                label=embassy.country_name[:100],
                value=embassy.embassy_id,
                description=f"{embassy.country_name} Embassy"[:100],
            )
            for embassy in embassies[:25]
        ]
        super().__init__(
            placeholder="Select an Embassy",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="embassy:select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        embassy = await self.registry.get_by_id(self.values[0])
        if embassy is None or not embassy.active:
            await interaction.response.send_message("That Embassy is no longer available.", ephemeral=True)
            return
        await self.on_select_callback(interaction, embassy)


class EmbassySelectView(discord.ui.View):
    def __init__(self, registry: EmbassyRegistry, embassies: list[Embassy], on_select, timeout: float | None = 300):
        super().__init__(timeout=timeout)
        self.add_item(EmbassySelect(registry, embassies, on_select))


async def send_embassy_selector(interaction: discord.Interaction, registry: EmbassyRegistry, on_select) -> None:
    embassies = await registry.get_active()
    if not embassies:
        await interaction.response.send_message("There are currently no active Embassies available.", ephemeral=True)
        return
    await interaction.response.send_message(
        "Select the Embassy you want access to:",
        view=EmbassySelectView(registry, embassies, on_select),
        ephemeral=True,
    )
