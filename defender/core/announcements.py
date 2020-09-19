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
from datetime import datetime

REPO_LINK = "https://github.com/Twentysix26/x26-Cogs"
WARDEN_URL = "https://github.com/Twentysix26/x26-Cogs/wiki/Warden"
WARDEN_ANNOUNCEMENT = ("Hello. There is a new auto-module available: **Warden**.\nThis auto-module allows you to define "
                       "complex rules to better monitor, manage and moderate your community.\nIt is now the most "
                       f"versatile module that Defender features and by following the [guide]({WARDEN_URL}) "
                       "you will learn how to leverage its full potential in no time. For any suggestion feel free to "
                       f"open an issue in my [repository]({REPO_LINK}).\n\n"
                       "Also, as a small quality of life improvement, the `[p]defender` command has been aliased to "
                       "`[p]def` (using the standard alias cog would cause some issues).\n\n"
                       "I hope you're enjoying Defender as much as I enjoyed creating it.")

ANNOUNCEMENTS = {
    1601078400 : WARDEN_ANNOUNCEMENT
}

def _make_announcement_embed(content):
    em = discord.Embed(color=discord.Colour.red(), description=content)
    em.set_author(name="Defender update")
    em.set_footer(text="A message from 26, creator of Defender")
    return em

def get_announcements(*, only_recent=True):
    to_send = {}
    now = datetime.utcnow()

    for k, v in ANNOUNCEMENTS.items():
        ts = datetime.utcfromtimestamp(k)
        if only_recent is True and now > ts: # The announcement is old
            continue
        to_send[k] = _make_announcement_embed(v)

    return to_send