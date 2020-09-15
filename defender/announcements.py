import discord
from datetime import datetime

REPO_LINK = "https://github.com/Twentysix26/x26-Cogs"
WARDEN_URL = "https://github.com/Twentysix26/x26-Cogs/wiki/Warden"
WARDEN_ANNOUNCEMENT = ("Hello. There is a new auto-module available: **Warden**.\nThis auto-module allows you to define "
                       "complex rules to better monitor, manage and moderate your community.\nIt is now the most "
                       f"versatile module that Defender features and by following the [guide]({WARDEN_URL}) "
                       "you will learn how to leverage its full potential in no time. For any suggestion feel free to "
                       f"open an issue in my [repository]({REPO_LINK}).\n\n"
                       "Also, as a small quality of life improvement, the `[p]defender` command has been aliased to "
                       "`[p]def` (using the standard alias cog would cause some issues).\n\n"
                       "I hope you're enjoying Defender as much as I enjoyed creating it.")

ANNOUNCEMENTS = {
    1601078404 : WARDEN_ANNOUNCEMENT
}

def _make_announcement_embed(content):
    em = discord.Embed(color=discord.Colour.red(), description=content)
    em.set_author(name="Defender update")
    em.set_footer(text="A message from 26, creator of Defender")
    return em

def get_new_announcements():
    to_send = {}
    now = datetime.utcnow()

    for k, v in ANNOUNCEMENTS.items():
        ts = datetime.utcfromtimestamp(k)
        if now > ts: # The announcement is old
            continue
        to_send[k] = _make_announcement_embed(v)

    return to_send