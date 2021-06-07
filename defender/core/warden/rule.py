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

from defender.core.warden.constants import ALLOWED_CONDITIONS, ALLOWED_ACTIONS, CONDITIONS_ARGS_N, CONDITIONS_PARAM_TYPE
from defender.core.warden.constants import ACTIONS_PARAM_TYPE, ACTIONS_ARGS_N
from ...enums import Rank, EmergencyMode, Action as ModAction
from .enums import Action, Condition, Event, ConditionBlock
from .checks import ACTIONS_SANITY_CHECK, CONDITIONS_SANITY_CHECK
from .utils import has_x_or_more_emojis, REMOVE_C_EMOJIS_RE, run_user_regex, make_fuzzy_suggestion, delete_message_after
from ...exceptions import InvalidRule, ExecutionError
from ...core import cache as df_cache
from ...core.utils import is_own_invite
from redbot.core.utils.common_filters import INVITE_URL_RE
from redbot.core.commands.converter import parse_timedelta
from discord.ext.commands import BadArgument
from string import Template
from redbot.core import modlog
from typing import Optional
from . import heat
import yaml
import fnmatch
import discord
import datetime
import logging
import re

log = logging.getLogger("red.x26cogs.defender")

utcnow = datetime.datetime.utcnow

ALLOW_ALL_MENTIONS = discord.AllowedMentions(everyone=True, roles=True, users=True)
RULE_REQUIRED_KEYS = ("name", "event", "rank", "if", "do")
RULE_FACULTATIVE_KEYS = ("priority", "run-every")

MEDIA_URL_RE = re.compile(r"""(http)?s?:?(\/\/[^"']*\.(?:png|jpg|jpeg|gif|png|svg|mp4|gifv))""", re.I)
URL_RE = re.compile(r"""https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)""", re.I)


class WardenRule:
    def __init__(self):
        self.parse_exception = None
        self.last_action = Action.NoOp
        self.name = None
        self.events = []
        self.rank = Rank.Rank4
        self.conditions = []
        self.actions = {}
        self.raw_rule = ""
        self.priority = 2666
        self.next_run = None
        self.run_every = None

    async def parse(self, rule_str, cog, author=None):
        self.raw_rule = rule_str

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

        if Event.Periodic in self.events:
            # cog is None when running tests
            if cog and not await cog.config.wd_periodic_allowed():
                raise InvalidRule("The creation of periodic Warden rules is currently disabled. "
                                  "The bot owner must use '[p]dset warden periodicallowed' to "
                                  "enable them.")
            if "run-every" not in rule.keys():
                raise InvalidRule("The 'run-every' parameter is mandatory with "
                                  "periodic rules.")
            try:
                td = parse_timedelta(str(rule["run-every"]),
                                     maximum=datetime.timedelta(hours=24),
                                     minimum=datetime.timedelta(minutes=5),
                                     allowed_units=["hours", "minutes"])
                if td is None:
                    raise BadArgument()
            except BadArgument:
                raise InvalidRule("The 'run-every' parameter must be between 5 minutes "
                                  "and 24 hours.")
            else:
                self.run_every = td
                self.next_run = utcnow() + td
        else:
            if "run-every" in rule.keys():
                raise InvalidRule("The 'periodic' event must be specified for rules with "
                                  "a 'run-every' parameter.")

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

        async def validate_condition(cond):
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
                    suggestion = make_fuzzy_suggestion(condition, [c.value for c in Condition])
                    raise InvalidRule(f"Invalid condition: `{condition}`.{suggestion}")

            if not is_condition_allowed_in_events(condition):
                raise InvalidRule(f"Condition `{condition.value}` not allowed in the event(s) you have defined.")

            _type = None
            for _type in CONDITIONS_PARAM_TYPE[condition]:
                if _type is None and parameter is None:
                    break
                elif _type is None:
                    continue
                if _type == list and isinstance(parameter, list):
                    mandatory_arg_number = CONDITIONS_ARGS_N.get(condition, None)
                    if mandatory_arg_number is None:
                        break
                    p_number = len(parameter)
                    if p_number != mandatory_arg_number:
                        raise InvalidRule(f"Condition `{condition.value}` requires {mandatory_arg_number} "
                                            f"arguments, got {p_number}.")
                    else:
                        break
                elif isinstance(parameter, _type):
                    break
            else:
                human_type = _type.__name__ if _type is not None else "No parameter."
                raise InvalidRule(f"Invalid parameter type for condition `{condition.value}`. Expected: `{human_type}`")

            if author:
                try:
                    await CONDITIONS_SANITY_CHECK[condition](cog=cog, author=author, condition=condition, parameter=parameter) # type: ignore
                except KeyError:
                    pass

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
                    suggestion = make_fuzzy_suggestion(condition, [c.value for c in Condition])
                    raise InvalidRule(f"Invalid condition: `{condition}`.{suggestion}")

            if isinstance(condition, ConditionBlock):
                if parameter is None:
                    raise InvalidRule("Condition blocks cannot be empty.")
                for p in parameter:
                    await validate_condition(p)
            else:
                await validate_condition(raw_condition)

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
                    suggestion = make_fuzzy_suggestion(action, [a.value for a in Action])
                    raise InvalidRule(f"Invalid action: `{action}`.{suggestion}")

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
                        await ACTIONS_SANITY_CHECK[action](cog=cog, author=author, action=action, parameter=parameter)
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

        # For the rule's conditions to pass, every "root level" condition (or block of conditions)
        # must equal to True
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
                cond_result = all(results)
            elif condition == ConditionBlock.IfAny:
                results = await self._evaluate_conditions(value, cog=cog, user=user, message=message, guild=guild)
                if len(results) != len(value):
                    raise RuntimeError("Mismatching number of conditions and evaluations")
                cond_result = any(results)
            elif condition == ConditionBlock.IfNot:
                results = await self._evaluate_conditions(value, cog=cog, user=user, message=message, guild=guild)
                if len(results) != len(value):
                    raise RuntimeError("Mismatching number of conditions and evaluations")
                results = [not r for r in results] # Bools are flipped
                cond_result = all(results)
            else:
                results = await self._evaluate_conditions([{condition: value}], cog=cog, user=user, message=message, guild=guild)
                if len(results) != 1:
                    raise RuntimeError(f"A single condition evaluation returned {len(results)} evaluations!")
                cond_result = results[0]

            if cond_result is False:
                return False # If one root condition is False there's no need to continue

        return True

    async def _evaluate_conditions(self, conditions, *, cog, user: discord.Member=None, message: discord.Message=None,
                                   guild: discord.Guild=None):
        bools = []

        if message and not user:
            user = message.author
        guild = guild if guild else user.guild
        channel: discord.Channel = message.channel if message else None

        # We are only supporting a few template variables here for custom heatpoints
        templates_vars = {
            "rule_name": self.name,
            "guild_id": guild.id
        }

        if user:
            templates_vars["user_id"] = user.id

        if message:
            templates_vars["message_id"] = message.id

        if channel:
            templates_vars["channel_id"] = channel.id
            templates_vars["channel_category_id"] = channel.category.id if channel.category else "0"

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
            elif condition == Condition.MessageMatchesRegex:
                bools.append(
                    await run_user_regex(
                        rule_obj=self,
                        cog=cog,
                        guild=guild,
                        regex=value, # type:ignore
                        text=message.content
                    )
                )
            elif condition == Condition.UserIdMatchesAny:
                for _id in value:
                    if _id == user.id:
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
            elif condition == Condition.UsernameMatchesRegex:
                bools.append(
                    await run_user_regex(
                        rule_obj=self,
                        cog=cog,
                        guild=guild,
                        regex=value, # type:ignore
                        text=user.name
                    )
                )
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
            elif condition == Condition.NicknameMatchesRegex:
                if not user.nick:
                    bools.append(False)
                    continue
                bools.append(
                    await run_user_regex(
                        rule_obj=self,
                        cog=cog,
                        guild=guild,
                        regex=value, # type:ignore
                        text=user.nick
                    )
                )
            elif condition == Condition.ChannelMatchesAny: # We accept IDs and channel names
                if channel.id in value:
                    bools.append(True)
                    continue
                for channel_str in value:
                    channel_str = str(channel_str)
                    channel_obj = discord.utils.get(guild.text_channels, name=channel_str)
                    if channel_obj is not None and channel_obj == channel:
                        bools.append(True)
                        break
                else:
                    bools.append(False)
            elif condition == Condition.CategoryMatchesAny: # We accept IDs and category names
                if channel.category is None:
                    bools.append(False)
                    continue
                if channel.category.id in value:
                    bools.append(True)
                    continue
                for category_str in value:
                    category_str = str(category_str)
                    category_obj = discord.utils.get(guild.categories, name=category_str)
                    if category_obj is not None and category_obj == channel.category:
                        bools.append(True)
                        break
                else:
                    bools.append(False)
            elif condition == Condition.ChannelIsPublic:
                everyone = guild.default_role
                public = everyone not in channel.overwrites or channel.overwrites[everyone].read_messages in (True, None)
                bools.append(value is public)
            elif condition == Condition.UserCreatedLessThan:
                if value == 0:
                    bools.append(True)
                    continue
                x_hours_ago = utcnow() - datetime.timedelta(hours=value) # type: ignore
                bools.append(user.created_at > x_hours_ago)
            elif condition == Condition.UserIsRank:
                bools.append(await cog.rank_user(user) == Rank(value)) # type: ignore
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
            elif condition == Condition.UserHasSentLessThanMessages:
                msg_n = await cog.get_total_recorded_messages(user)
                bools.append(msg_n < value)
            elif condition == Condition.MessageContainsInvite:
                invite_match = INVITE_URL_RE.search(message.content)
                if invite_match:
                    has_invite = True
                    try:
                        if await is_own_invite(guild, invite_match):
                            has_invite = False
                    except Exception as e:
                        log.error("Unexpected error in warden's own invite check", exc_info=e)
                        has_invite = False
                else:
                    has_invite = False
                bools.append(has_invite is value)
            elif condition == Condition.MessageContainsMedia:
                has_media = MEDIA_URL_RE.search(message.content)
                bools.append(bool(has_media) is value)
            elif condition == Condition.MessageContainsUrl:
                has_url = URL_RE.search(message.content)
                bools.append(bool(has_url) is value)
            elif condition == Condition.MessageContainsMTMentions:
                bools.append(len(message.raw_mentions) > value) # type: ignore
            elif condition == Condition.MessageContainsMTUniqueMentions:
                bools.append(len(set(message.mentions)) > value) # type: ignore
            elif condition == Condition.MessageContainsMTRolePings:
                bools.append(len(message.role_mentions) > value) # type: ignore
            elif condition == Condition.MessageContainsMTEmojis:
                over_limit = has_x_or_more_emojis(cog.bot, guild, message.content, value + 1) # type: ignore
                bools.append(over_limit)
            elif condition == Condition.MessageHasMTCharacters:
                # We're turning one custom emoji code into a single character to avoid
                # unexpected (from a user's POV) behaviour
                clean_content = REMOVE_C_EMOJIS_RE.sub("x", message.clean_content)
                bools.append(len(clean_content) > value) # type: ignore
            elif condition == Condition.IsStaff:
                is_staff = await cog.bot.is_mod(user)
                bools.append(is_staff is value)
            elif condition == Condition.UserHeatIs:
                bools.append(heat.get_user_heat(user) == value)
            elif condition == Condition.ChannelHeatIs:
                bools.append(heat.get_channel_heat(channel) == value)
            elif condition == Condition.CustomHeatIs:
                heat_key = Template(value[0]).safe_substitute(templates_vars)
                bools.append(heat.get_custom_heat(guild, heat_key) == value[1])
            elif condition == Condition.UserHeatMoreThan:
                bools.append(heat.get_user_heat(user) > value) # type: ignore
            elif condition == Condition.ChannelHeatMoreThan:
                bools.append(heat.get_channel_heat(channel) > value) # type: ignore
            elif condition == Condition.CustomHeatMoreThan:
                heat_key = Template(value[0]).safe_substitute(templates_vars)
                bools.append(heat.get_custom_heat(guild, heat_key) > value[1])

        return bools

    async def do_actions(self, *, cog, user: discord.Member=None, message: discord.Message=None,
                         guild: discord.Guild=None):
        if message and not user:
            user = message.author
        guild = guild if guild else user.guild
        channel: discord.Channel = message.channel if message else None

        templates_vars = {
            "rule_name": self.name,
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
            "user_created_at": user.created_at.strftime("%Y/%m/%d %H:%M:%S"),
            "user_joined_at": user.joined_at.strftime("%Y/%m/%d %H:%M:%S"),
            "user_heat": heat.get_user_heat(user),
            })

        if message:
            templates_vars["message"] = message.content.replace("@", "@\u200b")
            templates_vars["message_clean"] = message.clean_content
            templates_vars["message_id"] = message.id
            templates_vars["message_created_at"] = message.created_at
            templates_vars["message_link"] = message.jump_url
            if message.attachments:
                attachment = message.attachments[0]
                templates_vars["attachment_filename"] = attachment.filename
                templates_vars["attachment_url"] = attachment.url

        if channel:
            templates_vars["channel"] = f"#{channel}"
            templates_vars["channel_name"] = channel.name
            templates_vars["channel_id"] = channel.id
            templates_vars["channel_mention"] = channel.mention
            templates_vars["channel_category"] = channel.category.name if channel.category else "None"
            templates_vars["channel_category_id"] = channel.category.id if channel.category else "0"
            templates_vars["channel_heat"] = heat.get_channel_heat(channel)

        #for heat_key in heat.get_custom_heat_keys(guild):
        #    templates_vars[f"custom_heat_{heat_key}"] = heat.get_custom_heat(guild, heat_key)

        last_sent_message: Optional[discord.Message] = None
        last_expel_action = None

        for entry in self.actions:
            for action, value in entry.items():
                action = Action(action)
                self.last_action = action
                if action == Action.DmUser:
                    text = Template(value).safe_substitute(templates_vars)
                    try:
                        last_sent_message = await user.send(text)
                    except:
                        cog.send_to_monitor(guild, f"[Warden] ({self.name}): Failed to DM user "
                                            f"{user} ({user.id})")
                        last_sent_message = None
                elif action == Action.DeleteUserMessage:
                    await message.delete()
                elif action == Action.NotifyStaff:
                    text = Template(value).safe_substitute(templates_vars)
                    last_sent_message = await cog.send_notification(guild, text, allow_everyone_ping=True,
                                                                    force_text_only=True)
                elif action == Action.NotifyStaffAndPing:
                    text = Template(value).safe_substitute(templates_vars)
                    last_sent_message = await cog.send_notification(guild, text, ping=True, allow_everyone_ping=True,
                                                                    force_text_only=True)
                elif action == Action.NotifyStaffWithEmbed:
                    title, content = (value[0], value[1])
                    content = Template(content).safe_substitute(templates_vars)
                    last_sent_message = await cog.send_notification(guild, content,
                                                                    title=title, footer=f"Warden rule `{self.name}`",
                                                                    allow_everyone_ping=True)
                elif action == Action.SendInChannel:
                    text = Template(value).safe_substitute(templates_vars)
                    last_sent_message = await channel.send(text, allowed_mentions=ALLOW_ALL_MENTIONS)
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
                        last_sent_message = await user_to_dm.send(content)
                    except:
                        cog.send_to_monitor(guild, f"[Warden] ({self.name}): Failed to DM user "
                                            f"{user_to_dm} ({user_to_dm.id})")
                        last_sent_message = None
                elif action == Action.SendToChannel:
                    _id_or_name, content = (value[0], value[1])
                    channel_dest = guild.get_channel(_id_or_name)
                    if not channel_dest:
                        channel_dest = discord.utils.get(guild.text_channels, name=_id_or_name)
                    if not channel_dest:
                        raise ExecutionError(f"Channel '{_id_or_name}' not found.")
                    content = Template(content).safe_substitute(templates_vars)
                    last_sent_message = await channel_dest.send(content, allowed_mentions=ALLOW_ALL_MENTIONS)
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
                elif action == Action.AddUserHeatpoint:
                    timedelta = parse_timedelta(value)
                    heat.increase_user_heat(user, timedelta) # type: ignore
                    templates_vars["user_heat"] = heat.get_user_heat(user)
                elif action == Action.AddUserHeatpoints:
                    points_n = value[0]
                    timedelta = parse_timedelta(value[1])
                    for _ in range(points_n):
                        heat.increase_user_heat(user, timedelta) # type: ignore
                    templates_vars["user_heat"] = heat.get_user_heat(user)
                elif action == Action.AddChannelHeatpoint:
                    timedelta = parse_timedelta(value)
                    heat.increase_channel_heat(channel, timedelta) # type: ignore
                    templates_vars["channel_heat"] = heat.get_channel_heat(channel)
                elif action == Action.AddChannelHeatpoints:
                    points_n = value[0]
                    timedelta = parse_timedelta(value[1])
                    for _ in range(points_n):
                        heat.increase_channel_heat(channel, timedelta) # type: ignore
                    templates_vars["channel_heat"] = heat.get_channel_heat(channel)
                elif action == Action.AddCustomHeatpoint:
                    heat_key = Template(value[0]).safe_substitute(templates_vars)
                    timedelta = parse_timedelta(value[1])
                    heat.increase_custom_heat(guild, heat_key, timedelta) # type: ignore
                    #templates_vars[f"custom_heat_{heat_key}"] = heat.get_custom_heat(guild, heat_key)
                elif action == Action.AddCustomHeatpoints:
                    heat_key = Template(value[0]).safe_substitute(templates_vars)
                    points_n = value[1]
                    timedelta = parse_timedelta(value[2])
                    for _ in range(points_n):
                        heat.increase_custom_heat(guild, heat_key, timedelta) # type: ignore
                    #templates_vars[f"custom_heat_{heat_key}"] = heat.get_custom_heat(guild, heat_key)
                elif action == Action.EmptyUserHeat:
                    heat.empty_user_heat(user)
                elif action == Action.EmptyChannelHeat:
                    heat.empty_channel_heat(channel)
                elif action == Action.EmptyCustomHeat:
                    heat_key = Template(value).safe_substitute(templates_vars)
                    heat.empty_custom_heat(guild, heat_key)
                elif action == Action.IssueCommand:
                    issuer = guild.get_member(value[0])
                    if issuer is None:
                        raise ExecutionError(f"User {value[0]} is not in the server.")
                    msg_obj = df_cache.get_msg_obj()
                    if msg_obj is None:
                        raise ExecutionError(f"Failed to issue command. Sorry!")
                    if message is None:
                        notify_channel_id = await cog.config.guild(guild).notify_channel()
                        msg_obj.channel = guild.get_channel(notify_channel_id)
                        if msg_obj.channel is None:
                            raise ExecutionError(f"Failed to issue command. Sorry!")
                    else:
                        msg_obj.channel = message.channel
                    msg_obj.author = issuer
                    prefix = await cog.bot.get_prefix(msg_obj)
                    msg_obj.content = prefix[0] + Template(str(value[1])).safe_substitute(templates_vars)
                    cog.bot.dispatch("message", msg_obj)
                elif action == Action.DeleteLastMessageSentAfter:
                    if last_sent_message is not None:
                        timedelta = parse_timedelta(value)
                        cog.loop.create_task(delete_message_after(last_sent_message, timedelta.seconds))
                        last_sent_message = None
                elif action == Action.NoOp:
                    pass
                else:
                    raise ExecutionError(f"Unhandled action '{self.name}'.")

        return bool(last_expel_action)

    def __repr__(self):
        return f"<WardenRule '{self.name}'>"
