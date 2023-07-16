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

from typing import Any, Dict

import aiohttp
import logging
from copy import copy
from datetime import datetime
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.config import Config

from .parser import Cog, Repo
from .views import IndexCogsView, IndexReposView
from .exceptions import NoCogs

IX_PROTOCOL = 1
CC_INDEX_LINK = f"https://raw.githubusercontent.com/Cog-Creators/Red-Index/master/index/{IX_PROTOCOL}-min.json"
RED_INDEX_REPO = "https://github.com/Cog-Creators/Red-Index/"

log = logging.getLogger("red.x26cogs.index")

class Index(commands.Cog):
    """Browse and install repos / cogs from a Red-Index"""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=262626, force_registration=True
        )
        self.config.register_global(
            red_index_link=CC_INDEX_LINK,
            red_index_max_age=10,  # minutes
            red_index_cache={},
            red_index_show_unapproved=False,
        )
        self.session = aiohttp.ClientSession()
        self.cache = []
        self.last_fetched = None

    async def cog_unload(self):
        await self.session.close()

    async def red_get_data_for_user(self, *, user_id: int) -> Dict[str, Any]:
        return {}

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        pass

    @commands.group(name="index")
    async def indexgroup(self, ctx: commands.Context):
        """Red-Index cog discoverability commands"""

    @indexgroup.command(name="browse")
    @commands.bot_has_permissions(embed_links=True, add_reactions=True)
    async def index_browse(self, ctx: commands.Context, repo_name=""):
        """Browses repos / cogs"""
        try:
            await self.fetch_index()
        except Exception as e:
            await ctx.send("Something went wrong. Index service may be not "
                           "available or a not working link may have been set.\n"
                           f"Error: {e}")
            return
        if not repo_name:
            cache = self.cache.copy()
            await IndexReposView(ctx, repos=cache).show_repos()
        else:
            for r in self.cache:
                if not r.name.lower() == repo_name.lower():
                    continue
                try:
                    await IndexCogsView(ctx, repo=r).show_cogs()
                except NoCogs:
                    await ctx.send("This repository is empty: no cogs to show.")
                break
            else:
                await ctx.send("I could not find any repo with that name.")

    def get_all_cogs(self):
        cogs = []
        for r in self.cache:
            cogs.extend(r.cogs.values())
        return cogs

    @indexgroup.command(name="search")
    @commands.bot_has_permissions(embed_links=True, add_reactions=True)
    async def index_search(self, ctx: commands.Context, *, search_term: str):
        """Search for cogs"""
        try:
            await self.fetch_index()
        except Exception as e:
            await ctx.send("Something went wrong. Index service may be not "
                           "available or a not working link may have been set.\n"
                           f"Error: {e}")
            return
        cogs_cache = self.get_all_cogs()
        results = []
        search_term = search_term.lower()
        # First search by name
        for c in cogs_cache:
            if search_term in c.name.lower():
                results.append(c)
        # Then search by tags
        for c in cogs_cache:
            for tag in c.tags:
                if search_term in tag.lower():
                    if c not in results:
                        results.append(c)
        # If still nothing comes up search by description
        if not results:
            for c in cogs_cache:
                if search_term in c.description.lower():
                    results.append(c)
        # Maybe the user is looking for a particular repo...?
        if not results:
            for c in cogs_cache:
                if search_term in c.repo.name.lower():
                    results.append(c)
        # Ok maybe... authors?
        if not results:
            for c in cogs_cache:
                if search_term in " ".join(c.author).lower():
                    results.append(c)

        if results:
            await IndexCogsView(ctx, cogs=results).show_cogs()
        else:
            # Well, fuck it then
            await ctx.send("I could not find anything with those search terms.")

    @commands.is_owner()
    @commands.group()
    async def indexset(self, ctx: commands.Context):
        """Red-Index configuration"""

    @indexset.command(name="refresh")
    async def indexset_refresh(self, ctx: commands.Context):
        """Manually refresh the Red-Index cache."""
        async with ctx.typing():
            try:
                await self.fetch_index(force=True)
            except Exception as e:
                await ctx.send("Something went wrong. Index service may be not "
                               "available or a not working link may have been set.\n"
                               f"Error: {e}")
            else:
                await ctx.send("Index refreshed successfully.")

    @indexset.command(name="maxminutes")
    async def indexset_maxminutes(
        self, ctx: commands.Context, minutes: int
    ):
        """Minutes elapsed before the cache is considered stale

        Set 0 if you want the cache refresh to be manual only"""
        if minutes < 0:
            await ctx.send("Invalid minutes value.")
            return
        await self.config.red_index_max_age.set(minutes)
        if minutes:
            await ctx.send(f"After {minutes} minutes the cache will be automatically "
                            "refreshed when used.")
        else:
            await ctx.send("Cache auto-refresh disabled. Do "
                           f"{ctx.prefix}index refresh to refresh it.")

    @indexset.command(name="link")
    async def indexset_link(self, ctx: commands.Context, link: str=""):
        """Set a custom Red-Index link"""
        if not link:
            await ctx.send("With this command you can set a custom Red-Index link. "
                           "This gives you the freedom to run your own Red-Index: just fork the repo "
                           f"and it's ready to go!\n<{RED_INDEX_REPO}>\nTo keep using our curated "
                           f"index do `{ctx.prefix}indexset link default`")
            return
        if link.lower() == "default":
            await self.config.red_index_link.clear()
            await ctx.send(f"Link has been set to the default one:\n<{CC_INDEX_LINK}>")
            await self.fetch_index(force=True)
        else:
            await self.config.red_index_link.set(link)
            try:
                await self.fetch_index(force=True)
            except Exception as e:
                log.error("Error fetching the index file", exc_info=e)
                await ctx.send("Something went wrong while trying to reach the new link you have set. "
                               "I'll revert to the default one.\nA custom Red-Index link format must be "
                               f"similar to this: <{CC_INDEX_LINK}>.\nIt has to be static and point to a "
                               "valid json source.")
                await self.config.red_index_link.clear()
                await self.fetch_index(force=True)
            else:
                await ctx.send("New link successfully set. Remember that you can go back "
                               f"to the standard link with `{ctx.prefix}indexset link default.`")

    @indexset.command(name="showunapproved")
    async def indexset_showunapproved(self, ctx: commands.Context, yes_or_no: bool):
        """Toggle unapproved cogs display"""
        await self.config.red_index_show_unapproved.set(yes_or_no)
        try:
            await self.fetch_index(force=True)
        except Exception as e:
            await ctx.send("Something went wrong. Index service may be not "
                           "available or a not working link may have been set.\n"
                           f"Error: {e}")
            return
        if yes_or_no:
            await ctx.send("Done. Remember that unapproved cogs haven't been vetted "
                           "by anyone. Make sure you trust what you install!")
        else:
            await ctx.send("Done. I won't show any unapproved cog.")

    async def fetch_index(self, force=False):
        if force or await self.is_cache_stale():
            link = await self.config.red_index_link()
            async with self.session.get(link) as data:
                if data.status != 200:
                    raise RuntimeError(f"Could not fetch index. HTTP code: {data.status}")
                raw = await data.json(content_type=None)

            show_unapproved = await self.config.red_index_show_unapproved()
            cache = []

            for k, v in raw.items():
                cache.append(Repo(k, v))

            if not show_unapproved:
                cache = [r for r in cache if r.rx_category != "unapproved"]

            self.cache = cache
            self.last_fetched = datetime.utcnow()

    async def is_cache_stale(self):
        max_age = await self.config.red_index_max_age()
        if not max_age:  # 0 = no auto-refresh
            return False
        elif not self.last_fetched: # no fetch yet
            return True

        minutes_since = (datetime.utcnow() - self.last_fetched).seconds / 60
        return minutes_since > max_age

    async def install_repo_cog(self, ctx, repo: Repo, cog: Cog=None):
        """
        Following Jackenmen's Cogboard logic made my life easier here. Thanks Jack!
        https://github.com/jack1142/JackCogs/blob/91f39e1f4cb97491a70103cce90f0aa99fa2efc5/cogboard/menus.py#L30
        """
        async def get_fake_context(ctx, command):
            fake_message = copy(ctx.message)
            fake_message.content = f"{ctx.prefix}{command.qualified_name}"
            return await ctx.bot.get_context(fake_message)

        def get_repo_by_url(url):
            for r in downloader._repo_manager.repos:
                if url == r.clean_url:
                    return r

        def get_clean_url(url):
            if "@" in url:
                url, branch = url.split("@")
            return url, None

        downloader = self.bot.get_cog("Downloader")
        if downloader is None:
            raise RuntimeError("Downloader is not loaded.")

        url, branch = get_clean_url(repo.url)
        downloader_repo = get_repo_by_url(url)

        if not downloader_repo:
            command = downloader._repo_add
            fake_context = await get_fake_context(ctx, command)

            branch = repo.rx_branch if repo.rx_branch else None
            await command(fake_context, repo.name.lower(), url, branch)
            downloader_repo = get_repo_by_url(url)
            if not downloader_repo:
                raise RuntimeError("I could not find the repo after adding it through Downloader.")

        if cog:
            if downloader_repo is None:
                raise RuntimeError("No valid downloader repo.")
            await downloader._cog_install(ctx, downloader_repo, cog.name)
