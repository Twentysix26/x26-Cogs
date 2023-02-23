"""
Index - Browse and install Red repos and cogs using the Red-Index system
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

from typing import List, Optional

import discord
from redbot.core import commands

from .parser import Repo, Cog, build_embeds, FLOPPY_DISK, ARROW_DOWN

PREV_ARROW = "\N{LEFTWARDS BLACK ARROW}\N{VARIATION SELECTOR-16}"
CROSS_MARK = "\N{HEAVY MULTIPLICATION X}\N{VARIATION SELECTOR-16}"
NEXT_ARROW = "\N{BLACK RIGHTWARDS ARROW}\N{VARIATION SELECTOR-16}"

class IndexReposView(discord.ui.View):

    def __init__(self, ctx: commands.Context, repos: List[Repo]):
        super().__init__(timeout=60 * 3)
        self.ctx: commands.Context = ctx
        self.cog = ctx.cog

        self.repos: List[Repo] = repos

        self._message: Optional[discord.Message] = None
        self._embeds: Optional[List[discord.Embed]] = None
        self._selected = 0

    async def interaction_check(self, interaction: discord.Interaction):
        if not interaction.user.id == self.ctx.author.id:
            await interaction.response.send_message(
                f"You are not allowed to use this interaction. You can use `{self.ctx.prefix}index browse`.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        try:
            await self._message.delete()
        except discord.NotFound:
            pass

    async def show_repos(self):
        is_owner = await self.ctx.bot.is_owner(self.ctx.author) and self.ctx.bot.get_cog("Downloader")
        self._embeds = build_embeds(self.repos, prefix=self.ctx.prefix, is_owner=is_owner)
        if not is_owner:
            self.remove_item(self.install_repo)
        self._message = await self.ctx.send(embed=self._embeds[0], view=self)

    @discord.ui.button(label="Prev page", emoji=PREV_ARROW)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Item):
        if self._selected == (len(self.repos) - 1):
            self._selected = 0
        else:
            self._selected += 1
        await interaction.response.edit_message(embed=self._embeds[self._selected])

    @discord.ui.button(style=discord.ButtonStyle.danger, emoji=CROSS_MARK)
    async def close_page(self, interaction: discord.Interaction, button: discord.ui.Item):
        await interaction.response.defer()
        await self.on_timeout()
        self.stop()

    @discord.ui.button(emoji=NEXT_ARROW)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Item):
        if self._selected == 0:
            self._selected = len(self.repos) - 1
        else:
            self._selected -= 1
        await interaction.response.edit_message(embed=self._embeds[self._selected])

    @discord.ui.button(emoji=ARROW_DOWN)
    async def enter_repo(self, interaction: discord.Interaction, button: discord.ui.Item):
        await interaction.response.defer()
        await self._message.delete()
        await IndexCogsView(self.ctx, repo=self.repos[self._selected]).show_cogs()

    @discord.ui.button(style=discord.ButtonStyle.success, label="Install this repo", emoji=FLOPPY_DISK)
    async def install_repo(self, interaction: discord.Interaction, button: discord.ui.Item):
        await interaction.response.defer()
        try:
            await self.cog.install_repo_cog(self.ctx, self.repos[self._selected])
        except RuntimeError as e:
            await self.ctx.send(f"I could not install the repository: {e}")

class IndexCogsView(discord.ui.View):

    def __init__(self, ctx: commands.Context, repo: Optional[Repo] = None, cogs: Optional[List[Cog]] = None):
        super().__init__(timeout=60 * 3)
        self.ctx: commands.Context = ctx
        self.cog = ctx.cog

        self.repo: Optional[Repo] = repo
        self.cogs: Optional[List[Cog]] = cogs

        self._message: Optional[discord.Message] = None
        self._embeds: Optional[List[discord.Embed]] = None
        self._selected = 0

    async def interaction_check(self, interaction: discord.Interaction):
        if not interaction.user.id == self.ctx.author.id:
            await interaction.response.send_message(
                f"You are not allowed to use this interaction. You can use `{self.ctx.prefix}index search`.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        try:
            await self._message.delete()
        except discord.NotFound:
            pass

    async def show_cogs(self):
        is_owner = await self.ctx.bot.is_owner(self.ctx.author) and self.ctx.bot.get_cog("Downloader")
        if self.repo and not self.cogs:
            self.cogs = list(self.repo.cogs.values())
        elif self.cogs:
            pass
        else:
            raise ValueError()
        self._embeds = build_embeds(self.cogs, prefix=self.ctx.prefix, is_owner=is_owner)
        if not is_owner:
            self.remove_item(self.install_cog)
        self._message = await self.ctx.send(embed=self._embeds[0], view=self)

    @discord.ui.button(emoji=PREV_ARROW)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Item):
        if self._selected == (len(self.cogs) - 1):
            self._selected = 0
        else:
            self._selected += 1
        await interaction.response.edit_message(embed=self._embeds[self._selected])

    @discord.ui.button(style=discord.ButtonStyle.danger, emoji=CROSS_MARK)
    async def close_page(self, interaction: discord.Interaction, button: discord.ui.Item):
        await interaction.response.defer()
        await self.on_timeout()
        self.stop()

    @discord.ui.button(emoji=NEXT_ARROW)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Item):
        if self._selected == 0:
            self._selected = len(self.cogs) - 1
        else:
            self._selected -= 1
        await interaction.response.edit_message(embed=self._embeds[self._selected])

    @discord.ui.button(label="Browse repos", emoji=ARROW_DOWN)
    async def browse_repos(self, interaction: discord.Interaction, button: discord.ui.Item):
        await interaction.response.defer()
        await self._message.delete()
        await IndexReposView(self.ctx, repos=self.cog.cache.copy()).show_repos()

    @discord.ui.button(style=discord.ButtonStyle.success, label="Install this cog", emoji=FLOPPY_DISK)
    async def install_cog(self, interaction: discord.Interaction, button: discord.ui.Item):
        await interaction.response.defer()
        try:
            await self.cog.install_repo_cog(self.ctx, self.cogs[self._selected].repo, self.cogs[self._selected])
        except RuntimeError as e:
            await self.ctx.send(f"I could not install the repository: {e}")
