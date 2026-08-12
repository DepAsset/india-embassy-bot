from __future__ import annotations

import re

import discord

from app.cogs.embassy_requests import CompanyVerificationView


_previous_init = CompanyVerificationView.__init__


def _extract_otp(message: discord.Message) -> str | None:
    for embed in message.embeds:
        description = embed.description or ""
        # The verification embed uses ```OTP```. Do not treat the first part
        # of the OTP as a Markdown language identifier.
        match = re.search(r"```\s*([A-Z0-9]{4,32})\s*```", description)
        if match:
            return match.group(1).strip()
    return None


def _init(self: CompanyVerificationView, service):
    _previous_init(self, service)
    self._otp_from_message = _extract_otp


CompanyVerificationView.__init__ = _init
