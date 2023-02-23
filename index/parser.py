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

import discord
import logging

FLOPPY_DISK = "\N{FLOPPY DISK}"
ARROW_UP = "\N{UPWARDS BLACK ARROW}\N{VARIATION SELECTOR-16}"
ARROW_DOWN = "\N{DOWNWARDS BLACK ARROW}\N{VARIATION SELECTOR-16}"

log = logging.getLogger("red.x26cogs.index")

class Repo:
    def __init__(self, url: str, raw_data: dict):
        self.url = url
        self.rx_category = raw_data.get("rx_category", "unapproved")
        self.rx_cogs = raw_data.get("rx_cogs", [])
        self.author = raw_data.get("author", ["Unknown"])
        self.description = raw_data.get("description", "")
        self.short = raw_data.get("short", "")
        self.name = raw_data.get("name", "Unknown")
        self.rx_branch = raw_data.get("rx_branch", "")
        self.cogs = {}
        for cog_name, cog_raw in raw_data["rx_cogs"].items():
            if cog_raw.get("hidden", False) or cog_raw.get("disabled", False):
                continue
            self.cogs[cog_name] = Cog(cog_name, self, cog_raw)

    def build_embed(self, *, prefix="[p]", is_owner=False):
        em = discord.Embed(url=self.url, description=self.description, colour=discord.Colour.red())
        em.set_author(name=f"{self.name} by {', '.join(self.author)}")
        em.add_field(name="Type", value=self.rx_category, inline=True)
        if self.rx_branch:
            em.add_field(name="Branch", value=self.rx_branch, inline=True)
            url, _ = self.url.split("@", 1)
        else:
            url = self.url
        em.add_field(name="Command to add repo",
                     value=f"{prefix}repo add {self.name.lower()} {url} {self.rx_branch}",
                     inline=False)
        return em

class Cog:
    def __init__(self, name: str, repo: Repo, raw_data: dict):
        self.name = name
        self.author = raw_data.get("author", ["Unknown"])
        self.description = raw_data.get("description", "")
        self.end_user_data_statement = raw_data.get("end_user_data_statement", "")
        self.permissions = raw_data.get("permissions", [])
        self.short = raw_data.get("short", "")
        self.min_bot_version = raw_data.get("min_bot_version", "")
        self.max_bot_version = raw_data.get("max_bot_version", "")
        self.min_python_version = raw_data.get("min_python_version", "")
        self.hidden = False
        self.disabled = False
        self.required_cogs = raw_data.get("required_cogs", {})
        self.requirements = raw_data.get("requirements", [])
        self.tags = raw_data.get("tags", [])
        self.type = raw_data.get("type", "")
        self.repo = repo

    def build_embed(self, *, prefix="[p]", is_owner=False):
        url = f"{self.repo.url}/{self.name}"

        if self.description:
            description = self.description
        else:
            description = self.short
        if self.author:
            author = ', '.join(self.author)
        else:
            author = self.repo.name
        em = discord.Embed(url=url, description=description, colour=discord.Colour.red())
        em.set_author(name=f"{self.name} from {self.repo.name}")
        em.add_field(name="Type", value=self.repo.rx_category, inline=True)
        em.add_field(name="Author", value=author, inline=True)
        if self.requirements:
            em.add_field(name="External libraries", value=f"{', '.join(self.requirements)}", inline=True)
        if self.required_cogs:
            em.add_field(name="Required cogs", value=f"{', '.join(self.required_cogs.keys())}", inline=True)
        if self.repo.rx_branch:
            repo_url, _ = self.repo.url.split("@", 1)
        else:
            repo_url = self.repo.url
        em.add_field(name="Command to add repo",
                     value=f"{prefix}repo add {self.repo.name.lower()} {repo_url} {self.repo.rx_branch}",
                     inline=False)
        em.add_field(name="Command to add cog",
                     value=f"{prefix}cog install {self.repo.name.lower()} {self.name}",
                     inline=False)
        tags = ""
        if self.tags:
            tags = "\nTags: " + ", ".join(self.tags)
        em.set_footer(text=f"{tags}")
        return em

def build_embeds(repos_cogs, prefix="[p]", is_owner=False):
    embeds = []

    for rc in repos_cogs:
        if isinstance(rc, (Repo, Cog)):
            em = rc.build_embed(prefix=prefix, is_owner=is_owner)
        else:
            raise TypeError("Unhandled type.")
        embeds.append(em)

    return embeds
