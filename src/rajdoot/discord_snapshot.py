from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import discord


@dataclass(frozen=True, slots=True)
class DiscordPermissionOverwrite:
    target_id: int
    target_type: str
    allow: int
    deny: int


@dataclass(frozen=True, slots=True)
class DiscordCategorySnapshot:
    id: int
    name: str
    position: int
    permission_overwrites: tuple[DiscordPermissionOverwrite, ...]


@dataclass(frozen=True, slots=True)
class DiscordChannelSnapshot:
    id: int
    name: str
    channel_type: str
    position: int
    category_id: int | None
    category_position: int | None
    permission_overwrites: tuple[DiscordPermissionOverwrite, ...]


@dataclass(frozen=True, slots=True)
class DiscordRoleSnapshot:
    id: int
    name: str
    position: int
    managed: bool
    member_count: int


@dataclass(frozen=True, slots=True)
class DiscordGuildSnapshot:
    guild_id: int
    guild_name: str
    categories: tuple[DiscordCategorySnapshot, ...]
    channels: tuple[DiscordChannelSnapshot, ...]
    roles: tuple[DiscordRoleSnapshot, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DiscordSnapshotBuilder:
    """Build a read-only snapshot from Discord's already-cached guild state.

    The snapshot intentionally performs no mutations and no per-channel fetches.
    With the guild/member intents enabled, the bot can compare this single local
    snapshot against Supabase without repeatedly calling Discord while planning.
    """

    @staticmethod
    def _overwrites(
        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite],
    ) -> tuple[DiscordPermissionOverwrite, ...]:
        result: list[DiscordPermissionOverwrite] = []
        for target, overwrite in sorted(overwrites.items(), key=lambda item: item[0].id):
            allow, deny = overwrite.pair()
            target_type = "role" if isinstance(target, discord.Role) else "member"
            result.append(
                DiscordPermissionOverwrite(
                    target_id=target.id,
                    target_type=target_type,
                    allow=allow.value,
                    deny=deny.value,
                )
            )
        return tuple(result)

    @classmethod
    def build(cls, guild: discord.Guild) -> DiscordGuildSnapshot:
        categories = tuple(
            DiscordCategorySnapshot(
                id=category.id,
                name=category.name,
                position=category.position,
                permission_overwrites=cls._overwrites(category.overwrites),
            )
            for category in sorted(guild.categories, key=lambda item: item.position)
        )

        category_positions = {category.id: category.position for category in guild.categories}
        channels = tuple(
            DiscordChannelSnapshot(
                id=channel.id,
                name=channel.name,
                channel_type=str(channel.type),
                position=channel.position,
                category_id=channel.category_id,
                category_position=(
                    category_positions.get(channel.category_id)
                    if channel.category_id is not None
                    else None
                ),
                permission_overwrites=cls._overwrites(channel.overwrites),
            )
            for channel in sorted(guild.channels, key=lambda item: (item.position, item.id))
        )

        roles = tuple(
            DiscordRoleSnapshot(
                id=role.id,
                name=role.name,
                position=role.position,
                managed=role.managed,
                member_count=len(role.members),
            )
            for role in sorted(guild.roles, key=lambda item: item.position, reverse=True)
        )

        return DiscordGuildSnapshot(
            guild_id=guild.id,
            guild_name=guild.name,
            categories=categories,
            channels=channels,
            roles=roles,
        )
