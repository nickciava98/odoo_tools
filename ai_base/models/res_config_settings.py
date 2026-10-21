from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    ai_provider_base_url = fields.Char(
        config_parameter="ai_base.base_url",
        string="API Base URL"
    )
    ai_provider_api_key = fields.Char(
        config_parameter="ai_base.api_key",
        string="Provider API Key"
    )
    ai_provider_model = fields.Char(
        config_parameter="ai_base.model",
        string="Model"
    )
    ai_provider_timeout = fields.Integer(
        config_parameter="ai_base.timeout",
        string="Request Timeout (seconds)"
    )
