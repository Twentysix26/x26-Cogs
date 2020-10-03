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

from defender.enums import EmergencyMode
from ..abc import MixinMeta, CompositeMetaClass
from ..enums import Rank
from ..core.warden.enums import Event as WardenEvent
from ..core.warden.rule import WardenRule
from ..core.warden.enums import Event as WardenEvent
from ..core.status import make_status
from ..core.cache import UserCacheConverter
from ..exceptions import InvalidRule
from ..core.announcements import get_announcements
from redbot.core.utils.menus import DEFAULT_CONTROLS, menu
from redbot.core.utils.chat_formatting import pagify, box, inline
from redbot.core import commands
from io import BytesIO
import logging
import asyncio
import fnmatch
import discord
import datetime

log = logging.getLogger("red.x26cogs.defender")

utcnow = datetime.datetime.utcnow

class StaffTools(MixinMeta, metaclass=CompositeMetaClass): # type: ignore

    @commands.group(aliases=["def"])
    @commands.guild_only()
    @commands.mod()
    async def defender(self, ctx: commands.Context):
        """Defender commands reserved to staff"""

    @defender.command(name="status")
    @commands.bot_has_permissions(embed_links=True, add_reactions=True)
    async def defenderstatus(self, ctx: commands.Context):
        """Shows overall status of the Defender system"""
        pages = await make_status(ctx, self)
        await menu(ctx, pages, DEFAULT_CONTROLS)

    @defender.command(name="monitor")
    async def defendermonitor(self, ctx: commands.Context, *, keywords: str=""):
        """Shows recent events that might require your attention

        Can be filtered. Supports wildcards (* and ?)"""
        monitor = self.monitor[ctx.guild.id].copy()

        if not monitor:
            return await ctx.send("No recent events have been recorded.")

        if keywords:
            if "*" not in keywords and "?" not in keywords:
                keywords = f"*{keywords}*"
            keywords = keywords.lower()
            monitor = [e for e in monitor if fnmatch.fnmatch(e.lower(), keywords)]
            if not monitor:
                return await ctx.send("Filtering by those terms returns no result.")

        pages = list(pagify("\n".join(monitor), page_length=1300))

        if len(pages) == 1:
            await ctx.send(box(pages[0], lang="rust"))
        else:
            pages = [box(p, lang="rust") for p in pages]
            await menu(ctx, pages, DEFAULT_CONTROLS)

    @defender.group(name="messages")
    async def defmessagesgroup(self, ctx: commands.Context):
        """Access recorded messages of users / channels"""

    @defmessagesgroup.command(name="user")
    async def defmessagesgroupuser(self, ctx: commands.Context, user: UserCacheConverter):
        """Shows recent messages of a user"""
        author = ctx.author

        pages = self.make_message_log(user, guild=author.guild, requester=author, pagify_log=True,
                                      replace_backtick=True)

        if not pages:
            return await ctx.send("No messages recorded for that user.")

        self.send_to_monitor(ctx.guild, f"{author} ({author.id}) accessed message history "
                                        f"of user {user} ({user.id})")

        if len(pages) == 1:
            await ctx.send(box(pages[0], lang="rust"))
        else:
            pages = [box(p, lang="rust") for p in pages]
            await menu(ctx, pages, DEFAULT_CONTROLS)

    @defmessagesgroup.command(name="channel")
    async def defmessagesgroupuserchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Shows recent messages of a channel"""
        author = ctx.author
        if not channel.permissions_for(author).read_messages:
            self.send_to_monitor(ctx.guild, f"{author} ({author.id}) attempted to access the message "
                                            f"history of channel #{channel.name}")
            return await ctx.send("You do not have read permissions in that channel. Request denied.")

        pages = self.make_message_log(channel, guild=author.guild, requester=author, pagify_log=True,
                                      replace_backtick=True)

        if not pages:
            return await ctx.send("No messages recorded in that channel.")

        self.send_to_monitor(ctx.guild, f"{author} ({author.id}) accessed the message history "
                                        f"of channel #{channel.name}")

        if len(pages) == 1:
            await ctx.send(box(pages[0], lang="rust"))
        else:
            pages = [box(p, lang="rust") for p in pages]
            await menu(ctx, pages, DEFAULT_CONTROLS)

    @defmessagesgroup.command(name="exportuser")
    async def defmessagesgroupexportuser(self, ctx: commands.Context, user: UserCacheConverter):
        """Exports recent messages of a user to a file"""
        author = ctx.author

        _log = self.make_message_log(user, guild=author.guild, requester=author)

        if not _log:
            return await ctx.send("No messages recorded for that user.")

        self.send_to_monitor(ctx.guild, f"{author} ({author.id}) exported message history "
                                        f"of user {user} ({user.id})")

        ts = utcnow().strftime("%Y-%m-%d")
        _log = "\n".join(_log)
        f = discord.File(BytesIO(_log.encode("utf-8")), f"{ts}-{user.id}.txt")

        await ctx.send(file=f)

    @defmessagesgroup.command(name="exportchannel")
    async def defmessagesgroupuserexportchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Exports recent messages of a channel to a file"""
        author = ctx.author
        if not channel.permissions_for(author).read_messages:
            return await ctx.send("You do not have read permissions in that channel. Request denied.")

        _log = self.make_message_log(channel, guild=author.guild, requester=author)

        if not _log:
            return await ctx.send("No messages recorded in that channel.")

        self.send_to_monitor(ctx.guild, f"{author} ({author.id}) exported message history "
                                        f"of channel #{channel.name}")

        ts = utcnow().strftime("%Y-%m-%d")
        _log = "\n".join(_log)
        f = discord.File(BytesIO(_log.encode("utf-8")), f"{ts}-#{channel.name}.txt")

        await ctx.send(file=f)

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

    @defender.command(name="identify")
    @commands.bot_has_permissions(embed_links=True)
    async def defenderidentify(self, ctx, *, user: discord.Member):
        """Shows a member's rank + info"""
        em = await self.make_identify_embed(ctx.message, user)
        await ctx.send(embed=em)

    @defender.command(name="freshmeat")
    async def defenderfreshmeat(self, ctx, hours: int=24, *, keywords: str=""):
        """Returns a list of the new users of the day

        Can be filtered. Supports wildcards (* and ?)"""
        keywords = keywords.lower()
        msg = ""
        new_members = []
        x_hours_ago = ctx.message.created_at - datetime.timedelta(hours=hours)
        for m in ctx.guild.members:
            if m.joined_at > x_hours_ago:
                new_members.append(m)

        new_members.sort(key=lambda m: m.joined_at, reverse=True)

        if keywords:
            if "*" not in keywords and "?" not in keywords:
                keywords = f"*{keywords}*"
            keywords = keywords.lower()

        for m in new_members:
            if keywords:
                if not fnmatch.fnmatch(m.name.lower(), keywords):
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
                self.dispatch_event("emergency", guild)
            else:
                await ctx.send("Emergency mode is already ongoing.")
        else:
            if emergency_mode:
                del self.emergency_mode[guild.id]
                await self.send_notification(guild, "⚠️ Emergency mode manually disabled.")
            else:
                await ctx.send("Emergency mode is already off.")

    @defender.command(name="updates")
    async def defendererupdates(self, ctx: commands.Context):
        """Shows all the past announcements of Defender"""
        announcements = get_announcements(only_recent=False)
        if announcements:
            announcements = list(announcements.values())
            await menu(ctx, announcements, DEFAULT_CONTROLS)
        else:
            await ctx.send("Nothing to show.")

    @defender.group(name="warden")
    @commands.admin()
    async def wardengroup(self, ctx: commands.Context):
        """Warden rules management

        See [p]defender status for more information about Warden"""
        if await self.callout_if_fake_admin(ctx):
            ctx.invoked_subcommand = None

    @wardengroup.command(name="add")
    async def wardengroupaddrule(self, ctx: commands.Context, *, rule: str):
        """Adds a new rule"""
        EMOJI = "💾"
        guild = ctx.guild
        rule = rule.strip("\n")
        if rule.startswith("```yaml"):
            rule = rule.lstrip("```yaml")
        if rule.startswith("```") or rule.endswith("```"):
            rule = rule.strip("```")

        try:
            new_rule = WardenRule(rule, author=ctx.author)
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
        self.invalid_warden_rules[ctx.guild.id].pop(new_rule.name, None)

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
        guild = ctx.guild
        text = ""
        rules = {}
        for event in WardenEvent:
            rules[event.value] = self.get_warden_rules_by_event(guild, event)
        for k, v in rules.items():
            rules[k] = [inline(r.name) for r in v]
        rules["invalid"] = []
        for k, v in self.invalid_warden_rules[ctx.guild.id].items():
            rules["invalid"].append(inline(v.name))

        text = "Active Warden rules per event:\n\n"
        for k, v in rules.items():
            if k == "invalid":
                continue
            event_name = k.replace("-", " ").capitalize()
            rule_names = ", ".join(v) if v else "No rules set."
            text += f"**{event_name}**:\n{rule_names}\n"
        if rules["invalid"]:
            text += f"\n**Invalid rules**:\n{', '.join(rules['invalid'])}\n"
            text += ("These rules failed the validation process at the last start. Check if "
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

    @wardengroup.command(name="exportall", hidden=True)
    async def wardengroupexportall(self, ctx: commands.Context):
        """Sends all the rules as a tar.gz archive"""
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

    @wardengroup.command(name="run")
    async def wardengrouprun(self, ctx: commands.Context, *, name: str):
        """Runs a rule against the whole userbase

        Confirmation is asked before execution."""
        EMOJI = "✅"
        try:
            rule: WardenRule = self.active_warden_rules[ctx.guild.id][name]
            if WardenEvent.Manual not in rule.events:
                raise InvalidRule()
        except KeyError:
            return await ctx.send("There is no rule with that name.")
        except InvalidRule:
            return await ctx.send("That rule is not meant to be run in manual mode.")

        targets = []

        async with ctx.typing():
            for m in ctx.guild.members:
                if m.bot:
                    continue
                rank = await self.rank_user(m)
                if await rule.satisfies_conditions(rank=rank, user=m, cog=self):
                    targets.append(m)

        if len(targets) == 0:
            return await ctx.send("No user can be affected by this rule.")

        msg = await ctx.send(f"**{len(targets)} users** will be affected by this rule. "
                              "Are you sure you want to continue? React to confirm.")

        def confirm(r, user):
            return user == ctx.author and str(r.emoji) == EMOJI and r.message.id == msg.id

        await msg.add_reaction(EMOJI)
        try:
            r = await ctx.bot.wait_for('reaction_add', check=confirm, timeout=15)
        except asyncio.TimeoutError:
            return await ctx.send("Not proceeding with execution.")

        errors = 0
        async with ctx.typing():
            for m in targets:
                try:
                    await rule.do_actions(user=m, cog=self)
                except:
                    errors += 1

        text = f"Rule `{name}` has been executed on **{len(targets)} users**."
        if errors:
            text += f"\n**{errors}** of them triggered an error on this rule."

        await ctx.send(text)