from __future__ import annotations

import discord

from rajdoot.config import settings
from rajdoot.database import Database
from rajdoot.embassy_workflow import EmbassyStartView
from rajdoot.workflow_store import WorkflowStore


STATUS_TEXT = {
    "profile_pending": "Waiting for your WarEra profile",
    "company_verification": "Verifying your WarEra company / identity",
    "embassy_selection": "Verification complete — embassy selection is next",
    "awaiting_embassy_approval": "Waiting for embassy approval",
    "awaiting_government_approval": "Waiting for government approval",
    "approved": "Approved — embassy access granted",
    "rejected": "Request declined",
    "verification_failed": "Verification failed",
    "embassy_creation_pending": "Waiting for embassy creation/reconciliation",
}


class FixedVerificationDashboardView(discord.ui.View):
    def __init__(self, database: Database) -> None:
        super().__init__(timeout=None)
        self.database = database

    @discord.ui.button(label="Start Access Request", emoji="🔐", style=discord.ButtonStyle.primary, custom_id="rajdoot:fixed:verification:start")
    async def start_request(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This action is only available inside the embassy server.", ephemeral=True)
            return
        store = WorkflowStore(self.database)
        existing = await store.fetch_open_for_applicant(interaction.user.id)
        if existing:
            await self._show_status(interaction, existing, "⏳ You already have an active access request.")
            return
        parent = interaction.guild.get_channel(settings.request_channel_id or 0)
        if not isinstance(parent, discord.TextChannel):
            await interaction.response.send_message("⚠️ The access-request channel is not configured correctly.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        request = await store.create_request(interaction.user.id)
        thread = await parent.create_thread(name=f"access-request-{interaction.user.display_name}"[:100], type=discord.ChannelType.private_thread, invitable=False, auto_archive_duration=10080, reason="RAJDOOT Verification / Embassy Access Request")
        await thread.add_user(interaction.user)
        request_id = str(request["id"])
        await store.set_flow_state(request_id, "profile_pending", request_thread_id=thread.id)
        await thread.send(
            embed=discord.Embed(
                title="🔐 Verification & Embassy Access Request",
                description="This private request verifies your **WarEra identity** before embassy access is considered.\n\nStart by submitting your WarEra profile.",
                colour=discord.Colour.blurple(),
            ),
            view=EmbassyStartView(self.database, request_id, thread),
        )
        await store.log_audit(actor=interaction.user.id, action="EMBASSY_REQUEST_STARTED", target_type="request", target_id=request_id, embassy_id=None, result="CREATED", metadata={"thread_id": thread.id, "source": "verification_dashboard"})
        await interaction.followup.send(f"✅ Your private verification request is ready: {thread.mention}", ephemeral=True)

    @discord.ui.button(label="My Request Status", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="rajdoot:fixed:verification:status")
    async def status(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        request = await WorkflowStore(self.database).fetch_open_for_applicant(interaction.user.id)
        if not request:
            await interaction.response.send_message("📭 You do not have an active verification/access request.", ephemeral=True)
            return
        await self._show_status(interaction, request)

    @discord.ui.button(label="My Embassy Access", emoji="🏛️", style=discord.ButtonStyle.success, custom_id="rajdoot:fixed:verification:access")
    async def access(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("This action is only available inside the embassy server.", ephemeral=True)
            return
        assignments = await WorkflowStore(self.database).active_assignments_for_user(interaction.user.id)
        embed = discord.Embed(title="🏛️ My Embassy Access", colour=discord.Colour.green())
        if not assignments:
            embed.description = "You currently have no active embassy assignments."
        else:
            lines = []
            for assignment in assignments:
                country = str(assignment.get("country_name") or "Unknown Embassy")
                channel_id = assignment.get("channel_id")
                channel = interaction.guild.get_channel(int(channel_id)) if channel_id else None
                destination = channel.mention if isinstance(channel, discord.TextChannel) else country
                lines.append(f"• **{country}** — {assignment.get('assignment_type', 'diplomat').replace('_', ' ').title()} — {destination}")
            embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Help / Requirements", emoji="ℹ️", style=discord.ButtonStyle.secondary, custom_id="rajdoot:fixed:verification:help")
    async def help(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        embed = discord.Embed(title="ℹ️ Verification Requirements", colour=discord.Colour.blurple())
        embed.description = (
            "**1.** Start an access request.\n"
            "**2.** Submit your WarEra profile when prompted.\n"
            "**3.** Complete the identity/company verification step.\n"
            "**4.** Select the relevant embassy.\n"
            "**5.** Wait for the required diplomatic/government approval.\n\n"
            "Approval is never granted solely because a request was submitted."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _show_status(self, interaction: discord.Interaction, request: dict, prefix: str | None = None) -> None:
        stage = str(request.get("flow_stage") or "unknown")
        verification = str(request.get("verification_status") or "pending")
        status = str(request.get("request_status") or "unknown")
        embed = discord.Embed(title="📋 Embassy Access Request Status", colour=discord.Colour.blurple())
        if prefix:
            embed.description = prefix
        embed.add_field(name="Current Stage", value=STATUS_TEXT.get(stage, stage.replace("_", " ").title()), inline=False)
        embed.add_field(name="Verification", value=verification.replace("_", " ").title(), inline=True)
        embed.add_field(name="Request State", value=status.replace("_", " ").title(), inline=True)
        embed.add_field(name="Company Checks", value=f"{request.get('verification_attempts', 0)}/{request.get('verification_max_attempts', 5)}", inline=True)
        embassy = request.get("target_embassy_id")
        if embassy:
            embed.add_field(name="Embassy", value=str(request.get("target_country_id") or embassy), inline=True)
        thread_id = request.get("request_thread_id")
        thread = interaction.guild.get_thread(int(thread_id)) if interaction.guild and thread_id else None
        if thread:
            embed.add_field(name="Private Request", value=thread.mention, inline=False)
        if request.get("last_verification_error"):
            embed.add_field(name="Latest Verification Note", value=str(request["last_verification_error"])[:1024], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def ensure_verification_dashboard(channel: discord.TextChannel, database: Database, message_id: int | None) -> discord.Message:
    embed = discord.Embed(
        title="🔐 RAJDOOT Verification & Access Request",
        description="Welcome to the Embassy Access system.\n\nUse **Start Access Request** to open a private verification workflow. Your WarEra identity is verified before embassy access is granted.\n\n**My Request Status** lets you recover the current workflow at any time. **My Embassy Access** shows assignments already granted to you.\n\nThis dashboard is fixed and persistent. Use **/verification-dashboard** anytime to return here.",
        colour=discord.Colour.blurple(),
    )
    if message_id:
        try:
            message = await channel.fetch_message(message_id)
            await message.edit(embed=embed, view=FixedVerificationDashboardView(database))
            return message
        except (discord.NotFound, discord.HTTPException):
            pass
    return await channel.send(embed=embed, view=FixedVerificationDashboardView(database))
