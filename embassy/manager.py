from __future__ import annotations

from datetime import datetime, timezone

import discord

from core.audit import AuditLogger
from core.database import Database
from .registry import Embassy, EmbassyRegistry


class EmbassyManager:
    def __init__(self, database: Database) -> None:
        self.db = database
        self.registry = EmbassyRegistry(database)
        self.audit = AuditLogger(database)

    async def create_embassy(self, guild: discord.Guild, *, country_key: str, country_name: str, category: discord.CategoryChannel, actor_id: int) -> Embassy:
        key = country_key.strip().lower()
        if not key or not country_name.strip():
            raise ValueError("Country key and name are required")
        existing = await self.registry.get_by_country(key)
        if existing and existing.active:
            raise ValueError("An active embassy already exists for this country")
        channel = await guild.create_text_channel(
            name=f"embassy-{key}",
            category=category,
            topic=f"Official Embassy of {country_name.strip()} | Embassy System",
            reason=f"Embassy created by {actor_id}",
        )
        embassy = Embassy(
            embassy_id=key,
            country_key=key,
            country_name=country_name.strip(),
            channel_id=channel.id,
            category_id=category.id,
            active=True,
            archived_at=None,
        )
        await self.registry.upsert(embassy)
        await self.audit.log(action="EMBASSY_CREATED", actor_id=actor_id, embassy_id=key, metadata={"channel_id": channel.id, "country_name": country_name})
        return embassy

    async def archive_embassy(self, guild: discord.Guild, embassy_id: str, actor_id: int) -> bool:
        embassy = await self.registry.get_by_id(embassy_id)
        if not embassy or not embassy.active:
            return False
        changed = await self.registry.archive(embassy_id)
        if changed:
            channel = guild.get_channel(embassy.channel_id)
            if isinstance(channel, discord.TextChannel):
                await channel.edit(category=guild.get_channel(embassy.category_id), reason=f"Archive embassy by {actor_id}") if isinstance(guild.get_channel(embassy.category_id), discord.CategoryChannel) else None
                await channel.set_permissions(guild.default_role, view_channel=False, reason="Archived Embassy")
            await self.audit.log(action="EMBASSY_ARCHIVED", actor_id=actor_id, embassy_id=embassy_id)
        return changed

    async def restore_embassy(self, embassy_id: str, actor_id: int) -> bool:
        changed = await self.registry.restore(embassy_id)
        if changed:
            await self.audit.log(action="EMBASSY_RESTORED", actor_id=actor_id, embassy_id=embassy_id)
        return changed

    async def organize(self, guild: discord.Guild, actor_id: int) -> int:
        embassies = await self.registry.get_active()
        channels: list[discord.TextChannel] = []
        for embassy in embassies:
            channel = guild.get_channel(embassy.channel_id)
            if isinstance(channel, discord.TextChannel):
                channels.append(channel)
        channels.sort(key=lambda c: c.name.lower())
        for position, channel in enumerate(channels):
            await channel.edit(position=position, reason=f"Alphabetical Embassy organizer by {actor_id}")
        await self.audit.log(action="EMBASSIES_ORGANIZED", actor_id=actor_id, metadata={"count": len(channels)})
        return len(channels)
