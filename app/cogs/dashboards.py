from __future__ import annotations

from datetime import datetime, timezone
import logging
import discord
from access.models import AccessSource, AssignmentType
from access.projector import AccessProjector
from access.service import AccessService
from app.config import settings
from approval.workflow import ApprovalWorkflow, Decision, Route
from embassy.registry import EmbassyRegistry

log = logging.getLogger("india-embassy-bot.dashboard")

def _government(member):
    allowed = {settings.role_president_id, settings.role_vice_president_id, settings.role_nsa_id, settings.role_minister_id, settings.role_eam_id}
    return member.guild_permissions.administrator or any(role.id in allowed for role in member.roles)

def _diplomat(member):
    return any(role.id == settings.role_foreign_diplomat_id for role in member.roles)

def _warera_link(username, user_id):
    if not user_id: return "Unavailable"
    name = discord.utils.escape_markdown(username or user_id)
    return f"[{name}](https://app.warera.io/user/{user_id})"

class PreApprovalModal(discord.ui.Modal, title="Create Embassy Pre-Approval"):
    embassy_id = discord.ui.TextInput(label="Embassy ID", required=True, max_length=100)
    warera_user_id = discord.ui.TextInput(label="Applicant WarEra User ID", required=True, max_length=100)
    expiry_hours = discord.ui.TextInput(label="Expiry (hours)", default="72", required=False, max_length=4)
    reason = discord.ui.TextInput(label="Reason", style=discord.TextStyle.paragraph, required=False, max_length=500)
    def __init__(self, bot):
        super().__init__(timeout=300); self.bot = bot
    async def on_submit(self, interaction):
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("This action is guild-only.", ephemeral=True)
        access = AccessService(self.bot.database)
        if not await access.has_access(interaction.user.id, self.embassy_id.value.strip()):
            return await interaction.response.send_message("You can only pre-approve visitors for an Embassy where you currently have access.", ephemeral=True)
        try: hours = int(self.expiry_hours.value.strip() or "72")
        except ValueError: return await interaction.response.send_message("Expiry must be a whole number of hours.", ephemeral=True)
        if not 1 <= hours <= 720: return await interaction.response.send_message("Expiry must be between 1 and 720 hours.", ephemeral=True)
        workflow = ApprovalWorkflow(self.bot.database)
        expires = workflow.default_preapproval_expiry(hours)
        pid = await workflow.create_preapproval(embassy_id=self.embassy_id.value.strip(), diplomat_id=interaction.user.id, applicant_warera_id=self.warera_user_id.value.strip(), expires_at=expires, reason=self.reason.value.strip() or None)
        await interaction.response.send_message(f"✅ Pre-approval created.\n\n**ID:** `{pid}`\n**Embassy:** `{self.embassy_id.value.strip()}`\n**Expires:** <t:{int(expires.timestamp())}:R>", ephemeral=True)

class RequestDetailView(discord.ui.View):
    def __init__(self, bot, request_id):
        super().__init__(timeout=900); self.bot = bot; self.request_id = request_id
    async def _decide(self, interaction, decision):
        request = await self.bot.database.collection("requests").find_one({"request_id": self.request_id, "active": True})
        if not request: return await interaction.response.send_message("This request has already been handled.", ephemeral=True)
        route = Route(str(request.get("approval_route") or Route.GOVERNMENT_REVIEW.value))
        await __import__("app.cogs.embassy_flow", fromlist=["EmbassyFlow"]).EmbassyFlow(self.bot).decide(interaction, self.request_id, decision, route)
    @discord.ui.button(label="Approve", emoji="✅", style=discord.ButtonStyle.success)
    async def approve(self, interaction, _): await self._decide(interaction, Decision.APPROVED)
    @discord.ui.button(label="Decline", emoji="❌", style=discord.ButtonStyle.danger)
    async def decline(self, interaction, _): await self._decide(interaction, Decision.DECLINED)
    @discord.ui.button(label="View Thread", emoji="🧵", style=discord.ButtonStyle.secondary)
    async def thread(self, interaction, _):
        await interaction.response.defer(ephemeral=True)
        request = await self.bot.database.collection("requests").find_one({"request_id": self.request_id})
        channel = interaction.guild.get_thread(int(request["thread_id"])) if request and interaction.guild else None
        await interaction.followup.send(channel.jump_url if isinstance(channel, discord.Thread) else "Thread unavailable.", ephemeral=True)

class PendingRequestSelect(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=900); self.bot = bot
        self.select = discord.ui.Select(placeholder="Select a pending request...", custom_id="embassy:dashboard:request-select")
        self.select.callback = self.selected; self.add_item(self.select)
    async def refresh(self):
        rows = await self.bot.database.collection("requests").find({"active": True}).sort("created_at", 1).limit(25).to_list(25)
        self.select.options = [discord.SelectOption(label=str(r.get("verified_country_name") or "Unknown")[:100], description=f"{r.get('state','UNKNOWN')} • {r.get('discord_user_id','')}"[:100], value=str(r["request_id"])) for r in rows]
        self.select.disabled = not rows
    async def selected(self, interaction):
        await interaction.response.defer(ephemeral=True)
        request = await self.bot.database.collection("requests").find_one({"request_id": self.select.values[0], "active": True})
        if not request: return await interaction.followup.send("That request is no longer pending.", ephemeral=True)
        embassy = await EmbassyRegistry(self.bot.database).get_by_id(str(request.get("requested_embassy_id") or ""))
        embed = discord.Embed(title="📨 Request Details", color=discord.Color.orange())
        embed.add_field(name="Applicant", value=f"<@{request.get('discord_user_id')}>", inline=True)
        embed.add_field(name="WarEra", value=_warera_link(request.get("warera_username"), request.get("warera_user_id")), inline=True)
        embed.add_field(name="Country", value=str(request.get("verified_country_name") or "Unknown"), inline=True)
        embed.add_field(name="Requested Embassy", value=embassy.country_name if embassy else "Unknown", inline=True)
        embed.add_field(name="Verification", value=str(request.get("state") or "Unknown"), inline=True)
        embed.add_field(name="Route", value=str(request.get("approval_route") or "Unknown"), inline=True)
        await interaction.followup.send(embed=embed, view=RequestDetailView(self.bot, self.select.values[0]), ephemeral=True)

class EmbassyDirectoryView(discord.ui.View):
    def __init__(self, bot, page=0, filter_name="all"):
        super().__init__(timeout=900); self.bot=bot; self.page=page; self.filter_name=filter_name
        self.select=discord.ui.Select(placeholder="Filter Embassy Directory", options=[discord.SelectOption(label=x[0], value=x[1], default=filter_name==x[1]) for x in [("All","all"),("Active","active"),("No Diplomats","empty"),("Pending Requests","pending")]], custom_id="embassy:dashboard:directory-filter")
        self.select.callback=self.filter; self.add_item(self.select)
        self.prev=discord.ui.Button(label="Previous", style=discord.ButtonStyle.secondary, custom_id="embassy:dashboard:directory-prev", row=1); self.next=discord.ui.Button(label="Next", style=discord.ButtonStyle.secondary, custom_id="embassy:dashboard:directory-next", row=1)
        self.prev.callback=lambda i:self.turn(i,-1); self.next.callback=lambda i:self.turn(i,1); self.add_item(self.prev); self.add_item(self.next)
    async def _data(self):
        result=[]; access=AccessService(self.bot.database)
        for e in await EmbassyRegistry(self.bot.database).get_active():
            d=await access.active_for_embassy(e.embassy_id); p=await self.bot.database.collection("requests").count_documents({"active":True,"requested_embassy_id":e.embassy_id})
            if self.filter_name=="empty" and d: continue
            if self.filter_name=="pending" and not p: continue
            result.append((e,len(d),p))
        return result
    async def render(self, interaction):
        rows=await self._data(); pages=max(1,(len(rows)+24)//25); self.page=max(0,min(self.page,pages-1)); chunk=rows[self.page*25:(self.page+1)*25]
        embed=discord.Embed(title="📋 Embassy Directory", description="\n".join(f"**{e.country_name}** 🟢 • {d} diplomat(s) • {p} pending" for e,d,p in chunk) or "No Embassies match this filter.", color=discord.Color.blurple()); embed.set_footer(text=f"Page {self.page+1}/{pages}")
        self.prev.disabled=self.page==0; self.next.disabled=self.page>=pages-1
        await interaction.edit_original_response(embed=embed, view=self)
    async def filter(self, interaction):
        await interaction.response.defer(ephemeral=True); self.filter_name=self.select.values[0]; self.page=0; await self.render(interaction)
    async def turn(self, interaction, delta):
        await interaction.response.defer(ephemeral=True); self.page+=delta; await self.render(interaction)

class ManageDiplomatsView(discord.ui.View):
    def __init__(self, bot, mode):
        super().__init__(timeout=900); self.bot=bot; self.mode=mode
        self.user=discord.ui.UserSelect(placeholder="Select an Ambassador", custom_id=f"embassy:dashboard:{mode}:user"); self.user.callback=self.user_selected; self.add_item(self.user)
    async def user_selected(self, interaction):
        await interaction.response.defer(ephemeral=True)
        member=interaction.guild.get_member(self.user.values[0].id) if interaction.guild else None; role=interaction.guild.get_role(settings.role_ambassador_id) if interaction.guild else None
        if not member or not role or role not in member.roles: return await interaction.followup.send("The selected user must have the **Ambassador** role.", ephemeral=True)
        embassies=await EmbassyRegistry(self.bot.database).get_active()
        if not embassies: return await interaction.followup.send("There are no active Embassies available.", ephemeral=True)
        select=discord.ui.Select(placeholder="Select one or more Embassies", min_values=1, max_values=min(25,len(embassies)), options=[discord.SelectOption(label=e.country_name[:100],value=e.embassy_id) for e in embassies[:25]], custom_id=f"embassy:dashboard:{self.mode}:embassies")
        confirm=discord.ui.Button(label="Confirm",emoji="✅",style=discord.ButtonStyle.success,custom_id=f"embassy:dashboard:{self.mode}:confirm"); view=discord.ui.View(timeout=900); view.add_item(select); view.add_item(confirm)
        async def apply(i):
            await i.response.defer(ephemeral=True); service=AccessService(self.bot.database); projector=AccessProjector(self.bot.database); changed=failed=0
            for eid in select.values:
                try:
                    if self.mode=="assign":
                        await service.assign(member.id,eid,AssignmentType.AMBASSADOR,AccessSource.GOVERNMENT_OVERRIDE,assigned_by=i.user.id); await projector.grant(i.guild,member.id,eid,i.user.id,"Embassy Dashboard assignment"); changed+=1
                    else:
                        result=await service.revoke(member.id,eid,revoked_by=i.user.id,reason="Embassy Dashboard revocation",assignment_type=AssignmentType.AMBASSADOR)
                        if result.revoked: await projector.revoke(i.guild,member.id,eid,i.user.id,"Embassy Dashboard revocation"); changed+=1
                except Exception: failed+=1
            await projector.reconcile_member(i.guild,member.id); await i.followup.send(f"✅ Completed **{changed}** • Failed **{failed}**",ephemeral=True)
        confirm.callback=apply; await interaction.followup.send("Choose Embassy access, then confirm.",view=view,ephemeral=True)

class EmbassyManagementView(discord.ui.View):
    def __init__(self, bot, *, timeout=None): super().__init__(timeout=timeout); self.bot=bot
    async def interaction_check(self, interaction):
        if not isinstance(interaction.user,discord.Member) or not _government(interaction.user):
            await interaction.response.send_message("You are not authorized to use Embassy Management.",ephemeral=True); return False
        await interaction.response.defer(ephemeral=True); return True
    async def on_error(self, interaction, error, item):
        log.exception("Dashboard interaction failed", exc_info=error)
        try: await interaction.followup.send("⚠️ The dashboard action failed. Check the bot logs.",ephemeral=True)
        except discord.HTTPException: pass
    @discord.ui.button(label="Pending Requests",emoji="📨",style=discord.ButtonStyle.primary,custom_id="embassy:mgmt:requests",row=0)
    async def requests(self,interaction,_):
        view=PendingRequestSelect(self.bot); await view.refresh(); count=await self.bot.database.collection("requests").count_documents({"active":True}); await interaction.followup.send(embed=discord.Embed(title="📨 Pending Requests",description=f"Pending Requests: **{count}**",color=discord.Color.orange()),view=view,ephemeral=True)
    @discord.ui.button(label="Manage Embassies",emoji="🏛️",style=discord.ButtonStyle.secondary,custom_id="embassy:mgmt:embassies",row=0)
    async def embassies(self,interaction,_): await interaction.followup.send(embed=discord.Embed(title="🏛️ Manage Embassies",description="Embassy directory and live Embassy status.",color=discord.Color.blurple()),view=EmbassyDirectoryView(self.bot),ephemeral=True)
    @discord.ui.button(label="Manage Diplomats",emoji="👤",style=discord.ButtonStyle.secondary,custom_id="embassy:mgmt:diplomats",row=0)
    async def diplomats(self,interaction,_):
        view=discord.ui.View(timeout=900); a=discord.ui.Button(label="Assign Embassy Access",emoji="➕",style=discord.ButtonStyle.success,custom_id="embassy:mgmt:diplomats:assign"); r=discord.ui.Button(label="Remove Embassy Access",emoji="➖",style=discord.ButtonStyle.danger,custom_id="embassy:mgmt:diplomats:remove")
        a.callback=lambda i:i.response.send_message("Select an Ambassador:",view=ManageDiplomatsView(self.bot,"assign"),ephemeral=True); r.callback=lambda i:i.response.send_message("Select an Ambassador:",view=ManageDiplomatsView(self.bot,"remove"),ephemeral=True); view.add_item(a); view.add_item(r); await interaction.followup.send("👤 **Manage Diplomats**",view=view,ephemeral=True)
    @discord.ui.button(label="Embassy Directory",emoji="📋",style=discord.ButtonStyle.secondary,custom_id="embassy:mgmt:directory",row=1)
    async def directory(self,interaction,_): await interaction.followup.send(embed=discord.Embed(title="📋 Embassy Directory",description="Use the filters below to browse all active Embassies.",color=discord.Color.blurple()),view=EmbassyDirectoryView(self.bot),ephemeral=True)
    @discord.ui.button(label="Statistics",emoji="📊",style=discord.ButtonStyle.secondary,custom_id="embassy:mgmt:stats",row=1)
    async def stats(self,interaction,_):
        db=self.bot.database; total=await db.collection("embassies").count_documents({}); active=await db.collection("embassies").count_documents({"active":True}); diplomats=await db.collection("embassy_assignments").count_documents({"active":True}); pending=await db.collection("requests").count_documents({"active":True}); today=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0); approved=await db.collection("approval_decisions").count_documents({"decision":"APPROVED","decided_at":{"$gte":today}}); declined=await db.collection("approval_decisions").count_documents({"decision":"DECLINED","decided_at":{"$gte":today}})
        e=discord.Embed(title="📊 Diplomatic Statistics",color=discord.Color.blurple()); [e.add_field(name=n,value=v,inline=True) for n,v in [("Total Embassies",str(total)), ("Active Embassies",str(active)), ("Inactive Embassies",str(total-active)), ("Foreign Diplomats",str(diplomats)), ("Pending Requests",str(pending)), ("Approved Today",str(approved)), ("Declined Today",str(declined))]]; await interaction.followup.send(embed=e,ephemeral=True)
    @discord.ui.button(label="Logs",emoji="📜",style=discord.ButtonStyle.secondary,custom_id="embassy:mgmt:logs",row=1)
    async def logs(self,interaction,_):
        events=await self.bot.database.collection("audit_logs").find({}).sort("created_at",-1).limit(15).to_list(15); e=discord.Embed(title="📜 Embassy Logs",color=discord.Color.dark_grey()); e.description="\n".join(f"`{x.get('action','UNKNOWN')}` • actor `{x.get('actor_id','system')}`" for x in events) or "No audit events recorded yet."; await interaction.followup.send(embed=e,ephemeral=True)
    @discord.ui.button(label="Migration / Reconcile",emoji="🔄",style=discord.ButtonStyle.danger,custom_id="embassy:mgmt:migration",row=2)
    async def migration(self,interaction,_):
        states=await self.bot.database.collection("migration_state").find({}).sort("completed_at",-1).limit(10).to_list(10); assignments=await self.bot.database.collection("embassy_assignments").count_documents({"active":True}); e=discord.Embed(title="🔄 Migration & Access Health",color=discord.Color.orange()); e.description="\n".join(f"`{x.get('migration_id')}` • inserted {x.get('inserted',0)} • updated {x.get('updated',0)} • missing channels {x.get('missing_channels',0)}" for x in states) or "No migration record found."; e.add_field(name="Active assignments",value=str(assignments),inline=False); await interaction.followup.send(embed=e,ephemeral=True)

class ForeignDiplomatView(discord.ui.View):
    def __init__(self, bot, *, timeout=None): super().__init__(timeout=timeout); self.bot=bot
    async def interaction_check(self,interaction):
        if not isinstance(interaction.user,discord.Member) or not _diplomat(interaction.user): await interaction.response.send_message("You need the global Foreign Diplomat role to use this portal.",ephemeral=True); return False
        await interaction.response.defer(ephemeral=True); return True
    async def on_error(self,interaction,error,item):
        log.exception("Diplomat dashboard interaction failed",exc_info=error)
        try: await interaction.followup.send("⚠️ The dashboard action failed. Check the bot logs.",ephemeral=True)
        except discord.HTTPException: pass
    @discord.ui.button(label="My Diplomatic Profile",emoji="👤",style=discord.ButtonStyle.primary,custom_id="embassy:diplomat:profile",row=0)
    async def profile(self,interaction,_):
        assignments=await AccessService(self.bot.database).active_for_user(interaction.user.id); latest=await self.bot.database.collection("requests").find_one({"discord_user_id":interaction.user.id,"warera_user_id":{"$exists":True}},sort=[("updated_at",-1)]); e=discord.Embed(title="🤝 Diplomat Profile",color=discord.Color.blurple()); e.add_field(name="Discord",value=interaction.user.mention,inline=True); e.add_field(name="WarEra",value=_warera_link((latest or {}).get("warera_username"),(latest or {}).get("warera_user_id")),inline=True); e.add_field(name="Country",value=str((latest or {}).get("verified_country_name") or "Unknown"),inline=True); e.add_field(name="Position",value="Ambassador" if any(r.id==settings.role_ambassador_id for r in interaction.user.roles) else "Foreign Diplomat",inline=True); registry=EmbassyRegistry(self.bot.database); names=[]
        for a in assignments:
            embassy=await registry.get_by_id(str(a["embassy_id"]));
            if embassy: names.append(f"• {embassy.country_name}")
        e.add_field(name="Embassy Access",value="\n".join(names) or "None",inline=False); await interaction.followup.send(embed=e,ephemeral=True)
    @discord.ui.button(label="Embassy Members",emoji="👥",style=discord.ButtonStyle.secondary,custom_id="embassy:diplomat:members",row=0)
    async def members(self,interaction,_):
        assignments=await AccessService(self.bot.database).active_for_user(interaction.user.id); registry=EmbassyRegistry(self.bot.database); lines=[]
        for a in assignments:
            embassy=await registry.get_by_id(str(a["embassy_id"]));
            if embassy: lines.append(f"**{embassy.country_name}** • {len(await AccessService(self.bot.database).active_for_embassy(embassy.embassy_id))} active diplomat(s)")
        await interaction.followup.send("\n".join(lines) or "You have no Embassy assignments.",ephemeral=True)
    @discord.ui.button(label="Pre-Approve Visitor",emoji="⚡",style=discord.ButtonStyle.success,custom_id="embassy:diplomat:preapprove",row=1)
    async def preapprove(self,interaction,_):
        # A deferred interaction cannot open a modal. Present a second button which can.
        b=discord.ui.Button(label="Open Pre-Approval Form",emoji="⚡",style=discord.ButtonStyle.success,custom_id="embassy:diplomat:preapprove:open")
        async def open_modal(i): await i.response.send_modal(PreApprovalModal(self.bot))
        b.callback=open_modal; v=discord.ui.View(timeout=300); v.add_item(b); await interaction.followup.send("Open the form below to pre-approve a visitor.",view=v,ephemeral=True)
    @discord.ui.button(label="Embassy Information",emoji="📋",style=discord.ButtonStyle.secondary,custom_id="embassy:diplomat:info",row=1)
    async def info(self,interaction,_):
        assignments=await AccessService(self.bot.database).active_for_user(interaction.user.id); registry=EmbassyRegistry(self.bot.database); lines=[]
        for a in assignments:
            embassy=await registry.get_by_id(str(a["embassy_id"]));
            if embassy: lines.append(f"**{embassy.country_name} Embassy** • <#{embassy.channel_id}>")
        await interaction.followup.send("\n".join(lines) or "No Embassy information available.",ephemeral=True)

async def ensure_dashboards(bot, guild):
    configs=[(settings.channel_embassy_management_id,"admin","🏛️ EMBASSY MANAGEMENT","Manage India's diplomatic missions, Embassy access and foreign diplomats.",EmbassyManagementView(bot,timeout=None)),(settings.channel_foreign_diplomat_dashboard_id,"diplomat","🤝 DIPLOMATIC DASHBOARD","Manage only the Embassies you have active access to.",ForeignDiplomatView(bot,timeout=None))]
    state=bot.database.collection("dashboard_state")
    for channel_id,key,title,description,view in configs:
        channel=guild.get_channel(channel_id)
        if not isinstance(channel,discord.TextChannel): continue
        existing=await state.find_one({"key":key}); message=None
        if existing and existing.get("message_id"):
            try: message=await channel.fetch_message(int(existing["message_id"]))
            except discord.HTTPException: message=None
        e=discord.Embed(title=title,description=description,color=discord.Color.dark_red() if key=="admin" else discord.Color.blurple())
        if key=="admin":
            for n,v in [("📨 Pending Requests","Review Embassy applications and approvals."),("🏛️ Manage Embassies","Directory, status and Embassy details."),("👤 Manage Diplomats","Assign or revoke direct Embassy access."),("📊 Statistics","Live diplomatic statistics."),("📜 Logs","Audit trail of Embassy actions.")]: e.add_field(name=n,value=v,inline=True)
        else: e.add_field(name="Your Access",value="Only your active Embassy assignments are available here.",inline=False); e.add_field(name="Pre-Approve Visitor",value="Pre-approve visitors for your own Embassies only.",inline=True)
        if message: await message.edit(embed=e,view=view)
        else: message=await channel.send(embed=e,view=view)
        bot.add_view(view,message_id=message.id)
        await state.update_one({"key":key},{"$set":{"message_id":message.id,"channel_id":channel.id,"updated_at":datetime.now(timezone.utc)}},upsert=True)
