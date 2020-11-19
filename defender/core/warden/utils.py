import emoji
import re
import discord
import logging

EMOJI_RE = re.compile(r'<a?:[a-zA-Z0-9\_]+:([0-9]+)>')

log = logging.getLogger("red.x26cogs.defender")

# Based on d.py's EmojiConverter
# https://github.com/Rapptz/discord.py/blob/master/discord/ext/commands/converter.py

def has_x_or_more_emojis(bot: discord.Client, guild: discord.Guild, text: str, limit: int):
    n = emoji.emoji_count(text)

    if n >= limit:
        return True

    if "<" not in text: # No need to run a regex if no custom emoji can be present
        return False

    for m in re.finditer(EMOJI_RE, text):
        emoji_id = int(m.group(1))

        if discord.utils.get(guild.emojis, id=emoji_id):
            n += 1
        else:
            if discord.utils.get(bot.emojis, id=emoji_id):
                n += 1

        if n == limit:
            return True

    return False