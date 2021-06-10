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
from redbot.core.utils.chat_formatting import box, humanize_timedelta, inline
from redbot.core.utils.common_filters import INVITE_URL_RE
from ..abc import CompositeMetaClass
from ..enums import Action
from ..core import cache as df_cache
from ..core.utils import is_own_invite, ACTIONS_VERBS
from .warden import heat
from redbot.core import modlog
from io import BytesIO
from collections import deque
import discord
import datetime
import logging
import aiohttp

PERSPECTIVE_API_URL = "https://commentanalyzer.googleapis.com/v1alpha1/comments:analyze?key={}"
AIOHTTP_TIMEOUT = aiohttp.ClientTimeout(total=5)
log = logging.getLogger("red.x26cogs.defender")

class AutoModules(MixinMeta, metaclass=CompositeMetaClass): # type: ignore
    async def invite_filter(self, message):
        author = message.author
        guild = author.guild
        EMBED_TITLE = "🔥📧 • Invite filter"
        EMBED_FIELDS = [{"name": "Username", "value": f"`{author}`"},
                        {"name": "ID", "value": f"`{author.id}`"},
                        {"name": "Channel", "value": message.channel.mention}]

        result = INVITE_URL_RE.search(message.content)

        if not result:
            return

        exclude_own_invites = await self.config.guild(guild).invite_filter_exclude_own_invites()

        if exclude_own_invites:
            try:
                if await is_own_invite(guild, result):
                    return False
            except Exception as e:
                log.error("Unexpected error in invite filter's own invite check", exc_info=e)
                return False

        content = box(message.content)

        try:
            await message.delete()
        except discord.Forbidden:
            self.send_to_monitor(guild, "[InviteFilter] Failed to delete message: "
                                        f"no permissions in #{message.channel}")
        except discord.NotFound:
            pass
        except Exception as e:
            log.error("Unexpected error in invite filter's message deletion", exc_info=e)

        action = Action(await self.config.guild(guild).invite_filter_action())

        if action == Action.Ban:
            reason = "Posting an invite link (Defender autoban)"
            await guild.ban(author, reason=reason, delete_message_days=0)
            self.dispatch_event("member_remove", author, Action.Ban.value, reason)
        elif action == Action.Kick:
            reason = "Posting an invite link (Defender autokick)"
            await guild.kick(author, reason=reason)
            self.dispatch_event("member_remove", author, Action.Kick.value, reason)
        elif action == Action.Softban:
            reason = "Posting an invite link (Defender autokick)"
            await guild.ban(author, reason=reason, delete_message_days=1)
            await guild.unban(author)
            self.dispatch_event("member_remove", author, Action.Softban.value, reason)
        elif action == Action.Punish:
            punish_role = guild.get_role(await self.config.guild(guild).punish_role())
            punish_message = await self.config.guild(guild).punish_message()
            if punish_role and not self.is_role_privileged(punish_role):
                await author.add_roles(punish_role, reason="Defender: punish role assignation")
                if punish_message:
                    await message.channel.send(f"{author.mention} {punish_message}")
            else:
                self.send_to_monitor(guild, "[InviteFilter] Failed to punish user. Is the punish role "
                                            "still present and with *no* privileges?")
                return
        elif action == Action.NoAction:
            return await self.send_notification(guild, f"I have deleted a message with this content:\n{content}",
                                                title=EMBED_TITLE, fields=EMBED_FIELDS, jump_to=message)
        else:
            raise ValueError("Invalid action for invite filter")

        await self.send_notification(guild, f"I have {ACTIONS_VERBS[action]} a user for posting this message:\n{content}",
                                     title=EMBED_TITLE, fields=EMBED_FIELDS, jump_to=message)

        await modlog.create_case(
            self.bot,
            guild,
            message.created_at,
            action.value,
            author,
            guild.me,
            "Posting an invite link",
            until=None,
            channel=None,
        )

        return True

    async def detect_raider(self, message):
        author = message.author
        guild = author.guild
        EMBED_TITLE = "🦹 • Raider detection"
        EMBED_FIELDS = [{"name": "Username", "value": f"`{author}`"},
                        {"name": "ID", "value": f"`{author.id}`"},
                        {"name": "Channel", "value": message.channel.mention}]

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

        action = Action(await self.config.guild(guild).raider_detection_action())

        if action == Action.Ban:
            delete_days = await self.config.guild(guild).raider_detection_wipe()
            reason = "Message spammer (Defender autoban)"
            await guild.ban(author, reason=reason, delete_message_days=delete_days)
            self.dispatch_event("member_remove", author, Action.Ban.value, reason)
        elif action == Action.Kick:
            reason = "Message spammer (Defender autokick)"
            await guild.kick(author, reason=reason)
            self.dispatch_event("member_remove", author, Action.Kick.value, reason)
        elif action == Action.Softban:
            reason = "Message spammer (Defender autokick)"
            await guild.ban(author, reason=reason, delete_message_days=1)
            await guild.unban(author)
            self.dispatch_event("member_remove", author, Action.Softban.value, reason)
        elif action == Action.NoAction:
            heat_key = f"core-rd-{author.id}"
            if not heat.get_custom_heat(guild, heat_key) == 0:
                return
            await self.send_notification(guild,
                                        f"User {author} ({author.id}) is spamming messages ({recent} "
                                        f"messages in {minutes} minutes).",
                                        title=EMBED_TITLE,
                                        jump_to=message,
                                        ping=True)
            heat.increase_custom_heat(guild, heat_key, datetime.timedelta(minutes=15))
            return
        elif action == Action.Punish:
            punish_role = guild.get_role(await self.config.guild(guild).punish_role())
            punish_message = await self.config.guild(guild).punish_message()
            if punish_role and not self.is_role_privileged(punish_role):
                await author.add_roles(punish_role, reason="Defender: punish role assignation")
                if punish_message:
                    await message.channel.send(f"{author.mention} {punish_message}")
            else:
                self.send_to_monitor(guild, "[RaiderDetection] Failed to punish user. Is the punish role "
                                            "still present and with *no* privileges?")
                return
        else:
            raise ValueError("Invalid action for raider detection")

        await modlog.create_case(
            self.bot,
            guild,
            message.created_at,
            action.value,
            author,
            guild.me,
            "Message spammer",
            until=None,
            channel=None,
        )
        past_messages = await self.make_message_log(author, guild=author.guild)
        log = "\n".join(past_messages[:40])
        f = discord.File(BytesIO(log.encode("utf-8")), f"{author.id}-log.txt")
        await self.send_notification(guild, f"I have {ACTIONS_VERBS[action]} a user for posting {recent} "
                                     f"messages in {minutes} minutes. Attached their last stored messages.", file=f,
                                     title=EMBED_TITLE, fields=EMBED_FIELDS, jump_to=message)
        return True

    async def join_monitor_flood(self, member):
        EMBED_TITLE = "🔎🕵️ • Join monitor"
        guild = member.guild

        if guild.id not in self.joined_users:
            self.joined_users[guild.id] = deque([], maxlen=100)

        cache = self.joined_users[guild.id]
        cache.append(member)

        users = await self.config.guild(guild).join_monitor_n_users()
        minutes = await self.config.guild(guild).join_monitor_minutes()
        x_minutes_ago = member.joined_at - datetime.timedelta(minutes=minutes)

        recent_users = 0

        for m in cache:
            if m.joined_at > x_minutes_ago:
                recent_users += 1

        if recent_users >= users:
            heat_key = "core-jm"
            if not heat.get_custom_heat(guild, heat_key) == 0:
                return

            await self.send_notification(guild,
                                         f"Abnormal influx of new users ({recent_users} in the past "
                                         f"{minutes} minutes). Possible raid ongoing or about to start.",
                                         title=EMBED_TITLE, ping=True)
            heat.increase_custom_heat(guild, heat_key, datetime.timedelta(minutes=15))
            return True

    async def join_monitor_suspicious(self, member):
        EMBED_TITLE = "🔎🕵️ • Join monitor"
        EMBED_FIELDS = [{"name": "Username", "value": f"`{member}`"},
                        {"name": "ID", "value": f"`{member.id}`"},
                        {"name": "Account created", "value": member.created_at.strftime("%Y/%m/%d %H:%M:%S")},
                        {"name": "Joined this server", "value": member.joined_at.strftime("%Y/%m/%d %H:%M:%S")}]
        guild = member.guild
        hours = await self.config.guild(guild).join_monitor_susp_hours()

        delta = member.joined_at - member.created_at
        description = f"A {humanize_timedelta(timedelta=delta)} old user just joined the server."
        avatar = member.avatar_url_as(static_format="png")

        if hours:
            x_hours_ago = member.joined_at - datetime.timedelta(hours=hours)
            if member.created_at > x_hours_ago:
                footer = "To turn off these notifications do `[p]dset joinmonitor notifynew 0` (admin only)"
                try:
                    await self.send_notification(guild, description, title=EMBED_TITLE, fields=EMBED_FIELDS,
                                                 thumbnail=avatar, footer=footer)
                except (discord.Forbidden, discord.HTTPException):
                    pass

        description = f"A {humanize_timedelta(timedelta=delta)} old user just joined the server {guild.name}."
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
                footer = "To turn off these notifications do `[p]def notifynew 0` in the server."
                try:
                    await self.send_notification(user, description, title=EMBED_TITLE, fields=EMBED_FIELDS,
                                                 thumbnail=avatar, footer=footer)
                except (discord.Forbidden, discord.HTTPException):
                    pass

    async def comment_analysis(self, message):
        guild = message.guild
        author = message.author
        EMBED_TITLE = "💬 • Comment analysis"
        EMBED_FIELDS = [{"name": "Username", "value": f"`{author}`"},
                        {"name": "ID", "value": f"`{author.id}`"},
                        {"name": "Channel", "value": message.channel.mention}]

        body = {
            "comment": {
                "text": message.content
            },
            "requestedAttributes": {},
            "doNotStore": True,
        }

        token = await self.config.guild(guild).ca_token()
        attributes = await self.config.guild(guild).ca_attributes()
        threshold = await self.config.guild(guild).ca_threshold()

        for attribute in attributes:
            body["requestedAttributes"][attribute] = {}

        async with aiohttp.ClientSession() as session:
            async with session.post(PERSPECTIVE_API_URL.format(token), json=body, timeout=AIOHTTP_TIMEOUT) as r:
                if r.status == 200:
                    results = await r.json()
                else:
                    if r.status != 400:
                        # Not explicitly documented but if the API doesn't recognize the language error 400 is returned
                        # We can safely ignore those cases
                        log.error("Error querying Perspective API")
                        log.debug(f"Sent: '{message.content}', received {r.status}")
                    return

        scores = results["attributeScores"]
        for attribute in scores:
            attribute_score = scores[attribute]["summaryScore"]["value"] * 100
            if attribute_score >= threshold:
                triggered_attribute = attribute
                break
        else:
            return

        action = Action(await self.config.guild(guild).ca_action())

        sanitized_content = message.content.replace("`", "'")
        exp_text = f"I have {ACTIONS_VERBS[action]} the user for this message.\n" if action != Action.NoAction else ""
        text = (f"Possible rule breaking message detected. {exp_text}"
                f'The following message scored {round(attribute_score, 2)}% in the **{triggered_attribute}** category:\n'
                f"{box(sanitized_content)}")

        if action == Action.NoAction:
            heat_key = f"core-ca-{message.channel.id}-{author.id}"
            if heat.get_custom_heat(guild, heat_key) == 0:
                await self.send_notification(guild, text, title=EMBED_TITLE, fields=EMBED_FIELDS, jump_to=message)
                heat.increase_custom_heat(guild, heat_key, datetime.timedelta(minutes=15))
            return

        reason = await self.config.guild(guild).ca_reason()

        if action == Action.Ban:
            delete_days = await self.config.guild(guild).ca_wipe()
            await guild.ban(author, reason=reason, delete_message_days=delete_days)
            self.dispatch_event("member_remove", author, Action.Ban.value, reason)
        elif action == Action.Kick:
            await guild.kick(author, reason=reason)
            self.dispatch_event("member_remove", author, Action.Kick.value, reason)
        elif action == Action.Softban:
            await guild.ban(author, reason=reason, delete_message_days=1)
            await guild.unban(author)
            self.dispatch_event("member_remove", author, Action.Softban.value, reason)
        elif action == Action.Punish:
            punish_role = guild.get_role(await self.config.guild(guild).punish_role())
            punish_message = await self.config.guild(guild).punish_message()
            if punish_role and not self.is_role_privileged(punish_role):
                await author.add_roles(punish_role, reason="Defender: punish role assignation")
                if punish_message:
                    await message.channel.send(f"{author.mention} {punish_message}")
            else:
                self.send_to_monitor(guild, "[CommentAnalysis] Failed to punish user. Is the punish role "
                                            "still present and with *no* privileges?")
                return

        await self.send_notification(guild, text, title=EMBED_TITLE, fields=EMBED_FIELDS, jump_to=message)

        try:
            await message.delete()
        except:
            pass

        await modlog.create_case(
            self.bot,
            guild,
            message.created_at,
            action.value,
            author,
            guild.me,
            reason,
            until=None,
            channel=None,
        )
