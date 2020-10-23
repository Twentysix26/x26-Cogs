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

from defender.core.warden.constants import ALLOWED_CONDITIONS, ALLOWED_ACTIONS, CONDITIONS_PARAM_TYPE
from defender.core.warden.constants import ACTIONS_PARAM_TYPE, ACTIONS_ARGS_N
from ...enums import Rank, EmergencyMode, Action as ModAction
from .enums import Action, Condition, Event, ConditionBlock
from .checks import ACTIONS_SANITY_CHECK
from ...exceptions import InvalidRule, ExecutionError
from redbot.core.utils.common_filters import INVITE_URL_RE
from redbot.core.commands.converter import parse_timedelta
from string import Template
from redbot.core import modlog
from typing import Optional
import yaml
import fnmatch
import discord
import datetime
import logging
import re

log = logging.getLogger("red.x26cogs.defender")

utcnow = datetime.datetime.utcnow

RULE_REQUIRED_KEYS = ("name", "event", "rank", "if", "do")
RULE_FACULTATIVE_KEYS = ("priority",)

MEDIA_URL_RE = re.compile(r"""(http)?s?:?(\/\/[^"']*\.(?:png|jpg|jpeg|gif|png|svg|mp4|gifv))""", re.I)


class WardenRule:
    def __init__(self, rule_str, author=None, do_not_raise_during_parse=False):
        self.parse_exception = None
        self.last_action = Action.NoOp
        self.name = None
        self.events = []
        self.rank = Rank.Rank4
        self.conditions = []
        self.actions = {}
        self.raw_rule = rule_str
        self.priority = 2666
        try:
            self.parse(rule_str, author=author)
        except Exception as e:
            if not do_not_raise_during_parse:
                raise e
            self.parse_exception = e

    def parse(self, rule_str, author=None):
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
            if key not in RULE_REQUIRED_KEYS and key not in RULE_FACULTATIVE_KEYS:
                raise InvalidRule(f"Unexpected key at root level: '{key}'.")

        for key in RULE_REQUIRED_KEYS:
            if key not in rule.keys():
                raise InvalidRule(f"Missing key at root level: '{key}'.")

        if isinstance(rule["event"], list):
            try:
                for event in rule["event"]:
                    self.events.append(Event(event))
            except ValueError:
                raise InvalidRule(f"Invalid events.")
        else:
            try:
                self.events.append(Event(rule["event"]))
            except ValueError:
                raise InvalidRule("Invalid event.")
        if not self.events:
            raise InvalidRule("A least one event must be defined.")

        try:
            self.rank = Rank(rule["rank"])
        except:
            raise InvalidRule("Invalid target rank. Must be 1-4.")

        try:
            priority = rule["priority"]
            if not isinstance(priority, int) or priority < 1 or priority > 999:
                raise InvalidRule("Priority must be a number between 1 and 999.")
            self.priority = priority
        except KeyError:
            pass

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

        def is_condition_allowed_in_events(condition):
            for event in self.events:
                if not condition in ALLOWED_CONDITIONS[event]:
                    return False
            return True

        def is_action_allowed_in_events(action):
            for event in self.events:
                if not action in ALLOWED_ACTIONS[event]:
                    return False
            return True

        def validate_condition(cond):
            condition = parameter = None
            for r, p in cond.items():
                condition, parameter = r, p

            try:
                condition = Condition(condition)
            except ValueError:
                try:
                    condition = ConditionBlock(condition)
                    raise InvalidRule(f"Invalid: `{condition.value}` can only be at root level.")
                except ValueError:
                    raise InvalidRule(f"Invalid condition: `{condition}`")

            if not is_condition_allowed_in_events(condition):
                raise InvalidRule(f"Condition `{condition.value}` not allowed in the event(s) you have defined.")

            _type = None
            for _type in CONDITIONS_PARAM_TYPE[condition]:
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
                condition = Condition(condition)
            except ValueError:
                try:
                    condition = ConditionBlock(condition)
                except ValueError:
                    raise InvalidRule(f"Invalid condition: `{condition}`")

            if isinstance(condition, ConditionBlock):
                if parameter is None:
                    raise InvalidRule("Condition blocks cannot be empty.")
                for p in parameter:
                    validate_condition(p)
            else:
                validate_condition(raw_condition)

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
                    action = Action(action)
                except ValueError:
                    raise InvalidRule(f"Invalid action: `{action}`")

                if not is_action_allowed_in_events(action):
                    raise InvalidRule(f"Action `{action.value}` not allowed in the event(s) you have defined.")

                for _type in ACTIONS_PARAM_TYPE[action]:
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

                if author:
                    try:
                        ACTIONS_SANITY_CHECK[action](author=author, action=action, parameter=parameter)
                    except KeyError:
                        pass


    async def satisfies_conditions(self, *, rank: Optional[Rank], cog, user: discord.Member=None, message: discord.Message=None,
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
            condition = None
            value = []

            for r, v in raw_condition.items():
                condition, value = r, v
            try:
                condition = ConditionBlock(condition)
            except:
                condition = Condition(condition)

            if condition == ConditionBlock.IfAll:
                results = await self._evaluate_conditions(value, cog=cog, user=user, message=message, guild=guild)
                if len(results) != len(value):
                    raise RuntimeError("Mismatching number of conditions and evaluations")
                bools.append(all(results))
            elif condition == ConditionBlock.IfAny:
                results = await self._evaluate_conditions(value, cog=cog, user=user, message=message, guild=guild)
                if len(results) != len(value):
                    raise RuntimeError("Mismatching number of conditions and evaluations")
                bools.append(any(results))
            elif condition == ConditionBlock.IfNot:
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

            condition = Condition(condition)
            if condition == Condition.MessageMatchesAny:
                # One match = Passed
                content = message.content.lower()
                for pattern in value:
                    if fnmatch.fnmatch(content, pattern.lower()):
                        bools.append(True)
                        break
                else:
                    bools.append(False)
            elif condition == Condition.UsernameMatchesAny:
                # One match = Passed
                name = user.name.lower()
                for pattern in value:
                    if fnmatch.fnmatch(name, pattern.lower()):
                        bools.append(True)
                        break
                else:
                    bools.append(False)
            elif condition == Condition.NicknameMatchesAny:
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
            elif condition == Condition.ChannelMatchesAny: # We accept IDs and channel names
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
            elif condition == Condition.UserCreatedLessThan:
                if value == 0:
                    bools.append(True)
                    continue
                x_hours_ago = utcnow() - datetime.timedelta(hours=value) # type: ignore
                bools.append(user.created_at > x_hours_ago)
            elif condition == Condition.UserJoinedLessThan:
                if value == 0:
                    bools.append(True)
                    continue
                x_hours_ago = utcnow() - datetime.timedelta(hours=value) # type: ignore
                bools.append(user.joined_at > x_hours_ago)
            elif condition == Condition.UserHasDefaultAvatar:
                default_avatar_url_pattern = "*/embed/avatars/*.png"
                match = fnmatch.fnmatch(str(user.avatar_url), default_avatar_url_pattern)
                bools.append(value is match)
            elif condition == Condition.InEmergencyMode:
                in_emergency = cog.is_in_emergency_mode(guild)
                bools.append(in_emergency is value)
            elif condition == Condition.MessageHasAttachment:
                bools.append(bool(message.attachments) is value)
            elif condition == Condition.UserHasAnyRoleIn:
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
            elif condition == Condition.MessageContainsInvite:
                has_invite = INVITE_URL_RE.search(message.content)
                bools.append(bool(has_invite) is value)
            elif condition == Condition.MessageContainsMedia:
                has_media = MEDIA_URL_RE.search(message.content)
                bools.append(bool(has_media) is value)
            elif condition == Condition.MessageContainsMTMentions:
                bools.append(len(message.raw_mentions) > value) # type: ignore
            elif condition == Condition.MessageContainsMTUniqueMentions:
                bools.append(len(set(message.mentions)) > value) # type: ignore
            elif condition == Condition.IsStaff:
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
            templates_vars["message_link"] = message.jump_url
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
                action = Action(action)
                self.last_action = action
                if action == Action.DmUser:
                    text = Template(value).safe_substitute(templates_vars)
                    await user.send(text)
                elif action == Action.DeleteUserMessage:
                    await message.delete()
                elif action == Action.NotifyStaff:
                    text = Template(value).safe_substitute(templates_vars)
                    await cog.send_notification(guild, text)
                elif action == Action.NotifyStaffAndPing:
                    text = Template(value).safe_substitute(templates_vars)
                    await cog.send_notification(guild, text, ping=True)
                elif action == Action.NotifyStaffWithEmbed:
                    title, content = (value[0], value[1])
                    em = self._build_embed(title, content, templates_vars=templates_vars)
                    await cog.send_notification(guild, "", embed=em)
                elif action == Action.SendInChannel:
                    text = Template(value).safe_substitute(templates_vars)
                    await channel.send(text)
                elif action == Action.SetChannelSlowmode:
                    timedelta = parse_timedelta(value)
                    await channel.edit(slowmode_delay=timedelta.seconds)
                elif action == Action.Dm:
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
                elif action == Action.SendToChannel:
                    _id_or_name, content = (value[0], value[1])
                    channel_dest = guild.get_channel(_id_or_name)
                    if not channel_dest:
                        channel_dest = discord.utils.get(guild.channels, name=_id_or_name)
                    if not channel_dest:
                        raise ExecutionError(f"Channel '{_id_or_name}' not found.")
                    content = Template(content).safe_substitute(templates_vars)
                    await channel_dest.send(content)
                elif action == Action.AddRolesToUser:
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
                        await user.add_roles(*to_assign, reason=f"Assigned by Warden rule '{self.name}'")
                elif action == Action.RemoveRolesFromUser:
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
                        await user.remove_roles(*to_unassign, reason=f"Unassigned by Warden rule '{self.name}'")
                elif action == Action.SetUserNickname:
                    if value == "":
                        value = None
                    else:
                        value = Template(value).safe_substitute(templates_vars)
                    await user.edit(nick=value, reason=f"Changed nickname by Warden rule '{self.name}'")
                elif action == Action.BanAndDelete:
                    if user not in guild.members:
                        raise ExecutionError(f"User {user} ({user.id}) not in the server.")
                    reason = f"Banned by Warden rule '{self.name}'"
                    await guild.ban(user, delete_message_days=value, reason=reason)
                    last_expel_action = ModAction.Ban
                    cog.dispatch_event("member_remove", user, ModAction.Ban.value, reason)
                elif action == Action.Kick:
                    if user not in guild.members:
                        raise ExecutionError(f"User {user} ({user.id}) not in the server.")
                    reason = f"Kicked by Warden action '{self.name}'"
                    await guild.kick(user, reason=reason)
                    last_expel_action = Action.Kick
                    cog.dispatch_event("member_remove", user, ModAction.Kick.value, reason)
                elif action == Action.Softban:
                    if user not in guild.members:
                        raise ExecutionError(f"User {user} ({user.id}) not in the server.")
                    reason = f"Softbanned by Warden rule '{self.name}'"
                    await guild.ban(user, delete_message_days=1, reason=reason)
                    await guild.unban(user)
                    last_expel_action = Action.Softban
                    cog.dispatch_event("member_remove", user, ModAction.Softban.value, reason)
                elif action == Action.Modlog:
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
                elif action == Action.EnableEmergencyMode:
                    if value:
                        cog.emergency_mode[guild.id] = EmergencyMode(manual=True)
                    else:
                        try:
                            del cog.emergency_mode[guild.id]
                        except KeyError:
                            pass
                elif action == Action.SendToMonitor:
                    value = Template(value).safe_substitute(templates_vars)
                    cog.send_to_monitor(guild, f"[Warden] ({self.name}): {value}")
                elif action == Action.NoOp:
                    pass
                else:
                    raise ExecutionError(f"Unhandled action '{self.name}'.")

        return bool(last_expel_action)

    def _build_embed(self, title: str, content: str, *, templates_vars: dict):
        title = Template(title).safe_substitute(templates_vars)
        content = Template(content).safe_substitute(templates_vars)
        em = discord.Embed(color=discord.Colour.red(), description=content)
        em.set_author(name=title)
        em.set_footer(text=f"Warden rule `{self.name}`")
        return em
