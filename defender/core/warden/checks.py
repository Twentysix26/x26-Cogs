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

from .enums import Action
from ...exceptions import InvalidRule
from redbot.core.commands.converter import parse_timedelta
from discord.ext.commands import BadArgument
import datetime
import discord


def _check_role_hierarchy(*, author: discord.Member, action: Action, parameter: list):
    guild = author.guild
    roles = []

    is_server_owner = author.id == guild.owner_id

    for role_id_or_name in parameter:
        role = guild.get_role(role_id_or_name)
        if role is None:
            role = discord.utils.get(guild.roles, name=role_id_or_name)
        if role is None:
            raise InvalidRule(f"`{action.value}`: Role `{role_id_or_name}` doesn't seem to exist.")
        roles.append(role)

    if not is_server_owner:
        for r in roles:
            if r.position >= author.top_role.position:
                raise InvalidRule(f"`{action.value}` Cannot assign or remove role `{r.name}` through Warden. "
                                "You are autorized to only add or remove roles below your top role.")

def _check_slowmode(*, author: discord.Member, action: Action, parameter: str):
    if not author.guild_permissions.manage_channels:
        raise InvalidRule(f"`{action.value}` You need `manage channels` permissions to make a rule with "
                           "this action.")

    td = None
    try:
        td = parse_timedelta(parameter,
                             maximum=datetime.timedelta(hours=6),
                             minimum=datetime.timedelta(seconds=0),
                             allowed_units=["hours", "minutes", "seconds"])
    except BadArgument:
        pass

    if td is None:
        raise InvalidRule(f"`{action.value}` Invalid parameter. Must be between 1 second and 6 hours. "
                           "You must specify `seconds`, `minutes` or `hours`. Can be `0 seconds` to "
                           "deactivate slowmode.")

def _check_is_valid_channel(*, author: discord.Member, action: Action, parameter: list):
    guild = author.guild

    _id_or_name = parameter[0]
    channel_dest = guild.get_channel(_id_or_name)
    if not channel_dest:
        channel_dest = discord.utils.get(guild.channels, name=_id_or_name)
    if not channel_dest:
        raise InvalidRule(f"`{action.value}` Channel '{_id_or_name}' not found.")

# A callable with author, action and parameter kwargs
ACTIONS_SANITY_CHECK = {
    Action.AddRolesToUser: _check_role_hierarchy,
    Action.RemoveRolesFromUser: _check_role_hierarchy,
    Action.SetChannelSlowmode: _check_slowmode,
    Action.SendToChannel: _check_is_valid_channel,
}