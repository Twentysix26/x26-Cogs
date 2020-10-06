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

from typing import Deque
from redbot.core import commands, Config
from collections import Counter, defaultdict
from redbot.core.utils.chat_formatting import pagify, box
from .abc import CompositeMetaClass
from .core.automodules import AutoModules
from .commands import Commands
from .core.events import Events
from .enums import Rank, Action, EmergencyModules
from .exceptions import InvalidRule
from .core.warden.rule import WardenRule
from .core.warden.enums import Event as WardenEvent
from .core.announcements import get_announcements
from .core.cache import CacheUser
from .core import cache as df_cache
import datetime
import discord
import asyncio
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
    "announcements_sent": [],
    "actions_taken": 0, # Stats collection # TODO ?
    "invite_filter_enabled": False,
    "invite_filter_rank": Rank.Rank4.value,
    "invite_filter_action": Action.NoAction.value, # Type of action to take on users that posted filtered invites
    "invite_filter_exclude_own_invites": True, # Check against the server's own invites before taking action
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

default_owner_settings = {
    "cache_expiration" : 48, # Hours before a message will be removed from the cache
    "cache_cap": 3000, # Max messages to store for each user / channel
}

class Defender(Commands, AutoModules, Events, commands.Cog, metaclass=CompositeMetaClass):
    """Security tools to protect communities"""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, 262626, force_registration=True)
        self.config.register_guild(**default_guild_settings)
        self.config.register_member(**default_member_settings)
        self.config.register_global(**default_owner_settings)
        self.joined_users = {}
        self.last_raid_alert = {}
        # Part of rank4's logic
        self.message_counter = defaultdict(lambda: Counter())
        self.loop = asyncio.get_event_loop()
        self.counter_task = self.loop.create_task(self.persist_counter())
        self.staff_activity = {}
        self.emergency_mode = {}
        self.active_warden_rules = defaultdict(lambda: dict())
        self.invalid_warden_rules = defaultdict(lambda: dict())
        self.loop.create_task(self.load_warden_rules())
        self.loop.create_task(self.send_announcements())
        self.loop.create_task(self.load_cache_settings())
        self.loop.create_task(self.message_cache_cleaner())
        self.monitor = defaultdict(lambda: Deque(maxlen=500))

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

    def make_message_log(self, obj, *, guild: discord.Guild, requester: discord.Member=None,
                         replace_backtick=False, pagify_log=False):
        _log = []

        if isinstance(obj, (discord.Member, CacheUser)):
            messages = df_cache.get_user_messages(obj)

            for m in messages:
                ts = m.created_at.strftime("%H:%M:%S")
                channel = guild.get_channel(m.channel_id)
                # If requester is None it means that it's not a user requesting the logs
                # therefore we won't do any permission checking
                if channel and requester is not None:
                    requester_can_rm = channel.permissions_for(requester).read_messages
                else:
                    requester_can_rm = True
                channel = f"#{channel.name}" if channel else m.channel_id
                content = m.content if requester_can_rm else "[You are not authorized to access that channel]"
                _log.append(f"[{ts}]({channel}) {content}")
        elif isinstance(obj, discord.TextChannel):
            messages = df_cache.get_channel_messages(obj)

            for m in messages:
                ts = m.created_at.strftime("%H:%M:%S")
                user = guild.get_member(m.author_id)
                user = f"{user}" if user else m.author_id
                _log.append(f"[{ts}]({user}) {m.content}")
        else:
            raise ValueError("Invalid type passed to make_message_log")

        if replace_backtick:
            _log = [e.replace("`", "'") for e in _log]

        if pagify_log and _log:
            return list(pagify("\n".join(_log), page_length=1300))
        else:
            return _log

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

    def send_to_monitor(self, guild: discord.Guild, entry: str):
        now = utcnow().strftime("%m/%d %H:%M:%S")
        self.monitor[guild.id].appendleft(f"[{now}] {entry}")

    async def message_cache_cleaner(self):
        try:
            while True:
                await asyncio.sleep(60 * 60)
                await df_cache.discard_stale()
        except asyncio.CancelledError:
            pass

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
                    self.invalid_warden_rules[int(guid)][new_rule.name] = new_rule # type: ignore
                except Exception as e:
                    self.invalid_warden_rules[int(guid)][new_rule.name] = new_rule # type: ignore
                    log.error("Warden - unexpected error during cog load rule parsing", exc_info=e)

    async def load_cache_settings(self):
        df_cache.MSG_STORE_CAP = await self.config.cache_cap()
        df_cache.MSG_EXPIRATION_TIME = await self.config.cache_expiration()

    async def send_announcements(self):
        new_announcements = get_announcements(only_recent=True)
        if not new_announcements:
            return

        calls = []

        await self.bot.wait_until_ready()
        guilds = self.config._get_base_group(self.config.GUILD)
        async with guilds.all() as all_guilds:
            for guid, guild_data in all_guilds.items():
                guild = self.bot.get_guild(int(guid))
                if not guild:
                    continue
                notify_channel = guild_data.get("notify_channel", 0)
                if not notify_channel:
                    continue

                if "announcements_sent" not in guild_data:
                    guild_data["announcements_sent"] = []

                for ts, em in new_announcements.items():
                    if ts in guild_data["announcements_sent"]:
                        continue
                    calls.append(self.send_notification(guild, "", embed=em))

                    guild_data["announcements_sent"].append(ts)

        for call in calls:
            try:
                await call
            except (discord.Forbidden, discord.HTTPException):
                pass
            except Exception as e:
                log.error("Unexpected error during announcement delivery", exc_info=e)

            await asyncio.sleep(0.5)


    def cog_unload(self):
        self.counter_task.cancel()

    async def callout_if_fake_admin(self, ctx):
        if ctx.invoked_subcommand is None:
            # User is just checking out the help
            return False
        error_msg = ("It seems that you have a role that is considered admin at bot level but "
                     "not the basic permissions that one would reasonably expect an admin to have.\n"
                     "To use these commands, other than the admin role, you need `administrator` "
                     "permissions OR `manage messages` + `manage roles` + `ban member` permissions.\n"
                     "I cannot let you proceed until you properly configure permissions in this server.")
        channel = ctx.channel
        perms = channel.permissions_for(ctx.author)
        has_basic_perms = all((perms.manage_messages, perms.manage_roles, perms.ban_members))

        if not has_basic_perms:
            await ctx.send(error_msg)
            return True
        return False

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

    def get_warden_rules_by_event(self, guild: discord.Guild, event: WardenEvent):
        rules = self.active_warden_rules.get(guild.id, {}).values()
        rules = [r for r in rules if event in r.events]
        return sorted(rules, key=lambda k: k.priority)

    def dispatch_event(self, event_name, *args):
        event_name = "x26_defender_" + event_name
        self.bot.dispatch(event_name, *args)

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

        # Technically it isn't going to end up in config
        # but we'll scrub the cache too because we're nice
        await df_cache.discard_messages_from_user(user_id)
