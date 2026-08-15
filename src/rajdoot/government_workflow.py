from __future__ import annotations

import discord

from rajdoot.database import Database


class GovernmentRequestDecisionView(discord.ui.View):
    def __init__(self, database: Database, request_id: str) -> None:
        super().__init__(timeout=300)
        self.database = database
        self.request_id = request_id
        self.busy = False

    @staticmethod
    def _authorized(interaction: discord.Interaction) -> bool:
        return isinstance(interaction.user, discord.Member) and (
            interaction.user.guild_permissions.manage_guild
            or interaction.user.guild_permissions.administrator
        )

    async def _decide(self, interaction: discord.Interaction, decision: str, assignment_type: str | None = None) -> None:
        if not self._authorized(interaction):
            await interaction.response.send_message("🔐 Government authorization required.", ephemeral=True)
            return
        if self.busy:
            await interaction.response.send_message("⏳ This request is already being processed.", ephemeral=True)
            return
        self.busy = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        try:
            result = await self.database.decide_embassy_request_as_government(
                request_id=self.request_id,
                actor_discord_id=interaction.user.id,
                decision=decision,
                assignment_type=assignment_type,
            )
        except Exception as exc:
            for child in self.children:
                child.disabled = False
            self.busy = False
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title="⚠️ Request could not be processed",
                    description=str(exc),
                    colour=discord.Colour.red(),
                ),
                view=self,
            )
            return

        if decision == "approved":
            title = "✅ Embassy Access Approved"
            description = (
                f"Request `{result['id']}` approved.\n\n"
                f"Assignment: **{assignment_type.replace('_', ' ').title()}**\n"
                "The access assignment is now recorded in RAJDOOT."
            )
        else:
            title = "❌ Embassy Access Rejected"
            description = f"Request `{result['id']}` has been rejected."
        await interaction.edit_original_response(
            embed=discord.Embed(title=title, description=description, colour=discord.Colour.green() if decision == "approved" else discord.Colour.red()),
            view=None,
        )

    @discord.ui.button(label="Approve — Foreign Diplomat", emoji="🌍", style=discord.ButtonStyle.success, row=0)
    async def approve_diplomat(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._decide(interaction, "approved", "foreign_diplomat")

    @discord.ui.button(label="Approve — Indian Ambassador", emoji="🇮🇳", style=discord.ButtonStyle.success, row=0)
    async def approve_ambassador(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._decide(interaction, "approved", "indian_ambassador")

    @discord.ui.button(label="Reject", emoji="❌", style=discord.ButtonStyle.danger, row=1)
    async def reject(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._decide(interaction, "rejected")


class GovernmentRequestListView(discord.ui.View):
    def __init__(self, database: Database, requests: list[dict]) -> None:
        super().__init__(timeout=300)
        self.database = database
        self.requests = requests
        options = [
            discord.SelectOption(
                label=str(row.get("country_name") or "Embassy")[:100],
                description=f"Applicant {row.get('applicant_discord_id')} • {str(row['id'])[:8]}",
                value=str(row["id"]),
            )
            for row in requests[:25]
        ]
        self.select = discord.ui.Select(
            placeholder="Select a request to review",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="rajdoot:government:request-select",
        )
        self.select.callback = self._selected
        self.add_item(self.select)

    async def _selected(self, interaction: discord.Interaction) -> None:
        request_id = self.select.values[0]
        request = next((row for row in self.requests if str(row["id"]) == request_id), None)
        if request is None:
            await interaction.response.send_message("⚠️ That request is no longer in this list.", ephemeral=True)
            return
        snapshot = request.get("warera_profile_snapshot") or {}
        embed = discord.Embed(
            title="📨 Embassy Access Request",
            description="Review the verified applicant before making an assignment decision.",
            colour=discord.Colour.blurple(),
        )
        embed.add_field(name="Embassy", value=str(request.get("country_name") or "Unknown"), inline=True)
        embed.add_field(name="Applicant", value=f"<@{request['applicant_discord_id']}> (`{request['applicant_discord_id']}`)", inline=True)
        embed.add_field(name="WarEra ID", value=str(request.get("warera_user_id") or snapshot.get("id") or "Not available"), inline=True)
        if request.get("profile_url"):
            embed.add_field(name="Profile", value=str(request["profile_url"]), inline=False)
        fields = (
            ("Name", snapshot.get("name") or snapshot.get("username")),
            ("Country", snapshot.get("country") or snapshot.get("nationality")),
            ("Rank", snapshot.get("rank") or snapshot.get("role")),
        )
        for name, value in fields:
            if value:
                embed.add_field(name=name, value=str(value)[:1024], inline=True)
        embed.set_footer(text=f"Request ID: {request['id']}")
        await interaction.response.send_message(
            embed=embed,
            view=GovernmentRequestDecisionView(self.database, request_id),
            ephemeral=True,
        )


async def government_requests_embed(database: Database) -> tuple[discord.Embed, GovernmentRequestListView | None]:
    requests = await database.fetch_pending_requests_for_government()
    if not requests:
        return (
            discord.Embed(
                title="📥 Pending Embassy Requests",
                description="No verified embassy access requests are waiting for government review.",
                colour=discord.Colour.green(),
            ),
            None,
        )
    embed = discord.Embed(
        title="📥 Pending Embassy Requests",
        description=(
            f"**{len(requests)}** request(s) are awaiting government review.\n\n"
            "Select a request below to open its private review panel."
        ),
        colour=discord.Colour.blurple(),
    )
    embed.add_field(
        name="Queue",
        value="\n".join(
            f"• **{row.get('country_name', 'Unknown')}** — <@{row['applicant_discord_id']}>"
            for row in requests[:10]
        )[:1024],
        inline=False,
    )
    if len(requests) > 10:
        embed.set_footer(text=f"Showing the first 10 of {len(requests)}. Use the selector for any of the first 25.")
    return embed, GovernmentRequestListView(database, requests)
