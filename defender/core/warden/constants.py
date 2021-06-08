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
    Condition.UserIdMatchesAny: [list],
    Condition.UsernameMatchesAny: [list],
    Condition.UsernameMatchesRegex: [str],
    Condition.NicknameMatchesAny: [list],
    Condition.NicknameMatchesRegex: [str],
    Condition.MessageMatchesAny: [list],
    Condition.MessageMatchesRegex: [str],
    Condition.UserCreatedLessThan: [int],
    Condition.UserJoinedLessThan: [int],
    Condition.UserHasDefaultAvatar: [bool],
    Condition.ChannelMatchesAny: [list],
    Condition.CategoryMatchesAny: [list],
    Condition.ChannelIsPublic: [bool],
    Condition.InEmergencyMode: [bool],
    Condition.MessageHasAttachment: [bool],
    Condition.UserHasAnyRoleIn: [list],
    Condition.UserHasSentLessThanMessages: [int],
    Condition.MessageContainsInvite: [bool],
    Condition.MessageContainsMedia: [bool],
    Condition.MessageContainsUrl: [bool],
    Condition.MessageContainsMTMentions: [int],
    Condition.MessageContainsMTUniqueMentions: [int],
    Condition.MessageContainsMTRolePings: [int],
    Condition.MessageContainsMTEmojis: [int],
    Condition.MessageHasMTCharacters: [int],
    Condition.IsStaff: [bool],
    Condition.UserIsRank: [int],
    Condition.UserHeatIs: [int],
    Condition.UserHeatMoreThan: [int],
    Condition.ChannelHeatIs: [int],
    Condition.ChannelHeatMoreThan: [int],
    Condition.CustomHeatIs: [list],
    Condition.CustomHeatMoreThan: [list],
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
    Action.AddUserHeatpoint: [str],
    Action.AddUserHeatpoints: [list],
    Action.AddChannelHeatpoint: [str],
    Action.AddChannelHeatpoints: [list],
    Action.AddCustomHeatpoint: [list],
    Action.AddCustomHeatpoints: [list],
    Action.EmptyUserHeat: [None],
    Action.EmptyChannelHeat: [None],
    Action.EmptyCustomHeat: [str],
    Action.IssueCommand: [list],
    Action.DeleteLastMessageSentAfter: [str],
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

CONDITIONS_ARGS_N = {
    Condition.CustomHeatIs: 2,
    Condition.CustomHeatMoreThan: 2,
}

# These are for special commands such as DM, which require
# a mandatory # of "arguments"
ACTIONS_ARGS_N = {
    Action.Dm: 2,
    Action.NotifyStaffWithEmbed: 2,
    Action.SendToChannel: 2,
    Action.AddUserHeatpoints: 2,
    Action.AddChannelHeatpoints: 2,
    Action.AddCustomHeatpoint: 2,
    Action.AddCustomHeatpoints: 3,
    Action.IssueCommand: 2,
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