import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

PARAMETER_KEY = "ai_text_rewrite.provider"
OLD_DEFAULT_PROVIDER = "pollinations"
NEW_DEFAULT_PROVIDER = "openai"


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    # why: only the module config parameter is touched, sudo is scoped to this single read/write
    config_parameter_model = env["ir.config_parameter"].sudo()
    current_value = config_parameter_model.get_param(PARAMETER_KEY)

    if current_value != OLD_DEFAULT_PROVIDER:
        _logger.info(
            "ai_text_rewrite provider migration: no action, %s is %r (not the old shipped default %r)",
            PARAMETER_KEY, current_value, OLD_DEFAULT_PROVIDER
        )
        return

    config_parameter_model.set_param(PARAMETER_KEY, NEW_DEFAULT_PROVIDER)
    _logger.info(
        "ai_text_rewrite provider migration: moved %s from %r to %r",
        PARAMETER_KEY, OLD_DEFAULT_PROVIDER, NEW_DEFAULT_PROVIDER
    )
