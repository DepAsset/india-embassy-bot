from __future__ import annotations

import discord
from discord import app_commands

from rajdoot.database import Database
from rajdoot.embassy_access import EmbassyAccessService, EmbassySelectView, has_ambassador_role, has_foreign_diplomat_role, is_government
from rajdoot.workflow_store import WorkflowStore


class AmbassadorSelectView(discord.ui.View):
    def __init__(self, database: Database, member: discord.Member) -> None:
        super().__init__(timeout=300)
        self.database = database
        self.member = member
        self.select = discord.ui.Select(placeholder="Select one or more embassies", min_values=1, max_values=25, options=[])
        self.select.callback = self._callback
        self.add_item(self.select)

    async def populate(self) -> None:
        embassies = await self.database.fetch_active_embassies()
        self.select.options = [
            discord.SelectOption(label=str(e["country_name"])[:100], value=str(e["id"]))
            for e in embassies[:25]
        ]

    async def _callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_government(interaction.user):
            await interaction.response.send_message("🔐 Only Admin/EAM can complete this assignment.", ephemeral=True)
            return
        if not has_ambassador_role(self.member):
            await interaction.response.send_message("❌ The selected user no longer has the Ambassador role.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        embassies = {str(e["id"]): e for e in await self.database.fetch_active_embassies()}
        service = EmbassyAccessService(self.database)
        changed = 0
        for embassy_id in self.select.values:
            embassy = embassies.get(embassy_id)
            if embassy is None:
                continue
            await service.grant(
                interaction.guild,
                self.member,
                embassy,
                actor_id=interaction.user.id,
                assignment_type="indian_ambassador",
            )
            changed += 1
        await interaction.followup.send(f"✅ Ambassador access assigned for **{changed}** embassy/embassies.", ephemeral=True)
        self.stop()


def register_top_level_commands(tree: app_commands.CommandTree, database: Database, guild: discord.Object) -> None:
    store = WorkflowStore(database)

    @app_commands.command(name="assignambassador", description="Assign an Ambassador to one or more embassies")
    async def assignambassador(interaction: discord.Interaction, user: discord.Member) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_government(interaction.user):
            await interaction.response.send_message("🔐 Only Admin/EAM can assign ambassadors.", ephemeral=True)
            return
        if not has_ambassador_role(user):
            await interaction.response.send_message("❌ The selected user does not have the Ambassador role.", ephemeral=True)
            return
        view = AmbassadorSelectView(database, user)
        await view.populate()
        await interaction.response.send_message("🏛️ Select one or more embassy channels to assign:", view=view, ephemeral=True)

    @app_commands.command(name="dismissambassador", description="Dismiss an Ambassador from selected embassies")
    async def dismissambassador(interaction: discord.Interaction, user: discord.Member) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_government(interaction.user):
            await interaction.response.send_message("🔐 Only Admin/EAM can dismiss ambassadors.", ephemeral=True)
            return
        view = EmbassySelectView(database, member=user, action="revoke")
        await view.populate()
        await interaction.response.send_message("🧹 Select the embassy channels to revoke:", view=view, ephemeral=True)

    @app_commands.command(name="removediplomat", description="Remove a diplomat from selected embassy channels")
    async def removediplomat(interaction: discord.Interaction, user: discord.Member) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command is only available in the embassy server.", ephemeral=True)
            return
        if not is_government(interaction.user):
            assignments = await store.active_assignments_for_user(interaction.user.id)
            target_assignments = await store.active_assignments_for_user(user.id)
            allowed = {str(a["embassy_id"]) for a in assignments}
            if not allowed or not any(str(a["embassy_id"]) in allowed for a in target_assignments):
                await interaction.response.send_message("🔐 You may only remove diplomats from embassies you manage.", ephemeral=True)
                return
        view = EmbassySelectView(database, member=user, action="revoke")
        await view.populate()
        await interaction.response.send_message("🧹 Select the embassy channels to remove:", view=view, ephemeral=True)

    @app_commands.command(name="listembassies", description="List active embassies alphabetically")
    async def listembassies(interaction: discord.Interaction) -> None:
        if isinstance(interaction.user, discord.Member) and has_foreign_diplomat_role(interaction.user):
            await interaction.response.send_message("🔐 Foreign Diplomats cannot use this command.", ephemeral=True)
            return
        embassies = await database.fetch_active_embassies()
        lines = [f"**{i}. {e['country_name']}**" for i, e in enumerate(embassies, 1)] or ["No active embassies are registered."]
        await interaction.response.send_message(embed=discord.Embed(title="🏛️ Embassy Directory", description="\n".join(lines[:50]), colour=discord.Colour.blurple()), ephemeral=True)

    @app_commands.command(name="listdiplomats", description="List active diplomats by embassy")
    async def listdiplomats(interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_government(interaction.user):
            await interaction.response.send_message("🔐 Only Admin/EAM can use this command.", ephemeral=True)
            return
        embassies = await database.fetch_active_embassies()
        chunks = []
        for embassy in embassies:
            members = await store.active_embassy_members(str(embassy["id"]))
            names = [m.get("discord_username") or str(m.get("discord_user_id")) for m in members]
            chunks.append(f"**{embassy['country_name']}** — {', '.join(names) if names else 'No active diplomats'}")
        await interaction.response.send_message(embed=discord.Embed(title="👥 Diplomats by Embassy", description="\n".join(chunks[:50]) or "No embassies.", colour=discord.Colour.blurple()), ephemeral=True)

    @app_commands.command(name="diplomatprofile", description="Show a diplomat's verified profile and embassy assignments")
    async def diplomatprofile(interaction: discord.Interaction, user: discord.Member) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command is only available in the embassy server.", ephemeral=True)
            return
        if not is_government(interaction.user):
            own = await store.active_assignments_for_user(interaction.user.id)
            target = await store.active_assignments_for_user(user.id)
            own_ids = {str(a["embassy_id"]) for a in own}
            if not any(str(a["embassy_id"]) in own_ids for a in target):
                await interaction.response.send_message("🔐 You cannot inspect that diplomat's profile.", ephemeral=True)
                return
        assignments = await store.active_assignments_for_user(user.id)
        embed = discord.Embed(title="👤 Diplomatic Profile", colour=discord.Colour.blurple())
        embed.add_field(name="Discord", value=f"{user.mention} (`{user.id}`)", inline=False)
        embed.add_field(name="Embassies", value="\n".join(a["country_name"] for a in assignments) or "None", inline=False)
        embed.add_field(name="Assignment Types", value="\n".join(a["assignment_type"] for a in assignments) or "None", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    for command in (assignambassador, dismissambassador, removediplomat, listembassies, listdiplomats, diplomatprofile):
        tree.add_command(command, guild=guild)
