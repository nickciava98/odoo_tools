import hashlib

from lxml import etree

from odoo.tools.misc import file_open

SYSTEM_PROMPT_KEY = "ai_text_rewrite.system_prompt"
# why: sha256 of the 18.0.1.0.1 shipped prompt, only that one is replaced, a customised prompt is kept
PREVIOUS_SYSTEM_PROMPT_SHA256 = "d95420ae643f9199fa881053f657493af29a31a935ef5214b6f7f32293134ff8"


def migrate(cr, version):
    cr.execute("SELECT value FROM ir_config_parameter WHERE key = %s", (SYSTEM_PROMPT_KEY,))
    row = cr.fetchone()

    if not row or hashlib.sha256((row[0] or "").strip().encode()).hexdigest() != PREVIOUS_SYSTEM_PROMPT_SHA256:
        return

    with file_open("ai_text_rewrite/data/ai_rewrite_data.xml", "rb") as data_file:
        shipped_values = {
            record.findtext("field[@name='key']"): record.findtext("field[@name='value']")
            for record in etree.parse(data_file).xpath("//record[@model='ir.config_parameter']")
        }

    cr.execute("UPDATE ir_config_parameter SET value = %s WHERE key = %s", (shipped_values[SYSTEM_PROMPT_KEY], SYSTEM_PROMPT_KEY))
