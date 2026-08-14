"""One-time cleanup of legacy hard-coded member access on Embassy channels.

The legacy migration created explicit Discord channel permission overwrites for
individual members. The new system must not use those member-specific grants.
This cleanup therefore removes the *entire member overwrite* from Embassy
channels. It deliberately never touches role overwrites or @everyone.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import discord

log = logging.getLogger("india-embassy-bot")


@dataclass
class CleanupResult:
    channels_scanned: int = 0
    member_overrides_found: int = 0
    overrides_removed: int = 0
    failures: int = 0
    skipped: int = 0


async def _remove_member_override_safely(
    channel: discord.abc.GuildChannel,
    target: discord.Member,
) -> None:
    """Completely remove a member-specific channel overwrite with rate-limit handling."""
    for attempt in range(6):
        try:
            # overwrite=None deletes the explicit member entry entirely.
            await channel.set_permissions(
                target,
                overwrite=None,
                reason="Remove legacy hard-coded Embassy member access",
            )
            # Permission endpoints are aggressively rate limited by Discord.
            await asyncio.sleep(0.45)
            return
        except discord.HTTPException as exc:
            if exc.status != 429 or attempt >= 5:
                raise
            retry_after = getattr(exc, "retry_after", None)
            delay = float(retry_after) if retry_after else min(2.0 * (attempt + 1), 10.0)
            log.warning(
                "Discord rate limit while removing member overwrite channel=%s member=%s; retrying in %.2fs",
                channel.id,
                target.id,
                delay,
            )
            await asyncio.sleep(delay)


async def cleanup_legacy_direct_access(guild: discord.Guild) -> CleanupResult:
    """Remove every explicit member overwrite from every Embassy channel.

    This is intentionally broader than the previous cleanup implementation:
    the old migration's member entries may no longer contain the exact three
    permission bits it originally created. The screenshots/Discord state show
    that these entries are the unwanted "hard-coded member access" itself.

    Only ``discord.Member`` targets are removed. Role overwrites (including
    Embassy Access roles, President, VP, NSA, Minister, Foreign Diplomats,
    bot/admin roles, etc.) and the @everyone overwrite are untouched.
    """
    result = CleanupResult()

    # Snapshot the channel list so Discord mutations cannot affect iteration.
    channels = [
        channel
        for channel in guild.channels
        if isinstance(channel, discord.abc.GuildChannel)
        and "embassy" in channel.name.lower()
    ]

    for channel in channels:
        result.channels_scanned += 1

        # Snapshot overwrites before changing any permissions.
        member_targets = [
            target
            for target in list(channel.overwrites)
            if isinstance(target, discord.Member)
        ]

        for target in member_targets:
            result.member_overrides_found += 1
            try:
                await _remove_member_override_safely(channel, target)
                result.overrides_removed += 1
                log.info(
                    "Removed legacy hard-coded member access channel=%s member=%s (%s)",
                    channel.id,
                    target.id,
                    target.display_name,
                )
            except (discord.Forbidden, discord.HTTPException):
                result.failures += 1
                log.exception(
                    "Failed removing legacy hard-coded member access channel=%s member=%s",
                    channel.id,
                    target.id,
                )

    return result
