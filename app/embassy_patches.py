from __future__ import annotations

import logging
import random
from datetime import datetime, timezone

import discord

from app.config import settings
from app.cogs.embassy_flow import EmbassyFlow
from approval.workflow import Route
from access.models import AccessSource, AssignmentType
from access.discord import DiscordAccessProvisioner

logger = logging.getLogger(__name__)

WELCOME_MESSAGES = (
    "🎉 **Welcome to the Embassy family!** Your diplomatic passport has officially found its home. We are glad to have you with us!",
    "🌍 **Welcome, diplomat!** A new chapter of your diplomatic journey begins today. Your Embassy doors are open!",
    "🤝 **Welcome to your new Embassy!** Diplomacy is better with good people, and we are delighted to have you here.",
    "🏛️ **Welcome, diplomat!** Your Embassy has a new member today, and that is worth celebrating. Make yourself at home!",
    "🇮🇳 **Welcome to the diplomatic family!** Your access is granted, your Embassy awaits, and the paperwork gods are finally satisfied. Enjoy your new diplomatic home!",
    "✨ **A warm diplomatic welcome!** We hope this Embassy becomes a place for great conversations, cooperation and good memories.",
    "🎊 **The Embassy has a new diplomat!** Welcome aboard. Your diplomatic seat at the table is ready!",
    "🌟 **Welcome, diplomat!** You joined an Embassy today, and hopefully found a new corner of the community to call home. Glad to have you here!",
)

KLIPY_SURPRISE_URL = "https://klipy.com/gifs/rickroll-never-gonna-give-you-up-9"


class CuratedSurpriseView(discord.ui.View):
    """Persistent surprise button attached to Embassy welcome messages."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Click for a specially curated surprise for you",
        emoji="🎁",
        style=discord.ButtonStyle.primary,
        custom_id="embassy:curated-surprise",
    )
    async def surprise(self, interaction: discord.Interaction, _: discord.ui.Button):
        # Post the requested GIF page URL into the Embassy chat so Discord can
        # unfurl it for everyone in the Embassy channel.
        await interaction.response.send_message("🎁 Your specially curated surprise has arrived!")
        await interaction.channel.send(KLIPY_SURPRISE_URL)


def _role_mentions(guild: discord.Guild) -> str:
    mentions = []
    for role_id in (
        settings.role_president_id,
        settings.role_vice_president_id,
        settings.role_nsa_id,
        settings.role_minister_id,
        settings.role_eam_id,
    ):
        role = guild.get_role(role_id)
        if role:
            mentions.append(role.mention)
    return " ".join(dict.fromkeys(mentions))


def _welcome_embed(member: discord.Member, embassy, *, new_embassy: bool = False) -> discord.Embed:
    embed = discord.Embed(
        title="🎉 Welcome to the Embassy!",
        description=(
            f"{random.choice(WELCOME_MESSAGES)}\n\n"
            f"**New Diplomat:** {member.mention}\n"
            f"**Embassy:** {embassy.country_name}\n\n"
            "Make yourself comfortable. This is now your diplomatic home! 🏛️"
        ),
        color=discord.Color.green(),
    )
    if new_embassy:
        embed.add_field(
            name="🌱 A New Embassy Begins",
            value="This Embassy has just opened its doors, and you are its first active diplomat. That is a pretty cool first page in its history!",
            inline=False,
        )
    embed.set_footer(text="Embassy Access System • Welcome aboard")
    return embed


async def _dm_applicant(self, guild: discord.Guild, user_id: int, *, approved: bool, embassy_name: str) -> None:
    """Notify the applicant privately about the final Embassy decision."""
    try:
        member = guild.get_member(user_id)
        user = member or await self.bot.fetch_user(user_id)
        if approved:
            embed = discord.Embed(
                title="🎉 Embassy Application Accepted",
                description=(
                    f"Your Embassy access application has been **approved**.\n\n"
                    f"**Embassy:** {embassy_name}\n\n"
                    "Your diplomatic access has been granted. Welcome, diplomat! 🏛️"
                ),
                color=discord.Color.green(),
            )
        else:
            embed = discord.Embed(
                title="❌ Embassy Application Declined",
                description=(
                    f"Your Embassy access application has been **declined**.\n\n"
                    f"**Embassy:** {embassy_name}\n\n"
                    "No Embassy access has been granted. If you believe this was a mistake, please contact EAM/Admin."
                ),
                color=discord.Color.red(),
            )
        embed.set_footer(text="Rajdoot • Embassy Access System")
        await user.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException, discord.NotFound):
        logger.info("Could not DM applicant %s about Embassy decision", user_id)


async def _patched_notify_government(self, guild, request, embassy, *, revival: bool):
    channel = guild.get_channel(settings.channel_embassy_management_id)
    if not isinstance(channel, discord.TextChannel):
        raise ValueError("Embassy management channel is missing")
    reason = "Embassy exists but has no active diplomats" if revival else "Applicant requested an Embassy outside their WarEra country"
    embed = self._approval_embed(request, embassy, reason)
    mention_text = _role_mentions(guild)
    message = await channel.send(
        content=mention_text or "🏛️ Embassy Management",
        embed=embed,
        view=__import__("app.cogs.embassy_flow", fromlist=["EmbassyApprovalView"]).EmbassyApprovalView(self.bot, request["request_id"], Route.GOVERNMENT_REVIEW.value),
        allowed_mentions=discord.AllowedMentions(roles=True),
    )
    await self.db.collection("requests").update_one(
        {"request_id": request["request_id"]},
        {"$set": {"approval_message_id": message.id}},
    )


async def _patched_finalize_direct(self, interaction, request, embassy, reason: str, action: str = "REQUEST_APPROVED"):
    now = datetime.now(timezone.utc)
    is_new_embassy = "did not previously exist" in reason.lower()
    await self.db.collection("requests").update_one(
        {"request_id": request["request_id"]},
        {"$set": {
            "requested_embassy_id": embassy.embassy_id,
            "state": "APPROVED",
            "status": "APPROVED",
            "decision": "APPROVED",
            "decision_actor_id": None,
            "decision_reason": reason,
            "active": False,
            "updated_at": now,
        }},
    )
    await self.audit.log(
        action=action,
        actor_id=None,
        request_id=request["request_id"],
        embassy_id=embassy.embassy_id,
        reason=reason,
        metadata={"actor": "SYSTEM", "new_embassy": is_new_embassy},
    )
    log_content = (
        f"✅ **Embassy Access Granted**\n"
        f"**Embassy:** {embassy.country_name}\n"
        f"**Applicant:** <@{request['discord_user_id']}>\n"
        f"**Approved By:** **SYSTEM**\n"
        f"**Reason:** {reason}"
    )
    if is_new_embassy:
        log_content += "\n**New Embassy:** Yes"
    await self._log_channel(log_content)
    await self._close_request_thread(
        interaction.guild,
        request,
        f"Your Embassy access request has been **approved**.\n\n"
        f"**Embassy:** {embassy.country_name}\n"
        f"**Approved by:** **SYSTEM**\n\n"
        "Your Embassy access has been granted. Welcome, diplomat. 🇮🇳",
    )


async def _patched_log_channel(self, content: str):
    channel = self.bot.get_channel(settings.channel_embassy_request_logs_id)
    if not isinstance(channel, discord.TextChannel):
        return

    if "Embassy Access Granted" in content or "Embassy Access Approved" in content:
        lines = [line for line in content.split("\n") if line.strip()]
        embed = discord.Embed(title="🎉 Embassy Access Granted", color=discord.Color.green())
        for line in lines[1:]:
            if line.startswith("**") and ":**" in line:
                name, value = line.split(":**", 1)
                name = name.replace("**", "").strip()
                value = value.strip()
                if name and value:
                    embed.add_field(name=name, value=value, inline=True)
        is_new_embassy = any("New Embassy" in line and "Yes" in line for line in lines) or any("did not previously exist" in line for line in lines)
        embed.add_field(name="💌 Welcome", value=random.choice(WELCOME_MESSAGES), inline=False)
        if is_new_embassy:
            embed.add_field(
                name="🌱 New Embassy",
                value="This Embassy has just opened its doors, and the applicant is its first active diplomat.",
                inline=False,
            )
        embed.set_footer(text="Embassy Access System • A new diplomat has joined the family")
        content = _role_mentions(channel.guild) if is_new_embassy else None
        await channel.send(content=content, embed=embed, allowed_mentions=discord.AllowedMentions(users=True, roles=True))
        return

    await channel.send(content, allowed_mentions=discord.AllowedMentions(users=True, roles=True))


async def _patched_grant_access(self, guild, user_id: int, embassy, source: AccessSource):
    member = guild.get_member(user_id)
    channel = guild.get_channel(embassy.channel_id)
    if not isinstance(member, discord.Member) or not isinstance(channel, discord.TextChannel):
        raise ValueError("Applicant or Embassy channel is unavailable")
    await self.access.assign(user_id, embassy.embassy_id, AssignmentType.FOREIGN_DIPLOMAT, source)
    provisioner = DiscordAccessProvisioner(foreign_diplomat_role_id=settings.role_foreign_diplomat_id)
    await provisioner.grant_embassy_access(member, channel, reason=f"Embassy access granted for {embassy.country_name}")
    role = guild.get_role(settings.role_foreign_diplomat_id)
    if role:
        await provisioner.ensure_role(member, role, reason="User received Embassy access")

    eam_role = guild.get_role(settings.role_eam_id)
    eam_mention = eam_role.mention if eam_role else None
    await channel.send(
        content=eam_mention,
        embed=_welcome_embed(member, embassy, new_embassy=source is AccessSource.SPECIAL_OFFICIAL),
        view=CuratedSurpriseView(),
        allowed_mentions=discord.AllowedMentions(users=True, roles=True),
    )
    await _dm_applicant(self, guild, user_id, approved=True, embassy_name=embassy.country_name)


async def _patched_handle_own_country(self, interaction, request):
    country_id = str(request.get("verified_country_id") or "").strip()
    country_name = str(request.get("verified_country_name") or "").strip()
    embassy = await self.registry.get_by_country(country_id) if country_id else None
    if embassy is None:
        embassy = await self.registry.get_by_country(country_name)

    if embassy is None or not embassy.active:
        embassy = await self._create_embassy(interaction.guild, country_id or country_name, country_name, interaction.user.id)
        await self._grant_access(interaction.guild, interaction.user.id, embassy, AccessSource.SPECIAL_OFFICIAL)
        await self._finalize_direct(
            interaction,
            request,
            embassy,
            "Embassy did not previously exist. The applicant became the first active diplomat.",
        )
        return

    return await _ORIGINAL_HANDLE_OWN_COUNTRY(self, interaction, request)


_ORIGINAL_HANDLE_OWN_COUNTRY = EmbassyFlow._handle_own_country
EmbassyFlow._notify_government = _patched_notify_government
EmbassyFlow._finalize_direct = _patched_finalize_direct
EmbassyFlow._log_channel = _patched_log_channel
EmbassyFlow._grant_access = _patched_grant_access
EmbassyFlow._handle_own_country = _patched_handle_own_country
