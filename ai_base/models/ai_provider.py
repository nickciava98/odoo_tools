import logging

import requests

from odoo import models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

RATE_LIMIT_STATUS_CODE = 429
BAD_REQUEST_STATUS_CODE = 400
# why: Groq answers 413 when one request alone exceeds the tokens per minute of the model, it can never pass as is
PAYLOAD_TOO_LARGE_STATUS_CODE = 413
# why: Groq validates the tool calls the model generates and answers 400 with this code on a malformed one
TOOL_CALL_ERROR_CODE = "tool_use_failed"
MODEL_NOT_FOUND_STATUS_CODES = (404,)
RESPONSE_DETAIL_LENGTH = 300


class AiProviderRateLimitError(UserError):

    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


class AiProviderPayloadTooLargeError(UserError):
    pass


class AiProviderToolCallError(UserError):

    def __init__(self, message, detail=""):
        super().__init__(message)
        self.detail = detail


class AiProvider(models.AbstractModel):
    _name = "ai.provider"
    _description = "AI Provider"

    def _get_provider_settings(self):
        # why: only the config parameters are read with elevated rights, nothing else
        config_parameter_model = self.env["ir.config_parameter"].sudo()
        return {
            "base_url": config_parameter_model.get_param("ai_base.base_url"),
            "api_key": config_parameter_model.get_param("ai_base.api_key"),
            "model": config_parameter_model.get_param("ai_base.model"),
            "timeout": int(config_parameter_model.get_param("ai_base.timeout", 60) or 60)
        }

    def _chat_completion(self, messages, tools=None, model=False, temperature=0.3, tool_choice="auto"):
        settings = self._get_provider_settings()
        model = model or settings["model"]

        if not settings["base_url"] or not model:
            raise UserError(self.env._("Please configure the AI provider base URL and model in Settings."))

        headers = {"Content-Type": "application/json"}

        if settings["api_key"]:
            headers["Authorization"] = "Bearer %s" % settings["api_key"]

        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature
        }

        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice

        response = self._perform_provider_request(
            "post",
            settings["base_url"].rstrip("/") + "/chat/completions",
            {"headers": headers, "json": body, "timeout": settings["timeout"]},
            (401,),
            self.env._("The configured API key was rejected, please check it in Settings."),
            self.env._("The configured AI service could not be reached, please check the settings.")
        )
        payload = response.json()
        usage = payload.get("usage") or {}
        # why: the only trace of what each call costs against the provider's tokens per minute and per day quotas
        _logger.info(
            "AI provider call: model=%s, prompt_tokens=%s, completion_tokens=%s, remaining_tokens_minute=%s",
            model, usage.get("prompt_tokens"), usage.get("completion_tokens"), response.headers.get("x-ratelimit-remaining-tokens")
        )
        return payload["choices"][0]["message"]

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
            status_code = e.response.status_code if e.response is not None else None
            # why: a rate limit is expected on free tiers and the callers retry it, a traceback would read as a failure
            if status_code == RATE_LIMIT_STATUS_CODE and status_code not in quota_status_codes:
                _logger.warning("AI provider rate limit: %s", self._response_detail(e.response))
            else:
                _logger.exception("AI provider call failed: %s\n%s", e, self._response_detail(e.response))
            if status_code in quota_status_codes:
                raise UserError(quota_message) from e
            if status_code == RATE_LIMIT_STATUS_CODE:
                retry_after = self._parse_retry_after(e.response)
                if retry_after and retry_after >= 60:
                    message = self.env._("The AI service has reached its usage limit, please try again in %s minutes.", -(-retry_after // 60))
                else:
                    message = self.env._("The AI service is receiving too many requests, please try again in a moment.")
                raise AiProviderRateLimitError(message, retry_after) from e
            if status_code == BAD_REQUEST_STATUS_CODE and self._response_error_code(e.response) == TOOL_CALL_ERROR_CODE:
                raise AiProviderToolCallError(
                    self.env._("The AI model produced an invalid tool call, please try again."),
                    self._response_detail(e.response)
                ) from e
            if status_code == PAYLOAD_TOO_LARGE_STATUS_CODE:
                raise AiProviderPayloadTooLargeError(self.env._(
                    "The question needs more data than the AI service accepts in one request: "
                    "narrow it down, e.g. a shorter period or a single project."
                )) from e
            if status_code in MODEL_NOT_FOUND_STATUS_CODES:
                raise UserError(self.env._(
                    "The AI service does not know the configured model, or the API key has no access to it. "
                    "Check the model name in Settings.\n%s", self._response_detail(e.response))) from e
            raise UserError(generic_message) from e
        except Exception as e:
            _logger.exception("AI provider call failed: %s", e)
            raise UserError(generic_message) from e

        return response

    def _response_error_code(self, response):
        try:
            error = response.json().get("error")
        except (AttributeError, ValueError):
            return False
        return error.get("code") if isinstance(error, dict) else False

    def _parse_retry_after(self, response):
        try:
            return int(float(response.headers.get("Retry-After")))
        except (TypeError, ValueError):
            return None
