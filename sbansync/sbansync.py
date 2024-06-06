"""
Simplebansync - A simple, no frills bansync cog
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

from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.commands import GuildConverter
from redbot.core.config import Config
from redbot.core.utils.chat_formatting import inline
from enum import Enum
from collections import Counter
import discord
import logging

log = logging.getLogger("red.x26cogs.simplebansync")


class Operation(Enum):
    Pull = 1
    Push = 2
    Sync = 3


class Sbansync(commands.Cog):
    """Pull, push and sync bans between servers"""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=262_626, force_registration=True)
        self.config.register_guild(allow_pull_from=[], allow_push_to=[], silently=False)

    @commands.group()
    @commands.guild_only()
    @commands.admin()
    async def sbansync(self, ctx: commands.Context):
        """Pull, push and sync bans between servers"""
        if await self.callout_if_fake_admin(ctx):
            ctx.invoked_subcommand = None

    @sbansync.command(name="pull")
    @commands.bot_has_permissions(ban_members=True)
    async def sbansyncpullfrom(self, ctx: commands.Context, *, server: GuildConverter):
        """Pulls bans from a server

        The command issuer must be an admin on that server OR the server
        needs to whitelist this one for pull operations"""
        author = ctx.author
        if not await self.is_member_allowed(Operation.Pull, author, server):
            return await ctx.send("This server is not in that server's pull list.")

        async with ctx.typing():
            try:
                stats = await self.do_operation(Operation.Pull, author, server)
            except RuntimeError as e:
                return await ctx.send(str(e))

        text = ""

        if stats:
            for k, v in stats.items():
                text += f"{k} {v}\n"
        else:
            text = "No bans to pull."

        silently = await self.config.guild(ctx.guild).silently()

        if silently:
            await ctx.tick()
        else:
            await ctx.send(text)

    @sbansync.command(name="push")
    @commands.bot_has_permissions(ban_members=True)
    async def sbansyncpushto(self, ctx: commands.Context, *, server: GuildConverter):
        """Pushes bans to a server

        The command issuer must be an admin on that server OR the server
        needs to whitelist this one for push operations"""
        author = ctx.author
        if not await self.is_member_allowed(Operation.Push, author, server):
            return await ctx.send("This server is not in that server's push list.")

        async with ctx.typing():
            try:
                stats = await self.do_operation(Operation.Push, author, server)
            except RuntimeError as e:
                return await ctx.send(str(e))

        text = ""

        if stats:
            for k, v in stats.items():
                text += f"{k} {v}\n"
        else:
            text = "No bans to push."

        silently = await self.config.guild(ctx.guild).silently()

        if silently:
            await ctx.tick()
        else:
            await ctx.send(text)

    @sbansync.command(name="sync")
    @commands.bot_has_permissions(ban_members=True)
    async def sbansyncsyncwith(self, ctx: commands.Context, *, server: GuildConverter):
        """Syncs bans with a server

        The command issuer must be an admin on that server OR the server
        needs to whitelist this one for push and pull operations"""
        author = ctx.author
        if not await self.is_member_allowed(Operation.Sync, author, server):
            return await ctx.send("This server is not in that server's push and/or pull list.")

        async with ctx.typing():
            try:
                stats = await self.do_operation(Operation.Sync, author, server)
            except RuntimeError as e:
                return await ctx.send(str(e))

        text = ""

        if stats:
            for k, v in stats.items():
                text += f"{k} {v}\n"
        else:
            text = "No bans to sync."

        silently = await self.config.guild(ctx.guild).silently()

        if silently:
            await ctx.tick()
        else:
            await ctx.send(text)

    @commands.group()
    @commands.guild_only()
    @commands.admin()
    async def sbansyncset(self, ctx: commands.Context):
        """SimpleBansync settings"""
        if await self.callout_if_fake_admin(ctx):
            ctx.invoked_subcommand = None

    @sbansyncset.command(name="addpush")
    async def sbansyncsaddpush(self, ctx: commands.Context, *, server: GuildConverter):
        """Allows a server to push bans to this one"""
        async with self.config.guild(ctx.guild).allow_push_to() as allowed_push:
            if server.id not in allowed_push:
                allowed_push.append(server.id)
        await ctx.send(f"`{server.name}` will now be allowed to **push** bans to this server.")

    @sbansyncset.command(name="addpull")
    async def sbansyncsaddpull(self, ctx: commands.Context, *, server: GuildConverter):
        """Allows a server to pull bans from this one"""
        async with self.config.guild(ctx.guild).allow_pull_from() as allowed_pull:
            if server.id not in allowed_pull:
                allowed_pull.append(server.id)
        await ctx.send(f"`{server.name}` will now be allowed to **pull** bans from this server.")

    @sbansyncset.command(name="removepush")
    async def sbansyncsremovepush(self, ctx: commands.Context, *, server: GuildConverter):
        """Disallows a server to push bans to this one"""
        async with self.config.guild(ctx.guild).allow_push_to() as allowed_push:
            if server.id in allowed_push:
                allowed_push.remove(server.id)
        await ctx.send(
            f"`{server.name}` has been removed from the list of servers allowed to " "**push** bans to this server."
        )

    @sbansyncset.command(name="removepull")
    async def sbansyncsremovepull(self, ctx: commands.Context, *, server: GuildConverter):
        """Disallows a server to pull bans from this one"""
        async with self.config.guild(ctx.guild).allow_pull_from() as allowed_pull:
            if server.id in allowed_pull:
                allowed_pull.remove(server.id)
        await ctx.send(
            f"`{server.name}` has been removed from the list of servers allowed to " "**pull** bans from this server."
        )

    @sbansyncset.command(name="clearpush")
    async def sbansyncsaclearpush(self, ctx: commands.Context):
        """Clears the list of servers allowed to push bans to this one"""
        await self.config.guild(ctx.guild).allow_push_to.clear()
        await ctx.send(
            "Push list cleared. Only local admins are now allowed to push bans to this " "server from elsewhere."
        )

    @sbansyncset.command(name="clearpull")
    async def sbansyncsclearpull(self, ctx: commands.Context):
        """Clears the list of servers allowed to pull bans from this one"""
        await self.config.guild(ctx.guild).allow_pull_from.clear()
        await ctx.send(
            "Pull list cleared. Only local admins are now allowed to pull bans from this " "server from elsewhere."
        )

    @sbansyncset.command(name="showlists", aliases=["showsettings"])
    async def sbansyncsshowlists(self, ctx: commands.Context):
        """Shows the current pull and push lists"""
        b = self.bot
        pull = await self.config.guild(ctx.guild).allow_pull_from()
        push = await self.config.guild(ctx.guild).allow_push_to()
        pull = [inline(b.get_guild(s).name) for s in pull if b.get_guild(s)] or ["None"]
        push = [inline(b.get_guild(s).name) for s in push if b.get_guild(s)] or ["None"]

        await ctx.send(f"Pull: {', '.join(pull)}\nPush: {', '.join(push)}")

    @sbansyncset.command(name="silently")
    async def sbansyncssilently(self, ctx: commands.Context, on_or_off: bool):
        """Toggle whether to perform operations silently

        This is is useful in case pull, push and syncs are done by tasks
        instead of manually"""
        await self.config.guild(ctx.guild).silently.set(on_or_off)

        if on_or_off:
            await ctx.send("I will perform pull, push and syncs silently.")
        else:
            await ctx.send("I will report the number of users affected for each operation.")

    async def is_member_allowed(self, operation: Operation, member: discord.Member, target: discord.Guild):
        """A member is allowed to pull, push or sync to a guild if:
            A) Has an admin role in the target server WITH ban permissions
            B) The target server has whitelisted our server for this operation
        """
        target_member = target.get_member(member.id)
        if target_member:
            is_admin_in_target = await self.bot.is_admin(target_member)
            has_ban_perms = target_member.guild_permissions.ban_members
            if is_admin_in_target and has_ban_perms:
                return True

        allow_pull = member.guild.id in await self.config.guild(target).allow_pull_from()
        allow_push = member.guild.id in await self.config.guild(target).allow_push_to()

        if operation == Operation.Pull:
            return allow_pull
        elif operation == Operation.Push:
            return allow_push
        elif operation == Operation.Sync:
            return allow_pull and allow_push
        else:
            raise ValueError("Invalid operation")

    async def do_operation(self, operation: Operation, member: discord.Member, target_guild: discord.Guild):
        guild = member.guild
        if not target_guild.me.guild_permissions.ban_members:
            raise RuntimeError("I do not have ban members permissions in the target server.")

        stats = Counter()

        guild_bans = [m.user async for m in guild.bans(limit=None)]
        target_bans = [m.user async for m in target_guild.bans(limit=None)]

        if operation in (Operation.Pull, Operation.Sync):
            for m in target_bans:
                if m not in guild_bans:
                    try:
                        await guild.ban(m, delete_message_seconds=0, reason=f"Syncban issued by {member} ({member.id})")
                    except (discord.Forbidden, discord.HTTPException):
                        stats["Failed pulls: "] += 1
                    else:
                        stats["Pulled bans: "] += 1

        if operation in (Operation.Push, Operation.Sync):
            for m in guild_bans:
                if m not in target_bans:
                    try:
                        await target_guild.ban(
                            m, delete_message_seconds=0, reason=f"Syncban issued by {member} ({member.id})"
                        )
                    except (discord.Forbidden, discord.HTTPException):
                        stats["Failed pushes: "] += 1
                    else:
                        stats["Pushed bans: "] += 1

        return stats

    async def callout_if_fake_admin(self, ctx):
        if ctx.invoked_subcommand is None:
            # User is just checking out the help
            return False
        error_msg = (
            "It seems that you have a role that is considered admin at bot level but "
            "not the basic permissions that one would reasonably expect an admin to have.\n"
            "To use these commands, other than the admin role, you need `administrator` "
            "permissions OR `ban members`.\n"
            "I cannot let you proceed until you properly configure permissions in this server."
        )
        channel = ctx.channel
        has_ban_perms = channel.permissions_for(ctx.author).ban_members

        if not has_ban_perms:
            await ctx.send(error_msg)
            return True
        return False
