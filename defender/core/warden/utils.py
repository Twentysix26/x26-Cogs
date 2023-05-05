from rapidfuzz import fuzz, process
from redbot.core.utils import AsyncIter
import emoji
import regex as re
import discord
import logging
import functools
import asyncio
import multiprocessing

EMOJI_RE = re.compile(r'<a?:[a-zA-Z0-9\_]+:([0-9]+)>')
REMOVE_C_EMOJIS_RE = re.compile(r'<a?:[a-zA-Z0-9\_]+:[0-9]+>')

log = logging.getLogger("red.x26cogs.defender")

# Based on d.py's EmojiConverter
# https://github.com/Rapptz/discord.py/blob/master/discord/ext/commands/converter.py

def has_x_or_more_emojis(bot: discord.Client, guild: discord.Guild, text: str, limit: int):
    n = emoji.emoji_count(text)

    if n >= limit:
        return True

    if "<" in text: # No need to run a regex if no custom emoji can be present
        n += len(list(re.finditer(EMOJI_RE, text)))

    return n >= limit

async def run_user_regex(*, rule_obj, cog, guild: discord.Guild, regex: str, text: str):
    # This implementation is similar to what reTrigger does for safe-ish user regex. Thanks Trusty!
    # https://github.com/TrustyJAID/Trusty-cogs/blob/4d690f6ce51c1c5ebf98a2e05ff504ea26eac30b/retrigger/triggerhandler.py
    allowed = await cog.config.wd_regex_allowed()
    safety_checks_enabled = await cog.config.wd_regex_safety_checks()

    if not allowed:
        return False

    # TODO This section might benefit from locks in case of faulty rules?

    if safety_checks_enabled:
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
                                            f"Please fix it to prevent this from happening again in the future.", title="👮 • Warden")
            return False
        except Exception as e:
            log.error("Warden - Unexpected error while running user defined regex", exc_info=e)
            return False
        else:
            return bool(result)
    else:
        try:
            return bool(re.search(regex, text))
        except Exception as e:
            log.error(f"Warden - Unexpected error while running user defined regex with no safety checks", exc_info=e)
            return False

def make_fuzzy_suggestion(term, _list):
    result = process.extract(term, _list, limit=1, scorer=fuzz.QRatio)
    result = [r for r in result if r[1] > 10]
    if result:
        return f" Did you mean `{result[0][0]}`?"
    else:
        return ""

async def delete_message_after(message: discord.Message, sleep_for: int):
    await asyncio.sleep(sleep_for)
    try:
        await message.delete()
    except:
        pass

async def rule_add_periodic_prompt(*, cog, message: discord.Message, new_rule):
    confirm_emoji = "✅"
    guild = message.guild
    affected = 0
    channel = message.channel
    async with channel.typing():
        msg: discord.Message = await channel.send("Checking your new rule... Please wait and watch this message for updates.")

        def confirm(r, user):
            return user == message.author and str(r.emoji) == confirm_emoji and r.message.id == msg.id

        async for m in AsyncIter(guild.members, steps=2):
            if m.bot:
                continue
            if m.joined_at is None:
                continue
            rank = await cog.rank_user(m)
            if await new_rule.satisfies_conditions(rank=rank, user=m, guild=guild, cog=cog):
                affected += 1

    if affected >= 10 or affected >= len(guild.members) / 2:
        await msg.edit(content=f"You're adding a periodic rule. At the first run {affected} users will be affected. "
                                "Are you sure you want to continue?")
        await msg.add_reaction(confirm_emoji)
        try:
            await cog.bot.wait_for('reaction_add', check=confirm, timeout=15)
        except asyncio.TimeoutError:
            await channel.send("Not adding the rule.")
            return False
        else:
            return True
    else:
        await msg.edit(content="Safety checks passed.")
        return True

async def rule_add_overwrite_prompt(*, cog, message: discord.Message):
    save_emoji = "💾"
    channel = message.channel
    msg = await channel.send("There is a rule with the same name already. Do you want to "
                            "overwrite it? React to confirm.")

    def confirm(r, user):
        return user == message.author and str(r.emoji) == save_emoji and r.message.id == msg.id

    await msg.add_reaction(save_emoji)
    try:
        r = await cog.bot.wait_for('reaction_add', check=confirm, timeout=15)
    except asyncio.TimeoutError:
        await channel.send("Not proceeding with overwrite.")
        return False
    else:
        return True

def strip_yaml_codeblock(code: str):
    code = code.strip("\n")
    if code.startswith(("```yaml", "```YAML")):
        code = code.lstrip("`yamlYAML")
    if code.startswith(("```yml", "```YML")):
        code = code.lstrip("`ymlYML")
    if code.startswith("```") or code.endswith("```"):
        code = code.strip("`")

    return code