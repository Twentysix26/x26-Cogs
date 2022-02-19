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

from discord import ui
from typing import NamedTuple, Optional, List, Tuple, Union
from ..enums import PerspectiveAttributes as PAttr, EmergencyModules as EModules
import discord

class SelectEntry(NamedTuple):
    value: str
    label: str
    description: Optional[str]
    emoji: Optional[str]

PERSPECTIVE_ATTRS_ENTRIES = (
    SelectEntry(value=PAttr.Toxicity.value, label="Toxicity", description="Rude or generally disrespectful comments", emoji=None),
    SelectEntry(value=PAttr.SevereToxicity.value, label="Severe toxicity", description="Hateful, aggressive comments", emoji=None),
    SelectEntry(value=PAttr.IdentityAttack.value, label="Identity attack", description="Hateful comments attacking one's identity", emoji=None),
    SelectEntry(value=PAttr.Insult.value, label="Insult", description="Insulting, inflammatory or negative comments", emoji=None),
    SelectEntry(value=PAttr.Profanity.value, label="Profanity", description="Comments containing swear words, curse words or profanities", emoji=None),
    SelectEntry(value=PAttr.Threat.value, label="Threat", description="Comments perceived as an intention to inflict violence against others", emoji=None),
)

EM_ENTRIES = (
    SelectEntry(value=EModules.Silence.value, label="Silence", description="Apply a server wide mute on ranks", emoji="🔇"),
    SelectEntry(value=EModules.Vaporize.value, label="Vaporize", description="Silently get rid of multiple new users at once", emoji="☁️"),
    SelectEntry(value=EModules.Voteout.value, label="Voteout", description="Start a vote to expel misbehaving users", emoji="👎"),
)

class SettingSelect(ui.Select):
    def __init__(self, config_value, current_settings: List[Union[str, int]], all_settings: Tuple[SelectEntry], min_values=0, max_values=None, cast_to=None, **kwargs):
        self.cast_to = cast_to
        self.config_value = config_value
        if max_values is None:
            max_values = len(all_settings)
        super().__init__(min_values=min_values, max_values=max_values, **kwargs)
        for s in all_settings:
            self.add_option(
                value=s.value,
                label=s.label,
                description=s.description,
                emoji=s.emoji,
                default=True if s.value in current_settings else False,
            )

    async def callback(self, inter: discord.Interaction):
        values = self.values
        if self.cast_to:
            values = [self.cast_to(v) for v in values]
        if self.max_values == 1:
            await self.config_value.set(values[0])
        else:
            await self.config_value.set(values)

class RestrictedMenu(ui.View):
    def __init__(self, cog, issuer_id, timeout=180, **kwargs):
        super().__init__(timeout=timeout, **kwargs)
        self.cog = cog
        self.issuer_id = issuer_id

    async def interaction_check(self, inter: discord.Interaction):
        if inter.user.id != self.issuer_id:
            await inter.response.send_message("Only the issuer of the command can change these options.", ephemeral=True)
            return False
        return True