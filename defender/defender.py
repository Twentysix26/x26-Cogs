"""
Defender - Protects your community with automod features and
           empowers the staff and users you trust with
           advanced moderation tools
Copyright (C) 2020  Twentysix (https://github.com/Twentysix26/)
This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.
You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

from redbot.core import commands, checks, Config, modlog
from redbot.core.commands import check
from collections import deque, Counter, defaultdict
from io import BytesIO
from redbot.core.utils.mod import is_mod_or_superior
from redbot.core.utils.menus import DEFAULT_CONTROLS, menu
from redbot.core.utils.chat_formatting import pagify, box, inline
from redbot.core.utils.common_filters import INVITE_URL_RE
from .status import make_status
from .enums import Rank, Action, EmergencyModules, EmergencyMode, WardenEvent
from .exceptions import InvalidRule
from .warden import WardenRule
import datetime
import discord
import asyncio
import tarfile
import logging

utcnow = datetime.datetime.utcnow

log = logging.getLogger("red.x26cogs.defender")

default_guild_settings = {
    "enabled": False, # Defender system toggle
    "notify_channel": 0, # Staff channel where notifications are sent. Supposed to be private.
    "notify_role": 0, # Staff role to ping.
    "trusted_roles": [], # Roles that can be considered safe
    "helper_roles": [], # Roles that are allowed to use special commands to help the staff
    "rank3_joined_days": 1, # Users that joined < X days ago are considered new users (rank 3)
    "rank3_min_messages": 50, # Messages threshold that users should reach to be no longer classified as rank 4
    "count_messages": True, # Count users' messages. If disabled, rank4 will be unobtainable
    "actions_taken": 0, # Stats collection # TODO ?
    "invite_filter_enabled": False,
    "invite_filter_rank": Rank.Rank4.value,
    "invite_filter_action": Action.NoAction.value, # Type of action to take on users that posted filtered invites
    "raider_detection_enabled": False,
    "raider_detection_rank": Rank.Rank3.value, # Users misconfigurating this module can fuck up a server so Rank 3 it is
    "raider_detection_messages": 15, # Take action on users that send more than X messages in...
    "raider_detection_minutes": 1, # ...Y minutes
    "raider_detection_action": Action.Ban.value,
    "raider_detection_wipe": 1, # If action is ban, wipe X days worth of messages
    "join_monitor_enabled": False,
    "join_monitor_n_users": 10, # Alert staff if more than X users...
    "join_monitor_minutes": 5, # ... joined in the past Y minutes
    "join_monitor_susp_hours": 0, # Notify staff if new join is younger than X hours
    "join_monitor_susp_subs": [], # Staff members subscribed to suspicious join notifications
    "warden_enabled": True,
    "wd_rules": {}, # Warden rules | I have to break the naming convention here due to config.py#L798
    "alert_enabled": True, # Available to helper roles by default
    "silence_enabled": False, # This is a manual module. Enabled = Available to be used...
    "silence_rank": 0, # ... and as such, this default will be 0
    "vaporize_enabled": False,
    "voteout_enabled": False,
    "voteout_rank": Rank.Rank2.value, # Rank X or below
    "voteout_votes": 3, # Votes needed for a successful voting session
    "voteout_action": Action.Ban.value, # What happens if the vote is successful
    "voteout_wipe": 1, # If action is ban, wipe X days worth of messages
    "emergency_modules": [], # EmergencyModules enabled and rendered available to helper roles on emergency
    "emergency_minutes": 5, # Minutes of staff inactivity after an alert before the guild enters emergency mode
}

default_member_settings = {
    "messages" : 0,
    "join_monitor_susp_hours": 0, # Personalized hours for join monitor suspicious joins
}


class Defender(commands.Cog):
    """Security tools to protect communities"""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, 262626, force_registration=True)
        self.config.register_guild(**default_guild_settings)
        self.config.register_member(**default_member_settings)
        self.joined_users = {}
        self.last_raid_alert = {}
        # Raider detection module
        self.message_cache = {}
        # Part of rank4's logic
        self.message_counter = defaultdict(lambda: Counter())
        self.loop = asyncio.get_event_loop()
        self.counter_task = self.loop.create_task(self.persist_counter())
        self.staff_activity = {}
        self.emergency_mode = {}
        self.active_warden_rules = defaultdict(lambda: dict())
        self.invalid_warden_rules = defaultdict(lambda: dict())
        self.loop.create_task(self.load_warden_rules())

    async def rank_user(self, member):
        """Returns the user's rank"""
        is_mod = await self.bot.is_mod(member)
        if is_mod:
            return Rank.Rank1

        rank1_roles = await self.config.guild(member.guild).trusted_roles()
        rank1_roles.extend(await self.config.guild(member.guild).helper_roles())
        for role in member.roles:
            if role.id in rank1_roles:
                return Rank.Rank1

        days = await self.config.guild(member.guild).rank3_joined_days()
        x_days_ago = utcnow() - datetime.timedelta(days=days)
        if member.joined_at >= x_days_ago:
            is_rank_4 = await self.is_rank_4(member)
            if is_rank_4:
                return Rank.Rank4
            else:
                return Rank.Rank3

        return Rank.Rank2

    async def is_rank_4(self, member):
        # If messages aren't being counted Rank 4 is unobtainable
        if not await self.config.guild(member.guild).count_messages():
            return False
        min_m = await self.config.guild(member.guild).rank3_min_messages()
        # Potential for slightly outdated data here, but oh well, it's just 60 seconds
        messages = await self.config.member(member).messages()
        return messages < min_m

    @commands.group(aliases=["df"])
    @commands.mod()
    async def defender(self, ctx: commands.Context):
        """Defender system"""

    @defender.command(name="status")
    async def defenderstatus(self, ctx: commands.Context):
        """Shows overall status of the Defender system"""
        pages = await make_status(ctx, self)
        await menu(ctx, pages, DEFAULT_CONTROLS)

    @defender.command(name="memberranks")
    async def defendermemberranks(self, ctx: commands.Context):
        """Counts how many members are in each rank"""
        ranks = {
            Rank.Rank1: 0,
            Rank.Rank2: 0,
            Rank.Rank3: 0,
            Rank.Rank4: 0,
        }
        for m in ctx.guild.members:
            if m.bot:
                continue
            rank = await self.rank_user(m)
            ranks[rank] += 1
        await ctx.send(box(f"Rank1: {ranks[Rank.Rank1]}\nRank2: {ranks[Rank.Rank2]}\n"
                       f"Rank3: {ranks[Rank.Rank3]}\nRank4: {ranks[Rank.Rank4]}\n\n"
                       f"For details about each rank see {ctx.prefix}defender status",
                       lang="yaml"))

    async def make_identify_embed(self, message, user, rank=True, link=True):
        messages = await self.config.member(user).messages()
        em = discord.Embed()
        avatar = user.avatar_url_as(static_format="png")
        em.set_thumbnail(url=avatar)
        em.set_author(name=f"{user}", url=avatar)
        em.add_field(name="Account created", value=user.created_at.strftime("%Y/%m/%d %H:%M:%S"), inline=True)
        em.add_field(name="Joined this server", value=user.joined_at.strftime("%Y/%m/%d %H:%M:%S"), inline=True)
        if link:
            em.add_field(name="Link", value=user.mention, inline=True)
        if rank:
            rank = await self.rank_user(user)
            em.add_field(name="Rank", value=rank.value, inline=True)
        em.set_footer(text=(f"User ID: {user.id} | {messages} messages recorded"))
        return em

    @defender.command(name="identify")
    async def defenderidentify(self, ctx, user: discord.Member):
        """Shows a member's rank + info"""
        em = await self.make_identify_embed(ctx.message, user)
        await ctx.send(embed=em)

    @defender.command(name="freshmeat")
    async def defenderfreshmeat(self, ctx, hours: int=24, *, filter_str: str=""):
        """Returns a list of the new users of the day

        Can be filtered in a grep-like way"""
        filter_str = filter_str.lower()
        msg = ""
        new_members = []
        x_hours_ago = ctx.message.created_at - datetime.timedelta(hours=hours)
        for m in ctx.guild.members:
            if m.joined_at > x_hours_ago:
                new_members.append(m)

        new_members.sort(key=lambda m: m.joined_at, reverse=True)

        for m in new_members:
            if filter_str:
                if filter_str not in m.name.lower():
                    continue
            join = m.joined_at.strftime("%Y/%m/%d %H:%M:%S")
            created = m.created_at.strftime("%Y/%m/%d %H:%M:%S")
            msg += f"J/C: {join}  {created} | {m.id} | {m}\n"

        pages = []
        for p in pagify(msg, delims=["\n"], page_length=1500):
            pages.append(box(p, lang="go"))

        if pages:
            await menu(ctx, pages, DEFAULT_CONTROLS)
        else:
            await ctx.send("Nothing to show.")

    @defender.command(name="notifynew")
    async def defendernotifynew(self, ctx: commands.Context, hours: int):
        """Sends you a DM if a user younger than X hours joins

        Use 0 hours to disable notifications"""
        if hours < 0 or hours > 744: # I think a month is enough
            await ctx.send("Value must be between 1 and 744.")
            return

        await self.config.member(ctx.author).join_monitor_susp_hours.set(hours)
        async with self.config.guild(ctx.guild).join_monitor_susp_subs() as subs:
            if hours:
                if ctx.author.id not in subs:
                    subs.append(ctx.author.id)
            else:
                if ctx.author.id in subs:
                    subs.remove(ctx.author.id)

        await ctx.tick()

    @defender.command(name="emergency")
    async def defenderemergency(self, ctx: commands.Context, on_or_off: bool):
        """Manually engage or turn off emergency mode

        Upon activation, staff will be pinged and any module
        that is set to be active in emergency mode will be rendered
        available to helpers"""
        guild = ctx.guild
        author = ctx.author
        d_enabled = await self.config.guild(guild).enabled()
        if not d_enabled:
            return await ctx.send("Defender is currently not operational.")
        modules = await self.config.guild(ctx.guild).emergency_modules()
        if not modules:
            return await ctx.send("Emergency mode is disabled in this server.")

        alert_msg = (f"⚠️ Emergency mode manually engaged by `{author}` ({author.id}).\n"
                     f"The modules **{', '.join(modules)}** can now be used by "
                     "helper roles. To turn off emergency mode do "
                     f"`{ctx.prefix}defender emergency off`. Good luck.")
        emergency_mode = self.is_in_emergency_mode(guild)

        if on_or_off:
            if not emergency_mode:
                self.emergency_mode[guild.id] = EmergencyMode(manual=True)
                await self.send_notification(guild, alert_msg, ping=True)
            else:
                await ctx.send("Emergency mode is already ongoing.")
        else:
            if emergency_mode:
                del self.emergency_mode[guild.id]
                await self.send_notification(guild, "⚠️ Emergency mode manually disabled.")
            else:
                await ctx.send("Emergency mode is already off.")

    @defender.group(name="warden")
    @commands.admin()
    async def wardengroup(self, ctx: commands.Context):
        """Warden rules management"""

    @wardengroup.command(name="add")
    async def wardengroupaddrule(self, ctx: commands.Context, *, rule: str):
        """Adds a new rule"""
        EMOJI = "💾"
        guild = ctx.guild
        rule = rule.strip("\n")
        if rule.startswith("```") and rule.endswith("```"):
            rule = rule.strip("```")

        try:
            new_rule = WardenRule(rule)
        except InvalidRule as e:
            return await ctx.send(f"Error parsing the rule: {e}")
        except Exception as e:
            log.error("Warden - unexpected error during cog load rule parsing", exc_info=e)
            return await ctx.send(f"Something very wrong happened during the rule parsing. Please check its format.")

        asked_overwrite = False
        if new_rule.name in self.active_warden_rules[guild.id] or new_rule.name in self.invalid_warden_rules[guild.id]:
            msg = await ctx.send("There is a rule with the same name already. Do you want to "
                                 "overwrite it? React to confirm.")

            def confirm(r, user):
                return user == ctx.author and str(r.emoji) == EMOJI and r.message.id == msg.id

            await msg.add_reaction(EMOJI)
            try:
                r = await ctx.bot.wait_for('reaction_add', check=confirm, timeout=15)
            except asyncio.TimeoutError:
                return await ctx.send("Not proceeding with overwrite.")
            asked_overwrite = True

        async with self.config.guild(ctx.guild).wd_rules() as warden_rules:
            warden_rules[new_rule.name] = rule
        self.active_warden_rules[ctx.guild.id][new_rule.name] = new_rule

        if not asked_overwrite:
            await ctx.tick()
        else:
            await ctx.send("The rule has been overwritten.")

    @wardengroup.command(name="remove")
    async def wardengroupremoverule(self, ctx: commands.Context, *, name: str):
        """Removes a rule by name"""
        name = name.lower()
        try:
            self.active_warden_rules[ctx.guild.id].pop(name, None)
            self.invalid_warden_rules[ctx.guild.id].pop(name, None)
            async with self.config.guild(ctx.guild).wd_rules() as warden_rules:
                del warden_rules[name]
            await ctx.tick()
        except KeyError:
            await ctx.send("There is no rule with that name.")

    @wardengroup.command(name="removeall")
    async def wardengroupremoveall(self, ctx: commands.Context):
        """Removes all rules"""
        EMOJI = "🚮"

        msg = await ctx.send("Are you sure you want to remove all the rules? This is "
                             "an irreversible operation. React to confirm.")

        def confirm(r, user):
            return user == ctx.author and str(r.emoji) == EMOJI and r.message.id == msg.id

        await msg.add_reaction(EMOJI)
        try:
            r = await ctx.bot.wait_for('reaction_add', check=confirm, timeout=15)
        except asyncio.TimeoutError:
            return await ctx.send("Not proceeding with deletion.")

        await self.config.guild(ctx.guild).wd_rules.clear()
        self.active_warden_rules[ctx.guild.id] = {}
        self.invalid_warden_rules[ctx.guild.id] = {}
        await ctx.send("All rules have been deleted.")

    @wardengroup.command(name="list")
    async def wardengrouplistrules(self, ctx: commands.Context):
        """Lists existing rules"""
        text = ""
        rules = {"active": [], "invalid": []}
        for k, v in self.active_warden_rules[ctx.guild.id].items():
            rules["active"].append(inline(v.name))

        for k, v in self.invalid_warden_rules[ctx.guild.id].items():
            rules["invalid"].append(inline(v.name))

        if not rules["active"] and not rules["invalid"]:
            return await ctx.send("There are no rules set.")

        if rules["active"]:
            text += "**Active rules**: " + ", ".join(rules["active"])

        if rules["invalid"]:
            if text:
                text += "\n\n"
            text += "**Invalid rules**: " + ", ".join(rules["invalid"])
            text += ("\nThese rules failed the validation process at the last start. Check if "
                     "their format is still considered valid in the most recent version of "
                     "Defender.")

        for p in pagify(text, delims=[" ", "\n"]):
            await ctx.send(p)

    @wardengroup.command(name="show")
    async def wardengroupshowrule(self, ctx: commands.Context, *, name: str):
        """Shows a rule"""
        try:
            rule = self.active_warden_rules[ctx.guild.id].get(name)
            if rule is None:
                rule = self.invalid_warden_rules[ctx.guild.id][name]
        except KeyError:
            return await ctx.send("There is no rule with that name.")
        await ctx.send(box(rule.raw_rule, lang="yaml"))

    @wardengroup.command(name="export")
    async def wardengroupexport(self, ctx: commands.Context, *, name: str):
        """Sends the rule as a YAML file"""
        try:
            rule = self.active_warden_rules[ctx.guild.id].get(name)
            if rule is None:
                rule = self.invalid_warden_rules[ctx.guild.id][name]
        except KeyError:
            return await ctx.send("There is no rule with that name.")
        f = discord.File(BytesIO(rule.raw_rule.encode("utf-8")), f"{name}.yaml")
        await ctx.send(file=f)

    @wardengroup.command(name="exportall")
    async def wardengroupexportall(self, ctx: commands.Context):
        """Sends all the rule as a tar.gz archive"""
        return await ctx.send("Coming soon :tm:")
        # TODO No idea what is wrong here but yeah, that's for later
        to_archive = {}

        for k, v in self.active_warden_rules[ctx.guild.id].items():
            to_archive[k] = BytesIO(v.raw_rule.encode("utf8"))

        if not to_archive:
            return await ctx.send("There are no active rules to export")

        tar_obj = BytesIO()

        with tarfile.open(fileobj=tar_obj, mode='w:gz') as tar:
            for k, v in to_archive.items():
                info = tarfile.TarInfo(f"{k}.yaml")
                info.size = len(v.getvalue())
                tar.addfile(info, v)

        utc = utcnow()
        await ctx.send(file=discord.File(tar_obj.getvalue(), f"rules-export-{utc}.tar.gz"))

    @commands.group()
    @commands.admin()
    async def dset(self, ctx: commands.Context):
        """Defender system settings"""

    @dset.group(name="general")
    @commands.admin()
    async def generalgroup(self, ctx: commands.Context):
        """Defender general settings"""

    @generalgroup.command(name="enable")
    async def generalgroupenable(self, ctx: commands.Context, on_or_off: bool):
        """Toggle defender system"""
        guild = ctx.guild
        n_channel = guild.get_channel(await self.config.guild(guild).notify_channel())
        n_role = guild.get_role(await self.config.guild(guild).notify_role())
        if not n_channel or not n_role:
            await ctx.send(f"Configuration issues detected. Check `{ctx.prefix}defender status` for more details.")
            return

        await self.config.guild(guild).enabled.set(on_or_off)
        if on_or_off:
            await ctx.send("Defender system activated.")
        else:
            await ctx.send("Defender system disabled. All auto modules and manual modules are now non-operational.")

    @generalgroup.command(name="trustedroles")
    async def generalgrouptrustedroles(self, ctx: commands.Context, *roles: discord.Role):
        """Sets the trusted roles

        Users belonging to this role will be classified as Rank 1"""
        to_add = []
        for r in roles:
            to_add.append(r.id)

        await self.config.guild(ctx.guild).trusted_roles.set(to_add)
        await ctx.tick()

    @generalgroup.command(name="helperroles")
    async def generalgrouphelperroles(self, ctx: commands.Context, *roles: discord.Role):
        """Sets the helper roles

        See [p]defender status for more information about these roles"""
        to_add = []
        for r in roles:
            to_add.append(r.id)

        await self.config.guild(ctx.guild).helper_roles.set(to_add)
        await ctx.tick()

    @generalgroup.command(name="notifychannel")
    async def generalgroupnotifychannel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Sets the channel where notifications will be sent

        This channel should preferably be staff readable only as it could
        potentially contain sensitive info"""
        await self.config.guild(ctx.guild).notify_channel.set(channel.id)
        everyone = ctx.guild.default_role
        await ctx.tick()
        if channel.overwrites[everyone].read_messages in (True, None):
            await ctx.send("Channel set. However, that channel is public: "
                           "a private one (staff-only) would be preferable as I might "
                           "send sensitive data at some point (logs, etc).")

    @generalgroup.command(name="notifyrole")
    async def generalgroupnotifyrole(self, ctx: commands.Context, role: discord.Role):
        """Sets the role that will be pinged in case of alerts"""
        await self.config.guild(ctx.guild).notify_role.set(role.id)
        await ctx.tick()
        channel_id = await self.config.guild(ctx.guild).notify_channel()
        channel = ctx.guild.get_channel(channel_id)
        if not channel:
            return await ctx.send("Role set. Remember to set a notify channel as well.")

        perms = channel.permissions_for(ctx.guild.me)

        if perms.mention_everyone is not True and not role.mentionable:
            await ctx.send("Role set. It seems that I won't be able to ping this role "
                           "in the notify channel that you have set. I suggest to fix "
                           "this.")

    @generalgroup.command(name="countmessages")
    async def generalgroupcountmessages(self, ctx: commands.Context, on_or_off: bool):
        """Toggles message count (and rank 4)"""
        await self.config.guild(ctx.guild).count_messages.set(on_or_off)
        if on_or_off:
            await ctx.send("Message counting enabled. Rank 4 is now obtainable.")
        else:
            await ctx.send("Message counting disabled. Rank 4 is now unobtainable.")

    @generalgroup.command(name="reset")
    async def generalgroupreset(self, ctx: commands.Context, confirmation: bool=False):
        """Resets Defender configuration for this server"""
        if not confirmation:
            await ctx.send("Are you sure you want to do this? This will reset the entire Defender "
                           "configuration for this server, disabling it and reverting back to defaults.\n"
                           f"Issue `{ctx.prefix}dset general reset yes` if you want to do this.")
            return
        await self.config.guild(ctx.guild).clear()
        await ctx.tick()

    @dset.group(name="rank3")
    @commands.admin()
    async def rank3group(self, ctx: commands.Context):
        """Rank 3 configuration

        See [p]defender status for more information about this rank"""

    @rank3group.command(name="minmessages")
    async def rank3minmessages(self, ctx: commands.Context, messages: int):
        """Minimum messages required to reach Rank 3"""
        if messages < 3 or messages > 10000:
            await ctx.send("Value must be between 3 and 10000.")
            return
        count_enabled = await self.config.guild(ctx.guild).count_messages()
        count_warning = ("Value set, however message counting is disabled in this server, therefore users "
                        f"cannot obtain Rank 4. Enable it with `{ctx.prefix}dset countmessages`.")
        await self.config.guild(ctx.guild).rank3_min_messages.set(messages)
        await ctx.tick()
        if not count_enabled:
            await ctx.send(count_warning)

    @rank3group.command(name="joineddays")
    async def rank3joineddays(self, ctx: commands.Context, days: int):
        """Days since join required to be considered Rank 3"""
        if days < 2 or days > 30:
            await ctx.send("Value must be between 2 and 30.")
            return
        await self.config.guild(ctx.guild).rank3_joined_days.set(days)
        await ctx.tick()

    @dset.group(name="invitefilter")
    @commands.admin()
    async def invitefiltergroup(self, ctx: commands.Context):
        """Invite filter auto module configuration

        See [p]defender status for more information about this module"""

    @invitefiltergroup.command(name="enable")
    async def invitefilterenable(self, ctx: commands.Context, on_or_off: bool):
        """Toggle invite filter"""
        await self.config.guild(ctx.guild).invite_filter_enabled.set(on_or_off)
        if on_or_off:
            await ctx.send("Invite filter enabled.")
        else:
            await ctx.send("Invite filter disabled.")

    @invitefiltergroup.command(name="rank")
    async def invitefiltergrouprank(self, ctx: commands.Context, rank: int):
        """Sets target rank"""
        try:
            Rank(rank)
        except:
            await ctx.send("Not a valid rank. Must be 1-4.")
            return
        await self.config.guild(ctx.guild).invite_filter_rank.set(rank)
        await ctx.tick()

    @invitefiltergroup.command(name="action")
    async def invitefiltergroupaction(self, ctx: commands.Context, action: str):
        """Sets action (ban, kick, softban or none (deletion only))"""
        action = action.lower()
        try:
            Action(action)
        except:
            await ctx.send("Not a valid action. Must be ban, kick, softban or none.")
            return
        await self.config.guild(ctx.guild).invite_filter_action.set(action)
        if Action(action) == Action.NoAction:
            await ctx.send("Action set. Since you've chosen 'none' I will only delete "
                           "the invite link and notify the staff about it.")
        await ctx.tick()

    @dset.group(name="alert")
    @commands.admin()
    async def alertgroup(self, ctx: commands.Context):
        """Alert manual module configuration

        See [p]defender status for more information about this module"""

    @alertgroup.command(name="enable")
    async def alertenable(self, ctx: commands.Context, on_or_off: bool):
        """Toggle alert manual module"""
        await self.config.guild(ctx.guild).alert_enabled.set(on_or_off)
        if on_or_off:
            await ctx.send("Alert manual module enabled. Helper roles will be able to use this.")
        else:
            await ctx.send("Alert manual module disabled.")

    @dset.group(name="silence")
    @commands.admin()
    async def silencegroup(self, ctx: commands.Context):
        """Silence manual module configuration

        See [p]defender status for more information about this module"""

    @silencegroup.command(name="enable")
    async def silencegroupenable(self, ctx: commands.Context, on_or_off: bool):
        """Toggle silence manual module"""
        await self.config.guild(ctx.guild).silence_enabled.set(on_or_off)
        if on_or_off:
            await ctx.send("Silence manual module enabled.")
        else:
            await ctx.send("Silence manual module disabled.")

    @dset.group(name="vaporize")
    @commands.admin()
    async def vaporizegroup(self, ctx: commands.Context):
        """Vaporize manual module configuration

        See [p]defender status for more information about this module"""

    @vaporizegroup.command(name="enable")
    async def vaporizegroupenable(self, ctx: commands.Context, on_or_off: bool):
        """Toggle vaporize manual module"""
        await self.config.guild(ctx.guild).vaporize_enabled.set(on_or_off)
        if on_or_off:
            await ctx.send("Vaporize manual module enabled.")
        else:
            await ctx.send("Vaporize manual module disabled.")

    @dset.group(name="joinmonitor")
    @commands.admin()
    async def joinmonitorgroup(self, ctx: commands.Context):
        """Join monitor auto module configuration

        See [p]defender status for more information about this module"""

    @joinmonitorgroup.command(name="enable")
    async def joinmonitorgroupenable(self, ctx: commands.Context, on_or_off: bool):
        """Toggles join monitor"""
        await self.config.guild(ctx.guild).join_monitor_enabled.set(on_or_off)
        if on_or_off:
            await ctx.send("Join monitor enabled.")
        else:
            await ctx.send("Join monitor disabled.")

    @joinmonitorgroup.command(name="minutes")
    async def joinmonitorgroupminutes(self, ctx: commands.Context, minutes: int):
        """Sets minutes (X users joined in Y minutes)"""
        if minutes < 1 or minutes > 60:
            await ctx.send("Value must be 1 and 60.")
            return
        await self.config.guild(ctx.guild).join_monitor_minutes.set(minutes)
        await ctx.tick()

    @joinmonitorgroup.command(name="users")
    async def joinmonitorgroupusers(self, ctx: commands.Context, users: int):
        """Sets users (X users joined in Y minutes)"""
        if users < 1 or users > 100:
            await ctx.send("Value must be between 1 and 100.")
            return
        await self.config.guild(ctx.guild).join_monitor_n_users.set(users)
        await ctx.tick()

    @joinmonitorgroup.command(name="notifynew")
    async def joinmonitornotifynew(self, ctx: commands.Context, hours: int):
        """Enables notifications for users younger than X hours

        Use 0 hours to disable notifications"""
        if hours < 0 or hours > 744:
            await ctx.send("Value must be between 1 and 744.")
            return
        await self.config.guild(ctx.guild).join_monitor_susp_hours.set(hours)
        await ctx.tick()

    @dset.group(name="raiderdetection")
    @commands.admin()
    async def raiderdetectiongroup(self, ctx: commands.Context):
        """Raider detection auto module configuration

        See [p]defender status for more information about this module"""

    @raiderdetectiongroup.command(name="enable")
    async def raiderdetectiongroupenable(self, ctx: commands.Context, on_or_off: bool):
        """Toggles raider detection"""
        await self.config.guild(ctx.guild).raider_detection_enabled.set(on_or_off)
        if on_or_off:
            await ctx.send("Raider detection enabled.")
        else:
            await ctx.send("Raider detection disabled.")

    @raiderdetectiongroup.command(name="messages")
    async def raiderdetectiongroupmessages(self, ctx: commands.Context, messages: int):
        """Sets messages (User posted X messages in Y minutes)"""
        if messages < 8 or messages > 50:
            await ctx.send("Value must be between 8 and 50.")
            return
        await self.config.guild(ctx.guild).raider_detection_messages.set(messages)
        await ctx.tick()

    @raiderdetectiongroup.command(name="minutes")
    async def raiderdetectiongroupminutes(self, ctx: commands.Context, minutes: int):
        """Sets minutes (User posted X messages in Y minutes)"""
        if minutes < 1:
            await ctx.send("Value must be 1 or higher.")
            return
        await self.config.guild(ctx.guild).raider_detection_minutes.set(minutes)
        await ctx.tick()

    @raiderdetectiongroup.command(name="rank")
    async def raiderdetectiongrouprank(self, ctx: commands.Context, rank: int):
        """Sets target rank"""
        try:
            Rank(rank)
        except:
            await ctx.send("Not a valid rank. Must be 1-4.")
            return
        await self.config.guild(ctx.guild).raider_detection_rank.set(rank)
        await ctx.tick()

    @raiderdetectiongroup.command(name="action")
    async def raiderdetectiongroupaction(self, ctx: commands.Context, action: str):
        """Sets action (ban, kick, softban or none (notify only))"""
        action = action.lower()
        try:
            Action(action)
        except:
            await ctx.send("Not a valid action. Must be ban, kick, softban or none.")
            return
        await self.config.guild(ctx.guild).raider_detection_action.set(action)
        if Action(action) == Action.NoAction:
            await ctx.send("Action set. Since you've chosen 'none' I will only notify "
                           "the staff about message spamming.")
        await ctx.tick()

    @raiderdetectiongroup.command(name="wipe")
    async def raiderdetectiongroupwipe(self, ctx: commands.Context, days: int):
        """Sets how many days worth of messages to delete if the action is ban

        Setting 0 will not delete any message"""
        if days < 0 or days > 7:
            return await ctx.send("Value must be between 0 and 7.")
        await self.config.guild(ctx.guild).raider_detection_wipe.set(days)
        await ctx.send(f"Value set. I will delete {days} days worth "
                       "of messages if the action is ban.")

    @dset.group(name="warden")
    @commands.admin()
    async def wardenset(self, ctx: commands.Context):
        """Warden auto module configuration

        See [p]defender status for more information about this module"""

    @wardenset.command(name="enable")
    async def wardensetenable(self, ctx: commands.Context, on_or_off: bool):
        """Toggles warden"""
        await self.config.guild(ctx.guild).warden_enabled.set(on_or_off)
        if on_or_off:
            await ctx.send("Warden auto-module enabled. Existing rules are now active.")
        else:
            await ctx.send("Warden auto-module disabled. Existing rules will have no effect.")

    @dset.group(name="voteout")
    @commands.admin()
    async def voteoutgroup(self, ctx: commands.Context):
        """Voteout manual module configuration

        See [p]defender status for more information about this module"""

    @voteoutgroup.command(name="enable")
    async def voteoutgroupenable(self, ctx: commands.Context, on_or_off: bool):
        """Toggles voteout"""
        await self.config.guild(ctx.guild).voteout_enabled.set(on_or_off)
        if on_or_off:
            await ctx.send("Voteout enabled.")
        else:
            await ctx.send("Voteout disabled.")

    @voteoutgroup.command(name="rank")
    async def voteoutgrouprank(self, ctx: commands.Context, rank: int):
        """Sets target rank"""
        try:
            if rank < Rank.Rank2.value:
                raise ValueError()
            Rank(rank)
        except:
            await ctx.send("Not a valid rank. Must be 2-4.")
            return
        await self.config.guild(ctx.guild).voteout_rank.set(rank)
        await ctx.tick()

    @voteoutgroup.command(name="action")
    async def voteoutgroupaction(self, ctx: commands.Context, action: str):
        """Sets action (ban, kick, softban)"""
        action = action.lower()
        try:
            if action == Action.NoAction.value:
                raise ValueError()
            Action(action)
        except:
            await ctx.send("Not a valid action. Must be ban, kick or softban ")
            return
        await self.config.guild(ctx.guild).voteout_action.set(action)
        await ctx.tick()

    @voteoutgroup.command(name="votes")
    async def voteoutgroupvotes(self, ctx: commands.Context, votes: int):
        """Sets required votes number for it to pass"""
        if votes < 2:
            return await ctx.send("A minimum of 2 votes is required.")
        action = await self.config.guild(ctx.guild).voteout_action()
        await self.config.guild(ctx.guild).voteout_votes.set(votes)
        await ctx.send(f"Votes set. A minimum of {votes} (including "
                       "the person who started the vote) will be "
                       f"required to {action} the target user.")

    @voteoutgroup.command(name="wipe")
    async def voteoutgroupwipe(self, ctx: commands.Context, days: int):
        """Sets how many days worth of messages to delete if the action is ban

        Setting 0 will not delete any message"""
        if days < 0 or days > 7:
            return await ctx.send("Value must be between 0 and 7.")
        await self.config.guild(ctx.guild).voteout_wipe.set(days)
        await ctx.send(f"Value set. I will delete {days} days worth "
                       "of messages if the action is ban.")

    @dset.group(name="emergency")
    @commands.admin()
    async def emergencygroup(self, ctx: commands.Context):
        """Emergency mode configuration

        See [p]defender status for more information about emergency mode"""

    @emergencygroup.command(name="modules")
    async def emergencygroupmodules(self, ctx: commands.Context, *modules: str):
        """Sets emergency modules

        Emergency modules will be rendered available to helper roles
        during emergency mode. Passing no modules to this command will
        disable emergency mode.
        Available emergency modules: voteout, vaporize, silence"""
        modules = [m.lower() for m in modules]
        for m in modules:
            try:
                EmergencyModules(m)
            except:
                return await ctx.send_help()
        await self.config.guild(ctx.guild).emergency_modules.set(modules)
        if modules:
            await ctx.send("Emergency modules set. They will now be available to helper "
                           "roles during emergency mode.")
        else:
            await ctx.send("Emergency mode is now disabled. If you wish to enable it see "
                           f"`{ctx.prefix}help dset emergency modules`")


    @emergencygroup.command(name="minutes")
    async def emergencygroupminutes(self, ctx: commands.Context, minutes: int):
        """Sets max inactivity minutes for staff

        After X minutes of inactivity following an alert emergency
        mode will be engaged and helper roles will be able to use
        the emergency modules."""
        if minutes < 1 or minutes > 30:
            return await ctx.send("A value between 1 and 30 please.")

        await self.config.guild(ctx.guild).emergency_minutes.set(minutes)
        modules = await self.config.guild(ctx.guild).emergency_modules()
        if not modules:
            await ctx.send("Value set. Remember to also set the emergency modules.")
        else:
            await ctx.send("Value set. I will auto engage emergency mode after "
                          f"{minutes} minutes of staff inactivity following an alert.")

    @commands.cooldown(1, 120, commands.BucketType.channel)
    @commands.command(aliases=["staff"])
    async def alert(self, ctx):
        """Alert the staff members"""
        guild = ctx.guild
        d_enabled = await self.config.guild(guild).enabled()
        enabled = await self.config.guild(guild).alert_enabled()
        if not enabled or not d_enabled:
            ctx.command.reset_cooldown(ctx)
            return await ctx.send("This feature is currently not enabled.")

        if not await self.is_helper(ctx.author) and not await self.bot.is_mod(ctx.author):
            ctx.command.reset_cooldown(ctx)
            return await ctx.send("You are not authorized to issue this command.")

        notify_channel_id = await self.config.guild(guild).notify_channel()
        notify_channel = ctx.guild.get_channel(notify_channel_id)
        if not notify_channel_id or not notify_channel:
            ctx.command.reset_cooldown(ctx)
            return await ctx.send("I don't have a notify channel set or I could not find it.")

        emergency_modules = await self.config.guild(guild).emergency_modules()

        react_text = ""
        emoji = None
        if emergency_modules:
            react_text = "\nReacting to this message or taking some actions in this server will disable the emergency timer."
            emoji = "⚠️"

        await self.send_notification(guild,
                                     (f"Alert issued by {ctx.author.mention} in {ctx.channel.mention}."
                                      f"{react_text}"),
                                     ping=True,
                                     link_message=ctx.message,
                                     react=emoji)
        await ctx.send("The staff has been notified. Please keep calm, I'm sure everything is fine. 🔥")

        ### Emergency mode

        if not emergency_modules:
            return

        if self.is_in_emergency_mode(guild):
            return

        to_delete = []

        async def check_audit_log():
            try:
                await self.refresh_with_audit_logs_activity(guild)
            except discord.Forbidden: # No access to the audit log, welp
                pass

        async def cleanup_countdown():
            channel = ctx.channel
            if to_delete:
                try:
                    await channel.delete_messages(to_delete)
                except:
                    pass

        await asyncio.sleep(60)
        await check_audit_log()
        active = self.has_staff_been_active(guild, minutes=1)
        if active: # Someone was active very recently
            return

        minutes = await self.config.guild(guild).emergency_minutes()
        minutes -= 1

        if minutes: # This whole countdown thing is skipped if the max inactivity is a single minute
            text = ("⚠️ No staff activity detected in the past minute. "
                    "Emergency mode will be engaged in {} minutes. "
                    "Please stand by. ⚠️")

            await ctx.send(f"{ctx.author.mention} " + text.format(minutes))
            await self.send_notification(guild, "⚠️ Seems like you're not around. I will automatically engage "
                                                f"emergency mode in {minutes} minutes if you don't show up.")
            while minutes != 0:
                await asyncio.sleep(60)
                await check_audit_log()
                if self.has_staff_been_active(guild, minutes=1):
                    await cleanup_countdown()
                    ctx.command.reset_cooldown(ctx)
                    await ctx.send("Staff activity detected. Alert deactivated. "
                                    "Thanks for helping keep the community safe.")
                    return
                minutes -= 1
                if minutes % 2: # Halves the # of messages
                    to_delete.append(await ctx.send(text.format(minutes)))

        guide = {
            EmergencyModules.Voteout: "voteout <user>` - Start a vote to expel a user from the server",
            EmergencyModules.Vaporize: ("defender vaporize <users...>` - Allows you to mass ban users from "
                                        "the server"),
            EmergencyModules.Silence: ("silence <rank> (2-4)` - Enables auto-deletion of messages for "
                                       "the specified rank (and below)")}

        text = ("⚠️ Emergency mode engaged. Helpers, you are now authorized to use the modules listed below.\n"
                "Please be responsible and only use these in case of true necessity, every action you take "
                "will be logged and reviewed at a later time.\n")

        for module in emergency_modules:
            text += f"`{ctx.prefix}{guide[EmergencyModules(module)]}\n"

        self.emergency_mode[guild.id] = EmergencyMode(manual=False)

        await self.send_notification(guild, "⚠️ Emergency mode engaged. Our helpers are now able to use the "
                                            f"**{', '.join(emergency_modules)}** modules.")

        await ctx.send(text)
        await cleanup_countdown()

    @commands.command()
    async def vaporize(self, ctx, *members: discord.Member):
        """Gets rid of bad actors in a quick and silent way

        Works only on Rank 3 and under"""
        guild = ctx.guild
        d_enabled = await self.config.guild(guild).enabled()
        enabled = await self.config.guild(guild).vaporize_enabled()
        em_enabled = await self.is_emergency_module(guild, EmergencyModules.Vaporize)
        emergency_mode = self.is_in_emergency_mode(guild)
        override = em_enabled and emergency_mode
        is_staff = await self.bot.is_mod(ctx.author)
        if not is_staff: # Prevents weird edge cases where staff is also helper
            is_helper = await self.is_helper(ctx.author)
        else:
            is_helper = False

        if not d_enabled:
            ctx.command.reset_cooldown(ctx)
            return await ctx.send("Defender is currently not operational.")
        if not is_staff and not is_helper:
            ctx.command.reset_cooldown(ctx)
            return await ctx.send("You are not authorized to issue this command.")
        if not override:
            if is_helper:
                ctx.command.reset_cooldown(ctx)
                if em_enabled:
                    return await ctx.send("This command is only available during emergency mode. "
                                        "No such thing right now.")
                else:
                    return await ctx.send("You are not authorized to issue this command.")
            if is_staff:
                if not enabled:
                    ctx.command.reset_cooldown(ctx)
                    return await ctx.send("This command is not available right now.")

        guild = ctx.guild
        if not members:
            await ctx.send_help()
            return
        if len(members) > 15:
            await ctx.send("No more than 15. Please try again.")
            return
        for m in members:
            rank = await self.rank_user(m)
            if rank < Rank.Rank3:
                await ctx.send("This command can only be used on Rank 3 and under. "
                               f"`{m}` ({m.id}) is Rank {rank.value}.")
                return

        errored = []

        for m in members:
            try:
                await guild.ban(m, reason=f"Vaporized by {ctx.author} ({ctx.author.id})", delete_message_days=0)
            except:
                errored.append(str(m.id))

        if not errored:
            await ctx.tick()
        else:
            await ctx.send("I could not ban the following IDs: " + ", ".join(errored))

        if len(errored) == len(members):
            return

        total = len(members) - len(errored)
        await self.send_notification(guild, f"🔥 {ctx.author} ({ctx.author.id}) has vaporized {total} users. 🔥")

    @commands.cooldown(1, 22, commands.BucketType.guild)  # More useful as a lock of sorts in this case
    @commands.command(cooldown_after_parsing=True)        # Only one concurrent session per guild
    async def voteout(self, ctx, user: discord.Member):
        """Initiates a vote to expel a user from the server

        Can be used by members with helper roles during emergency mode"""
        EMOJI = "👢"
        guild = ctx.guild

        d_enabled = await self.config.guild(guild).enabled()
        enabled = await self.config.guild(guild).voteout_enabled()
        em_enabled = await self.is_emergency_module(guild, EmergencyModules.Voteout)
        emergency_mode = self.is_in_emergency_mode(guild)
        override = em_enabled and emergency_mode
        is_staff = await self.bot.is_mod(ctx.author)
        if not is_staff: # Prevents weird edge cases where staff is also helper
            is_helper = await self.is_helper(ctx.author)
        else:
            is_helper = False

        if not d_enabled:
            ctx.command.reset_cooldown(ctx)
            return await ctx.send("Defender is currently not operational.")
        if not is_staff and not is_helper:
            ctx.command.reset_cooldown(ctx)
            return await ctx.send("You are not authorized to issue this command.")
        if not override:
            if is_helper:
                ctx.command.reset_cooldown(ctx)
                if em_enabled:
                    return await ctx.send("This command is only available during emergency mode. "
                                        "No such thing right now.")
                else:
                    return await ctx.send("You are not authorized to issue this command.")
            if is_staff:
                if not enabled:
                    ctx.command.reset_cooldown(ctx)
                    return await ctx.send("This command is not available right now.")

        required_rank = await self.config.guild(guild).voteout_rank()
        target_rank = await self.rank_user(user)
        if target_rank < required_rank:
            ctx.command.reset_cooldown(ctx)
            await ctx.send("You cannot vote to expel that user. "
                           f"User rank: {target_rank.value} (Must be rank {required_rank} or below)")
            return

        required_votes = await self.config.guild(guild).voteout_votes()
        action = await self.config.guild(guild).voteout_action()

        msg = await ctx.send(f"A voting session to {action} user `{user}` has been initiated.\n"
                             f"Required votes: **{required_votes}**. Only helper roles and staff "
                             f"are allowed to vote.\nReact with {EMOJI} to vote.")
        await msg.add_reaction(EMOJI)

        allowed_roles = await self.config.guild(guild).helper_roles()
        allowed_roles.extend(await ctx.bot._config.guild(guild).admin_role())
        allowed_roles.extend(await ctx.bot._config.guild(guild).mod_role())
        voters = [ctx.author]

        def is_allowed(user):
            for r in user.roles:
                if r.id in allowed_roles:
                    return True
            return False

        def add_vote(r, user):
            if r.message.id != msg.id:
                return False
            elif str(r.emoji) != EMOJI:
                return False
            elif user.bot:
                return False
            if user not in voters:
                if is_allowed(user):
                    voters.append(user)

            return len(voters) >= required_votes

        try:
            r = await ctx.bot.wait_for('reaction_add', check=add_vote, timeout=20)
        except asyncio.TimeoutError:
            ctx.command.reset_cooldown(ctx)
            return await ctx.send("Vote aborted: insufficient votes.")

        voters_list = ", ".join([f"{v} ({v.id})" for v in voters])
        if Action(action) == Action.Ban:
            action_text = "Votebanned with Defender."
            days = await self.config.guild(guild).voteout_wipe()
            await guild.ban(user, reason=f"{action_text} Voters: {voters_list}", delete_message_days=days)
        elif Action(action) == Action.Softban:
            action_text = "Votekicked with Defender." # Softban can be considered a kick
            await guild.ban(user, reason=f"{action_text} Voters: {voters_list}", delete_message_days=1)
            await guild.unban(user)
        elif Action(action) == Action.Kick:
            action_text = "Votekicked with Defender."
            await guild.kick(user, reason=f"{action_text} Voters: {voters_list}")
        else:
            raise ValueError("Invalid action set for voteout.")

        await self.send_notification(guild, f"User {user} ({user.id}) has been expelled with "
                                            f"a vote.\nVoters: `{voters_list}`",
                                     link_message=msg)

        await modlog.create_case(
            self.bot,
            guild,
            ctx.message.created_at,
            action,
            user,
            guild.me,
            action_text,
            until=None,
            channel=None,
        )

        ctx.command.reset_cooldown(ctx)
        await ctx.send(f"Vote successful. `{user}` has been expelled.")

    @commands.command()
    async def silence(self, ctx: commands.Context, rank: int):
        """Enables server wide message autodeletion for the specified rank (and below)

        Only applicable to Ranks 2-4. 0 will disable this."""
        guild = ctx.guild
        d_enabled = await self.config.guild(guild).enabled()
        enabled = await self.config.guild(guild).silence_enabled()
        em_enabled = await self.is_emergency_module(guild, EmergencyModules.Silence)
        emergency_mode = self.is_in_emergency_mode(guild)
        override = em_enabled and emergency_mode
        is_staff = await self.bot.is_mod(ctx.author)
        if not is_staff: # Prevents weird edge cases where staff is also helper
            is_helper = await self.is_helper(ctx.author)
        else:
            is_helper = False

        if not d_enabled:
            ctx.command.reset_cooldown(ctx)
            return await ctx.send("Defender is currently not operational.")
        if not is_staff and not is_helper:
            ctx.command.reset_cooldown(ctx)
            return await ctx.send("You are not authorized to issue this command.")
        if not override:
            if is_helper:
                ctx.command.reset_cooldown(ctx)
                if em_enabled:
                    return await ctx.send("This command is only available during emergency mode. "
                                        "No such thing right now.")
                else:
                    return await ctx.send("You are not authorized to issue this command.")
            if is_staff:
                if not enabled:
                    ctx.command.reset_cooldown(ctx)
                    return await ctx.send("This command is not available right now.")

        if rank != 0:
            try:
                if Rank(rank) == Rank.Rank1:
                    await ctx.send("Rank 1 cannot be silenced.")
                    return
                Rank(rank)
            except:
                await ctx.send("Not a valid rank. Must be 2-4.")
                return
        await self.config.guild(ctx.guild).silence_rank.set(rank)
        if rank:
            await ctx.send(f"Any message from Rank {rank} and below will be deleted. "
                           "Set 0 to disable silence mode.")
        else:
            await ctx.send("Silence mode disabled.")

    def has_staff_been_active(self, guild: discord.Guild, minutes: int):
        timestamp = self.staff_activity.get(guild.id)
        if not timestamp:
            return False

        x_minutes_ago = utcnow() - datetime.timedelta(minutes=minutes)

        return timestamp > x_minutes_ago

    async def refresh_staff_activity(self, guild, timestamp=None):
        disabled = False
        if not timestamp:
            timestamp = utcnow()
            try:
                em = self.emergency_mode[guild.id]
                if not em.is_manual: # Staff activity = disable auto emergency
                    del self.emergency_mode[guild.id]
                    disabled = True
            except KeyError:
                pass

        if disabled:
            await self.send_notification(guild, "⚠️ Emergency mode disabled. Welcome back.")

        self.staff_activity[guild.id] = timestamp

    async def refresh_with_audit_logs_activity(self, guild):
        last_activity = self.staff_activity.get(guild.id)
        refreshed = False
        async for entry in guild.audit_logs(limit=10):
            user = entry.user
            if not isinstance(user, discord.Member) or user.bot:
                continue
            if not await self.bot.is_mod(user):
                continue
            if last_activity is None or entry.created_at > last_activity:
                last_activity = entry.created_at
                refreshed = True

        if last_activity and refreshed:
            await self.refresh_staff_activity(guild, last_activity)

    def is_in_emergency_mode(self, guild):
        return guild.id in self.emergency_mode

    async def persist_counter(self):
        try:
            while True:
                await asyncio.sleep(60)

                all_counters = self.message_counter.copy()
                self.message_counter = defaultdict(lambda: Counter())

                members = self.config._get_base_group(self.config.MEMBER)
                async with members.all() as all_members:
                    for guid, counter in all_counters.items():
                        for uid, n_messages in counter.items():
                            guid = str(guid)
                            uid = str(uid)
                            if guid not in all_members:
                                all_members[guid] = {}
                            if uid not in all_members[guid]:
                                all_members[guid][uid] = {}
                            if "messages" not in all_members[guid][uid]:
                                all_members[guid][uid]["messages"] = 0
                            all_members[guid][uid]["messages"] += n_messages
                all_counters = None
        except asyncio.CancelledError:
            pass

    async def load_warden_rules(self):
        rules_to_load = defaultdict()
        guilds = self.config._get_base_group(self.config.GUILD)
        async with guilds.all() as all_guilds:
            for guid, guild_data in all_guilds.items():
                if "wd_rules" in guild_data:
                    if guild_data["wd_rules"]:
                        rules_to_load[guid] = guild_data["wd_rules"].copy()

        for guid, rules in rules_to_load.items():
            for rule in rules.values():
                try:
                    new_rule = WardenRule(rule, do_not_raise_during_parse=True)
                    # If the rule ends up not even having a name some extreme level of fuckery is going on
                    # At that point we might as well pretend it doesn't exist at config level
                    if new_rule.parse_exception and new_rule.name is not None:
                        raise new_rule.parse_exception
                    elif new_rule.name is not None:
                        self.active_warden_rules[int(guid)][new_rule.name] = new_rule
                    else:
                        log.error("Warden - rule did not reach name "
                                  "parsing during cog load", exc_info=new_rule.parse_exception)
                except InvalidRule as e:
                    self.invalid_warden_rules[int(guid)][new_rule.name] = new_rule
                except Exception as e:
                    self.invalid_warden_rules[int(guid)][new_rule.name] = new_rule
                    log.error("Warden - unexpected error during cog load rule parsing", exc_info=e)

    def cog_unload(self):
        self.counter_task.cancel()

    async def inc_message_count(self, member):
        self.message_counter[member.guild.id][member.id] += 1

    async def is_helper(self, member: discord.Member):
        helper_roles = await self.config.guild(member.guild).helper_roles()
        for r in member.roles:
            if r.id in helper_roles:
                return True
        return False

    async def is_emergency_module(self, guild, module: EmergencyModules):
        return module.value in await self.config.guild(guild).emergency_modules()

    async def send_notification(self, guild: discord.Guild, notification: str, *,
                                ping=False, link_message: discord.Message=None,
                                file: discord.File=None, embed: discord.Embed=None,
                                react: str=None):
        if ping:
            id_to_ping = await self.config.guild(guild).notify_role()
            if id_to_ping:
                notification = f"<@&{id_to_ping}>! {notification}"

        if link_message:
            m = link_message
            link = f"https://discordapp.com/channels/{m.guild.id}/{m.channel.id}/{m.id}"
            notification = f"{notification}\n{link}"

        notify_channel_id = await self.config.guild(guild).notify_channel()
        notify_channel = guild.get_channel(notify_channel_id)
        if notify_channel:
            msg = await notify_channel.send(notification, file=file, embed=embed,
                                            allowed_mentions=discord.AllowedMentions(roles=True))
            if react:
                await msg.add_reaction(react)
            return msg
        return False

    async def invite_filter(self, message):
        author = message.author
        guild = author.guild

        result = INVITE_URL_RE.search(message.content)

        if not result:
            return

        content = box(message.content)
        await message.delete()
        action = await self.config.guild(guild).invite_filter_action()
        if not action: # Only delete message
            return

        if Action(action) == Action.Ban:
            await guild.ban(author, reason="Posting an invite link (Defender autoban)", delete_message_days=0)
        elif Action(action) == Action.Kick:
            await guild.kick(author, reason="Posting an invite link (Defender autokick)")
        elif Action(action) == Action.Softban:
            await guild.ban(author, reason="Posting an invite link (Defender autokick)", delete_message_days=1)
            await guild.unban(author)
        elif Action(action) == Action.NoAction:
            pass
        else:
            raise ValueError("Invalid action for invite filter")

        if Action(action) != Action.NoAction:
            await self.send_notification(guild, f"I have expelled user {author} ({author.id}) for posting this message:\n{content}")

            await modlog.create_case(
                self.bot,
                guild,
                message.created_at,
                action,
                author,
                guild.me,
                "Posting an invite link",
                until=None,
                channel=None,
            )

            return True
        else:
            await self.send_notification(guild, f"I have deleted a message from {author} ({author.id}) with this content:\n{content}")

    async def detect_raider(self, message):
        author = message.author
        guild = author.guild
        if guild.id not in self.message_cache:
            self.message_cache[guild.id] = {}
        cache = self.message_cache[guild.id]
        if author.id not in cache:
            cache[author.id] = deque([message], maxlen=50)
            return
        else:
            cache[author.id].append(message)

        max_messages = await self.config.guild(guild).raider_detection_messages()
        minutes = await self.config.guild(guild).raider_detection_minutes()
        x_minutes_ago = message.created_at - datetime.timedelta(minutes=minutes)
        recent = 0

        for m in cache[author.id]:
            if m.created_at > x_minutes_ago:
                recent += 1

        # if recent < max_messages:
        #     return
        # Should be enough to avoid the race condition.
        # If the raider is stopped when the cap is reached any subsequent message should be ignored
        # If the ban fails for whatever reason when reaching the cap it's safe to assume
        # that repeating the action a mere milliseconds later won't make a difference.
        if recent != max_messages:
            return

        action = await self.config.guild(guild).raider_detection_action()

        if Action(action) == Action.Ban:
            delete_days = await self.config.guild(guild).raider_detection_wipe()
            await guild.ban(author, reason="Message spammer (Defender autoban)", delete_message_days=delete_days)
        elif Action(action) == Action.Kick:
            await guild.kick(author, reason="Message spammer (Defender autokick)")
        elif Action(action) == Action.Softban:
            await guild.ban(author, reason="Message spammer (Defender autokick)", delete_message_days=1)
            await guild.unban(author)
        elif Action(action) == Action.NoAction:
            fifteen_minutes_ago = message.created_at - datetime.timedelta(minutes=15)
            if guild.id in self.last_raid_alert:
                if self.last_raid_alert[guild.id] > fifteen_minutes_ago:
                    return
            self.last_raid_alert[guild.id] = message.created_at
            await self.send_notification(guild,
                                        f"User {author} ({author.id}) is spamming messages ({recent} "
                                        f"messages in {minutes} minutes).",
                                        link_message=message,
                                        ping=True)
            return
        else:
            raise ValueError("Invalid action for raider detection")

        await modlog.create_case(
            self.bot,
            guild,
            message.created_at,
            action,
            author,
            guild.me,
            "Message spammer",
            until=None,
            channel=None,
        )
        messages = cache[author.id].copy()
        messages.reverse()
        log = ""
        for m in messages:
            log += f"{m.created_at}\n{m.content}\n\n"
        f = discord.File(BytesIO(log.encode("utf-8")), f"{author.id}-log.txt")
        await self.send_notification(guild, f"I have expelled user {author} ({author.id}) for posting {recent} "
                                     f"messages in {minutes} minutes. Attached their last 20 messages.", file=f)
        return True

    async def join_monitor_flood(self, member):
        guild = member.guild

        if guild.id not in self.joined_users:
            self.joined_users[guild.id] = deque([], maxlen=100)

        cache = self.joined_users[guild.id]
        cache.append(member)

        users = await self.config.guild(guild).join_monitor_n_users()
        minutes = await self.config.guild(guild).join_monitor_minutes()
        x_minutes_ago = member.joined_at - datetime.timedelta(minutes=minutes)
        fifteen_minutes_ago = member.joined_at - datetime.timedelta(minutes=15)

        recent_users = 0

        for m in cache:
            if m.joined_at > x_minutes_ago:
                recent_users += 1

        if recent_users >= users:
            if guild.id in self.last_raid_alert:
                if self.last_raid_alert[guild.id] > fifteen_minutes_ago:
                        return
            self.last_raid_alert[guild.id] = member.joined_at

            await self.send_notification(guild,
                                         f"Abnormal influx of new users ({recent_users} in the past "
                                         f"{minutes} minutes). Possible raid ongoing or about to start.",
                                         ping=True)
            return True

    async def join_monitor_suspicious(self, member):
        guild = member.guild
        hours = await self.config.guild(guild).join_monitor_susp_hours()
        em = await self.make_identify_embed(None, member, rank=False)

        if hours:
            x_hours_ago = member.joined_at - datetime.timedelta(hours=hours)
            if member.created_at > x_hours_ago:
                await self.send_notification(guild, f"A user younger than {hours} "
                                                    f"hours just joined. If you wish to turn off "
                                                    "these notifications do `[p]dset joinmonitor "
                                                    "notifynew 0` (admin only)", embed=em)

        subs = await self.config.guild(guild).join_monitor_susp_subs()

        for _id in subs:
            user = guild.get_member(_id)
            if not user:
                continue

            hours = await self.config.member(user).join_monitor_susp_hours()
            if not hours:
                continue

            x_hours_ago = member.joined_at - datetime.timedelta(hours=hours)
            if member.created_at > x_hours_ago:
                try:
                    await user.send(f"A user younger than {hours} "
                                    f"hours just joined in the server {guild.name}. "
                                    "If you wish to turn off these notifications do "
                                    "`[p]defender notifynew 0` in the server.", embed=em)
                except:
                    pass

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.attachments:
            print(message.attachments)
        author = message.author
        if not hasattr(author, "guild") or not author.guild:
            return
        guild = author.guild
        if author.bot:
            return

        if not await self.config.guild(guild).enabled():
            return

        if await self.config.guild(guild).count_messages():
            await self.inc_message_count(author)

        banned = False
        rank = await self.rank_user(author)

        if rank == Rank.Rank1:
            if await self.bot.is_mod(author): # Is staff?
                await self.refresh_staff_activity(guild)
                return

        if await self.config.guild(guild).warden_enabled():
            env = {"message": message, "cog": self}
            for rule in self.active_warden_rules[guild.id].values():
                if rule.event != WardenEvent.OnMessage:
                    continue
                if await rule.satisfies_conditions(rank, env):
                    try:
                        await rule.do_actions(env)
                    except Exception as e:
                        log.error("Warden - unexpected error during actions execution", exc_info=e)

        inv_filter_enabled = await self.config.guild(guild).invite_filter_enabled()
        if inv_filter_enabled:
            inv_filter_rank = await self.config.guild(guild).invite_filter_rank()
            if rank >= inv_filter_rank:
                banned = await self.invite_filter(message)

        if banned:
            return

        rd_enabled = await self.config.guild(guild).raider_detection_enabled()
        if rd_enabled:
            rd_rank = await self.config.guild(guild).raider_detection_rank()
            if rank >= rd_rank:
                banned = await self.detect_raider(message)

        if banned:
            return

        silence_enabled = await self.config.guild(guild).silence_enabled()

        if silence_enabled:
            rank_silenced = await self.config.guild(guild).silence_rank()
            if rank_silenced and rank >= rank_silenced:
                try:
                    await message.delete()
                except:
                    pass


    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.bot:
            return

        guild = member.guild
        if not await self.config.guild(guild).enabled():
            return

        if await self.config.guild(guild).warden_enabled():
            env = {"user": member, "cog": self}
            for rule in self.active_warden_rules[guild.id].values():
                if rule.event != WardenEvent.OnUserJoin:
                    continue
                rank = await self.rank_user(member)
                if await rule.satisfies_conditions(rank, env):
                    try:
                        await rule.do_actions(env)
                    except Exception as e:
                        log.error("Warden - unexpected error during actions execution", exc_info=e)

        if await self.config.guild(guild).join_monitor_enabled():
            await self.join_monitor_flood(member)
            await self.join_monitor_suspicious(member)

    @commands.Cog.listener()
    async def on_message_edit(self, _, message):
        author = message.author
        if not hasattr(author, "guild") or not author.guild or author.bot:
            return
        if await self.bot.is_mod(author): # Is staff?
            await self.refresh_staff_activity(author.guild)

    @commands.Cog.listener()
    async def on_reaction_add(self, _, user):
        if not hasattr(user, "guild") or not user.guild or user.bot:
            return
        if await self.bot.is_mod(user): # Is staff?
            await self.refresh_staff_activity(user.guild)

    @commands.Cog.listener()
    async def on_reaction_remove(self, _, user):
        if not hasattr(user, "guild") or not user.guild or user.bot:
            return
        if await self.bot.is_mod(user): # Is staff?
            await self.refresh_staff_activity(user.guild)

    async def red_delete_data_for_user(self, requester, user_id):
        # We store only IDs
        if requester != "discord_deleted_user":
            return

        for _, counter in self.message_counter.items():
            del counter[user_id] # Counters don't raise if key is missing

        guilds = self.config._get_base_group(self.config.GUILD)
        async with guilds.all() as all_guilds:
            for _, guild_data in all_guilds.items():
                try:
                    guild_data["join_monitor_susp_subs"].remove(user_id)
                except:
                    pass

        members = self.config._get_base_group(self.config.MEMBER)
        async with members.all() as all_members:
            for _, guild_data in all_members.items():
                try:
                    del guild_data[str(user_id)]
                except:
                    pass
