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

from __future__ import annotations
from ...core.warden.validation import (ALLOWED_CONDITIONS, ALLOWED_ACTIONS, ALLOWED_DEBUG_ACTIONS, model_validator,
                                       DEPRECATED)
from ...core.warden import validation as models
from ...enums import Rank, EmergencyMode, Action as ModAction
from .enums import Action, Condition, Event, ConditionBlock, ConditionalActionBlock
from .utils import has_x_or_more_emojis, REMOVE_C_EMOJIS_RE, run_user_regex, make_fuzzy_suggestion, delete_message_after
from ...exceptions import InvalidRule, ExecutionError, StopExecution, MisconfigurationError
from ...core import cache as df_cache
from ...core.utils import get_external_invite, QuickAction, utcnow
from redbot.core.utils.common_filters import INVITE_URL_RE
from redbot.core.utils.chat_formatting import box
from redbot.core.commands.converter import parse_timedelta
from discord.ext.commands import BadArgument
from string import Template
from redbot.core import modlog
from typing import Optional
from pydantic import ValidationError
from typing import TYPE_CHECKING
from . import heat
import random
import yaml
import fnmatch
import discord
import datetime
import logging
import regex as re

if TYPE_CHECKING:
    from ...abc import MixinMeta

log = logging.getLogger("red.x26cogs.defender")

ALLOW_ALL_MENTIONS = discord.AllowedMentions(everyone=True, roles=True, users=True)
RULE_REQUIRED_KEYS = ("name", "event", "rank", "if", "do")
RULE_FACULTATIVE_KEYS = ("priority", "run-every")

MEDIA_URL_RE = re.compile(r"""(http)?s?:?(\/\/[^"']*\.(?:png|jpg|jpeg|gif|png|svg|mp4|gifv))""", re.I)
URL_RE = re.compile(r"""https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)""", re.I)

class ConditionResult:
    """This is used to store the condition evaluations at runtime
    It is designed to aid the user in debugging the rules"""
    def __init__(self, rule_name, debug):
        self.rule_name = rule_name
        self.conditions = []
        self.result = False
        self.debug = debug

    def add_condition(self, condition: Condition, result: bool):
        if self.debug:
            self.conditions.append((condition, result))

    def add_condition_block(self, condition_block: ConditionBlock, inner_conditions: list, results: list):
        if self.debug:
            block = (condition_block, [])
            for i, c in enumerate(inner_conditions):
                block[1].append((next(iter(c)), results[i]))
            self.conditions.append(block)

    def __bool__(self):
        return self.result

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

    async def parse(self, rule_str, cog: MixinMeta, author=None):
        self.raw_rule = rule_str

        try:
            rule = yaml.safe_load(rule_str)
        except:
            raise InvalidRule("Error parsing YAML. Please make sure the format "
                              "is valid (a YAML validator may help)")

        if not isinstance(rule, dict):
            raise InvalidRule(f"This rule doesn't seem to follow the expected format.")

        if rule.get("name") is None:
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

        if "if" in rule:
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
                    suggestion = make_fuzzy_suggestion(condition, [c.value for c in Condition
                                                                   if c not in DEPRECATED])
                    raise InvalidRule(f"Invalid condition: `{condition}`.{suggestion}")

            # Checking author prevents old rules from raising at load
            if author and condition in DEPRECATED:
                raise InvalidRule(f"Condition `{condition.value}` is deprecated: check the documentation "
                                  "for a supported alternative.")

            if not is_condition_allowed_in_events(condition):
                raise InvalidRule(f"Condition `{condition.value}` not allowed in the event(s) you have defined.")

            try:
                model = model_validator(condition, parameter)
            except ValidationError as e:
                raise InvalidRule(f"Condition `{condition.value}` invalid:\n{box(str(e))}")

            if author:
                try:
                    await model._runtime_check(cog=cog, author=author, action_or_cond=condition)
                except NotImplementedError:
                    pass

        for raw_condition in self.conditions:
            condition = parameter = None

            if not isinstance(raw_condition, dict):
                raise InvalidRule(f"Invalid condition: `{raw_condition}`. Expected map. Did you forget the colon?")

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
                    suggestion = make_fuzzy_suggestion(condition, [c.value for c in Condition
                                                                   if c not in DEPRECATED])
                    raise InvalidRule(f"Invalid condition: `{condition}`.{suggestion}")

            if isinstance(condition, ConditionBlock):
                if parameter is None:
                    raise InvalidRule("Condition blocks cannot be empty.")
                for p in parameter:
                    await validate_condition(p)
            else:
                await validate_condition(raw_condition)

        async def validate_action(action, parameter):
            # Checking author prevents old rules from raising at load
            if author and action in DEPRECATED:
                raise InvalidRule(f"Action `{action.value}` is deprecated: check the documentation "
                                "for a supported alternative.")

            if not is_action_allowed_in_events(action):
                raise InvalidRule(f"Action `{action.value}` not allowed in the event(s) you have defined.")

            try:
                model = model_validator(action, parameter)
            except ValidationError as e:
                raise InvalidRule(f"Action `{action.value}` invalid:\n{box(str(e))}")

            if author:
                try:
                    await model._runtime_check(cog=cog, author=author, action_or_cond=action)
                except NotImplementedError:
                    pass

        # Basically a list of one-key dicts
        # We need to preserve order of actions
        for entry in self.actions:
            # This will be a single loop
            if not isinstance(entry, dict):
                raise InvalidRule(f"Invalid action: `{entry}`. Expected map.")

            if len(entry) != 1:
                raise InvalidRule(f"Invalid format in the actions. Make sure you've got the dashes right!")

            for enum, parameter in entry.items():
                try:
                    enum = self._get_actions_enum(enum)
                except ValueError:
                    suggestion = make_fuzzy_suggestion(enum, [a.value for a in Action
                                                                if a not in DEPRECATED])
                    raise InvalidRule(f"Invalid action: `{enum}`.{suggestion}")

                if isinstance(enum, Action):
                    await validate_action(enum, parameter)
                elif isinstance(enum, Condition):
                    await validate_condition({enum.value: parameter})
                elif isinstance(enum, ConditionBlock):
                    if parameter is None:
                        raise InvalidRule("Condition blocks cannot be empty.")
                    for p in parameter:
                        await validate_condition(p)
                elif isinstance(enum, ConditionalActionBlock):
                    if parameter is None:
                        raise InvalidRule("Conditional action blocks cannot be empty.")
                    for raw_action in parameter:
                        if not isinstance(raw_action, dict):
                            raise InvalidRule(f"`{enum.value}` contains a non-map. Did you forget the colon?")
                        for action, subparameter in raw_action.items():
                            try:
                                action = self._get_actions_enum(action)
                            except ValueError:
                                suggestion = make_fuzzy_suggestion(action, [a.value for a in Action
                                                                            if a not in DEPRECATED])
                                raise InvalidRule(f"Invalid action: `{action}`.{suggestion}")
                            await validate_action(action, subparameter)


    async def satisfies_conditions(self, *, rank: Rank, cog: MixinMeta, user: discord.Member=None, message: discord.Message=None,
                                   guild: discord.Guild=None, debug=False)->ConditionResult:
        cr = ConditionResult(rule_name=self.name, debug=debug)
        if rank < self.rank:
            return cr

        # Due to the strict checking done during parsing we can
        # expect to always have available the variables that we need for
        # the different type of events and conditions
        # Unless I fucked up somewhere, then we're in trouble!
        if message and not user:
            user = message.author

        # For the rule's conditions to pass, every "root level" condition (or block of conditions)
        # must equal to True
        try:
            return await self._evaluate_conditions_block(block=self.conditions, cog=cog, user=user, message=message, guild=guild,
                                                        debug=debug)
        except ExecutionError:
            return cr # Ensure the rule doesn't pass if a condition errored

    async def _evaluate_conditions_block(self, *, block, cog, user: discord.Member=None, message: discord.Message=None,
                                   guild: discord.Guild=None, templates_vars=None, debug)->ConditionResult:
        # This is used during condition processing AND action processing for conditional actions
        cr = ConditionResult(rule_name=self.name, debug=debug)

        for raw_condition in block:
            condition = None
            value = []

            for r, v in raw_condition.items():
                condition, value = r, v
            try:
                condition = ConditionBlock(condition)
            except:
                condition = Condition(condition)

            if condition == ConditionBlock.IfAll:
                results = await self._evaluate_conditions(value, cog=cog, user=user, message=message,
                                                          guild=guild, templates_vars=templates_vars, debug=debug)
                if len(results) != len(value):
                    raise RuntimeError("Mismatching number of conditions and evaluations")
                cr.add_condition_block(condition, value, results) # type: ignore
                cond_result = all(results)
            elif condition == ConditionBlock.IfAny:
                results = await self._evaluate_conditions(value, cog=cog, user=user, message=message,
                                                          guild=guild, templates_vars=templates_vars, debug=debug)
                if len(results) != len(value):
                    raise RuntimeError("Mismatching number of conditions and evaluations")
                cr.add_condition_block(condition, value, results) # type: ignore
                cond_result = any(results)
            elif condition == ConditionBlock.IfNot:
                results = await self._evaluate_conditions(value, cog=cog, user=user, message=message,
                                                          guild=guild, templates_vars=templates_vars, debug=debug)
                if len(results) != len(value):
                    raise RuntimeError("Mismatching number of conditions and evaluations")
                cr.add_condition_block(condition, value, results) # type: ignore
                results = [not r for r in results] # Bools are flipped
                cond_result = all(results)
            else:
                results = await self._evaluate_conditions([{condition: value}], cog=cog, user=user, message=message,
                                                          guild=guild, templates_vars=templates_vars, debug=debug)
                if len(results) != 1:
                    raise RuntimeError(f"A single condition evaluation returned {len(results)} evaluations!")
                cr.add_condition(condition, results[0]) # type: ignore
                cond_result = results[0]

            if cond_result is False:
                return cr # If one root condition is False there's no need to continue

        cr.result = True
        return cr

    async def _evaluate_conditions(self, conditions, *, cog: MixinMeta, user: discord.Member=None, message: discord.Message=None,
                                   guild: discord.Guild=None, templates_vars=None, debug):

        if message and not user:
            user = message.author
        guild = guild if guild else user.guild
        channel: discord.Channel = message.channel if message else None

        if templates_vars is None:
            templates_vars = {}
            await populate_ctx_vars(t_vars=templates_vars,
                                    rule=self,
                                    cog=cog,
                                    guild=guild,
                                    message=message,
                                    user=user,
                                    channel=channel,
                                    debug=debug)

        checkers = {}

        def checker(condition: Condition, suggest: Condition=None):
            def decorator(function):
                def wrapper(*args, **kwargs):
                    if suggest is not None:
                        cog.send_to_monitor(guild, f"[Warden] ({self.name}): Condition "
                                                   f"'{condition.value}' is deprecated, use "
                                                   f"'{suggest.value}' instead.")
                    return function(*args, **kwargs)
                checkers[condition] = wrapper
                return wrapper
            return decorator

        def safe_sub(string):
            if string == discord.Embed.Empty:
                return string
            return Template(string).safe_substitute(templates_vars)

        @checker(Condition.MessageMatchesAny)
        async def message_matches_any(params: models.NonEmptyListStr):
            # One match = Passed
            content = message.content.lower()
            for pattern in params.value:
                if fnmatch.fnmatch(content, pattern.lower()):
                    return True
            return False

        @checker(Condition.MessageMatchesRegex)
        async def message_matches_regex(params: models.IsStr):
            return await run_user_regex(
                rule_obj=self,
                cog=cog,
                guild=guild,
                regex=params.value,
                text=message.content
            )

        @checker(Condition.UserActivityMatchesAny)
        async def user_activity_matches_any(params: models.NonEmptyListStr):
            to_check = []
            for activity in user.activities:
                if isinstance(activity, discord.BaseActivity):
                    if activity.name is not None:
                        to_check.append(activity.name)

            for activity in to_check:
                for pattern in params.value:
                    if fnmatch.fnmatch(activity.lower(), pattern.lower()):
                        return True

            return False

        @checker(Condition.UserStatusMatchesAny)
        async def user_status_matches_any(params: models.NonEmptyListStr):
            status_str = str(user.status)
            for status in params.value:
                if status.lower() == status_str:
                    return True
            return False

        @checker(Condition.UserIdMatchesAny)
        async def user_id_matches_any(params: models.NonEmptyListInt):
            for _id in params.value:
                if _id == user.id:
                    return True
            return False

        @checker(Condition.UsernameMatchesAny)
        async def username_matches_any(params: models.NonEmptyListStr):
            # One match = Passed
            name = user.name.lower()
            for pattern in params.value:
                if fnmatch.fnmatch(name, pattern.lower()):
                    return True
            return False

        @checker(Condition.UsernameMatchesRegex)
        async def username_matches_regex(params: models.IsStr):
            return await run_user_regex(
                rule_obj=self,
                cog=cog,
                guild=guild,
                regex=params.value,
                text=user.name
            )

        @checker(Condition.NicknameMatchesAny)
        async def nickname_matches_any(params: models.NonEmptyListStr):
            # One match = Passed
            if not user.nick:
                return False
            nick = user.nick.lower()
            for pattern in params.value:
                if fnmatch.fnmatch(nick, pattern.lower()):
                    return True
            return False

        @checker(Condition.NicknameMatchesRegex)
        async def nickname_matches_regex(params: models.IsStr):
            if not user.nick:
                return False
            return await run_user_regex(
                rule_obj=self,
                cog=cog,
                guild=guild,
                regex=params.value,
                text=user.nick
            )

        @checker(Condition.ChannelMatchesAny)
        async def channel_matches_any(params: models.NonEmptyList):
            if channel.id in params.value:
                return True
            for channel_str in params.value:
                channel_str = str(channel_str)
                channel_obj = discord.utils.get(guild.text_channels, name=channel_str)
                if channel_obj is not None and channel_obj == channel:
                    return True
            return False

        @checker(Condition.CategoryMatchesAny)
        async def category_matches_any(params: models.NonEmptyList):
            if channel.category is None:
                return False
            if channel.category.id in params.value:
                return True
            for category_str in params.value:
                category_str = str(category_str)
                category_obj = discord.utils.get(guild.categories, name=category_str)
                if category_obj is not None and category_obj == channel.category:
                    return True
            return False

        @checker(Condition.ChannelIsPublic)
        async def channel_is_public(params: models.IsBool):
            everyone = guild.default_role
            public = everyone not in channel.overwrites or channel.overwrites[everyone].read_messages in (True, None)
            return params.value is public

        @checker(Condition.UserCreatedLessThan)
        async def user_created_less_than(params: models.UserJoinedCreated):
            if isinstance(params.value, int):
                if params.value == 0:
                    return True
                x_hours_ago = utcnow() - datetime.timedelta(hours=params.value)
            else:
                x_hours_ago = utcnow() - params.value # type: ignore

            return user.created_at > x_hours_ago

        @checker(Condition.UserIsRank)
        async def user_is_rank(params: models.IsRank):
            return await cog.rank_user(user) == Rank(params.value)

        @checker(Condition.UserJoinedLessThan)
        async def user_joined_less_than(params: models.UserJoinedCreated):
            if isinstance(params.value, int):
                if params.value == 0:
                    return True
                x_hours_ago = utcnow() - datetime.timedelta(hours=params.value)
            else:
                x_hours_ago = utcnow() - params.value # type: ignore

            return user.joined_at > x_hours_ago

        @checker(Condition.UserHasDefaultAvatar)
        async def user_has_default_avatar(params: models.IsBool):
            default_avatar_url_pattern = "*/embed/avatars/*.png"
            match = fnmatch.fnmatch(str(user.avatar_url), default_avatar_url_pattern)
            return params.value is match

        @checker(Condition.InEmergencyMode)
        async def in_emergency_mode(params: models.IsBool):
            in_emergency = cog.is_in_emergency_mode(guild)
            return in_emergency is params.value

        @checker(Condition.MessageHasAttachment)
        async def message_has_attachment(params: models.IsBool):
            return bool(message.attachments) is params.value

        @checker(Condition.UserHasAnyRoleIn)
        async def user_has_any_role_in(params: models.NonEmptyList):
            for role_id_or_name in params.value:
                role = guild.get_role(role_id_or_name)
                if role is None:
                    role = discord.utils.get(guild.roles, name=role_id_or_name)
                if role:
                    if role in user.roles:
                        return True
            return False

        @checker(Condition.UserHasSentLessThanMessages)
        async def user_has_sent_less_than_messages(params: models.IsInt):
            msg_n = await cog.get_total_recorded_messages(user)
            return msg_n < params.value

        @checker(Condition.MessageContainsInvite)
        async def message_contains_invite(params: models.IsBool):
            results = INVITE_URL_RE.findall(message.content)
            if results:
                has_invite = True
                try:
                    if await get_external_invite(guild, results) is None:
                        has_invite = False
                except MisconfigurationError as e:
                    raise ExecutionError(str(e))
                except Exception as e:
                    error_text = "Unexpected error: failed to fetch server's own invites"
                    log.error(error_text, exc_info=e)
                    raise ExecutionError(error_text)
            else:
                has_invite = False
            return has_invite is params.value

        @checker(Condition.MessageContainsMedia)
        async def message_contains_media(params: models.IsBool):
            has_media = MEDIA_URL_RE.search(message.content)
            return bool(has_media) is params.value

        @checker(Condition.MessageContainsUrl)
        async def message_contains_url(params: models.IsBool):
            has_url = URL_RE.search(message.content)
            return bool(has_url) is params.value

        @checker(Condition.MessageContainsMTMentions)
        async def message_contains_mt_mentions(params: models.IsInt):
            return len(message.raw_mentions) > params.value

        @checker(Condition.MessageContainsMTUniqueMentions)
        async def message_contains_mt_unique_mentions(params: models.IsInt):
            return len(set(message.mentions)) > params.value

        @checker(Condition.MessageContainsMTRolePings)
        async def message_contains_mt_role_pings(params: models.IsInt):
            return len(message.role_mentions) > params.value

        @checker(Condition.MessageContainsMTEmojis)
        async def message_contains_mt_emojis(params: models.IsInt):
            over_limit = has_x_or_more_emojis(cog.bot, guild, message.content, params.value + 1)
            return over_limit

        @checker(Condition.MessageHasMTCharacters)
        async def message_has_mt_characters(params: models.IsInt):
            # We're turning one custom emoji code into a single character to avoid
            # unexpected (from a user's POV) behaviour
            clean_content = REMOVE_C_EMOJIS_RE.sub("x", message.clean_content)
            return len(clean_content) > params.value

        @checker(Condition.IsStaff)
        async def is_staff(params: models.IsBool):
            is_staff = await cog.bot.is_mod(user)
            return is_staff is params.value

        @checker(Condition.IsHelper)
        async def is_helper(params: models.IsBool):
            is_helper = await cog.is_helper(user)
            return is_helper is params.value

        @checker(Condition.UserHeatIs)
        async def user_heat_is(params: models.IsInt):
            return heat.get_user_heat(user, debug=debug) == params.value

        @checker(Condition.ChannelHeatIs)
        async def channel_heat_is(params: models.IsInt):
            return heat.get_channel_heat(channel, debug=debug) == params.value

        @checker(Condition.CustomHeatIs)
        async def custom_heat_is(params: models.CheckCustomHeatpoint):
            heat_key = Template(params.label).safe_substitute(templates_vars)
            return heat.get_custom_heat(guild, heat_key, debug=debug) == params.points

        @checker(Condition.UserHeatMoreThan)
        async def user_heat_more_than(params: models.IsInt):
            return heat.get_user_heat(user, debug=debug) > params.value

        @checker(Condition.ChannelHeatMoreThan)
        async def channel_heat_more_than(params: models.IsInt):
            return heat.get_channel_heat(channel, debug=debug) > params.value

        @checker(Condition.CustomHeatMoreThan)
        async def custom_heat_more_than(params: models.CheckCustomHeatpoint):
            heat_key = Template(params.label).safe_substitute(templates_vars)
            return heat.get_custom_heat(guild, heat_key, debug=debug) > params.points

        @checker(Condition.Compare)
        async def compare(params: models.Compare):
            value1 = safe_sub(params.value1)
            value2 = safe_sub(params.value2)

            if params.operator == "==":
                return value1 == value2
            elif params.operator == "contains":
                return value2 in value1
            elif params.operator == "contains-pattern":
                return fnmatch.fnmatch(value1.lower(), value2.lower())
            elif params.operator == "!=":
                return value1 != value2

            # Numeric operators
            try:
                value1, value2 = int(value1), int(value2)
            except ValueError:
                raise ExecutionError(f"Could not compare {value1} with {value2}: they both need to be numbers!")

            if params.operator == ">":
                return value1 > value2
            elif params.operator == "<":
                return value1 < value2
            elif params.operator == "<=":
                return value1 <= value2
            elif params.operator == ">=":
                return value1 >= value2

        if debug:
            for condition in Condition:
                if condition not in checkers:
                    raise ExecutionError(f"{condition.value} does not have a checker.")

        bools = []

        for raw_condition in conditions:

            condition = value = None
            for c, v in raw_condition.items():
                condition, value = c, v

            condition = Condition(condition)

            params = model_validator(condition, value)
            try:
                processor_func = checkers[condition]
            except KeyError:
                raise ExecutionError(f"Unhandled condition '{condition.value}'.")

            try:
                result = await processor_func(params)
            except ExecutionError as e:
                if cog: # is None in unit tests
                    cog.send_to_monitor(guild, f"[Warden] ({self.name}): {e}")
                raise e
            if result in (True, False):
                bools.append(result)
            else:
                raise ExecutionError(f"Unexpected condition evaluation result for '{condition.value}'.")

        return bools

    async def do_actions(self, *, cog: MixinMeta, user: discord.Member=None, message: discord.Message=None,
                         guild: discord.Guild=None, debug=False):
        if message and not user:
            user = message.author
        guild = guild if guild else user.guild
        channel: discord.Channel = message.channel if message else None

        templates_vars = {}
        await populate_ctx_vars(t_vars=templates_vars,
                                rule=self,
                                cog=cog,
                                guild=guild,
                                message=message,
                                user=user,
                                channel=channel,
                                debug=debug)

        def safe_sub(string):
            if string == discord.Embed.Empty:
                return string
            return Template(string).safe_substitute(templates_vars)

        #for heat_key in heat.get_custom_heat_keys(guild):
        #    templates_vars[f"custom_heat_{heat_key}"] = heat.get_custom_heat(guild, heat_key)

        last_sent_message: Optional[discord.Message] = None
        last_expel_action = None

        processors = {}

        def processor(action: Action, suggest: Action=None):
            def decorator(function):
                def wrapper(*args, **kwargs):
                    if suggest is not None:
                        cog.send_to_monitor(guild, f"[Warden] ({self.name}): Action "
                                                   f"'{action.value}' is deprecated, use "
                                                   f"'{suggest.value}' instead.")
                    return function(*args, **kwargs)
                processors[action] = wrapper
                return wrapper
            return decorator

        @processor(Action.DeleteUserMessage)
        async def delete_user_message(params: models.IsNone):
            await message.delete()

        @processor(Action.Dm, suggest=Action.SendMessage)
        async def send_dm(params: models.SendMessageToUser):
            nonlocal last_sent_message
            user_to_dm = guild.get_member(params.id)
            if not user_to_dm:
                user_to_dm = discord.utils.get(guild.members, name=params.id)
            if not user_to_dm:
                return
            content = Template(params.content).safe_substitute(templates_vars)
            try:
                last_sent_message = await user_to_dm.send(content)
            except:
                cog.send_to_monitor(guild, f"[Warden] ({self.name}): Failed to DM user "
                                    f"{user_to_dm} ({user_to_dm.id})")
                last_sent_message = None

        @processor(Action.DmUser, suggest=Action.SendMessage)
        async def send_user_dm(params: models.IsStr):
            nonlocal last_sent_message
            text = Template(params.value).safe_substitute(templates_vars)
            try:
                last_sent_message = await user.send(text)
            except:
                cog.send_to_monitor(guild, f"[Warden] ({self.name}): Failed to DM user "
                                    f"{user} ({user.id})")
                last_sent_message = None

        @processor(Action.NotifyStaff)
        async def notify_staff(params: models.NotifyStaff):
            nonlocal last_sent_message
            # Checks if only "content" has been passed
            text_only = params.__fields_set__ == {"content"}

            quick_action = None
            if params.qa_target:
                if params.qa_reason is None:
                    params.qa_reason = ""

                params.qa_target = safe_sub(params.qa_target)
                params.qa_reason = safe_sub(params.qa_reason)

                try:
                    quick_action = QuickAction(int(params.qa_target), params.qa_reason)
                except ValueError:
                    raise ExecutionError(f"{params.qa_target} is not a valid ID for a Quick Action target.")

            jump_to_msg = None

            if params.jump_to_ctx_message:
                jump_to_msg = message

            if params.jump_to:
                params.jump_to.channel_id = safe_sub(params.jump_to.channel_id)
                params.jump_to.message_id = safe_sub(params.jump_to.message_id)
                try:
                    jump_to_ch = discord.utils.get(guild.text_channels, id=int(params.jump_to.channel_id))
                except ValueError:
                    raise ExecutionError(f"{params.jump_to.channel_id} is not a valid channel ID for a \"jump to\" message.")
                if not params.jump_to.message_id.isdigit():
                    raise ExecutionError(f"{params.jump_to.message_id} is not a valid message ID for a \"jump to\" message.")
                if jump_to_ch:
                    jump_to_msg = jump_to_ch.get_partial_message(params.jump_to.message_id)
                else:
                    raise ExecutionError(f"I could not find the destination channel for the \"jump to\" message.")

            title = safe_sub(params.title) if params.title else None
            heat_key = safe_sub(params.no_repeat_key) if params.no_repeat_key else None

            fields = []

            if params.fields:
                for param in params.fields:
                    fields.append(param.dict())

            for field in fields:
                for attr in ("name", "value"):
                    if attr in field:
                        field[attr] = safe_sub(field[attr])

            if params.add_ctx_fields:
                ctx_fields = []
                if user:
                    ctx_fields.append({"name": "Username", "value": f"`{user}`"})
                    ctx_fields.append({"name": "ID", "value": f"`{user.id}`"})
                if message:
                    ctx_fields.append({"name": "Channel", "value": message.channel.mention})
                fields = ctx_fields + fields

            footer = None
            if not text_only:
                if params.footer_text is None:
                    footer = f"Warden rule `{self.name}`"
                elif params.footer_text == "":
                    footer = None
                else:
                    footer = safe_sub(params.footer_text)

            last_sent_message = await cog.send_notification(guild,
                                                            safe_sub(params.content),
                                                            title=title,
                                                            ping=params.ping,
                                                            fields=fields,
                                                            footer=footer,
                                                            thumbnail=safe_sub(params.thumbnail) if params.thumbnail else None,
                                                            jump_to=jump_to_msg,
                                                            no_repeat_for=params.no_repeat_for,
                                                            heat_key=heat_key,
                                                            quick_action=quick_action,
                                                            force_text_only=text_only,
                                                            allow_everyone_ping=params.allow_everyone_ping)

        @processor(Action.NotifyStaffAndPing, suggest=Action.NotifyStaff)
        async def notify_staff_and_ping(params: models.IsStr):
            nonlocal last_sent_message
            text = Template(params.value).safe_substitute(templates_vars)
            last_sent_message = await cog.send_notification(guild, text, ping=True, allow_everyone_ping=True,
                                                            force_text_only=True)

        @processor(Action.NotifyStaffWithEmbed, suggest=Action.NotifyStaff)
        async def notify_staff_with_embed(params: models.NotifyStaffWithEmbed):
            nonlocal last_sent_message
            title = Template(params.title).safe_substitute(templates_vars)
            content = Template(params.content).safe_substitute(templates_vars)
            last_sent_message = await cog.send_notification(guild, content,
                                                            title=title, footer=f"Warden rule `{self.name}`",
                                                            allow_everyone_ping=True)

        @processor(Action.SendInChannel, suggest=Action.SendMessage)
        async def send_in_channel(params: models.IsStr):
            nonlocal last_sent_message
            text = Template(params.value).safe_substitute(templates_vars)
            last_sent_message = await channel.send(text, allowed_mentions=ALLOW_ALL_MENTIONS)

        @processor(Action.SetChannelSlowmode)
        async def set_channel_slowmode(params: models.IsTimedelta):
            if params.value.seconds != channel.slowmode_delay:
                await channel.edit(slowmode_delay=params.value.seconds)

        @processor(Action.SendToChannel, suggest=Action.SendMessage)
        async def send_to_channel(params: models.SendMessageToChannel):
            nonlocal last_sent_message
            channel_dest = guild.get_channel(params.id_or_name)
            if not channel_dest:
                channel_dest = discord.utils.get(guild.text_channels, name=params.id_or_name)
            if not channel_dest:
                raise ExecutionError(f"Channel '{params.id_or_name}' not found.")
            content = Template(params.content).safe_substitute(templates_vars)
            last_sent_message = await channel_dest.send(content, allowed_mentions=ALLOW_ALL_MENTIONS)

        @processor(Action.AddRolesToUser)
        async def add_roles_to_user(params: models.NonEmptyList):
            to_assign = []
            for role_id_or_name in params.value:
                role = guild.get_role(role_id_or_name)
                if role is None:
                    role = discord.utils.get(guild.roles, name=role_id_or_name)
                if role:
                    to_assign.append(role)
            to_assign = list(set(to_assign))
            to_assign = [r for r in to_assign if r not in user.roles]
            if to_assign:
                await user.add_roles(*to_assign, reason=f"Assigned by Warden rule '{self.name}'")

        @processor(Action.RemoveRolesFromUser)
        async def remove_roles_from_user(params: models.NonEmptyList):
            to_unassign = []
            for role_id_or_name in params.value:
                role = guild.get_role(role_id_or_name)
                if role is None:
                    role = discord.utils.get(guild.roles, name=role_id_or_name)
                if role:
                    to_unassign.append(role)
            to_unassign = list(set(to_unassign))
            to_unassign = [r for r in to_unassign if r in user.roles]
            if to_unassign:
                await user.remove_roles(*to_unassign, reason=f"Unassigned by Warden rule '{self.name}'")

        @processor(Action.SetUserNickname)
        async def set_user_nickname(params: models.IsStr):
            if params.value == "":
                value = None
            else:
                value = Template(params.value).safe_substitute(templates_vars)
            await user.edit(nick=value, reason=f"Changed nickname by Warden rule '{self.name}'")

        @processor(Action.BanAndDelete)
        async def ban_and_delete(params: models.IsInt):
            nonlocal last_expel_action
            if user not in guild.members:
                raise ExecutionError(f"User {user} ({user.id}) not in the server.")
            reason = f"Banned by Warden rule '{self.name}'"
            await guild.ban(user, delete_message_days=params.value, reason=reason)
            last_expel_action = ModAction.Ban
            cog.dispatch_event("member_remove", user, ModAction.Ban.value, reason)

        @processor(Action.Kick)
        async def kick(params: models.IsNone):
            nonlocal last_expel_action
            if user not in guild.members:
                raise ExecutionError(f"User {user} ({user.id}) not in the server.")
            reason = f"Kicked by Warden action '{self.name}'"
            await guild.kick(user, reason=reason)
            last_expel_action = ModAction.Kick
            cog.dispatch_event("member_remove", user, ModAction.Kick.value, reason)

        @processor(Action.Softban)
        async def softban(params: models.IsNone):
            nonlocal last_expel_action
            if user not in guild.members:
                raise ExecutionError(f"User {user} ({user.id}) not in the server.")
            reason = f"Softbanned by Warden rule '{self.name}'"
            await guild.ban(user, delete_message_days=1, reason=reason)
            await guild.unban(user)
            last_expel_action = Action.Softban
            cog.dispatch_event("member_remove", user, ModAction.Softban.value, reason)

        @processor(Action.PunishUser)
        async def punish_user(params: models.IsNone):
            punish_role = guild.get_role(await cog.config.guild(guild).punish_role())
            if punish_role and not cog.is_role_privileged(punish_role):
                await user.add_roles(punish_role, reason=f"Punished by Warden rule '{self.name}'")
            else:
                cog.send_to_monitor(guild, f"[Warden] ({self.name}): Failed to punish user. Is the punish role "
                                            "still present and with *no* privileges?")

        @processor(Action.PunishUserWithMessage)
        async def punish_user_with_message(params: models.IsNone):
            punish_role = guild.get_role(await cog.config.guild(guild).punish_role())
            punish_message = await cog.config.guild(guild).punish_message()
            if punish_role and not cog.is_role_privileged(punish_role):
                await user.add_roles(punish_role, reason=f"Punished by Warden rule '{self.name}'")
                if punish_message:
                    await channel.send(f"{user.mention} {punish_message}")
            else:
                cog.send_to_monitor(guild, f"[Warden] ({self.name}): Failed to punish user. Is the punish role "
                                            "still present and with *no* privileges?")

        @processor(Action.Modlog)
        async def send_mod_log(params: models.IsStr):
            if last_expel_action is None:
                return
            reason = Template(params.value).safe_substitute(templates_vars)
            await cog.create_modlog_case(
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

        @processor(Action.EnableEmergencyMode)
        async def enable_emergency_mode(params: models.IsBool):
            if params.value:
                cog.emergency_mode[guild.id] = EmergencyMode(manual=True)
            else:
                try:
                    del cog.emergency_mode[guild.id]
                except KeyError:
                    pass

        @processor(Action.SendToMonitor)
        async def send_to_monitor(params: models.IsStr):
            value = Template(params.value).safe_substitute(templates_vars)
            cog.send_to_monitor(guild, f"[Warden] ({self.name}): {value}")

        @processor(Action.AddUserHeatpoint)
        async def add_user_heatpoint(params: models.IsTimedelta):
            heat.increase_user_heat(user, params.value, debug=debug) # type: ignore
            templates_vars["user_heat"] = heat.get_user_heat(user, debug=debug)

        @processor(Action.AddUserHeatpoints)
        async def add_user_heatpoints(params: models.AddHeatpoints):
            for _ in range(params.points):
                heat.increase_user_heat(user, params.delta, debug=debug) # type: ignore
            templates_vars["user_heat"] = heat.get_user_heat(user, debug=debug)

        @processor(Action.AddChannelHeatpoint)
        async def add_channel_heatpoint(params: models.IsTimedelta):
            heat.increase_channel_heat(channel, params.value, debug=debug) # type: ignore
            templates_vars["channel_heat"] = heat.get_channel_heat(channel, debug=debug)

        @processor(Action.AddChannelHeatpoints)
        async def add_channel_heatpoints(params: models.AddHeatpoints):
            for _ in range(params.points):
                heat.increase_channel_heat(channel, params.delta, debug=debug) # type: ignore
            templates_vars["channel_heat"] = heat.get_channel_heat(channel, debug=debug)

        @processor(Action.AddCustomHeatpoint)
        async def add_custom_heatpoint(params: models.AddCustomHeatpoint):
            heat_key = Template(params.label).safe_substitute(templates_vars)
            heat.increase_custom_heat(guild, heat_key, params.delta, debug=debug) # type: ignore

        @processor(Action.AddCustomHeatpoints)
        async def add_custom_heatpoints(params: models.AddCustomHeatpoints):
            heat_key = Template(params.label).safe_substitute(templates_vars)
            for _ in range(params.points):
                heat.increase_custom_heat(guild, heat_key, params.delta, debug=debug) # type: ignore

        @processor(Action.EmptyUserHeat)
        async def empty_user_heat(params: models.IsNone):
            heat.empty_user_heat(user, debug=debug)

        @processor(Action.EmptyChannelHeat)
        async def empty_channel_heat(params: models.IsNone):
            heat.empty_channel_heat(channel, debug=debug)

        @processor(Action.EmptyCustomHeat)
        async def empty_custom_heat(params: models.IsStr):
            heat_key = Template(params.value).safe_substitute(templates_vars)
            heat.empty_custom_heat(guild, heat_key, debug=debug)

        @processor(Action.IssueCommand)
        async def issue_command(params: models.IssueCommand):
            issuer = guild.get_member(params.issue_as)
            if issuer is None:
                raise ExecutionError(f"User {params.issue_as} is not in the server.")
            msg_obj = df_cache.get_msg_obj()
            if msg_obj is None:
                raise ExecutionError(f"Failed to issue command. Sorry!")

            # User id + command in a non-message context
            if message is None and params.destination is None:
                notify_channel_id = await cog.config.guild(guild).notify_channel()
                msg_obj.channel = guild.get_channel(notify_channel_id)
                if msg_obj.channel is None:
                    raise ExecutionError(f"Failed to issue command. I could not find the "
                                         "notification channel.")
            else:
                if params.destination is None: # User id + command in a message context
                    msg_obj.channel = message.channel
                else: # User id + command + arbitrary destination
                    params.destination = safe_sub(params.destination)
                    try:
                        msg_obj.channel = guild.get_channel(int(params.destination))
                    except ValueError:
                        raise ExecutionError(f"{params.destination} is not a valid ID.")
                    if msg_obj.channel is None:
                        raise ExecutionError(f"Failed to issue command. I could not find the "
                                            "notification channel.")

            msg_obj.author = issuer
            prefix = await cog.bot.get_prefix(msg_obj)
            msg_obj.content = prefix[0] + safe_sub(params.command)
            cog.bot.dispatch("message", msg_obj)

        @processor(Action.DeleteLastMessageSentAfter)
        async def delete_last_message_sent_after(params: models.IsTimedelta):
            nonlocal last_sent_message
            if last_sent_message is not None:
                cog.loop.create_task(delete_message_after(last_sent_message, params.value.seconds))
                last_sent_message = None

        @processor(Action.SendMessage)
        async def send_message(params: models.SendMessage):
            nonlocal last_sent_message
            default_values = 0

            for key in params.dict():
                if key == "edit_message_id":
                    continue
                attr = getattr(params, key)
                if attr is None:
                    default_values += 1
                    setattr(params, key, discord.Embed.Empty)
                elif isinstance(attr, str):
                    setattr(params, key, safe_sub(attr))

            is_user = False
            if params.id.isdigit():
                params.id = int(params.id)
                destination = discord.utils.get(guild.text_channels, id=params.id)
                if destination is None:
                    destination = guild.get_member(params.id)
                    if destination is None:
                        cog.send_to_monitor(guild, f"[Warden] ({self.name}): Failed to send message, "
                                                    f"I could not find the recipient.")
                        return
                    else:
                        is_user = True
            else:
                destination = discord.utils.get(guild.text_channels, name=params.id)
                if destination is None:
                    raise ExecutionError(f"[Warden] ({self.name}): Failed to send message, "
                                        f"'{params.id}' is not a valid channel name.")

            em = None
            no_embed = default_values >= 10 # Yuck, maybe I'll think of something better

            if no_embed and not params.content:
                raise ExecutionError(f"[Warden] ({self.name}): I have no content and "
                                      "no embed to send.")

            if no_embed is False:
                em = discord.Embed(title=params.title,
                                description=params.description,
                                url=params.url)

                if params.author_name:
                    em.set_author(name=params.author_name, url=params.author_url,
                                icon_url=params.author_icon_url)
                em.set_image(url=params.image)
                em.set_thumbnail(url=params.thumbnail)
                em.set_footer(text=params.footer_text, icon_url=params.footer_icon_url)
                for field in params.fields:
                    em.add_field(name=safe_sub(field.name),
                                value=safe_sub(field.value),
                                inline=field.inline)
                if params.add_timestamp:
                    em.timestamp = utcnow()

                if params.color is True:
                    em.color = await cog.bot.get_embed_color(destination)
                elif not params.color:
                    pass
                else:
                    em.color = discord.Colour(params.color)

            mentions = discord.AllowedMentions(everyone=params.allow_mass_mentions, roles=True, users=True,
                                               replied_user=params.ping_on_reply)

            if params.edit_message_id:
                params.edit_message_id = safe_sub(params.edit_message_id)

            if isinstance(destination, discord.Member):
                destination = destination.dm_channel if destination.dm_channel else await destination.create_dm()

            reference = None
            if params.reply_message_id:
                params.reply_message_id = safe_sub(params.reply_message_id)
                if params.reply_message_id.isdigit():
                    reference = destination.get_partial_message(int(params.reply_message_id))

            if not params.edit_message_id:
                try:
                    last_sent_message = await destination.send(params.content, embed=em, allowed_mentions=mentions,
                                                               reference=reference)
                except (discord.HTTPException, discord.Forbidden) as e:
                    # A user could just have DMs disabled
                    if is_user is False:
                        raise ExecutionError(f"[Warden] ({self.name}): Failed to deliver message "
                                            f"to channel #{destination}. {e}")
            else:
                try:
                    partial_msg = destination.get_partial_message(int(params.edit_message_id))
                    await partial_msg.edit(content=params.content if params.content else None,
                                           embed=em, allowed_mentions=mentions)
                except (discord.HTTPException, discord.Forbidden) as e:
                    raise ExecutionError(f"[Warden] ({self.name}): Failed to edit message "
                                        f"in channel #{destination}. {e}")
                except ValueError:
                    raise ExecutionError(f"[Warden] ({self.name}): Failed to edit message. "
                                        f"{params.edit_message_id} is not a valid ID")

        @processor(Action.GetUserInfo)
        async def get_user_info(params: models.GetUserInfo):
            params.id = safe_sub(params.id)
            if not params.id.isdigit():
                raise ExecutionError(f"{params.id} is not a valid ID.")

            member = guild.get_member(int(params.id))
            if not member:
                raise ExecutionError(f"Member {params.id} not found.")

            for target, attr in params.mapping.items():
                if attr.startswith("_") or "." in attr:
                    raise ExecutionError(f"You cannot access internal attributes.")

                attr = attr.lower()

                if attr == "rank":
                    value = await cog.rank_user(member)
                    value = value.value
                elif attr == "is_staff":
                    value = await cog.bot.is_mod(member)
                elif attr == "is_helper":
                    value = await cog.is_helper(member)
                elif attr == "message_count":
                    value = await cog.get_total_recorded_messages(member)
                else:
                    value = getattr(member, attr, None)
                    if value is None:
                        raise ExecutionError(f"Attribute \"{attr}\" does not exist.")

                if isinstance(value, bool):
                    value = str(value).lower()
                elif isinstance(value, datetime.datetime):
                    value = value.strftime("%Y/%m/%d %H:%M:%S")
                elif isinstance(value, discord.BaseActivity):
                    value = value.name if value.name is not None else "none"
                elif isinstance(value, discord.Spotify):
                    value = "none"
                elif isinstance(value, (str, int, discord.Asset, discord.Status)):
                    value = str(value)
                else:
                    raise ExecutionError(f"Attribute \"{attr}\" not supported.")

                templates_vars[safe_sub(target)] = value

        @processor(Action.Exit)
        async def exit(params: models.IsNone):
            raise StopExecution("Exiting.")

        @processor(Action.VarAssign)
        async def assign(params: models.VarAssign):
            if params.evaluate:
                params.value = safe_sub(params.value)

            templates_vars[safe_sub(params.var_name)] = params.value

        @processor(Action.VarAssignRandom)
        async def assign_random(params: models.VarAssignRandom):
            choices = []
            weights = []

            if isinstance(params.choices, list):
                choices = params.choices
            else:
                for k, v in params.choices.items():
                    choices.append(k)
                    weights.append(v)

            choice = random.choices(choices, weights=weights or None, k=1)[0]
            if params.evaluate:
                choice = safe_sub(choice)

            templates_vars[safe_sub(params.var_name)] = choice

        @processor(Action.VarReplace)
        async def var_replace(params: models.VarReplace):
            var_name = safe_sub(params.var_name)
            var = templates_vars.get(var_name, None)
            if var is None:
                raise ExecutionError(f"Variable \"{var_name}\" does not exist.")

            to_sub = []

            if isinstance(params.strings, str):
                to_sub.append(params.strings)
            else:
                to_sub = params.strings

            for sub in to_sub:
                var = var.replace(sub, params.substring)

            templates_vars[var_name] = var

        @processor(Action.VarSplit)
        async def var_split(params: models.VarSplit):
            var_name = safe_sub(params.var_name)
            var = templates_vars.get(var_name, None)
            if var is None:
                raise ExecutionError(f"Variable \"{var_name}\" does not exist.")

            sequences = var.split(params.separator, maxsplit=params.max_split)

            for i, var in enumerate(params.split_into):
                try:
                    templates_vars[var] = sequences[i]
                except IndexError:
                    templates_vars[var] = ""

        @processor(Action.VarTransform)
        async def var_transform(params: models.VarTransform):
            var_name = safe_sub(params.var_name)
            var = templates_vars.get(var_name, None)
            if var is None:
                raise ExecutionError(f"Variable \"{var_name}\" does not exist.")

            operation = params.operation.lower()

            if operation == "capitalize":
                var = var.capitalize()
            elif operation == "lowercase":
                var = var.lower()
            elif operation == "reverse":
                var = var[::-1]
            elif operation == "uppercase":
                var = var.upper()
            elif operation == "title":
                var = var.title()

            templates_vars[var_name] = var

        @processor(Action.VarSlice)
        async def var_slice(params: models.VarSlice):
            var_name = safe_sub(params.var_name)
            var = templates_vars.get(var_name, None)
            if var is None:
                raise ExecutionError(f"Variable \"{var_name}\" does not exist.")

            var = var[params.index:params.end_index:params.step]

            if params.slice_into:
                templates_vars[safe_sub(params.slice_into)] = var
            else:
                templates_vars[var_name] = var

        @processor(Action.NoOp)
        async def no_op(params: models.IsNone):
            pass

        if debug:
            for action in Action:
                if action not in processors:
                    raise ExecutionError(f"{action.value} does not have a processor.")

        async def process_action(action, value):
            self.last_action = action
            if debug and action not in ALLOWED_DEBUG_ACTIONS:
                return

            params = model_validator(action, value)

            try:
                processor_func = processors[action]
            except KeyError:
                raise ExecutionError(f"Unhandled action '{action.value}'.")

            await processor_func(params)


        last_cond_action_result = None

        for entry in self.actions:
            for enum, value in entry.items():
                enum = self._get_actions_enum(enum)
                if isinstance(enum, Action):
                    try:
                        await process_action(enum, value)
                    except StopExecution:
                        return bool(last_expel_action)
                elif isinstance(enum, Condition):
                    _eval = await self._evaluate_conditions([{enum.value: value}],
                                                            cog=cog, user=user, message=message,
                                                            guild=guild, templates_vars=templates_vars,
                                                            debug=debug)
                    last_cond_action_result = _eval[0]
                elif isinstance(enum, ConditionBlock):
                    _eval = await self._evaluate_conditions_block(block=[{enum.value: value}],
                                                                  cog=cog, user=user, message=message,
                                                                  guild=guild, templates_vars=templates_vars,
                                                                  debug=debug)
                    last_cond_action_result = bool(_eval)
                elif isinstance(enum, ConditionalActionBlock):
                    is_true = enum == ConditionalActionBlock.IfTrue and last_cond_action_result is True
                    is_false = enum == ConditionalActionBlock.IfFalse and last_cond_action_result is False
                    if is_true or is_false:
                        for raw_action in value:
                            for action, subvalue in raw_action.items():
                                action = self._get_actions_enum(action)
                                try:
                                    await process_action(action, subvalue)
                                except StopExecution:
                                    return bool(last_expel_action)

        return bool(last_expel_action)

    def _get_actions_enum(self, enum):
        try:
            enum = Action(enum)
        except ValueError:
            try:
                enum = Condition(enum)
            except ValueError:
                try:
                    enum = ConditionBlock(enum)
                except ValueError:
                    enum = ConditionalActionBlock(enum)

        return enum

    def __repr__(self):
        return f"<WardenRule '{self.name}'>"

async def populate_ctx_vars(*, t_vars: dict, rule: WardenRule, cog, guild, message, user, channel, debug):
    guild_icon_url = guild.icon_url_as()
    guild_banner_url = guild.banner_url_as()
    t_vars.update({
        "rule_name": rule.name,
        "guild": str(guild),
        "guild_id": guild.id,
        "guild_icon_url": guild_icon_url if guild_icon_url else "",
        "guild_banner_url": guild_banner_url if guild_banner_url else "",
        "notification_channel_id": await cog.config.guild(guild).notify_channel() if cog else 0,
    })

    if user:
        t_vars.update({
            "user": str(user),
            "user_name": user.name,
            "user_id": user.id,
            "user_mention": user.mention,
            "user_nickname": str(user.nick),
            "user_created_at": user.created_at.strftime("%Y/%m/%d %H:%M:%S"),
            "user_joined_at": user.joined_at.strftime("%Y/%m/%d %H:%M:%S"),
            "user_heat": heat.get_user_heat(user, debug=debug),
            "user_avatar_url": user.avatar_url
        })

    if message:
        t_vars.update({
            "message": message.content.replace("@", "@\u200b"),
            "message_clean": message.clean_content,
            "message_id": message.id,
            "message_created_at": message.created_at,
            "message_link": message.jump_url
        })
        if message.attachments:
            attachment = message.attachments[0]
            t_vars.update({
                "attachment_filename": attachment.filename,
                "attachment_url": attachment.url
            })

    if channel:
        t_vars.update({
            "channel": f"#{channel}",
            "channel_name": channel.name,
            "channel_id": channel.id,
            "channel_mention": channel.mention,
            "channel_category": channel.category.name if channel.category else "None",
            "channel_category_id": channel.category.id if channel.category else "0",
            "channel_heat": heat.get_channel_heat(channel, debug=debug),
        })