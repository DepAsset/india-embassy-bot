from __future__ import annotations
from datetime import datetime, timezone
import discord
from app.config import settings
from access.projector import AccessProjector
from access.models import AccessSource, AssignmentType
from access.service import AccessService
from approval.workflow import ApprovalWorkflow, Decision
from app.cogs.embassy_flow import EmbassyFlow
from app.cogs.dashboards import EmbassyManagementView, ForeignDiplomatView
from app.cogs.embassy_requests import EmbassyRequestsCog
from embassy.registry import EmbassyRegistry


def gov(m):
    ids={settings.role_president_id,settings.role_vice_president_id,settings.role_nsa_id,settings.role_minister_id,settings.role_eam_id}
    return isinstance(m,discord.Member) and (m.guild_permissions.administrator or any(r.id in ids for r in m.roles))
def diplomat(m): return isinstance(m,discord.Member) and any(r.id==settings.role_foreign_diplomat_id for r in m.roles)
def eam(m): return isinstance(m,discord.Member) and (m.guild_permissions.administrator or any(r.id==settings.role_eam_id for r in m.roles))

async def requests_page(i,bot):
    rs=await bot.database.collection('requests').find({'active':True}).sort('created_at',1).limit(25).to_list(25)
    e=discord.Embed(title='📨 Pending Requests',description=f'Pending Requests: **{len(rs)}**',color=discord.Color.orange())
    if rs:e.add_field(name='Queue',value='\n'.join(f"**{r.get('verified_country_name','Unknown')}** • <@{r.get('discord_user_id')}> • `{r.get('approval_route',r.get('state','UNKNOWN'))}`" for r in rs),inline=False)
    v=discord.ui.View(timeout=600)
    if rs:
        s=discord.ui.Select(placeholder='Select a request...',options=[discord.SelectOption(label=str(r.get('verified_country_name') or 'Unknown')[:100],description=str(r.get('state') or 'UNKNOWN'),value=str(r['request_id'])) for r in rs]);s.callback=lambda x: request_detail(x,bot);v.add_item(s)
    await i.response.send_message(embed=e,view=v,ephemeral=True)

async def request_detail(i,bot):
    rid=i.data['values'][0];r=await bot.database.collection('requests').find_one({'request_id':rid})
    if not r:return await i.response.send_message('Request not found.',ephemeral=True)
    emb=await EmbassyRegistry(bot.database).get_by_id(str(r.get('requested_embassy_id') or ''))
    e=discord.Embed(title='Request Details',color=discord.Color.orange())
    for n,val in [('Applicant',f"<@{r.get('discord_user_id')}> (`{r.get('discord_user_id')}`)"),('WarEra Profile',str(r.get('warera_profile_url') or r.get('warera_profile_raw_url') or 'Unavailable')),('Country',str(r.get('verified_country_name') or 'Unknown')),('Requested Embassy',emb.country_name if emb else str(r.get('requested_embassy_id') or 'Unknown')),('Verification Status',str(r.get('state') or 'Unknown')),('Government Status',str(r.get('official_flags') or 'None')),('Pre-Approval Status',str(r.get('approval_route') or 'None')),('Current Status',str(r.get('status') or r.get('state') or 'Unknown'))]: e.add_field(name=n,value=val,inline=n not in ('Applicant','WarEra Profile','Current Status'))
    v=discord.ui.View(timeout=600)
    for label,decision,style in [('Approve',Decision.APPROVED,discord.ButtonStyle.success),('Decline',Decision.DECLINED,discord.ButtonStyle.danger)]:
        b=discord.ui.Button(label=label,style=style);b.callback=lambda x,d=decision: decide_request(x,bot,rid,d);v.add_item(b)
    b=discord.ui.Button(label='View Thread',emoji='🧵');b.callback=lambda x:view_thread(x,bot,r);v.add_item(b)
    await i.response.send_message(embed=e,view=v,ephemeral=True)

async def decide_request(i,bot,rid,decision):
    if not gov(i.user):return await i.response.send_message('You are not authorized.',ephemeral=True)
    r=await bot.database.collection('requests').find_one({'request_id':rid,'active':True})
    if not r:return await i.response.send_message('This request is already closed.',ephemeral=True)
    route='GOVERNMENT_REVIEW' if eam(i.user) else str(r.get('approval_route') or 'FOREIGN_DIPLOMAT')
    await EmbassyFlow(bot).decide(i,rid,decision,route)
async def view_thread(i,bot,r):
    ch=i.guild.get_thread(int(r['thread_id'])) if i.guild else None
    await i.response.send_message(ch.jump_url if isinstance(ch,discord.Thread) else 'Thread unavailable.',ephemeral=True)

class EmbassyList(discord.ui.View):
    def __init__(self,bot,page=0):super().__init__(timeout=600);self.bot=bot;self.page=page
    async def send(self,i):
        es=await EmbassyRegistry(self.bot.database).get_active();pages=max(1,(len(es)+24)//25);self.page=max(0,min(self.page,pages-1));chunk=es[self.page*25:(self.page+1)*25]
        lines=[]
        for x in chunk: lines.append(f"{x.country_name} • {'🟢' if await AccessService(self.bot.database).active_for_embassy(x.embassy_id) else '⚪'}")
        e=discord.Embed(title='📋 Embassy Directory',description='\n'.join(lines) or 'No active Embassies.',color=discord.Color.blurple());e.set_footer(text=f'Page {self.page+1}/{pages} • Active: {len(es)}')
        v=discord.ui.View(timeout=600)
        if chunk:
            s=discord.ui.Select(placeholder='Select an Embassy...',options=[discord.SelectOption(label=x.country_name[:100],value=x.embassy_id) for x in chunk]);s.callback=lambda z:self.details(z);v.add_item(s)
        p=discord.ui.Button(label='Previous',disabled=self.page==0);n=discord.ui.Button(label='Next',disabled=self.page>=pages-1);p.callback=lambda z:self.turn(z,-1);n.callback=lambda z:self.turn(z,1);v.add_item(p);v.add_item(n)
        await i.response.send_message(embed=e,view=v,ephemeral=True)
    async def turn(self,i,d):self.page+=d;await self.send(i)
    async def details(self,i):
        eid=i.data['values'][0];e=await EmbassyRegistry(self.bot.database).get_by_id(eid);a=await AccessService(self.bot.database).active_for_embassy(eid);p=await self.bot.database.collection('requests').count_documents({'active':True,'requested_embassy_id':eid});pre=await self.bot.database.collection('preapprovals').count_documents({'active':True,'embassy_id':eid})
        x=discord.Embed(title=f'🏛️ {e.country_name} Embassy',color=discord.Color.green());x.add_field(name='Status',value='🟢 Active');x.add_field(name='Channel',value=f'<#{e.channel_id}>');x.add_field(name='Active Diplomats',value=str(len(a)));x.add_field(name='Pending Requests',value=str(p));x.add_field(name='Pre-Approvals',value=str(pre));x.add_field(name='Embassy ID',value=f'`{eid}`',inline=False);await i.response.send_message(embed=x,ephemeral=True)

class UserAccess(discord.ui.View):
    def __init__(self,bot,mode):super().__init__(timeout=600);self.bot=bot;self.mode=mode;s=discord.ui.UserSelect(placeholder='Select an Ambassador...');s.callback=self.pick;self.add_item(s)
    async def pick(self,i):
        m=i.guild.get_member(self.children[0].values[0].id);ar=i.guild.get_role(settings.role_ambassador_id)
        if not m or not ar or ar not in m.roles:return await i.response.send_message('The selected user must have the **Ambassador** role.',ephemeral=True)
        es=await EmbassyRegistry(self.bot.database).get_active();s=discord.ui.Select(placeholder='Select Embassies...',min_values=1,max_values=min(25,len(es)),options=[discord.SelectOption(label=e.country_name[:100],value=e.embassy_id) for e in es]);v=discord.ui.View(timeout=600);v.add_item(s);b=discord.ui.Button(label='Confirm',style=discord.ButtonStyle.success);v.add_item(b);b.callback=lambda x:apply_access(x,self.bot,m,self.mode,s);await i.response.send_message('Select one or more Embassies, then Confirm.',view=v,ephemeral=True)

async def apply_access(i,bot,m,mode,s):
    ids=list(s.values);svc=AccessService(bot.database);proj=AccessProjector(bot.database);changed=failed=0
    for eid in ids:
        try:
            if mode=='assign':
                r=await svc.assign(m.id,eid,AssignmentType.AMBASSADOR,AccessSource.GOVERNMENT_OVERRIDE,assigned_by=i.user.id);await proj.grant(i.guild,m.id,eid,i.user.id,'Embassy Dashboard manual assignment');changed+=int(r.created)
            else:
                r=await svc.revoke(m.id,eid,revoked_by=i.user.id,reason='Embassy Dashboard manual revocation',assignment_type=AssignmentType.AMBASSADOR)
                if r.revoked:await proj.revoke(i.guild,m.id,eid,i.user.id,'Embassy Dashboard manual revocation');changed+=1
        except Exception:failed+=1
    role=i.guild.get_role(settings.role_foreign_diplomat_id)
    if mode=='assign' and role and role not in m.roles:await m.add_roles(role,reason='Embassy Dashboard manual access')
    if mode=='remove' and not await svc.active_for_user(m.id) and role and role in m.roles:await m.remove_roles(role,reason='No Embassy access remains')
    await i.response.send_message(f'✅ Changed: **{changed}** • Failed: **{failed}**',ephemeral=True)

async def diplomat_profile(i,bot):
    m=i.guild.get_member(i.data['values'][0].id);a=await AccessService(bot.database).active_for_user(m.id);r=EmbassyRegistry(bot.database);names=[]
    for z in a:
        e=await r.get_by_id(str(z['embassy_id']));names.append(e.country_name if e else z['embassy_id'])
    x=discord.Embed(title='🤝 Diplomat Profile',color=discord.Color.blurple());x.add_field(name='Discord',value=m.mention);x.add_field(name='Position',value='Ambassador' if any(r.id==settings.role_ambassador_id for r in m.roles) else 'Foreign Diplomat');x.add_field(name='Foreign Diplomat',value='✅' if diplomat(m) else '❌');x.add_field(name='Embassy Access',value='\n'.join(f'• {n}' for n in names) or 'None',inline=False);await i.response.send_message(embed=x,ephemeral=True)

class ManageDiplomats(discord.ui.View):
    def __init__(self,bot):super().__init__(timeout=600);self.bot=bot
    @discord.ui.button(label='Assign Embassy Access',emoji='➕',style=discord.ButtonStyle.success)
    async def assign(self,i,_):await i.response.send_message('Select an Ambassador:',view=UserAccess(self.bot,'assign'),ephemeral=True)
    @discord.ui.button(label='Remove Embassy Access',emoji='➖',style=discord.ButtonStyle.danger)
    async def remove(self,i,_):await i.response.send_message('Select an Ambassador:',view=UserAccess(self.bot,'remove'),ephemeral=True)
    @discord.ui.button(label='View Diplomat',emoji='🔎')
    async def profile(self,i,_):
        s=discord.ui.UserSelect(placeholder='Select a diplomat...');s.callback=lambda x:diplomat_profile(x,self.bot);v=discord.ui.View(timeout=600);v.add_item(s);await i.response.send_message('Select a diplomat:',view=v,ephemeral=True)

class AdminView(discord.ui.View):
    def __init__(self,bot,timeout=None):super().__init__(timeout=timeout);self.bot=bot
    async def interaction_check(self,i):
        if not gov(i.user):await i.response.send_message('You are not authorized to use Embassy Management.',ephemeral=True);return False
        return True
    @discord.ui.button(label='Requests',emoji='📨',style=discord.ButtonStyle.primary,row=0)
    async def requests(self,i,_):await requests_page(i,self.bot)
    @discord.ui.button(label='Embassies',emoji='🏛️',row=0)
    async def embassies(self,i,_):await EmbassyList(self.bot).send(i)
    @discord.ui.button(label='Manage Diplomats',emoji='👤',row=0)
    async def diplomats(self,i,_):await i.response.send_message('👤 **Manage Diplomats**',view=ManageDiplomats(self.bot),ephemeral=True)
    @discord.ui.button(label='Directory',emoji='📋',row=1)
    async def directory(self,i,_):await EmbassyList(self.bot).send(i)
    @discord.ui.button(label='Statistics',emoji='📊',row=1)
    async def stats(self,i,_):
        db=self.bot.database;total=await db.collection('embassies').count_documents({});active=await db.collection('embassies').count_documents({'active':True});pending=await db.collection('requests').count_documents({'active':True});dips=await db.collection('embassy_assignments').count_documents({'active':True});today=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0);ap=await db.collection('approval_decisions').count_documents({'decision':'APPROVED','decided_at':{'$gte':today}});de=await db.collection('approval_decisions').count_documents({'decision':'DECLINED','decided_at':{'$gte':today}});await i.response.send_message(f'📊 **Diplomatic Statistics**\n\nTotal Embassies: **{total}**\nActive: **{active}**\nInactive: **{total-active}**\nForeign Diplomat assignments: **{dips}**\nPending Requests: **{pending}**\nApproved Today: **{ap}**\nDeclined Today: **{de}**',ephemeral=True)
    @discord.ui.button(label='Logs',emoji='📜',row=1)
    async def logs(self,i,_):
        xs=await self.bot.database.collection('audit_logs').find({}).sort('created_at',-1).limit(15).to_list(15);await i.response.send_message('📜 **Embassy Logs**\n\n'+('\n'.join(f"`{x.get('action','UNKNOWN')}` • `{x.get('actor_id','system')}`" for x in xs) if xs else 'No logs.'),ephemeral=True)
    @discord.ui.button(label='Migration',emoji='🔄',style=discord.ButtonStyle.danger,row=2)
    async def migration(self,i,_):
        xs=await self.bot.database.collection('migration_state').find({}).sort('completed_at',-1).limit(10).to_list(10);await i.response.send_message('🔄 **Migration Status**\n\n'+('\n'.join(f"`{x.get('migration_id')}` • inserted {x.get('inserted',0)} • updated {x.get('updated',0)} • missing {x.get('missing_channels',0)}" for x in xs) if xs else 'No migration recorded.'),ephemeral=True)
    @discord.ui.button(label='Reconcile Access',emoji='🔧',style=discord.ButtonStyle.success,row=2)
    async def reconcile(self,i,_):
        await i.response.defer(ephemeral=True);xs=await self.bot.database.collection('embassy_assignments').find({'active':True},{'discord_user_id':1}).limit(500).to_list(500);p=AccessProjector(self.bot.database);ok=bad=0
        for uid in {int(x['discord_user_id']) for x in xs if x.get('discord_user_id')}:
            try:await p.reconcile_member(i.guild,uid);ok+=1
            except Exception:bad+=1
        await i.followup.send(f'🔧 Checked **{ok+bad}** users • reconciled **{ok}** • failed **{bad}**',ephemeral=True)

class ForeignView(discord.ui.View):
    def __init__(self,bot,timeout=None):super().__init__(timeout=timeout);self.bot=bot
    async def interaction_check(self,i):
        if not diplomat(i.user):await i.response.send_message('You need the Foreign Diplomat role.',ephemeral=True);return False
        return True
    @discord.ui.button(label='My Diplomatic Profile',emoji='👤',style=discord.ButtonStyle.primary,row=0)
    async def profile(self,i,_):await diplomat_profile(i,self.bot)
    @discord.ui.button(label='Embassy Members',emoji='👥',row=0)
    async def members(self,i,_):
        a=await AccessService(self.bot.database).active_for_user(i.user.id);r=EmbassyRegistry(self.bot.database);out=[]
        for z in a:
            e=await r.get_by_id(str(z['embassy_id']));ms=await AccessService(self.bot.database).active_for_embassy(str(z['embassy_id']));out.append(f"**{e.country_name if e else z['embassy_id']}**\n"+' '.join(f"<@{m['discord_user_id']}>" for m in ms[:20]) or 'No members')
        await i.response.send_message('👥 **Embassy Members**\n\n'+('\n\n'.join(out) or 'None'),ephemeral=True)
    @discord.ui.button(label='Pre-Approve Visitor',emoji='📨',style=discord.ButtonStyle.success,row=1)
    async def preapprove(self,i,_):
        es=await EmbassyRegistry(self.bot.database).get_active();mine=[]
        for e in es:
            if await AccessService(self.bot.database).has_access(i.user.id,e.embassy_id):mine.append(e)
        if not mine:return await i.response.send_message('You have no active Embassy access.',ephemeral=True)
        s=discord.ui.Select(placeholder='Select your Embassy...',options=[discord.SelectOption(label=e.country_name[:100],value=e.embassy_id) for e in mine[:25]]);v=discord.ui.View(timeout=600);v.add_item(s);s.callback=lambda x:preapprove_modal(x,self.bot);await i.response.send_message('Select the Embassy for this pre-approval:',view=v,ephemeral=True)
    @discord.ui.button(label='Embassy Information',emoji='📋',row=1)
    async def info(self,i,_):
        a=await AccessService(self.bot.database).active_for_user(i.user.id);r=EmbassyRegistry(self.bot.database);out=[]
        for z in a:
            e=await r.get_by_id(str(z['embassy_id']))
            if e:out.append(f'🏛️ **{e.country_name}** • <#{e.channel_id}>')
        await i.response.send_message('📋 **Embassy Information**\n\n'+('\n'.join(out) or 'None'),ephemeral=True)

class PreModal(discord.ui.Modal,title='Create Embassy Pre-Approval'):
    user_id=discord.ui.TextInput(label='Applicant WarEra User ID',required=True)
    expiry=discord.ui.TextInput(label='Expiry (hours)',default='72',required=False)
    reason=discord.ui.TextInput(label='Reason',style=discord.TextStyle.paragraph,required=False)
    def __init__(self,bot,eid):super().__init__(timeout=300);self.bot=bot;self.eid=eid
    async def on_submit(self,i):
        if not await AccessService(self.bot.database).has_access(i.user.id,self.eid):return await i.response.send_message('You do not have access to that Embassy.',ephemeral=True)
        try:h=int(self.expiry.value or '72')
        except ValueError:return await i.response.send_message('Expiry must be a whole number.',ephemeral=True)
        w=ApprovalWorkflow(self.bot.database);ex=w.default_preapproval_expiry(h);pid=await w.create_preapproval(embassy_id=self.eid,diplomat_id=i.user.id,applicant_warera_id=self.user_id.value.strip(),expires_at=ex,reason=self.reason.value.strip() or None);await i.response.send_message(f'✅ Pre-approval created. Expires <t:{int(ex.timestamp())}:R>. ID `{pid}`',ephemeral=True)
async def preapprove_modal(i,bot): await i.response.send_modal(PreModal(bot,i.data['values'][0]))

async def admin_dashboard(self,interaction):
    if not gov(interaction.user):return await interaction.response.send_message('You are not authorized to use Embassy Management.',ephemeral=True)
    ch=interaction.guild.get_channel(settings.channel_embassy_management_id)
    if not isinstance(ch,discord.TextChannel):return await interaction.response.send_message('Configured Embassy Management channel is unavailable.',ephemeral=True)
    await ch.send(embed=discord.Embed(title='🏛️ EMBASSY MANAGEMENT',description="Manage India's diplomatic missions, Embassy access and Foreign Diplomats.",color=discord.Color.dark_red()),view=AdminView(self.bot,timeout=None));await interaction.response.send_message(f'✅ Dashboard posted in {ch.mention}.',ephemeral=True)
async def foreign_dashboard(self,interaction):
    if not diplomat(interaction.user):return await interaction.response.send_message('You need the Foreign Diplomat role.',ephemeral=True)
    ch=interaction.guild.get_channel(settings.channel_foreign_diplomat_dashboard_id)
    if not isinstance(ch,discord.TextChannel):return await interaction.response.send_message('Configured Foreign Diplomat dashboard channel is unavailable.',ephemeral=True)
    await ch.send(embed=discord.Embed(title='🤝 FOREIGN DIPLOMAT DASHBOARD',description='Manage your Embassy access, Embassy members and pre-approvals.',color=discord.Color.blurple()),view=ForeignView(self.bot,timeout=None));await interaction.response.send_message(f'✅ Dashboard posted in {ch.mention}.',ephemeral=True)
EmbassyRequestsCog.embassy_dashboard._callback=admin_dashboard
EmbassyRequestsCog.foreign_diplomat_dashboard._callback=foreign_dashboard

def _admin_init(self,bot,*,timeout=None): AdminView.__init__(self,bot,timeout=timeout)
def _foreign_init(self,bot,*,timeout=None): ForeignView.__init__(self,bot,timeout=timeout)
EmbassyManagementView.__init__=_admin_init
ForeignDiplomatView.__init__=_foreign_init
