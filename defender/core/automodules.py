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

# Most automodules are too small to have their own files

from ..abc import MixinMeta, CompositeMetaClass
from redbot.core.utils.chat_formatting import box
from redbot.core.utils.common_filters import INVITE_URL_RE
from ..abc import CompositeMetaClass
from ..enums import Action
from ..core import cache as df_cache
from redbot.core import modlog
from io import BytesIO
from collections import deque
import discord
import datetime
import logging

log = logging.getLogger("red.x26cogs.defender")

class AutoModules(MixinMeta, metaclass=CompositeMetaClass): # type: ignore
    async def invite_filter(self, message):
        author = message.author
        guild = author.guild

        result = INVITE_URL_RE.search(message.content)

        if not result:
            return

        exclude_own_invites = await self.config.guild(guild).invite_filter_exclude_own_invites()

        if exclude_own_invites:
            try:
                is_own_invite = await self.is_own_invite(guild, result)
                if is_own_invite:
                    return
            except Exception as e:
                log.error("Unexpected error in invite filter's own invite check", exc_info=e)

        content = box(message.content)
        await message.delete()
        action = await self.config.guild(guild).invite_filter_action()
        if not action: # Only delete message
            return

        if Action(action) == Action.Ban:
            reason = "Posting an invite link (Defender autoban)"
            await guild.ban(author, reason=reason, delete_message_days=0)
            self.dispatch_event("member_remove", author, Action.Ban.value, reason)
        elif Action(action) == Action.Kick:
            reason = "Posting an invite link (Defender autokick)"
            await guild.kick(author, reason=reason)
            self.dispatch_event("member_remove", author, Action.Kick.value, reason)
        elif Action(action) == Action.Softban:
            reason = "Posting an invite link (Defender autokick)"
            await guild.ban(author, reason=reason, delete_message_days=1)
            await guild.unban(author)
            self.dispatch_event("member_remove", author, Action.Softban.value, reason)
        elif Action(action) == Action.NoAction:
            pass
        else:
            raise ValueError("Invalid action for invite filter")

        if Action(action) != Action.NoAction:
            await self.send_notification(guild, f"I have expelled user {author} ({author.id}) for posting this message:\n{content}")

            await modlog.create_case(
                self.bot,
                guild,
                message.created_at,
                action,
                author,
                guild.me,
                "Posting an invite link",
                until=None,
                channel=None,
            )

            return True
        else:
            await self.send_notification(guild, f"I have deleted a message from {author} ({author.id}) with this content:\n{content}")

    async def detect_raider(self, message):
        author = message.author
        guild = author.guild

        cache = df_cache.get_user_messages(author)

        max_messages = await self.config.guild(guild).raider_detection_messages()
        minutes = await self.config.guild(guild).raider_detection_minutes()
        x_minutes_ago = message.created_at - datetime.timedelta(minutes=minutes)
        recent = 0

        for i, m in enumerate(cache):
            if m.created_at > x_minutes_ago:
                recent += 1
            # We only care about the X most recent ones
            if i == max_messages-1:
                break

        if recent != max_messages:
            return

        action = await self.config.guild(guild).raider_detection_action()

        if Action(action) == Action.Ban:
            delete_days = await self.config.guild(guild).raider_detection_wipe()
            reason = "Message spammer (Defender autoban)"
            await guild.ban(author, reason=reason, delete_message_days=delete_days)
            self.dispatch_event("member_remove", author, Action.Ban.value, reason)
        elif Action(action) == Action.Kick:
            reason = "Message spammer (Defender autokick)"
            await guild.kick(author, reason=reason)
            self.dispatch_event("member_remove", author, Action.Kick.value, reason)
        elif Action(action) == Action.Softban:
            reason = "Message spammer (Defender autokick)"
            await guild.ban(author, reason=reason, delete_message_days=1)
            await guild.unban(author)
            self.dispatch_event("member_remove", author, Action.Softban.value, reason)
        elif Action(action) == Action.NoAction:
            fifteen_minutes_ago = message.created_at - datetime.timedelta(minutes=15)
            if guild.id in self.last_raid_alert:
                if self.last_raid_alert[guild.id] > fifteen_minutes_ago:
                    return
            self.last_raid_alert[guild.id] = message.created_at
            await self.send_notification(guild,
                                        f"User {author} ({author.id}) is spamming messages ({recent} "
                                        f"messages in {minutes} minutes).",
                                        link_message=message,
                                        ping=True)
            return
        else:
            raise ValueError("Invalid action for raider detection")

        await modlog.create_case(
            self.bot,
            guild,
            message.created_at,
            action,
            author,
            guild.me,
            "Message spammer",
            until=None,
            channel=None,
        )
        log = "\n".join(self.make_message_log(author, guild=author.guild)[:40])
        f = discord.File(BytesIO(log.encode("utf-8")), f"{author.id}-log.txt")
        await self.send_notification(guild, f"I have expelled user {author} ({author.id}) for posting {recent} "
                                     f"messages in {minutes} minutes. Attached their last stored messages.", file=f)
        return True

    async def join_monitor_flood(self, member):
        guild = member.guild

        if guild.id not in self.joined_users:
            self.joined_users[guild.id] = deque([], maxlen=100)

        cache = self.joined_users[guild.id]
        cache.append(member)

        users = await self.config.guild(guild).join_monitor_n_users()
        minutes = await self.config.guild(guild).join_monitor_minutes()
        x_minutes_ago = member.joined_at - datetime.timedelta(minutes=minutes)
        fifteen_minutes_ago = member.joined_at - datetime.timedelta(minutes=15)

        recent_users = 0

        for m in cache:
            if m.joined_at > x_minutes_ago:
                recent_users += 1

        if recent_users >= users:
            if guild.id in self.last_raid_alert:
                if self.last_raid_alert[guild.id] > fifteen_minutes_ago:
                    return
            self.last_raid_alert[guild.id] = member.joined_at

            await self.send_notification(guild,
                                         f"Abnormal influx of new users ({recent_users} in the past "
                                         f"{minutes} minutes). Possible raid ongoing or about to start.",
                                         ping=True)
            return True

    async def join_monitor_suspicious(self, member):
        guild = member.guild
        hours = await self.config.guild(guild).join_monitor_susp_hours()
        em = await self.make_identify_embed(None, member, rank=False)

        if hours:
            x_hours_ago = member.joined_at - datetime.timedelta(hours=hours)
            if member.created_at > x_hours_ago:
                try:
                    await self.send_notification(guild, f"A user younger than {hours} "
                                                        f"hours just joined. If you wish to turn off "
                                                        "these notifications do `[p]dset joinmonitor "
                                                        "notifynew 0` (admin only)", embed=em)
                except (discord.Forbidden, discord.HTTPException):
                    pass

        subs = await self.config.guild(guild).join_monitor_susp_subs()

        for _id in subs:
            user = guild.get_member(_id)
            if not user:
                continue

            hours = await self.config.member(user).join_monitor_susp_hours()
            if not hours:
                continue

            x_hours_ago = member.joined_at - datetime.timedelta(hours=hours)
            if member.created_at > x_hours_ago:
                try:
                    await user.send(f"A user younger than {hours} "
                                    f"hours just joined in the server {guild.name}. "
                                    "If you wish to turn off these notifications do "
                                    "`[p]defender notifynew 0` in the server.", embed=em)
                except:
                    pass

    async def is_own_invite(self, guild: discord.Guild, match):
        if not guild.me.guild_permissions.manage_guild:
            return False

        has_vanity_url = "VANITY_URL" in guild.features

        if has_vanity_url:
            invite_url = await guild.vanity_invite()
            if invite_url.code.lower() == match.group(2).lower():
                return True

        for invite in await guild.invites():
            if invite.code == match.group(2):
                return True

        return False
