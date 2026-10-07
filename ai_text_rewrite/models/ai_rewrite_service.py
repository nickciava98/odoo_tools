import logging
import re
from urllib.parse import quote

import requests

from odoo import models, api
from odoo.exceptions import AccessError, UserError
from odoo.tools import html2plaintext, html_sanitize

_logger = logging.getLogger(__name__)

MAX_INPUT_LENGTH = 20000
POLLINATIONS_MAX_INPUT_LENGTH = 500
POLLINATIONS_URL = "https://text.pollinations.ai/%s"
POLLINATIONS_REFERER = "odoo-ai-text-rewrite"
POLLINATIONS_QUOTA_STATUS_CODES = (402, 403, 429)
OPENAI_UNAUTHORIZED_STATUS_CODES = (401,)
OPENAI_MODEL_NOT_FOUND_STATUS_CODES = (404,)
RESPONSE_DETAIL_LENGTH = 300
STYLE_EXAMPLE_LIMIT = 10
STYLE_EXAMPLE_MIN_LENGTH = 20
STYLE_EXAMPLE_MAX_LENGTH = 1000
STYLE_EXAMPLES_MAX_LENGTH = 6000
STYLE_FIELD_TYPES = ("char", "html", "text")
RECORD_CONTEXT_MAX_LENGTH = 8000
MARKDOWN_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n?|\n?```$")


class AiRewriteService(models.AbstractModel):
    _name = "ai.rewrite.service"
    _description = "AI Text Rewrite Service"

    @api.private
    @api.model
    def rewrite(self, text, instruction=False, is_html=False, model=False, field=False, res_id=False, record_values=False):
        # why: public + unprivate would be callable over RPC by any logged in user, bypassing the
        # route's own checks and spending the configured (possibly paid) API key on arbitrary input
        if not text or not text.strip():
            raise UserError(self.env._("There is no text to rewrite."))

        settings = self._get_ai_settings()
        prompt = self._build_ai_prompt(text, instruction, is_html, settings)

        if len(prompt) > MAX_INPUT_LENGTH:
            raise UserError(self.env._("The text is too long to be rewritten (maximum %s characters).", MAX_INPUT_LENGTH))

        # why: the free provider caps the whole prompt at a few hundred chars, context would never fit
        if model and settings["provider"] == "openai":
            budget = min(RECORD_CONTEXT_MAX_LENGTH, MAX_INPUT_LENGTH - len(prompt))
            record_context = self._get_record_context(model, field, res_id, record_values or {})[:budget]
            if record_context:
                prompt = self._build_ai_prompt(text, instruction, is_html, settings, record_context=record_context)

            if field and settings["style_enabled"]:
                budget = min(STYLE_EXAMPLES_MAX_LENGTH, MAX_INPUT_LENGTH - len(prompt))
                style_examples = self._get_style_examples(model, field, res_id, text, budget)
                if style_examples:
                    prompt = self._build_ai_prompt(text, instruction, is_html, settings, style_examples, record_context)

        # why: no other trace of an outbound call exists; needed to explain a cost spike or a data query,
        # without logging the text itself or the API key
        _logger.info("AI rewrite request: uid=%s, provider=%s, prompt_length=%s", self.env.uid, settings["provider"], len(prompt))

        if settings["provider"] == "openai":
            raw = self._call_openai_compatible(prompt, settings)
        else:
            raw = self._call_pollinations(prompt, settings)

        return self._clean_ai_response(raw, is_html)

    def _get_ai_settings(self):
        # why: only the config parameters are read with elevated rights, nothing else
        config_parameter_model = self.env["ir.config_parameter"].sudo()
        return {
            "provider": config_parameter_model.get_param("ai_text_rewrite.provider", "openai"),
            "base_url": config_parameter_model.get_param("ai_text_rewrite.base_url"),
            "api_key": config_parameter_model.get_param("ai_text_rewrite.api_key"),
            "model": config_parameter_model.get_param("ai_text_rewrite.model"),
            "system_prompt": config_parameter_model.get_param("ai_text_rewrite.system_prompt"),
            "timeout": int(config_parameter_model.get_param("ai_text_rewrite.timeout", 60)),
            "style_enabled": config_parameter_model.get_param("ai_text_rewrite.style_enabled", "True") != "False"
        }

    def _get_record_context(self, model, field, res_id, record_values):
        return ""

    def _get_style_examples(self, model, field, res_id, text, budget):
        if model not in self.env:
            return []

        record_model = self.env[model]
        model_field = record_model._fields.get(field)

        if not model_field or model_field.type not in STYLE_FIELD_TYPES or not model_field.store:
            return []

        try:
            record_model.check_access("read")
            record_model.check_field_access_rights("read", [field])
        except AccessError:
            return []

        domain = [(field, "!=", False)]

        if res_id:
            domain.append(("id", "!=", res_id))

        # why: the user's own records first, they carry the writing style to imitate
        own_record_ids = record_model.search_fetch(
            domain + [("create_uid", "=", self.env.uid)],
            [field],
            limit=STYLE_EXAMPLE_LIMIT * 3,
            order="write_date desc, id desc"
        )
        other_record_ids = record_model.search_fetch(
            domain + [("create_uid", "!=", self.env.uid)],
            [field],
            limit=STYLE_EXAMPLE_LIMIT * 3,
            order="write_date desc, id desc"
        )
        current_text = self._style_plain_text(text, model_field.type)
        examples = []
        used_length = 0

        for record in own_record_ids + other_record_ids:
            example = self._style_plain_text(record[field], model_field.type)[:STYLE_EXAMPLE_MAX_LENGTH]
            if len(example) < STYLE_EXAMPLE_MIN_LENGTH or example == current_text or example in examples:
                continue
            if used_length + len(example) > budget:
                break
            examples.append(example)
            used_length += len(example)
            if len(examples) >= STYLE_EXAMPLE_LIMIT:
                break

        return examples

    def _style_plain_text(self, value, field_type):
        if field_type == "html":
            value = html2plaintext(value or "")
        return (value or "").strip()

    def _build_ai_prompt(self, text, instruction, is_html, settings=None, style_examples=None, record_context=None):
        # why: settings is optional so direct 3-argument calls (as in the original contract) still
        # work; rewrite() passes its own settings down to avoid a second round of get_param calls
        settings = settings or self._get_ai_settings()
        parts = []

        if settings["system_prompt"]:
            parts.append(settings["system_prompt"])

        if instruction:
            parts.append(instruction)

        if is_html:
            parts.append(self.env._("The text is HTML markup: keep the tags and only rewrite the visible content."))

        if record_context:
            parts.append(
                "Background on the work the text refers to. Use it only to understand and correctly name what the "
                "text already mentions. Never add an activity, a result, a fact or a detail that the text itself "
                "does not mention, even when the background describes it: the background covers the whole work "
                "item, the text covers only one part of it.\n\n"
                "<background>\n%s\n</background>" % record_context
            )

        if style_examples:
            parts.append(
                "Style references: other texts written in this same field of the application. Match their "
                "vocabulary, terminology, tone, structure, length and level of technical detail. They are a style "
                "guide only: never copy a fact, a name, a code or a number from them into the rewrite.\n\n%s"
                % "\n\n".join("<reference>\n%s\n</reference>" % example for example in style_examples)
            )
            parts.append("Text to rewrite:")
        else:
            # why: without references nothing tells the model a field holds labels, which it would inflate
            parts.append("No style references are available: a short label of a few words stays a short label, on one line and with no final full stop. Correct and sharpen it, never develop it into sentences.")

        parts.append(text)
        return "\n\n".join(parts)

    def _call_pollinations(self, prompt, settings):
        # why: measured against the live free endpoint, prompts beyond a few hundred chars get a raw 402
        if len(prompt) > POLLINATIONS_MAX_INPUT_LENGTH:
            raise UserError(self.env._(
                "The free AI service only accepts short texts (up to about %s characters, including the "
                "shared system prompt). For longer texts, configure a provider with an API key in Settings.",
                POLLINATIONS_MAX_INPUT_LENGTH
            ))

        response = self._perform_provider_request(
            "get",
            POLLINATIONS_URL % quote(prompt),
            {"headers": {"Referer": POLLINATIONS_REFERER}, "timeout": settings["timeout"]},
            POLLINATIONS_QUOTA_STATUS_CODES,
            self.env._("The free AI service refused the request: it is a shared public service with no guarantees. "
              "Please try again later or configure a provider with an API key in Settings."),
            self.env._("The free AI service is currently unavailable, please try again later.")
        )
        return response.text

    def _call_openai_compatible(self, prompt, settings):
        if not settings["base_url"] or not settings["model"]:
            raise UserError(self.env._("Please configure the API base URL and the model name in Settings."))

        headers = {"Content-Type": "application/json"}

        if settings["api_key"]:
            headers["Authorization"] = "Bearer %s" % settings["api_key"]

        body = {
            "model": settings["model"],
            "messages": [
                {"role": "system", "content": settings["system_prompt"] or ""},
                {"role": "user", "content": self._strip_leading_system_prompt(prompt, settings)}
            ],
            "temperature": 0.3
        }

        response = self._perform_provider_request(
            "post",
            settings["base_url"].rstrip("/") + "/chat/completions",
            {"headers": headers, "json": body, "timeout": settings["timeout"]},
            OPENAI_UNAUTHORIZED_STATUS_CODES,
            self.env._("The configured API key was rejected, please check it in Settings."),
            self.env._("The configured AI service could not be reached, please check the settings.")
        )
        rewritten = (response.json()["choices"][0]["message"].get("content") or "").strip()

        if not rewritten:
            raise UserError(self.env._("The AI service returned an empty answer, please try again."))

        return rewritten

    def _strip_leading_system_prompt(self, prompt, settings):
        # why: _build_ai_prompt already puts the system prompt in front of the composed prompt for the
        # free provider, which has no separate channel; here it also has its own "system" message above,
        # so the leading copy is dropped to not pay twice for the same tokens on every single call
        system_prompt = settings["system_prompt"]
        prefix = "%s\n\n" % system_prompt if system_prompt else ""
        if prefix and prompt.startswith(prefix):
            return prompt[len(prefix):]
        return prompt

    def _response_detail(self, response):
        if response is None:
            return ""

        try:
            payload = response.json()
        except ValueError:
            return response.text[:RESPONSE_DETAIL_LENGTH]

        error = payload.get("error") if isinstance(payload, dict) else None

        if isinstance(error, dict) and error.get("message"):
            return error["message"][:RESPONSE_DETAIL_LENGTH]

        return response.text[:RESPONSE_DETAIL_LENGTH]

    def _perform_provider_request(self, http_method, url, request_kwargs, quota_status_codes, quota_message, generic_message):
        try:
            response = getattr(requests, http_method)(url, **request_kwargs)
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            # why: the provider explains itself in the body, so logging the status alone
            # turns a precise error ("model does not exist") into an unreadable 404
            _logger.exception("AI rewrite provider call failed: %s\n%s", e, self._response_detail(e.response))
            if e.response is not None and e.response.status_code in quota_status_codes:
                raise UserError(quota_message) from e
            if e.response is not None and e.response.status_code in OPENAI_MODEL_NOT_FOUND_STATUS_CODES:
                raise UserError(self.env._(
                    "The AI service does not know the configured model, or the API key has no access to it. "
                    "Check the model name in Settings.\n%s", self._response_detail(e.response))) from e
            raise UserError(generic_message) from e
        except Exception as e:
            _logger.exception("AI rewrite provider call failed: %s", e)
            raise UserError(generic_message) from e

        return response

    def _clean_ai_response(self, raw, is_html):
        cleaned = MARKDOWN_FENCE_RE.sub("", raw.strip()).strip()

        if is_html:
            cleaned = html_sanitize(cleaned)

        return cleaned
