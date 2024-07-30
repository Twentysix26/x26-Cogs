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

import discord
import logging
import asyncio
from ...core.utils import utcnow
from copy import deepcopy
from datetime import timedelta
from collections import defaultdict, deque
from typing import Union

"""
This system is meant to enhance Warden in a way that allows to track (and act on) recurring events
Thanks to this system, for example, it's possible to make rules that track how many messages a user
has sent in a set window of time and act after an arbitrary threshold is reached.
This system works by attaching "heat" points to members (or even channels) that expire after a set
amount of time and are shared between different Warden rules.
"""

MAX_HEATPOINTS = 100
log = logging.getLogger("red.x26cogs.defender")

_guild_heat = {"channels" : {}, "users": {}, "custom": {}}
_heat_store = defaultdict(lambda: deepcopy(_guild_heat))
_sandbox_heat_store = defaultdict(lambda: deepcopy(_guild_heat))
class HeatLevel:
    __slots__ = ("guild", "id", "type", "_heat_points",)

    def __init__(self, guild: int, _id: Union[str, int], _type: str):
        self.guild = guild
        self.id = _id
        self.type = _type
        self._heat_points = deque(maxlen=MAX_HEATPOINTS)

    def increase_heat(self, td: timedelta):
        ts = utcnow()
        ts += td
        self._heat_points.append(ts)

    def _expire_heat(self):
        now = utcnow()
        self._heat_points = deque([h for h in self._heat_points if h > now], maxlen=MAX_HEATPOINTS)

    def __len__(self):
        self._expire_heat()
        q = len(self._heat_points)
        if q == 0:
            discard_heatlevel(self)
        return q

    def __repr__(self):
        return f"<HeatLevel: {len(self._heat_points)}>"

def get_heat_store(guild_id, debug=False):
    if debug is False:
        return _heat_store[guild_id]
    else:
        return _sandbox_heat_store[guild_id]

def get_user_heat(user: discord.Member, *, debug=False):
    heat = get_heat_store(user.guild.id, debug)["users"].get(user.id)
    if heat:
        return len(heat)
    else:
        return 0

def get_channel_heat(channel: discord.TextChannel, *, debug=False):
    heat = get_heat_store(channel.guild.id, debug)["channels"].get(channel.id)
    if heat:
        return len(heat)
    else:
        return 0

def get_custom_heat(guild: discord.Guild, key: str, *, debug=False):
    key = key.lower()
    heat = get_heat_store(guild.id, debug)["custom"].get(key)
    if heat:
        return len(heat)
    else:
        return 0

def empty_user_heat(user: discord.Member, *, debug=False):
    heat = get_heat_store(user.guild.id, debug)["users"].get(user.id)
    if heat:
        discard_heatlevel(heat, debug=debug)

def empty_channel_heat(channel: discord.TextChannel, *, debug=False):
    heat = get_heat_store(channel.guild.id, debug)["channels"].get(channel.id)
    if heat:
        discard_heatlevel(heat, debug=debug)

def empty_custom_heat(guild: discord.Guild, key: str, *, debug=False):
    key = key.lower()
    heat = get_heat_store(guild.id, debug)["custom"].get(key)
    if heat:
        discard_heatlevel(heat, debug=debug)

def increase_user_heat(user: discord.Member, td: timedelta, *, debug=False):
    heat = get_heat_store(user.guild.id, debug)["users"].get(user.id)
    if heat:
        heat.increase_heat(td)
    else:
        get_heat_store(user.guild.id, debug)["users"][user.id] = HeatLevel(user.guild.id, user.id, "users")
        get_heat_store(user.guild.id, debug)["users"][user.id].increase_heat(td)

def increase_channel_heat(channel: discord.TextChannel, td: timedelta, *, debug=False):
    heat = get_heat_store(channel.guild.id, debug)["channels"].get(channel.id)
    if heat:
        heat.increase_heat(td)
    else:
        get_heat_store(channel.guild.id, debug)["channels"][channel.id] = HeatLevel(channel.guild.id, channel.id, "channels")
        get_heat_store(channel.guild.id, debug)["channels"][channel.id].increase_heat(td)

def increase_custom_heat(guild: discord.Guild, key: str, td: timedelta, *, debug=False):
    key = key.lower()
    heat = get_heat_store(guild.id, debug)["custom"].get(key)
    if heat:
        heat.increase_heat(td)
    else:
        get_heat_store(guild.id, debug)["custom"][key] = HeatLevel(guild.id, key, "custom")
        get_heat_store(guild.id, debug)["custom"][key].increase_heat(td)

def discard_heatlevel(heatlevel: HeatLevel, *, debug=False):
    try:
        del get_heat_store(heatlevel.guild, debug)[heatlevel.type][heatlevel.id]
    except Exception as e:
        pass

async def remove_stale_heat():
    # In case you're wondering wtf am I doing here:
    # I'm calling len on each HeatLevel object to trigger
    # its auto removal logic, so they don't linger indefinitely
    # in the cache after the heatpoints are expired and the user is long gone
    for store in (_heat_store, _sandbox_heat_store):
        for c in store.values():
            for cc in c.values():
                for heat_level in list(cc.values()):
                    len(heat_level)
            await asyncio.sleep(0)

def get_state(guild, debug=False):
    if not debug:
        return _heat_store[guild.id].copy()
    else:
        return _sandbox_heat_store[guild.id].copy()

def empty_state(guild, debug=False):
    try:
        if not debug:
            del _heat_store[guild.id]
        else:
            del _sandbox_heat_store[guild.id]
    except KeyError:
        pass

def get_custom_heat_keys(guild: discord.Guild):
    return list(_heat_store[guild.id]["custom"].keys())
