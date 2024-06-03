import discord
import typing

import datetime
import logging

from redbot.core.utils import AsyncIter

from ..enums import Rank

log = logging.getLogger("red.x26cogs.defender")

def dashboard_page(*args, **kwargs):
    def decorator(func: typing.Callable):
        func.__dashboard_decorator_params__ = (args, kwargs)
        return func

    return decorator


class StatusIntegration:
    @dashboard_page(name=None, description="Defender status.", methods=("GET", "POST"))
    async def dashboard_status_page(self, user: discord.User, guild: discord.Guild, **kwargs) -> typing.Dict[str, typing.Any]:
        member = guild.get_member(user.id)
        if user.id != guild.owner.id and not await self.bot.is_admin(member) and user.id not in self.bot.owner_ids:
            return {
                "status": 1,
                "error_code": 403,
                "error_message": "You must be an administrator to access this page.",
            }
        perms = member.guild_permissions
        if not all((perms.manage_messages, perms.manage_roles, perms.ban_members)):
            return {
                "status": 1,
                "error_code": 403,
                "error_message": "You must have the following permissions to access this page: Manage Messages, Manage Roles and Ban Members.",
            }

        monitor = "\n".join(self.monitor[guild.id])
        freshmeat = ""
        x_hours_ago = datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(hours=24)
        new_members = sorted(
            [m for m in guild.members if m.joined_at is not None and m.joined_at > x_hours_ago],
            key=lambda m: m.joined_at,
            reverse=True,
        )
        for m in new_members:
            join = m.joined_at.strftime("%Y/%m/%d %H:%M:%S")
            created = m.created_at.strftime("%Y/%m/%d %H:%M:%S")
            freshmeat += f"J/C: {join}  {created} | {m.id} | {m}\n"
        ranks = {
            Rank.Rank1: 0,
            Rank.Rank2: 0,
            Rank.Rank3: 0,
            Rank.Rank4: 0,
        }
        async for m in AsyncIter(guild.members, steps=2):
            if m.bot:
                continue
            if m.joined_at is None:
                continue
            rank = await self.rank_user(m)
            ranks[rank] += 1
        member_ranks = "\n".join(f"- Rank {rank}: {count} Members" for rank, count in ranks.items())

        return {
            "status": 0,
            "web_content": {
                "source": WEB_CONTENT,
                "monitor": monitor,
                "freshmeat": freshmeat,
                "member_ranks": member_ranks,
            },
        }

WEB_CONTENT = """
    <div id="Monitor" class="card">
        <div class="card-header" id="headingMonitor">
            <a class="btn btn-link mb-0" data-toggle="collapse" data-target="#collapseMonitor" aria-expanded="true" aria-controls="collapseMonitor" style="width: 100%;">
                <div class="d-flex justify-content-between align-items-center">
                    <h4 class="mb-0">Monitor</h4>
                    <h4><i class="fa fa-arrow-circle-o-down"></i></h4>
                </div>
            </a>
        </div>
        <div id="collapseMonitor" class="collapse card-body" aria-labelledby="headingMonitor" style="padding-top: 0px;">
            {{ monitor|highlight("rust") if monitor else "No recent events have been recorded." }}
        </div>
    </div>

    <br />
    <div id="Freshmeat" class="card">
        <div class="card-header" id="headingFreshmeat">
            <a class="btn btn-link mb-0" data-toggle="collapse" data-target="#collapseFreshmeat" aria-expanded="true" aria-controls="collapseFreshmeat" style="width: 100%;">
                <div class="d-flex justify-content-between align-items-center">
                    <h4 class="mb-0">Freshmeat</h4>
                    <h4><i class="fa fa-arrow-circle-o-down"></i></h4>
                </div>
            </a>
        </div>
        <div id="collapseFreshmeat" class="collapse card-body" aria-labelledby="headingFreshmeat" style="padding-top: 0px;">
            {{ freshmeat|highlight("go") if freshmeat else "No new members have joined in the last 24 hours." }}
        </div>
    </div>

    <br />
    <div id="MemberRanks" class="card">
        <div class="card-header" id="headingMemberRanks">
            <a class="btn btn-link mb-0" data-toggle="collapse" data-target="#collapseMemberRanks" aria-expanded="true" aria-controls="collapseMemberRanks" style="width: 100%;">
                <div class="d-flex justify-content-between align-items-center">
                    <h4 class="mb-0">MemberRanks</h4>
                    <h4><i class="fa fa-arrow-circle-o-down"></i></h4>
                </div>
            </a>
        </div>
        <div id="collapseMemberRanks" class="collapse card-body" aria-labelledby="headingMemberRanks" style="padding-top: 0px;">
            {{ member_ranks|highlight("yaml") }}
        </div>
    </div>
"""
