import discord
import typing

import logging

from ..core.warden.rule import WardenRule, InvalidRule

log = logging.getLogger("red.x26cogs.defender")

def dashboard_page(*args, **kwargs):
    def decorator(func: typing.Callable):
        func.__dashboard_decorator_params__ = (args, kwargs)
        return func

    return decorator


class SettingsIntegration:
    @dashboard_page(name="settings", description="Manage Defender settings.", methods=("GET", "POST"))
    async def dashboard_settings_page(self, user: discord.User, guild: discord.Guild, **kwargs) -> typing.Dict[str, typing.Any]:
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

        return {
            "status": 0,
            "web_content": {
                "source": WEB_CONTENT,
            },
        }

WEB_CONTENT = """
    {{ warden_rules_form|safe }}
"""
