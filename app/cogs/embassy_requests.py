from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from app.config import settings
from app.services.requests import EmbassyRequestService
from verification.service import VerificationService
from verification.warera import WarEraApiError, WarEraHttpClient

logger = logging.getLogger(__name__)


class WarEraProfileModal(discord.ui.Modal, title="Embassy Verification"):
    profile = discord.ui.TextInput(
        label="WarEra Profile Link or ID",
        placeholder="https://app.warera.io/user/... or your WarEra User ID",
        min_length=1,
        max_length=200,
        required=True,
    )

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

            await self.service.database.collection("requests").update_one(
                {"request_id": request_id},
                {"$set": {"profile_input": self.profile.value.strip()}},
            )
            await interaction.response.send_message(f"Your private Embassy request has been created: {thread.mention}", ephemeral=True)
            await thread.send(
                embed=discord.Embed(
                    title="🇮🇳 Embassy Access Request",
                    description=(
                        "Your request has been created successfully.\n\n"
                        "**WarEra Profile:**\n"
                        f"`{self.profile.value.strip()}`\n\n"
                        "The profile has been captured. Click **Continue Verification** to resolve your canonical WarEra identity and generate the ownership OTP."
                    ),
                    color=discord.Color.dark_red(),
                ),
                view=VerificationStartView(self.service, self.service.database),
            )
        except discord.Forbidden:
            await interaction.response.send_message("I cannot create the private request thread. Please contact an administrator.", ephemeral=True)
        except discord.HTTPException:
            logger.exception("Discord API failure while creating embassy request")
            await interaction.response.send_message("Discord returned an error while creating your request. Please try again later.", ephemeral=True)


class RequestPanelView(discord.ui.View):
    def __init__(self, service: EmbassyRequestService) -> None:
        super().__init__(timeout=None)
        self.service = service

    @discord.ui.button(label="Request Embassy Access", style=discord.ButtonStyle.primary, emoji="🏛️", custom_id="embassy:request-access")
    async def request_access(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(WarEraProfileModal(self.service))


class CompanyVerificationView(discord.ui.View):
    """One-click live company ownership check."""

    def __init__(self, database, applicant_discord_id: int, request_id: str, warera_user_id: str, otp: str) -> None:
        super().__init__(timeout=None)
        self.verifier = VerificationService(database)
        self.applicant_discord_id = applicant_discord_id
        self.request_id = request_id
        self.warera_user_id = warera_user_id
        self.otp = otp
        # Each active request gets a unique component ID, preventing cross-request dispatch.
        self.children[0].custom_id = f"embassy:verify-company:{request_id}"

    @discord.ui.button(label="Verify Company", style=discord.ButtonStyle.success, emoji="🔍", custom_id="embassy:verify-company")
    async def verify_company(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.applicant_discord_id:
            await interaction.response.send_message("Only the applicant can use this verification button.", ephemeral=True)
            return

        # Acknowledge before the external API call. This fixes Discord's 3-second interaction timeout.
        await interaction.response.defer()
        client = getattr(interaction.client, "warera", None)
        if not isinstance(client, WarEraHttpClient):
            await interaction.followup.send("The WarEra API client is not available. Please contact an administrator.", ephemeral=True)
            return

        try:
            verified, attempts, lock_until, _ = await self.verifier.verify_company_ownership(
                self.request_id,
                self.warera_user_id,
                client,
            )
        except WarEraApiError as exc:
            logger.exception("WarEra company verification failed")
            await interaction.followup.send(f"⚠️ WarEra could not be checked right now. Please try again in a moment.\n`{exc}`", ephemeral=True)
            return
        except Exception:
            logger.exception("Unexpected embassy company verification error")
            await interaction.followup.send("⚠️ An unexpected verification error occurred. Please contact an administrator.", ephemeral=True)
            return

        if verified:
            button.disabled = True
            await interaction.message.edit(view=self)
            await interaction.followup.send(
                "✅ **WarEra Verification Complete**\n\n"
                "Your WarEra identity and company ownership have been verified.\n\n"
                "Your request can now proceed to embassy access review."
            )
            return

        if lock_until is not None:
            button.disabled = True
            await interaction.message.edit(view=self)
            await interaction.followup.send(f"🔒 **Verification locked.** You have used all **5 attempts**. Try again after <t:{int(lock_until.timestamp())}:R>.")
            return

        await interaction.followup.send(
            f"❌ **Company OTP not found.** Attempt **{attempts}/5**.\n\n"
            f"Rename one of your owned WarEra companies to **`{self.otp}`**, wait a few seconds, and click **Verify Company** again."
        )


class VerificationStartView(discord.ui.View):
    """Persistent bridge from profile capture to live OTP verification."""

    def __init__(self, service: EmbassyRequestService, database) -> None:
        super().__init__(timeout=None)
        self.service = service
        self.database = database

    @discord.ui.button(label="Continue Verification", style=discord.ButtonStyle.success, emoji="🔐", custom_id="embassy:continue-verification")
    async def continue_verification(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("This verification control must be used inside your request thread.", ephemeral=True)
            return

        request = await self.database.collection("requests").find_one({"thread_id": interaction.channel.id})
        if not request:
            await interaction.response.send_message("This request could not be found. Please contact an administrator.", ephemeral=True)
            return
        if request.get("discord_user_id") != interaction.user.id:
            await interaction.response.send_message("Only the applicant can continue this verification.", ephemeral=True)
            return

        profile_input = str(request.get("profile_input", "")).strip()
        client = getattr(interaction.client, "warera", None)
        if not isinstance(client, WarEraHttpClient):
            await interaction.response.send_message("The WarEra API client is not available. Please contact an administrator.", ephemeral=True)
            return

        await interaction.response.defer()
        verifier = VerificationService(self.database)
        try:
            profile = await client.get_profile(profile_input)
            otp = await verifier.issue_otp(str(request["request_id"]))
            await self.database.collection("requests").update_one(
                {"request_id": request["request_id"]},
                {"$set": {"warera_user_id": profile.user_id, "verified_country_id": profile.country_id}},
            )
        except (WarEraApiError, ValueError) as exc:
            await interaction.followup.send(f"⚠️ I could not resolve that WarEra profile. Please check the profile link/ID and try again.\n`{exc}`", ephemeral=True)
            return
        except Exception:
            logger.exception("Unexpected WarEra profile resolution error")
            await interaction.followup.send("⚠️ WarEra profile resolution failed unexpectedly. Please contact an administrator.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🔐 WarEra Company Verification",
            description=(
                f"**Player:** {interaction.user.display_name}\n"
                f"**Country:** {profile.country_name}\n"
                f"**WarEra ID:** `{profile.user_id}`\n\n"
                "Create or rename one of your **owned WarEra companies** so its exact name matches the OTP below.\n\n"
                f"**Your OTP:** `{otp}`\n\n"
                "Once the company name matches, click **Verify Company**. The bot will query your current companies and compare their names automatically."
            ),
            color=discord.Color.blurple(),
        )
        await interaction.followup.send(
            embed=embed,
            view=CompanyVerificationView(
                self.database,
                interaction.user.id,
                str(request["request_id"]),
                profile.user_id,
                otp,
            ),
        )


class EmbassyRequestsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service = EmbassyRequestService(bot.database)

    async def cog_load(self) -> None:
        self.bot.add_view(RequestPanelView(self.service))
        self.bot.add_view(VerificationStartView(self.service, self.bot.database))

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

        await channel.send(
            embed=discord.Embed(
                title="🇮🇳 Embassy Access System",
                description=(
                    "Need access to an Embassy? Click the button below to begin.\n\n"
                    "You will first provide your **WarEra profile link or ID**. The bot will then create a private request thread for the verification process."
                ),
                color=discord.Color.dark_red(),
            ),
            view=RequestPanelView(self.service),
        )
        await interaction.response.send_message("Embassy request panel installed.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EmbassyRequestsCog(bot))
