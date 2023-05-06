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

import enum

class Event(enum.Enum):
    OnMessage = "on-message"
    OnMessageEdit = "on-message-edit"
    OnMessageDelete = "on-message-delete"
    OnReactionAdd = "on-reaction-add"
    OnReactionRemove = "on-reaction-remove"
    OnUserJoin = "on-user-join"
    OnUserLeave = "on-user-leave"
    OnRoleAdd = "on-role-add"
    OnRoleRemove = "on-role-remove"
    OnEmergency = "on-emergency"
    Manual = "manual"
    Periodic = "periodic"

class Action(enum.Enum):
    NotifyStaff = "notify-staff"
    BanAndDelete = "ban-user-and-delete" # Ban user in context and delete X days
    Kick = "kick-user" # Kick user in context
    Softban = "softban-user" # Softban user in context
    PunishUser = "punish-user" # Assign the punish role to the user
    PunishUserWithMessage = "punish-user-with-message" # Assign the punish role to the user and send the set message
    Modlog = "send-mod-log" # Send modlog case of last expel action + reason
    DeleteUserMessage = "delete-user-message" # Delete message in context
    SetChannelSlowmode = "set-channel-slowmode" # 0 - 6h
    AddRolesToUser = "add-roles-to-user" # Adds roles to user in context
    RemoveRolesFromUser = "remove-roles-from-user" # Remove roles from user in context
    EnableEmergencyMode = "enable-emergency-mode"
    SetUserNickname = "set-user-nickname" # Changes nickname of user in context
    NoOp = "no-op" # Does nothing. For testing purpose.
    SendToMonitor = "send-to-monitor" # Posts a message to [p]defender monitor
    AddUserHeatpoint = "add-user-heatpoint"
    AddUserHeatpoints = "add-user-heatpoints"
    AddChannelHeatpoint = "add-channel-heatpoint"
    AddChannelHeatpoints = "add-channel-heatpoints"
    AddCustomHeatpoint = "add-custom-heatpoint"
    AddCustomHeatpoints = "add-custom-heatpoints"
    EmptyUserHeat = "empty-user-heat"
    EmptyChannelHeat = "empty-channel-heat"
    EmptyCustomHeat = "empty-custom-heat"
    IssueCommand = "issue-command"
    DeleteLastMessageSentAfter = "delete-last-message-sent-after"
    SendMessage = "send-message" # Send a message to an arbitrary destination with an optional embed
    GetUserInfo = "get-user-info" # Get info of an arbitrary user
    Exit = "exit" # Stops processing the rule
    WarnSystemWarn = "warnsystem-warn" ## Warnsystem integration
    VarAssign = "var-assign" # Assigns a string to a variable
    VarAssignRandom = "var-assign-random" # Assigns a random string to a variable
    VarAssignHeat = "var-assign-heat" # Assign heat values to a variable
    VarMath = "var-math"
    VarReplace = "var-replace" # Replace var's str with substr
    VarSlice = "var-slice" # Slice a var
    VarSplit = "var-split" # Splits a string into substrings
    VarTransform = "var-transform" # Perform a variety of operations on the var

class Condition(enum.Enum):
    UserIdMatchesAny = "user-id-matches-any"
    UsernameMatchesAny = "username-matches-any"
    UsernameMatchesRegex = "username-matches-regex"
    NicknameMatchesAny = "nickname-matches-any"
    NicknameMatchesRegex = "nickname-matches-regex"
    MessageMatchesAny = "message-matches-any"
    MessageMatchesRegex = "message-matches-regex"
    MessageContainsWord = "message-contains-word"
    UserCreatedLessThan = "user-created-less-than"
    UserJoinedLessThan = "user-joined-less-than"
    UserActivityMatchesAny = "user-activity-matches-any"
    UserStatusMatchesAny = "user-status-matches-any"
    UserHasDefaultAvatar = "user-has-default-avatar"
    UserHasSentLessThanMessages = "user-has-sent-less-than-messages"
    ChannelMatchesAny = "channel-matches-any"
    CategoryMatchesAny = "category-matches-any"
    ChannelIsPublic = "channel-is-public"
    MessageHasAttachment = "message-has-attachment"
    InEmergencyMode = "in-emergency-mode"
    UserHasAnyRoleIn = "user-has-any-role-in"
    MessageContainsInvite = "message-contains-invite"
    MessageContainsMedia = "message-contains-media"
    MessageContainsUrl = "message-contains-url"
    MessageContainsMTMentions = "message-contains-more-than-mentions"
    MessageContainsMTUniqueMentions = "message-contains-more-than-unique-mentions"
    MessageContainsMTRolePings = "message-contains-more-than-role-pings"
    MessageContainsMTEmojis = "message-contains-more-than-emojis"
    MessageHasMTCharacters = "message-has-more-than-characters"
    UserIsRank = "user-is-rank"
    IsStaff = "is-staff"
    IsHelper = "is-helper"
    UserHeatIs = "user-heat-is"
    ChannelHeatIs = "channel-heat-is"
    UserHeatMoreThan = "user-heat-more-than"
    ChannelHeatMoreThan = "channel-heat-more-than"
    CustomHeatIs = "custom-heat-is"
    CustomHeatMoreThan = "custom-heat-more-than"
    Compare = "compare"

class ConditionBlock(enum.Enum):
    IfAll = "if-all"
    IfAny = "if-any"
    IfNot = "if-not"

class ConditionalActionBlock(enum.Enum):
    IfTrue = "if-true"
    IfFalse = "if-false"

class ChecksKeys(enum.Enum):
    CommentAnalysis = "ca"
    RaiderDetection = "raider_detection"
    InviteFilter = "invite_filter"
    JoinMonitor = "join_monitor"