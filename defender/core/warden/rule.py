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
from ...core.warden.validation import (ALLOWED_STATEMENTS, ALLOWED_DEBUG_ACTIONS, model_validator,
                                       DEPRECATED, BaseModel)
from ...core.warden import validation as models
from ...enums import Rank, EmergencyMode, Action as ModAction
from .enums import Action, Condition, Event, ConditionBlock, ConditionalActionBlock, ChecksKeys
from .utils import has_x_or_more_emojis, REMOVE_C_EMOJIS_RE, run_user_regex, make_fuzzy_suggestion, delete_message_after
from ...exceptions import InvalidRule, ExecutionError, StopExecution, MisconfigurationError
from ...core import cache as df_cache
from ...core.utils import get_external_invite, QuickAction, utcnow
from ...core.menus import QAView
from redbot.core.utils.common_filters import INVITE_URL_RE
from redbot.core.utils.chat_formatting import box
from redbot.core.commands.converter import parse_timedelta
from discord.ext.commands import BadArgument
from string import Template
from typing import Optional
from pydantic import ValidationError
from typing import TYPE_CHECKING, Union, List, Dict
from . import heat
import random
import yaml
import fnmatch
import discord
import datetime
import logging
import regex as re
import math

if TYPE_CHECKING:
    from ...abc import MixinMeta

log = logging.getLogger("red.x26cogs.defender")

ALLOW_ALL_MENTIONS = discord.AllowedMentions(everyone=True, roles=True, users=True)
RULE_REQUIRED_KEYS = ("name", "event", "rank", "if", "do")
RULE_FACULTATIVE_KEYS = ("priority", "run-every")

MEDIA_URL_RE = re.compile(r"""(http)?s?:?(\/\/[^"']*\.(?:png|jpg|jpeg|gif|png|svg|mp4|gifv))""", re.I)
URL_RE = re.compile(r"""https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)""", re.I)
MAX_NESTED = 10

CHECKS_MODULES_EVENTS = {
    ChecksKeys.CommentAnalysis: Event.OnMessage,
    ChecksKeys.InviteFilter: Event.OnMessage,
    ChecksKeys.JoinMonitor: Event.OnUserJoin,
    ChecksKeys.RaiderDetection: Event.OnMessage,
}

class WDStatement:
    __slots__ = ('enum',)
    def __repr__(self):
        return f"<{self.__class__.__name__} '{self.enum.value}'>"

class WDCondition(WDStatement):
    def __init__(self, enum: Condition):
        self.enum = enum

class WDAction(WDStatement):
    def __init__(self, enum: Action):
        self.enum = enum

class WDConditionBlock(WDStatement):
    def __init__(self, enum: ConditionBlock):
        self.enum = enum

class WDConditionalActionBlock(WDStatement):
    def __init__(self, enum: ConditionalActionBlock):
        self.enum = enum

class WDRuntime:
    def __init__(self):
        self.rule_name = "" # Debugging purpose
        self.cog: MixinMeta
        self.user: discord.Member
        self.guild: discord.Guild
        self.message: discord.Message
        self.reaction: discord.Reaction
        self.role: discord.Role
        self.evaluations: List[List[bool]] = []
        self.last_result: Optional[bool] = None
        self.state = {}
        self.trace = []
        self.last_expel_action: Optional[Union[Action, ModAction]]=None
        self.last_sent_message: Optional[discord.Message]=None
        self.debug = True

    async def populate_ctx_vars(self, rule: WardenRule):
        cog = self.cog
        guild = self.guild
        self.state.update({
            "rule_name": rule.name,
            "guild": str(guild),
            "guild_id": guild.id,
            "guild_icon_url": guild.icon.url if guild.icon else "",
            "guild_banner_url": guild.banner.url if guild.banner else "",
            "notification_channel_id": await cog.config.guild(guild).notify_channel() if cog else 0,
        })

        if self.user:
            user = self.user
            self.state.update({
                "user": str(user),
                "user_name": user.name,
                "user_display": user.display_name,
                "user_id": user.id,
                "user_mention": user.mention,
                "user_nickname": str(user.nick),
                "user_created_at": user.created_at.strftime("%Y/%m/%d %H:%M:%S"),
                "user_joined_at": user.joined_at.strftime("%Y/%m/%d %H:%M:%S"),
                "user_heat": heat.get_user_heat(user, debug=self.debug),
                "user_avatar_url": user.avatar.url if user.avatar else ""
            })

        if self.message:
            message = self.message
            channel = message.channel
            self.state.update({
                "message": message.content.replace("@", "@\u200b"),
                "message_clean": message.clean_content,
                "message_id": message.id,
                "message_created_at": message.created_at,
                "message_link": message.jump_url,
                "message_reaction": str(self.reaction) if self.reaction else "",
                "message_author_id": message.author.id,
                "channel": f"#{channel}",
                "channel_name": channel.name,
                "channel_id": channel.id,
                "channel_mention": channel.mention,
                "channel_category": channel.category.name if channel.category else "None",
                "channel_category_id": channel.category.id if channel.category else "0",
                "channel_heat": heat.get_channel_heat(channel, debug=self.debug),
                "parent": "",
                "parent_name": "",
                "parent_id": "",
                "parent_mention": "",
                "parent_heat": "",
            })
            if message.attachments:
                attachment = message.attachments[0]
                self.state.update({
                    "attachment_filename": attachment.filename,
                    "attachment_url": attachment.url
                })

            if isinstance(channel, discord.Thread):
                self.state.update({
                    "parent": f"#{channel.parent}",
                    "parent_name": channel.parent.name,
                    "parent_id": channel.parent.id,
                    "parent_mention": channel.parent.mention,
                    "parent_heat": heat.get_channel_heat(channel.parent, debug=self.debug),
                })

        if self.role:
            self.state.update({
                "role_id": self.role.id,
                "role_name": self.role.name,
                "role_mention": self.role.mention,
                "role_added": "true" if self.role in self.user.roles else "false",
            })

    def __repr__(self):
        return f"<WDRuntime '{self.rule_name}'>"

    def add_trace_enter(self, stack, enum, ignore=None):
        if enum == ignore:
            return
        stack += 1
        stack = "".join([" " for i in range(stack)])

        if isinstance(enum, Condition):
            self.trace.append(f"{stack}[=] {enum.value}")
        elif isinstance(enum, Action):
            self.trace.append(f"{stack}[=] {enum.value}")
        elif isinstance(enum, (ConditionBlock, ConditionalActionBlock)):
            self.trace.append(f"{stack}[>] {enum.value} block")

    def add_trace_exit(self, stack, enum):
        stack += 1
        stack = "".join([" " for i in range(stack)])
        if isinstance(enum, Condition):
            last_trace = self.trace.pop()
            last_trace += f" ({self.last_result})"
            self.trace.append(last_trace)
        elif isinstance(enum, Action):
            last_trace = self.trace.pop()
            last_trace += f" (Done)"
            self.trace.append(last_trace)
        elif isinstance(enum, ConditionBlock):
            self.trace.append(f"{stack}[<] {enum.value} block ({self.last_result})")
        elif isinstance(enum, ConditionalActionBlock):
            self.trace.append(f"{stack}[<] {enum.value} block")

    def __bool__(self):
        return bool(self.last_result)

class WardenRule:
    errors = {
        "CONDITIONS_ONLY": "Actions and conditional action blocks are not allowed in the condition section of a rule.",
        "NOT_ALLOWED_IN_EVENTS": "Statement `{}` not allowed in the event(s) you have defined.",
    }

    def __init__(self):
        self.last_action = Action.NoOp
        self.name = None
        self.events = []
        self.rank = Rank.Rank4
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

        if not rule["if"]:
            raise InvalidRule("Rule must have at least one condition.")

        self.cond_tree = await self.parse_tree(rule["if"],
                                               cog=cog,
                                               author=author,
                                               events=self.events,
                                               conditions_only=True)

        if not isinstance(rule["do"], list):
            raise InvalidRule("Invalid 'do' category. Must be a list of maps.")

        if not rule["do"]:
            raise InvalidRule("Rule must have at least one action.")

        self.action_tree = await self.parse_tree(rule["do"],
                                                 cog=cog,
                                                 author=author,
                                                 events=self.events)

    async def parse_tree(self, raw_tree, *, events, author, cog: MixinMeta, conditions_only=False, stack=-1, outer_block=None):
        def get_enum(statement):
            try:
                enum = Condition(statement)
            except ValueError:
                try:
                    enum = ConditionBlock(statement)
                except ValueError:
                    try:
                        enum = ConditionalActionBlock(statement)
                    except ValueError:
                        enum = Action(statement)

            return enum

        stack += 1
        if stack > MAX_NESTED:
            raise InvalidRule(f"Exceeded maximum nesting level ({MAX_NESTED})")

        tree = {}

        for _dict in raw_tree:
            if not isinstance(_dict, dict):
                raise InvalidRule(f"Invalid statement: `{_dict}`. Expected map. Did you forget the colon?")

            statement, value = next(iter(_dict.items()))

            try:
                enum = get_enum(statement)
            except ValueError:
                suggestions = [c.value for c in Condition if c not in DEPRECATED]
                if conditions_only is False:
                    suggestions.extend([a.value for a in Action if a not in DEPRECATED])
                suggestion = make_fuzzy_suggestion(statement, suggestions)
                raise InvalidRule(f"Invalid statement: `{statement}`.{suggestion}")

            if conditions_only and isinstance(enum, (Action, ConditionalActionBlock)):
                raise InvalidRule(self.errors["CONDITIONS_ONLY"])

            model = None

            try:
                if isinstance(enum, Condition):
                    model = model_validator(enum, value)
                    tree[WDCondition(enum=enum)] = model
                elif isinstance(enum, Action):
                    if outer_block is ConditionBlock:
                        raise InvalidRule("Actions are not allowed inside condition blocks")
                    model = model_validator(enum, value)
                    tree[WDAction(enum=enum)] = model
                elif isinstance(enum, ConditionBlock):
                    tree[WDConditionBlock(enum=enum)] = await self.parse_tree(value, events=events, author=author, cog=cog,
                                                                              conditions_only=conditions_only, stack=stack, outer_block=ConditionBlock)
                elif isinstance(enum, ConditionalActionBlock):
                    if outer_block is ConditionBlock:
                        raise InvalidRule("Conditional action blocks are not allowed inside condition blocks")
                    tree[WDConditionalActionBlock(enum=enum)] = await self.parse_tree(value, events=events, author=author, cog=cog,
                                                                                      conditions_only=conditions_only, stack=stack, outer_block=ConditionalActionBlock)
            except ValidationError as e:
                raise InvalidRule(f"Statement `{enum.value}` invalid:\n{box(str(e))}")

            if model and author:
                try:
                    await model._runtime_check(cog=cog, author=author, action_or_cond=enum)
                except NotImplementedError:
                    pass

            if model:
                for event in events:
                    if not enum in ALLOWED_STATEMENTS[event]:
                        raise InvalidRule(self.errors["NOT_ALLOWED_IN_EVENTS"].format(enum.value))

            if author and model:
            # Checking author prevents old rules from raising at load
                if enum in DEPRECATED:
                    raise InvalidRule(f"Statement `{enum.value}` is deprecated: check the documentation "
                                      "for a supported alternative.")

        if not tree:
            raise InvalidRule("Empty block.")

        return tree

    async def eval_tree(self, tree: Dict[WDStatement, Union[BaseModel, List]], *, runtime: WDRuntime, bool_stop=None, stack=-1, outer_block=None)->WDRuntime:
        stack += 1

        for statement, value in tree.items():
            if runtime.debug:
                runtime.add_trace_enter(stack, statement.enum, ignore=WDConditionalActionBlock if runtime.last_result else None)

            if isinstance(statement, WDCondition):
                await self._evaluate_condition(condition=statement.enum, model=value, runtime=runtime)
            elif isinstance(statement, WDAction):
                await self._do_action(action=statement.enum, model=value, runtime=runtime)
            elif isinstance(statement, WDConditionBlock):
                block_bool_stop = statement.enum in (ConditionBlock.IfNot, ConditionBlock.IfAny)
                await self.eval_tree(value, runtime=runtime, bool_stop=block_bool_stop, stack=stack, outer_block=statement.enum)
            elif isinstance(statement, WDConditionalActionBlock):
                can_run_true = statement.enum is ConditionalActionBlock.IfTrue and runtime.last_result is True
                can_run_false = statement.enum is ConditionalActionBlock.IfFalse and runtime.last_result is False
                if can_run_true or can_run_false:
                    if runtime.debug:
                        runtime.add_trace_enter(stack, statement.enum)
                    last_stack_result = runtime.last_result # ConditionalActionBlocks leaking inner last_results leads to unintuitive behaviour
                    await self.eval_tree(value, runtime=runtime, stack=stack)
                    runtime.last_result = last_stack_result
                else:
                    continue # We don't want a trace exit for non-executing CondActionBlocks

            if runtime.debug:
                runtime.add_trace_exit(stack, statement.enum)

            # Condition blocks stop evaluating at their first failed eval, depending on their type
            if bool_stop in (True, False) and runtime.last_result is bool_stop:
                runtime.last_result = outer_block is ConditionBlock.IfAny
                return runtime

        # The block did not exit early and can be considered successsful
        if outer_block and outer_block is not ConditionBlock.IfAny:
            runtime.last_result = True

        return runtime

    async def satisfies_conditions(self, *, rank: Rank, cog: MixinMeta, user: Optional[discord.Member]=None, message: Optional[discord.Message]=None,
                                   guild: discord.Guild, reaction: Optional[discord.Reaction]=None, role: Optional[discord.Role]=None, debug=False)->WDRuntime:
        runtime = WDRuntime()
        runtime.rule_name = self.name
        runtime.cog = cog
        runtime.guild = guild or message.guild
        runtime.user = user
        runtime.message = message
        runtime.reaction = reaction
        runtime.role = role
        runtime.debug = debug
        await runtime.populate_ctx_vars(self)

        if rank < self.rank:
            return runtime
        if not self.cond_tree:
            return runtime

        try:
            await self.eval_tree(self.cond_tree, runtime=runtime, bool_stop=False)
        except (StopExecution, ExecutionError):
            runtime.last_result = False

        return runtime

    async def _evaluate_condition(self, condition: Condition, *, model: BaseModel, runtime: WDRuntime):
        cog = runtime.cog
        message = runtime.message
        user = runtime.user
        guild = runtime.guild
        debug = runtime.debug

        if message and not user:
            user = message.author
        guild = guild if guild else user.guild
        channel: discord.Channel = message.channel if message else None
        parent = None

        if channel is not None:
            if type(channel) is discord.Thread:
                parent = channel.parent

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
            if string is None:
                return string
            return Template(string).safe_substitute(runtime.state)

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

        @checker(Condition.MessageContainsWord)
        async def message_contains_word(params: models.NonEmptyListStr):
            message_words = message.content.lower().split()
            for word in message_words:
                for pattern in params.value:
                    if fnmatch.fnmatch(word, pattern.lower()):
                        return True
            return False

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
            if parent is None: # Name matching for channels only
                for channel_str in params.value:
                    channel_str = str(channel_str)
                    channel_obj = discord.utils.get(guild.text_channels, name=channel_str)
                    if channel_obj is not None and channel_obj == channel:
                        return True
            return False

        @checker(Condition.CategoryMatchesAny)
        async def category_matches_any(params: models.NonEmptyList):
            chan = channel if parent is None else parent
            if chan.category is None:
                return False
            if chan.category.id in params.value:
                return True
            for category_str in params.value:
                category_str = str(category_str)
                category_obj = discord.utils.get(guild.categories, name=category_str)
                if category_obj is not None and category_obj == chan.category:
                    return True
            return False

        @checker(Condition.ChannelIsPublic)
        async def channel_is_public(params: models.IsBool):
            if parent is None:
                everyone = guild.default_role
                public = everyone not in channel.overwrites or channel.overwrites[everyone].read_messages in (True, None)
                return params.value is public
            else:
                is_public_thread = channel.type is discord.ChannelType.public_thread
                return params.value is is_public_thread

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
            match = fnmatch.fnmatch(user.avatar.url, default_avatar_url_pattern)
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
            heat_key = Template(params.label).safe_substitute(runtime.state)
            return heat.get_custom_heat(guild, heat_key, debug=debug) == params.points

        @checker(Condition.UserHeatMoreThan)
        async def user_heat_more_than(params: models.IsInt):
            return heat.get_user_heat(user, debug=debug) > params.value

        @checker(Condition.ChannelHeatMoreThan)
        async def channel_heat_more_than(params: models.IsInt):
            return heat.get_channel_heat(channel, debug=debug) > params.value

        @checker(Condition.CustomHeatMoreThan)
        async def custom_heat_more_than(params: models.CheckCustomHeatpoint):
            heat_key = Template(params.label).safe_substitute(runtime.state)
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
            for c in Condition:
                if c not in checkers:
                    raise ExecutionError(f"{condition.value} does not have a checker.")

        try:
            processor_func = checkers[condition]
        except KeyError:
            raise ExecutionError(f"Unhandled condition '{condition.value}'.")

        try:
            result = await processor_func(model)
        except ExecutionError as e:
            if cog: # is None in unit tests
                cog.send_to_monitor(guild, f"[Warden] ({self.name}): {e}")
            runtime.last_result = False
            raise e
        if result in (True, False):
            runtime.last_result = result
            return runtime
        else:
            raise ExecutionError(f"Unexpected condition evaluation result for '{condition.value}'.")

    async def do_actions(self, *, cog: MixinMeta, user: Optional[discord.Member]=None, message:  Optional[discord.Message]=None,
                         reaction: Optional[discord.Reaction]=None, guild: discord.Guild, role: Optional[discord.Role]=None, debug=False):
        runtime = WDRuntime()
        runtime.rule_name = self.name
        runtime.cog = cog
        runtime.guild = guild
        runtime.user = user
        runtime.message = message
        runtime.reaction = reaction
        runtime.role = role
        runtime.debug = debug
        await runtime.populate_ctx_vars(self)

        try:
            await self.eval_tree(self.action_tree, runtime=runtime)
        except StopExecution:
            return

    async def _do_action(self, action: Action, *, model: BaseModel, runtime: WDRuntime):
        cog = runtime.cog
        message = runtime.message
        user = runtime.user
        guild = runtime.guild
        debug = runtime.debug

        if message and not user:
            user = message.author
        guild = guild if guild else user.guild
        channel: discord.Channel = message.channel if message else None
        parent = None

        if channel is not None:
            if type(channel) is discord.Thread:
                parent = channel.parent

        def safe_sub(string):
            if string is None:
                return string
            return Template(string).safe_substitute(runtime.state)

        #for heat_key in heat.get_custom_heat_keys(guild):
        #    runtime.state[f"custom_heat_{heat_key}"] = heat.get_custom_heat(guild, heat_key)

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

        @processor(Action.NotifyStaff)
        async def notify_staff(params: models.NotifyStaff):
            # Checks if only "content" has been passed
            text_only = params.__fields_set__ == {"content"}

            quick_action = None
            if params.qa_target:
                qa_target = safe_sub(params.qa_target)
                try:
                    qa_target = int(qa_target)
                except ValueError:
                    raise ExecutionError(f"{qa_target} is not a valid ID for a Quick Action target.")
                qa_reason = "" if params.qa_reason is None else params.qa_reason
                qa_reason = safe_sub(qa_reason)
                quick_action = QAView(cog, qa_target, qa_reason)

            jump_to_msg = None

            if params.jump_to_ctx_message:
                jump_to_msg = message

            if params.jump_to:
                jump_to_channel_id = safe_sub(params.jump_to.channel_id)
                jump_to_message_id = safe_sub(params.jump_to.message_id)
                try:
                    jump_to_ch = discord.utils.get(guild.text_channels, id=int(jump_to_channel_id))
                except ValueError:
                    raise ExecutionError(f"{jump_to_channel_id} is not a valid channel ID for a \"jump to\" message.")
                if jump_to_ch:
                    try:
                        jump_to_msg = jump_to_ch.get_partial_message(int(jump_to_message_id))
                    except ValueError:
                        raise ExecutionError(f"{jump_to_message_id} is not a valid message ID for a \"jump to\" message.")
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

            runtime.last_sent_message = await cog.send_notification(guild,
                                                                    safe_sub(params.content),
                                                                    title=title,
                                                                    ping=params.ping,
                                                                    fields=fields,
                                                                    footer=footer,
                                                                    thumbnail=safe_sub(params.thumbnail) if params.thumbnail else None,
                                                                    jump_to=jump_to_msg,
                                                                    no_repeat_for=params.no_repeat_for,
                                                                    heat_key=heat_key,
                                                                    view=quick_action,
                                                                    force_text_only=text_only,
                                                                    allow_everyone_ping=params.allow_everyone_ping)

        @processor(Action.SetChannelSlowmode)
        async def set_channel_slowmode(params: models.IsTimedelta):
            if params.value.seconds != channel.slowmode_delay:
                await channel.edit(slowmode_delay=params.value.seconds)

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
                value = Template(params.value).safe_substitute(runtime.state)
            await user.edit(nick=value, reason=f"Changed nickname by Warden rule '{self.name}'")

        @processor(Action.BanAndDelete)
        async def ban_and_delete(params: models.IsInt):
            if user not in guild.members:
                raise ExecutionError(f"User {user} ({user.id}) not in the server.")
            reason = f"Banned by Warden rule '{self.name}'"
            await guild.ban(user, delete_message_days=params.value, reason=reason)
            runtime.last_expel_action = ModAction.Ban
            cog.dispatch_event("member_remove", user, ModAction.Ban.value, reason)

        @processor(Action.Kick)
        async def kick(params: models.IsNone):
            if user not in guild.members:
                raise ExecutionError(f"User {user} ({user.id}) not in the server.")
            reason = f"Kicked by Warden action '{self.name}'"
            await guild.kick(user, reason=reason)
            runtime.last_expel_action = ModAction.Kick
            cog.dispatch_event("member_remove", user, ModAction.Kick.value, reason)

        @processor(Action.Softban)
        async def softban(params: models.IsNone):
            if user not in guild.members:
                raise ExecutionError(f"User {user} ({user.id}) not in the server.")
            reason = f"Softbanned by Warden rule '{self.name}'"
            await guild.ban(user, delete_message_days=1, reason=reason)
            await guild.unban(user)
            runtime.last_expel_action = Action.Softban
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
            punish_message = await cog.format_punish_message(user)
            if punish_role and not cog.is_role_privileged(punish_role):
                await user.add_roles(punish_role, reason=f"Punished by Warden rule '{self.name}'")
                if punish_message:
                    await channel.send(punish_message)
            else:
                cog.send_to_monitor(guild, f"[Warden] ({self.name}): Failed to punish user. Is the punish role "
                                            "still present and with *no* privileges?")

        @processor(Action.Modlog)
        async def send_mod_log(params: models.IsStr):
            if runtime.last_expel_action is None:
                return
            reason = Template(params.value).safe_substitute(runtime.state)
            await cog.create_modlog_case(
                cog.bot,
                guild,
                utcnow(),
                runtime.last_expel_action.value,
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
            value = Template(params.value).safe_substitute(runtime.state)
            cog.send_to_monitor(guild, f"[Warden] ({self.name}): {value}")

        @processor(Action.AddUserHeatpoint)
        async def add_user_heatpoint(params: models.IsTimedelta):
            heat.increase_user_heat(user, params.value, debug=debug) # type: ignore
            runtime.state["user_heat"] = heat.get_user_heat(user, debug=debug)

        @processor(Action.AddUserHeatpoints)
        async def add_user_heatpoints(params: models.AddHeatpoints):
            for _ in range(params.points):
                heat.increase_user_heat(user, params.delta, debug=debug) # type: ignore
            runtime.state["user_heat"] = heat.get_user_heat(user, debug=debug)

        @processor(Action.AddChannelHeatpoint)
        async def add_channel_heatpoint(params: models.IsTimedelta):
            heat.increase_channel_heat(channel, params.value, debug=debug) # type: ignore
            runtime.state["channel_heat"] = heat.get_channel_heat(channel, debug=debug)

        @processor(Action.AddChannelHeatpoints)
        async def add_channel_heatpoints(params: models.AddHeatpoints):
            for _ in range(params.points):
                heat.increase_channel_heat(channel, params.delta, debug=debug) # type: ignore
            runtime.state["channel_heat"] = heat.get_channel_heat(channel, debug=debug)

        @processor(Action.AddCustomHeatpoint)
        async def add_custom_heatpoint(params: models.AddCustomHeatpoint):
            heat_key = Template(params.label).safe_substitute(runtime.state)
            heat.increase_custom_heat(guild, heat_key, params.delta, debug=debug) # type: ignore

        @processor(Action.AddCustomHeatpoints)
        async def add_custom_heatpoints(params: models.AddCustomHeatpoints):
            heat_key = Template(params.label).safe_substitute(runtime.state)
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
            heat_key = Template(params.value).safe_substitute(runtime.state)
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
                    destination = safe_sub(params.destination)
                    try:
                        msg_obj.channel = guild.get_channel(int(destination))
                    except ValueError:
                        raise ExecutionError(f"{destination} is not a valid ID.")
                    if msg_obj.channel is None:
                        raise ExecutionError(f"Failed to issue command. I could not find the "
                                            "notification channel.")
                    if msg_obj.channel.permissions_for(issuer).view_channel is False:
                        raise ExecutionError("Failed to issue command. The issuer has no permissions "
                                             "to view the destination channel.")

            msg_obj.author = issuer
            prefix = await cog.bot.get_prefix(msg_obj)
            msg_obj.content = prefix[0] + safe_sub(params.command)
            cog.bot.dispatch("message", msg_obj)

        @processor(Action.DeleteLastMessageSentAfter)
        async def delete_last_message_sent_after(params: models.IsTimedelta):
            if runtime.last_sent_message is not None:
                cog.loop.create_task(delete_message_after(runtime.last_sent_message, params.value.seconds))
                runtime.last_sent_message = None

        @processor(Action.SendMessage)
        async def send_message(params: models.SendMessage):

            params = params.copy() # This model is mutable for easier handling

            send_embed = False

            for key in params.__fields_set__:
                if key not in params._text_only_attrs:
                    send_embed = True
                    break

            for key in params.dict():
                attr = getattr(params, key)
                if attr is None and key not in params._text_only_attrs:
                    setattr(params, key, None)
                elif isinstance(attr, str):
                    setattr(params, key, safe_sub(attr))

            is_user = False
            pool = guild.text_channels if parent is None else guild.threads
            if params.id.isdigit():
                params.id = int(params.id)
                destination = discord.utils.get(pool, id=params.id)
                if destination is None:
                    destination = guild.get_member(params.id)
                    if destination is None:
                        cog.send_to_monitor(guild, f"[Warden] ({self.name}): Failed to send message, "
                                                    f"I could not find the recipient.")
                        return
                    else:
                        is_user = True
            else:
                destination = discord.utils.get(pool, name=params.id)
                if destination is None:
                    raise ExecutionError(f"[Warden] ({self.name}): Failed to send message, "
                                        f"'{params.id}' is not a valid channel name.")

            em = None

            if send_embed is False and not params.content:
                raise ExecutionError(f"[Warden] ({self.name}): I have no content and "
                                      "no embed to send.")

            if send_embed:
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
                    runtime.last_sent_message = await destination.send(params.content, embed=em, allowed_mentions=mentions,
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
            _id = safe_sub(params.id)
            if not _id.isdigit():
                raise ExecutionError(f"{_id} is not a valid ID.")

            member = guild.get_member(int(_id))
            if not member:
                raise ExecutionError(f"Member {_id} not found.")

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

                runtime.state[safe_sub(target)] = value

        @processor(Action.Exit)
        async def exit(params: models.IsNone):
            raise StopExecution("Exiting.")

        @processor(Action.VarAssign)
        async def assign(params: models.VarAssign):
            value = safe_sub(params.value) if params.evaluate else params.value
            runtime.state[safe_sub(params.var_name)] = value

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

            runtime.state[safe_sub(params.var_name)] = choice

        @processor(Action.VarAssignHeat)
        async def assign_heat(params: models.VarAssignHeat):
            heat_key = safe_sub(params.heat_label)

            if heat_key == "user_heat" and user:
                value = heat.get_user_heat(user, debug=debug)
            elif heat_key == "channel_heat" and channel:
                value = heat.get_channel_heat(channel, debug=debug)
            else:
                value = heat.get_custom_heat(guild, heat_key, debug=debug)

            runtime.state[params.var_name] = value

        @processor(Action.VarMath)
        async def var_math(params: models.VarMath):
            ops = ("+", "-", "*", "/", "pow")
            single_ops = ("abs", "floor", "ceil", "trunc")

            op = safe_sub(params.operator).lower()

            if op not in ops and op not in single_ops:
                raise ExecutionError(f"{op} is not a valid operator.")
            elif op in ops and params.operand2 is None:
                raise ExecutionError("Missing second operand.")
            elif op in single_ops and params.operand2 is not None:
                raise ExecutionError(f"A second operand is not needed with operator {op}")

            num1, num2 = safe_sub(params.operand1), safe_sub(params.operand2) if params.operand2 is not None else 0

            def cast_to_number(n):
                try:
                    return int(n)
                except:
                    try:
                        return float(n)
                    except:
                        raise ExecutionError(f"{n} is not a number.")

            num1, num2 = cast_to_number(num1), cast_to_number(num2)

            try:
                if op == "+":
                    result = num1 + num2
                elif op == "-":
                    result = num1 - num2
                elif op == "*":
                    result = num1 * num2
                elif op == "/":
                    result = num1 / num2
                elif op == "abs":
                    result = abs(num1)
                elif op == "pow":
                    result = math.pow(num1, num2)
                elif op == "floor":
                    result = math.floor(num1)
                elif op == "ceil":
                    result = math.ceil(num1)
                elif op == "trunc":
                    result = math.trunc(num1)
                else:
                    raise ExecutionError(f"Unhandled operator: {op}.")
            except Exception as e:
                raise ExecutionError(f"Calculation error: {e}")

            runtime.state[params.result_var] = str(result)

        @processor(Action.VarReplace)
        async def var_replace(params: models.VarReplace):
            var_name = safe_sub(params.var_name)
            var = runtime.state.get(var_name, None)
            if var is None:
                raise ExecutionError(f"Variable \"{var_name}\" does not exist.")

            to_sub = []

            if isinstance(params.strings, str):
                to_sub.append(params.strings)
            else:
                to_sub = params.strings

            for sub in to_sub:
                var = var.replace(sub, params.substring)

            runtime.state[var_name] = var

        @processor(Action.VarSplit)
        async def var_split(params: models.VarSplit):
            var_name = safe_sub(params.var_name)
            var = runtime.state.get(var_name, None)
            if var is None:
                raise ExecutionError(f"Variable \"{var_name}\" does not exist.")

            sequences = var.split(params.separator, maxsplit=params.max_split)

            for i, var in enumerate(params.split_into):
                try:
                    runtime.state[var] = sequences[i]
                except IndexError:
                    runtime.state[var] = ""

        @processor(Action.VarTransform)
        async def var_transform(params: models.VarTransform):
            var_name = safe_sub(params.var_name)
            var = runtime.state.get(var_name, None)
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

            runtime.state[var_name] = var

        @processor(Action.VarSlice)
        async def var_slice(params: models.VarSlice):
            var_name = safe_sub(params.var_name)
            var = runtime.state.get(var_name, None)
            if var is None:
                raise ExecutionError(f"Variable \"{var_name}\" does not exist.")

            var = var[params.index:params.end_index:params.step]

            if params.slice_into:
                runtime.state[safe_sub(params.slice_into)] = var
            else:
                runtime.state[var_name] = var

        @processor(Action.WarnSystemWarn)
        async def warnsystem_warn(params: models.WarnSystemWarn):
            ws = cog.bot.get_cog("WarnSystem")
            if ws is None:
                raise ExecutionError("WarnSystem is not loaded. Integration not available.")

            if isinstance(params.members, list):
                raw_targets = [safe_sub(m) for m in params.members]
            else:
                raw_targets = [safe_sub(params.members)]

            targets = []
            for rt in raw_targets:
                try:
                    member = guild.get_member(int(rt))
                except ValueError:
                    raise ExecutionError(f"'{rt}' is not a valid ID.")
                if member is None:
                    if rt.isnumeric():
                        raise ExecutionError("The hackban feature is not yet available.") # TODO
                        #targets.append(ws.api.UnavailableMember(rt)) # hackban
                    else:
                        raise ExecutionError(f"'{rt}' is not a valid ID.")
                else:
                    targets.append(member)

            if params.author:
                ws_author = guild.get_member(int(safe_sub(params.author)))
                if ws_author is None:
                    raise ExecutionError(f"I could not find the author to issue the warning ({ws_author}).")
            else:
                ws_author = guild.me

            reason = safe_sub(params.reason) if params.reason else None

            try:
                await ws.api.warn(guild=guild, members=targets, author=ws_author, level=params.level, reason=reason,
                                time=params.time, date=params.date, ban_days=params.ban_days, log_modlog=params.log_modlog,
                                log_dm=params.log_dm, take_action=params.take_action, automod=params.automod)
            except Exception as e:
                raise ExecutionError(f"WarnSystem error: {e}")

        @processor(Action.NoOp)
        async def no_op(params: models.IsNone):
            pass

        if debug:
            for a in Action:
                if a not in processors:
                    raise ExecutionError(f"{a.value} does not have a processor.")

        self.last_action = action
        if debug and action not in ALLOWED_DEBUG_ACTIONS:
            return

        try:
            processor_func = processors[action]
        except KeyError:
            raise ExecutionError(f"Unhandled action '{action.value}'.")

        await processor_func(model)

        return runtime

    def __repr__(self):
        return f"<{self.__class__.__name__} '{self.name}'>"

class WardenCheck(WardenRule):
    """Warden Checks are groups of Warden based condition checks that the user can choose to implement
    for each Defender's module. They are evaluated in addition to a module's standard checks and allow for
    much greater control over the conditions under which a module should act.
    e.g. A user can decide that the Comment Analysis automodule should only function in channel A and B"""

    errors = {
        "CONDITIONS_ONLY": "Only conditions are allowed to be used in Warden checks.",
        "NOT_ALLOWED_IN_EVENTS": "Statement `{}` is not allowed in the checks for this module.",
    }

    async def parse(self, rule_str, cog: MixinMeta, module: ChecksKeys, author=None):
        self.raw_rule = rule_str

        try:
            rule = yaml.safe_load(rule_str)
        except:
            raise InvalidRule("Error parsing YAML. Please make sure the format "
                              "is valid (a YAML validator may help)")

        if not isinstance(rule, list):
            raise InvalidRule(f"Please review the format: checks should be a list of conditions")

        self.name = module.value

        self.cond_tree = await self.parse_tree(rule,
                                               cog=cog,
                                               author=author,
                                               events=[CHECKS_MODULES_EVENTS[module]],
                                               conditions_only=True)
        self.action_tree = {}
