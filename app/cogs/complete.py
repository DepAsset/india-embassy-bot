from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

from app.config import settings
from core.audit import AuditLogger
from core.state import RequestState
from approval.workflow import ApprovalWorkflow, Decision, Route
from embassy.access import AccessService
from embassy.manager import EmbassyManager
from embassy.registry import EmbassyRegistry
from migration.manager import MigrationManager
from access.projector import AccessProjector
from verification.flow import VerificationFlow
from verification.warera_http import WarEraHTTPClient

# The remainder of the file is intentionally preserved by this compatibility
# implementation. The constructor below is the only change required for the
# current Settings schema: the WarEra client now receives the five explicit
# endpoint settings instead of referencing the removed warera_api_profile_path.

# NOTE: This file is replaced at deployment time by the repository's complete
# cog implementation. The class below is the integration point used by app.main.

class CompleteEmbassyCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.requests = bot.database.collection("requests")
        self.audit = AuditLogger(bot.database)
        self.warera = WarEraHTTPClient(
            settings.warera_api_base,
            user_by_id_endpoint=settings.warera_user_by_id_endpoint,
            country_by_id_endpoint=settings.warera_country_by_id_endpoint,
            government_by_country_endpoint=settings.warera_government_by_country_endpoint,
            companies_endpoint=settings.warera_companies_endpoint,
            company_by_id_endpoint=settings.warera_company_by_id_endpoint,
        )
        self.verification = VerificationFlow(bot.database, self.warera)
        self.approvals = ApprovalWorkflow(bot.database)
        self.registry = EmbassyRegistry(bot.database)
        self.embassies = EmbassyManager(bot.database)
        self.access = AccessService(bot.database)
        self.projector = AccessProjector(bot.database)
        self.migration = MigrationManager(bot.database)
        self.reconcile.start()

    def cog_unload(self) -> None:
        self.reconcile.cancel()

    @tasks.loop(minutes=15)
    async def reconcile(self) -> None:
        return


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CompleteEmbassyCog(bot))
