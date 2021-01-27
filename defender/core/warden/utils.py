from fuzzywuzzy import fuzz, process
import emoji
import re
import discord
import logging
import functools
import asyncio
import multiprocessing
import datetime

EMOJI_RE = re.compile(r'<a?:[a-zA-Z0-9\_]+:([0-9]+)>')
REMOVE_C_EMOJIS_RE = re.compile(r'<a?:[a-zA-Z0-9\_]+:[0-9]+>')

utcnow = datetime.datetime.utcnow
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

async def run_user_regex(*, rule_obj, cog, guild: discord.Guild, regex: str, text: str):
    # This implementation is similar to what reTrigger does for safe-ish user regex. Thanks Trusty!
    # https://github.com/TrustyJAID/Trusty-cogs/blob/4d690f6ce51c1c5ebf98a2e05ff504ea26eac30b/retrigger/triggerhandler.py
    allowed = await cog.config.wd_regex_allowed()

    if not allowed:
        return False

    # TODO This section might benefit from locks in case of faulty rules?

    try:
        regex_obj = re.compile(regex) # type: ignore
        process = cog.wd_pool.apply_async(regex_obj.findall, (text,))
        task = functools.partial(process.get, timeout=3)
        new_task = cog.bot.loop.run_in_executor(None, task)
        result = await asyncio.wait_for(new_task, timeout=5)
    except (multiprocessing.TimeoutError, asyncio.TimeoutError):
        log.warning(f"Warden - User defined regex timed out. This rule has been disabled."
                    f"\nGuild: {guild.id}\nRegex: {regex}")
        cog.active_warden_rules[guild.id].pop(rule_obj.name, None)
        cog.invalid_warden_rules[guild.id][rule_obj.name] = rule_obj
        async with cog.config.guild(guild).wd_rules() as warden_rules:
            # There's no way to disable rules for now. So, let's just break it :D
            rule_obj.raw_rule = ":!!! Regex in this rule perform poorly. Fix the issue and remove this line !!!:\n" + rule_obj.raw_rule
            warden_rules[rule_obj.name] = rule_obj.raw_rule
        await cog.send_notification(guild, f"The Warden rule `{rule_obj.name}` has been disabled for poor regex performances. "
                                           f"Please fix it to prevent this from happening again in the future.")
        return False
    except Exception as e:
        log.error("Warden - Unexpected error while running user defined regex", exc_info=e)
        return False
    else:
        return bool(result)

def make_fuzzy_suggestion(term, _list):
    result = process.extract(term, _list, limit=1, scorer=fuzz.QRatio)
    result = [r for r in result if r[1] > 10]
    if result:
        return f" Did you mean `{result[0][0]}`?"
    else:
        return ""
