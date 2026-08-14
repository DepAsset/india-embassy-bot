"""One-time cleanup of legacy direct member permissions on embassy channels.

This intentionally does NOT use the old migration snapshot.  The previous
migration may have produced an incomplete snapshot, so cleanup is based on
live Discord channel permission overwrites and the known legacy embassy role
mapping.
"""

from __future__ import annotations

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


# Permissions that the legacy direct-access migration granted.  We only remove
# an overwrite when it is a member overwrite and contains one of these grants.
# Other member-specific permissions are preserved.
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


async def cleanup_legacy_direct_access(guild: discord.Guild) -> CleanupResult:
    """Remove legacy member-specific embassy access from live Discord channels.

    Role overwrites and @everyone overwrites are never touched.  Member
    overwrites that contain the legacy grants are either reduced to unrelated
    permissions or removed entirely.
    """
    result = CleanupResult()

    for channel in guild.channels:
        if not isinstance(channel, discord.abc.GuildChannel):
            continue
        # Only channels conventionally belonging to an embassy are considered.
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
                if replacement is None:
                    await channel.set_permissions(target, overwrite=None,
                                                  reason="Remove legacy Embassy direct member access")
                else:
                    await channel.set_permissions(target, overwrite=replacement,
                                                  reason="Remove legacy Embassy direct member access")
                result.overrides_removed += 1
            except (discord.Forbidden, discord.HTTPException) as exc:
                result.failures += 1
                log.exception("Failed removing legacy access channel=%s member=%s", channel.id, target.id, exc_info=exc)

    return result
