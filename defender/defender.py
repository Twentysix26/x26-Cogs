"""
Defender - Protects your community with automod features and
           empowers the staff and users you trust with
           advanced moderation tools
Copyright (C) 2020-present  Twentysix (https://github.com/Twentysix26/)
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

from typing import Deque, List, Optional
from redbot.core import commands, Config
from collections import Counter, defaultdict
from redbot.core.utils.chat_formatting import pagify
from redbot.core.utils import AsyncIter
from redbot.core import modlog
from .abc import CompositeMetaClass
from .core.automodules import AutoModules
from .commands import Commands
from .core.events import Events
from .enums import Rank, Action, EmergencyModules, PerspectiveAttributes
from .exceptions import InvalidRule
from .core.warden.rule import WardenRule
from .core.warden.enums import Event as WardenEvent
from .core.warden import heat, api as WardenAPI
from .core.announcements import get_announcements_text
from .core.cache import CacheUser
from .core.utils import utcnow, timestamp
from .core import cache as df_cache
from multiprocessing.pool import Pool
from zlib import crc32
from string import Template
from discord import ui
import datetime
import discord
import asyncio
import logging

log = logging.getLogger("red.x26cogs.defender")

default_guild_settings = {
    "enabled": False, # Defender system toggle
    "notify_channel": 0, # Staff channel where notifications are sent. Supposed to be private.
    "notify_role": 0, # Staff role to ping.
    "punish_role": 0, # Role to apply if the "Action" is punish
    "trusted_roles": [], # Roles that can be considered safe
    "helper_roles": [], # Roles that are allowed to use special commands to help the staff
    "punish_message": "", # Message to send after the punish role is assigned
    "rank3_joined_days": 1, # Users that joined < X days ago are considered new users (rank 3)
    "rank3_min_messages": 50, # Messages threshold that users should reach to be no longer classified as rank 4
    "count_messages": True, # Count users' messages. If disabled, rank4 will be unobtainable
    "announcements_sent": [],
    "invite_filter_enabled": False,
    "invite_filter_rank": Rank.Rank4.value,
    "invite_filter_action": Action.NoAction.value, # Type of action to take on users that posted filtered invites
    "invite_filter_exclude_own_invites": True, # Check against the server's own invites before taking action
    "invite_filter_delete_message": True, # Whether to delete the invite's message or not
    "invite_filter_wdchecks": "",
    "raider_detection_enabled": False,
    "raider_detection_rank": Rank.Rank3.value, # Users misconfigurating this module can fuck up a server so Rank 3 it is
    "raider_detection_messages": 15, # Take action on users that send more than X messages in...
    "raider_detection_minutes": 1, # ...Y minutes
    "raider_detection_action": Action.Ban.value,
    "raider_detection_wipe": 1, # If action is ban, wipe X days worth of messages
    "raider_detection_wdchecks": "",
    "join_monitor_enabled": False,
    "join_monitor_n_users": 10, # Alert staff if more than X users...
    "join_monitor_minutes": 5, # ... joined in the past Y minutes
    "join_monitor_v_level": 0, # Raise verification up to X on raids
    "join_monitor_susp_hours": 0, # Notify staff if new join is younger than X hours
    "join_monitor_susp_subs": [], # Staff members subscribed to suspicious join notifications
    "join_monitor_wdchecks": "",
    "warden_enabled": True,
    "wd_rules": {}, # Warden rules | I have to break the naming convention here due to config.py#L798
    "ca_enabled": False, # Comment analysis
    "ca_token": None, # CA token
    "ca_attributes": [PerspectiveAttributes.SevereToxicity.value], # Attributes to query
    "ca_threshold": 80, # Percentage for CA to trigger
    "ca_action": Action.NoAction.value,
    "ca_rank": Rank.Rank3.value,
    "ca_reason": "Bad comment", # Mod-log reason
    "ca_wipe": 0, # If action is ban, wipe X days worth of messages
    "ca_delete_message": True, # Whether to delete the offending message
    "ca_wdchecks": "",
    "alert_enabled": True, # Available to helper roles by default
    "silence_enabled": False, # This is a manual module. Enabled = Available to be used...
    "silence_rank": 0, # ... and as such, this default will be 0
    "vaporize_enabled": False,
    "vaporize_max_targets": 15,
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
    "wd_regex_allowed": False, # Allows the creation of Warden rules with user defined regex
    "wd_periodic_allowed": True, # Allows the creation of periodic Warden rules
    "wd_upload_max_size": 3, # Max size for Warden rule upload (in kilobytes)
    "wd_regex_safety_checks": True, # Performance safety checks for user defined regex
}

class Defender(Commands, AutoModules, Events, commands.Cog, metaclass=CompositeMetaClass):
    """Security tools to protect communities"""

    __version__ = "2.0.1"

    def __init__(self, bot):
        self.bot = bot
        WardenAPI.init_api(self)
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
        self.warden_checks = defaultdict(lambda: dict())
        self.loop.create_task(self.load_warden_rules())
        self.loop.create_task(self.send_announcements())
        self.loop.create_task(self.load_cache_settings())
        self.mc_task = self.loop.create_task(self.message_cache_cleaner())
        self.wd_periodic_task = self.loop.create_task(self.wd_periodic_rules())
        self.monitor = defaultdict(lambda: Deque(maxlen=500))
        self.wd_pool = Pool(maxtasksperchild=1000)
        self.quick_actions = defaultdict(lambda: dict())

    async def rank_user(self, member: discord.Member):
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

    async def is_rank_4(self, member: discord.Member):
        # If messages aren't being counted Rank 4 is unobtainable
        if not await self.config.guild(member.guild).count_messages():
            return False
        min_m = await self.config.guild(member.guild).rank3_min_messages()
        messages = await self.get_total_recorded_messages(member)
        return messages < min_m

    async def get_total_recorded_messages(self, member: discord.Member):
        # The ones already stored in config...
        msg_n = await self.config.member(member).messages()
        # And the ones that will be stored in a few seconds
        msg_n += self.message_counter[member.guild.id][member.id]
        return msg_n

    async def make_message_log(self, obj, *, guild: discord.Guild, requester: discord.Member=None,
                               replace_backtick=False, pagify_log=False):
        text_unauthorized = "[You are not authorized to access that channel]"
        _log = []

        if isinstance(obj, (discord.Member, CacheUser)):
            messages = df_cache.get_user_messages(obj)

            async for m in AsyncIter(messages, steps=20):
                ts = m.created_at.strftime("%H:%M:%S")
                channel = guild.get_channel(m.channel_id) or guild.get_thread(m.channel_id)
                # If requester is None it means that it's not a user requesting the logs
                # therefore we won't do any permission checking
                if channel and requester is not None:
                    requester_can_rm = channel.permissions_for(requester).read_messages
                else:
                    requester_can_rm = True
                channel = f"#{channel.name}" if channel else m.channel_id
                content = m.content if requester_can_rm else text_unauthorized
                if m.edits:
                    entry = len(m.edits) + 1
                    _log.append(f"[{ts}]({channel})[{entry}] {content}")
                    for edit in m.edits:
                        entry -= 1
                        ts = edit.edited_at.strftime("%H:%M:%S")
                        content = edit.content if requester_can_rm else text_unauthorized
                        _log.append(f"[{ts}]({channel})[{entry}] {content}")
                else:
                    _log.append(f"[{ts}]({channel}) {content}")
        elif isinstance(obj, (discord.TextChannel, discord.Thread)):
            messages = df_cache.get_channel_messages(obj)

            async for m in AsyncIter(messages, steps=20):
                ts = m.created_at.strftime("%H:%M:%S")
                user = guild.get_member(m.author_id)
                user = f"{user}" if user else m.author_id
                if m.edits:
                    entry = len(m.edits) + 1
                    _log.append(f"[{ts}]({user})[{entry}] {m.content}")
                    for edit in m.edits:
                        entry -= 1
                        ts = edit.edited_at.strftime("%H:%M:%S")
                        _log.append(f"[{ts}]({user})[{entry}] {edit.content}")
                else:
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
            await self.send_notification(guild, "⚠️ Emergency mode disabled. Welcome back.", force_text_only=True)

        self.staff_activity[guild.id] = timestamp

    async def make_identify_embed(self, message: discord.Member, user, rank=True, link=True):
        messages = await self.get_total_recorded_messages(user)
        em = discord.Embed()
        em.set_thumbnail(url=user.avatar)
        em.set_author(name=f"{user}", url=user.avatar)
        em.add_field(name="Account created", value=timestamp(user.created_at), inline=True)
        em.add_field(name="Joined this server", value=timestamp(user.joined_at), inline=True)
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
                await heat.remove_stale_heat()
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
                        async for uid, n_messages in AsyncIter(counter.items(), steps=50):
                            guid = str(guid)
                            uid = str(uid)
                            if guid not in all_members:
                                all_members[guid] = {}
                            if uid not in all_members[guid]:
                                all_members[guid][uid] = {}
                            if "messages" not in all_members[guid][uid]:
                                all_members[guid][uid]["messages"] = 0
                            all_members[guid][uid]["messages"] += n_messages
                        await asyncio.sleep(0)
                all_counters = None
        except asyncio.CancelledError:
            pass


    async def wd_periodic_rules(self):
        try:
            await self.bot.wait_until_red_ready()
            while True:
                await asyncio.sleep(60)
                if await self.config.wd_periodic_allowed():
                    await self.spin_wd_periodic_rules()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error(f"Defender's scheduler for Warden periodic rules errored: {e}")

    async def spin_wd_periodic_rules(self):
        all_guild_rules = self.active_warden_rules.copy()
        tasks = []

        for guid in all_guild_rules.keys():
            guild = self.bot.get_guild(guid)
            if guild is None:
                continue
            if await self.bot.cog_disabled_in_guild(self, guild): # type: ignore
                continue

            rules = self.get_warden_rules_by_event(guild, WardenEvent.Periodic)

            if not rules:
                continue

            if not await self.config.guild(guild).enabled():
                continue

            if not await self.config.guild(guild).warden_enabled():
                continue

            tasks.append(self.exec_wd_period_rules(guild, rules))

        if tasks:
            await asyncio.gather(*tasks)

    async def exec_wd_period_rules(self, guild, rules):
        for rule in rules:
            if not rule.next_run <= utcnow() or rule.run_every is None:
                continue
            async for member in AsyncIter(guild.members, steps=2):
                if member.bot:
                    continue
                if member.joined_at is None:
                    continue
                rank = await self.rank_user(member)
                if await rule.satisfies_conditions(cog=self, rank=rank, guild=member.guild, user=member):
                    try:
                        await rule.do_actions(cog=self, guild=member.guild, user=member)
                    except Exception as e:
                        self.send_to_monitor(guild, f"[Warden] Rule {rule.name} "
                                                    f"({rule.last_action.value}) - {str(e)}")
            rule.next_run = utcnow() + rule.run_every

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
                new_rule = WardenRule()
                # If the rule ends up not even having a name some extreme level of fuckery is going on
                # At that point we might as well pretend it doesn't exist at config level
                try:
                    await new_rule.parse(rule, self)
                except InvalidRule as e:
                    if new_rule.name is not None:
                        self.invalid_warden_rules[int(guid)][new_rule.name] = new_rule # type: ignore
                    else:
                        log.error("Warden - rule did not reach name "
                                  "parsing during cog load", exc_info=e)
                except Exception as e:
                    if new_rule.name is not None:
                        self.invalid_warden_rules[int(guid)][new_rule.name] = new_rule # type: ignore
                    log.error("Warden - unexpected error during cog load rule parsing", exc_info=e)
                else:
                    self.active_warden_rules[int(guid)][new_rule.name] = new_rule

        await WardenAPI.load_modules_checks()


    async def load_cache_settings(self):
        df_cache.MSG_STORE_CAP = await self.config.cache_cap()
        df_cache.MSG_EXPIRATION_TIME = await self.config.cache_expiration()

    async def send_announcements(self):
        new_announcements = get_announcements_text(only_recent=True)
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
                if await self.bot.cog_disabled_in_guild(self, guild): # type: ignore
                    continue
                notify_channel = guild_data.get("notify_channel", 0)
                if not notify_channel:
                    continue

                if "announcements_sent" not in guild_data:
                    guild_data["announcements_sent"] = []

                for ts, ann in new_announcements.items():
                    if ts in guild_data["announcements_sent"]:
                        continue
                    calls.append(self.send_notification(guild, **ann))

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
        self.wd_periodic_task.cancel()
        self.mc_task.cancel()
        self.wd_pool.close()
        self.bot.loop.run_in_executor(None, self.wd_pool.join)

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

    async def send_notification(self, destination: discord.abc.Messageable, description: str, *,
                                title: str=None, fields: list=[], footer: str=None,
                                thumbnail: str=None,
                                ping=False, file: discord.File=None, react: str=None,
                                jump_to: discord.Message=None,
                                allow_everyone_ping=False, force_text_only=False, heat_key: str=None,
                                no_repeat_for: datetime.timedelta=None, view: ui.View=None)->Optional[discord.Message]:
        """Sends a notification to the staff channel if a guild is passed. Embed preference is respected."""
        if no_repeat_for:
            if isinstance(destination, discord.Guild):
                guild = destination
            else:
                guild = destination.guild

            if not heat_key: # A custom heat_key can be passed to block dynamic content
                heat_key = f"{destination.id}-{description}-{fields}"
                heat_key =  f"core-notif-{crc32(heat_key.encode('utf-8', 'ignore'))}"

            if not heat.get_custom_heat(guild, heat_key) == 0:
                return
            heat.increase_custom_heat(guild, heat_key, no_repeat_for)

        guild = destination
        is_staff_notification = False
        if isinstance(destination, discord.Guild):
            is_staff_notification = True
            notify_channel_id = await self.config.guild(destination).notify_channel()
            destination = destination.get_channel(notify_channel_id)
            if destination is None:
                return

        staff_mention = ""
        if ping and is_staff_notification:
            staff_mention = f"<@&{await self.config.guild(guild).notify_role()}> "

        embed = None
        send_embed = await self.bot.embed_requested(destination)
        if send_embed is True and force_text_only is False:
            if jump_to:
                description += f"\n[Click to jump]({jump_to.jump_url})"
            embed = discord.Embed(
                title=title if title else "",
                description=description,
            )
            if footer: embed.set_footer(text=footer)
            if thumbnail: embed.set_thumbnail(url=thumbnail)
            for field in fields:
                embed.add_field(**field)
            message_content = staff_mention
            embed.color = await self.bot.get_embed_color(destination)
            embed.timestamp = utcnow()
        else:
            title = f"**{title}\n**" if title else ""
            footer = f"\n*{footer}*" if footer else ""
            fields_txt = ""
            for field in fields:
                fields_txt += f"\n**{field['name']}**: {field['value']}"
            jump_to = f"\n{jump_to.jump_url}" if jump_to else ""
            message_content = f"{title}{staff_mention}{description}{fields_txt}{jump_to}{footer}"

        allowed_mentions = discord.AllowedMentions(roles=True, everyone=allow_everyone_ping)
        msg = await destination.send(message_content, file=file, embed=embed,
                                     allowed_mentions=allowed_mentions, view=view)
        if react:
            await msg.add_reaction(react)

        return msg


    def is_role_privileged(self, role: discord.Role, issuers_top_role: discord.Role=None):
        if any((
            role.permissions.manage_channels, role.permissions.manage_guild,
            role.permissions.manage_messages, role.permissions.manage_roles,
            role.permissions.ban_members, role.permissions.kick_members,
            role.permissions.administrator)):
            return True

        if role.guild.me.top_role <= role:
            return True

        if issuers_top_role:
            return role >= issuers_top_role
        else:
            return False

    def get_warden_rules_by_event(self, guild: discord.Guild, event: WardenEvent)->List[WardenRule]:
        rules = self.active_warden_rules.get(guild.id, {}).values()
        rules = [r for r in rules if event in r.events]
        return sorted(rules, key=lambda k: k.priority)

    async def format_punish_message(self, member: discord.Member):
        text = await self.config.guild(member.guild).punish_message()
        if not text:
            return ""

        ctx_vars = {
            "user": str(member),
            "user_name": member.name,
            "user_display": member.display_name,
            "user_id": member.id,
            "user_mention": member.mention,
            "user_nickname": str(member.nick),
        }

        return Template(text).safe_substitute(ctx_vars)

    def dispatch_event(self, event_name, *args):
        event_name = "x26_defender_" + event_name
        self.bot.dispatch(event_name, *args)

    async def create_modlog_case(self, bot, guild, created_at, action_type, user, moderator=None, reason=None, until=None,
                                 channel=None, last_known_username=None):
        if action_type == Action.NoAction.value:
            return

        mod_id = moderator.id if moderator else "none"

        heat_key = f"core-modlog-{user.id}-{action_type}-{mod_id}"
        if not heat.get_custom_heat(guild, heat_key) == 0:
            return
        heat.increase_custom_heat(guild, heat_key, datetime.timedelta(seconds=15))

        await modlog.create_case(
            bot,
            guild,
            created_at,
            action_type,
            user,
            moderator,
            reason,
            until,
            channel,
            last_known_username
        )

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
