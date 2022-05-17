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
from ..enums import Action, QAAction
from ..exceptions import MisconfigurationError
from collections import namedtuple
import datetime
import discord

ACTIONS_VERBS = {
    Action.Ban: "banned",
    Action.Softban: "softbanned",
    Action.Kick: "kicked",
    Action.Punish: "punished",
    Action.NoAction: "",
}

QUICK_ACTION_EMOJIS = {
    "👢": Action.Kick,
    "🔨": Action.Ban,
    "💨": Action.Softban,
    "👊": Action.Punish,
    "👊🏻": Action.Punish,
    "👊🏼": Action.Punish,
    "👊🏾": Action.Punish,
    "👊🏿": Action.Punish,
    "🔂": QAAction.BanDeleteOneDay,
}

QuickAction = namedtuple("QuickAction", ("target", "reason"))

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

def timestamp(ts: datetime.datetime, relative=False):
    # Discord assumes UTC timestamps
    timestamp = int(ts.replace(tzinfo=datetime.timezone.utc).timestamp())

    if relative:
        return f"<t:{timestamp}:R>"
    else:
        return f"<t:{timestamp}>"
