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

class EmergencyMode:
    def __init__(self, *, manual):
        self.is_manual = manual # Manual mode won't automatically be disabled by staff activity

class Rank(enum.IntEnum):
    """Ranks of trust"""
    Rank1 = 1 # Trusted user. Has at least one of the roles defined in "trusted_roles" or is staff/admin
    Rank2 = 2 # User that satisfies all the requirements below
    Rank3 = 3 # User that joined <X days ago
    Rank4 = 4 # User that satisfies Rank3's requirement and also has less than X messages in the server

class Action(enum.Enum):
    NoAction = "none"
    Ban = "ban"
    Kick = "kick"
    Softban = "softban"

class EmergencyModules(enum.Enum):
    Voteout = "voteout"
    Vaporize = "vaporize"
    Silence = "silence"

class WardenEvent(enum.Enum):
    OnMessage = "on-message"
    OnUserJoin = "on-user-join"
    OnEmergency = "on-emergency"
    Manual = "manual"

class WardenAction(enum.Enum):
    Dm = "dm" #DM an arbitrary user. Must provide name/id + content
    DmUser = "dm-user" # DMs user in context
    NotifyStaff = "notify-staff"
    NotifyStaffAndPing = "notify-staff-and-ping"
    BanAndDelete = "ban-and-delete" # Ban user in context and delete X days
    Kick = Action.Kick.value # Kick user in context
    Softban = Action.Softban.value # Softban user in context
    Modlog = "send-mod-log" # Send modlog case of last expel action + reason
    DeleteUserMessage = "delete-user-message" # Delete message in context
    SendInChannel = "send-in-channel" # Send message to channel in context
    AddRolesToUser = "add-roles-to-user" # Adds roles to user in context
    RemoveRolesFromUser = "remove-roles-from-user" # Remove roles from user in context
    TriggerEmergencyMode = "trigger-emergency-mode"
    SetUserNickname = "set-user-nickname" # Changes nickname of user in context
    NoOp = "no-op" # Does nothing. For testing purpose.
    SendToMonitor = "send-to-monitor" # Posts a message to [p]df monitor
    # TODO Heat system / Warnings?

class WardenCondition(enum.Enum):
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