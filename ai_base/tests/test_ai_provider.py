# Copyright 2026 Niccolò Ciavarella
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import requests
from lxml import etree
from requests.structures import CaseInsensitiveDict

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger
from odoo.tools.misc import file_open

from odoo.addons.ai_base.models.ai_provider import AiProviderPayloadTooLargeError, AiProviderRateLimitError, AiProviderToolCallError

# Namespace where requests is *used*: patch here, not where it is defined.
_MODULE = "odoo.addons.ai_base.models.ai_provider"

BASE_URL = "https://api.groq.com/openai/v1"
MODEL = "openai/gpt-oss-120b"
MESSAGES = [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "How many quotations?"}]
TOOLS = [{"type": "function", "function": {"name": "list_models", "parameters": {"type": "object", "properties": {}}}}]
ANSWER = {"role": "assistant", "content": "There are 3 quotations."}
MISSING_CONFIGURATION_MESSAGE = "Please configure the AI provider base URL and model in Settings."


@tagged("post_install", "-at_install")
class TestAiProvider(TransactionCase):
    """Contract of the ai.provider abstract model, the single LLM client of the ai_* modules. No test may reach the network."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env["ai.provider"]
        cls.config_param = cls.env["ir.config_parameter"].sudo()

    def _set_settings(self, **values):
        for key, value in values.items():
            self.config_param.set_param("ai_base.%s" % key, value)
        return True

    def _configure(self, **values):
        settings = {"base_url": BASE_URL, "model": MODEL, "api_key": "test-api-key", "timeout": 42}
        settings.update(values)
        return self._set_settings(**settings)

    @contextmanager
    def _mocked_requests(self, answer=None):
        requests_mock = MagicMock(name="requests")
        requests_mock.exceptions = requests.exceptions
        requests_mock.post.return_value.json.return_value = {"choices": [{"message": answer or ANSWER}]}
        with patch("%s.requests" % _MODULE, requests_mock):
            yield requests_mock

    def _http_error(self, status_code, body=None, headers=None):
        response_mock = MagicMock(name="response")
        response_mock.status_code = status_code
        response_mock.headers = CaseInsensitiveDict(headers or {})
        response_mock.json.return_value = body or {}
        response_mock.text = json.dumps(body or {})
        return requests.exceptions.HTTPError("%s Error" % status_code, response=response_mock)

    def _failing_call(self, status_code, body=None, headers=None, expected_exception=UserError):
        self._configure()
        with self._mocked_requests() as requests_mock:
            requests_mock.post.return_value.raise_for_status.side_effect = self._http_error(status_code, body, headers)
            with self.assertRaises(expected_exception) as raised:
                self.provider._chat_completion(MESSAGES)
        return raised.exception

    # ------------------------------------------------------------------
    # 1. Settings
    # ------------------------------------------------------------------

    def test_provider_settings_are_read_from_the_ai_base_parameters(self):
        # The provider is shared by every ai_* module: its configuration lives on its own ai_base.* keys.
        self._configure(base_url="https://llm.example.invalid/v1", model="some-model", api_key="sk-123", timeout=17)
        self.assertEqual(self.provider._get_provider_settings(), {
            "base_url": "https://llm.example.invalid/v1",
            "api_key": "sk-123",
            "model": "some-model",
            "timeout": 17
        })

    def test_provider_settings_ignore_the_old_ai_text_rewrite_parameters(self):
        # After the 2.0 split the rewrite keys are dead: reading them would resurrect a stale configuration.
        self._configure(base_url=False, model=False)
        self.config_param.set_param("ai_text_rewrite.base_url", "https://old.example.invalid/v1")
        self.config_param.set_param("ai_text_rewrite.model", "old-model")
        settings = self.provider._get_provider_settings()
        self.assertFalse(settings["base_url"])
        self.assertFalse(settings["model"])

    def test_timeout_defaults_to_sixty_seconds_as_an_integer(self):
        # get_param returns strings: an un-cast or missing timeout would be handed to requests as text or None.
        self._set_settings(timeout=False)
        settings = self.provider._get_provider_settings()
        self.assertIsInstance(settings["timeout"], int)
        self.assertEqual(settings["timeout"], 60)

    def test_shipped_data_points_at_groq(self):
        # Decision of 21/10/2026: default provider is Groq (no training on the data). Read the shipped file,
        # not the stored parameter: data/ is noupdate="1" and a database may hold anything by now.
        with file_open("ai_base/data/ai_base_data.xml", "rb") as data_file:
            shipped_values = {
                record.findtext("field[@name='key']"): record.findtext("field[@name='value']")
                for record in etree.parse(data_file).xpath("//record[@model='ir.config_parameter']")
            }
        self.assertEqual(shipped_values.get("ai_base.base_url"), BASE_URL)
        self.assertEqual(shipped_values.get("ai_base.model"), MODEL)
        self.assertEqual(shipped_values.get("ai_base.timeout"), "60")
        self.assertNotIn("ai_base.api_key", shipped_values, "No API key may ship with the module")

    # ------------------------------------------------------------------
    # 2. Request shape
    # ------------------------------------------------------------------

    def test_chat_completion_posts_the_openai_compatible_payload(self):
        # Golden path: one POST on /chat/completions with model, messages, temperature, bearer and timeout.
        self._configure()
        with self._mocked_requests() as requests_mock:
            answer = self.provider._chat_completion(MESSAGES)
        requests_mock.post.assert_called_once()
        call_args = requests_mock.post.call_args
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url")
        self.assertEqual(url, "%s/chat/completions" % BASE_URL)
        self.assertEqual(call_args.kwargs.get("headers", {}).get("Authorization"), "Bearer test-api-key")
        self.assertEqual(call_args.kwargs.get("timeout"), 42)
        self.assertEqual(call_args.kwargs.get("json"), {"model": MODEL, "messages": MESSAGES, "temperature": 0.3})
        self.assertEqual(answer, ANSWER)

    def test_chat_completion_strips_a_trailing_slash_from_the_base_url(self):
        # A base URL pasted with its final slash must not become "//chat/completions", which some gateways 404.
        self._configure(base_url="%s/" % BASE_URL)
        with self._mocked_requests() as requests_mock:
            self.provider._chat_completion(MESSAGES)
        call_args = requests_mock.post.call_args
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url")
        self.assertEqual(url, "%s/chat/completions" % BASE_URL)

    def test_chat_completion_omits_the_authorization_header_without_api_key(self):
        # An empty key means a local endpoint (Ollama), which rejects a bare "Bearer " header.
        self._configure(base_url="http://localhost:11434/v1", api_key=False, model="llama3")
        with self._mocked_requests() as requests_mock:
            self.provider._chat_completion(MESSAGES)
        self.assertNotIn("Authorization", requests_mock.post.call_args.kwargs.get("headers", {}))

    def test_chat_completion_sends_tools_only_when_given(self):
        # Some endpoints refuse an empty "tools" list or a "tool_choice" without tools: plain calls carry neither.
        self._configure()
        with self._mocked_requests() as requests_mock:
            self.provider._chat_completion(MESSAGES)
        payload = requests_mock.post.call_args.kwargs.get("json", {})
        self.assertNotIn("tools", payload)
        self.assertNotIn("tool_choice", payload)

    def test_chat_completion_sends_tools_with_automatic_choice(self):
        # The chatbot hands its tool schemas over: the model must be free to call them or to answer.
        self._configure()
        with self._mocked_requests() as requests_mock:
            self.provider._chat_completion(MESSAGES, tools=TOOLS)
        payload = requests_mock.post.call_args.kwargs.get("json", {})
        self.assertEqual(payload.get("tools"), TOOLS)
        self.assertEqual(payload.get("tool_choice"), "auto")

    def test_chat_completion_model_argument_overrides_the_configured_one(self):
        # The chatbot may run on a dedicated model while the rewrite keeps the shared one.
        self._configure()
        with self._mocked_requests() as requests_mock:
            self.provider._chat_completion(MESSAGES, model="dedicated-model", temperature=0.0)
        payload = requests_mock.post.call_args.kwargs.get("json", {})
        self.assertEqual(payload.get("model"), "dedicated-model")
        self.assertEqual(payload.get("temperature"), 0.0)

    def test_chat_completion_returns_the_tool_calls_untouched(self):
        # The agent loop needs the raw assistant message, tool_calls included, to run the requested tools.
        tool_answer = {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "list_models", "arguments": "{}"}}]
        }
        self._configure()
        with self._mocked_requests(answer=tool_answer):
            answer = self.provider._chat_completion(MESSAGES, tools=TOOLS)
        self.assertEqual(answer, tool_answer)

    def test_missing_base_url_is_a_settings_error_and_issues_no_call(self):
        # A half configured endpoint must be reported as a settings problem, not as a network error.
        self._configure(base_url=False)
        with self._mocked_requests() as requests_mock, self.assertRaises(UserError) as raised:
            self.provider._chat_completion(MESSAGES)
        requests_mock.post.assert_not_called()
        self.assertEqual(str(raised.exception), MISSING_CONFIGURATION_MESSAGE)

    def test_missing_model_is_a_settings_error_and_issues_no_call(self):
        self._configure(model=False)
        with self._mocked_requests() as requests_mock, self.assertRaises(UserError) as raised:
            self.provider._chat_completion(MESSAGES)
        requests_mock.post.assert_not_called()
        self.assertEqual(str(raised.exception), MISSING_CONFIGURATION_MESSAGE)

    def test_model_argument_fills_a_missing_configured_model(self):
        # The override is a real model choice: with it, an empty shared model is not a configuration error.
        self._configure(model=False)
        with self._mocked_requests() as requests_mock:
            self.provider._chat_completion(MESSAGES, model="dedicated-model")
        self.assertEqual(requests_mock.post.call_args.kwargs["json"]["model"], "dedicated-model")

    # ------------------------------------------------------------------
    # 3. Error mapping
    # ------------------------------------------------------------------

    @mute_logger(_MODULE)
    def test_rejected_api_key_gets_a_dedicated_message(self):
        # A 401 is a wrong key in Settings: calling it "unreachable" sends the reader hunting the network.
        generic_message = str(self._failing_call(500))
        unauthorized_message = str(self._failing_call(401))
        self.assertTrue(unauthorized_message.strip())
        self.assertNotEqual(unauthorized_message, generic_message)
        self.assertNotIn("Traceback", unauthorized_message)

    @mute_logger(_MODULE)
    def test_unknown_model_says_so_with_the_provider_detail(self):
        # A 404 means the model is unknown to the endpoint, and the provider's own words say which one.
        message = str(self._failing_call(404, {"error": {"message": "The model `some-model` does not exist."}}))
        self.assertIn("does not know the configured model", message)
        self.assertIn("some-model", message)

    @mute_logger(_MODULE)
    def test_a_non_json_error_body_is_still_reported(self):
        # Not every gateway answers JSON; the raw body is more useful than nothing at all.
        self._configure()
        response_mock = MagicMock(name="response")
        response_mock.status_code = 404
        response_mock.headers = CaseInsensitiveDict()
        response_mock.json.side_effect = ValueError("not json")
        response_mock.text = "<html>404 Not Found</html>"
        with self._mocked_requests() as requests_mock:
            requests_mock.post.return_value.raise_for_status.side_effect = requests.exceptions.HTTPError("404", response=response_mock)
            with self.assertRaises(UserError) as raised:
                self.provider._chat_completion(MESSAGES)
        self.assertIn("404 Not Found", str(raised.exception))

    @mute_logger(_MODULE)
    def test_other_http_errors_get_the_generic_message(self):
        message = str(self._failing_call(500))
        self.assertTrue(message.strip())
        self.assertNotIn("Traceback", message)

    @mute_logger(_MODULE)
    def test_a_network_failure_is_a_user_error(self):
        # Timeout or DNS failure must reach the user as a readable message, never as a traceback.
        self._configure()
        with self._mocked_requests() as requests_mock:
            requests_mock.post.side_effect = requests.exceptions.Timeout("connection timed out")
            with self.assertRaises(UserError) as raised:
                self.provider._chat_completion(MESSAGES)
        self.assertTrue(str(raised.exception).strip())
        self.assertNotIsInstance(raised.exception, AiProviderRateLimitError)

    def test_a_response_detail_without_a_response_is_empty(self):
        self.assertEqual(self.provider._response_detail(None), "")

    # ------------------------------------------------------------------
    # 4. Rate limit (429)
    # ------------------------------------------------------------------

    def test_rate_limit_error_is_a_user_error(self):
        # Any caller that only catches UserError (the rewrite dialog) must keep showing a readable message.
        self.assertTrue(issubclass(AiProviderRateLimitError, UserError))

    @mute_logger(_MODULE)
    def test_400_on_an_invalid_tool_call_raises_the_tool_call_error(self):
        # Groq rejects a malformed tool call the model generated: the chatbot can retry the step with the reason.
        body = {"error": {"message": "parameters for tool aggregate_records did not match schema", "code": "tool_use_failed"}}
        error = self._failing_call(400, body, expected_exception=AiProviderToolCallError)
        self.assertIn("did not match schema", error.detail)

    @mute_logger(_MODULE)
    def test_413_raises_the_payload_too_large_error(self):
        self._failing_call(413, expected_exception=AiProviderPayloadTooLargeError)

    @mute_logger(_MODULE)
    def test_other_400_errors_get_the_generic_message(self):
        error = self._failing_call(400, {"error": {"message": "bad", "code": "invalid_request"}})
        self.assertNotIsInstance(error, AiProviderToolCallError)

    @mute_logger(_MODULE)
    def test_429_raises_the_rate_limit_error_with_retry_after(self):
        # Groq answers 429 with Retry-After on its free tier: the chatbot waits that long once and retries.
        error = self._failing_call(429, headers={"Retry-After": "7"}, expected_exception=AiProviderRateLimitError)
        self.assertEqual(error.retry_after, 7)
        self.assertTrue(str(error).strip())

    @mute_logger(_MODULE)
    def test_429_with_a_long_wait_says_how_many_minutes(self):
        error = self._failing_call(429, headers={"Retry-After": "406"}, expected_exception=AiProviderRateLimitError)
        self.assertIn("7 minutes", str(error))

    @mute_logger(_MODULE)
    def test_429_without_retry_after_carries_none(self):
        # No header means no hint: the caller must not invent a wait.
        error = self._failing_call(429, expected_exception=AiProviderRateLimitError)
        self.assertIsNone(error.retry_after)

    @mute_logger(_MODULE)
    def test_429_with_an_unparsable_retry_after_carries_none(self):
        # Retry-After may also be an HTTP date: an unreadable value must not crash the error mapping.
        error = self._failing_call(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, expected_exception=AiProviderRateLimitError)
        self.assertIsNone(error.retry_after)

    @mute_logger(_MODULE)
    def test_429_listed_by_the_caller_keeps_the_caller_quota_message(self):
        # The free Pollinations service passes 429 among its quota codes: there it means "configure a key",
        # and must keep that message instead of becoming a retryable rate limit.
        with self._mocked_requests() as requests_mock:
            requests_mock.get.return_value.raise_for_status.side_effect = self._http_error(429, headers={"Retry-After": "7"})
            with self.assertRaises(UserError) as raised:
                self.provider._perform_provider_request(
                    "get",
                    "https://text.pollinations.ai/hello",
                    {"timeout": 10},
                    (402, 403, 429),
                    "Quota message.",
                    "Generic message."
                )
        self.assertNotIsInstance(raised.exception, AiProviderRateLimitError)
        self.assertEqual(str(raised.exception), "Quota message.")

    def test_perform_provider_request_returns_the_response_and_forwards_the_kwargs(self):
        # The helper moved from ai_text_rewrite unchanged: same method, url and kwargs reach requests.
        with self._mocked_requests() as requests_mock:
            response = self.provider._perform_provider_request(
                "get",
                "https://text.pollinations.ai/hello",
                {"headers": {"Referer": "odoo-ai-text-rewrite"}, "timeout": 10},
                (402,),
                "Quota message.",
                "Generic message."
            )
        requests_mock.get.assert_called_once_with("https://text.pollinations.ai/hello", headers={"Referer": "odoo-ai-text-rewrite"}, timeout=10)
        self.assertIs(response, requests_mock.get.return_value)
