import hashlib
import logging

from lxml import etree

from odoo import SUPERUSER_ID, api
from odoo.tools.misc import file_open

_logger = logging.getLogger(__name__)

PARAMETER_KEY = "ai_text_rewrite.system_prompt"
# why: sha256 of the 16.0.1.4.0 shipped prompt, only that one is replaced, a customised prompt is kept
PREVIOUS_DEFAULT_PROMPT_SHA256 = "d95420ae643f9199fa881053f657493af29a31a935ef5214b6f7f32293134ff8"


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    # why: only the module config parameter is touched, sudo is scoped to this single read/write
    config_parameter_model = env["ir.config_parameter"].sudo()
    current_value = (config_parameter_model.get_param(PARAMETER_KEY) or "").strip()

    if hashlib.sha256(current_value.encode()).hexdigest() != PREVIOUS_DEFAULT_PROMPT_SHA256:
        _logger.info("ai_text_rewrite prompt migration: no action, %s does not hold the previous default", PARAMETER_KEY)
        return

    with file_open("ai_text_rewrite/data/ai_rewrite_data.xml", "rb") as data_file:
        shipped_values = {
            record.findtext("field[@name='key']"): record.findtext("field[@name='value']")
            for record in etree.parse(data_file).xpath("//record[@model='ir.config_parameter']")
        }

    config_parameter_model.set_param(PARAMETER_KEY, shipped_values[PARAMETER_KEY])
    _logger.info("ai_text_rewrite prompt migration: moved %s to the current default", PARAMETER_KEY)
