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
import fnmatch
import discord
import datetime
import logging
import re
from .enums import Rank, Action, EmergencyMode
from .enums import WardenAction, WardenCondition, WardenEvent, WardenConditionBlock
from .exceptions import InvalidRule
from redbot.core.utils.common_filters import INVITE_URL_RE
from string import Template
from redbot.core import modlog

log = logging.getLogger("red.x26cogs.defender")

utcnow = datetime.datetime.utcnow

RULE_KEYS = ("name", "event", "rank", "if", "do")

MEDIA_URL_RE = re.compile(r"""(http)?s?:?(\/\/[^"']*\.(?:png|jpg|jpeg|gif|png|svg|mp4|gifv))""", re.I)

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
    WardenCondition.IsStaff: [bool]
}

WARDEN_ACTIONS_PARAM_TYPE = {
    WardenAction.Dm: [list],
    WardenAction.DmUser: [str],
    WardenAction.NotifyStaff: [str],
    WardenAction.NotifyStaffAndPing: [str],
    WardenAction.NotifyStaffWithEmbed: [list],
    WardenAction.BanAndDelete: [int],
    WardenAction.Softban: [None],
    WardenAction.Kick: [None],
    WardenAction.Modlog: [str],
    WardenAction.DeleteUserMessage: [None],
    WardenAction.SendInChannel: [str],
    WardenAction.AddRolesToUser: [list],
    WardenAction.RemoveRolesFromUser: [list],
    WardenAction.EnableEmergencyMode: [bool],
    WardenAction.SetUserNickname: [str],
    WardenAction.NoOp: [None],
    WardenAction.SendToMonitor: [str]
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
    WardenEvent.OnEmergency: [c for c in WardenAction if c != WardenAction.NotifyStaff and c!= WardenAction.NotifyStaffAndPing and
                                                         c != WardenAction.NotifyStaffWithEmbed and
                                                         c != WardenAction.Dm and c != WardenAction.EnableEmergencyMode]
}
DENIED_ACTIONS[WardenEvent.Manual] = DENIED_ACTIONS[WardenEvent.OnUserJoin]

# These are for special commands such as DM, which require
# a mandatory # of "arguments"
ACTIONS_ARGS_N = {
    WardenAction.Dm: 2,
    WardenAction.NotifyStaffWithEmbed: 2
}

class WardenRule:
    def __init__(self, rule_str, do_not_raise_during_parse=False):
        self.parse_exception = None
        self.last_action = WardenAction.NoOp
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
            self.event = WardenEvent(rule["event"])
        except ValueError:
            raise InvalidRule("Invalid event.")

        try:
            self.rank = Rank(rule["rank"])
        except:
            raise InvalidRule("Invalid target rank. Must be 1-4.")

        if "if" in rule: # TODO Conditions probably shouldn't be mandatory.
            if not isinstance(rule["if"], list):
                raise InvalidRule("Invalid 'if' category. Must be a list of conditions.")
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

        def validate_condition(cond):
            condition = parameter = None
            for r, p in cond.items():
                condition, parameter = r, p

            try:
                condition = WardenCondition(condition)
            except ValueError:
                try:
                    condition = WardenConditionBlock(condition)
                    raise InvalidRule(f"Invalid: `{condition.value}` can only be at root level.")
                except ValueError:
                    raise InvalidRule(f"Invalid condition: `{condition}`")

            if condition in denied:
                raise InvalidRule(f"Condition `{condition.value}` not allowed in `{self.event.value}`")

            _type = None
            for _type in WARDEN_CONDITIONS_PARAM_TYPE[condition]:
                if _type is None and parameter is None:
                    break
                elif _type is None:
                    continue
                if isinstance(parameter, _type):
                    break
            else:
                human_type = _type.__name__ if _type is not None else "No parameter."
                raise InvalidRule(f"Invalid parameter type for condition `{condition.value}`. Expected: `{human_type}`")

        for raw_condition in self.conditions:
            condition = parameter = None

            if not isinstance(raw_condition, dict):
                raise InvalidRule(f"Invalid condition: `{raw_condition}`. Expected map.")

            for r, p in raw_condition.items():
                condition, parameter = r, p

            if len(raw_condition) != 1:
                raise InvalidRule(f"Invalid format in the conditions. Make sure you've got the dashes right!")

            try:
                condition = WardenCondition(condition)
            except ValueError:
                try:
                    condition = WardenConditionBlock(condition)
                except ValueError:
                    raise InvalidRule(f"Invalid condition: `{condition}`")

            if isinstance(condition, WardenConditionBlock):
                if parameter is None:
                    raise InvalidRule("Condition blocks cannot be empty.")
                for p in parameter:
                    validate_condition(p)
            else:
                validate_condition(raw_condition)

        denied = DENIED_ACTIONS[self.event]

        # Basically a list of one-key dicts
        # We need to preserve order of actions
        for entry in self.actions:
            # This will be a single loop
            if not isinstance(entry, dict):
                raise InvalidRule(f"Invalid action: `{entry}`. Expected map.")

            if len(entry) != 1:
                raise InvalidRule(f"Invalid format in the actions. Make sure you've got the dashes right!")

            _type = None
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
                    human_type = _type.__name__ if _type is not None else "No parameter."
                    raise InvalidRule(f"Invalid parameter type for action `{action.value}`. Expected: `{human_type}`")


    async def satisfies_conditions(self, *, rank: Rank, cog, user: discord.Member=None, message: discord.Message=None,
                                   guild: discord.Guild=None):
        if rank < self.rank:
            return False

        # Due to the strict checking done during parsing we can
        # expect to always have available the variables that we need for
        # the different type of events and conditions
        # Unless I fucked up somewhere, then we're in trouble!
        if message and not user:
            user = message.author

        # For the condition block to pass, every "root level" condition (or block of conditions)
        # must equal to True
        bools = []

        for raw_condition in self.conditions:
            condition = value = None

            for r, v in raw_condition.items():
                condition, value = r, v
            try:
                condition = WardenConditionBlock(condition)
            except:
                condition = WardenCondition(condition)

            if condition == WardenConditionBlock.IfAll:
                results = await self._evaluate_conditions(value, cog=cog, user=user, message=message, guild=guild)
                if len(results) != len(value):
                    raise RuntimeError("Mismatching number of conditions and evaluations")
                bools.append(all(results))
            elif condition == WardenConditionBlock.IfAny:
                results = await self._evaluate_conditions(value, cog=cog, user=user, message=message, guild=guild)
                if len(results) != len(value):
                    raise RuntimeError("Mismatching number of conditions and evaluations")
                bools.append(any(results))
            elif condition == WardenConditionBlock.IfNot:
                results = await self._evaluate_conditions(value, cog=cog, user=user, message=message, guild=guild)
                if len(results) != len(value):
                    raise RuntimeError("Mismatching number of conditions and evaluations")
                results = [not r for r in results] # Bools are flipped
                bools.append(all(results))
            else:
                results = await self._evaluate_conditions([{condition: value}], cog=cog, user=user, message=message, guild=guild)
                if len(results) != 1:
                    raise RuntimeError(f"A single condition evaluation returned {len(results)} evaluations!")
                bools.append(results[0])

        return all(bools)

    async def _evaluate_conditions(self, conditions, *, cog, user: discord.Member=None, message: discord.Message=None,
                                   guild: discord.Guild=None):
        bools = []

        if message and not user:
            user = message.author
        guild = guild if guild else user.guild
        channel: discord.Channel = message.channel if message else None

        for raw_condition in conditions:

            condition = value = None
            for c, v in raw_condition.items():
                condition, value = c, v

            condition = WardenCondition(condition)
            if condition == WardenCondition.MessageMatchesAny:
                # One match = Passed
                content = message.content.lower()
                for pattern in value:
                    if fnmatch.fnmatch(content, pattern.lower()):
                        bools.append(True)
                        break
                else:
                    bools.append(False)
            elif condition == WardenCondition.UsernameMatchesAny:
                # One match = Passed
                name = user.name.lower()
                for pattern in value:
                    if fnmatch.fnmatch(name, pattern.lower()):
                        bools.append(True)
                        break
                else:
                    bools.append(False)
            elif condition == WardenCondition.NicknameMatchesAny:
                # One match = Passed
                if not user.nick:
                    bools.append(False)
                    continue
                nick = user.nick.lower()
                for pattern in value:
                    if fnmatch.fnmatch(nick, pattern.lower()):
                        bools.append(True)
                        break
                else:
                    bools.append(False)
            elif condition == WardenCondition.ChannelMatchesAny: # We accept IDs and channel names
                if channel.id in value:
                    bools.append(True)
                    continue
                for channel_str in value:
                    if not isinstance(channel_str, str):
                        continue
                    channel_obj = discord.utils.get(guild.channels, name=channel_str)
                    if channel_obj is not None and channel_obj == channel:
                        bools.append(True)
                        break
                else:
                    bools.append(False)
            elif condition == WardenCondition.UserCreatedLessThan:
                if value == 0:
                    bools.append(True)
                    continue
                x_hours_ago = utcnow() - datetime.timedelta(hours=value)
                bools.append(user.created_at > x_hours_ago)
            elif condition == WardenCondition.UserJoinedLessThan:
                if value == 0:
                    bools.append(True)
                    continue
                x_hours_ago = utcnow() - datetime.timedelta(hours=value)
                bools.append(user.joined_at > x_hours_ago)
            elif condition == WardenCondition.UserHasDefaultAvatar:
                default_avatar_url_pattern = "*/embed/avatars/*.png"
                match = fnmatch.fnmatch(str(user.avatar_url), default_avatar_url_pattern)
                bools.append(value is match)
            elif condition == WardenCondition.InEmergencyMode:
                in_emergency = cog.is_in_emergency_mode(guild)
                bools.append(in_emergency is value)
            elif condition == WardenCondition.MessageHasAttachment:
                bools.append(bool(message.attachments) is value)
            elif condition == WardenCondition.UserHasAnyRoleIn:
                for role_id_or_name in value:
                    role = guild.get_role(role_id_or_name)
                    if role is None:
                        role = discord.utils.get(guild.roles, name=role_id_or_name)
                    if role:
                        if role in user.roles:
                            bools.append(True)
                            break
                else:
                    bools.append(False)
            elif condition == WardenCondition.MessageContainsInvite:
                has_invite = INVITE_URL_RE.search(message.content)
                bools.append(bool(has_invite) is value)
            elif condition == WardenCondition.MessageContainsMedia:
                has_media = MEDIA_URL_RE.search(message.content)
                bools.append(bool(has_media) is value)
            elif condition == WardenCondition.IsStaff:
                is_staff = await cog.bot.is_mod(user)
                bools.append(is_staff is value)

        return bools

    async def do_actions(self, *, cog, user: discord.Member=None, message: discord.Message=None,
                         guild: discord.Guild=None):
        if message and not user:
            user = message.author
        guild = guild if guild else user.guild
        channel: discord.Channel = message.channel if message else None

        templates_vars = {
            "action_name": self.name,
            "guild": str(guild),
            "guild_id": guild.id
        }

        if user:
            templates_vars.update({
            "user": str(user),
            "user_name": user.name,
            "user_id": user.id,
            "user_mention": user.mention,
            "user_nickname": str(user.nick),
            "user_created_at": user.created_at,
            "user_joined_at": user.joined_at,
            })

        if message:
            templates_vars["message"] = message.content
            templates_vars["message_id"] = message.id
            templates_vars["message_created_at"] = message.created_at
            templates_vars["message_link"] = f"https://discordapp.com/channels/{guild.id}/{channel.id}/{message.id}"
            if message.attachments:
                attachment = message.attachments[0]
                templates_vars["attachment_filename"] = attachment.filename
                templates_vars["attachment_url"] = attachment.url

        if channel:
            templates_vars["channel"] = str(channel)
            templates_vars["channel_name"] = channel.name
            templates_vars["channel_id"] = channel.id
            templates_vars["channel_mention"] = channel.mention

        last_expel_action = None

        for entry in self.actions:
            for action, value in entry.items():
                action = WardenAction(action)
                self.last_action = action
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
                elif action == WardenAction.NotifyStaffWithEmbed:
                    title, content = (value[0], value[1])
                    em = self._build_embed(title, content, templates_vars=templates_vars)
                    await cog.send_notification(guild, "", embed=em)
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
                    await guild.ban(user, delete_message_days=value, reason=f"Banned by Warden action '{self.name}'")
                    last_expel_action = Action.Ban
                elif action == WardenAction.Kick:
                    await guild.kick(user, reason=f"Kicked by Warden action '{self.name}'")
                    last_expel_action = Action.Kick
                elif action == WardenAction.Softban:
                    await guild.ban(user, delete_message_days=1, reason=f"Softbanned by Warden action '{self.name}'")
                    await guild.unban(user)
                    last_expel_action = Action.Softban
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
                elif action == WardenAction.EnableEmergencyMode:
                    if value:
                        cog.emergency_mode[guild.id] = EmergencyMode(manual=True)
                    else:
                        try:
                            del cog.emergency_mode[guild.id]
                        except KeyError:
                            pass
                elif action == WardenAction.SendToMonitor:
                    value = Template(value).safe_substitute(templates_vars)
                    cog.send_to_monitor(guild, f"[Warden] ({self.name}): {value}")
                elif action == WardenAction.NoOp:
                    pass

        return bool(last_expel_action)

    def _build_embed(self, title, content, *, templates_vars):
        title = Template(title).safe_substitute(templates_vars)
        content = Template(content).safe_substitute(templates_vars)
        em = discord.Embed(color=discord.Colour.red(), description=content)
        em.set_author(name=title)
        em.set_footer(text=f"Warden rule `{self.name}`")
        return em

