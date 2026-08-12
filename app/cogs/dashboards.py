from __future__ import annotations

from datetime import timedelta

import discord

from app.config import settings
from access.service import AccessService
from approval.workflow import ApprovalWorkflow
from embassy.registry import EmbassyRegistry


def _government(member: discord.Member) -> bool:
    allowed = {
        settings.role_president_id,
        settings.role_vice_president_id,
        settings.role_nsa_id,
        settings.role_minister_id,
        settings.role_eam_id,
    }
    return member.guild_permissions.administrator or any(role.id in allowed for role in member.roles)


def _diplomat(member: discord.Member) -> bool:
    return any(role.id == settings.role_foreign_diplomat_id for role in member.roles)


class PreApprovalModal(discord.ui.Modal, title="Create Embassy Pre-Approval"):
    embassy_id = discord.ui.TextInput(
        label="Embassy ID",
        placeholder="Use the Embassy ID shown in My Embassies",
        min_length=1,
        max_length=100,
        required=True,
    )
    warera_user_id = discord.ui.TextInput(
        label="Applicant WarEra User ID",
        placeholder="WarEra user ID of the person you want to pre-approve",
        min_length=1,
        max_length=100,
        required=True,
    )
    expiry_hours = discord.ui.TextInput(
        label="Expiry (hours)",
        placeholder="72",
        min_length=1,
        max_length=4,
        required=False,
        default="72",
    )
    reason = discord.ui.TextInput(
        label="Reason",
        style=discord.TextStyle.paragraph,
        placeholder="Optional reason for the pre-approval",
        max_length=500,
        required=False,
    )

    def __init__(self, bot: discord.Client):
        super().__init__(timeout=300)
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This action is guild-only.", ephemeral=True)
            return

        access = AccessService(self.bot.database)
        embassy_id = self.embassy_id.value.strip()
        if not await access.has_access(interaction.user.id, embassy_id):
            await interaction.response.send_message(
                "You can only create pre-approvals for an Embassy where you currently have active diplomat access.",
                ephemeral=True,
            )
            return

        try:
            hours = int(self.expiry_hours.value.strip() or "72")
        except ValueError:
            await interaction.response.send_message("Expiry must be a whole number of hours.", ephemeral=True)
            return
        if hours < 1 or hours > 720:
            await interaction.response.send_message("Expiry must be between 1 and 720 hours.", ephemeral=True)
            return

        workflow = ApprovalWorkflow(self.bot.database)
        preapproval_id = await workflow.create_preapproval(
            embassy_id=embassy_id,
            diplomat_id=interaction.user.id,
            applicant_warera_id=self.warera_user_id.value.strip(),
            expires_at=workflow.default_preapproval_expiry(hours),
            reason=self.reason.value.strip() or None,
        )
        await interaction.response.send_message(
            f"✅ Pre-approval created successfully.\n\n**Pre-approval ID:** `{preapproval_id}`\n**Embassy:** `{embassy_id}`\n**WarEra User:** `{self.warera_user_id.value.strip()}`\n**Expires:** <t:{int((workflow.default_preapproval_expiry(hours)).timestamp())}:R>",
            ephemeral=True,
        )


class EmbassyManagementView(discord.ui.View):
    def __init__(self, bot: discord.Client, *, timeout: float | None = None):
        super().__init__(timeout=timeout)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member) or not _government(interaction.user):
            await interaction.response.send_message("You are not authorized to use Embassy Management.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Requests", emoji="📨", style=discord.ButtonStyle.primary, custom_id="embassy:mgmt:requests")
    async def requests(self, interaction: discord.Interaction, _: discord.ui.Button):
        pending = await self.bot.database.collection("requests").count_documents({"active": True})
        diplomat = await self.bot.database.collection("requests").count_documents({"active": True, "state": "DIPLOMAT_REVIEW"})
        government = await self.bot.database.collection("requests").count_documents({"active": True, "state": "GOVERNMENT_REVIEW"})
        await interaction.response.send_message(
            f"**Active requests:** {pending}\n**Diplomat approvals:** {diplomat}\n**Government approvals:** {government}",
            ephemeral=True,
        )

    @discord.ui.button(label="Embassies", emoji="🏛️", style=discord.ButtonStyle.secondary, custom_id="embassy:mgmt:embassies")
    async def embassies(self, interaction: discord.Interaction, _: discord.ui.Button):
        registry = EmbassyRegistry(self.bot.database)
        active = await registry.get_active()
        if not active:
            await interaction.response.send_message("No active Embassies are registered.", ephemeral=True)
            return
        text = "**Active Embassies:**\n" + "\n".join(f"• `{e.embassy_id}` | {e.country_name}" for e in active[:50])
        await interaction.response.send_message(text, ephemeral=True)

    @discord.ui.button(label="Access", emoji="🔐", style=discord.ButtonStyle.secondary, custom_id="embassy:mgmt:access")
    async def access(self, interaction: discord.Interaction, _: discord.ui.Button):
        count = await self.bot.database.collection("embassy_assignments").count_documents({"active": True})
        await interaction.response.send_message(f"**Active assignments:** {count}", ephemeral=True)

    @discord.ui.button(label="Migration", emoji="🔄", style=discord.ButtonStyle.danger, custom_id="embassy:mgmt:migration")
    async def migration(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message(
            "Migration controls are safety-gated. Snapshot, dry-run, confirmation and rollback are required before live role changes.",
            ephemeral=True,
        )

    @discord.ui.button(label="Audit", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="embassy:mgmt:audit")
    async def audit(self, interaction: discord.Interaction, _: discord.ui.Button):
        latest = await self.bot.database.collection("audit_logs").find({}).sort("created_at", -1).limit(10).to_list(10)
        if not latest:
            text = "No audit events recorded yet."
        else:
            text = "\n".join(f"`{item.get('action', 'UNKNOWN')}` by `{item.get('actor_id', 'system')}`" for item in latest)
        await interaction.response.send_message(text, ephemeral=True)


class ForeignDiplomatView(discord.ui.View):
    def __init__(self, bot: discord.Client, *, timeout: float | None = None):
        super().__init__(timeout=timeout)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member) or not _diplomat(interaction.user):
            await interaction.response.send_message("You need the global Foreign Diplomat role to use this portal.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="My Embassies", emoji="🏛️", style=discord.ButtonStyle.primary, custom_id="embassy:diplomat:embassies")
    async def my_embassies(self, interaction: discord.Interaction, _: discord.ui.Button):
        assignments = await AccessService(self.bot.database).active_for_user(interaction.user.id)
        if not assignments:
            await interaction.response.send_message("You have no active Embassy assignments.", ephemeral=True)
            return
        registry = EmbassyRegistry(self.bot.database)
        lines = []
        for item in assignments:
            embassy = await registry.get_by_id(str(item["embassy_id"]))
            label = embassy.country_name if embassy else item["embassy_id"]
            lines.append(f"• `{item['embassy_id']}` | {label} | `{item.get('source', 'UNKNOWN')}`")
        await interaction.response.send_message("**Your active Embassies:**\n" + "\n".join(lines), ephemeral=True)

    @discord.ui.button(label="Pre-Approve", emoji="⚡", style=discord.ButtonStyle.success, custom_id="embassy:diplomat:preapprove")
    async def preapprove(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(PreApprovalModal(self.bot))

    @discord.ui.button(label="Activity", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="embassy:diplomat:activity")
    async def activity(self, interaction: discord.Interaction, _: discord.ui.Button):
        events = await self.bot.database.collection("audit_logs").find({"actor_id": interaction.user.id}).sort("created_at", -1).limit(10).to_list(10)
        text = "No activity recorded yet." if not events else "\n".join(f"`{e.get('action', 'UNKNOWN')}`" for e in events)
        await interaction.response.send_message(text, ephemeral=True)

    @discord.ui.button(label="Access", emoji="🔐", style=discord.ButtonStyle.secondary, custom_id="embassy:diplomat:access")
    async def access(self, interaction: discord.Interaction, _: discord.ui.Button):
        assignments = await AccessService(self.bot.database).active_for_user(interaction.user.id)
        await interaction.response.send_message(f"You have **{len(assignments)}** active Embassy assignment(s).", ephemeral=True)
