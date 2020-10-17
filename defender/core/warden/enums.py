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

import enum

class Event(enum.Enum):
    OnMessage = "on-message"
    OnMessageEdit = "on-message-edit"
    OnMessageDelete = "on-message-delete"
    OnUserJoin = "on-user-join"
    OnUserLeave = "on-user-leave"
    OnEmergency = "on-emergency"
    Manual = "manual"

class Action(enum.Enum):
    Dm = "send-dm" #DM an arbitrary user. Must provide name/id + content
    DmUser = "dm-user" # DMs user in context
    NotifyStaff = "notify-staff"
    NotifyStaffAndPing = "notify-staff-and-ping"
    NotifyStaffWithEmbed = "notify-staff-with-embed"
    BanAndDelete = "ban-user-and-delete" # Ban user in context and delete X days
    Kick = "kick-user" # Kick user in context
    Softban = "softban-user" # Softban user in context
    Modlog = "send-mod-log" # Send modlog case of last expel action + reason
    DeleteUserMessage = "delete-user-message" # Delete message in context
    SendInChannel = "send-in-channel" # Send message to channel in context
    SetChannelSlowmode = "set-channel-slowmode" # 0 - 6h
    AddRolesToUser = "add-roles-to-user" # Adds roles to user in context
    RemoveRolesFromUser = "remove-roles-from-user" # Remove roles from user in context
    EnableEmergencyMode = "enable-emergency-mode"
    SetUserNickname = "set-user-nickname" # Changes nickname of user in context
    NoOp = "no-op" # Does nothing. For testing purpose.
    SendToMonitor = "send-to-monitor" # Posts a message to [p]defender monitor
    SendToChannel = "send-to-channel" # Sends a message to an arbitrary channel
    # TODO Heat system / Warnings?

class Condition(enum.Enum):
    UsernameMatchesAny = "username-matches-any"
    NicknameMatchesAny = "nickname-matches-any"
    MessageMatchesAny = "message-matches-any"
    UserCreatedLessThan = "user-created-less-than"
    UserJoinedLessThan = "user-joined-less-than"
    UserHasDefaultAvatar = "user-has-default-avatar"
    ChannelMatchesAny = "channel-matches-any"
    MessageHasAttachment = "message-has-attachment"
    InEmergencyMode = "in-emergency-mode"
    UserHasAnyRoleIn = "user-has-any-role-in"
    MessageContainsInvite = "message-contains-invite"
    MessageContainsMedia = "message-contains-media"
    MessageContainsMTMentions = "message-contains-more-than-mentions"
    MessageContainsMTUniqueMentions = "message-contains-more-than-unique-mentions"
    IsStaff = "is-staff"

class ConditionBlock(enum.Enum):
    IfAll = "if-all"
    IfAny = "if-any"
    IfNot = "if-not"