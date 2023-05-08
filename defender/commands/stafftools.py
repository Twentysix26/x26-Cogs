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

from defender.enums import EmergencyMode
from ..abc import MixinMeta, CompositeMetaClass
from ..enums import Rank
from ..core.warden.enums import Event as WardenEvent
from ..core.warden.rule import WardenRule
from ..core.warden.enums import Event as WardenEvent, ChecksKeys
from ..core.warden.utils import rule_add_periodic_prompt, rule_add_overwrite_prompt, strip_yaml_codeblock
from ..core.warden import heat, api as WardenAPI
from ..core.status import make_status
from ..core.cache import UserCacheConverter
from ..core.utils import utcnow
from ..exceptions import ExecutionError, InvalidRule
from ..core.announcements import get_announcements_embed
from redbot.core.utils import AsyncIter
from redbot.core.utils.menus import DEFAULT_CONTROLS, menu
from redbot.core.utils.chat_formatting import error, pagify, box, inline, escape
from redbot.core import commands
from io import BytesIO
from inspect import cleandoc
from typing import Union
import emoji, pydantic, regex, yaml, sys, rapidfuzz # Debug info purpose
import logging
import asyncio
import fnmatch
import discord
import datetime
import tarfile

log = logging.getLogger("red.x26cogs.defender")

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

    @defender.group(name="messages", aliases=["msg"])
    async def defmessagesgroup(self, ctx: commands.Context):
        """Access recorded messages of users / channels"""

    @defmessagesgroup.command(name="user")
    async def defmessagesgroupuser(self, ctx: commands.Context, user: UserCacheConverter):
        """Shows recent messages of a user"""
        author = ctx.author

        pages = await self.make_message_log(user, guild=author.guild, requester=author, pagify_log=True,
                                            replace_backtick=True)

        if not pages:
            return await ctx.send("No messages recorded for that user.")

        self.send_to_monitor(ctx.guild, f"{author} ({author.id}) accessed message history "
                                        f"of user {user} ({user.id})")

        if len(pages) == 1:
            await ctx.send(box(pages[0], lang="md"))
        else:
            pages = [box(p, lang="md") for p in pages]
            await menu(ctx, pages, DEFAULT_CONTROLS)

    @defmessagesgroup.command(name="channel")
    async def defmessagesgroupuserchannel(self, ctx: commands.Context, channel: Union[discord.TextChannel, discord.Thread]):
        """Shows recent messages of a channel"""
        author = ctx.author
        if not channel.permissions_for(author).read_messages:
            self.send_to_monitor(ctx.guild, f"{author} ({author.id}) attempted to access the message "
                                            f"history of channel #{channel.name}")
            return await ctx.send("You do not have read permissions in that channel. Request denied.")

        pages = await self.make_message_log(channel, guild=author.guild, requester=author, pagify_log=True,
                                            replace_backtick=True)

        if not pages:
            return await ctx.send("No messages recorded in that channel.")

        self.send_to_monitor(ctx.guild, f"{author} ({author.id}) accessed the message history "
                                        f"of channel #{channel.name}")

        if len(pages) == 1:
            await ctx.send(box(pages[0], lang="md"))
        else:
            pages = [box(p, lang="md") for p in pages]
            await menu(ctx, pages, DEFAULT_CONTROLS)

    @defmessagesgroup.command(name="exportuser")
    async def defmessagesgroupexportuser(self, ctx: commands.Context, user: UserCacheConverter):
        """Exports recent messages of a user to a file"""
        author = ctx.author

        _log = await self.make_message_log(user, guild=author.guild, requester=author)

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

        _log = await self.make_message_log(channel, guild=author.guild, requester=author)

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

        async with ctx.typing():
            async for m in AsyncIter(ctx.guild.members, steps=2):
                if m.bot:
                    continue
                if m.joined_at is None:
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
            if m.joined_at is not None and m.joined_at > x_hours_ago:
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
                await self.send_notification(guild, alert_msg, title="Emergency mode",
                                             ping=True, jump_to=ctx.message)
                self.dispatch_event("emergency", guild)
            else:
                await ctx.send("Emergency mode is already ongoing.")
        else:
            if emergency_mode:
                del self.emergency_mode[guild.id]
                await self.send_notification(guild, "⚠️ Emergency mode manually disabled.",
                                             title="Emergency mode", jump_to=ctx.message)
            else:
                await ctx.send("Emergency mode is already off.")

    @defender.command(name="updates")
    async def defendererupdates(self, ctx: commands.Context):
        """Shows all the past announcements of Defender"""
        announcements = get_announcements_embed(only_recent=False)
        if announcements:
            announcements = list(announcements.values())
            await menu(ctx, announcements, DEFAULT_CONTROLS)
        else:
            await ctx.send("Nothing to show.")

    @defender.command(name="debuginfo", hidden=True)
    @commands.is_owner()
    async def defenderdebuginfo(self, ctx: commands.Context):
        """Debug info about Defender and its dependencies"""
        guild = ctx.guild
        admin_roles = await ctx.bot._config.guild(ctx.guild).admin_role()
        mod_roles = await ctx.bot._config.guild(ctx.guild).mod_role()
        conf = self.config.guild(ctx.guild)
        notif_channel_set = bool(await conf.notify_channel())
        notify_role_set = bool(await conf.notify_role())
        punish_role_set = bool(await conf.punish_role())
        py_ver = sys.version_info
        try:
            pydantic_version = pydantic.__version__
        except AttributeError:
            pydantic_version = pydantic.version.VERSION

        async def wd_checks_present(module_key):
            return "Active" if await WardenAPI.get_check(guild, module_key) else "None"

        await ctx.send(box(cleandoc(
            f"""
             Defender {self.__version__}
            -- Deps --
             python {py_ver.major}.{py_ver.minor}.{py_ver.micro}
             emoji {emoji.__version__}
             pydantic {pydantic_version}
             pyyaml {yaml.__version__}
             regex {regex.__version__}
             rapidfuzz {rapidfuzz.__version__}
            -- General settings --
             Notif channel set: {notif_channel_set}
             Notif role set: {notify_role_set}
             Punish role set: {punish_role_set}
             Roles: {len(admin_roles)} admin / {len(mod_roles)} mod
            -- Enabled modules --
             Defender: {await conf.enabled()}
             IF: {await conf.invite_filter_enabled()} (WD checks: {await wd_checks_present(ChecksKeys.InviteFilter)})
             RD: {await conf.raider_detection_enabled()} (WD checks: {await wd_checks_present(ChecksKeys.RaiderDetection)})
             JM: {await conf.join_monitor_enabled()} (WD checks: {await wd_checks_present(ChecksKeys.JoinMonitor)})
             WD: {await conf.warden_enabled()}
             CA: {await conf.ca_enabled()} (WD checks: {await wd_checks_present(ChecksKeys.CommentAnalysis)})
             Alert: {await conf.alert_enabled()}
             Vaporize: {await conf.vaporize_enabled()}
             Silence: {await conf.silence_enabled()}
             Voteout: {await conf.voteout_enabled()}"""
            ), lang="py"))

    @defender.group(name="warden", aliases=["wd"])
    @commands.admin()
    async def wardengroup(self, ctx: commands.Context):
        """Warden rules management

        See [p]defender status for more information about Warden"""
        if await self.callout_if_fake_admin(ctx):
            ctx.invoked_subcommand = None

    @wardengroup.command(name="add")
    async def wardengroupaddrule(self, ctx: commands.Context, *, rule: str):
        """Adds a new rule"""
        guild = ctx.guild
        # Since some people immediately dive into Warden before configuring everything up...
        n_channel = await self.config.guild(guild).notify_channel()
        if n_channel == 0:
            await ctx.send("It is important that you configure and understand how Defender works before "
                           f"using Warden. Please read `{ctx.prefix}def status` in its entirety.")
            return

        rule = strip_yaml_codeblock(rule)
        prompts_sent = False

        try:
            new_rule = WardenRule()
            await new_rule.parse(rule, cog=self, author=ctx.author)
        except InvalidRule as e:
            return await ctx.send(f"Error parsing the rule: {e}")
        except Exception as e:
            log.error("Warden - unexpected error during rule parsing", exc_info=e)
            return await ctx.send(f"Something very wrong happened during the rule parsing. Please check its format.")

        if WardenEvent.Periodic in new_rule.events:
            prompts_sent = True
            if not await rule_add_periodic_prompt(cog=self, message=ctx.message, new_rule=new_rule):
                return

        if new_rule.name in self.active_warden_rules[guild.id] or new_rule.name in self.invalid_warden_rules[guild.id]:
            prompts_sent = True
            if not await rule_add_overwrite_prompt(cog=self, message=ctx.message):
                return

        async with self.config.guild(ctx.guild).wd_rules() as warden_rules:
            warden_rules[new_rule.name] = rule
        self.active_warden_rules[ctx.guild.id][new_rule.name] = new_rule
        self.invalid_warden_rules[ctx.guild.id].pop(new_rule.name, None)

        if not prompts_sent:
            await ctx.tick()
        else:
            await ctx.send("The rule has been added.")

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
        events_without_rules = []

        for k, v in rules.items():
            if not v and k != "invalid":
                events_without_rules.append(k.replace("-", " "))
                continue
            if k == "invalid":
                continue
            event_name = k.replace("-", " ").capitalize()
            rule_names = ", ".join(v)
            text += f"**{event_name}**:\n{rule_names}\n"

        if events_without_rules:
            text += "\nThese events have no rules: "
            text += ", ".join(events_without_rules)

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


        raw_rule = rule.raw_rule
        no_box = "```" in raw_rule

        if no_box:
            raw_rule = escape(raw_rule, formatting=True)

        for p in pagify(raw_rule, page_length=1950, escape_mass_mentions=False):
            if no_box:
                await ctx.send(p)
            else:
                await ctx.send(box(p, lang="yaml"))

    @commands.cooldown(1, 3600*24, commands.BucketType.guild) # only one session per guild
    @wardengroup.command(name="upload")
    async def wardengroupupload(self, ctx: commands.Context):
        """Starts a rule upload session"""
        max_size = await self.config.wd_upload_max_size()
        confirm_emoji = "✅"
        guild = ctx.guild
        await ctx.send("Please start sending your rules. Files must be in .yaml or .txt format. "
                       "Type `quit` to stop this process.")

        def is_valid_attachment(m):
            if ctx.bot.get_cog("Defender") is not self:
                raise asyncio.TimeoutError() # The cog has been reloaded
            elif m.author.id != ctx.author.id or m.channel.id != ctx.channel.id:
                return False
            elif m.content.lower() in ("quit", "`quit`"):
                raise asyncio.TimeoutError()
            elif not m.attachments:
                return False

            attachment = m.attachments[0]
            if not attachment.filename.endswith((".txt", ".TXT", ".yaml", ".YAML")):
                self.loop.create_task(ctx.send("Invalid file type."))
                return False
            if attachment.height is not None:
                return False

            if attachment.size < 1 or attachment.size > (max_size*1024):
                self.loop.create_task(ctx.send(f"The file is too big. The maximum size is {max_size}KB."))
                return False

            return True

        while True:
            try:
                message = await ctx.bot.wait_for("message", check=is_valid_attachment, timeout=120)
            except asyncio.TimeoutError:
                ctx.command.reset_cooldown(ctx)
                return await ctx.send(f"Please reissue `{ctx.prefix}def warden upload` if you want to upload more rules")
            except Exception as e:
                ctx.command.reset_cooldown(ctx)
                return log.error("Error during Warden rules upload", exc_info=e)

            raw_rule = BytesIO()

            try:
                await message.attachments[0].save(raw_rule)
                raw_rule = raw_rule.read().decode(encoding="utf-8", errors="strict")
            except UnicodeError:
                await ctx.send("Error while parsing your file: is it utf-8 encoded? Please try again.")
                continue
            except (discord.HTTPException, discord.NotFound) as e:
                await ctx.send("Error while retrieving your rule. Please try again.")
                continue
            except Exception as e:
                log.error("Unexpected error in Warden rule upload.", exc_info=e)
                ctx.command.reset_cooldown(ctx)
                return await ctx.send("Unexpected error while retrieving or parsing your file.")

            try:
                new_rule = WardenRule()
                await new_rule.parse(raw_rule, cog=self, author=ctx.author)
            except InvalidRule as e:
                await ctx.send(f"Error parsing the rule: {e}")
                continue
            except Exception as e:
                log.error("Warden - unexpected error during rule parsing", exc_info=e)
                await ctx.send(f"Something very wrong happened during the rule parsing. Please check its format.")
                continue
            else:
                prompts_sent = False
                if WardenEvent.Periodic in new_rule.events:
                    prompts_sent = True
                    if not await rule_add_periodic_prompt(cog=self, message=message, new_rule=new_rule):
                        continue

                if new_rule.name in self.active_warden_rules[guild.id] or new_rule.name in self.invalid_warden_rules[guild.id]:
                    prompts_sent = True
                    if not await rule_add_overwrite_prompt(cog=self, message=message):
                        continue

                async with self.config.guild(ctx.guild).wd_rules() as warden_rules:
                    warden_rules[new_rule.name] = raw_rule
                self.active_warden_rules[ctx.guild.id][new_rule.name] = new_rule
                self.invalid_warden_rules[ctx.guild.id].pop(new_rule.name, None)
                if not prompts_sent:
                    await message.add_reaction(confirm_emoji)
                else:
                    await ctx.send("The rule has been added.")

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
        """Sends all the rules as a tar.gz archive"""
        to_archive = {}

        for k, v in self.active_warden_rules[ctx.guild.id].items():
            to_archive[k] = BytesIO(v.raw_rule.encode("utf8"))

        for k, v in self.invalid_warden_rules[ctx.guild.id].items():
            to_archive[k] = BytesIO(v.raw_rule.encode("utf8"))

        if not to_archive:
            return await ctx.send("There are no rules to export")

        tar_obj = BytesIO()

        with tarfile.open(fileobj=tar_obj, mode='w:gz') as tar:
            for k, v in to_archive.items():
                info = tarfile.TarInfo(f"{k}.yaml")
                info.size = len(v.getvalue())
                tar.addfile(info, v)

        utc = utcnow()
        tar_obj.seek(0)
        await ctx.send(file=discord.File(tar_obj, f"rules-export-{utc}.tar.gz"))

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
            async for m in AsyncIter(ctx.guild.members, steps=2):
                if m.bot:
                    continue
                if m.joined_at is None:
                    continue
                rank = await self.rank_user(m)
                if await rule.satisfies_conditions(rank=rank, user=m, cog=self, guild=m.guild):
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
            async for m in AsyncIter(targets, steps=2):
                try:
                    await rule.do_actions(user=m, guild=m.guild, cog=self)
                except Exception as e:
                    errors += 1
                    self.send_to_monitor(ctx.guild, f"[Warden] ({rule.name}): {e}")

        text = f"Rule `{name}` has been executed on **{len(targets)} users**."
        if errors:
            text += (f"\n**{errors}** of them triggered an error on this rule. For more details check "
                     f"`{ctx.prefix}def monitor`.")

        await ctx.send(text)

    @wardengroup.command(name="memory")
    async def wardengroupmemory(self, ctx: commands.Context, *, keywords: str=""):
        """Shows or resets the memory of Warden

        Can be filtered. Supports wildcards (* and ?)"""
        def is_relevant(value, keywords):
            if not keywords:
                return True
            if "*" not in keywords and "?" not in keywords:
                keywords = f"*{keywords}*"
            keywords = keywords.lower()
            if fnmatch.fnmatch(str(value).lower(), keywords):
                return True
            return False

        prod_state = heat.get_state(ctx.guild)
        dev_state = heat.get_state(ctx.guild, debug=True)
        text = ""

        def show_state(state, state_name):
            text = ""
            first_run = True
            for _type in ("custom", "users", "channels"):
                to_add = []
                for k, v in sorted(state[_type].items()):
                    if is_relevant(k, keywords):
                        to_add.append(f"{k}: {len(v)}")
                if to_add:
                    if first_run:
                        text += f"- **{state_name}**:"
                        first_run = False
                    if text: text += "\n"
                    text += f"`{_type.title()} heat levels`\n"
                    text += ", ".join(to_add)
            return text

        text = (show_state(prod_state, "Production heat store") + "\n\n" +
                show_state(dev_state, "Sandbox heat store"))

        if text == "\n\n":
            return await ctx.send("There is currently nothing stored in Warden's memory.")

        text += "\nIf you want to empty Warden's memory, say `free` in the next 10 seconds."

        for p in pagify(text):
            await ctx.send(p)

        def say_free(m):
            return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() == "free"

        try:
            message = await ctx.bot.wait_for("message", check=say_free, timeout=10)
        except asyncio.TimeoutError:
            pass
        else:
            heat.empty_state(ctx.guild)
            heat.empty_state(ctx.guild, debug=True)
            await message.add_reaction("✅")


    @wardengroup.command(name="debug", usage="<id> <event> [rank]")
    async def wardengroupdebug(self, ctx: commands.Context, _id: int, event: WardenEvent, rank: int=None):
        """Simulate and give a detailed summary of an event

        A Warden event must be passed with the proper target ID (user or local message)

        When this command is issued all the rules registered to the event will be
        processed in a safe way against the target, if any.
        If the target satisfies the conditions, *only* the heatpoint related actions
        will be carried on.
        The heatpoint actions will be "sandboxed", so the newly added heatpoints won't
        have any effect outside this test.
        Remember that Warden evaluates each condition in order and stops at the first failed
        root condition: the last condition that is listed in a failed rule is where Warden
        stopped evaluating them.
        If a valid Rank is also passed it will be used in place of the target's real
        rank during the test.
        See the documentation for a full list of Warden events.

        Example:
        [p]def warden debug <valid_user_id> on-user-join
        [p]def warden debug <valid_message_id> on-message
        [p]def warden debug <valid_message_id> on-message-edit 3"""
        if rank is not None:
            try:
                rank = Rank(rank)
            except ValueError:
                await ctx.send("You must provide a valid rank (1-4) or leave it empty "
                               "to test against the target's real rank.")
                return

        rules = self.get_warden_rules_by_event(ctx.guild, event)
        if not rules:
            return await ctx.send("There are no rules associated with that event.")

        results = []
        message = None
        guild = ctx.guild

        if event in (WardenEvent.OnMessage, WardenEvent.OnMessageEdit, WardenEvent.OnMessageDelete):
            try:
                message = await ctx.channel.fetch_message(_id)
            except discord.NotFound:
                return await ctx.send("I could not retrieve the message. Is it in this channel?")
            except:
                return await ctx.send("I failed to retrieve the message.")
            user = message.author
            rank = rank or await self.rank_user(user)
        elif event in (WardenEvent.OnUserJoin, WardenEvent.OnUserLeave, WardenEvent.Manual, WardenEvent.Periodic):
            user = ctx.guild.get_member(_id)
            if user is None:
                return await ctx.send("I could not retrieve the user.")
            rank = rank or await self.rank_user(user)
        else:
            rank = Rank.Rank1 # On a user-less event (for now, only on-emergency) rank is not considered
            user = None


        for rule in rules:
            result = await rule.satisfies_conditions(cog=self, guild=guild, rank=rank, user=user,
                                                     message=message, debug=True)
            results.append(result)
            if result:
                await rule.do_actions(cog=self, guild=guild, user=user, message=message, debug=True)

        text = ""
        for i, result in enumerate(results):
            i += 1
            text += f"**{i}. {result.rule_name}** "
            if result.last_result is True:
                text += "(Passed)\n"
            elif not result.trace:
                text += "(Failed rank check)\n"
            else:
                text += "(Failed)\n"
                trace = "\n".join(result.trace)
                text += f"{box(trace)}"
        text += "\nIf you want to empty Warden's sandbox memory, say `free` in the next 10 seconds."

        for p in pagify(text):
            await ctx.send(p)

        def say_free(m):
            return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() == "free"

        try:
            message = await ctx.bot.wait_for("message", check=say_free, timeout=10)
        except asyncio.TimeoutError:
            pass
        else:
            heat.empty_state(ctx.guild, debug=True)
            await message.add_reaction("✅")

    @wardengroup.command(name="find", aliases=["search"])
    async def wardengroupfind(self, ctx: commands.Context, *, text: str):
        """Search for text in existing rules"""
        text = text.lower()
        all_rules = self.active_warden_rules[ctx.guild.id].copy()
        all_rules.update(self.invalid_warden_rules[ctx.guild.id].copy())
        results = []
        if not all_rules:
            return await ctx.send("No Warden rules have been added yet.")

        for name, rule in all_rules.items():
            if text in rule.raw_rule.lower():
                results.append(name)

        if not results:
            return await ctx.send("Your search yielded no results.")

        results.sort()
        results = [inline(r) for r in results]
        text = "Your search term was found in the following rules:\n" + ", ".join(results)

        for p in pagify(text, delims=[",", " "]):
            await ctx.send(p)
