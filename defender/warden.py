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

import yaml
import enum
import fnmatch
import discord
import datetime
import logging
import re
from .enums import Rank, Action, EmergencyMode, WardenEvent
from .exceptions import InvalidRule
from redbot.core.utils.common_filters import INVITE_URL_RE
from string import Template
from redbot.core import modlog

log = logging.getLogger("red.x26cogs.defender")

utcnow = datetime.datetime.utcnow

RULE_KEYS = ("name", "event", "rank", "if", "do")

MEDIA_URL_RE = re.compile(r"""(http)?s?:?(\/\/[^"']*\.(?:png|jpg|jpeg|gif|png|svg|mp4|gifv))""", re.I)

class WardenAction(enum.Enum):
    Dm = "dm" #DM an arbitrary user. Must provide name/id + content
    DmUser = "dm-user" # DMs user in context
    NotifyStaff = "notify-staff"
    NotifyStaffAndPing = "notify-staff-and-ping"
    BanAndDelete = "ban-and-delete" # Ban user in context and delete X days
    Kick = Action.Kick.value # Kick user in context
    Softban = Action.Softban.value # Softban user in context
    Modlog = "send-mod-log" # Send modlog case of last expel action + reason
    DeleteUserMessage = "delete-user-message" # Delete message in context
    SendInChannel = "send-in-channel" # Send message to channel in context
    AddRolesToUser = "add-roles-to-user" # Adds roles to user in context
    RemoveRolesFromUser = "remove-roles-from-user" # Remove roles from user in context
    TriggerEmergencyMode = "trigger-emergency-mode"
    SetUserNickname = "set-user-nickname" # Changes nickname of user in context
    # TODO Heat system / Warnings?

class WardenCondition(enum.Enum):
    UsernameMatchesAny = "username-matches-any"
    NicknameMatchesAny = "nickname-matches-any"
    MessageMatchesAny = "message-matches-any"
    UserCreatedLessThan = "user-created-less-than"
    UserJoinedLessThan = "user-joined-less-than"
    UserHasDefaultAvatar = "user-has-default-avatar"
    ChannelMatchesAny = "channel-matches-any"
    MessageHasAttachment = "message-has-attachment"
    InEmergencyMode = "in-emergency-mode"
    UserHasAnyRoleIn = "user-has-any-role-in"
    MessageContainsInvite = "message-contains-invite"
    MessageContainsMedia = "message-contains-media"

# Below are the accepted types of each condition for basic sanity checking
# before a rule is accepted and entered into the system
WARDEN_CONDITIONS_PARAM_TYPE = {
    WardenCondition.UsernameMatchesAny: [list],
    WardenCondition.NicknameMatchesAny: [list],
    WardenCondition.MessageMatchesAny: [list],
    WardenCondition.UserCreatedLessThan: [int],
    WardenCondition.UserJoinedLessThan: [int],
    WardenCondition.UserHasDefaultAvatar: [bool],
    WardenCondition.ChannelMatchesAny: [list],
    WardenCondition.InEmergencyMode: [bool],
    WardenCondition.MessageHasAttachment: [bool],
    WardenCondition.UserHasAnyRoleIn: [list],
    WardenCondition.MessageContainsInvite: [bool],
    WardenCondition.MessageContainsMedia: [bool],
}

WARDEN_ACTIONS_PARAM_TYPE = {
    WardenAction.Dm: [list],
    WardenAction.DmUser: [str],
    WardenAction.NotifyStaff: [str],
    WardenAction.NotifyStaffAndPing: [str],
    WardenAction.BanAndDelete: [int],
    WardenAction.Softban: [None],
    WardenAction.Kick: [None],
    WardenAction.Modlog: [str],
    WardenAction.DeleteUserMessage: [None],
    WardenAction.SendInChannel: [str],
    WardenAction.AddRolesToUser: [list],
    WardenAction.RemoveRolesFromUser: [list],
    WardenAction.TriggerEmergencyMode: [None],
    WardenAction.SetUserNickname: [str]
}

# Not every condition is available to all events
# It's better to catch these during parsing to avoid giving
# the user the illusion that they will have any effect on the rule
DENIED_CONDITIONS = {
    WardenEvent.OnMessage: [],
    WardenEvent.OnUserJoin: [WardenCondition.MessageMatchesAny, WardenCondition.MessageHasAttachment, WardenCondition.MessageContainsInvite,
                             WardenCondition.MessageContainsMedia],
    WardenEvent.OnEmergency: [c for c in WardenCondition if c != WardenCondition.InEmergencyMode] # Basically all of them. There's no context
}
DENIED_CONDITIONS[WardenEvent.Manual] = DENIED_CONDITIONS[WardenEvent.OnUserJoin]

DENIED_ACTIONS = {
    WardenEvent.OnMessage: [],
    WardenEvent.OnUserJoin: [WardenAction.SendInChannel, WardenAction.DeleteUserMessage],
    WardenEvent.OnEmergency: [c for c in WardenAction if c != WardenAction.NotifyStaff and c!= WardenAction.NotifyStaffAndPing]
}
DENIED_ACTIONS[WardenEvent.Manual] = DENIED_ACTIONS[WardenEvent.OnUserJoin]

# These are for special commands such as DM, which require
# a mandatory # of "arguments"
ACTIONS_ARGS_N = {
    WardenAction.Dm: 2,
}

class WardenRule:
    def __init__(self, rule_str, do_not_raise_during_parse=False):
        self.parse_exception = None
        self.last_error = ""
        self.name = None
        self.event = None
        self.rank = None
        self.conditions = []
        self.actions = {}
        self.raw_rule = rule_str
        try:
            self.parse(rule_str)
        except Exception as e:
            if not do_not_raise_during_parse:
                raise e
            self.parse_exception = e

    def parse(self, rule_str):
        try:
            rule = yaml.safe_load(rule_str)
        except:
            raise InvalidRule("Error parsing YAML. Please make sure the format "
                              "is valid (a YAML validator may help)")

        if not isinstance(rule, dict):
            raise InvalidRule(f"This rule doesn't seem to follow the expected format.")

        if rule["name"] is None:
            raise InvalidRule("Rule has no 'name' parameter.")

        self.name = rule["name"].lower().replace(" ", "-")

        for key in rule.keys():
            if key not in RULE_KEYS:
                raise InvalidRule(f"Unexpected key at root level: '{key}'.")

        for key in RULE_KEYS:
            if key not in rule.keys():
                raise InvalidRule(f"Missing key at root level: '{key}'.")

        try:
            event = WardenEvent(rule["event"])
        except ValueError:
            raise InvalidRule("Invalid event.")

        self.event = WardenEvent(rule["event"])

        try:
            Rank(rule["rank"])
        except:
            raise InvalidRule("Invalid target rank. Must be 1-4.")

        self.rank = rule["rank"]

        if "if" in rule: # TODO Conditions probably shouldn't be mandatory.
            if not isinstance(rule["if"], dict):
                raise InvalidRule("Invalid 'if' category. Must be a map of conditions.")
        else:
            raise InvalidRule("Rule must have at least one condition.")

        self.conditions = rule["if"]

        if not rule["if"]:
            raise InvalidRule("Rule must have at least one condition.")

        if not isinstance(rule["do"], list):
            raise InvalidRule("Invalid 'do' category. Must be a list of maps.")

        if not rule["do"]:
            raise InvalidRule("Rule must have at least one action.")

        self.actions = rule["do"]

        denied = DENIED_CONDITIONS[self.event]

        for condition, parameter in self.conditions.items():
            try:
                condition = WardenCondition(condition)
            except ValueError:
                raise InvalidRule(f"Invalid condition: `{condition}`")

            if condition in denied:
                raise InvalidRule(f"Condition `{condition.value}` not allowed in `{self.event.value}`")

            for _type in WARDEN_CONDITIONS_PARAM_TYPE[condition]:
                if _type is None and parameter is None:
                    break
                elif _type is None:
                    continue
                if isinstance(parameter, _type):
                    break
            else:
                raise InvalidRule(f"Invalid parameter type for condition `{condition.value}`")

        denied = DENIED_ACTIONS[self.event]

        # Basically a list of one-key dicts
        # We need to preserve order of actions
        for entry in self.actions:
            # This will be a single loop
            if not isinstance(entry, dict):
                raise InvalidRule(f"Invalid action: `{entry}`. Expected map (mind the colon!).")
            for action, parameter in entry.items():
                try:
                    action = WardenAction(action)
                except ValueError:
                    raise InvalidRule(f"Invalid action: `{action}`")

                if action in denied:
                    raise InvalidRule(f"Action `{action.value}` not allowed in `{self.event.value}`")

                for _type in WARDEN_ACTIONS_PARAM_TYPE[action]:
                    if _type is None and parameter is None:
                        break
                    elif _type is None:
                        continue
                    if _type == list and isinstance(parameter, list):
                        mandatory_arg_number = ACTIONS_ARGS_N.get(action, None)
                        if mandatory_arg_number is None:
                            break
                        p_number = len(parameter)
                        if p_number != mandatory_arg_number:
                            raise InvalidRule(f"Action `{action.value}` requires {mandatory_arg_number} "
                                              f"arguments, got {p_number}.")
                        else:
                            break
                    elif isinstance(parameter, _type):
                        break
                else:
                    raise InvalidRule(f"Invalid parameter type for action `{action.value}`")


    async def satisfies_conditions(self, *, rank: Rank, cog, user: discord.Member=None, message: discord.Message=None):
        if rank < self.rank:
            return False

        # Due to the strict checking done during parsing we can
        # expect to always have available the variables that we need for
        # the different type of events and conditions
        # Unless I fucked up somewhere, then we're in trouble!
        if message and not user:
            user = message.author
        guild: discord.Guild = user.guild
        channel: discord.Channel = message.channel if message else None

        for condition, value in self.conditions.items():
            condition = WardenCondition(condition)
            if condition == WardenCondition.MessageMatchesAny:
                # One match = Passed
                content = message.content.lower()
                for pattern in value:
                    if fnmatch.fnmatch(content, pattern.lower()):
                        break
                else:
                    return False
            elif condition == WardenCondition.UsernameMatchesAny:
                # One match = Passed
                name = user.name.lower()
                for pattern in value:
                    if fnmatch.fnmatch(name, pattern.lower()):
                        break
                else:
                    return False
            elif condition == WardenCondition.NicknameMatchesAny:
                # One match = Passed
                if not user.nick:
                    return False
                nick = user.nick.lower()
                for pattern in value:
                    if fnmatch.fnmatch(nick, pattern.lower()):
                        break
                else:
                    return False
            elif condition == WardenCondition.ChannelMatchesAny: # We accept IDs and channel names
                if channel.id in value:
                    continue
                for channel_str in value:
                    if not isinstance(channel_str, str):
                        continue
                    channel_obj = discord.utils.get(guild.channels, name=channel_str)
                    if channel_obj is not None and channel_obj == channel:
                        break
                else:
                    return False
            elif condition == WardenCondition.UserCreatedLessThan:
                if value == 0:
                    continue
                x_hours_ago = utcnow() - datetime.timedelta(hours=value)
                if user.created_at < x_hours_ago:
                    return False
            elif condition == WardenCondition.UserJoinedLessThan:
                if value == 0:
                    continue
                x_hours_ago = utcnow() - datetime.timedelta(hours=value)
                if user.joined_at < x_hours_ago:
                    return False
            elif condition == WardenCondition.UserHasDefaultAvatar:
                default_avatar_url_pattern = "*/embed/avatars/*.png"
                if fnmatch.fnmatch(str(user.avatar_url), default_avatar_url_pattern) != value:
                    return False
            elif condition == WardenCondition.InEmergencyMode:
                in_emergency = cog.is_in_emergency_mode(guild)
                if in_emergency != value:
                    return False
            elif condition == WardenCondition.MessageHasAttachment:
                if bool(message.attachments) != value:
                    return False
            elif condition == WardenCondition.UserHasAnyRoleIn:
                for role_id_or_name in value:
                    role = guild.get_role(role_id_or_name)
                    if role is None:
                        role = discord.utils.get(guild.roles, name=role_id_or_name)
                    if role:
                        if role in user.roles:
                            break
                else:
                    return False
            elif condition == WardenCondition.MessageContainsInvite:
                has_invite = INVITE_URL_RE.search(message.content)
                if bool(has_invite) != value:
                    return False
            elif condition == WardenCondition.MessageContainsMedia:
                has_media = MEDIA_URL_RE.search(message.content)
                if bool(has_media) != value:
                    return False

        return True

    async def do_actions(self, *, cog, user: discord.Member=None, message: discord.Message=None):
        if message and not user:
            user = message.author
        guild: discord.Guild = user.guild
        channel: discord.Channel = message.channel if message else None

        templates_vars = {
            "action_name": self.name,
            "user": str(user),
            "user_name": user.name,
            "user_id": user.id,
            "user_mention": user.mention,
            "user_nickname": str(user.nick),
            "user_created_at": user.created_at,
            "user_joined_at": user.joined_at,
            "guild": str(guild),
            "guild_id": guild.id
        }

        if message:
            templates_vars["message"] = message.content
            templates_vars["message_id"] = message.id
            templates_vars["message_created_at"] = message.created_at
            if message.attachments:
                attachment = message.attachments[0]
                templates_vars["attachment_filename"] = attachment.filename
                templates_vars["attachment_url"] = attachment.url

        if channel:
            templates_vars["channel"] = str(channel)
            templates_vars["channel_id"] = channel.id
            templates_vars["channel_mention"] = channel.mention

        last_expel_action = None

        for entry in self.actions:
            for action, value in entry.items():
                action = WardenAction(action)
                if action == WardenAction.DmUser:
                    text = Template(value).safe_substitute(templates_vars)
                    await user.send(text)
                elif action == WardenAction.DeleteUserMessage:
                    await message.delete()
                elif action == WardenAction.NotifyStaff:
                    text = Template(value).safe_substitute(templates_vars)
                    await cog.send_notification(guild, text)
                elif action == WardenAction.NotifyStaffAndPing:
                    text = Template(value).safe_substitute(templates_vars)
                    await cog.send_notification(guild, text, ping=True)
                elif action == WardenAction.SendInChannel:
                    text = Template(value).safe_substitute(templates_vars)
                    await channel.send(text)
                elif action == WardenAction.Dm:
                    _id_or_name, content = (value[0], value[1])
                    user_to_dm = guild.get_member(_id_or_name)
                    if not user_to_dm:
                        user_to_dm = discord.utils.get(guild.members, name=_id_or_name)
                    if not user_to_dm:
                        continue
                    content = Template(content).safe_substitute(templates_vars)
                    try:
                        await user_to_dm.send(content)
                    except: # Should we care if the DM fails?
                        pass
                elif action == WardenAction.AddRolesToUser:
                    to_assign = []
                    for role_id_or_name in value:
                        role = guild.get_role(role_id_or_name)
                        if role is None:
                            role = discord.utils.get(guild.roles, name=role_id_or_name)
                        if role:
                            to_assign.append(role)
                    to_assign = list(set(to_assign))
                    to_assign = [r for r in to_assign if r not in user.roles]
                    if to_assign:
                        await user.add_roles(*to_assign, reason=f"Assigned by Warden action '{self.name}'")
                elif action == WardenAction.RemoveRolesFromUser:
                    to_unassign = []
                    for role_id_or_name in value:
                        role = guild.get_role(role_id_or_name)
                        if role is None:
                            role = discord.utils.get(guild.roles, name=role_id_or_name)
                        if role:
                            to_unassign.append(role)
                    to_unassign = list(set(to_unassign))
                    to_unassign = [r for r in to_unassign if r in user.roles]
                    if to_unassign:
                        await user.remove_roles(*to_unassign, reason=f"Unassigned by Warden action '{self.name}'")
                elif action == WardenAction.SetUserNickname:
                    if value == "":
                        value = None
                    else:
                        value = Template(value).safe_substitute(templates_vars)
                    await user.edit(nick=value, reason=f"Changed nickname by Warden action '{self.name}'")
                elif action == WardenAction.BanAndDelete:
                    last_expel_action = Action.Ban
                    await guild.ban(user, delete_message_days=value, reason=f"Banned by Warden action '{self.name}'")
                elif action == WardenAction.Kick:
                    last_expel_action = Action.Kick
                    await guild.kick(user, reason=f"Kicked by Warden action '{self.name}'")
                elif action == WardenAction.Softban:
                    last_expel_action = Action.Softban
                    await guild.ban(user, delete_message_days=1, reason=f"Softbanned by Warden action '{self.name}'")
                    await guild.unban(user)
                elif action == WardenAction.Modlog:
                    if last_expel_action is None:
                        continue
                    reason = Template(value).safe_substitute(templates_vars)
                    await modlog.create_case(
                        cog.bot,
                        guild,
                        utcnow(),
                        last_expel_action.value,
                        user,
                        guild.me,
                        reason,
                        until=None,
                        channel=None,
                    )
                elif action == WardenAction.TriggerEmergencyMode:
                    cog.emergency_mode[guild.id] = EmergencyMode(manual=True)
