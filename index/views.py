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
from .exceptions import NoCogs

PREV_ARROW = "\N{LEFTWARDS BLACK ARROW}\N{VARIATION SELECTOR-16}"
CROSS_MARK = "\N{HEAVY MULTIPLICATION X}\N{VARIATION SELECTOR-16}"
NEXT_ARROW = "\N{BLACK RIGHTWARDS ARROW}\N{VARIATION SELECTOR-16}"
MAG_GLASS = "\N{LEFT-POINTING MAGNIFYING GLASS}"

class IndexView(discord.ui.View):
    def __init__(self, ctx: commands.Context, *args, **kwargs):
        self.ctx: commands.Context = ctx
        self.cog = ctx.cog

        self._message: Optional[discord.Message] = None
        self._embeds: Optional[List[discord.Embed]] = None
        self._selected = 0

        super().__init__(*args, timeout=60 * 3, **kwargs)

    async def interaction_check(self, interaction: discord.Interaction):
        if not interaction.user.id == self.ctx.author.id:
            await interaction.response.send_message(
                "You are not allowed to interact with this menu. "
                f"You can open your own with `{self.ctx.prefix}index browse`.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        for child in self.children:
            if not child.style == discord.ButtonStyle.url:
                child.disabled = True
        try:
            await self._message.edit(view=self)
        except discord.HTTPException:
            pass

class IndexReposView(IndexView):
    def __init__(self, ctx: commands.Context, repos: List[Repo]):
        super().__init__(ctx)
        self.repos: List[Repo] = repos

    async def show_repos(self):
        is_owner = await self.ctx.bot.is_owner(self.ctx.author) and self.ctx.bot.get_cog("Downloader")
        self._embeds = build_embeds(self.repos, prefix=self.ctx.prefix, is_owner=is_owner)
        if not is_owner:
            self.remove_item(self.install_repo)
        self._message = await self.ctx.send(embed=self._embeds[self._selected], view=self)

    @discord.ui.button(emoji=PREV_ARROW)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._selected == (len(self.repos) - 1):
            self._selected = 0
        else:
            self._selected += 1
        await interaction.response.edit_message(embed=self._embeds[self._selected], view=self)

    @discord.ui.button(emoji=MAG_GLASS)
    async def enter_repo(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await IndexCogsView(self.ctx, repo=self.repos[self._selected]).show_cogs()
        except NoCogs:
            await interaction.response.send_message("This repository is empty: no cogs to show.",
                                                    ephemeral=True)
            return
        await interaction.response.defer()
        await self._message.delete()

    @discord.ui.button(emoji=NEXT_ARROW)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._selected == 0:
            self._selected = len(self.repos) - 1
        else:
            self._selected -= 1
        await interaction.response.edit_message(embed=self._embeds[self._selected], view=self)

    @discord.ui.button(style=discord.ButtonStyle.danger, emoji=CROSS_MARK)
    async def close_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            await self._message.delete()
        except discord.HTTPException:
            pass
        self.stop()

    @discord.ui.button(style=discord.ButtonStyle.success, label="Install repo", emoji=FLOPPY_DISK)
    async def install_repo(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            await self.cog.install_repo_cog(self.ctx, self.repos[self._selected])
        except RuntimeError as e:
            await self.ctx.send(f"I could not install the repository: {e}")

class IndexCogsView(IndexView):
    def __init__(self, ctx: commands.Context, repo: Optional[Repo] = None, cogs: Optional[List[Cog]] = None):
        super().__init__(ctx)
        self.repo: Optional[Repo] = repo
        self.cogs: Optional[List[Cog]] = cogs

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
        if len(self._embeds) == 0:
            raise NoCogs()
        self._message = await self.ctx.send(embed=self._embeds[self._selected], view=self)

    @discord.ui.button(emoji=PREV_ARROW)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._selected == (len(self.cogs) - 1):
            self._selected = 0
        else:
            self._selected += 1
        await interaction.response.edit_message(embed=self._embeds[self._selected], view=self)

    @discord.ui.button(emoji=ARROW_DOWN)
    async def browse_repos(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self._message.delete()
        await IndexReposView(self.ctx, repos=self.cog.cache.copy()).show_repos()

    @discord.ui.button(emoji=NEXT_ARROW)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._selected == 0:
            self._selected = len(self.cogs) - 1
        else:
            self._selected -= 1
        await interaction.response.edit_message(embed=self._embeds[self._selected], view=self)

    @discord.ui.button(style=discord.ButtonStyle.danger, emoji=CROSS_MARK)
    async def close_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            await self._message.delete()
        except discord.HTTPException:
            pass
        self.stop()

    @discord.ui.button(style=discord.ButtonStyle.success, label="Install cog", emoji=FLOPPY_DISK)
    async def install_cog(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            await self.cog.install_repo_cog(self.ctx, self.cogs[self._selected].repo, self.cogs[self._selected])
        except RuntimeError as e:
            await self.ctx.send(f"I could not install the repository: {e}")
