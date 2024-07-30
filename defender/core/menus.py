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

from discord import ui
from discord import SelectOption
from typing import List, Tuple, Union
from ..enums import QAInteractions
from .utils import utcnow
from collections.abc import Iterable
import discord
import logging

log = logging.getLogger("red.x26cogs.defender")

class SettingSetSelect(ui.Select):
    def __init__(self, config_value, current_settings: Union[int, str, List[Union[str, int]]], select_options: Tuple[SelectOption, ...], max_values=None, cast_to=None, **kwargs):
        self.cast_to = cast_to
        self.config_value = config_value
        iterable = isinstance(current_settings, Iterable)
        if max_values is None:
            max_values = len(select_options)
        if not iterable:
            current_settings = [str(current_settings)]
        else:
            current_settings = [str(s) for s in current_settings]
        super().__init__(max_values=max_values, **kwargs)
        for s in select_options:
            default = s.value if s.value is not None else s.label
            self.add_option(
                value=str(s.value) if s.value is not None else discord.utils.MISSING,
                label=s.label,
                description=s.description,
                emoji=s.emoji,
                default=True if default in current_settings else False,
            )

    async def callback(self, inter: discord.Interaction):
        values = self.values
        if self.cast_to:
            values = [self.cast_to(v) for v in values]
        if self.max_values == 1:
            log.debug(f"Setting {values[0]}, type {type(values[0])}")
            await self.config_value.set(values[0])
        else:
            log.debug(f"Setting {values}")
            await self.config_value.set(values)

        await inter.response.defer()

class RestrictedView(ui.View):
    def __init__(self, cog, issuer_id, timeout=180, **kwargs):
        super().__init__(timeout=timeout, **kwargs)
        self.cog = cog
        self.issuer_id = issuer_id

    async def interaction_check(self, inter: discord.Interaction):
        if inter.user.id != self.issuer_id:
            await inter.response.send_message("Only the issuer of the command can change these options.", ephemeral=True)
            return False
        return True

class QASelect(discord.ui.Select):
    def __init__(self, target_id: int):
        super().__init__(custom_id=str(target_id), placeholder="Quick action")
        self.options = [
            SelectOption(value=QAInteractions.Ban.value, label="Ban", emoji="🔨"),
            SelectOption(value=QAInteractions.Kick.value, label="Kick", emoji="👢"),
            SelectOption(value=QAInteractions.Softban.value, label="Softban", emoji="💨"),
            SelectOption(value=QAInteractions.Punish.value, label="Punish", emoji="👊"),
            SelectOption(value=QAInteractions.BanAndDelete24.value, label="Ban + 24h deletion", emoji="🔂"),
        ]

    async def callback(self, inter: discord.Interaction):
        guild: discord.Guild = inter.guild
        user: discord.Member = inter.user
        view: QAView = self.view
        cog = view.cog
        bot = view.bot
        reason = view.reason
        action = QAInteractions(self.values[0])

        target = guild.get_member(int(self.custom_id))
        if target is None:
            await inter.response.send_message("I have tried to take action but the user seems to be gone.", ephemeral=True)
            return
        elif target.top_role >= user.top_role:
            cog.send_to_monitor(guild, f"[QuickAction] Prevented user {user} from taking action on {target}: "
                                        "hierarchy check failed.")
            await inter.response.send_message("Denied. Your top role must be higher than the target's to take action on them.", ephemeral=True)
            return

        #if action in (QAInteractions.Ban, QAInteractions.Softban, QAInteractions.Kick): # Expel = no more actions
        #    self.quick_actions[guild.id].pop(payload.message_id, None)

        if await bot.is_mod(target):
            cog.send_to_monitor(guild, f"[QuickAction] Target user {target} is a staff member. I cannot do that.")
            await inter.response.send_message("Denied. You're trying to take action on a staff member.", ephemeral=True)
            return

        check1 = user.guild_permissions.ban_members is False and action in (QAInteractions.Ban, QAInteractions.Softban, QAInteractions.BanAndDelete24)
        check2 = user.guild_permissions.kick_members is False and action == QAInteractions.Kick

        if any((check1, check2)):
            cog.send_to_monitor(guild, f"[QuickAction] Mod {user} lacks permissions to {action.value}.")
            await inter.response.send_message("Denied. You lack appropriate permissions for this action.", ephemeral=True)
            return

        auditlog_reason = f"Defender QuickAction issued by {user} ({user.id})"

        if action == QAInteractions.Ban:
            await guild.ban(target, reason=auditlog_reason, delete_message_days=0)
            cog.dispatch_event("member_remove", target, action.value, reason)
        elif action == QAInteractions.Softban:
            await guild.ban(target, reason=auditlog_reason, delete_message_days=1)
            await guild.unban(target)
            cog.dispatch_event("member_remove", target, action.value, reason)
        elif action == QAInteractions.Kick:
            await guild.kick(target, reason=auditlog_reason)
            cog.dispatch_event("member_remove", target, action.value, reason)
        elif action == QAInteractions.Punish:
            punish_role = guild.get_role(await cog.config.guild(guild).punish_role())
            if punish_role and not cog.is_role_privileged(punish_role):
                await target.add_roles(punish_role, reason=auditlog_reason)
            else:
                cog.send_to_monitor(guild, "[QuickAction] Failed to punish user. Is the punish role "
                                           "still present and with *no* privileges?")
            await inter.response.defer()
            return
        elif action == QAInteractions.BanAndDelete24:
            await guild.ban(target, reason=auditlog_reason, delete_message_days=1)
            cog.dispatch_event("member_remove", target, action.value, reason)

        if action == QAInteractions.BanAndDelete24:
            action = QAInteractions.Ban

        await inter.response.defer()

        await cog.create_modlog_case(
            bot,
            guild,
            utcnow(),
            action.value,
            target,
            user,
            reason if reason else None,
            until=None,
            channel=None,
        )

class QAView(discord.ui.View):
    def __init__(self, cog, target_id: int, reason: str):
        self.cog = cog
        self.bot = cog.bot
        self.reason = reason
        super().__init__(timeout=0)
        self.add_item(QASelect(target_id))

    async def interaction_check(self, inter: discord.Interaction):
        if not await self.bot.is_mod(inter.user):
            await inter.response.send_message("Only staff members are allowed to take action. You sure don't look like one.", ephemeral=True)
            return False
        return True


class StopAlertButton(discord.ui.Button):
    async def callback(self, inter: discord.Interaction):
        self.view.stop()
        await self.view.cog.refresh_staff_activity(inter.guild)
        self.disabled = True
        await inter.response.edit_message(view=self.view)

class EmergencyView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=0)
        self.cog = cog
        self.add_item(StopAlertButton(style=discord.ButtonStyle.danger, emoji="⚠️", label="Stop timer"))

    async def interaction_check(self, inter: discord.Interaction):
        if not await self.cog.bot.is_mod(inter.user):
            await inter.response.send_message("Only staff members are allowed to press this button. You sure don't look like one.", ephemeral=True)
            return False
        return True