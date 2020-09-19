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

from collections import deque, defaultdict
from datetime import timedelta
from copy import deepcopy
from discord.ext.commands.errors import BadArgument
from discord.ext.commands import IDConverter
import re
import datetime
import discord
import logging
import asyncio

utcnow = datetime.datetime.utcnow
log = logging.getLogger("red.x26cogs.defender")

# These values are overriden at runtime with the owner's settings
MSG_EXPIRATION_TIME = 48 # Hours
MSG_STORE_CAP = 3000
_guild_dict = {"users": {}, "channels": {}}
_message_cache = defaultdict(lambda: deepcopy(_guild_dict))

# We're gonna store *a lot* of messages in memory and we're gonna improve
# performances by storing only a lite version of them

class LiteMessage:
    __slots__ = ("id", "created_at", "content", "channel_id", "author_id")
    def __init__(self, message: discord.Message):
        self.id = message.id
        self.created_at = message.created_at
        self.content = message.content
        self.author_id = message.author.id
        self.channel_id = message.channel.id
        if message.attachments:
            filename = message.attachments[0].filename
            self.content = f"(Attachment: {filename}) {self.content}"

class CacheUser:
    def __init__(self, _id, guild):
        self.id = _id
        self.guild = guild

    def __str__(self):
        return "Unknown"

class UserCacheConverter(IDConverter):
    """
    This is a modified version of discord.py's Member converter
    https://github.com/Rapptz/discord.py/blob/master/discord/ext/commands/converter.py
    1. Lookup by ID. If found, return a Member
    2. Lookup by name. If found, return a Member
    3. Lookup by ID in cache. If found, return a CacheUser object that will allow to access the cache
    """
    async def convert(self, ctx, argument):
        match = self._get_id_match(argument) or re.match(r'<@!?([0-9]+)>$', argument)
        guild = ctx.guild
        result = None
        user_id = None
        if match is None:
            # not a mention...
            if guild:
                result = guild.get_member_named(argument)
        else:
            user_id = int(match.group(1))
            if guild:
                result = guild.get_member(user_id) or discord.utils.get(ctx.message.mentions, id=user_id)

        if result is None and guild and user_id:
            try:
                _message_cache[guild.id]["users"][user_id]
            except KeyError:
                pass
            else:
                result = CacheUser(_id=user_id, guild=guild)

        if result is None:
            raise BadArgument("User not found in the guild nor in the recorded messages.")

        return result

def add_message(message):
    author = message.author
    guild = message.guild
    channel = message.channel
    if author.id not in _message_cache[guild.id]["users"]:
        _message_cache[guild.id]["users"][author.id] = deque(maxlen=MSG_STORE_CAP)

    lite_message = LiteMessage(message)

    _message_cache[guild.id]["users"][author.id].appendleft(lite_message)

    if channel.id not in _message_cache[guild.id]["channels"]:
        _message_cache[guild.id]["channels"][channel.id] = deque(maxlen=MSG_STORE_CAP)

    _message_cache[guild.id]["channels"][channel.id].appendleft(lite_message)

def get_user_messages(user):
    guild = user.guild
    if user.id not in _message_cache[guild.id]["users"]:
        return []

    return _message_cache[guild.id]["users"][user.id].copy()

def get_channel_messages(channel):
    guild = channel.guild
    if channel.id not in _message_cache[guild.id]["channels"]:
        return []

    return _message_cache[guild.id]["channels"][channel.id].copy()

async def discard_stale():
    x_hours_ago = utcnow() - timedelta(hours=MSG_EXPIRATION_TIME)
    for guid, _cache in _message_cache.items():
        for uid, store in _cache["users"].items():
            _message_cache[guid]["users"][uid] = deque([m for m in store if m.created_at > x_hours_ago], maxlen=MSG_STORE_CAP)
        await asyncio.sleep(0)

    for guid, _cache in _message_cache.items():
        for cid, store in _cache["channels"].items():
            _message_cache[guid]["channels"][cid] = deque([m for m in store if m.created_at > x_hours_ago], maxlen=MSG_STORE_CAP)
        await asyncio.sleep(0)

async def discard_messages_from_user(_id):
    for guid, _cache in _message_cache.items():
        for uid, store in _cache["users"].items():
            _message_cache[guid]["users"][uid] = deque([m for m in store if m.author_id != _id], maxlen=MSG_STORE_CAP)
        await asyncio.sleep(0)

    for guid, _cache in _message_cache.items():
        for cid, store in _cache["channels"].items():
            _message_cache[guid]["channels"][cid] = deque([m for m in store if m.author_id != _id], maxlen=MSG_STORE_CAP)
        await asyncio.sleep(0)