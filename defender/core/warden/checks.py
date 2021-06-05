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

from .enums import Action, Condition
from ...exceptions import InvalidRule
from ...enums import Rank
from redbot.core.commands.converter import parse_timedelta
from discord.ext.commands import BadArgument
import datetime
import discord


async def _check_role_hierarchy(*, cog, author: discord.Member, action: Action, parameter: list):
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

async def _check_slowmode(*, cog, author: discord.Member, action: Action, parameter: str):
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

async def _check_is_valid_channel(*, cog, author: discord.Member, action: Action, parameter: list):
    guild = author.guild

    _id_or_name = parameter[0]
    channel_dest = guild.get_channel(_id_or_name)
    if not channel_dest:
        channel_dest = discord.utils.get(guild.text_channels, name=_id_or_name)
    if not channel_dest:
        raise InvalidRule(f"`{action.value}` Channel '{_id_or_name}' not found.")

async def _check_heatpoint(*, cog, author: discord.Member, action: Action, parameter: str):
    td = None
    try:
        td = parse_timedelta(parameter,
                             maximum=datetime.timedelta(hours=24),
                             minimum=datetime.timedelta(seconds=1),
                             allowed_units=["hours", "minutes", "seconds"])
    except BadArgument:
        pass

    if td is None:
        raise InvalidRule(f"`{action.value}` Invalid parameter. Must be between 1 second and 24 hours. "
                           "You must specify `seconds`, `minutes` or `hours`")

async def _check_heatpoints(*, cog, author: discord.Member, action: Action, parameter: list):
    if parameter[0] < 1 or parameter[0] > 100:
        raise InvalidRule(f"`{action.value}` Invalid parameter. You can only assign between 1 and 100 "
                           "heatpoints.")
    td = None
    try:
        td = parse_timedelta(parameter[1],
                             maximum=datetime.timedelta(hours=24),
                             minimum=datetime.timedelta(seconds=1),
                             allowed_units=["hours", "minutes", "seconds"])
    except BadArgument:
        pass

    if td is None:
        raise InvalidRule(f"`{action.value}` Invalid parameter. Must be between 1 second and 24 hours. "
                           "You must specify `seconds`, `minutes` or `hours`")

async def _check_custom_heatpoint(*, cog, author: discord.Member, action: Action, parameter: list):
    if not isinstance(parameter[0], str):
        raise InvalidRule(f"`{action.value}` Invalid parameter. The custom heat key must be a string.")

    td = None
    try:
        td = parse_timedelta(parameter[1],
                             maximum=datetime.timedelta(hours=24),
                             minimum=datetime.timedelta(seconds=1),
                             allowed_units=["hours", "minutes", "seconds"])
    except BadArgument:
        pass

    if td is None:
        raise InvalidRule(f"`{action.value}` Invalid parameter. Must be between 1 second and 24 hours. "
                           "You must specify `seconds`, `minutes` or `hours`")

    if parameter[0].startswith("core-"):
        raise InvalidRule(f"`{action.value}` Invalid parameter. Your custom heatpoint's name cannot "
                           "start with 'core-': this is reserved for internal use.")

async def _check_custom_heatpoints(*, cog, author: discord.Member, action: Action, parameter: list):
    if not isinstance(parameter[0], str):
        raise InvalidRule(f"`{action.value}` Invalid parameter. The custom heat key must be a string.")

    if parameter[1] < 1 or parameter[1] > 100:
        raise InvalidRule(f"`{action.value}` Invalid parameter. You can only assign between 1 and 100 "
                           "heatpoints.")
    td = None
    try:
        td = parse_timedelta(parameter[2],
                             maximum=datetime.timedelta(hours=24),
                             minimum=datetime.timedelta(seconds=1),
                             allowed_units=["hours", "minutes", "seconds"])
    except BadArgument:
        pass

    if td is None:
        raise InvalidRule(f"`{action.value}` Invalid parameter. Must be between 1 second and 24 hours. "
                           "You must specify `seconds`, `minutes` or `hours`")

    if parameter[0].startswith("core-"):
        raise InvalidRule(f"`{action.value}` Invalid parameter. Your custom heatpoint's name cannot "
                           "start with 'core-': this is reserved for internal use.")

async def _check_issue_command(*, cog, author: discord.Member, action: Action, parameter: list):
    if parameter[0] != author.id:
        raise InvalidRule(f"`{action.value}` The first parameter must be your ID. For security reasons "
                          "you're not allowed to issue commands as other users.")

async def _check_message_delete_after(*, cog, author: discord.Member, action: Action, parameter: str):
    td = None
    try:
        td = parse_timedelta(parameter,
                             maximum=datetime.timedelta(minutes=1),
                             minimum=datetime.timedelta(seconds=1),
                             allowed_units=["minutes", "seconds"])
    except BadArgument:
        pass

    if td is None:
        raise InvalidRule(f"`{action.value}` Invalid parameter. Must be between 1 second and 1 minute. "
                           "You must specify `seconds` or `minutes`")

async def _check_valid_rank(*, cog, author: discord.Member, condition: Condition, parameter: int):
    try:
        rank = Rank(parameter)
        if rank < Rank.Rank1 or rank > Rank.Rank4:
            raise ValueError()
    except ValueError:
        raise InvalidRule(f"`{condition.value}` Invalid rank. Rank level must be between 1 and 4.")

async def _check_valid_id(*, cog, author: discord.Member, condition: Condition, parameter: list):
    for _id in parameter:
        if type(_id) is not int:
            raise InvalidRule(f"`{condition.value}` Invalid ID. Must contain only valid Discord IDs.")

async def _check_regex_enabled(*, cog, author: discord.Member, condition: Condition, parameter: str):
    enabled: bool = await cog.config.wd_regex_allowed()
    if not enabled:
        raise InvalidRule(f"`{condition.value}` Regex use is globally disabled. The bot owner must use "
                           "`[p]dset warden regexallowed` to activate it.")

async def _check_cond_custom_heat(*, cog, author: discord.Member, condition: Condition, parameter: list):
    if not isinstance(parameter[0], str):
        raise InvalidRule(f"`{condition.value}` Invalid parameter. The custom heat key must be a string.")

    if not isinstance(parameter[1], int):
        raise InvalidRule(f"`{condition.value}` Invalid parameter. The second element must be a number "
                          "representing the heat level.")


# A callable with author, action and parameter kwargs
ACTIONS_SANITY_CHECK = {
    Action.AddRolesToUser: _check_role_hierarchy,
    Action.RemoveRolesFromUser: _check_role_hierarchy,
    Action.SetChannelSlowmode: _check_slowmode,
    Action.SendToChannel: _check_is_valid_channel,
    Action.AddUserHeatpoint: _check_heatpoint,
    Action.AddChannelHeatpoint: _check_heatpoint,
    Action.AddCustomHeatpoint: _check_custom_heatpoint,
    Action.AddUserHeatpoints: _check_heatpoints,
    Action.AddChannelHeatpoints: _check_heatpoints,
    Action.AddCustomHeatpoints: _check_custom_heatpoints,
    Action.IssueCommand: _check_issue_command,
    Action.DeleteLastMessageSentAfter: _check_message_delete_after,
}

CONDITIONS_SANITY_CHECK = {
    Condition.UserIdMatchesAny: _check_valid_id,
    Condition.UserIsRank: _check_valid_rank,
    Condition.MessageMatchesRegex: _check_regex_enabled,
    Condition.UsernameMatchesRegex: _check_regex_enabled,
    Condition.NicknameMatchesRegex: _check_regex_enabled,
    Condition.CustomHeatIs: _check_cond_custom_heat,
    Condition.CustomHeatMoreThan: _check_cond_custom_heat,
}