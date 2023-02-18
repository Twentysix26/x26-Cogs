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

from defender.core.warden.rule import WardenRule
from defender.core.warden.enums import ChecksKeys as WDChecksKeys
from defender.core.warden import api as WardenAPI
from ..abc import MixinMeta, CompositeMetaClass
from ..enums import Action, Rank, PerspectiveAttributes as PAttr, EmergencyModules as EModules
from redbot.core import commands
from redbot.core.utils.chat_formatting import box, pagify, escape
from ..core import cache as df_cache
from ..core.menus import RestrictedView, SettingSetSelect
from redbot.core.commands import GuildConverter
from discord import SelectOption
import discord
import asyncio
import logging

log = logging.getLogger("red.x26cogs.defender")

P_ATTRS_URL = "https://developers.perspectiveapi.com/s/about-the-api-attributes-and-languages"

class Settings(MixinMeta, metaclass=CompositeMetaClass):  # type: ignore

    @commands.group(name="dset", aliases=["defset"])
    @commands.guild_only()
    @commands.admin()
    async def dset(self, ctx: commands.Context):
        """Defender system settings"""
        if await self.callout_if_fake_admin(ctx):
            ctx.invoked_subcommand = None

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
        admin_roles = await ctx.bot._config.guild(ctx.guild).admin_role()
        mod_roles = await ctx.bot._config.guild(ctx.guild).mod_role()
        has_core_roles_set = bool(admin_roles) or bool(mod_roles)

        if not n_channel or not n_role or not has_core_roles_set:
            await ctx.send(f"Configuration issues detected. Check `{ctx.prefix}defender status` for more details.")
            return

        await self.config.guild(guild).enabled.set(on_or_off)
        if on_or_off:
            await ctx.send("Defender system activated.")
        else:
            await ctx.send("Defender system disabled. All auto modules and manual modules are now non-operational.")

    @dset.command(name="importfrom")
    async def dsetimportfrom(self, ctx: commands.Context, server: GuildConverter):
        """Import the configuration from another server

        This is permitted only if the command issuer is admin in both servers"""
        EMOJI = "✅"
        other_guild = server
        other_member = other_guild.get_member(ctx.author.id)
        if other_member is None:
            return await ctx.send("You are not in that server.")

        if not await self.bot.is_admin(other_member):
            return await ctx.send("You are not admin in that server.")

        msg = await ctx.send("This will import all the Defender settings from that server. Role / channel "
                             "specific settings will not carry over. Optionally Warden rules can also be ported over.\n"
                             "Existing settings will be **lost**. React to proceed.")

        def confirm(r, user):
            return user == ctx.author and str(r.emoji) == EMOJI and r.message.id == msg.id

        await msg.add_reaction(EMOJI)
        try:
            await ctx.bot.wait_for('reaction_add', check=confirm, timeout=15)
        except asyncio.TimeoutError:
            return await ctx.send("Import aborted.")

        conf = await self.config.guild(other_guild).all()
        to_copy = conf.copy()
        to_copy.pop("enabled", None)
        enabled = to_copy.pop("notify_channel", None)
        to_copy.pop("punish_role", None)
        to_copy.pop("notify_role", None)
        to_copy.pop("trusted_roles", None)
        to_copy.pop("helper_roles", None)
        to_copy.pop("announcements_sent", None)
        has_rules = bool(to_copy.pop("wd_rules", {}))

        if not enabled:
            return await ctx.send("That server doesn't have Defender configured. Import aborted.")

        async with self.config.guild(ctx.guild).all() as guild_data:
            guild_data.update(to_copy)

        imported = 0
        failed = 0
        if has_rules:
            msg = await ctx.send("I have imported the settings. Do you also want to import their "
                                 "Warden rules? Any existing Warden rule with the same name will be "
                                 "overwritten. React to confirm.")
            def confirm(r, user):
                return user == ctx.author and str(r.emoji) == EMOJI and r.message.id == msg.id

            await msg.add_reaction(EMOJI)
            try:
                await ctx.bot.wait_for('reaction_add', check=confirm, timeout=15)
            except asyncio.TimeoutError:
                return await ctx.send("Warden rules importation aborted.")

            other_rules = self.active_warden_rules.get(other_guild.id, {})
            to_add_raw = {}
            for rule in other_rules.values():
                new_rule = WardenRule()

                try:
                    await new_rule.parse(rule.raw_rule, self, author=ctx.author)
                except Exception:
                    failed += 1
                else:
                    self.active_warden_rules[ctx.guild.id][rule.name] = rule
                    to_add_raw[new_rule.name] = new_rule.raw_rule
                    imported += 1

            async with self.config.guild(ctx.guild).wd_rules() as wd_rules:
                wd_rules.update(to_add_raw)

        imported_txt = "" if not imported else f" Imported {imported} rules. "
        failed_txt = "" if not failed else f" Failed to import {failed} rules. "
        await ctx.send(f"Configuration import completed successfully.{imported_txt}{failed_txt}"
                       f"\nPlease check `{ctx.prefix}def status` for any remaining feature left to "
                       "set up.")

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
        if everyone not in channel.overwrites or channel.overwrites[everyone].read_messages in (True, None):
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

    @generalgroup.command(name="punishrole")
    async def generalgrouppunishrole(self, ctx: commands.Context, role: discord.Role):
        """Sets the role that will be assigned to misbehaving users

        Note: this will only be assigned if the 'action' of a module
        is set to 'punish'."""
        if self.is_role_privileged(role, ctx.author.top_role):
            return await ctx.send("I cannot let you proceed: that role has either privileged "
                                  "permissions or is higher than your top role in the role hierarchy. "
                                  "The punish role is meant to be assigned to misbehaving users, "
                                  "it is not supposed to have any sort of privilege.")
        await self.config.guild(ctx.guild).punish_role.set(role.id)
        await ctx.send("Role set. Remember that you're supposed to configure this role in a way that is "
                       "somehow limiting to the user. Whether this means preventing them from sending "
                       "messages or only post in certain channels is up to you.")

    @generalgroup.command(name="punishmessage")
    async def generalgrouppunishmessage(self, ctx: commands.Context, *, message: str):
        """Sets the messages that I will send after assigning the punish role

        Supports context variables. You can add the following to your message:
        $user -> User's name + tag
        $user_name -> User's name
        $user_display -> User's nickname if set or user's name
        $user_id -> User's id
        $user_mention -> User's mention
        $user_nickname -> User's nickname if set or 'None'"""
        if len(message) > 1950: # Since 4k messages might soon be a thing let's check for this
            return await ctx.send("The message is too long.")
        await self.config.guild(ctx.guild).punish_message.set(message)
        await ctx.tick()

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
        self.active_warden_rules.pop(ctx.guild.id, None)
        self.invalid_warden_rules.pop(ctx.guild.id, None)
        await ctx.tick()

    @generalgroup.command(name="messagecacheexpire")
    @commands.is_owner()
    async def generalgroupcacheexpire(self, ctx: commands.Context, hours: int):
        """Sets how long a message should be cached before being discarded"""
        if hours < 2 or hours > 720:
            return await ctx.send("A number between 2 and 720 please.")
        df_cache.MSG_EXPIRATION_TIME = hours
        await self.config.cache_expiration.set(hours)
        await ctx.send("Value set. If you experience out of memory issues it might be "
                       "a good idea to tweak this setting.")

    @generalgroup.command(name="messagecachecap")
    @commands.is_owner()
    async def generalgroupcachecap(self, ctx: commands.Context, messages: int):
        """Sets the maximum # of messages to cache for each user / channel"""
        if messages < 100 or messages > 999999:
            return await ctx.send("A number between 100 and 999999 please.")
        df_cache.MSG_STORE_CAP = messages
        await self.config.cache_cap.set(messages)
        await ctx.send("Value set. If you experience out of memory issues it might be "
                       "a good idea to tweak this setting.")

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

    @dset.group(name="invitefilter", aliases=["if"])
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
        """Sets action (ban, kick, softban, punish or none (deletion only))"""
        action = action.lower()
        try:
            Action(action)
        except:
            await ctx.send("Not a valid action. Must be ban, kick, softban, punish or none.")
            return
        await self.config.guild(ctx.guild).invite_filter_action.set(action)
        if Action(action) == Action.NoAction:
            await ctx.send("Action set. Since you've chosen 'none' I may only delete "
                           "the invite link (`[p]dset if deletemessage`) and notify the staff about it.")
        await ctx.tick()

    @invitefiltergroup.command(name="excludeowninvites")
    async def invitefilterexcludeowninvites(self, ctx: commands.Context, yes_or_no: bool):
        """Excludes this server's invites from the filter"""
        await self.config.guild(ctx.guild).invite_filter_exclude_own_invites.set(yes_or_no)
        if yes_or_no:
            perms = ""
            if not ctx.guild.me.guild_permissions.manage_guild:
                perms = "However, I will need 'Manage server' permissions in order to do that."
            await ctx.send(f"Got it. I will not take action on invites that belong to this server. {perms}")
        else:
            await ctx.send("Got it. I will take action on any invite, even ours.")

    @invitefiltergroup.command(name="deletemessage")
    async def invitefilterdeletemessage(self, ctx: commands.Context, on_or_off: bool):
        """Toggles whether to delete the invite's message"""
        await self.config.guild(ctx.guild).invite_filter_delete_message.set(on_or_off)
        if on_or_off:
            await ctx.send("I will delete the message containing the invite.")
        else:
            await ctx.send("I will not delete the message containing the invite.")

    @invitefiltergroup.command(name="wdchecks")
    async def invitefilterwdchecks(self, ctx: commands.Context, *, conditions: str=""):
        """Implement advanced Warden based checks

        Issuing this command with no arguments will show the current checks
        Passing 'remove' will remove existing checks"""
        await self.wd_check_manager(ctx, WDChecksKeys.InviteFilter, conditions)

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

    @vaporizegroup.command(name="maxtargets")
    async def vaporizegroupmaxtargets(self, ctx: commands.Context, max_targets: int):
        """Sets the maximum amount of targets (1-999)

        By default only a maximum of 15 users can be vaporized at once"""
        if max_targets < 1 or max_targets > 999:
            return await ctx.send_help()

        await self.config.guild(ctx.guild).vaporize_max_targets.set(max_targets)
        await ctx.tick()

    @dset.group(name="joinmonitor", aliases=["jm"])
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

    @joinmonitorgroup.command(name="verificationlevel")
    async def joinmonitorvlevel(self, ctx: commands.Context):
        """Raises the server's verification level on raids

        You can find a full description of Discord's verification levels in
        the server's settings "Moderation" tab.

        Verification levels:
        0 - No action
        1 - Low: verified email
        2 - Medium: must be registered for longer than 5 minutes
        3 - High: must be a member of this server for longer than 10 minutes
        4 - Highest: must have a verified phone on their Discord account"""
        if not ctx.me.guild_permissions.manage_guild:
            return await ctx.send("I cannot do this without `Manage server` permissions. "
                                  "Please fix this and try again.")

        select_options = (
            SelectOption(value="0", label="No action", description="Are you sure?", emoji="🤠"),
            SelectOption(value="1", label="Low", description="Must have a verified email address on their Discord", emoji="🟢"),
            SelectOption(value="2", label="Medium", description="Must also be registered on Discord for >= 5 minutes", emoji="🟡"),
            SelectOption(value="3", label="High", description="Must also be a member here for more than 10 minutes", emoji="🟠"),
            SelectOption(value="4", label="Highest", description="Must also have a verified phone on their Discord", emoji="🔴"),
        )

        view = RestrictedView(self, ctx.author.id)
        view.add_item(
            SettingSetSelect(
                config_value=self.config.guild(ctx.guild).join_monitor_v_level,
                current_settings=await self.config.guild(ctx.guild).join_monitor_v_level(),
                select_options=select_options,
                max_values=1,
                cast_to=int
            )
        )

        await ctx.send("Select the verification level that will be set when a raid is detected", view=view)

    @joinmonitorgroup.command(name="wdchecks")
    async def joinmonitorwdchecks(self, ctx: commands.Context, *, conditions: str=""):
        """Implement advanced Warden based checks

        Issuing this command with no arguments will show the current checks
        Passing 'remove' will remove existing checks"""
        await self.wd_check_manager(ctx, WDChecksKeys.JoinMonitor, conditions)

    @dset.group(name="raiderdetection", aliases=["rd"])
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
        """Sets action (ban, kick, softban, punish or none (notify only))"""
        action = action.lower()
        try:
            Action(action)
        except:
            await ctx.send("Not a valid action. Must be ban, kick, softban, punish or none.")
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

    @raiderdetectiongroup.command(name="wdchecks")
    async def raiderdetectiongroupwdchecks(self, ctx: commands.Context, *, conditions: str=""):
        """Implement advanced Warden based checks

        Issuing this command with no arguments will show the current checks
        Passing 'remove' will remove existing checks"""
        await self.wd_check_manager(ctx, WDChecksKeys.RaiderDetection, conditions)

    @dset.group(name="warden", aliases=["wd"])
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

    @wardenset.command(name="regexallowed")
    @commands.is_owner()
    async def wardensetregex(self, ctx: commands.Context, on_or_off: bool):
        """Toggles the ability to globally create rules with user defined regex"""
        await self.config.wd_regex_allowed.set(on_or_off)
        if on_or_off:
            await ctx.send("All servers will now be able to create Warden rules with user defined regex. "
                           "Keep in mind that badly designed regex can affect bot performances. Defender, "
                           "other than actively trying to prevent or mitigate this issue, will also report "
                           "such occurrences in the bot logs.")
        else:
            await ctx.send("The creation of Warden rules with user defined regex has been disabled for "
                           "all servers. Existing rules with regex conditions will not work anymore.")

    @wardenset.command(name="regexsafetychecks")
    @commands.is_owner()
    async def wardenregexsafetychecks(self, ctx: commands.Context, on_or_off: bool):
        """Globally toggles the safety checks for user defined regex

        These checks disable Warden rules with regex that takes too long to be evaluated. It is
        recommended to keep this feature enabled."""
        await self.config.wd_regex_safety_checks.set(on_or_off)
        if on_or_off:
            await ctx.send("Global safety checks for user defined regex are now enabled.")
        else:
            await ctx.send("Global safety checks for user defined regex are now disabled. Please note "
                           "that badly designed regex can affect bot performances. Keep this in mind if "
                           "at any point you experience high resource usage on the host.")

    @wardenset.command(name="periodicallowed")
    @commands.is_owner()
    async def wardensetperiodic(self, ctx: commands.Context, on_or_off: bool):
        """Toggles the ability to globally create periodic rules

        Periodic rules are rules that can be scheduled to run against
        an entire server userbase on an interval between 5 minutes and 24 hours
        """
        await self.config.wd_periodic_allowed.set(on_or_off)
        if on_or_off:
            await ctx.send("All servers will now be able to create periodic Warden rules.")
        else:
            await ctx.send("The creation of periodic Warden rules has been disabled for all servers. "
                           "Existing periodic rules will not be run anymore.")

    @wardenset.command(name="uploadmaxsize")
    @commands.is_owner()
    async def wardenuploadmaxsize(self, ctx: commands.Context, kilobytes: int):
        """Sets the maximum allowed size for Warden rules upload

        Reccommended size is 3KB"""
        if kilobytes < 2 or kilobytes > 50:
            return await ctx.send("Maximum size must be between 2 and 50KB.")
        await self.config.wd_upload_max_size.set(kilobytes)
        await ctx.send(f"Size set. I will not accept any rule bigger than {kilobytes}KB.")

    @dset.group(name="commentanalysis", aliases=["ca"])
    @commands.admin()
    async def caset(self, ctx: commands.Context):
        """Comment analysis configuration

        See [p]defender status for more information about this module"""

    @caset.command(name="enable")
    async def casetenable(self, ctx: commands.Context, on_or_off: bool):
        """Toggles comment analysis"""
        if not await self.config.guild(ctx.guild).ca_token():
            return await ctx.send("There is no Perspective API token set.")
        await self.config.guild(ctx.guild).ca_enabled.set(on_or_off)
        if on_or_off:
            await ctx.send("Comment analysis enabled.")
        else:
            await ctx.send("Comment analysis disabled.")

    @caset.command(name="token")
    async def casettoken(self, ctx: commands.Context, token: str):
        """Sets Perspective API token

        https://developers.perspectiveapi.com/s/docs"""
        if len(token) < 30 or len(token) > 50:
            return await ctx.send("That doesn't look like a valid Perspective API token.")
        await self.config.guild(ctx.guild).ca_token.set(token)
        await ctx.tick()

    @caset.command(name="attributes")
    async def casetattributes(self, ctx: commands.Context):
        """Setup the attributes that CA will check"""
        select_options = (
            SelectOption(value=PAttr.Toxicity.value, label="Toxicity", description="Rude or generally disrespectful comments"),
            SelectOption(value=PAttr.SevereToxicity.value, label="Severe toxicity", description="Hateful, aggressive comments"),
            SelectOption(value=PAttr.IdentityAttack.value, label="Identity attack", description="Hateful comments attacking one's identity"),
            SelectOption(value=PAttr.Insult.value, label="Insult", description="Insulting, inflammatory or negative comments"),
            SelectOption(value=PAttr.Profanity.value, label="Profanity", description="Comments containing swear words, curse words or profanities"),
            SelectOption(value=PAttr.Threat.value, label="Threat", description="Comments perceived as an intention to inflict violence against others"),
        )

        view = RestrictedView(self, ctx.author.id)
        view.add_item(
            SettingSetSelect(
                config_value=self.config.guild(ctx.guild).ca_attributes,
                current_settings=await self.config.guild(ctx.guild).ca_attributes(),
                select_options=select_options,
                min_values=1,
            )
        )
        await ctx.send("Select the attributes that Comment Analysis will check. You can find more "
                       f"information here:\n{P_ATTRS_URL}", view=view)

    @caset.command(name="threshold")
    async def casetthreshold(self, ctx: commands.Context, threshold: int):
        """Sets the threshold that will trigger CA's action (20-100)"""
        if threshold < 20 or threshold > 100:
            return await ctx.send("The threshold must be a value between 20 and 100.")
        await self.config.guild(ctx.guild).ca_threshold.set(threshold)
        await ctx.tick()

    @caset.command(name="rank")
    async def casetrank(self, ctx: commands.Context, rank: int):
        """Sets target rank"""
        try:
            Rank(rank)
        except:
            await ctx.send("Not a valid rank. Must be 1-4.")
            return
        await self.config.guild(ctx.guild).ca_rank.set(rank)
        await ctx.tick()

    @caset.command(name="action")
    async def casetaction(self, ctx: commands.Context, action: str):
        """Sets action (ban, kick, softban, punish or none (notification only))"""
        action = action.lower()
        try:
            Action(action)
        except:
            await ctx.send("Not a valid action. Must be ban, kick, softban or none.")
            return
        await self.config.guild(ctx.guild).ca_action.set(action)
        if Action(action) == Action.NoAction:
            await ctx.send("Action set. Since you've chosen 'none' I will only "
                           "notify the staff about it.")
        await ctx.tick()

    @caset.command(name="reason")
    async def casetreason(self, ctx: commands.Context, *, reason: str):
        """Sets a reason for the action (modlog use)"""
        if len(reason) < 1 or len(reason) > 500:
            return await ctx.send("The reason can only contain a maximum of 500 characters.")
        await self.config.guild(ctx.guild).ca_reason.set(reason)
        await ctx.tick()

    @caset.command(name="wipe")
    async def casetwipe(self, ctx: commands.Context, days: int):
        """Sets how many days worth of messages to delete if the action is ban

        Setting 0 will not delete any message"""
        if days < 0 or days > 7:
            return await ctx.send("Value must be between 0 and 7.")
        await self.config.guild(ctx.guild).ca_wipe.set(days)
        await ctx.send(f"Value set. I will delete {days} days worth "
                       "of messages if the action is ban.")

    @caset.command(name="deletemessage")
    async def casetdeletemessage(self, ctx: commands.Context, on_or_off: bool):
        """Toggles whether to delete the offending message"""
        await self.config.guild(ctx.guild).ca_delete_message.set(on_or_off)
        if on_or_off:
            await ctx.send("I will delete the offending message.")
        else:
            await ctx.send("I will not delete the offending message.")

    @caset.command(name="wdchecks")
    async def casetwdchecks(self, ctx: commands.Context, *, conditions: str=""):
        """Implement advanced Warden based checks

        Issuing this command with no arguments will show the current checks
        Passing 'remove' will remove existing checks"""
        await self.wd_check_manager(ctx, WDChecksKeys.CommentAnalysis, conditions)

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
        """Sets action (ban, kick, softban, punish)"""
        action = action.lower()
        try:
            if action == Action.NoAction.value:
                raise ValueError()
            Action(action)
        except:
            await ctx.send("Not a valid action. Must be ban, kick, softban or punish.")
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
    async def emergencygroupmodules(self, ctx: commands.Context):
        """Sets emergency modules

        Emergency modules will be rendered available to helper roles
        during emergency mode. Selecting no modules to this command will
        disable emergency mode.
        Available emergency modules: voteout, vaporize, silence"""
        select_options = (
            SelectOption(value=EModules.Silence.value, label="Silence", description="Apply a server wide mute on ranks", emoji="🔇"),
            SelectOption(value=EModules.Vaporize.value, label="Vaporize", description="Silently get rid of multiple new users at once", emoji="☁️"),
            SelectOption(value=EModules.Voteout.value, label="Voteout", description="Start a vote to expel misbehaving users", emoji="👎"),
        )

        view = RestrictedView(self, ctx.author.id)
        view.add_item(
            SettingSetSelect(
                config_value=self.config.guild(ctx.guild).emergency_modules,
                current_settings=await self.config.guild(ctx.guild).emergency_modules(),
                select_options=select_options,
                placeholder="Select 0 or more modules",
                min_values=0,
            )
        )
        await ctx.send("Select the modules that you want available to helpers during an emergency. "
                       "Deselecting all of them will disable emergency mode.", view=view)

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

    async def wd_check_manager(self, ctx, module, conditions):
        if conditions == "":
            raw_check = await WardenAPI.get_check(ctx.guild, module)
            if raw_check is None:
                return await ctx.send_help()

            no_box = "```" in raw_check
            if no_box:
                raw_check = escape(raw_check, formatting=True)

            rm_how_to = "Pass `remove` to this command to remove these checks.\n\n"

            for p in pagify(raw_check, page_length=1900, escape_mass_mentions=False):
                if no_box:
                    await ctx.send(rm_how_to + p)
                else:
                    await ctx.send(rm_how_to + box(p, lang="yml"))
                rm_how_to = ""
        elif conditions.lower() == "remove":
            await WardenAPI.remove_check(ctx.guild, module)
            await ctx.tick()
        else:
            try:
                await WardenAPI.set_check(ctx.guild, module, conditions, ctx.author)
            except Exception as e:
                await ctx.send(f"Error setting the checks: {e}")
            else:
                await ctx.send("Warden checks set. These additional checks will be evaluated "
                               "*after* the module's standard checks (e.g. rank)")