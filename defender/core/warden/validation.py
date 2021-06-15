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

from .enums import Action, Condition, Event
from typing import Union
from pydantic import BaseModel, conlist

######### CONDITION VALIDATORS #########

class CheckCustomHeatpoint(BaseModel):
    label: str
    points: int

######### ACTION VALIDATORS #########

class SendMessageToDestination(BaseModel):
    _id: int
    content: str

class NotifyStaffWithEmbed(BaseModel):
    title: str
    content: str

class AddCustomHeatpoint(BaseModel):
    label: str
    delta: str

class AddCustomHeatpoints(BaseModel):
    label: str
    points: int
    delta: str

class AddHeatpoints(BaseModel):
    points: int
    delta: str

class IssueCommand(BaseModel):
    _id: int
    command: str

######### MIXED VALIDATORS  #########

class NonEmptyList(BaseModel):
    value: conlist(Union[str, int], min_items=1)

class NonEmptyListInt(BaseModel):
    value: conlist(int, min_items=1)

class NonEmptyListStr(BaseModel):
    value: conlist(str, min_items=1)

class IsStr(BaseModel):
    value: str

class IsInt(BaseModel):
    value: int

class IsBool(BaseModel):
    value: bool

class IsNone(BaseModel):
    value: None

# The accepted types of each condition for basic sanity checking
CONDITIONS_VALIDATORS = {
    Condition.UserIdMatchesAny: NonEmptyListInt,
    Condition.UsernameMatchesAny: NonEmptyListStr,
    Condition.UsernameMatchesRegex: IsStr,
    Condition.NicknameMatchesAny: NonEmptyListStr,
    Condition.NicknameMatchesRegex: IsStr,
    Condition.MessageMatchesAny: NonEmptyListStr,
    Condition.MessageMatchesRegex: IsStr,
    Condition.UserCreatedLessThan: IsInt,
    Condition.UserJoinedLessThan: IsInt,
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
    Condition.UserIsRank: IsInt,
    Condition.UserHeatIs: IsInt,
    Condition.UserHeatMoreThan: IsInt,
    Condition.ChannelHeatIs: IsInt,
    Condition.ChannelHeatMoreThan: IsInt,
    Condition.CustomHeatIs: CheckCustomHeatpoint,
    Condition.CustomHeatMoreThan: CheckCustomHeatpoint,
}

ACTIONS_VALIDATORS = {
    Action.Dm: SendMessageToDestination,
    Action.DmUser: IsStr,
    Action.NotifyStaff: IsStr,
    Action.NotifyStaffAndPing: IsStr,
    Action.NotifyStaffWithEmbed: NotifyStaffWithEmbed,
    Action.BanAndDelete: IsInt,
    Action.Softban: IsNone,
    Action.Kick: IsNone,
    Action.PunishUser: IsNone,
    Action.PunishUserWithMessage: IsNone,
    Action.Modlog: IsStr,
    Action.DeleteUserMessage: IsNone,
    Action.SendInChannel: IsStr,
    Action.SetChannelSlowmode: IsStr,
    Action.AddRolesToUser: NonEmptyList,
    Action.RemoveRolesFromUser: NonEmptyList,
    Action.EnableEmergencyMode: IsBool,
    Action.SetUserNickname: IsStr,
    Action.NoOp: IsNone,
    Action.SendToMonitor: IsStr,
    Action.SendToChannel: SendMessageToDestination,
    Action.AddUserHeatpoint: IsStr,
    Action.AddUserHeatpoints: AddHeatpoints,
    Action.AddChannelHeatpoint: IsStr, # TODO Timedelta check?
    Action.AddChannelHeatpoints: AddHeatpoints,
    Action.AddCustomHeatpoint: AddCustomHeatpoint,
    Action.AddCustomHeatpoints: AddCustomHeatpoints,
    Action.EmptyUserHeat: IsNone,
    Action.EmptyChannelHeat: IsNone,
    Action.EmptyCustomHeat: IsStr,
    Action.IssueCommand: IssueCommand,
    Action.DeleteLastMessageSentAfter: IsStr,
}

CONDITIONS_ANY_CONTEXT = [
    Condition.InEmergencyMode,
]

CONDITIONS_USER_CONTEXT = [
    Condition.UserIdMatchesAny,
    Condition.UsernameMatchesAny,
    Condition.UsernameMatchesRegex,
    Condition.NicknameMatchesAny,
    Condition.NicknameMatchesRegex,
    Condition.UserCreatedLessThan,
    Condition.UserJoinedLessThan,
    Condition.UserHasDefaultAvatar,
    Condition.UserHasAnyRoleIn,
    Condition.UserHasSentLessThanMessages,
    Condition.IsStaff,
    Condition.UserIsRank,
    Condition.UserHeatIs,
    Condition.UserHeatMoreThan,
    Condition.CustomHeatIs,
    Condition.CustomHeatMoreThan,
]

CONDITIONS_MESSAGE_CONTEXT = [
    Condition.MessageMatchesAny,
    Condition.MessageMatchesRegex,
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
    Action.Dm,
    Action.NotifyStaff,
    Action.NotifyStaffAndPing,
    Action.NotifyStaffWithEmbed,
    Action.NoOp,
    Action.SendToMonitor,
    Action.EnableEmergencyMode,
    Action.SendToChannel,
    Action.IssueCommand,
    Action.AddCustomHeatpoint,
    Action.AddCustomHeatpoints,
    Action.EmptyCustomHeat,
    Action.DeleteLastMessageSentAfter,
]

ACTIONS_USER_CONTEXT = [
    Action.DmUser,
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
    Action.SendInChannel,
    Action.AddChannelHeatpoint,
    Action.AddChannelHeatpoints,
    Action.EmptyChannelHeat,
    Action.PunishUserWithMessage,
]

ALLOWED_CONDITIONS = {
    Event.OnMessage: [*CONDITIONS_ANY_CONTEXT, *CONDITIONS_MESSAGE_CONTEXT, *CONDITIONS_USER_CONTEXT],
    Event.OnMessageEdit: [*CONDITIONS_ANY_CONTEXT, *CONDITIONS_MESSAGE_CONTEXT, *CONDITIONS_USER_CONTEXT],
    Event.OnMessageDelete: [*CONDITIONS_ANY_CONTEXT, *CONDITIONS_MESSAGE_CONTEXT, *CONDITIONS_USER_CONTEXT],
    Event.OnUserJoin: [*CONDITIONS_ANY_CONTEXT, *CONDITIONS_USER_CONTEXT],
    Event.OnUserLeave: [*CONDITIONS_ANY_CONTEXT, *CONDITIONS_USER_CONTEXT],
    Event.OnEmergency: [*CONDITIONS_ANY_CONTEXT],
    Event.Manual: [*CONDITIONS_ANY_CONTEXT, *CONDITIONS_USER_CONTEXT],
    Event.Periodic: [*CONDITIONS_ANY_CONTEXT, *CONDITIONS_USER_CONTEXT],
}

ALLOWED_ACTIONS = {
    Event.OnMessage: [*ACTIONS_ANY_CONTEXT, *ACTIONS_MESSAGE_CONTEXT, *ACTIONS_USER_CONTEXT],
    Event.OnMessageEdit: [*ACTIONS_ANY_CONTEXT, *ACTIONS_MESSAGE_CONTEXT, *ACTIONS_USER_CONTEXT],
    Event.OnMessageDelete: [*ACTIONS_ANY_CONTEXT, *ACTIONS_MESSAGE_CONTEXT, *ACTIONS_USER_CONTEXT],
    Event.OnUserJoin: [*ACTIONS_ANY_CONTEXT, *ACTIONS_USER_CONTEXT],
    Event.OnUserLeave: [*ACTIONS_ANY_CONTEXT],
    Event.OnEmergency: [*ACTIONS_ANY_CONTEXT],
    Event.Manual: [*ACTIONS_ANY_CONTEXT, *ACTIONS_USER_CONTEXT],
    Event.Periodic: [*ACTIONS_ANY_CONTEXT, *ACTIONS_USER_CONTEXT],
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