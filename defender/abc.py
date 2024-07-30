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

from abc import ABC, abstractmethod
from typing import Optional
from redbot.core import Config, commands
from redbot.core.bot import Red
from .enums import Rank, EmergencyModules
from .core.warden.enums import Event as WardenEvent
from .core.warden.rule import WardenRule
from .core.utils import QuickAction
from typing import List, Dict
import datetime
import discord
import asyncio

class CompositeMetaClass(type(commands.Cog), type(ABC)):
    """
    This allows the metaclass used for proper type detection to
    coexist with discord.py's metaclass
    """
    pass

class MixinMeta(ABC):
    """
    Base class for well behaved type hint detection with composite class.
    Basically, to keep developers sane when not all attributes are defined in each mixin.
    """

    def __init__(self, *_args):
        self.config: Config
        self.bot: Red
        self.emergency_mode: dict
        self.active_warden_rules: dict
        self.invalid_warden_rules: dict
        self.warden_checks: dict
        self.joined_users: dict
        self.monitor: dict
        self.loop: asyncio.AbstractEventLoop
        self.quick_actions: Dict[int, Dict[int, QuickAction]]

    @abstractmethod
    async def rank_user(self, member: discord.Member) -> Rank:
        raise NotImplementedError()

    @abstractmethod
    async def is_rank_4(self, member: discord.Member) -> bool:
        raise NotImplementedError()

    @abstractmethod
    def is_role_privileged(self, role: discord.Role, issuers_top_role: discord.Role=None) -> bool:
        raise NotImplementedError()

    @abstractmethod
    async def make_message_log(self, obj, *, guild: discord.Guild, requester: discord.Member=None,
                               replace_backtick=False, pagify_log=False):
        raise NotImplementedError()

    @abstractmethod
    def has_staff_been_active(self, guild: discord.Guild, minutes: int) -> bool:
        raise NotImplementedError()

    @abstractmethod
    async def refresh_staff_activity(self, guild: discord.Guild, timestamp=None):
        raise NotImplementedError()

    @abstractmethod
    async def refresh_with_audit_logs_activity(self, guild: discord.Guild):
        raise NotImplementedError()

    @abstractmethod
    def is_in_emergency_mode(self, guild: discord.Guild) -> bool:
        raise NotImplementedError()

    @abstractmethod
    def send_to_monitor(self, guild: discord.Guild, entry: str):
        raise NotImplementedError()

    @abstractmethod
    async def send_announcements(self):
        raise NotImplementedError()

    @abstractmethod
    async def inc_message_count(self, member: discord.Member):
        raise NotImplementedError()

    @abstractmethod
    async def get_total_recorded_messages(self, member: discord.Member) -> int:
        raise NotImplementedError()

    @abstractmethod
    async def is_helper(self, member: discord.Member) -> bool:
        raise NotImplementedError()

    @abstractmethod
    async def is_emergency_module(self, guild, module: EmergencyModules):
        raise NotImplementedError()

    @abstractmethod
    async def create_modlog_case(self, bot, guild, created_at, action_type, user, moderator=None, reason=None,
                                 until=None, channel=None, last_known_username=None):
        raise NotImplementedError()

    @abstractmethod
    async def send_notification(self, destination: discord.abc.Messageable, description: str, *,
                                title: str=None, fields: list=[], footer: str=None,
                                thumbnail: str=None,
                                ping=False, file: discord.File=None, react: str=None,
                                jump_to: discord.Message=None,
                                allow_everyone_ping=False, force_text_only=False, heat_key: str=None,
                                no_repeat_for: datetime.timedelta=None,
                                quick_action: QuickAction=None, view: discord.ui.View=None)->Optional[discord.Message]:
        raise NotImplementedError()

    @abstractmethod
    async def join_monitor_flood(self, member: discord.Member):
        raise NotImplementedError()

    @abstractmethod
    async def join_monitor_suspicious(self, member: discord.Member):
        raise NotImplementedError()

    @abstractmethod
    async def invite_filter(self, message: discord.Message):
        raise NotImplementedError()

    @abstractmethod
    async def detect_raider(self, message: discord.Message):
        raise NotImplementedError()

    @abstractmethod
    async def comment_analysis(self, message: discord.Message):
        raise NotImplementedError()

    @abstractmethod
    async def make_identify_embed(self, message, user, rank=True, link=True):
        raise NotImplementedError()

    @abstractmethod
    async def callout_if_fake_admin(self, ctx: commands.Context):
        raise NotImplementedError()

    @abstractmethod
    def get_warden_rules_by_event(self, guild: discord.Guild, event: WardenEvent)->List[WardenRule]:
        raise NotImplementedError()

    @abstractmethod
    def dispatch_event(self, event_name, *args):
        raise NotImplementedError()

    @abstractmethod
    async def format_punish_message(self, member: discord.Member) -> str:
        raise NotImplementedError()
