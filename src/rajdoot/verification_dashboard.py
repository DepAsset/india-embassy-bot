from __future__ import annotations

import discord

from rajdoot.config import settings
from rajdoot.database import Database
from rajdoot.embassy_workflow import EmbassyStartView
from rajdoot.workflow_store import WorkflowStore


class FixedVerificationDashboardView(discord.ui.View):
    def __init__(self, database: Database) -> None:
        super().__init__(timeout=None)
        self.database = database

    @discord.ui.button(
        label="Start Access Request",
        emoji="🔐",
        style=discord.ButtonStyle.primary,
        custom_id="rajdoot:fixed:verification:start",
    )
    async def start_request(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This action is only available inside the embassy server.", ephemeral=True)
            return

        store = WorkflowStore(self.database)
        existing = await store.fetch_open_for_applicant(interaction.user.id)
        latest = await store.fetch_latest_for_applicant(interaction.user.id)
        thread = None

        if existing:
            thread_id = existing.get("request_thread_id")
            thread = interaction.guild.get_thread(int(thread_id)) if thread_id else None
            suffix = f" Continue here: {thread.mention}" if thread else " Continue in your existing request thread."
            await interaction.response.send_message(f"⏳ You already have an active access request.{suffix}", ephemeral=True)
            return

        if latest and latest.get("request_thread_id"):
            thread = interaction.guild.get_thread(int(latest["request_thread_id"]))
            if thread is not None and not thread.archived and not thread.locked:
                await interaction.response.send_message(
                    f"⏳ Your previous request thread is still open: {thread.mention}. Close that request before starting another one.",
                    ephemeral=True,
                )
                return

        parent = interaction.guild.get_channel(settings.request_channel_id or 0)
        if not isinstance(parent, discord.TextChannel):
            await interaction.response.send_message("⚠️ The access-request channel is not configured correctly.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        request = await store.create_request(interaction.user.id)
        thread = await parent.create_thread(
            name=f"access-request-{interaction.user.display_name}"[:100],
            type=discord.ChannelType.private_thread,
            invitable=False,
            auto_archive_duration=10080,
            reason="RAJDOOT Verification / Embassy Access Request",
        )
        await thread.add_user(interaction.user)
        request_id = str(request["id"])
        await store.set_flow_state(request_id, "profile_pending", request_thread_id=thread.id)
        await thread.send(
            embed=discord.Embed(
                title="🔐 Verification & Embassy Access Request",
                description=(
                    "This private request verifies your **WarEra identity** before embassy access is considered.\n\n"
                    "Start by submitting your WarEra profile."
                ),
                colour=discord.Colour.blurple(),
            ),
            view=EmbassyStartView(self.database, request_id, thread),
        )
        await store.log_audit(
            actor=interaction.user.id,
            action="EMBASSY_REQUEST_STARTED",
            target_type="request",
            target_id=request_id,
            embassy_id=None,
            result="CREATED",
            metadata={"thread_id": thread.id, "source": "verification_dashboard"},
        )
        await interaction.followup.send(f"✅ Your private verification request is ready: {thread.mention}", ephemeral=True)

    @discord.ui.button(
        label="My Request Status",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="rajdoot:fixed:verification:status",
    )
    async def status(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        request = await WorkflowStore(self.database).fetch_open_for_applicant(interaction.user.id)
        if not request:
            await interaction.response.send_message("📭 You do not have an active verification/access request.", ephemeral=True)
            return
        embed = discord.Embed(title="📋 Your Access Request", colour=discord.Colour.blurple())
        embed.add_field(name="Stage", value=str(request.get("flow_stage", "unknown")).replace("_", " ").title(), inline=True)
        embed.add_field(name="Verification", value=str(request.get("verification_status", "pending")).title(), inline=True)
        embed.add_field(name="Company Checks", value=f"{request.get('verification_attempts', 0)}/5", inline=True)
        thread_id = request.get("request_thread_id")
        thread = interaction.guild.get_thread(int(thread_id)) if interaction.guild and thread_id else None
        if thread:
            embed.add_field(name="Private Request", value=thread.mention, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def ensure_verification_dashboard(channel: discord.TextChannel, database: Database, message_id: int | None) -> discord.Message:
    embed = discord.Embed(
        title="🔐 RAJDOOT Verification & Access Request",
        description=(
            "Welcome to the Embassy Access system.\n\n"
            "Use **Start Access Request** to open a private verification workflow. "
            "Your WarEra identity is verified before any embassy access is granted.\n\n"
            "This dashboard is fixed and persistent. Use **/verification-dashboard** anytime to return here."
        ),
        colour=discord.Colour.blurple(),
    )
    if message_id:
        try:
            message = await channel.fetch_message(message_id)
            await message.edit(embed=embed, view=FixedVerificationDashboardView(database))
            return message
        except (discord.NotFound, discord.HTTPException):
            pass

    # Recover an existing fixed dashboard before creating anything. This makes the
    # dashboard singleton resilient to stale/missing database message IDs and bot restarts.
    marker = "RAJDOOT Verification & Access Request"
    try:
        bot_id = channel.guild.me.id if channel.guild.me else None
        async for candidate in channel.history(limit=100, oldest_first=True):
            if bot_id is not None and candidate.author.id != bot_id:
                continue
            if candidate.embeds and marker in (candidate.embeds[0].title or ""):
                await candidate.edit(embed=embed, view=FixedVerificationDashboardView(database))
                return candidate
    except discord.HTTPException:
        pass

    return await channel.send(embed=embed, view=FixedVerificationDashboardView(database))
