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

from defender.core.warden.validation import ALLOWED_CONDITIONS, ALLOWED_ACTIONS, ALLOWED_DEBUG_ACTIONS, model_validator
from defender.core.warden import validation as models
from ...enums import Rank, EmergencyMode, Action as ModAction
from .enums import Action, Condition, Event, ConditionBlock
from .checks import ACTIONS_SANITY_CHECK, CONDITIONS_SANITY_CHECK
from .utils import has_x_or_more_emojis, REMOVE_C_EMOJIS_RE, run_user_regex, make_fuzzy_suggestion, delete_message_after
from ...exceptions import InvalidRule, ExecutionError
from ...core import cache as df_cache
from ...core.utils import is_own_invite
from redbot.core.utils.common_filters import INVITE_URL_RE
from redbot.core.utils.chat_formatting import box
from redbot.core.commands.converter import parse_timedelta
from discord.ext.commands import BadArgument
from string import Template
from redbot.core import modlog
from typing import Optional
from pydantic import ValidationError
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
                    suggestion = make_fuzzy_suggestion(condition, [c.value for c in Condition])
                    raise InvalidRule(f"Invalid condition: `{condition}`.{suggestion}")

            if not is_condition_allowed_in_events(condition):
                raise InvalidRule(f"Condition `{condition.value}` not allowed in the event(s) you have defined.")

            try:
                model_validator(condition, parameter)
            except ValidationError as e:
                raise InvalidRule(f"Condition `{condition.value}` invalid:\n{box(str(e))}")

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

            for action, parameter in entry.items():
                try:
                    action = Action(action)
                except ValueError:
                    suggestion = make_fuzzy_suggestion(action, [a.value for a in Action])
                    raise InvalidRule(f"Invalid action: `{action}`.{suggestion}")

                if not is_action_allowed_in_events(action):
                    raise InvalidRule(f"Action `{action.value}` not allowed in the event(s) you have defined.")

                try:
                    model_validator(action, parameter)
                except ValidationError as e:
                    raise InvalidRule(f"Action `{action.value}` invalid:\n{box(str(e))}")

                if author:
                    try:
                        await ACTIONS_SANITY_CHECK[action](cog=cog, author=author, action=action, parameter=parameter)
                    except KeyError:
                        pass


    async def satisfies_conditions(self, *, rank: Optional[Rank], cog, user: discord.Member=None, message: discord.Message=None,
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
                results = await self._evaluate_conditions(value, cog=cog, user=user, message=message, guild=guild, debug=debug)
                if len(results) != len(value):
                    raise RuntimeError("Mismatching number of conditions and evaluations")
                cr.add_condition_block(condition, value, results) # type: ignore
                cond_result = all(results)
            elif condition == ConditionBlock.IfAny:
                results = await self._evaluate_conditions(value, cog=cog, user=user, message=message, guild=guild, debug=debug)
                if len(results) != len(value):
                    raise RuntimeError("Mismatching number of conditions and evaluations")
                cr.add_condition_block(condition, value, results) # type: ignore
                cond_result = any(results)
            elif condition == ConditionBlock.IfNot:
                results = await self._evaluate_conditions(value, cog=cog, user=user, message=message, guild=guild, debug=debug)
                if len(results) != len(value):
                    raise RuntimeError("Mismatching number of conditions and evaluations")
                cr.add_condition_block(condition, value, results) # type: ignore
                results = [not r for r in results] # Bools are flipped
                cond_result = all(results)
            else:
                results = await self._evaluate_conditions([{condition: value}], cog=cog, user=user, message=message, guild=guild, debug=debug)
                if len(results) != 1:
                    raise RuntimeError(f"A single condition evaluation returned {len(results)} evaluations!")
                cr.add_condition(condition, results[0]) # type: ignore
                cond_result = results[0]

            if cond_result is False:
                return cr # If one root condition is False there's no need to continue

        cr.result = True
        return cr

    async def _evaluate_conditions(self, conditions, *, cog, user: discord.Member=None, message: discord.Message=None,
                                   guild: discord.Guild=None, debug):
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
                bools.append(heat.get_user_heat(user, debug=debug) == value)
            elif condition == Condition.ChannelHeatIs:
                bools.append(heat.get_channel_heat(channel, debug=debug) == value)
            elif condition == Condition.CustomHeatIs:
                heat_key = Template(value[0]).safe_substitute(templates_vars)
                bools.append(heat.get_custom_heat(guild, heat_key, debug=debug) == value[1])
            elif condition == Condition.UserHeatMoreThan:
                bools.append(heat.get_user_heat(user, debug=debug) > value) # type: ignore
            elif condition == Condition.ChannelHeatMoreThan:
                bools.append(heat.get_channel_heat(channel, debug=debug) > value) # type: ignore
            elif condition == Condition.CustomHeatMoreThan:
                heat_key = Template(value[0]).safe_substitute(templates_vars)
                bools.append(heat.get_custom_heat(guild, heat_key, debug=debug) > value[1])

        return bools

    async def do_actions(self, *, cog, user: discord.Member=None, message: discord.Message=None,
                         guild: discord.Guild=None, debug=False):
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
            "user_heat": heat.get_user_heat(user, debug=debug),
            "user_avatar_url": user.avatar_url
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
            templates_vars["channel_heat"] = heat.get_channel_heat(channel, debug=debug)

        def safe_sub(string):
            if string == discord.Embed.Empty:
                return string
            return Template(string).safe_substitute(templates_vars)

        #for heat_key in heat.get_custom_heat_keys(guild):
        #    templates_vars[f"custom_heat_{heat_key}"] = heat.get_custom_heat(guild, heat_key)

        last_sent_message: Optional[discord.Message] = None
        last_expel_action = None

        processors = {}

        def processor(action: Action):
            def decorator(function):
                processors[action] = function
                def wrapper(*args, **kwargs):
                    return function(*args, **kwargs)
                return wrapper
            return decorator

        @processor(Action.DeleteUserMessage)
        async def delete_user_message(params: models.IsNone):
            await message.delete()

        @processor(Action.Dm)
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

        @processor(Action.DmUser)
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
        async def notify_staff(params: models.IsStr):
            nonlocal last_sent_message
            text = Template(params.value).safe_substitute(templates_vars)
            last_sent_message = await cog.send_notification(guild, text, allow_everyone_ping=True,
                                                            force_text_only=True)

        @processor(Action.NotifyStaffAndPing)
        async def notify_staff_and_ping(params: models.IsStr):
            nonlocal last_sent_message
            text = Template(params.value).safe_substitute(templates_vars)
            last_sent_message = await cog.send_notification(guild, text, ping=True, allow_everyone_ping=True,
                                                            force_text_only=True)

        @processor(Action.NotifyStaffWithEmbed)
        async def notify_staff_with_embed(params: models.NotifyStaffWithEmbed):
            nonlocal last_sent_message
            title = Template(params.title).safe_substitute(templates_vars)
            content = Template(params.content).safe_substitute(templates_vars)
            last_sent_message = await cog.send_notification(guild, content,
                                                            title=title, footer=f"Warden rule `{self.name}`",
                                                            allow_everyone_ping=True)

        @processor(Action.SendInChannel)
        async def send_in_channel(params: models.IsStr):
            nonlocal last_sent_message
            text = Template(params.value).safe_substitute(templates_vars)
            last_sent_message = await channel.send(text, allowed_mentions=ALLOW_ALL_MENTIONS)

        @processor(Action.SetChannelSlowmode)
        async def set_channel_slowmode(params: models.IsTimedelta):
            await channel.edit(slowmode_delay=params.value.seconds)

        @processor(Action.SendToChannel)
        async def send_to_channel(params: models.SendMessageToChannel):
            nonlocal last_sent_message
            channel_dest = guild.get_channel(params.id_or_name)
            if not channel_dest:
                channel_dest = discord.utils.get(guild.text_channels, name=params.id_or_name)
            if not channel_dest:
                raise ExecutionError(f"Channel '{params._id_or_name}' not found.")
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
            last_expel_action = Action.Kick
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
            issuer = guild.get_member(params.id)
            if issuer is None:
                raise ExecutionError(f"User {params.id} is not in the server.")
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
            msg_obj.content = prefix[0] + Template(params.command).safe_substitute(templates_vars)
            cog.bot.dispatch("message", msg_obj)

        @processor(Action.DeleteLastMessageSentAfter)
        async def delete_last_message_sent_after(params: models.IsTimedelta):
            nonlocal last_sent_message
            if last_sent_message is not None:
                cog.loop.create_task(delete_message_after(last_sent_message, params.value.seconds))
                last_sent_message = None

        @processor(Action.Send)
        async def send(params: models.Send):
            nonlocal last_sent_message
            default_values = 0

            for key in params.dict():
                attr = getattr(params, key)
                if attr is None:
                    default_values += 1
                    setattr(params, key, discord.Embed.Empty)
                elif isinstance(attr, str):
                    setattr(params, key, safe_sub(attr))

            try:
                params.id = int(params.id)
            except ValueError:
                raise ExecutionError(f"[Warden] ({self.name}): Failed to send message, "
                                     "no valid id.")

            is_user = False
            destination = guild.get_channel(params.id)
            if destination is None:
                destination = guild.get_member(params.id)
                if destination is None:
                    cog.send_to_monitor(guild, f"[Warden] ({self.name}): Failed to send message, "
                                                f"I could not find the recipient.")
                    return
                else:
                    is_user = True

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
                    em.add_field(name=field.name,
                                value=field.value,
                                inline=field.inline)
                if params.add_timestamp:
                    em.timestamp = utcnow()

                if params.color is True:
                    em.color = await cog.bot.get_embed_color(destination)
                elif not params.color:
                    pass
                else:
                    em.color = discord.Colour(params.color)

            mentions = discord.AllowedMentions(everyone=params.allow_mass_mentions, roles=True, users=True)

            try:
                last_sent_message = await destination.send(params.content, embed=em, allowed_mentions=mentions)
            except (discord.HTTPException, discord.Forbidden) as e:
                # A user could just have DMs disabled
                if is_user is False:
                    raise ExecutionError(f"[Warden] ({self.name}): Failed to deliver message "
                                         f"to channel #{destination}")

        @processor(Action.NoOp)
        async def no_op(params: models.IsNone):
            pass

        if debug:
            for action in Action:
                if action not in processors:
                    raise ExecutionError(f"{action.value} does not have a processor.")

        for entry in self.actions:
            for action, value in entry.items():
                action = Action(action)
                self.last_action = action
                if debug and action not in ALLOWED_DEBUG_ACTIONS:
                    continue
                params = model_validator(action, value)
                try:
                    processor_func = processors[action]
                except KeyError:
                    raise ExecutionError(f"Unhandled action '{action.value}'.")

                await processor_func(params)

        return bool(last_expel_action)

    def __repr__(self):
        return f"<WardenRule '{self.name}'>"
