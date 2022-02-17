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

from typing import Tuple, List
from ..enums import Action, QAInteractions
from ..exceptions import MisconfigurationError
import datetime
import discord

ACTIONS_VERBS = {
    Action.Ban: "banned",
    Action.Softban: "softbanned",
    Action.Kick: "kicked",
    Action.Punish: "punished",
    Action.NoAction: "",
}

async def get_external_invite(guild: discord.Guild, invites: List[Tuple]):
    if not guild.me.guild_permissions.manage_guild:
        raise MisconfigurationError("I need 'manage guild' permissions to fetch this server's invites.")

    has_vanity_url = "VANITY_URL" in guild.features
    vanity_url = await guild.vanity_invite() if has_vanity_url else ""
    if vanity_url:
        vanity_url = vanity_url.code

    own_invites = []
    for invite in await guild.invites():
        own_invites.append(invite.code)

    for invite in invites:
        if invite[1] == vanity_url:
            continue
        for own_invite in own_invites:
            if invite[1] == own_invite:
                break
        else:
            return invite[1]

    return None

def utcnow():
    if discord.version_info.major >= 2:
        return datetime.datetime.now(datetime.timezone.utc)
    else:
        return datetime.datetime.utcnow()

def timestamp(datetime: datetime.datetime, relative=False):
    if relative:
        return f"<t:{int(datetime.timestamp())}:R>"
    else:
        return f"<t:{int(datetime.timestamp())}>"

class QAView(discord.ui.View):
    custom_id: str

    def __init__(self, *args, **kwargs):
        self.cog = kwargs.pop("cog")
        self.bot = self.cog.bot
        self.reason = kwargs.pop("reason")
        super().__init__(**kwargs)

    async def interaction_check(self, inter: discord.Interaction):
        if not await self.bot.is_mod(inter.user):
            await inter.response.send_message("Only staff members are allowed to take action. You sure don't look like one.", ephemeral=True)
            return False
        return True

class QASelect(discord.ui.Select):
    async def callback(self, inter: discord.Interaction):
        guild: discord.Guild = inter.guild
        user: discord.Member = inter.user
        view: QAView = self.view
        cog = view.cog
        bot = view.bot
        reason = view.reason
        action = QAInteractions(self.values[0])

        target = guild.get_member(int(self.custom_id))
        if target is None: # TODO?
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
            return
        elif action == QAInteractions.BanAndDelete24:
            await guild.ban(target, reason=auditlog_reason, delete_message_days=1)
            cog.dispatch_event("member_remove", target, action.value, reason)

        if action == QAInteractions.BanAndDelete24:
            action = QAInteractions.Ban

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