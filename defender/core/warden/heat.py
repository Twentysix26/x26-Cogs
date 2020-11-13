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

import discord
import datetime
import logging
from copy import deepcopy
from datetime import timedelta
from collections import defaultdict, deque

"""
This system is meant to enhance Warden in a way that allows to track (and act on) recurring events
Thanks to this system, for example, it's possible to make rules that track how many messages a user
has sent in a set window of time and act after an arbitrary threshold is reached.
This system works by attaching "heat" points to members (or even channels) that expire after a set
amount of time and are shared between different Warden rules.
"""

utcnow = datetime.datetime.utcnow
log = logging.getLogger("red.x26cogs.defender")

_guild_heat = {"channels" : {}, "users": {}}
_heat_store = defaultdict(lambda: deepcopy(_guild_heat))

class HeatLevel:
    __slots__ = ("guild", "id", "type", "_heat_points",)

    def __init__(self, guild: int, _id: int, _type: str):
        self.guild = guild
        self.id = _id
        self.type = _type
        self._heat_points = deque(maxlen=100)

    def increase_heat(self, td: timedelta):
        ts = utcnow()
        ts += td
        self._heat_points.append(ts)

    def _expire_heat(self):
        now = utcnow()
        self._heat_points = [h for h in self._heat_points if h > now]

    def __len__(self):
        self._expire_heat()
        q = len(self._heat_points)
        if q == 0:
            discard_heatlevel(self)
        return q

    def __repr__(self):
        return f"<HeatLevel: {len(self)}>"

def get_user_heat(user: discord.Member):
    heat = _heat_store[user.guild.id]["users"].get(user.id)
    if heat:
        return len(heat)
    else:
        return 0

def get_channel_heat(channel: discord.TextChannel):
    heat = _heat_store[channel.guild.id]["channels"].get(channel.id)
    if heat:
        return len(heat)
    else:
        return 0

def empty_user_heat(user: discord.Member):
    heat = _heat_store[user.guild.id]["users"].get(user.id)
    if heat:
        discard_heatlevel(heat)

def empty_channel_heat(channel: discord.TextChannel):
    heat = _heat_store[channel.guild.id]["channels"].get(channel.id)
    if heat:
        discard_heatlevel(heat)

def increase_user_heat(user: discord.Member, td: timedelta):
    heat = _heat_store[user.guild.id]["users"].get(user.id)
    if heat:
        heat.increase_heat(td)
    else:
        _heat_store[user.guild.id]["users"][user.id] = HeatLevel(user.guild.id, user.id, "users")
        _heat_store[user.guild.id]["users"][user.id].increase_heat(td)

def increase_channel_heat(channel: discord.TextChannel, td: timedelta):
    heat = _heat_store[channel.guild.id]["channels"].get(channel.id)
    if heat:
        heat.increase_heat(td)
    else:
        _heat_store[channel.guild.id]["channels"][channel.id] = HeatLevel(channel.guild.id, channel.id, "channels")
        _heat_store[channel.guild.id]["channels"][channel.id].increase_heat(td)

def discard_heatlevel(heatlevel: HeatLevel):
    try:
        del _heat_store[heatlevel.guild][heatlevel.type][heatlevel.id]
    except:
        pass
