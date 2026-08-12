from __future__ import annotations

import asyncio
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from app.config import settings
from app.services.requests import EmbassyRequestService
from app.cogs.dashboards import EmbassyManagementView, ForeignDiplomatView
from verification.warera_http import WarEraAPIError

logger = logging.getLogger(__name__)


def warera_profile_link(profile) -> str:
    """Return the canonical in-game name as a clickable WarEra profile link."""
    name = discord.utils.escape_markdown(str(profile.username))
    return f"[{name}]({profile.profile_url})"


class WarEraProfileModal(discord.ui.Modal, title="Embassy Verification"):
    profile = discord.ui.TextInput(label="WarEra Profile Link or ID", placeholder="https://app.warera.io/user/... or your WarEra User ID", min_length=1, max_length=200, required=True)

    def __init__(self, service: EmbassyRequestService) -> None:
        super().__init__(timeout=300)
        self.service = service

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This application can only be started inside the India server.", ephemeral=True)
            return
        parent = interaction.guild.get_channel(settings.channel_request_parent_id)
        if not isinstance(parent, discord.TextChannel):
            await interaction.response.send_message("The Embassy request channel is not configured as a text channel. Please contact an administrator.", ephemeral=True)
            return
        try:
            request_id, thread, created = await self.service.create_private_request(channel=parent, applicant=interaction.user)
            if not created:
                await interaction.response.send_message(f"You already have an active Embassy request: {thread.mention}", ephemeral=True)
                return
            await self.service.database.collection("requests").update_one({"request_id": request_id}, {"$set": {"profile_input": self.profile.value.strip()}})
            await interaction.response.send_message(f"Your private Embassy request has been created: {thread.mention}", ephemeral=True)
            message = await thread.send(
                embed=discord.Embed(
                    title="🇮🇳 Embassy Access Request",
                    description=(
                        "Your request has been created successfully.\n\n"
                        "**WarEra Profile:**\n"
                        f"`{self.profile.value.strip()}`\n\n"
                        "Click **Continue Verification** to resolve your WarEra identity and begin OTP verification."
                    ),
                    color=discord.Color.dark_red(),
                ),
                view=VerificationStartView(self.service),
            )
            await self.service.database.collection("requests").update_one(
                {"request_id": request_id},
                {"$set": {"request_message_id": message.id}},
            )
        except discord.Forbidden:
            message = "I cannot create the private request thread. Please contact an administrator."
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            logger.exception("Discord API failure while creating embassy request")
            message = "Discord returned an error while creating your request. Please try again later."
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)


class RequestPanelView(discord.ui.View):
    def __init__(self, service: EmbassyRequestService) -> None:
        super().__init__(timeout=None)
        self.service = service

    @discord.ui.button(label="Request Embassy Access", style=discord.ButtonStyle.primary, emoji="🏛️", custom_id="embassy:request-access")
    async def request_access(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(WarEraProfileModal(self.service))


class CompanyVerificationView(discord.ui.View):
    """Mobile-friendly company verification controls using the stored OTP hash."""

    WAITING_MESSAGES = (
        "🔎 **Checking your WarEra companies...**\n\nThe Embassy desk is looking for the company you just renamed.",
        "📡 **Establishing a secure connection to WarEra...**\n\nPlease wait while the company records are fetched.",
        "🗂️ **Reviewing company records...**\n\nThe bot is checking the companies you currently own.",
        "🌍 **Cross-checking your diplomatic identity...**\n\nAlmost there.",
        "🤝 **Almost there...**\n\nWarEra is being checked for the matching company name.",
    )

    def __init__(self, service: EmbassyRequestService) -> None:
        super().__init__(timeout=None)
        self.service = service

        open_companies = discord.ui.Button(
            label="Open Your Companies",
            emoji="🌐",
            style=discord.ButtonStyle.secondary,
            custom_id="embassy:open-companies",
            row=0,
        )
        open_companies.callback = self.open_companies
        self.add_item(open_companies)

        copy_otp = discord.ui.Button(
            label="Copy OTP",
            emoji="📋",
            style=discord.ButtonStyle.secondary,
            custom_id="embassy:copy-otp",
            row=0,
        )
        copy_otp.callback = self.copy_otp
        self.add_item(copy_otp)

        verify = discord.ui.Button(
            label="Verify Company",
            emoji="🔍",
            style=discord.ButtonStyle.success,
            custom_id="embassy:verify-company",
            row=1,
        )
        verify.callback = self.verify_company
        self.add_item(verify)

    async def open_companies(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("This button can only be used inside your Embassy request thread.", ephemeral=True)
            return
        request = await self.service.database.collection("requests").find_one({"thread_id": interaction.channel.id})
        if not request or request.get("discord_user_id") != interaction.user.id:
            await interaction.response.send_message("Only the applicant can open their WarEra companies.", ephemeral=True)
            return
        raw_profile = str(request.get("warera_profile_raw_url") or "").rstrip("/")
        if not raw_profile:
            user_id = str(request.get("warera_user_id") or "").strip()
            if not user_id:
                await interaction.response.send_message("The WarEra profile has not been resolved yet.", ephemeral=True)
                return
            raw_profile = f"https://app.warera.io/user/{user_id}"
        companies_url = f"{raw_profile}/companies"
        await interaction.response.send_message(
            f"🌐 **Open your WarEra companies:** {companies_url}",
            ephemeral=True,
        )

    @staticmethod
    def _otp_from_message(message: discord.Message) -> str | None:
        for embed in message.embeds:
            description = embed.description or ""
            match = re.search(r"```(?:[A-Za-z0-9_-]+)?\\s*([A-Z0-9]{4,32})\\s*```", description)
            if match:
                return match.group(1).strip()
        return None

    async def copy_otp(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("This button can only be used inside your Embassy request thread.", ephemeral=True)
            return
        request = await self.service.database.collection("requests").find_one({"thread_id": interaction.channel.id})
        if not request or request.get("discord_user_id") != interaction.user.id:
            await interaction.response.send_message("Only the applicant can access this OTP.", ephemeral=True)
            return
        otp = self._otp_from_message(interaction.message) if interaction.message else None
        if not otp:
            await interaction.response.send_message("I could not recover the OTP from this verification message. Please use the OTP shown above.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"📋 **Your OTP**\n```{otp}```\n\nUse Discord's copy control on the code block to copy it.",
            ephemeral=True,
        )

    async def _animate_wait(self, status_message: discord.Message, stop: asyncio.Event) -> None:
        index = 0
        while not stop.is_set():
            try:
                await status_message.edit(content=self.WAITING_MESSAGES[index % len(self.WAITING_MESSAGES)])
            except (discord.HTTPException, discord.NotFound):
                return
            index += 1
            try:
                await asyncio.wait_for(stop.wait(), timeout=1.8)
            except asyncio.TimeoutError:
                pass

    async def verify_company(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("This verification must be completed inside your request thread.", ephemeral=True)
            return

        request = await self.service.database.collection("requests").find_one({"thread_id": interaction.channel.id})
        if not request or request.get("discord_user_id") != interaction.user.id:
            await interaction.response.send_message("Only the applicant can verify this company.", ephemeral=True)
            return

        verify_button = next((item for item in self.children if isinstance(item, discord.ui.Button) and item.custom_id == "embassy:verify-company"), None)
        if verify_button is not None:
            verify_button.disabled = True
        await interaction.response.defer()
        try:
            await interaction.message.edit(view=self)
        except discord.HTTPException:
            logger.exception("Could not disable company verification button for %s", request["request_id"])

        status_message = await interaction.channel.send(self.WAITING_MESSAGES[0])
        stop_animation = asyncio.Event()
        animation_task = asyncio.create_task(self._animate_wait(status_message, stop_animation))

        async def finish_status(content: str) -> None:
            stop_animation.set()
            animation_task.cancel()
            try:
                await animation_task
            except asyncio.CancelledError:
                pass
            try:
                await status_message.edit(content=content)
            except (discord.HTTPException, discord.NotFound):
                pass

        complete_cog = interaction.client.get_cog("CompleteEmbassyCog")
        if complete_cog is None:
            await finish_status("⚠️ **Verification service unavailable.** Please try again later.")
            if verify_button is not None:
                verify_button.disabled = False
            await interaction.message.edit(view=self)
            return

        try:
            verified, attempts, lock_until = await complete_cog.verification.verify_company_ownership(
                str(request["request_id"]),
                interaction.user.id,
            )
        except WarEraAPIError:
            logger.exception("WarEra API error during company ownership verification for %s", request["request_id"])
            await finish_status("⚠️ **WarEra could not be checked right now.** Your attempt was not consumed. Please try again in a moment.")
            if verify_button is not None:
                verify_button.disabled = False
            await interaction.message.edit(view=self)
            return
        except ValueError as exc:
            await finish_status(f"⚠️ {exc}")
            if verify_button is not None:
                verify_button.disabled = False
            await interaction.message.edit(view=self)
            return
        except Exception:
            logger.exception("Unexpected company ownership verification error for %s", request["request_id"])
            await finish_status("⚠️ **An unexpected verification error occurred.** Please contact an administrator.")
            if verify_button is not None:
                verify_button.disabled = False
            await interaction.message.edit(view=self)
            return

        if verified:
            await finish_status(
                "✅ **WarEra Verification Complete**\n\n"
                "Your WarEra identity and company ownership have been verified.\n\n"
                "Your request can now proceed to Embassy access review."
            )
            return

        if lock_until is not None:
            await finish_status(
                f"🔒 **Verification locked.** You have used all **5 attempts**. "
                f"Try again after <t:{int(lock_until.timestamp())}:R>."
            )
            return

        if verify_button is not None:
            verify_button.disabled = False
        await interaction.message.edit(view=self)
        await finish_status(
            f"❌ **Company OTP not found.** Attempt **{attempts}/5**.\n\n"
            "Rename one of your owned WarEra companies to the OTP shown in the verification message, wait a few seconds, and click **Verify Company** again."
        )


class VerificationStartView(discord.ui.View):
    def __init__(self, service: EmbassyRequestService) -> None:
        super().__init__(timeout=None)
        self.service = service

    @discord.ui.button(label="Continue Verification", style=discord.ButtonStyle.success, emoji="🔐", custom_id="embassy:continue-verification")
    async def continue_verification(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("This verification control must be used inside your request thread.", ephemeral=True)
            return
        request = await self.service.database.collection("requests").find_one({"thread_id": interaction.channel.id})
        if not request:
            await interaction.response.send_message("This request could not be found. Please contact an administrator.", ephemeral=True)
            return
        if request.get("discord_user_id") != interaction.user.id:
            await interaction.response.send_message("Only the applicant can continue this verification.", ephemeral=True)
            return
        if request.get("state") == "VERIFIED":
            await interaction.response.send_message("This request has already been verified.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        complete_cog = interaction.client.get_cog("CompleteEmbassyCog")
        if complete_cog is None:
            await interaction.followup.send("The verification service is temporarily unavailable. Please try again later.", ephemeral=True)
            return
        try:
            profile_input = str(request.get("profile_input") or "").strip()
            if not profile_input:
                await interaction.followup.send("No WarEra profile was captured for this request. Please restart the request.", ephemeral=True)
                return
            profile = await complete_cog.verification.resolve_profile(request["request_id"], profile_input, interaction.user.id)
            otp = await complete_cog.verification.issue_company_otp(request["request_id"], interaction.user.id)
        except WarEraAPIError:
            logger.exception("WarEra API error while resolving embassy profile %s", request.get("request_id"))
            await interaction.followup.send("I could not resolve that WarEra profile. Please check the ID/link and try again.", ephemeral=True)
            return
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except Exception:
            logger.exception("Unexpected verification error for %s", request.get("request_id"))
            await interaction.followup.send("An unexpected error occurred while starting verification. Please try again later.", ephemeral=True)
            return

        official_flags = []
        if profile.is_president:
            official_flags.append("President")
        if profile.is_vice_president:
            official_flags.append("Vice President")
        if profile.is_eam_or_mofa:
            official_flags.append("EAM / Foreign Affairs")
        official_text = ", ".join(official_flags) if official_flags else "None detected"
        profile_link = warera_profile_link(profile)

        request_message_id = request.get("request_message_id")
        if request_message_id:
            try:
                request_message = await interaction.channel.fetch_message(int(request_message_id))
                resolved_embed = discord.Embed(
                    title="🇮🇳 Embassy Access Request",
                    description=(
                        "Your request has been created successfully.\n\n"
                        f"**WarEra:** {profile_link}\n\n"
                        "Your WarEra identity has been resolved. Click **Continue Verification** below to continue with company ownership verification."
                    ),
                    color=discord.Color.dark_red(),
                )
                await request_message.edit(embed=resolved_embed)
            except (discord.HTTPException, discord.NotFound):
                logger.exception("Could not update initial Embassy request message for %s", request["request_id"])

        embed = discord.Embed(
            title="🔐 WarEra Company Verification",
            description=(
                "Your WarEra identity has been resolved. Now create or rename one of your **owned companies** so its exact name matches the OTP below.\n\n"
                f"**Player:** {profile_link}\n**Country:** {profile.country_name}\n**Official status:** {official_text}\n\n"
                "**Your OTP:**\n"
                f"```{otp}```\n\n"
                "Use the **Copy OTP** button below if you are on mobile. Discord does not expose a bot API for directly writing to a user's device clipboard, so the button opens a private copyable code block.\n\n"
                "Once the company name matches the OTP, click **Verify Company**. The bot will discover your company IDs with `company.getCompanies` and resolve every company through `company.getById` before accepting the match."
            ),
            color=discord.Color.blurple(),
        )
        await interaction.channel.send(embed=embed, view=CompanyVerificationView(self.service))
        await interaction.followup.send(
            f"WarEra identity resolved as {profile_link}. An OTP was issued; follow the instructions in this request thread.",
            ephemeral=True,
        )


class EmbassyRequestsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service = EmbassyRequestService(bot.database)

    async def cog_load(self) -> None:
        self.bot.add_view(RequestPanelView(self.service))
        self.bot.add_view(VerificationStartView(self.service))
        self.bot.add_view(CompanyVerificationView(self.service))
        self.bot.add_view(EmbassyManagementView(self.bot, timeout=None))
        self.bot.add_view(ForeignDiplomatView(self.bot, timeout=None))

    @app_commands.command(name="embassy-setup", description="Install or refresh the Embassy request panel.")
    async def embassy_setup(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command is guild-only.", ephemeral=True)
            return
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("You need Manage Server to run this setup command.", ephemeral=True)
            return
        channel = interaction.guild.get_channel(settings.channel_request_parent_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("CHANNEL_REQUEST_PARENT_ID must point to a normal text channel.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await channel.send(embed=discord.Embed(title="🇮🇳 Embassy Access System", description="Need access to an Embassy? Click the button below to begin.\n\nYou will first provide your **WarEra profile link or ID**. The bot will then create a private request thread for the verification process.", color=discord.Color.dark_red()), view=RequestPanelView(self.service))
            await interaction.followup.send("Embassy request panel installed.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("I cannot send the Embassy request panel in that channel. Check View Channel and Send Messages permissions.", ephemeral=True)
        except discord.HTTPException:
            logger.exception("Discord API failure while installing embassy request panel")
            await interaction.followup.send("Discord returned an error while installing the Embassy request panel. Please check the bot permissions and try again.", ephemeral=True)

    @app_commands.command(name="embassy-dashboard", description="Open the Embassy Management Dashboard.")
    async def embassy_dashboard(self, interaction: discord.Interaction) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Guild-only command.", ephemeral=True)
            return
        allowed_roles = {settings.role_president_id, settings.role_vice_president_id, settings.role_nsa_id, settings.role_minister_id}
        if not member.guild_permissions.administrator and not any(r.id in allowed_roles for r in member.roles):
            await interaction.response.send_message("You are not authorized to use this dashboard.", ephemeral=True)
            return
        embed = discord.Embed(title="🏛️ Embassy Management", description="Central management for requests, Ambassadors, Foreign Diplomats, embassies, access, migration and maintenance.", color=discord.Color.dark_red())
        await interaction.response.send_message(embed=embed, view=EmbassyManagementView(self.bot, timeout=None))

    @app_commands.command(name="foreign-diplomat-dashboard", description="Open the Foreign Diplomat Dashboard.")
    async def foreign_diplomat_dashboard(self, interaction: discord.Interaction) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member) or not any(r.id == settings.role_foreign_diplomat_id for r in member.roles):
            await interaction.response.send_message("You need the Foreign Diplomat role to use this dashboard.", ephemeral=True)
            return
        embed = discord.Embed(title="🌍 Foreign Diplomat Portal", description="Manage only your assigned embassies, create pre-approvals for those embassies, and review your activity.", color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, view=ForeignDiplomatView(self.bot, timeout=None), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EmbassyRequestsCog(bot))
