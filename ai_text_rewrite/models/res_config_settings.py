from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    ai_rewrite_provider = fields.Selection(
        [("pollinations", "Free service (no API key)"), ("openai", "OpenAI-compatible endpoint")],
        config_parameter="ai_text_rewrite.provider",
        string="AI Provider"
    )
    ai_rewrite_base_url = fields.Char(
        config_parameter="ai_text_rewrite.base_url",
        string="API Base URL"
    )
    ai_rewrite_api_key = fields.Char(
        config_parameter="ai_text_rewrite.api_key",
        string="API Key"
    )
    ai_rewrite_model = fields.Char(
        config_parameter="ai_text_rewrite.model",
        string="Model"
    )
    ai_rewrite_system_prompt = fields.Text(
        string="System Prompt"
    )
    is_ai_rewrite_style_enabled = fields.Boolean(
        string="Learn from Existing Texts"
    )
    ai_rewrite_timeout = fields.Integer(
        config_parameter="ai_text_rewrite.timeout",
        string="Request Timeout (seconds)"
    )

    def get_values(self):
        res = super().get_values()
        # why: fields.Text is not an allowed config_parameter type in v16 (res_config._get_classified_fields)
        res["ai_rewrite_system_prompt"] = self.env["ir.config_parameter"].sudo().get_param("ai_text_rewrite.system_prompt")
        res["is_ai_rewrite_style_enabled"] = self.env["ai.rewrite.service"]._get_ai_settings()["style_enabled"]
        return res

    def set_values(self):
        super().set_values()
        # why: same restriction as get_values(), the parameter is read/written by hand
        self.env["ir.config_parameter"].sudo().set_param("ai_text_rewrite.system_prompt", self.ai_rewrite_system_prompt or "")
        # why: a boolean config_parameter deletes the key when unchecked, and the default would turn it back on
        self.env["ir.config_parameter"].sudo().set_param("ai_text_rewrite.style_enabled", str(self.is_ai_rewrite_style_enabled))
