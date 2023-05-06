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

from .enums import Action, Condition, Event
from typing import List, Union, Optional, Dict
from redbot.core.commands.converter import parse_timedelta, BadArgument
from pydantic import BaseModel as PydanticBaseModel, conlist, validator, root_validator, conint
from pydantic import ValidationError, ExtraError
from pydantic.error_wrappers import ErrorWrapper
from datetime import timedelta, datetime
from ...exceptions import InvalidRule
import logging
import string
import discord

VALID_VAR_NAME_CHARS = string.ascii_letters + string.digits + "_"

log = logging.getLogger("red.x26cogs.defender")

class BaseModel(PydanticBaseModel):
    _single_value = False
    _short_form = ()
    class Config:
        extra = "forbid"
        allow_reuse = True
        allow_mutation = False

    async def _runtime_check(self, *, cog, author: discord.Member, action_or_cond: Union[Action, Condition]):
        raise NotImplementedError

#
#   VALIDATORS
#

class HeatKey(str):
    """
    Custom heat key restriction
    """
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        v = str(v)
        if v.startswith("core-"):
            raise TypeError("The custom heatpoint's key cannot start with 'core-': "
                            "this is reserved for internal use.")
        return v

    def __repr__(self):
        return f"HeatKey({super().__repr__()})"

class AlphaNumeric(str):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        v = str(v)
        for char in v:
            if char not in VALID_VAR_NAME_CHARS:
                raise TypeError(f"Invalid variable name. It can only contain "
                                "letters, numbers and underscores.")
        return v

    def __repr__(self):
        return f"AlphaNumeric({super().__repr__()})"

class TimeDelta(str):
    """
    Valid Red timedelta
    """
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        return cls.parse_td(v)

    @classmethod
    def parse_td(cls, v, min=None, max=None):
        if not isinstance(v, str):
            raise TypeError("Not a valid timedelta")
        try:
            td = parse_timedelta(v, minimum=min, maximum=max)
        except BadArgument as e:
            raise TypeError(f"{e}")
        if td is None:
            raise TypeError("Not a valid timedelta")
        return td

    def __repr__(self):
        return f"TimeDelta({super().__repr__()})"

class HTimeDelta(TimeDelta):
    """
    Restricted Timedelta for heatpoints
    """
    @classmethod
    def validate(cls, v):
        return cls.parse_td(v, min=timedelta(seconds=1), max=timedelta(hours=24))

class SlowmodeTimeDelta(TimeDelta):
    """
    Restricted Timedelta for slowmode
    """
    @classmethod
    def validate(cls, v):
        return cls.parse_td(v, min=timedelta(seconds=0), max=timedelta(hours=6))

class DeleteLastMessageSentAfterTimeDelta(TimeDelta):
    """
    Restricted Timedelta for delete message after
    """
    @classmethod
    def validate(cls, v):
        return cls.parse_td(v, min=timedelta(seconds=1), max=timedelta(minutes=15))

#
#   MODELS
#

class CheckCustomHeatpoint(BaseModel):
    label: str
    points: int

class Compare(BaseModel):
    value1: str
    operator: str
    value2: str

    @validator("operator", allow_reuse=True)
    def check_empty_split(cls, v):
        allowed = ("==", "contains", "contains-pattern", ">=", "<=", "<", ">",
                   "!=")
        if isinstance(v, str):
            if v.lower() not in allowed:
                raise ValueError("Unknown operator")
        return v


class EmbedField(BaseModel):
    name: str
    value: str
    inline: Optional[bool]=True

class Message(BaseModel):
    channel_id: str
    message_id: str

class NotifyStaff(BaseModel):
    _short_form = ("content",)
    content: str
    title: Optional[str]
    fields: Optional[List[EmbedField]]=[]
    add_ctx_fields: Optional[bool]
    thumbnail: Optional[str]
    footer_text: Optional[str]
    ping: Optional[bool]
    jump_to: Optional[Message]
    jump_to_ctx_message: Optional[bool]
    qa_target: Optional[str]
    qa_reason: Optional[str]
    no_repeat_for: Optional[TimeDelta]
    no_repeat_key: Optional[str]
    allow_everyone_ping: Optional[bool]=False

    @root_validator(pre=False, allow_reuse=True)
    def check_jump_to(cls, values):
        if values["jump_to_ctx_message"] is True and values["jump_to"]:
            raise ValueError('You cannot specify a message to jump to while also choosing '
                             'the option to jump to the context\'s message.')

        return values

class AddCustomHeatpoint(BaseModel):
    label: HeatKey
    delta: HTimeDelta

class AddCustomHeatpoints(BaseModel):
    label: HeatKey
    points: conint(gt=0, le=100)
    delta: HTimeDelta

class AddHeatpoints(BaseModel):
    points: conint(gt=0, le=100)
    delta: HTimeDelta

class IssueCommand(BaseModel):
    _short_form = ("issue_as", "command")
    issue_as: int
    command: str
    destination: Optional[str]=None

    async def _runtime_check(self, *, cog, author: discord.Member, action_or_cond: Union[Action, Condition]):
        if self.issue_as != author.id:
            raise InvalidRule(f"`{action_or_cond.value}` The first parameter must be your ID. For security reasons "
                               "you're not allowed to issue commands as other users.")

class SendMessage(BaseModel):
    class Config(PydanticBaseModel.Config):
        allow_mutation = True # This being immutable is such a pita that I'd rather take the performance hit of a .copy() :-)
    _short_form = ("id", "content")
    # Used internally to determine whether an embed has to be sent
    # If any key other than these ones is passed an embed will be sent
    _text_only_attrs = ("id", "content", "allow_mass_mentions", "ping_on_reply",
                        "reply_message_id", "edit_message_id", "add_timestamp")
    id: str # or context variable
    content: Optional[str]=""
    description: Optional[str]=None
    title: Optional[str]=None
    fields: Optional[List[EmbedField]]=[]
    footer_text: Optional[str]=None
    footer_icon_url: Optional[str]=None
    thumbnail: Optional[str]=None
    author_name: Optional[str]=None
    author_url: Optional[str]=None
    author_icon_url: Optional[str]=None
    image: Optional[str]=None
    url: Optional[str]=None
    color: Optional[Union[bool, int]]=True
    add_timestamp: Optional[bool]=False
    allow_mass_mentions: Optional[bool]=False
    ping_on_reply: Optional[bool]=False
    reply_message_id: Optional[str]=None
    edit_message_id: Optional[str]=None

class GetUserInfo(BaseModel):
    id: str # or context variable
    mapping: Dict[str, str]

class WarnSystemWarn(BaseModel):
    _short_form = ("members", "level", "reason", "time")
    members: Union[str, conlist(str, min_items=1)]
    author: Optional[str]
    level: conint(ge=1, le=5)
    reason: Optional[str]
    time: Optional[TimeDelta]
    date: Optional[datetime]
    ban_days: Optional[int]
    log_modlog: Optional[bool]=True
    log_dm: Optional[bool]=True
    take_action: Optional[bool]=True
    automod: Optional[bool]=True

class VarAssign(BaseModel):
    var_name: AlphaNumeric
    value: str
    evaluate: bool=False

class VarAssignRandom(BaseModel):
    var_name: str
    choices: Union[List[str], Dict[str, int]]
    evaluate: bool=False

    @validator("choices", allow_reuse=True)
    def check_empty(cls, v):
        if len(v) == 0:
            raise ValueError("Choices cannot be empty")
        return v

class VarAssignHeat(BaseModel):
    var_name: AlphaNumeric
    heat_label: str

class VarReplace(BaseModel):
    var_name: str
    strings: Union[List[str], str]
    substring: str

class VarMath(BaseModel):
    result_var: str
    operand1: str
    operator: str
    operand2: Optional[str]=None

class VarSplit(BaseModel):
    var_name: str
    separator: str
    split_into: List[str]
    max_split: Optional[int]=-1

    @validator("split_into", allow_reuse=True)
    def check_empty_split(cls, v):
        if len(v) == 0:
            raise ValueError("You must insert at least one variable")
        return v

class VarSlice(BaseModel):
    var_name: str
    index: Optional[int]
    end_index: Optional[int]
    slice_into: Optional[str]
    step: Optional[int]

class VarTransform(BaseModel):
    var_name: str
    operation: str

    @validator("operation", allow_reuse=True)
    def check_operation_allowed(cls, v):
        allowed = ("capitalize", "lowercase", "reverse", "uppercase", "title")
        if isinstance(v, str):
            if v.lower() not in allowed:
                raise ValueError("Unknown operation")
        return v

class NonEmptyList(BaseModel):
    _single_value = True
    value: conlist(Union[int, str], min_items=1)

class RolesList(NonEmptyList):
    async def _runtime_check(self, *, cog, author: discord.Member, action_or_cond: Union[Action, Condition]):
        guild = author.guild
        roles = []

        is_server_owner = author.id == guild.owner_id

        for role_id_or_name in self.value:
            role = guild.get_role(role_id_or_name)
            if role is None:
                role = discord.utils.get(guild.roles, name=role_id_or_name)
            if role is None:
                raise InvalidRule(f"`{action_or_cond.value}`: Role `{role_id_or_name}` doesn't seem to exist.")
            roles.append(role)

        if not is_server_owner:
            for r in roles:
                if r.position >= author.top_role.position:
                    raise InvalidRule(f"`{action_or_cond.value}` Cannot assign or remove role `{r.name}` through Warden. "
                                    "You are authorized to only add or remove roles below your top role.")

class NonEmptyListInt(BaseModel):
    _single_value = True
    value: conlist(int, min_items=1)

class NonEmptyListStr(BaseModel):
    _single_value = True
    value: conlist(str, min_items=1)

class StatusList(NonEmptyListStr):
    async def _runtime_check(self, *, cog, author: discord.Member, action_or_cond: Union[Action, Condition]):
        for status in self.value:
            try:
                discord.Status(status.lower())
            except ValueError:
                raise InvalidRule(f"`{action_or_cond.value}` Invalid status. The condition must contain one of "
                                "the following statuses: online, offline, idle, dnd.")

class IsStr(BaseModel):
    _single_value = True
    value: str

class IsRegex(IsStr):
    async def _runtime_check(self, *, cog, author: discord.Member, action_or_cond: Union[Action, Condition]):
        enabled: bool = await cog.config.wd_regex_allowed()
        if not enabled:
            raise InvalidRule(f"`{action_or_cond.value}` Regex use is globally disabled. The bot owner must use "
                            "`[p]dset warden regexallowed` to activate it.")

#
#   SINGLE VALUE MODELS
#

class UserJoinedCreated(BaseModel):
    _single_value = True
    value: Union[TimeDelta, int]

class IsInt(BaseModel):
    _single_value = True
    value: int

class IsBool(BaseModel):
    _single_value = True
    value: bool

class IsNone(BaseModel):
    _single_value = True
    value: None

class IsTimedelta(BaseModel):
    _single_value = True
    value: TimeDelta

class IsHTimedelta(BaseModel):
    _single_value = True
    value: HTimeDelta

class IsSlowmodeTimedelta(BaseModel):
    _single_value = True
    value: SlowmodeTimeDelta

    async def _runtime_check(self, *, cog, author: discord.Member, action_or_cond: Union[Action, Condition]):
        if not author.guild_permissions.manage_channels:
            raise InvalidRule(f"`{action_or_cond.value}` You need `manage channels` permissions to make a rule with "
                            "this action.")

class IsDeleteLastMessageSentAfterTimeDelta(BaseModel):
    _single_value = True
    value: DeleteLastMessageSentAfterTimeDelta

class IsRank(BaseModel):
    _single_value = True
    value: conint(ge=1, le=4)

# The accepted types of each condition for basic sanity checking
CONDITIONS_VALIDATORS = {
    Condition.UserIdMatchesAny: NonEmptyListInt,
    Condition.UsernameMatchesAny: NonEmptyListStr,
    Condition.UsernameMatchesRegex: IsRegex,
    Condition.NicknameMatchesAny: NonEmptyListStr,
    Condition.NicknameMatchesRegex: IsRegex,
    Condition.MessageMatchesAny: NonEmptyListStr,
    Condition.MessageMatchesRegex: IsRegex,
    Condition.MessageContainsWord: NonEmptyListStr,
    Condition.UserCreatedLessThan: UserJoinedCreated,
    Condition.UserJoinedLessThan: UserJoinedCreated,
    Condition.UserActivityMatchesAny: NonEmptyListStr,
    Condition.UserStatusMatchesAny: StatusList,
    Condition.UserHasDefaultAvatar: IsBool,
    Condition.ChannelMatchesAny: NonEmptyList,
    Condition.CategoryMatchesAny: NonEmptyList,
    Condition.ChannelIsPublic: IsBool,
    Condition.InEmergencyMode: IsBool,
    Condition.MessageHasAttachment: IsBool,
    Condition.UserHasAnyRoleIn: NonEmptyList,
    Condition.UserHasSentLessThanMessages: IsInt,
    Condition.MessageContainsInvite: IsBool,
    Condition.MessageContainsMedia: IsBool,
    Condition.MessageContainsUrl: IsBool,
    Condition.MessageContainsMTMentions: IsInt,
    Condition.MessageContainsMTUniqueMentions: IsInt,
    Condition.MessageContainsMTRolePings: IsInt,
    Condition.MessageContainsMTEmojis: IsInt,
    Condition.MessageHasMTCharacters: IsInt,
    Condition.IsStaff: IsBool,
    Condition.IsHelper: IsBool,
    Condition.UserIsRank: IsRank,
    Condition.UserHeatIs: IsInt,
    Condition.UserHeatMoreThan: IsInt,
    Condition.ChannelHeatIs: IsInt,
    Condition.ChannelHeatMoreThan: IsInt,
    Condition.CustomHeatIs: CheckCustomHeatpoint,
    Condition.CustomHeatMoreThan: CheckCustomHeatpoint,
    Condition.Compare: Compare,
}

ACTIONS_VALIDATORS = {
    Action.NotifyStaff: NotifyStaff,
    Action.BanAndDelete: IsInt,
    Action.Softban: IsNone,
    Action.Kick: IsNone,
    Action.PunishUser: IsNone,
    Action.PunishUserWithMessage: IsNone,
    Action.Modlog: IsStr,
    Action.DeleteUserMessage: IsNone,
    Action.SetChannelSlowmode: IsSlowmodeTimedelta,
    Action.AddRolesToUser: RolesList,
    Action.RemoveRolesFromUser: RolesList,
    Action.EnableEmergencyMode: IsBool,
    Action.SetUserNickname: IsStr,
    Action.NoOp: IsNone,
    Action.SendToMonitor: IsStr,
    Action.AddUserHeatpoint: IsHTimedelta,
    Action.AddUserHeatpoints: AddHeatpoints,
    Action.AddChannelHeatpoint: IsHTimedelta,
    Action.AddChannelHeatpoints: AddHeatpoints,
    Action.AddCustomHeatpoint: AddCustomHeatpoint,
    Action.AddCustomHeatpoints: AddCustomHeatpoints,
    Action.EmptyUserHeat: IsNone,
    Action.EmptyChannelHeat: IsNone,
    Action.EmptyCustomHeat: IsStr,
    Action.IssueCommand: IssueCommand,
    Action.DeleteLastMessageSentAfter: IsDeleteLastMessageSentAfterTimeDelta,
    Action.SendMessage: SendMessage,
    Action.GetUserInfo: GetUserInfo,
    Action.Exit: IsNone,
    Action.WarnSystemWarn: WarnSystemWarn,
    Action.VarAssign: VarAssign,
    Action.VarAssignRandom: VarAssignRandom,
    Action.VarAssignHeat: VarAssignHeat,
    Action.VarReplace: VarReplace,
    Action.VarMath: VarMath,
    Action.VarSlice: VarSlice,
    Action.VarSplit: VarSplit,
    Action.VarTransform: VarTransform,
}

CONDITIONS_ANY_CONTEXT = [
    Condition.InEmergencyMode,
    Condition.Compare,
    Condition.CustomHeatIs,
    Condition.CustomHeatMoreThan,
]

CONDITIONS_USER_CONTEXT = [
    Condition.UserIdMatchesAny,
    Condition.UsernameMatchesAny,
    Condition.UsernameMatchesRegex,
    Condition.NicknameMatchesAny,
    Condition.NicknameMatchesRegex,
    Condition.UserActivityMatchesAny,
    Condition.UserStatusMatchesAny,
    Condition.UserCreatedLessThan,
    Condition.UserJoinedLessThan,
    Condition.UserHasDefaultAvatar,
    Condition.UserHasAnyRoleIn,
    Condition.UserHasSentLessThanMessages,
    Condition.IsStaff,
    Condition.IsHelper,
    Condition.UserIsRank,
    Condition.UserHeatIs,
    Condition.UserHeatMoreThan,
]

CONDITIONS_MESSAGE_CONTEXT = [
    Condition.MessageMatchesAny,
    Condition.MessageMatchesRegex,
    Condition.MessageContainsWord,
    Condition.ChannelMatchesAny,
    Condition.CategoryMatchesAny,
    Condition.ChannelIsPublic,
    Condition.ChannelHeatIs,
    Condition.ChannelHeatMoreThan,
    Condition.MessageHasAttachment,
    Condition.MessageContainsInvite,
    Condition.MessageContainsMedia,
    Condition.MessageContainsUrl,
    Condition.MessageContainsMTMentions,
    Condition.MessageContainsMTUniqueMentions,
    Condition.MessageContainsMTRolePings,
    Condition.MessageContainsMTEmojis,
    Condition.MessageHasMTCharacters,
]

ACTIONS_ANY_CONTEXT = [
    Action.NotifyStaff,
    Action.NoOp,
    Action.SendToMonitor,
    Action.EnableEmergencyMode,
    Action.IssueCommand,
    Action.AddCustomHeatpoint,
    Action.AddCustomHeatpoints,
    Action.EmptyCustomHeat,
    Action.DeleteLastMessageSentAfter,
    Action.SendMessage,
    Action.GetUserInfo,
    Action.Exit,
    Action.WarnSystemWarn,
    Action.VarAssign,
    Action.VarAssignRandom,
    Action.VarAssignHeat,
    Action.VarMath,
    Action.VarReplace,
    Action.VarSlice,
    Action.VarSplit,
    Action.VarTransform,
]

ACTIONS_USER_CONTEXT = [
    Action.BanAndDelete,
    Action.Softban,
    Action.Kick,
    Action.PunishUser,
    Action.Modlog,
    Action.AddRolesToUser,
    Action.RemoveRolesFromUser,
    Action.SetUserNickname,
    Action.AddUserHeatpoint,
    Action.AddUserHeatpoints,
    Action.EmptyUserHeat,
]

ACTIONS_MESSAGE_CONTEXT = [
    Action.DeleteUserMessage,
    Action.SetChannelSlowmode,
    Action.AddChannelHeatpoint,
    Action.AddChannelHeatpoints,
    Action.EmptyChannelHeat,
    Action.PunishUserWithMessage,
]

ALLOWED_STATEMENTS = {
    Event.OnMessage: [*CONDITIONS_ANY_CONTEXT, *CONDITIONS_MESSAGE_CONTEXT, *CONDITIONS_USER_CONTEXT,
                      *ACTIONS_ANY_CONTEXT, *ACTIONS_MESSAGE_CONTEXT, *ACTIONS_USER_CONTEXT],
    Event.OnMessageEdit: [*CONDITIONS_ANY_CONTEXT, *CONDITIONS_MESSAGE_CONTEXT, *CONDITIONS_USER_CONTEXT,
                          *ACTIONS_ANY_CONTEXT, *ACTIONS_MESSAGE_CONTEXT, *ACTIONS_USER_CONTEXT],
    Event.OnMessageDelete: [*CONDITIONS_ANY_CONTEXT, *CONDITIONS_MESSAGE_CONTEXT, *CONDITIONS_USER_CONTEXT,
                            *ACTIONS_ANY_CONTEXT, *ACTIONS_MESSAGE_CONTEXT, *ACTIONS_USER_CONTEXT],
    Event.OnReactionAdd: [*CONDITIONS_ANY_CONTEXT, *CONDITIONS_MESSAGE_CONTEXT, *CONDITIONS_USER_CONTEXT,
                          *ACTIONS_ANY_CONTEXT, *ACTIONS_MESSAGE_CONTEXT, *ACTIONS_USER_CONTEXT],
    Event.OnReactionRemove: [*CONDITIONS_ANY_CONTEXT, *CONDITIONS_MESSAGE_CONTEXT, *CONDITIONS_USER_CONTEXT,
                            *ACTIONS_ANY_CONTEXT, *ACTIONS_MESSAGE_CONTEXT, *ACTIONS_USER_CONTEXT],
    Event.OnUserJoin: [*CONDITIONS_ANY_CONTEXT, *CONDITIONS_USER_CONTEXT,
                       *ACTIONS_ANY_CONTEXT, *ACTIONS_USER_CONTEXT],
    Event.OnUserLeave: [*CONDITIONS_ANY_CONTEXT, *CONDITIONS_USER_CONTEXT,
                        *ACTIONS_ANY_CONTEXT, *ACTIONS_USER_CONTEXT],
    Event.OnRoleAdd: [*CONDITIONS_ANY_CONTEXT, *CONDITIONS_USER_CONTEXT,
                        *ACTIONS_ANY_CONTEXT, *ACTIONS_USER_CONTEXT],
    Event.OnRoleRemove: [*CONDITIONS_ANY_CONTEXT, *CONDITIONS_USER_CONTEXT,
                        *ACTIONS_ANY_CONTEXT, *ACTIONS_USER_CONTEXT],
    Event.OnEmergency: [*CONDITIONS_ANY_CONTEXT,
                        *ACTIONS_ANY_CONTEXT],
    Event.Manual: [*CONDITIONS_ANY_CONTEXT, *CONDITIONS_USER_CONTEXT,
                   *ACTIONS_ANY_CONTEXT, *ACTIONS_USER_CONTEXT],
    Event.Periodic: [*CONDITIONS_ANY_CONTEXT, *CONDITIONS_USER_CONTEXT,
                     *ACTIONS_ANY_CONTEXT, *ACTIONS_USER_CONTEXT],
}

ALLOWED_DEBUG_ACTIONS = [
    Action.AddUserHeatpoint,
    Action.AddUserHeatpoints,
    Action.AddChannelHeatpoint,
    Action.AddChannelHeatpoints,
    Action.AddCustomHeatpoint,
    Action.AddCustomHeatpoints,
    Action.EmptyUserHeat,
    Action.EmptyChannelHeat,
    Action.EmptyCustomHeat,
]

DEPRECATED = []

def model_validator(action_or_cond: Union[Action, Condition], parameter: Union[list, dict, str, int, bool])->BaseModel:
    """
    In Warden it's possible to pass arguments in "Long form" and "Short form"
    Long form is a dict, and we can simply validate it against its model
    Short form is a list that we unpack "on top" of the model, akin to the concept of positional arguments

    Short form would of course be prone to easily break if I were to change the order of the attributes
    in the model, so I have added the optional attribute "_short_form" to enforce an exact order
    Additionally, the "_single_value" attribute denotes models for which their parameters should never be unpacked
    on top of, such as models with a single list as an attribute. For these models long form is not allowed.
    """
    try:
        validator = ACTIONS_VALIDATORS[action_or_cond] # type: ignore
    except KeyError:
        validator = CONDITIONS_VALIDATORS[action_or_cond] # type: ignore

    # Long form
    if not validator._single_value and isinstance(parameter, dict):
        return validator(**parameter)

    # Short form
    if not validator._short_form:
        validator._short_form = [k for k in validator.schema()['properties']]

    args = {}
    if validator._single_value is False:
        if isinstance(parameter, list):
            if len(parameter) > len(validator._short_form):
                raise ValidationError([ErrorWrapper(ExtraError(), loc="Short form")], validator)
            params = parameter
        else:
            params = (parameter,)

        for i, attr in enumerate(validator._short_form):
            try:
                args[attr] = params[i]
            except IndexError:
                pass
    else:
        args[validator._short_form[0]] = parameter

    return validator(**args)
