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

from ..enums import Action
import discord
import re

ACTIONS_VERBS = {
    Action.Ban: "banned",
    Action.Softban: "softbanned",
    Action.Kick: "kicked",
    Action.Punish: "punished",
    Action.NoAction: "",
}

async def is_own_invite(guild: discord.Guild, match: re.Match):
    if not guild.me.guild_permissions.manage_guild:
        return False

    has_vanity_url = "VANITY_URL" in guild.features

    if has_vanity_url:
        invite_url = await guild.vanity_invite()
        if invite_url.code.lower() == match.group(2).lower():
            return True

    for invite in await guild.invites():
        if invite.code == match.group(2):
            return True

    return False