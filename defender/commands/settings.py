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

from ..abc import MixinMeta, CompositeMetaClass
from ..enums import EmergencyModules, Action, Rank
from redbot.core import commands
from ..core import cache as df_cache
import discord


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
        modules = [m.lower() for m in modules] # type: ignore
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
