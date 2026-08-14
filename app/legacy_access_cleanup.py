"""One-time cleanup of legacy direct member permissions on embassy channels.

This intentionally does NOT use the old migration snapshot. The previous
migration produced an incomplete rollback snapshot, so cleanup is based on
live Discord channel permission overwrites.
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


_LEGACY_GRANTS = {
    "view_channel": True,
    "send_messages": True,
    "read_message_history": True,
}


def _looks_like_legacy_override(overwrite: discord.PermissionOverwrite) -> bool:
    return any(getattr(overwrite, name, None) is True for name in _LEGACY_GRANTS)


def _remove_legacy_bits(overwrite: discord.PermissionOverwrite) -> discord.PermissionOverwrite | None:
    data = overwrite._values.copy()
    changed = False
    for name in _LEGACY_GRANTS:
        if data.get(name) is True:
            data.pop(name, None)
            changed = True
    if not changed:
        return overwrite
    if not data:
        return None
    return discord.PermissionOverwrite(**data)


async def _set_permissions_safely(
    channel: discord.abc.GuildChannel,
    target: discord.Member,
    replacement: discord.PermissionOverwrite | None,
) -> None:
    """Apply a permission change with conservative Discord rate-limit handling."""
    # Keep mutations deliberately serialized. Discord permission endpoints are
    # heavily rate-limited and the old migration already hit HTTP 429s.
    for attempt in range(5):
        try:
            await channel.set_permissions(
                target,
                overwrite=replacement,
                reason="Remove legacy Embassy direct member access",
            )
            # Small pacing delay prevents a burst of permission PUTs across
            # dozens of Embassy channels.
            await asyncio.sleep(0.35)
            return
        except discord.HTTPException as exc:
            if exc.status != 429 or attempt >= 4:
                raise
            retry_after = getattr(exc, "retry_after", None)
            delay = float(retry_after) if retry_after else min(2.0 * (attempt + 1), 8.0)
            await asyncio.sleep(delay)


async def cleanup_legacy_direct_access(guild: discord.Guild) -> CleanupResult:
    """Remove legacy member-specific Embassy access from live Discord channels.

    Role overwrites and @everyone overwrites are never touched. Member
    overwrites are reduced by removing only the three permissions used by the
    legacy direct-access migration. Any unrelated member permissions remain.
    """
    result = CleanupResult()

    for channel in guild.channels:
        if not isinstance(channel, discord.abc.GuildChannel):
            continue
        if "embassy" not in channel.name.lower():
            continue

        result.channels_scanned += 1
        for target, overwrite in list(channel.overwrites.items()):
            if not isinstance(target, discord.Member):
                continue
            if not _looks_like_legacy_override(overwrite):
                continue

            result.member_overrides_found += 1
            replacement = _remove_legacy_bits(overwrite)
            try:
                await _set_permissions_safely(channel, target, replacement)
                result.overrides_removed += 1
            except (discord.Forbidden, discord.HTTPException):
                result.failures += 1
                log.exception(
                    "Failed removing legacy access channel=%s member=%s",
                    channel.id,
                    target.id,
                )

    return result
