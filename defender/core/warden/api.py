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

from ...abc import MixinMeta
from ...enums import Rank
from .utils import strip_yaml_codeblock
from .rule import WardenCheck
from .enums import Event as WDEvent, ChecksKeys
from typing import Optional
import logging
import discord
import asyncio

log = logging.getLogger("red.x26cogs.defender")
cog: Optional[MixinMeta] = None

def init_api(_cog: MixinMeta):
    global cog
    cog = _cog

async def get_check(guild, module: ChecksKeys):
    if cog is None:
        raise RuntimeError("Warden API was not initialized.")

    check = cog.warden_checks[guild.id].get(module, None)

    if check:
        return check.raw_rule

    return None

async def set_check(guild, module: ChecksKeys, conditions: str, author: discord.Member):
    if cog is None:
        raise RuntimeError("Warden API was not initialized.")

    wd_cond = strip_yaml_codeblock(conditions)

    wd_check = WardenCheck()
    await wd_check.parse(wd_cond, cog=cog, author=author, module=module)

    cog.warden_checks[guild.id][module] = wd_check
    await cog.config.guild(guild).set_raw(f"{module.value}_wdchecks", value=wd_cond)

async def remove_check(guild, module: ChecksKeys):
    if cog is None:
        raise RuntimeError("Warden API was not initialized.")

    try:
        del cog.warden_checks[guild.id][module]
    except KeyError:
        pass

    await cog.config.guild(guild).clear_raw(f"{module.value}_wdchecks")

async def eval_check(guild, module: ChecksKeys, user: Optional[discord.Member]=None, message: Optional[discord.Message]=None):
    if cog is None:
        raise RuntimeError("Warden API was not initialized.")

    wd_check: WardenCheck = cog.warden_checks[guild.id].get(module, None)
    if wd_check is None: # No check = Passed
        return True

    return bool(await wd_check.satisfies_conditions(rank=Rank.Rank4, cog=cog, guild=guild, user=user, message=message))

async def load_modules_checks():
    if cog is None:
        raise RuntimeError("Warden API was not initialized.")

    n = 0

    guilds = cog.config._get_base_group(cog.config.GUILD)
    async with guilds.all() as all_guilds:
        for guid, guild_data in all_guilds.items():
            for key in ChecksKeys:
                raw_check = guild_data.get(f"{key.value}_wdchecks", None)
                if raw_check is None:
                    continue
                n += 1
                wd_check = WardenCheck()
                await wd_check.parse(raw_check, cog=cog, module=key)
                cog.warden_checks[int(guid)][key] = wd_check

            await asyncio.sleep(0)

    log.debug(f"Warden: Loaded {n} checks")