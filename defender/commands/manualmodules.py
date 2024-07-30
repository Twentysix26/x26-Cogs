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

from ..enums import EmergencyMode
from ..abc import MixinMeta, CompositeMetaClass
from ..enums import EmergencyModules, Action, Rank
from ..core.menus import EmergencyView
from redbot.core import commands
from redbot.core.utils.chat_formatting import box
import discord
import asyncio


class ManualModules(MixinMeta, metaclass=CompositeMetaClass):  # type: ignore
    @commands.cooldown(1, 120, commands.BucketType.channel)
    @commands.command(aliases=["staff"])
    @commands.guild_only()
    async def alert(self, ctx):
        """Alert the staff members"""
        guild = ctx.guild
        author = ctx.author
        message = ctx.message
        EMBED_TITLE = "🚨 • Alert"
        EMBED_FIELDS = [{"name": "Issuer", "value": f"`{author}`"},
                        {"name": "ID", "value": f"`{author.id}`"},
                        {"name": "Channel", "value": message.channel.mention}]
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
        if emergency_modules:
            react_text = " Press the button or take some actions in this server to disable the emergency timer."

        await self.send_notification(guild,
                                    f"An alert has been issued!{react_text}",
                                     title=EMBED_TITLE,
                                     fields=EMBED_FIELDS,
                                     ping=True,
                                     jump_to=ctx.message,
                                     view=EmergencyView(self))
        await ctx.send("The staff has been notified. Please keep calm, I'm sure everything is fine. 🔥")

        ### Emergency mode

        if not emergency_modules:
            return

        if self.is_in_emergency_mode(guild):
            return

        async def check_audit_log():
            try:
                await self.refresh_with_audit_logs_activity(guild)
            except discord.Forbidden: # No access to the audit log, welp
                pass

        async def maybe_delete(message):
            if not message:
                return
            try:
                await message.delete()
            except:
                pass

        await asyncio.sleep(60)
        await check_audit_log()
        active = self.has_staff_been_active(guild, minutes=1)
        if active: # Someone was active very recently
            return

        minutes = await self.config.guild(guild).emergency_minutes()
        minutes -= 1
        last_msg = None

        if minutes: # This whole countdown thing is skipped if the max inactivity is a single minute
            text = ("⚠️ No staff activity detected in the past minute. "
                    "Emergency mode will be engaged in {} minutes. "
                    "Please stand by. ⚠️")

            last_msg = await ctx.send(f"{ctx.author.mention} " + text.format(minutes))
            await self.send_notification(guild, "⚠️ Looks like you're not around. I will automatically engage "
                                                f"emergency mode in {minutes} minutes if you don't show up.",
                                                force_text_only=True)
            while minutes != 0:
                await asyncio.sleep(60)
                await check_audit_log()
                if self.has_staff_been_active(guild, minutes=1):
                    await maybe_delete(last_msg)
                    ctx.command.reset_cooldown(ctx)
                    await ctx.send("Staff activity detected. Alert deactivated. "
                                    "Thanks for helping keep the community safe.")
                    return
                minutes -= 1
                if minutes % 2: # Halves the # of messages
                    await maybe_delete(last_msg)
                    last_msg = await ctx.send(text.format(minutes))

        guide = {
            EmergencyModules.Voteout: "voteout <user>` - Start a vote to expel a user from the server",
            EmergencyModules.Vaporize: ("vaporize <users...>` - Allows you to mass ban users from "
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
                                            f"**{', '.join(emergency_modules)}** modules.", force_text_only=True)

        await ctx.send(text)
        self.dispatch_event("emergency", guild)
        await maybe_delete(last_msg)

    @commands.command()
    @commands.guild_only()
    async def vaporize(self, ctx, *members: discord.Member):
        """Gets rid of bad actors in a quick and silent way

        Works only on Rank 3 and under"""
        guild = ctx.guild
        channel = ctx.channel
        EMBED_TITLE = "☁️ • Vaporize"
        EMBED_FIELDS = [{"name": "Issuer", "value": f"`{ctx.author}`"},
                        {"name": "ID", "value": f"`{ctx.author.id}`"},
                        {"name": "Channel", "value": channel.mention}]
        has_ban_perms = channel.permissions_for(ctx.author).ban_members
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
            if is_staff and not enabled:
                ctx.command.reset_cooldown(ctx)
                return await ctx.send("This command is not available right now.")
            if is_staff and not has_ban_perms:
                ctx.command.reset_cooldown(ctx)
                if em_enabled:
                    return await ctx.send("You need ban permissions to use this module outside of emergency mode.")
                else:
                    return await ctx.send("You need ban permissions to use this module.")

        guild = ctx.guild
        if not members:
            await ctx.send_help()
            return
        max_targets = await self.config.guild(guild).vaporize_max_targets()
        if len(members) > max_targets:
            await ctx.send(f"No more than {max_targets} users at once. Please try again.")
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
        await self.send_notification(guild, f"{total} users have been vaporized.",
                                     title=EMBED_TITLE, fields=EMBED_FIELDS, jump_to=ctx.message)

    @commands.cooldown(1, 22, commands.BucketType.guild)  # More useful as a lock of sorts in this case
    @commands.command(cooldown_after_parsing=True)        # Only one concurrent session per guild
    @commands.guild_only()
    async def voteout(self, ctx, *, user: discord.Member):
        """Initiates a vote to expel a user from the server

        Can be used by members with helper roles during emergency mode"""
        EMOJI = "👢"
        guild = ctx.guild
        channel = ctx.channel
        EMBED_TITLE = "👍 👎 • Voteout"
        EMBED_FIELDS = [{"name": "Username", "value": f"`{user}`"},
                        {"name": "ID", "value": f"`{user.id}`"},
                        {"name": "Channel", "value": channel.mention}]
        action = await self.config.guild(guild).voteout_action()
        user_perms = channel.permissions_for(ctx.author)
        if Action(action) == Action.Ban:
            perm_text = "ban"
            has_action_perms = user_perms.ban_members
        else: # Kick / Softban
            perm_text = "kick"
            has_action_perms = user_perms.kick_members

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
            if is_staff and not enabled:
                ctx.command.reset_cooldown(ctx)
                return await ctx.send("This command is not available right now.")
            if is_staff and not has_action_perms:
                ctx.command.reset_cooldown(ctx)
                if em_enabled:
                    return await ctx.send(f"You need {perm_text} permissions to use this module outside of "
                                          "emergency mode.")
                else:
                    return await ctx.send(f"You need {perm_text} permissions to use this module.")

        required_rank = await self.config.guild(guild).voteout_rank()
        target_rank = await self.rank_user(user)
        if target_rank < required_rank:
            ctx.command.reset_cooldown(ctx)
            await ctx.send("You cannot vote to expel that user. "
                           f"User rank: {target_rank.value} (Must be rank {required_rank} or below)")
            return

        required_votes = await self.config.guild(guild).voteout_votes()

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

        voters_list = "\n".join([f"{v} ({v.id})" for v in voters])
        if Action(action) == Action.Ban:
            action_text = "Votebanned with Defender."
            days = await self.config.guild(guild).voteout_wipe()
            reason = f"{action_text} Voters: {voters_list}"
            await guild.ban(user, reason=reason, delete_message_days=days)
            self.dispatch_event("member_remove", user, Action.Ban.value, reason)
        elif Action(action) == Action.Softban:
            action_text = "Votekicked with Defender." # Softban can be considered a kick
            reason = f"{action_text} Voters: {voters_list}"
            await guild.ban(user, reason=reason, delete_message_days=1)
            await guild.unban(user)
            self.dispatch_event("member_remove", user, Action.Softban.value, reason)
        elif Action(action) == Action.Kick:
            action_text = "Votekicked with Defender."
            reason = f"{action_text} Voters: {voters_list}"
            await guild.kick(user, reason=reason)
            self.dispatch_event("member_remove", user, Action.Kick.value, reason)
        elif Action(action) == Action.Punish:
            action_text = ""
            punish_role = guild.get_role(await self.config.guild(guild).punish_role())
            punish_message = await self.format_punish_message(user)
            if punish_role and not self.is_role_privileged(punish_role):
                await user.add_roles(punish_role, reason="Defender: punish role assignation")
                if punish_message:
                    await ctx.channel.send(punish_message)
            else:
                self.send_to_monitor(guild, "[Voteout] Failed to punish user. Is the punish role "
                                            "still present and with *no* privileges?")
                await ctx.channel.send("The voting session passed but I was not able to punish the "
                                       "user due to a misconfiguration.")
                return
        else:
            raise ValueError("Invalid action set for voteout.")

        await self.send_notification(guild, f"A user has been expelled with "
                                            f"a vote.\nVoters:\n{box(voters_list)}",
                                     title=EMBED_TITLE,
                                     fields=EMBED_FIELDS,
                                     jump_to=msg)

        await self.create_modlog_case(
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
    @commands.guild_only()
    async def silence(self, ctx: commands.Context, rank: int):
        """Enables server wide message autodeletion for the specified rank (and below)

        Passing 0 will disable this."""
        guild = ctx.guild
        channel = ctx.channel
        EMBED_TITLE = "🔇 • Silence"
        EMBED_FIELDS = [{"name": "Issuer", "value": f"`{ctx.author}`"},
                        {"name": "ID", "value": f"`{ctx.author.id}`"}]
        has_mm_perms = channel.permissions_for(ctx.author).manage_messages
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
            if is_staff and not enabled:
                ctx.command.reset_cooldown(ctx)
                return await ctx.send("This command is not available right now.")
            if is_staff and not has_mm_perms:
                ctx.command.reset_cooldown(ctx)
                if em_enabled:
                    return await ctx.send("You need manage messages permissions to use this "
                                          "module outside of emergency mode.")
                else:
                    return await ctx.send("You need manage messages permissions to use this module.")

        if rank != 0:
            try:
                Rank(rank)
            except:
                return await ctx.send("Not a valid rank. Must be 1-4.")
        await self.config.guild(ctx.guild).silence_rank.set(rank)
        if rank:
            await self.send_notification(guild, "This module has been enabled. "
                                                f"Message from users belonging to rank {rank} or below will be deleted.",
                                         title=EMBED_TITLE, fields=EMBED_FIELDS, jump_to=ctx.message)
            await ctx.send(f"Any message from Rank {rank} and below will be deleted. "
                           "Set 0 to disable silence mode.")
        else:
            await self.send_notification(guild, "This module has been disabled. Messages will no longer be deleted.",
                                         title=EMBED_TITLE, fields=EMBED_FIELDS, jump_to=ctx.message)
            await ctx.send("Silence mode disabled.")