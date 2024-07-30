import discord
import typing

import logging

from ..enums import Rank, Action, PerspectiveAttributes as PAttr, EmergencyModules as EModules
from ..core.status import (
    get_status_msg,
    DOCS_BASE_URL,
    get_overview_msg,
    get_ranks_msg,
    get_helper_roles_msg,
    get_automatic_modules_msgs,
    get_manual_modules_msgs,
)

log = logging.getLogger("red.x26cogs.defender")


def dashboard_page(*args, **kwargs):
    def decorator(func: typing.Callable):
        func.__dashboard_decorator_params__ = (args, kwargs)
        return func

    return decorator


class SettingsIntegration:
    @dashboard_page(
        name="settings", description="Manage Defender settings.", methods=("GET", "POST")
    )
    async def dashboard_settings_page(
        self, user: discord.User, guild: discord.Guild, **kwargs
    ) -> typing.Dict[str, typing.Any]:
        member = guild.get_member(user.id)
        if (
            member is None
            or user.id != guild.owner.id
            and not await self.bot.is_admin(member)
            and user.id not in self.bot.owner_ids
        ):
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

        d_enabled, possible_config_issue, status_msg = await get_status_msg(guild, self)

        import wtforms

        settings = await self.config.guild(guild).all()

        overview_msg = get_overview_msg()

        class OverviewSettingsForm(kwargs["Form"]):
            def __init__(self) -> None:
                super().__init__(prefix="overview_settings_form_")

            enabled: wtforms.BooleanField = wtforms.BooleanField(
                "Enabled:", default=settings["enabled"]
            )
            notify_role: wtforms.SelectField = wtforms.SelectField(
                "Notify Role:",
                choices=kwargs["get_sorted_roles"](guild),
                default=str(settings["notify_role"]),
                validators=[
                    kwargs["DpyObjectConverter"](discord.Role),
                    wtforms.validators.Optional(),
                ],
            )
            notify_channel: wtforms.SelectField = wtforms.SelectField(
                "Notify Channel:",
                choices=kwargs["get_sorted_channels"](guild, (discord.TextChannel,)),
                default=str(settings["notify_channel"]),
                validators=[
                    kwargs["DpyObjectConverter"](discord.TextChannel),
                    wtforms.validators.Optional(),
                ],
            )
            punish_role: wtforms.SelectField = wtforms.SelectField(
                "Punish Role:",
                choices=kwargs["get_sorted_roles"](
                    guild,
                    filter_func=lambda role: not self.is_role_privileged(role, member.top_role),
                ),
                default=str(settings["punish_role"]),
                validators=[
                    kwargs["DpyObjectConverter"](discord.Role),
                    wtforms.validators.Optional(),
                ],
            )
            punish_message: wtforms.TextAreaField = wtforms.TextAreaField(
                "Punish Message:",
                default=settings["punish_message"],
                validators=[wtforms.validators.Length(max=1950)],
            )
            submit: wtforms.SubmitField = wtforms.SubmitField("Save Modifications")

        overview_settings_form = OverviewSettingsForm()
        if (
            overview_settings_form.validate_on_submit()
            and await overview_settings_form.validate_dpy_converters()
        ):
            notifications = []
            await self.config.guild(guild).enabled.set(overview_settings_form.enabled.data)
            if overview_settings_form.notify_role.data:
                await self.config.guild(guild).notify_role.set(
                    overview_settings_form.notify_role.data.id
                )
            else:
                await self.config.guild(guild).notify_role.clear()
            if overview_settings_form.notify_channel.data:
                await self.config.guild(guild).notify_channel.set(
                    overview_settings_form.notify_channel.data.id
                )
                everyone = guild.default_role
                if (
                    everyone not in overview_settings_form.notify_channel.data.overwrites
                    or overview_settings_form.notify_channel.data.overwrites[
                        everyone
                    ].read_messages
                    in (True, None)
                ):
                    notifications.append(
                        {
                            "message": "Channel set. However, that channel is public: a private one (staff-only) would be preferable as I might send sensitive data at some point (logs, etc).",
                            "category": "warning",
                        }
                    )
            else:
                await self.config.guild(guild).notify_channel.clear()
            if overview_settings_form.punish_role.data:
                await self.config.guild(guild).punish_role.set(
                    overview_settings_form.punish_role.data.id
                )
            else:
                await self.config.guild(guild).punish_role.clear()
            if overview_settings_form.punish_message.data:
                await self.config.guild(guild).punish_message.set(
                    overview_settings_form.punish_message.data
                )
            else:
                await self.config.guild(guild).punish_message.clear()
            notifications.append(
                {
                    "message": "The modifications have been successfully saved.",
                    "category": "success",
                }
            )
            return {
                "status": 0,
                "notifications": notifications,
                "redirect_url": kwargs["request_url"],
            }

        ranks_msg = await get_ranks_msg(guild, self)

        class RanksSettingsForm(kwargs["Form"]):
            def __init__(self) -> None:
                super().__init__(prefix="ranks_settings_form_")

            rank3_min_messages: wtforms.IntegerField = wtforms.IntegerField(
                "Rank 3 Min Messages:",
                default=settings["rank3_min_messages"],
                validators=[wtforms.validators.NumberRange(min=3, max=10000)],
            )
            rank3_joined_days: wtforms.IntegerField = wtforms.IntegerField(
                "Rank 3 Min Days Joined:",
                default=settings["rank3_joined_days"],
                validators=[wtforms.validators.NumberRange(min=1, max=30)],
            )
            count_messages: wtforms.BooleanField = wtforms.BooleanField(
                "Count Messages (and Rank 4):", default=settings["count_messages"]
            )
            submit: wtforms.SubmitField = wtforms.SubmitField("Save Modifications")

        ranks_settings_form = RanksSettingsForm()
        if (
            ranks_settings_form.validate_on_submit()
            and await ranks_settings_form.validate_dpy_converters()
        ):
            await self.config.guild(guild).rank3_min_messages.set(
                ranks_settings_form.rank3_min_messages.data
            )
            await self.config.guild(guild).rank3_joined_days.set(
                ranks_settings_form.rank3_joined_days.data
            )
            await self.config.guild(guild).count_messages.set(
                ranks_settings_form.count_messages.data
            )
            return {
                "status": 0,
                "notifications": [
                    {
                        "message": "The modifications have been successfully saved.",
                        "category": "success",
                    }
                ],
                "redirect_url": kwargs["request_url"],
            }
        helper_roles_msg = await get_helper_roles_msg(guild, self, "[p]")

        class HelperRolesSettingsForm(kwargs["Form"]):
            def __init__(self) -> None:
                super().__init__(prefix="helper_roles_settings_form_")

            trusted_roles: wtforms.SelectMultipleField = wtforms.SelectMultipleField(
                "Trusted Roles:",
                choices=kwargs["get_sorted_roles"](guild),
                default=[str(role_id) for role_id in settings["trusted_roles"]],
                validators=[kwargs["DpyObjectConverter"](discord.Role)],
            )
            helper_roles: wtforms.SelectMultipleField = wtforms.SelectMultipleField(
                "Helper Roles:",
                choices=kwargs["get_sorted_roles"](guild),
                default=[str(role_id) for role_id in settings["helper_roles"]],
                validators=[kwargs["DpyObjectConverter"](discord.Role)],
            )
            submit: wtforms.SubmitField = wtforms.SubmitField("Save Modifications")

        helper_roles_settings_form = HelperRolesSettingsForm()
        if (
            helper_roles_settings_form.validate_on_submit()
            and await helper_roles_settings_form.validate_dpy_converters()
        ):
            await self.config.guild(guild).trusted_roles.set(
                [role.id for role in helper_roles_settings_form.trusted_roles.data]
            )
            await self.config.guild(guild).helper_roles.set(
                [role.id for role in helper_roles_settings_form.helper_roles.data]
            )
            return {
                "status": 0,
                "notifications": [
                    {
                        "message": "The modifications have been successfully saved.",
                        "category": "success",
                    }
                ],
                "redirect_url": kwargs["request_url"],
            }

        # Automatic Modules.

        automatic_modules_msgs = await get_automatic_modules_msgs(guild, self)

        raider_detection_msg = automatic_modules_msgs["raider_detection"]

        class RaiderDetectionSettingsForm(kwargs["Form"]):
            def __init__(self) -> None:
                super().__init__(prefix="raider_detection_settings_form_")

            raider_detection_enabled: wtforms.BooleanField = wtforms.BooleanField(
                "Enabled:", default=settings["raider_detection_enabled"]
            )
            raider_detection_messages: wtforms.IntegerField = wtforms.IntegerField(
                "Messages:",
                default=settings["raider_detection_messages"],
                validators=[wtforms.validators.NumberRange(min=8, max=50)],
            )
            raider_detection_minutes: wtforms.IntegerField = wtforms.IntegerField(
                "Minutes:",
                default=settings["raider_detection_minutes"],
                validators=[wtforms.validators.NumberRange(min=1)],
            )
            raider_detection_rank: wtforms.SelectField = wtforms.SelectField(
                "Rank:",
                choices=[(rank.value, f"Rank {rank.value}") for rank in Rank],
                default=settings["raider_detection_rank"],
                validators=[wtforms.validators.AnyOf([rank.value for rank in Rank])],
            )
            raider_detection_action: wtforms.SelectField = wtforms.SelectField(
                "Action:",
                choices=[(action.value, action.name) for action in Action],
                default=settings["raider_detection_action"],
                validators=[wtforms.validators.AnyOf([action.value for action in Action])],
            )
            raider_detection_wipe: wtforms.BooleanField = wtforms.BooleanField(
                "Wipe Messages Days:",
                default=settings["raider_detection_wipe"],
                validators=[wtforms.validators.NumberRange(min=0, max=7)],
            )
            submit: wtforms.SubmitField = wtforms.SubmitField("Save Modifications")

        raider_detection_settings_form = RaiderDetectionSettingsForm()
        if (
            raider_detection_settings_form.validate_on_submit()
            and await raider_detection_settings_form.validate_dpy_converters()
        ):
            await self.config.guild(guild).raider_detection_enabled.set(
                raider_detection_settings_form.raider_detection_enabled.data
            )
            await self.config.guild(guild).raider_detection_messages.set(
                raider_detection_settings_form.raider_detection_messages.data
            )
            await self.config.guild(guild).raider_detection_minutes.set(
                raider_detection_settings_form.raider_detection_minutes.data
            )
            await self.config.guild(guild).raider_detection_rank.set(
                raider_detection_settings_form.raider_detection_rank.data
            )
            await self.config.guild(guild).raider_detection_action.set(
                raider_detection_settings_form.raider_detection_action.data
            )
            await self.config.guild(guild).raider_detection_wipe.set(
                raider_detection_settings_form.raider_detection_wipe.data
            )
            return {
                "status": 0,
                "notifications": [
                    {
                        "message": "The modifications have been successfully saved.",
                        "category": "success",
                    }
                ],
                "redirect_url": kwargs["request_url"],
            }

        invite_filter_msg = automatic_modules_msgs["invite_filter"]

        class InviteFilterSettingsForm(kwargs["Form"]):
            def __init__(self) -> None:
                super().__init__(prefix="invite_filter_settings_form_")

            invite_filter_enabled: wtforms.BooleanField = wtforms.BooleanField(
                "Enabled:", default=settings["invite_filter_enabled"]
            )
            invite_filter_rank: wtforms.SelectField = wtforms.SelectField(
                "Rank:",
                choices=[(rank.value, f"Rank {rank.value}") for rank in Rank],
                default=settings["invite_filter_rank"],
                validators=[wtforms.validators.AnyOf([rank.value for rank in Rank])],
            )
            invite_filter_action: wtforms.SelectField = wtforms.SelectField(
                "Action:",
                choices=[(action.value, action.name) for action in Action],
                default=settings["invite_filter_action"],
                validators=[wtforms.validators.AnyOf([action.value for action in Action])],
            )
            invite_filter_exclude_own_invites: wtforms.BooleanField = wtforms.BooleanField(
                "Exclude Own Invites:", default=settings["invite_filter_exclude_own_invites"]
            )
            invite_filter_delete_message: wtforms.BooleanField = wtforms.BooleanField(
                "Delete Message:", default=settings["invite_filter_delete_message"]
            )
            submit: wtforms.SubmitField = wtforms.SubmitField("Save Modifications")

        invite_filter_settings_form = InviteFilterSettingsForm()
        if (
            invite_filter_settings_form.validate_on_submit()
            and await invite_filter_settings_form.validate_dpy_converters()
        ):
            await self.config.guild(guild).invite_filter_enabled.set(
                invite_filter_settings_form.invite_filter_enabled.data
            )
            await self.config.guild(guild).invite_filter_rank.set(
                invite_filter_settings_form.invite_filter_rank.data
            )
            await self.config.guild(guild).invite_filter_action.set(
                invite_filter_settings_form.invite_filter_action.data
            )
            await self.config.guild(guild).invite_filter_exclude_own_invites.set(
                invite_filter_settings_form.invite_filter_exclude_own_invites.data
            )
            await self.config.guild(guild).invite_filter_delete_message.set(
                invite_filter_settings_form.invite_filter_delete_message.data
            )
            return {
                "status": 0,
                "notifications": [
                    {
                        "message": "The modifications have been successfully saved.",
                        "category": "success",
                    }
                ],
                "redirect_url": kwargs["request_url"],
            }

        join_monitor_msg = automatic_modules_msgs["join_monitor"]
        levels = [
            ("0", "🤠 No action - Are you sure?"),
            ("1", "🟢 Low - Must have a verified email address on their Discord."),
            ("2", "🟡 Medium - Must also be registered on Discord for >= 5 minutes."),
            ("3", "🟠 High - Must also be a member here for more than 10 minutes."),
            ("4", "🔴 Highest - Must also have a verified phone on their Discord."),
        ]

        class JoinMonitorSettingsForm(kwargs["Form"]):
            def __init__(self) -> None:
                super().__init__(prefix="join_monitor_settings_form_")

            join_monitor_enabled: wtforms.BooleanField = wtforms.BooleanField(
                "Enabled:", default=settings["join_monitor_enabled"]
            )
            join_monitor_minutes: wtforms.IntegerField = wtforms.IntegerField(
                "Minutes:",
                default=settings["join_monitor_minutes"],
                validators=[wtforms.validators.NumberRange(min=1, max=60)],
            )
            join_monitor_n_users: wtforms.IntegerField = wtforms.IntegerField(
                "N Users:",
                default=settings["join_monitor_n_users"],
                validators=[wtforms.validators.NumberRange(min=1, max=100)],
            )
            join_monitor_susp_hours: wtforms.IntegerField = wtforms.IntegerField(
                "Susp Hours:",
                default=settings["join_monitor_susp_hours"],
                validators=[wtforms.validators.NumberRange(min=1, max=744)],
            )
            join_monitor_v_level: wtforms.SelectField = wtforms.SelectField(
                "Verification Level:",
                choices=levels,
                default=str(settings["join_monitor_v_level"]),
                validators=[wtforms.validators.AnyOf([level[0] for level in levels])],
            )
            submit: wtforms.SubmitField = wtforms.SubmitField("Save Modifications")

        join_monitor_settings_form = JoinMonitorSettingsForm()
        if (
            join_monitor_settings_form.validate_on_submit()
            and await join_monitor_settings_form.validate_dpy_converters()
        ):
            await self.config.guild(guild).join_monitor_enabled.set(
                join_monitor_settings_form.join_monitor_enabled.data
            )
            await self.config.guild(guild).join_monitor_minutes.set(
                join_monitor_settings_form.join_monitor_minutes.data
            )
            await self.config.guild(guild).join_monitor_n_users.set(
                join_monitor_settings_form.join_monitor_n_users.data
            )
            await self.config.guild(guild).join_monitor_susp_hours.set(
                join_monitor_settings_form.join_monitor_susp_hours.data
            )
            await self.config.guild(guild).join_monitor_v_level.set(
                int(join_monitor_settings_form.join_monitor_v_level.data)
            )
            return {
                "status": 0,
                "notifications": [
                    {
                        "message": "The modifications have been successfully saved.",
                        "category": "success",
                    }
                ],
                "redirect_url": kwargs["request_url"],
            }

        warden_msg = automatic_modules_msgs["warden"]
        if user.id not in self.bot.owner_ids:

            class WardenSettingsForm(kwargs["Form"]):
                def __init__(self) -> None:
                    super().__init__(prefix="warden_settings_form_")

                warden_enabled: wtforms.BooleanField = wtforms.BooleanField(
                    "Enabled:", default=settings["warden_enabled"]
                )
                submit: wtforms.SubmitField = wtforms.SubmitField("Save Modifications")

        else:
            global_settings = await self.config.all()

            class WardenSettingsForm(kwargs["Form"]):
                def __init__(self) -> None:
                    super().__init__(prefix="warden_settings_form_")

                warden_enabled: wtforms.BooleanField = wtforms.BooleanField(
                    "Enabled:", default=settings["warden_enabled"]
                )
                wd_regex_allowed: wtforms.BooleanField = wtforms.BooleanField(
                    "OWNER-GLOBAL Regex Allowed:", default=global_settings["wd_regex_allowed"]
                )
                wd_regex_safety_checks: wtforms.BooleanField = wtforms.BooleanField(
                    "OWNER-GLOBAL Regex Safety Checks:",
                    default=global_settings["wd_regex_safety_checks"],
                )
                wd_periodic_allowed: wtforms.BooleanField = wtforms.BooleanField(
                    "OWNER-GLOBAL Periodic Allowed:",
                    default=global_settings["wd_periodic_allowed"],
                )
                wd_upload_max_size: wtforms.IntegerField = wtforms.IntegerField(
                    "OWNER-GLOBAL Upload Max Size (kB):",
                    default=global_settings["wd_upload_max_size"],
                    validators=[wtforms.validators.NumberRange(min=2, max=50)],
                )
                submit: wtforms.SubmitField = wtforms.SubmitField("Save Modifications")

        warden_settings_form = WardenSettingsForm()
        if (
            warden_settings_form.validate_on_submit()
            and await warden_settings_form.validate_dpy_converters()
        ):
            await self.config.guild(guild).warden_enabled.set(
                warden_settings_form.warden_enabled.data
            )
            if user.id in self.bot.owner_ids:
                await self.config.wd_regex_allowed.set(warden_settings_form.wd_regex_allowed.data)
                await self.config.wd_regex_safety_checks.set(
                    warden_settings_form.wd_regex_safety_checks.data
                )
                await self.config.wd_periodic_allowed.set(
                    warden_settings_form.wd_periodic_allowed.data
                )
                await self.config.wd_upload_max_size.set(
                    warden_settings_form.wd_upload_max_size.data
                )
            return {
                "status": 0,
                "notifications": [
                    {
                        "message": "The modifications have been successfully saved.",
                        "category": "success",
                    }
                ],
                "redirect_url": kwargs["request_url"],
            }

        comment_analysis_msg = automatic_modules_msgs["comment_analysis"]
        attributes = [
            (PAttr.Toxicity.value, "Toxicity - Rude or generally disrespectful comments."),
            (PAttr.SevereToxicity.value, "Severe toxicity - Hateful, aggressive comments."),
            (
                PAttr.IdentityAttack.value,
                "Identity attack - Hateful comments attacking one's identity.",
            ),
            (PAttr.Insult.value, "Insult - Insulting, inflammatory or negative comments."),
            (
                PAttr.Profanity.value,
                "Profanity - Comments containing swear words, curse words or profanities.",
            ),
            (
                PAttr.Threat.value,
                "Threat - Comments perceived as an intention to inflict violence against others.",
            ),
        ]

        class CommentAnalysisSettingsForm(kwargs["Form"]):
            def __init__(self) -> None:
                super().__init__(prefix="comment_analysis_settings_form_")

            ca_enabled: wtforms.BooleanField = wtforms.BooleanField(
                "Enabled:", default=settings["ca_enabled"]
            )
            ca_token: wtforms.StringField = wtforms.StringField(
                "Perspective API Token:",
                default=settings["ca_token"],
                validators=[
                    wtforms.validators.Length(min=30, max=50),
                    wtforms.validators.Optional(),
                ],
            )
            ca_attributes: wtforms.SelectMultipleField = wtforms.SelectMultipleField(
                "Attributes:",
                choices=attributes,
                default=[attr[0] for attr in settings["ca_attributes"]],
                validators=[wtforms.validators.AnyOf([attr[0] for attr in attributes])],
            )
            ca_threshold: wtforms.IntegerField = wtforms.IntegerField(
                "Perspective API Threshold:",
                default=settings["ca_threshold"],
                validators=[wtforms.validators.NumberRange(min=20, max=100)],
            )
            ca_rank: wtforms.SelectField = wtforms.SelectField(
                "Rank:",
                choices=[(rank.value, f"Rank {rank.value}") for rank in Rank],
                default=settings["ca_rank"],
                validators=[wtforms.validators.AnyOf([rank.value for rank in Rank])],
            )
            ca_action: wtforms.SelectField = wtforms.SelectField(
                "Action:",
                choices=[(action.value, action.name) for action in Action],
                default=settings["ca_action"],
                validators=[wtforms.validators.AnyOf([action.value for action in Action])],
            )
            ca_reason: wtforms.StringField = wtforms.StringField(
                "Reason:",
                default=settings["ca_reason"],
                validators=[wtforms.validators.Length(max=500)],
            )
            ca_wipe: wtforms.BooleanField = wtforms.BooleanField(
                "Wipe Messages Days:",
                default=settings["ca_wipe"],
                validators=[wtforms.validators.NumberRange(min=0, max=7)],
            )
            ca_delete_message: wtforms.BooleanField = wtforms.BooleanField(
                "Delete Message:", default=settings["ca_delete_message"]
            )
            submit: wtforms.SubmitField = wtforms.SubmitField("Save Modifications")

        comment_analysis_settings_form = CommentAnalysisSettingsForm()
        if (
            comment_analysis_settings_form.validate_on_submit()
            and await comment_analysis_settings_form.validate_dpy_converters()
        ):
            notifications = []
            if (
                comment_analysis_settings_form.ca_enabled.data
                and not comment_analysis_settings_form.ca_token.data
            ):
                comment_analysis_settings_form.ca_enabled.data = False
                notifications.append(
                    {"message": "There is no Perspective API Token set.", "category": "error"}
                )
            await self.config.guild(guild).ca.enabled.set(
                comment_analysis_settings_form.ca_enabled.data
            )
            await self.config.guild(guild).ca_token.set(
                comment_analysis_settings_form.ca_token.data
            )
            await self.config.guild(guild).ca_attributes.set(
                [
                    attr
                    for attr in attributes
                    if attr[0] in comment_analysis_settings_form.ca_attributes.data
                ]
            )
            await self.config.guild(guild).ca_threshold.set(
                comment_analysis_settings_form.ca_threshold.data
            )
            await self.config.guild(guild).ca_rank.set(comment_analysis_settings_form.ca_rank.data)
            await self.config.guild(guild).ca_action.set(
                comment_analysis_settings_form.ca_action.data
            )
            await self.config.guild(guild).ca_reason.set(
                comment_analysis_settings_form.ca_reason.data
            )
            await self.config.guild(guild).ca_wipe.set(comment_analysis_settings_form.ca_wipe.data)
            await self.config.guild(guild).ca_delete_message.set(
                comment_analysis_settings_form.ca_delete_message.data
            )
            notifications.append(
                {
                    "message": "The modifications have been successfully saved.",
                    "category": "success",
                }
            )
            return {
                "status": 0,
                "notifications": notifications,
                "redirect_url": kwargs["request_url"],
            }

        # Manual Modules.

        manual_modules_msgs = await get_manual_modules_msgs(guild, self, "[p]")

        alert_msg = manual_modules_msgs["alert"]

        class AlertSettingsForm(kwargs["Form"]):
            def __init__(self) -> None:
                super().__init__(prefix="alert_settings_form_")

            alert_enabled: wtforms.BooleanField = wtforms.BooleanField(
                "Enabled:", default=settings["alert_enabled"]
            )
            submit: wtforms.SubmitField = wtforms.SubmitField("Save Modifications")

        alert_settings_form = AlertSettingsForm()
        if (
            alert_settings_form.validate_on_submit()
            and await alert_settings_form.validate_dpy_converters()
        ):
            await self.config.guild(guild).alert_enabled.set(
                alert_settings_form.alert_enabled.data
            )
            return {
                "status": 0,
                "notifications": [
                    {
                        "message": "The modifications have been successfully saved.",
                        "category": "success",
                    }
                ],
                "redirect_url": kwargs["request_url"],
            }

        vaporize_msg = manual_modules_msgs["vaporize"]

        class VaporizeSettingsForm(kwargs["Form"]):
            def __init__(self) -> None:
                super().__init__(prefix="vaporize_settings_form_")

            vaporize_enabled: wtforms.BooleanField = wtforms.BooleanField(
                "Enabled:", default=settings["vaporize_enabled"]
            )
            vaporize_max_targets: wtforms.IntegerField = wtforms.IntegerField(
                "Max Targets:",
                default=settings["vaporize_max_targets"],
                validators=[wtforms.validators.NumberRange(min=1, max=999)],
            )
            submit: wtforms.SubmitField = wtforms.SubmitField("Save Modifications")

        vaporize_settings_form = VaporizeSettingsForm()
        if (
            vaporize_settings_form.validate_on_submit()
            and await vaporize_settings_form.validate_dpy_converters()
        ):
            await self.config.guild(guild).vaporize_enabled.set(
                vaporize_settings_form.vaporize_enabled.data
            )
            if vaporize_settings_form.vaporize_max_targets.data is not None:
                await self.config.guild(guild).vaporize_max_targets.set(
                    vaporize_settings_form.vaporize_max_targets.data
                )
            else:
                await self.config.guild(guild).vaporize_max_targets.clear()
            return {
                "status": 0,
                "notifications": [
                    {
                        "message": "The modifications have been successfully saved.",
                        "category": "success",
                    }
                ],
                "redirect_url": kwargs["request_url"],
            }

        silence_msg = manual_modules_msgs["silence"]

        class SilenceSettingsForm(kwargs["Form"]):
            def __init__(self) -> None:
                super().__init__(prefix="silence_settings_form_")

            silence_enabled: wtforms.BooleanField = wtforms.BooleanField(
                "Enabled:", default=settings["silence_enabled"]
            )
            submit: wtforms.SubmitField = wtforms.SubmitField("Save Modifications")

        silence_settings_form = SilenceSettingsForm()
        if (
            silence_settings_form.validate_on_submit()
            and await silence_settings_form.validate_dpy_converters()
        ):
            await self.config.guild(guild).silence_enabled.set(
                silence_settings_form.silence_enabled.data
            )
            return {
                "status": 0,
                "notifications": [
                    {
                        "message": "The modifications have been successfully saved.",
                        "category": "success",
                    }
                ],
                "redirect_url": kwargs["request_url"],
            }

        voteout_msg = manual_modules_msgs["voteout"]

        class VoteoutSettingsForm(kwargs["Form"]):
            def __init__(self) -> None:
                super().__init__(prefix="voteout_settings_form_")

            voteout_enabled: wtforms.BooleanField = wtforms.BooleanField(
                "Enabled:", default=settings["voteout_enabled"]
            )
            voteout_rank: wtforms.SelectField = wtforms.SelectField(
                "Rank:",
                choices=[(rank.value, f"Rank {rank.value}") for rank in Rank],
                default=settings["voteout_rank"],
                validators=[wtforms.validators.AnyOf([rank.value for rank in Rank])],
            )
            voteout_action: wtforms.SelectField = wtforms.SelectField(
                "Action:",
                choices=[(action.value, action.name) for action in Action],
                default=settings["voteout_action"],
                validators=[wtforms.validators.AnyOf([action.value for action in Action])],
            )
            voteout_votes: wtforms.IntegerField = wtforms.IntegerField(
                "Votes:",
                default=settings["voteout_votes"],
                validators=[wtforms.validators.NumberRange(min=2)],
            )
            voteout_wipe: wtforms.BooleanField = wtforms.BooleanField(
                "Wipe Messages Days:",
                default=settings["voteout_wipe"],
                validators=[wtforms.validators.NumberRange(min=0, max=7)],
            )
            submit: wtforms.SubmitField = wtforms.SubmitField("Save Modifications")

        voteout_settings_form = VoteoutSettingsForm()
        if (
            voteout_settings_form.validate_on_submit()
            and await voteout_settings_form.validate_dpy_converters()
        ):
            await self.config.guild(guild).voteout_enabled.set(
                voteout_settings_form.voteout_enabled.data
            )
            await self.config.guild(guild).voteout_rank.set(
                voteout_settings_form.voteout_rank.data
            )
            await self.config.guild(guild).voteout_action.set(
                voteout_settings_form.voteout_action.data
            )
            await self.config.guild(guild).voteout_votes.set(
                voteout_settings_form.voteout_votes.data
            )
            await self.config.guild(guild).voteout_wipe.set(
                voteout_settings_form.voteout_wipe.data
            )
            return {
                "status": 0,
                "notifications": [
                    {
                        "message": "The modifications have been successfully saved.",
                        "category": "success",
                    }
                ],
                "redirect_url": kwargs["request_url"],
            }

        # Emergency Mode.
        modules = [
            (EModules.Silence.value, "🔇 Silence - Apply a server wide mute on ranks."),
            (
                EModules.Vaporize.value,
                "☁️ Vaporize - Silently get rid of multiple new users at once.",
            ),
            (EModules.Voteout.value, "👎 Voteout - Start a vote to expel misbehaving users."),
        ]

        class EmergencyModeSettingsForm(kwargs["Form"]):
            def __init__(self) -> None:
                super().__init__(prefix="emergency_mode_settings_form_")

            emergency_modules: wtforms.SelectMultipleField = wtforms.SelectMultipleField(
                "Modules:",
                choices=modules,
                default=[module[0] for module in settings["emergency_modules"]],
                validators=[wtforms.validators.AnyOf([module[0] for module in modules])],
            )
            emergency_minutes: wtforms.IntegerField = wtforms.IntegerField(
                "Minutes:",
                default=settings["emergency_minutes"],
                validators=[wtforms.validators.NumberRange(min=1, max=30)],
            )
            submit: wtforms.SubmitField = wtforms.SubmitField("Save Modifications")

        emergency_mode_settings_form = EmergencyModeSettingsForm()
        if (
            emergency_mode_settings_form.validate_on_submit()
            and await emergency_mode_settings_form.validate_dpy_converters()
        ):
            await self.config.guild(guild).emergency_modules.set(
                emergency_mode_settings_form.emergency_modules.data
            )
            await self.config.guild(guild).emergency_minutes.set(
                emergency_mode_settings_form.emergency_minutes.data
            )
            return {
                "status": 0,
                "notifications": [
                    {
                        "message": "The modifications have been successfully saved.",
                        "category": "success",
                    }
                ],
                "redirect_url": kwargs["request_url"],
            }

        return {
            "status": 0,
            "web_content": {
                "source": WEB_CONTENT,
                "VERSION": self.__version__,
                "DOCS_BASE_URL": DOCS_BASE_URL,
                "d_enabled": d_enabled,
                "possible_config_issue": possible_config_issue,
                "status_msg": status_msg,
                # Overview.
                "overview_msg": overview_msg,
                "overview_settings_form": overview_settings_form,
                # Ranks & Helper Roles.
                "ranks_msg": ranks_msg,
                "ranks_settings_form": ranks_settings_form,
                "helper_roles_msg": helper_roles_msg,
                "helper_roles_settings_form": helper_roles_settings_form,
                # Automatic Modules.
                "raider_detection_msg": raider_detection_msg,
                "raider_detection_settings_form": raider_detection_settings_form,
                "invite_filter_msg": invite_filter_msg,
                "invite_filter_settings_form": invite_filter_settings_form,
                "join_monitor_msg": join_monitor_msg,
                "join_monitor_settings_form": join_monitor_settings_form,
                "warden_msg": warden_msg,
                "warden_settings_form": warden_settings_form,
                "comment_analysis_msg": comment_analysis_msg,
                "comment_analysis_settings_form": comment_analysis_settings_form,
                # Manual Modules.
                "alert_msg": alert_msg,
                "alert_settings_form": alert_settings_form,
                "vaporize_msg": vaporize_msg,
                "vaporize_settings_form": vaporize_settings_form,
                "silence_msg": silence_msg,
                "silence_settings_form": silence_settings_form,
                "voteout_msg": voteout_msg,
                "voteout_settings_form": voteout_settings_form,
                # Emergency Mode.
                "emergency_mode_settings_form": emergency_mode_settings_form,
            },
        }


WEB_CONTENT = """
<div class="alert alert-{{ ("success" if not possible_config_issue else "warning") if d_enabled else "danger" }} text-white" role="alert">
    {{ status_msg|markdown }}
    <div class="d-flex justify-content-between">
        <p style="padding-top: 10px;"><strong>Defender system v{{ VERSION }}</strong></p>
        <a href="{{ DOCS_BASE_URL }}" class="btn btn-gradient-default text-white">Documentation</a>
    </div>
</div>

<br />
<div id="Overview">
    <h4>Overview:</h4>
    {{ overview_msg|markdown }}
    {{ overview_settings_form|safe }}
</div>

<br /><br />
<div id="RanksHelperRoles">
    <h4>Ranks & Helper Roles:</h4>
    {{ ranks_msg|markdown }}
    {{ ranks_settings_form|safe }}
    <br />
    {{ helper_roles_msg|markdown }}
    {{ helper_roles_settings_form|safe }}
</div>

<br /><br />
<div id="AutomaticModules">
    <h4>Automatic Modules:</h4>
    <div id="RaiderDetection">
        {{ raider_detection_msg|markdown }}
        {{ raider_detection_settings_form|safe }}
    </div>
    <br />
    <div id="InviteFilter">
        {{ invite_filter_msg|markdown }}
        {{ invite_filter_settings_form|safe }}
    </div>
    <br />
    <div id="JoinMonitor">
        {{ join_monitor_msg|markdown }}
        {{ join_monitor_settings_form|safe }}
    </div>
    <br />
    <div id="Warden">
        {{ warden_msg|markdown }}
        {{ warden_settings_form|safe }}
    </div>
    <br />
    <div id="CommentAnalysis">
        {{ comment_analysis_msg|markdown }}
        {{ comment_analysis_settings_form|safe }}
    </div>
</div>

<br /><br />
<div id="ManualModules">
    <h4>Manual Modules:</h4>
    <div id="Alert">
        {{ alert_msg|markdown }}
        {{ alert_settings_form|safe }}
    </div>
    <br />
    <div id="Vaporize">
        {{ vaporize_msg|markdown }}
        {{ vaporize_settings_form|safe }}
    </div>
    <br />
    <div id="Silence">
        {{ silence_msg|markdown }}
        {{ silence_settings_form|safe }}
    </div>
    <br />
    <div id="Voteout">
        {{ voteout_msg|markdown }}
        {{ voteout_settings_form|safe }}
    </div>
</div>

<br /><br />
<div id="EmergencyMode">
    <h4>Emergency Mode:</h4>
    {{ emergency_mode_settings_form|safe }}
</div>
"""
