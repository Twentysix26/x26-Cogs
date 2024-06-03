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


class WardenIntegration:
    @dashboard_page(name="warden-rules", description="Manage Warden rules.", methods=("GET", "POST"))
    async def dashboard_warden_page(self, user: discord.User, guild: discord.Guild, **kwargs) -> typing.Dict[str, typing.Any]:
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
        n_channel = await self.config.guild(guild).notify_channel()
        if n_channel == 0:
            return {
                "status": 1,
                "error_code": 403,
                "error_message": "It is important that you configure and understand how Defender works before using Warden.",
            }

        import wtforms
        from markupsafe import Markup
        class MarkdownTextAreaField(wtforms.TextAreaField):
            def __call__(
                self,
                disable_toolbar: bool = False,
                **kwargs,
            ) -> Markup:
                if "class" not in kwargs:
                    kwargs["class"] = "markdown-text-area-field"
                else:
                    kwargs["class"] += " markdown-text-area-field"
                if disable_toolbar:
                    kwargs["class"] += " markdown-text-area-field-toolbar-disabled"
                return super().__call__(**kwargs)
        class WardenRuleForm(kwargs["Form"]):
            rule: MarkdownTextAreaField = MarkdownTextAreaField("Rule", validators=[wtforms.validators.InputRequired()])
        class WardenRulesForm(kwargs["Form"]):
            def __init__(self, warden_rules: typing.Dict[str, str]) -> None:
                super().__init__(prefix="warden_rules_form_")
                for rule in warden_rules:
                    self.warden_rules.append_entry({"rule": rule})
                self.warden_rules.default = [entry for entry in self.warden_rules.entries if entry.csrf_token.data is None]
                self.warden_rules.entries = [entry for entry in self.warden_rules.entries if entry.csrf_token.data is not None]
            warden_rules: wtforms.FieldList = wtforms.FieldList(wtforms.FormField(WardenRuleForm))
            submit: wtforms.SubmitField = wtforms.SubmitField("Save Modifications")

        existing_warden_rules = self.active_warden_rules[guild.id].copy()
        warden_rules_form: WardenRulesForm = WardenRulesForm([warden_rule.raw_rule for warden_rule in sorted(existing_warden_rules.values(), key=lambda warden_rule: warden_rule.name)])
        if warden_rules_form.validate_on_submit() and await warden_rules_form.validate_dpy_converters():
            notifications = []
            warden_rules = [warden_rule.rule.data for warden_rule in warden_rules_form.warden_rules]
            rules_names = []
            for raw_rule in warden_rules:
                try:
                    rule = WardenRule()
                    await rule.parse(raw_rule, cog=self, author=user)
                except InvalidRule as e:
                    notifications.append({"message": f"Invalid rule: {e}", "category": "error"})
                    continue
                except Exception as e:
                    log.error("Warden - unexpected error during rule parsing", exc_info=e)
                    notifications.append({"message": "Unexpected error during rule parsing.", "category": "error"})
                    continue
                rules_names.append(rule.name)
                if rule.name not in existing_warden_rules or raw_rule != existing_warden_rules[rule.name].raw_rule:
                    async with self.config.guild(guild).wd_rules() as warden_rules:
                        warden_rules[rule.name] = raw_rule
                    self.active_warden_rules[guild.id][rule.name] = rule
                    self.invalid_warden_rules[guild.id].pop(rule.name, None)
            for rule_name in existing_warden_rules:
                if rule_name not in rules_names:
                    self.active_warden_rules[guild.id].pop(rule_name, None)
                    self.invalid_warden_rules[guild.id].pop(rule_name, None)
                    async with self.config.guild(guild).wd_rules() as warden_rules:
                        del warden_rules[rule_name]
            if not notifications:
                notifications.append({"message": "Warden rules have been successfully updated.", "category": "success"})
            return {
                "status": 0,
                "notifications": notifications,
                "redirect_url": kwargs["request_url"],
            }

        html_form = [
            '<form action="" method="POST" role="form" enctype="multipart/form-data">',
            f"    {warden_rules_form.hidden_tag()}",
        ]
        for i, warden_rule_form in enumerate(warden_rules_form.warden_rules.default):
            html_form.append('    <div class="row mb-3">')
            if i > 0:
                html_form.append('        <hr class="horizontal dark" />')
            warden_rule_form.rule.render_kw = {"class": "form-control form-control-default"}
            html_form.extend(
                [
                    f"       {warden_rule_form.hidden_tag()}",
                    '        <div class="form-group">',
                    f"           {warden_rule_form.rule(rows=5, disable_toolbar=True, placeholder='Rule')}",
                    "        </div>",
                    '        <div class="col-md-12 d-flex justify-content-end align-items-center">',
                    '            <a href="javascript:void(0);" onclick="this.parentElement.parentNode.remove();" class="text-danger mr-3"><i class="fa fa-minus-circle"></i> Delete Warden Rule</a>',
                    "        </div>",
                    "    </div>",
                ]
            )
        warden_rules_form.submit.render_kw = {"class": "btn mb-0 bg-gradient-success btn-md w-100 my-4"}
        html_form.extend(
            [
                '    <a href="javascript:void(0);" onclick="createWardenRule(this);" class="text-success mr-3"><i class="fa fa-plus-circle"></i> Create Warden Rule</a>'
                '    <div class="text-center">'
                f"        {warden_rules_form.submit()}",
                "    </div>",
                "</form>",
            ]
        )
        warden_rules_form_str = Markup("\n".join(html_form))

        return {
            "status": 0,
            "web_content": {
                "source": WEB_CONTENT,
                "warden_rules_form": warden_rules_form_str,
                "warden_rules_form_length": len(warden_rules_form.warden_rules.default),
            },
        }

WEB_CONTENT = """
    {{ warden_rules_form|safe }}

    <script>
        var warden_rule_index = {{ warden_rules_form_length }} - 1;
        function createWardenRule(element) {
            var newRow = document.createElement("div");
            newRow.classList.add("row", "mb-3");
            warden_rule_index += 1;
            if (document.querySelectorAll("#third-party-content .row").length != 0) {
                var horizontal = '<hr class="horizontal dark" />\\n';
            } else {
                var horizontal = "";
            }
            newRow.innerHTML = horizontal + `
                <input id="warden_rules_form_warden_rules-${warden_rule_index}-csrf_token" name="warden_rules_form_warden_rules-${warden_rule_index}-csrf_token" type="hidden" value="{{ csrf_token() }}">
                <div class="form-group">
                    <textarea class="form-control form-control-default markdown-text-area-field markdown-text-area-field-toolbar-disabled" id="warden_rules_form_warden_rules-${warden_rule_index}-rule" maxlength="1700" name="warden_rules_form_warden_rules-${warden_rule_index}-rule" required rows="5" placeholder="Rule"></textarea>
                </div>
                <div class="col-md-12 d-flex justify-content-end align-items-center">
                    <a href="javascript:void(0);" onclick="this.parentElement.parentNode.remove();" class="text-danger mr-3"><i class="fa fa-minus-circle"></i> Delete Warden Rule</a>
                </div>
            `
            element.parentNode.insertBefore(newRow, element);
            MarkdownField(document.getElementById(`warden_rules_form_warden_rules-${warden_rule_index}-rule`));
            document.getElementById(`warden_rules_form_warden_rules-${warden_rule_index}-rule`).focus();
        }
    </script>
"""
