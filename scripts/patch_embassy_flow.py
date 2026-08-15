from pathlib import Path
import re


def replace_once(path: str, pattern: str, replacement: str) -> None:
    p = Path(path)
    text = p.read_text()
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL | re.MULTILINE)
    if count != 1:
        raise SystemExit(f"Patch anchor not found exactly once: {path}")
    p.write_text(updated)


# 1. Verification dashboard singleton recovery.
replace_once(
    "src/rajdoot/verification_dashboard.py",
    r'''        store = WorkflowStore\(self\.database\)\n        existing = await store\.fetch_open_for_applicant\(interaction\.user\.id\)\n        if existing:\n.*?            return\n\n        parent = interaction\.guild\.get_channel\(settings\.request_channel_id or 0\)''',
    '''        store = WorkflowStore(self.database)\n        existing = await store.fetch_open_for_applicant(interaction.user.id)\n        latest = await store.fetch_latest_for_applicant(interaction.user.id)\n        thread = None\n\n        if existing:\n            thread_id = existing.get("request_thread_id")\n            thread = interaction.guild.get_thread(int(thread_id)) if thread_id else None\n            suffix = f" Continue here: {thread.mention}" if thread else " Continue in your existing request thread."\n            await interaction.response.send_message(f"⏳ You already have an active access request.{suffix}", ephemeral=True)\n            return\n\n        if latest and latest.get("request_thread_id"):\n            thread = interaction.guild.get_thread(int(latest["request_thread_id"]))\n            if thread is not None and not thread.archived and not thread.locked:\n                await interaction.response.send_message(\n                    f"⏳ Your previous request thread is still open: {thread.mention}. Close that request before starting another one.",\n                    ephemeral=True,\n                )\n                return\n\n        parent = interaction.guild.get_channel(settings.request_channel_id or 0)'''
)

replace_once(
    "src/rajdoot/verification_dashboard.py",
    r'''    if message_id:\n        try:\n            message = await channel\.fetch_message\(message_id\)\n            await message\.edit\(embed=embed, view=FixedVerificationDashboardView\(database\)\)\n            return message\n        except \(discord\.NotFound, discord\.HTTPException\):\n            pass\n    return await channel\.send\(embed=embed, view=FixedVerificationDashboardView\(database\)\)''',
    '''    if message_id:\n        try:\n            message = await channel.fetch_message(message_id)\n            await message.edit(embed=embed, view=FixedVerificationDashboardView(database))\n            return message\n        except (discord.NotFound, discord.HTTPException):\n            pass\n\n    # Recover an existing fixed dashboard before creating anything. This makes the\n    # dashboard singleton resilient to stale/missing database message IDs and bot restarts.\n    marker = "RAJDOOT Verification & Access Request"\n    try:\n        bot_id = channel.guild.me.id if channel.guild.me else None\n        async for candidate in channel.history(limit=100, oldest_first=True):\n            if bot_id is not None and candidate.author.id != bot_id:\n                continue\n            if candidate.embeds and marker in (candidate.embeds[0].title or ""):\n                await candidate.edit(embed=embed, view=FixedVerificationDashboardView(database))\n                return candidate\n    except discord.HTTPException:\n        pass\n\n    return await channel.send(embed=embed, view=FixedVerificationDashboardView(database))'''
)

# 2. Historical request lookup used to enforce the Discord-thread guard.
replace_once(
    "src/rajdoot/workflow_store.py",
    r'''    async def issue_otp\(self, request_id: str, otp_hash: str\) -> dict\[str, Any\] \| None:''',
    '''    async def fetch_latest_for_applicant(self, applicant_id: int) -> dict[str, Any] | None:\n        connection = await self._connection()\n        async with connection.cursor() as cursor:\n            await cursor.execute(\n                "select * from embassy_requests where applicant_discord_id = %s order by created_at desc limit 1",\n                (applicant_id,),\n            )\n            return await cursor.fetchone()\n\n    async def issue_otp(self, request_id: str, otp_hash: str) -> dict[str, Any] | None:'''
)

# 3. New embassy creation immediately uses the existing canonical alphabetical/category planner.
replace_once(
    "src/rajdoot/embassy_workflow.py",
    r'''from rajdoot\.database import Database\nfrom rajdoot\.embassy_access import EmbassyAccessService, is_government''',
    '''from rajdoot.database import Database\nfrom rajdoot.embassy_access import EmbassyAccessService, is_government\nfrom rajdoot.embassy_layout import EmbassyDiscordOrganizer, EmbassyLayoutPlanner'''
)

replace_once(
    "src/rajdoot/embassy_workflow.py",
    r'''            if row is None:\n                raise RuntimeError\("Embassy record creation failed"\)\n            return dict\(row\)''',
    '''            if row is None:\n                raise RuntimeError("Embassy record creation failed")\n            created = dict(row)\n\n    active_after = await database.fetch_active_embassies()\n    plan = EmbassyLayoutPlanner.plan(active_after)\n    await EmbassyDiscordOrganizer().apply_plan(guild, plan)\n    return created'''
)

# 4. No diplomat = no approval card. Own-country access is granted immediately.
replace_once(
    "src/rajdoot/embassy_workflow.py",
    r'''    await store\.set_flow_state\(\n        request_id,\n        "awaiting_embassy_approval" if own_country else "awaiting_government_approval",''',
    '''    if own_country:\n        diplomats = await store.active_embassy_members(str(embassy["id"]))\n        if not diplomats:\n            await store.set_flow_state(\n                request_id,\n                "approved_new_or_unstaffed_embassy",\n                request_status="approved",\n                government_auto_approved=True,\n                target_country_id=str(embassy.get("country_id") or country_id or ""),\n                target_embassy_id=str(embassy["id"]),\n            )\n            await EmbassyAccessService(database).grant(\n                applicant.guild,\n                applicant,\n                embassy,\n                actor_id=None,\n                assignment_type="foreign_diplomat",\n            )\n            await store.log_audit(\n                actor=applicant.id,\n                action="UNSTAFFED_EMBASSY_AUTO_APPROVED",\n                target_type="request",\n                target_id=request_id,\n                embassy_id=str(embassy["id"]),\n                result="APPROVED",\n                metadata={"reason": "no_active_diplomats"},\n            )\n            if channel:\n                await channel.send(\n                    f"🟢 **{embassy['country_name']} Embassy access granted.** "\n                    "This embassy currently has no active diplomats, so no approval step was required."\n                )\n            await close_thread(channel)\n            return\n\n    await store.set_flow_state(\n        request_id,\n        "awaiting_embassy_approval" if own_country else "awaiting_government_approval",'''
)
