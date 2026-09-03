import logging
import re
from urllib.parse import quote

import requests

from odoo import models, api, _
from odoo.exceptions import UserError
from odoo.tools import html_sanitize

_logger = logging.getLogger(__name__)

MAX_INPUT_LENGTH = 20000
POLLINATIONS_MAX_INPUT_LENGTH = 500
POLLINATIONS_URL = "https://text.pollinations.ai/%s"
POLLINATIONS_REFERER = "odoo-ai-text-rewrite"
POLLINATIONS_QUOTA_STATUS_CODES = (402, 403, 429)
OPENAI_UNAUTHORIZED_STATUS_CODES = (401,)
OPENAI_MODEL_NOT_FOUND_STATUS_CODES = (404,)
RESPONSE_DETAIL_LENGTH = 300
MARKDOWN_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n?|\n?```$")


class AiRewriteService(models.AbstractModel):
    _name = "ai.rewrite.service"
    _description = "AI Text Rewrite Service"

    @api.private
    @api.model
    def rewrite(self, text, instruction=False, is_html=False):
        # why: public + unprivate would be callable over RPC by any logged in user, bypassing the
        # route's own checks and spending the configured (possibly paid) API key on arbitrary input
        if not text or not text.strip():
            raise UserError(_("There is no text to rewrite."))

        settings = self._get_ai_settings()
        prompt = self._build_ai_prompt(text, instruction, is_html, settings)

        if len(prompt) > MAX_INPUT_LENGTH:
            raise UserError(_("The text is too long to be rewritten (maximum %s characters).", MAX_INPUT_LENGTH))

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
            "timeout": int(config_parameter_model.get_param("ai_text_rewrite.timeout", 60))
        }

    def _build_ai_prompt(self, text, instruction, is_html, settings=None):
        # why: settings is optional so direct 3-argument calls (as in the original contract) still
        # work; rewrite() passes its own settings down to avoid a second round of get_param calls
        settings = settings or self._get_ai_settings()
        parts = []

        if settings["system_prompt"]:
            parts.append(settings["system_prompt"])

        if instruction:
            parts.append(instruction)

        if is_html:
            parts.append(_("The text is HTML markup: keep the tags and only rewrite the visible content."))

        parts.append(text)
        return "\n\n".join(parts)

    def _call_pollinations(self, prompt, settings):
        # why: measured against the live free endpoint, prompts beyond a few hundred chars get a raw 402
        if len(prompt) > POLLINATIONS_MAX_INPUT_LENGTH:
            raise UserError(_(
                "The free AI service only accepts short texts (up to about %s characters, including the "
                "shared system prompt). For longer texts, configure a provider with an API key in Settings.",
                POLLINATIONS_MAX_INPUT_LENGTH
            ))

        response = self._perform_provider_request(
            "get",
            POLLINATIONS_URL % quote(prompt),
            {"headers": {"Referer": POLLINATIONS_REFERER}, "timeout": settings["timeout"]},
            POLLINATIONS_QUOTA_STATUS_CODES,
            _("The free AI service refused the request: it is a shared public service with no guarantees. "
              "Please try again later or configure a provider with an API key in Settings."),
            _("The free AI service is currently unavailable, please try again later.")
        )
        return response.text

    def _call_openai_compatible(self, prompt, settings):
        if not settings["base_url"] or not settings["model"]:
            raise UserError(_("Please configure the API base URL and the model name in Settings."))

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
            _("The configured API key was rejected, please check it in Settings."),
            _("The configured AI service could not be reached, please check the settings.")
        )
        rewritten = (response.json()["choices"][0]["message"].get("content") or "").strip()

        if not rewritten:
            raise UserError(_("The AI service returned an empty answer, please try again."))

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
                raise UserError(_(
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
