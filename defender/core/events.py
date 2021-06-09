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
from ..enums import Rank
from ..core.warden.enums import Event as WardenEvent
from ..core.warden.rule import WardenRule
from ..exceptions import ExecutionError
from . import cache as df_cache
from redbot.core import commands
import discord
import logging
import asyncio

log = logging.getLogger("red.x26cogs.defender")

class Events(MixinMeta, metaclass=CompositeMetaClass): # type: ignore
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        author = message.author
        if not hasattr(author, "guild") or not author.guild:
            return
        guild = author.guild
        if await self.bot.cog_disabled_in_guild(self, guild): # type: ignore
            return
        if author.bot:
            return

        if not await self.config.guild(guild).enabled():
            return

        if message.nonce == "262626":
            # This is a mock command from Warden and we don't want to process it
            return

        if await self.config.guild(guild).count_messages():
            await self.inc_message_count(author)

        df_cache.add_message(message)
        df_cache.maybe_store_msg_obj(message)

        is_staff = False
        expelled = False
        wd_expelled = False
        rank = await self.rank_user(author)

        if rank == Rank.Rank1:
            if await self.bot.is_mod(author): # Is staff?
                is_staff = True
                await self.refresh_staff_activity(guild)

        rule: WardenRule
        if await self.config.guild(guild).warden_enabled():
            rules = self.get_warden_rules_by_event(guild, WardenEvent.OnMessage)
            for rule in rules:
                if await rule.satisfies_conditions(cog=self, rank=rank, message=message):
                    try:
                        wd_expelled = await rule.do_actions(cog=self, message=message)
                        if wd_expelled:
                            expelled = True
                            await asyncio.sleep(0.1)
                    except (discord.Forbidden, discord.HTTPException, ExecutionError) as e:
                        self.send_to_monitor(guild, f"[Warden] Rule {rule.name} "
                                                    f"({rule.last_action.value}) - {str(e)}")
                    except Exception as e:
                        self.send_to_monitor(guild, f"[Warden] Rule {rule.name} "
                                                    f"({rule.last_action.value}) - {str(e)}")
                        log.error("Warden - unexpected error during actions execution", exc_info=e)

        if expelled:
            return

        inv_filter_enabled = await self.config.guild(guild).invite_filter_enabled()
        if inv_filter_enabled and not is_staff:
            inv_filter_rank = await self.config.guild(guild).invite_filter_rank()
            if rank >= inv_filter_rank:
                try:
                    expelled = await self.invite_filter(message)
                except discord.Forbidden as e:
                    self.send_to_monitor(guild, "[InviteFilter] Failed to take action on "
                                                f"user {author.id}. Please check my permissions.")
                except Exception as e:
                    log.warning("Unexpected error in InviteFilter", exc_info=e)
        if expelled:
            return

        rd_enabled = await self.config.guild(guild).raider_detection_enabled()
        if rd_enabled and not is_staff:
            rd_rank = await self.config.guild(guild).raider_detection_rank()
            if rank >= rd_rank:
                try:
                    expelled = await self.detect_raider(message)
                except discord.Forbidden as e:
                    self.send_to_monitor(guild, "[RaiderDetection] Failed to take action on "
                                                f"user {author.id}. Please check my permissions.")
                except Exception as e:
                    log.warning("Unexpected error in RaiderDetection", exc_info=e)
        if expelled:
            return

        silence_enabled = await self.config.guild(guild).silence_enabled()

        if silence_enabled and not is_staff:
            rank_silenced = await self.config.guild(guild).silence_rank()
            if rank_silenced and rank >= rank_silenced:
                try:
                    await message.delete()
                except:
                    pass

        ca_enabled = await self.config.guild(guild).ca_enabled()

        if ca_enabled and not is_staff:
            rank_ca = await self.config.guild(guild).ca_rank()
            if rank_ca and rank >= rank_ca:
                try:
                    await self.comment_analysis(message)
                except discord.Forbidden as e:
                    self.send_to_monitor(guild, "[CommentAnalysis] Failed to take action on "
                                                f"user {author.id}. Please check my permissions.")
                except Exception as e:
                    log.error("Unexpected error in CommentAnalysis", exc_info=e)

    @commands.Cog.listener()
    async def on_message_edit(self, message_before: discord.Message, message: discord.Message):
        author = message.author
        if not hasattr(author, "guild") or not author.guild:
            return
        guild = author.guild
        if await self.bot.cog_disabled_in_guild(self, guild): # type: ignore
            return
        if author.bot:
            return
        if message_before.content == message.content:
            return

        if not await self.config.guild(guild).enabled():
            return

        self.loop.create_task(df_cache.add_message_edit(message))

        is_staff = False
        expelled = False
        wd_expelled = False
        rank = await self.rank_user(author)

        if rank == Rank.Rank1:
            if await self.bot.is_mod(author): # Is staff?
                is_staff = True
                await self.refresh_staff_activity(guild)

        rule: WardenRule
        if await self.config.guild(guild).warden_enabled():
            rules = self.get_warden_rules_by_event(guild, WardenEvent.OnMessageEdit)
            for rule in rules:
                if await rule.satisfies_conditions(cog=self, rank=rank, message=message):
                    try:
                        wd_expelled = await rule.do_actions(cog=self, message=message)
                        if wd_expelled:
                            expelled = True
                            await asyncio.sleep(0.1)
                    except (discord.Forbidden, discord.HTTPException, ExecutionError) as e:
                        self.send_to_monitor(guild, f"[Warden] Rule {rule.name} "
                                                    f"({rule.last_action.value}) - {str(e)}")
                    except Exception as e:
                        self.send_to_monitor(guild, f"[Warden] Rule {rule.name} "
                                                    f"({rule.last_action.value}) - {str(e)}")
                        log.error("Warden - unexpected error during actions execution", exc_info=e)

        if expelled:
            return

        inv_filter_enabled = await self.config.guild(guild).invite_filter_enabled()
        if inv_filter_enabled and not is_staff:
            inv_filter_rank = await self.config.guild(guild).invite_filter_rank()
            if rank >= inv_filter_rank:
                try:
                    expelled = await self.invite_filter(message)
                except discord.Forbidden as e:
                    self.send_to_monitor(guild, "[InviteFilter] Failed to take action on "
                                                f"user {author.id}. Please check my permissions.")
                except Exception as e:
                    log.warning("Unexpected error in InviteFilter", exc_info=e)

        ca_enabled = await self.config.guild(guild).ca_enabled()
        if ca_enabled and not is_staff:
            rank_ca = await self.config.guild(guild).ca_rank()
            if rank_ca and rank >= rank_ca:
                try:
                    await self.comment_analysis(message)
                except discord.Forbidden as e:
                    self.send_to_monitor(guild, "[CommentAnalysis] Failed to take action on "
                                                f"user {author.id}. Please check my permissions.")
                except Exception as e:
                    log.error("Unexpected error in CommentAnalysis", exc_info=e)


    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        author = message.author
        if not hasattr(author, "guild") or not author.guild:
            return
        guild = author.guild
        if await self.bot.cog_disabled_in_guild(self, guild): # type: ignore
            return
        if author.bot:
            return

        if not await self.config.guild(guild).enabled():
            return

        rank = await self.rank_user(author)

        rule: WardenRule
        if await self.config.guild(guild).warden_enabled():
            rules = self.get_warden_rules_by_event(guild, WardenEvent.OnMessageDelete)
            for rule in rules:
                if await rule.satisfies_conditions(cog=self, rank=rank, message=message):
                    try:
                        await rule.do_actions(cog=self, message=message)
                    except (discord.Forbidden, discord.HTTPException, ExecutionError) as e:
                        self.send_to_monitor(guild, f"[Warden] Rule {rule.name} "
                                                    f"({rule.last_action.value}) - {str(e)}")
                    except Exception as e:
                        self.send_to_monitor(guild, f"[Warden] Rule {rule.name} "
                                                    f"({rule.last_action.value}) - {str(e)}")
                        log.error("Warden - unexpected error during actions execution", exc_info=e)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        guild = member.guild
        if await self.bot.cog_disabled_in_guild(self, guild): # type: ignore
            return
        if not await self.config.guild(guild).enabled():
            return

        if await self.config.guild(guild).warden_enabled():
            rule: WardenRule
            rules = self.get_warden_rules_by_event(guild, WardenEvent.OnUserJoin)
            for rule in rules:
                rank = await self.rank_user(member)
                if await rule.satisfies_conditions(cog=self, rank=rank, user=member):
                    try:
                        await rule.do_actions(cog=self, user=member)
                    except (discord.Forbidden, discord.HTTPException, ExecutionError) as e:
                        self.send_to_monitor(guild, f"[Warden] Rule {rule.name} "
                                                    f"({rule.last_action.value}) - {str(e)}")
                    except Exception as e:
                        self.send_to_monitor(guild, f"[Warden] Rule {rule.name} "
                                                    f"({rule.last_action.value}) - {str(e)}")
                        log.error("Warden - unexpected error during actions execution", exc_info=e)

        if await self.config.guild(guild).join_monitor_enabled():
            await self.join_monitor_flood(member)
            await self.join_monitor_suspicious(member)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return

        guild = member.guild
        if await self.bot.cog_disabled_in_guild(self, guild): # type: ignore
            return
        if not await self.config.guild(guild).enabled():
            return

        if await self.config.guild(guild).warden_enabled():
            rule: WardenRule
            rules = self.get_warden_rules_by_event(guild, WardenEvent.OnUserLeave)
            for rule in rules:
                rank = await self.rank_user(member)
                if await rule.satisfies_conditions(cog=self, rank=rank, user=member):
                    try:
                        await rule.do_actions(cog=self, user=member)
                    except (discord.Forbidden, discord.HTTPException, ExecutionError) as e:
                        self.send_to_monitor(guild, f"[Warden] Rule {rule.name} "
                                                    f"({rule.last_action.value}) - {str(e)}")
                    except Exception as e:
                        self.send_to_monitor(guild, f"[Warden] Rule {rule.name} "
                                                    f"({rule.last_action.value}) - {str(e)}")
                        log.error("Warden - unexpected error during actions execution", exc_info=e)

    @commands.Cog.listener()
    async def on_reaction_add(self, _, user: discord.Member):
        if not hasattr(user, "guild") or not user.guild or user.bot:
            return
        if await self.bot.cog_disabled_in_guild(self, user.guild): # type: ignore
            return
        if await self.bot.is_mod(user): # Is staff?
            await self.refresh_staff_activity(user.guild)

    @commands.Cog.listener()
    async def on_reaction_remove(self, _, user: discord.Member):
        if not hasattr(user, "guild") or not user.guild or user.bot:
            return
        if await self.bot.cog_disabled_in_guild(self, user.guild): # type: ignore
            return
        if await self.bot.is_mod(user): # Is staff?
            await self.refresh_staff_activity(user.guild)

    @commands.Cog.listener()
    async def on_x26_defender_emergency(self, guild: discord.Guild):
        rule: WardenRule
        if await self.bot.cog_disabled_in_guild(self, guild): # type: ignore
            return
        if not await self.config.guild(guild).warden_enabled():
            return

        rules = self.get_warden_rules_by_event(guild, WardenEvent.OnEmergency)
        for rule in rules:
            if await rule.satisfies_conditions(cog=self, rank=rule.rank, guild=guild):
                try:
                    await rule.do_actions(cog=self, guild=guild)
                except (discord.Forbidden, discord.HTTPException, ExecutionError) as e:
                    self.send_to_monitor(guild, f"[Warden] Rule {rule.name} "
                                                f"({rule.last_action.value}) - {str(e)}")
                except Exception as e:
                    self.send_to_monitor(guild, f"[Warden] Rule {rule.name} "
                                                f"({rule.last_action.value}) - {str(e)}")
                    log.error("Warden - unexpected error during actions execution", exc_info=e)
