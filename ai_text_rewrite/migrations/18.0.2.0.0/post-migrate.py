import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

MOVED_KEYS = ("base_url", "api_key", "model", "timeout")


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    # why: only module config parameters are touched, sudo is scoped to them
    config_parameter_model = env["ir.config_parameter"].sudo()

    for key in MOVED_KEYS:
        old_key = "ai_text_rewrite.%s" % key
        old_value = config_parameter_model.get_param(old_key)

        if old_value:
            config_parameter_model.set_param("ai_base.%s" % key, old_value)

        old_parameter_ids = config_parameter_model.search([("key", "=", old_key)])
        env["ir.model.data"].sudo().search([
            ("module", "=", "ai_text_rewrite"),
            ("model", "=", "ir.config_parameter"),
            ("res_id", "in", old_parameter_ids.ids)
        ]).unlink()
        old_parameter_ids.unlink()

    _logger.info("ai_text_rewrite 2.0.0 migration: provider parameters moved to ai_base")
