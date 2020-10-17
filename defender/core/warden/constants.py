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

# The accepted types of each condition for basic sanity checking
CONDITIONS_PARAM_TYPE = {
    Condition.UsernameMatchesAny: [list],
    Condition.NicknameMatchesAny: [list],
    Condition.MessageMatchesAny: [list],
    Condition.UserCreatedLessThan: [int],
    Condition.UserJoinedLessThan: [int],
    Condition.UserHasDefaultAvatar: [bool],
    Condition.ChannelMatchesAny: [list],
    Condition.InEmergencyMode: [bool],
    Condition.MessageHasAttachment: [bool],
    Condition.UserHasAnyRoleIn: [list],
    Condition.MessageContainsInvite: [bool],
    Condition.MessageContainsMedia: [bool],
    Condition.MessageContainsMTMentions: [int],
    Condition.MessageContainsMTUniqueMentions: [int],
    Condition.IsStaff: [bool]
}

ACTIONS_PARAM_TYPE = {
    Action.Dm: [list],
    Action.DmUser: [str],
    Action.NotifyStaff: [str],
    Action.NotifyStaffAndPing: [str],
    Action.NotifyStaffWithEmbed: [list],
    Action.BanAndDelete: [int],
    Action.Softban: [None],
    Action.Kick: [None],
    Action.Modlog: [str],
    Action.DeleteUserMessage: [None],
    Action.SendInChannel: [str],
    Action.SetChannelSlowmode: [str],
    Action.AddRolesToUser: [list],
    Action.RemoveRolesFromUser: [list],
    Action.EnableEmergencyMode: [bool],
    Action.SetUserNickname: [str],
    Action.NoOp: [None],
    Action.SendToMonitor: [str],
    Action.SendToChannel: [list],
}

CONDITIONS_ANY_CONTEXT = [
    Condition.InEmergencyMode,
]

CONDITIONS_USER_CONTEXT = [
    Condition.UsernameMatchesAny,
    Condition.NicknameMatchesAny,
    Condition.UserCreatedLessThan,
    Condition.UserJoinedLessThan,
    Condition.UserHasDefaultAvatar,
    Condition.UserHasAnyRoleIn,
    Condition.IsStaff
]

CONDITIONS_MESSAGE_CONTEXT = [
    Condition.MessageMatchesAny,
    Condition.ChannelMatchesAny,
    Condition.MessageHasAttachment,
    Condition.MessageContainsInvite,
    Condition.MessageContainsMedia,
    Condition.MessageContainsMTMentions,
    Condition.MessageContainsMTUniqueMentions,
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
]

ACTIONS_USER_CONTEXT = [
    Action.DmUser,
    Action.BanAndDelete,
    Action.Softban,
    Action.Kick,
    Action.Modlog,
    Action.AddRolesToUser,
    Action.RemoveRolesFromUser,
    Action.SetUserNickname
]

ACTIONS_MESSAGE_CONTEXT = [
    Action.DeleteUserMessage,
    Action.SetChannelSlowmode,
    Action.SendInChannel
]

ALLOWED_CONDITIONS = {
    Event.OnMessage: [*CONDITIONS_ANY_CONTEXT, *CONDITIONS_MESSAGE_CONTEXT, *CONDITIONS_USER_CONTEXT],
    Event.OnMessageEdit: [*CONDITIONS_ANY_CONTEXT, *CONDITIONS_MESSAGE_CONTEXT, *CONDITIONS_USER_CONTEXT],
    Event.OnMessageDelete: [*CONDITIONS_ANY_CONTEXT, *CONDITIONS_MESSAGE_CONTEXT, *CONDITIONS_USER_CONTEXT],
    Event.OnUserJoin: [*CONDITIONS_ANY_CONTEXT, *CONDITIONS_USER_CONTEXT],
    Event.OnUserLeave: [*CONDITIONS_ANY_CONTEXT, *CONDITIONS_USER_CONTEXT],
    Event.OnEmergency: [*CONDITIONS_ANY_CONTEXT],
    Event.Manual: [*CONDITIONS_ANY_CONTEXT, *CONDITIONS_USER_CONTEXT]
}

ALLOWED_ACTIONS = {
    Event.OnMessage: [*ACTIONS_ANY_CONTEXT, *ACTIONS_MESSAGE_CONTEXT, *ACTIONS_USER_CONTEXT],
    Event.OnMessageEdit: [*ACTIONS_ANY_CONTEXT, *ACTIONS_MESSAGE_CONTEXT, *ACTIONS_USER_CONTEXT],
    Event.OnMessageDelete: [*ACTIONS_ANY_CONTEXT, *ACTIONS_MESSAGE_CONTEXT, *ACTIONS_USER_CONTEXT],
    Event.OnUserJoin: [*ACTIONS_ANY_CONTEXT, *ACTIONS_USER_CONTEXT],
    Event.OnUserLeave: [*ACTIONS_ANY_CONTEXT],
    Event.OnEmergency: [*ACTIONS_ANY_CONTEXT],
    Event.Manual: [*ACTIONS_ANY_CONTEXT, *ACTIONS_USER_CONTEXT]
}

# These are for special commands such as DM, which require
# a mandatory # of "arguments"
ACTIONS_ARGS_N = {
    Action.Dm: 2,
    Action.NotifyStaffWithEmbed: 2,
    Action.SendToChannel: 2,
}