"""
Defender - Protects your community with automod features and
           empowers the staff and users you trust with
           advanced moderation tools
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
from ..enums import Action, EmergencyModules

DOCS_BASE_URL = "https://twentysix26.github.io/defender-docs"
WD_CHECKS = f"[Warden checks]({DOCS_BASE_URL}/#warden-checks): " "**{}**"

async def make_status(ctx, cog):
    def is_active(arg):
        return "active" if bool(arg) else "not active"

    pages = []
    guild = ctx.guild
    d_enabled = await cog.config.guild(guild).enabled()
    n_channel = guild.get_channel(await cog.config.guild(guild).notify_channel())
    can_sm_in_n_channel = None
    can_rm_in_n_channel = None
    if n_channel:
        can_sm_in_n_channel = n_channel.permissions_for(guild.me).send_messages
        can_rm_in_n_channel = n_channel.permissions_for(guild.me).read_messages

    n_role = guild.get_role(await cog.config.guild(guild).notify_role())
    can_ban = ctx.channel.permissions_for(guild.me).ban_members
    can_kick = ctx.channel.permissions_for(guild.me).kick_members
    can_read_al = ctx.channel.permissions_for(guild.me).view_audit_log
    can_see_own_invites = True
    punish_role = guild.get_role(await cog.config.guild(guild).punish_role())
    if not guild.me.guild_permissions.manage_guild:
        if await cog.config.guild(guild).invite_filter_enabled():
            exclude_own = await cog.config.guild(guild).invite_filter_exclude_own_invites()
            if exclude_own:
                can_see_own_invites = False

    msg = ("This is an overview of the status and the general settings.\n*Notify role* is the "
            "role that gets pinged in case of urgent matters.\n*Notify channel* is where I send "
            "notifications about reports and actions I take.\n*Punish role* is the role that I "
            "will assign to misbehaving users if the \"action\" of a Defender module is "
            "set to \"punish\".\n\n")

    admin_roles = await ctx.bot._config.guild(ctx.guild).admin_role()
    mod_roles = await ctx.bot._config.guild(ctx.guild).mod_role()
    has_core_roles_set = bool(admin_roles) or bool(mod_roles)

    _not = "NOT " if not d_enabled else ""
    msg += f"[Defender]({DOCS_BASE_URL}) is **{_not}operational**.\n\n"

    p = ctx.prefix

    if not has_core_roles_set:
        msg += (f"**Configuration issue:** Core admin / mod roles are not set: see {p}set showsettings / "
                f"{p}help set\n")
    if not n_channel:
        msg += f"**Configuration issue:** Notify channel not set ({p}dset general notifychannel)\n"
    if can_sm_in_n_channel is False or can_rm_in_n_channel is False:
        msg += "**Configuration issue:** I cannot read and/or send messages in the notify channel.\n"
    if not n_role:
        msg += f"**Configuration issue:** Notify role not set ({p}dset general notifyrole)\n"
    if not can_see_own_invites:
        msg += "**Configuration issue:** I need 'Manage server' permissions to see our own invites.\n"
    if not can_ban:
        msg += "**Possible configuration issue:** I'm not able to ban in this server.\n"
    if not can_kick:
        msg += "**Possible configuration issue:** I'm not able to kick in this server.\n"
    if not can_read_al:
        msg += ("**Possible configuration issue:** I'm not able to see the audit log in this server. "
                "I may need this to detect staff activity.\n")
    if not d_enabled:
        msg += ("**Warning:** Since the Defender system is **off** every module will be shown as "
                "disabled, regardless of individual settings.\n")

    em = discord.Embed(color=discord.Colour.red(), description=msg)
    em.set_footer(text=f"`{p}dset general` to configure")
    em.set_author(name=f"Defender system v{cog.__version__}", url=DOCS_BASE_URL)
    em.add_field(name="Notify role", value=n_role.mention if n_role else "None set", inline=True)
    em.add_field(name="Notify channel", value=n_channel.mention if n_channel else "None set", inline=True)
    em.add_field(name="Punish role", value=punish_role.mention if punish_role else "None set", inline=True)

    pages.append(em)

    days = await cog.config.guild(guild).rank3_joined_days()

    msg = ("To grant you more granular control on *who* I should target "
            "and monitor I categorize the userbase in **ranks**.\n\n"
            "**Rank 1** are staff, trusted roles and helper roles\n**Rank 2** are "
            "regular users.\n**Rank 3** are users who joined this server "
            f"less than *{days} days ago*.\n")

    is_counting = await cog.config.guild(guild).count_messages()
    if is_counting:
        messages = await cog.config.guild(guild).rank3_min_messages()
        rank4_text = (f"**Rank 4** are users who joined less than *{days} days ago* "
                        f"and also have sent less than *{messages}* messages in this "
                        "server.\n\n")
    else:
        rank4_text = ("Currently there is no **Rank 4** because *message counting* "
                        "in this server is disabled.\n\n")

    msg += rank4_text

    msg += ("When setting the target rank of a module, that rank and anything below that will be "
            "targeted. Setting Rank 3 as a target, for example, means that Rank 3 and Rank 4 will be "
            "considered valid targets.\n\n")

    helpers = (f"**Helper roles** are users who are able to use `{p}alert` to report "
                "problems that need your attention.\nIf you wish, you can also enable "
                "*emergency mode*: if no staff activity is detected in a set time window "
                "after an *alert* is issued, helper roles will be granted access to modules "
                "that may help them in taking care of bad actors by themselves.\n")

    em_modules = await cog.config.guild(guild).emergency_modules()
    minutes = await cog.config.guild(guild).emergency_minutes()

    helpers += "Currently "
    if not em_modules:
        helpers += ("no modules are set to be available in *emergency mode* and as such it is disabled. "
                    "Some manual modules can be set to be used in *emergency mode* if you wish.\n\n")
    else:
        em_modules = [f"**{m}**" for m in em_modules]
        helpers += ("the modules " + ", ".join(em_modules))
        helpers += (f" will be available to helper roles after **{minutes} minutes** of staff inactivity "
                    "following an alert.\n\n")

    msg += helpers

    trusted = await cog.config.guild(guild).trusted_roles()
    helper = await cog.config.guild(guild).helper_roles()
    trusted_roles = []
    helper_roles = []

    for r in guild.roles:
        if r.id in trusted:
            trusted_roles.append(r.mention)
        if r.id in helper:
            helper_roles.append(r.mention)

    if not trusted_roles:
        trusted_roles = ["None set."]
    if not helper_roles:
        helper_roles = ["None set."]

    msg += "Trusted roles: " + " ".join(trusted_roles) + "\n"
    msg += "Helper roles: " + " ".join(helper_roles)

    em = discord.Embed(color=discord.Colour.red(), description=msg)
    em.set_footer(text=f"See `{p}dset rank3` `{p}dset general` `{p}dset emergency`")
    em.set_author(name="Ranks and helper roles")

    pages.append(em)

    enabled = False
    if d_enabled:
        enabled = await cog.config.guild(guild).raider_detection_enabled()

    rank = await cog.config.guild(guild).raider_detection_rank()
    messages = await cog.config.guild(guild).raider_detection_messages()
    minutes = await cog.config.guild(guild).raider_detection_minutes()
    action = Action(await cog.config.guild(guild).raider_detection_action())
    wipe = await cog.config.guild(guild).raider_detection_wipe()
    if action == Action.NoAction:
        action = "**notify** the staff about it"
    else:
        action = f"**{action.value}** them"


    msg = ("**Raider detection   🦹**\nThis auto-module is designed to counter raiders. It can detect large "
            "amounts of messages in a set time window and take action on the user.\n")
    msg += (f"It is set so that if a **Rank {rank}** user (or below) sends **{messages} messages** in "
            f"**{minutes} minutes** I will {action}.\n")
    if action == Action.Ban and wipe:
        msg += f"The **ban** will also delete **{wipe} days** worth of messages.\n"
    msg += f"{WD_CHECKS.format(is_active(await cog.config.guild(guild).raider_detection_wdchecks()))}\n"
    msg += "This module is currently "
    msg += "**enabled**.\n\n" if enabled else "**disabled**.\n\n"

    if d_enabled:
        enabled = await cog.config.guild(guild).invite_filter_enabled()
    rank = await cog.config.guild(guild).invite_filter_rank()
    action = await cog.config.guild(guild).invite_filter_action()
    own_invites = await cog.config.guild(guild).invite_filter_exclude_own_invites()
    if own_invites:
        oi_text = "Users are **allowed** to post invites that belong to this server."
        if not guild.me.guild_permissions.manage_guild:
            oi_text += " However I lack the 'Manage guild' permission. I need that to see our own invites."
    else:
        oi_text = "I will take action on **any invite**, even when they belong to this server."

    if action == "none":
        action = "**target** any user"
    else:
        action = f"**{action}** any user"

    if await cog.config.guild(guild).invite_filter_delete_message():
        action_msg = "I will also **delete** the invite's message."
    else:
        action_msg = "I will **not delete** the invite's message."

    msg += ("**Invite filter   🔥📧**\nThis auto-module is designed to take care of advertisers. It can detect "
            f"a standard Discord invite and take action on the user.\nIt is set so that I will {action} "
            f"who is **Rank {rank}** or below. {action_msg} {oi_text}\n")
    msg += f"{WD_CHECKS.format(is_active(await cog.config.guild(guild).invite_filter_wdchecks()))}\n"
    msg += "This module is currently "
    msg += "**enabled**.\n\n" if enabled else "**disabled**.\n\n"

    if d_enabled:
        enabled = await cog.config.guild(guild).join_monitor_enabled()
    users = await cog.config.guild(guild).join_monitor_n_users()
    minutes = await cog.config.guild(guild).join_monitor_minutes()
    newhours = await cog.config.guild(guild).join_monitor_susp_hours()
    v_level = await cog.config.guild(guild).join_monitor_v_level()

    msg += ("**Join monitor   🔎🕵️**\nThis auto-module is designed to report suspicious user joins. It is able "
            "to detect an abnormal influx of new users and report any account that has been recently "
            "created.\n")
    msg += (f"It is set so that if **{users} users** join in the span of **{minutes} minutes** I will notify "
            "the staff with a ping.\n")
    if v_level:
        msg += ("Additionally I will raise the server's verification level to "
                f"**{discord.VerificationLevel(v_level)}**.\n")
    else:
        msg += ("I will **not** raise the server's verification level.\n")
    if newhours:
        msg += f"I will also report any new user whose account is less than **{newhours} hours old**.\n"
    else:
        msg += "Newly created accounts notifications are **off**.\n"
    msg += f"{WD_CHECKS.format(is_active(await cog.config.guild(guild).join_monitor_wdchecks()))}\n"
    msg += "This module is currently "
    msg += "**enabled**.\n\n" if enabled else "**disabled**.\n\n"

    em = discord.Embed(color=discord.Colour.red(), description=msg)
    em.set_footer(text=f"`{p}dset raiderdetection` `{p}dset invitefilter` `{p}dset joinmonitor` to configure.")
    em.set_author(name="Auto modules (1/2)")

    pages.append(em)

    if d_enabled:
        enabled = await cog.config.guild(guild).warden_enabled()
    active_rules = len(cog.active_warden_rules[guild.id])
    invalid_rules = len(cog.invalid_warden_rules[guild.id])
    total_rules = active_rules + invalid_rules
    warden_guide = f"{DOCS_BASE_URL}/warden/overview/"
    invalid_text = ""
    if invalid_rules:
        invalid_text = f", **{invalid_rules}** of which are invalid"

    wd_periodic = "allowed" if await cog.config.wd_periodic_allowed() else "not allowed"
    wd_regex = "allowed" if await cog.config.wd_regex_allowed() else "not allowed"

    msg = ("**Warden   👮**\nThis auto-module is extremely versatile. Thanks to a rich set of  "
            "*events*, *conditions* and *actions* that you can combine Warden allows you to define "
            "custom rules to counter any common pattern of bad behaviour that you notice in your "
            "community.\nMessage filtering, assignation of roles to misbehaving users, "
            "custom staff alerts are only a few examples of what you can accomplish "
            f"with this powerful module.\nYou can learn more [here]({warden_guide}).\n")
    msg += (f"The creation of periodic Warden rules is **{wd_periodic}**.\n")
    msg += (f"The use of regex in Warden rules is **{wd_regex}**.\n")
    msg += (f"There are a total of **{total_rules}** rules defined{invalid_text}.\n")
    msg += "This module is currently "
    msg += "**enabled**.\n\n" if enabled else "**disabled**.\n\n"

    PERSPECTIVE_URL = "https://www.perspectiveapi.com/"
    PERSPECTIVE_API_URL = "https://developers.perspectiveapi.com/s/docs-get-started"
    ca_token = await cog.config.guild(guild).ca_token()
    if ca_token:
        ca_token = f"The API key is currently set: **{ca_token[:3]}...{ca_token[len(ca_token)-3:]}**"
    else:
        ca_token = f"The API key is **NOT** set. Get one [here]({PERSPECTIVE_API_URL})"

    ca_action = Action(await cog.config.guild(guild).ca_action())
    ca_wipe = await cog.config.guild(guild).ca_wipe()
    ca_show_single_deletion = True
    if ca_action == Action.Ban:
        if ca_wipe:
            ca_show_single_deletion = False
            ca_action = f"**ban** the author and **delete {ca_wipe} days** worth of messages"
        else:
            ca_action = f"**ban** the author"
    elif ca_action == Action.Softban:
        ca_show_single_deletion = False
        ca_action = f"**softban** the author"
    elif ca_action == Action.NoAction:
        ca_action = "**notify** the staff"
    else:
        ca_action = f"**{ca_action.value}** the author"

    ca_message_delete = await cog.config.guild(guild).ca_delete_message()
    ca_del = ""
    if ca_show_single_deletion:
        if ca_message_delete:
            ca_del = " and **delete** it"
        else:
            ca_del = " and **not delete** it"

    ca_rank = await cog.config.guild(guild).ca_rank()
    ca_attributes = len(await cog.config.guild(guild).ca_attributes())
    ca_threshold = await cog.config.guild(guild).ca_threshold()
    enabled = await cog.config.guild(guild).ca_enabled()

    msg += ("**Comment analysis    💬**\nThis automodule interfaces with Google's "
            f"[Perspective API]({PERSPECTIVE_URL}) to analyze the messages in your server and "
            "detect abusive content.\nIt supports a variety of languages and it is a powerful tool "
            "for monitoring and prevention. Be mindful of *false positives*: context is not taken "
            f"in consideration.\n{ca_token}.\nIt is set so that if I detect an abusive message I will "
            f"{ca_action}{ca_del}. The offending user must be **Rank {ca_rank}** or below.\nI will take action "
            f"only if the **{ca_threshold}%** threshold is reached for any of the **{ca_attributes}** "
            f"attribute(s) that have been set.\n")
    msg += f"{WD_CHECKS.format(is_active(await cog.config.guild(guild).ca_wdchecks()))}\n"
    msg += "This module is currently "
    msg += "**enabled**.\n\n" if enabled else "**disabled**.\n\n"

    em = discord.Embed(color=discord.Colour.red(), description=msg)
    em.set_footer(text=f"`{p}dset warden` `{p}def warden` `{p}dset commentanalysis` to configure.")
    em.set_author(name="Auto modules (2/2)")

    pages.append(em)

    if d_enabled:
        enabled = await cog.config.guild(guild).alert_enabled()
    em_modules = await cog.config.guild(guild).emergency_modules()
    minutes = await cog.config.guild(guild).emergency_minutes()

    msg = ("**Alert   🚨**\nThis manual module is designed to aid helper roles in reporting bad actors to "
            f"the staff. Upon issuing the `{p}alert` command the staff will get pinged in the set notification "
            "channel and will be given context from where the alert was issued.\nFurther, if any manual module is "
            "set to be used in case of staff inactivity (*emergency mode*), they will be rendered available to "
            "helper roles after the set time window.\n")
    if em_modules:
        msg += (f"It is set so that the modules **{', '.join(em_modules)}** will be rendered available to helper roles "
                f"after the staff has been inactive for **{minutes} minutes** following an alert.\n")
    else:
        msg += (f"No module is set to be used in *emergency mode*, therefore it cannot currently be triggered.\n")
    msg += "This module is currently "
    msg += "**enabled**.\n\n" if enabled else "**disabled**.\n\n"

    if d_enabled:
        enabled = await cog.config.guild(guild).vaporize_enabled()

    v_max_targets = await cog.config.guild(guild).vaporize_max_targets()
    msg += ("**Vaporize   ☁️**\nThis manual module is designed to get rid of vast amounts of bad actors in a quick way "
            "without creating a mod-log entry. To prevent misuse only **Rank 3** and below are targetable by this "
            f"module. A maximum of **{v_max_targets}** users can be vaporized at once. This module can be rendered available "
            "to helper roles in *emergency mode*.\n")
    if EmergencyModules.Vaporize.value in em_modules:
        msg += "It is set to be rendered available to helper roles in *emergency mode*.\n"
    else:
        msg += "It is not set to be available in *emergency mode*.\n"
    msg += "This module is currently "
    msg += "**enabled**.\n\n" if enabled else "**disabled**.\n\n"

    if d_enabled:
        enabled = await cog.config.guild(guild).silence_enabled()

    rank_silenced = await cog.config.guild(guild).silence_rank()

    msg += ("**Silence   🔇**\nThis manual module allows to enable auto-deletion of messages for the selected ranks.\n"
            "It can be rendered available to helper roles in *emergency mode*.\n")
    if rank_silenced:
        msg += (f"It is set to silence **Rank {rank_silenced}** and below.\n")
    else:
        msg += ("No rank is set to be silenced.\n")
    if EmergencyModules.Silence.value in em_modules:
        msg += "It is set to be rendered available to helper roles in *emergency mode*.\n"
    else:
        msg += "It is not set to be available in *emergency mode*.\n"
    msg += "This module is currently "
    msg += "**enabled**.\n\n" if enabled else "**disabled**.\n\n"

    em = discord.Embed(color=discord.Colour.red(), description=msg)
    em.set_footer(text=f"`{p}dset alert` `{p}dset vaporize` `{p}dset silence` `{p}dset emergency` to configure.")
    em.set_author(name="Manual modules (1/2)")

    pages.append(em)

    if d_enabled:
        enabled = await cog.config.guild(guild).voteout_enabled()

    votes = await cog.config.guild(guild).voteout_votes()
    rank = await cog.config.guild(guild).voteout_rank()
    action = await cog.config.guild(guild).voteout_action()
    wipe = await cog.config.guild(guild).voteout_wipe()

    msg = ("**Voteout   👍 👎**\nThis manual module allows to start a voting session to expel a user from the "
           "server. It is most useful to helper roles, however staff can also use this.\n"
           "It can be rendered available to helper roles in *emergency mode*.\n")
    msg += (f"It is set so that **{votes} votes** (including the issuer) are required to **{action}** "
            f"the target user, which must be **Rank {rank}** or below.")
    if Action(action) == Action.Ban and wipe:
        msg += f"\nThe **ban** will also delete **{wipe} days** worth of messages."
    msg += "\n"
    if EmergencyModules.Voteout.value in em_modules:
        msg += "It is set to be rendered available to helper roles in *emergency mode*.\n"
    else:
        msg += "It is not set to be available in *emergency mode*.\n"
    msg += "This module is currently "
    msg += "**enabled**.\n\n" if enabled else "**disabled**.\n\n"

    em = discord.Embed(color=discord.Colour.red(), description=msg)
    em.set_footer(text=f"`{p}dset voteout` `{p}dset emergency` to configure.")
    em.set_author(name="Manual modules (2/2)")

    pages.append(em)

    return pages
