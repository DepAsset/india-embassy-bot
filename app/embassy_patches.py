from __future__ import annotations

import random
from datetime import datetime, timezone

import discord

from app.config import settings
from app.cogs.embassy_flow import EmbassyFlow
from approval.workflow import Route
from access.models import AccessSource

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
        await self._announce_new_diplomat(interaction.guild, interaction.user, embassy, new_embassy=True)
        return

    return await _ORIGINAL_HANDLE_OWN_COUNTRY(self, interaction, request)


async def _patched_announce_new_diplomat(self, guild, member, embassy, new_embassy: bool = False):
    channel = guild.get_channel(embassy.channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
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
    await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=True))


_ORIGINAL_HANDLE_OWN_COUNTRY = EmbassyFlow._handle_own_country
EmbassyFlow._notify_government = _patched_notify_government
EmbassyFlow._finalize_direct = _patched_finalize_direct
EmbassyFlow._log_channel = _patched_log_channel
EmbassyFlow._handle_own_country = _patched_handle_own_country
EmbassyFlow._announce_new_diplomat = _patched_announce_new_diplomat
