import logging

from odoo import _, http
from odoo.exceptions import UserError
from odoo.http import request

_logger = logging.getLogger(__name__)


class AiTextRewriteController(http.Controller):

    @http.route("/ai_text_rewrite/rewrite", type="json", auth="user")
    def ai_rewrite(self, text, instruction=None, is_html=False, model=None, field=None, res_id=None, record_values=None):
        # auth="user" also lets authenticated portal/share users through (they are not "public"
        # but are not internal users either): restrict this LLM proxy to internal users only.
        if not request.env.user.has_group("base.group_user"):
            return {"error": _("You do not have access to this feature.")}
        if not isinstance(text, str):
            return {"error": _("Invalid text.")}
        if instruction is not None and not isinstance(instruction, str):
            return {"error": _("Invalid instruction.")}
        # why: the style context is optional, a malformed one only loses the examples, never the rewrite
        if not isinstance(model, str) or not isinstance(field, str):
            model = field = None
        if not isinstance(res_id, int) or isinstance(res_id, bool):
            res_id = None
        if not isinstance(record_values, dict) or not model:
            record_values = None
        try:
            rewritten_text = request.env["ai.rewrite.service"].rewrite(
                text, instruction, bool(is_html), model, field, res_id, record_values
            )
        except UserError as e:
            return {"error": str(e)}
        except Exception as e:
            _logger.exception("Unexpected error while rewriting text: %s", e)
            return {"error": _("An unexpected error occurred while rewriting the text.")}
        return {"text": rewritten_text}
