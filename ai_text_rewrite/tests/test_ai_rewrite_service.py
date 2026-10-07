# Copyright 2026 Niccolò Ciavarella
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from urllib.parse import unquote

import requests
from lxml import etree

from odoo.exceptions import AccessError, UserError
from odoo.service.model import get_public_method
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger
from odoo.tools.misc import file_open

from odoo.addons.ai_text_rewrite.models.ai_rewrite_service import MAX_INPUT_LENGTH, POLLINATIONS_MAX_INPUT_LENGTH

# Namespace where the symbols are *used*: patch here, not where they are defined.
_MODULE = "odoo.addons.ai_text_rewrite.models.ai_rewrite_service"

SYSTEM_PROMPT = "SENTINEL SYSTEM PROMPT: never change a number."
POLLINATIONS_URL_PREFIX = "https://text.pollinations.ai/"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.3-70b-versatile"


@tagged("post_install", "-at_install")
class TestAiRewriteService(TransactionCase):
    """Contract of the ai.rewrite.service abstract model. No test may reach the network."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = cls.env["ai.rewrite.service"]
        cls.config_param = cls.env["ir.config_parameter"].sudo()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_settings(self, **values):
        """Write the module config parameters; a falsy value deletes the parameter."""
        for key, value in values.items():
            self.config_param.set_param("ai_text_rewrite.%s" % key, value)
        return True

    def _use_openai(self, **values):
        """Select the OpenAI-compatible provider with a complete, valid configuration."""
        settings = {"provider": "openai", "base_url": GROQ_BASE_URL, "model": GROQ_MODEL}
        settings.update(values)
        return self._set_settings(**settings)

    def _use_pollinations(self, **values):
        """Select the free provider with a short system prompt, well below its own input limit."""
        settings = {"provider": "pollinations", "system_prompt": "Rewrite it."}
        settings.update(values)
        return self._set_settings(**settings)

    @contextmanager
    def _mocked_requests(self):
        """Replace the requests module seen by the service, so a real HTTP call is impossible."""
        requests_mock = MagicMock(name="requests")
        requests_mock.exceptions = requests.exceptions
        with patch("%s.requests" % _MODULE, requests_mock):
            yield requests_mock

    @contextmanager
    def _mocked_providers(self, pollinations=None, openai=None):
        """Patch both provider helpers; autospec keeps the recordset as first call argument."""
        service_cls = type(self.service)
        with patch.object(service_cls, "_call_pollinations", autospec=True) as pollinations_mock, patch.object(
            service_cls, "_call_openai_compatible", autospec=True
        ) as openai_mock:
            pollinations_mock.return_value = pollinations if pollinations is not None else "Rewritten by the free provider."
            openai_mock.return_value = openai if openai is not None else "Rewritten by the openai endpoint."
            yield pollinations_mock, openai_mock

    def _http_call(self, requests_mock):
        """Return (args, kwargs) of the single HTTP call issued through the mocked requests module."""
        for method in ("get", "post", "request"):
            call_args = getattr(requests_mock, method).call_args
            if call_args is not None:
                return call_args.args, call_args.kwargs
        raise AssertionError("The provider issued no HTTP call at all")

    def _called_url(self, args, kwargs):
        if args:
            return args[0]
        return kwargs.get("url")

    def _http_error(self, status_code):
        """Build the HTTPError that requests raises from raise_for_status() for a given status."""
        response_mock = MagicMock(name="response")
        response_mock.status_code = status_code
        return requests.exceptions.HTTPError("%s Error" % status_code, response=response_mock)

    def _provider_error_message(self, method, settings, status_code):
        """Return the message the user gets when the provider answers with the given HTTP status."""
        with self._mocked_requests() as requests_mock:
            requests_mock.get.return_value.raise_for_status.side_effect = self._http_error(status_code)
            requests_mock.post.return_value.raise_for_status.side_effect = self._http_error(status_code)
            with self.assertRaises(UserError) as error:
                getattr(self.service, method)("Rewrite this text please", settings)
        return str(error.exception)

    # ------------------------------------------------------------------
    # 1. Input guards
    # ------------------------------------------------------------------

    def test_rewrite_raises_when_text_is_empty(self):
        # Contract "API — Model layer": empty text is a user mistake, not a provider round trip.
        with self._mocked_providers() as (pollinations_mock, openai_mock), self.assertRaises(UserError):
            self.service.rewrite("")
        pollinations_mock.assert_not_called()
        openai_mock.assert_not_called()

    def test_rewrite_raises_when_text_is_only_whitespace(self):
        # Contract: "text vuoto/solo spazi" — a field holding blanks has nothing to rewrite.
        with self._mocked_providers() as (pollinations_mock, openai_mock), self.assertRaises(UserError):
            self.service.rewrite("   \n\t  ")
        pollinations_mock.assert_not_called()
        openai_mock.assert_not_called()

    def test_max_input_length_is_the_agreed_limit(self):
        # Contract: the cap is a module constant the whole stack shares, fixed at 20000 characters.
        self.assertEqual(MAX_INPUT_LENGTH, 20000)

    def test_rewrite_raises_when_text_exceeds_max_input_length(self):
        # Contract: oversized input must be refused locally, before paying for a provider call.
        with self._mocked_providers() as (pollinations_mock, openai_mock), self.assertRaises(UserError):
            self.service.rewrite("a" * (MAX_INPUT_LENGTH + 1))
        pollinations_mock.assert_not_called()
        openai_mock.assert_not_called()

    def test_rewrite_accepts_a_composed_prompt_of_exactly_max_input_length(self):
        # The cap is on what is actually sent and it is inclusive: a text that exactly fills the budget
        # left by the system prompt must still go through. The budget comes from the real builder.
        self._use_openai(system_prompt=SYSTEM_PROMPT)
        prompt_overhead = len(self.service._build_ai_prompt("", False, False))
        text = "a" * (MAX_INPUT_LENGTH - prompt_overhead)
        with self._mocked_providers(openai="Rewritten.") as (_pollinations_mock, openai_mock):
            result = self.service.rewrite(text)
        self.assertEqual(result, "Rewritten.")
        self.assertEqual(len(openai_mock.call_args.args[1]), MAX_INPUT_LENGTH)

    def test_rewrite_refuses_when_the_system_prompt_pushes_it_over_the_cap(self):
        # One character over the budget: the text alone is still under the cap, the composed prompt is not.
        # Guarding only the field left the shared system prompt free to overflow whatever is sent.
        self._use_openai(system_prompt=SYSTEM_PROMPT)
        prompt_overhead = len(self.service._build_ai_prompt("", False, False))
        text = "a" * (MAX_INPUT_LENGTH - prompt_overhead + 1)
        self.assertLess(len(text), MAX_INPUT_LENGTH)
        with self._mocked_providers() as (pollinations_mock, openai_mock), self.assertRaises(UserError):
            self.service.rewrite(text)
        pollinations_mock.assert_not_called()
        openai_mock.assert_not_called()

    def test_rewrite_counts_the_instruction_in_the_cap(self):
        # The instruction is free text coming from the dialog: leaving it out of the cap left the paid
        # provider open to an unbounded prompt built from a perfectly short field.
        self._use_openai(system_prompt=SYSTEM_PROMPT)
        with self._mocked_providers() as (pollinations_mock, openai_mock), self.assertRaises(UserError):
            self.service.rewrite("Invoice 12 is late.", "i" * MAX_INPUT_LENGTH)
        pollinations_mock.assert_not_called()
        openai_mock.assert_not_called()

    # ------------------------------------------------------------------
    # 2. Settings
    # ------------------------------------------------------------------

    def test_shipped_data_selects_the_openai_provider(self):
        # The free service was measured refusing real prompts (402 above ~580 chars), so a fresh install
        # must point at the paid-tier endpoint. Read the shipped file and not the stored parameter:
        # data/ is noupdate="1", so a database installed before the switch still holds the old value.
        with file_open("ai_text_rewrite/data/ai_rewrite_data.xml", "rb") as data_file:
            shipped_values = {
                record.findtext("field[@name='key']"): record.findtext("field[@name='value']")
                for record in etree.parse(data_file).xpath("//record[@model='ir.config_parameter']")
            }
        self.assertEqual(shipped_values.get("ai_text_rewrite.provider"), "openai")
        self.assertEqual(shipped_values.get("ai_text_rewrite.base_url"), GROQ_BASE_URL)
        self.assertTrue(shipped_values.get("ai_text_rewrite.model"))

    def test_default_provider_is_openai_when_the_parameter_is_missing(self):
        # An administrator clearing the parameter must not silently fall back to the free service.
        self._set_settings(provider=False)
        self.assertEqual(self.service._get_ai_settings()["provider"], "openai")

    def test_stored_provider_wins_over_the_default(self):
        # The free provider stays selectable: the fallback must not be hard-coded over the stored choice.
        self._set_settings(provider="pollinations")
        self.assertEqual(self.service._get_ai_settings()["provider"], "pollinations")

    def test_settings_expose_every_contract_key(self):
        # Contract: _get_ai_settings() is the single source the two providers read from.
        self.assertEqual(
            set(self.service._get_ai_settings()),
            {"provider", "base_url", "api_key", "model", "system_prompt", "timeout", "style_enabled"}
        )

    def test_settings_timeout_is_an_integer(self):
        # get_param returns strings: an un-cast timeout would be handed to requests as text.
        self._set_settings(timeout=False)
        settings = self.service._get_ai_settings()
        self.assertIsInstance(settings["timeout"], int)
        self.assertEqual(settings["timeout"], 60)

    def test_settings_carry_a_non_empty_system_prompt_by_default(self):
        # Contract "data/ai_rewrite_data.xml": the shared "how to rewrite" instruction ships with the module.
        self.assertTrue(self.service._get_ai_settings()["system_prompt"].strip())

    # ------------------------------------------------------------------
    # 3. Prompt building
    # ------------------------------------------------------------------

    def test_build_ai_prompt_includes_the_configured_system_prompt(self):
        # Contract: the prompt set in Settings is shared by every field, so it must reach the model.
        self._set_settings(system_prompt=SYSTEM_PROMPT)
        prompt = self.service._build_ai_prompt("Invoice 12 is late.", False, False)
        self.assertIn(SYSTEM_PROMPT, prompt)
        self.assertIn("Invoice 12 is late.", prompt)

    def test_build_ai_prompt_includes_the_user_instruction(self):
        # The dialog lets the user edit the instruction: dropping it would make that field decorative.
        self._set_settings(system_prompt=SYSTEM_PROMPT)
        prompt = self.service._build_ai_prompt("Invoice 12 is late.", "Make it shorter and polite.", False)
        self.assertIn("Make it shorter and polite.", prompt)
        self.assertIn(SYSTEM_PROMPT, prompt)

    def test_rewrite_sends_the_prompt_built_by_build_ai_prompt(self):
        # The prompt actually sent must be the one the real builder produces, not a second hand-rolled format.
        self._use_openai(system_prompt=SYSTEM_PROMPT)
        expected_prompt = self.service._build_ai_prompt("Invoice 12 is late.", "Make it polite.", False)
        with self._mocked_providers(openai="Rewritten.") as (_pollinations_mock, openai_mock):
            self.service.rewrite("Invoice 12 is late.", "Make it polite.", False)
        self.assertEqual(openai_mock.call_args.args[1], expected_prompt)

    # ------------------------------------------------------------------
    # 4. Response cleaning
    # ------------------------------------------------------------------

    def test_clean_ai_response_strips_markdown_fences(self):
        # Models wrap answers in ``` fences: pasted as is, the fence lands in the customer facing field.
        cleaned = self.service._clean_ai_response("```\nPlain answer.\n```", False)
        self.assertEqual(cleaned, "Plain answer.")

    def test_clean_ai_response_strips_language_tagged_markdown_fences(self):
        # Same defect with the ```html variant, which is what an html field usually gets back.
        cleaned = self.service._clean_ai_response("```html\n<p>Hello there.</p>\n```", True)
        self.assertNotIn("```", cleaned)
        self.assertNotIn("html\n", cleaned)
        self.assertIn("Hello there.", cleaned)

    def test_clean_ai_response_strips_surrounding_whitespace(self):
        # Contract: the cleaned answer is stripped, so replacing does not add blank lines to the field.
        self.assertEqual(self.service._clean_ai_response("\n\n  Plain answer.  \n", False), "Plain answer.")

    def test_clean_ai_response_leaves_a_plain_answer_unchanged(self):
        # The cleaner must not damage a well behaved answer.
        self.assertEqual(self.service._clean_ai_response("Plain answer.", False), "Plain answer.")

    def test_clean_ai_response_sanitizes_the_html_returned_by_the_model(self):
        # Security: an LLM answer is untrusted input, a <script> must never reach an html field.
        raw = "<p>Legit paragraph.</p><script>alert('xss')</script><img src=x onerror=alert(1)>"
        cleaned = self.service._clean_ai_response(raw, True)
        self.assertNotIn("<script", cleaned)
        self.assertNotIn("alert(", cleaned)
        self.assertNotIn("onerror", cleaned)
        self.assertIn("Legit paragraph.", cleaned)

    def test_clean_ai_response_keeps_markup_characters_in_plain_text(self):
        # A text field is not html: escaping here would show "&lt;" to the user.
        cleaned = self.service._clean_ai_response("Quantity 5 < 6 & margin > 3", False)
        self.assertEqual(cleaned, "Quantity 5 < 6 & margin > 3")

    # ------------------------------------------------------------------
    # 5. Full rewrite() flow, providers mocked
    # ------------------------------------------------------------------

    def test_rewrite_returns_the_cleaned_provider_answer(self):
        # Golden path: rewrite() returns a plain string, already cleaned, ready to replace the field value.
        self._use_openai()
        with self._mocked_providers(openai="```\nRewritten sentence.\n```") as (pollinations_mock, openai_mock):
            result = self.service.rewrite("Sentence to rewrite.")
        self.assertEqual(result, "Rewritten sentence.")
        self.assertIsInstance(result, str)
        openai_mock.assert_called_once()
        pollinations_mock.assert_not_called()

    def test_rewrite_routes_to_the_free_provider_when_configured(self):
        # Choosing the free service in Settings must actually change the provider that is called.
        self._use_pollinations()
        with self._mocked_providers(pollinations="Rewritten sentence.") as (pollinations_mock, openai_mock):
            result = self.service.rewrite("Sentence to rewrite.")
        self.assertEqual(result, "Rewritten sentence.")
        pollinations_mock.assert_called_once()
        openai_mock.assert_not_called()

    def test_rewrite_never_returns_unsanitized_html(self):
        # End to end guard: the sanitising must happen inside rewrite(), not only in the helper.
        self._use_openai()
        raw = "<p>Legit paragraph.</p><script>alert('xss')</script>"
        with self._mocked_providers(openai=raw):
            result = self.service.rewrite("<p>Something.</p>", False, True)
        self.assertNotIn("<script", result)
        self.assertNotIn("alert(", result)
        self.assertIn("Legit paragraph.", result)

    # ------------------------------------------------------------------
    # 6. Provider wiring, requests mocked
    # ------------------------------------------------------------------

    def test_pollinations_request_carries_the_referer_header_and_the_timeout(self):
        # Contract: without the Referer header the free service answers 402, and a call without timeout hangs a worker.
        self._use_pollinations(timeout=42)
        settings = self.service._get_ai_settings()
        with self._mocked_requests() as requests_mock:
            requests_mock.get.return_value.text = "Rewritten by the free provider."
            raw = self.service._call_pollinations("Rewrite this text please", settings)
            args, kwargs = self._http_call(requests_mock)
        self.assertEqual(raw, "Rewritten by the free provider.")
        url = self._called_url(args, kwargs)
        self.assertTrue(url.startswith(POLLINATIONS_URL_PREFIX), "The free provider must be called on %s, got %s" % (POLLINATIONS_URL_PREFIX, url))
        self.assertNotIn(" ", url, "The prompt must be url encoded")
        self.assertEqual(kwargs.get("headers", {}).get("Referer"), "odoo-ai-text-rewrite")
        self.assertEqual(kwargs.get("timeout"), 42)

    def test_openai_request_posts_chat_completions_with_the_bearer_token(self):
        # Contract "Provider 2": OpenAI compatible payload, authenticated, system prompt as its own message.
        self._use_openai(api_key="test-api-key", system_prompt=SYSTEM_PROMPT, timeout=42)
        settings = self.service._get_ai_settings()
        with self._mocked_requests() as requests_mock:
            requests_mock.post.return_value.json.return_value = {"choices": [{"message": {"content": "Rewritten by the endpoint."}}]}
            raw = self.service._call_openai_compatible("Rewrite this text please", settings)
            args, kwargs = self._http_call(requests_mock)
        self.assertEqual(raw, "Rewritten by the endpoint.")
        self.assertEqual(self._called_url(args, kwargs), "%s/chat/completions" % GROQ_BASE_URL)
        self.assertEqual(kwargs.get("headers", {}).get("Authorization"), "Bearer test-api-key")
        self.assertEqual(kwargs.get("timeout"), 42)
        payload = kwargs.get("json", {})
        self.assertEqual(payload.get("model"), GROQ_MODEL)
        messages = {message["role"]: message["content"] for message in payload.get("messages", [])}
        self.assertEqual(messages.get("system"), SYSTEM_PROMPT)
        self.assertEqual(messages.get("user"), "Rewrite this text please")

    def test_openai_request_omits_the_authorization_header_without_api_key(self):
        # Contract: an empty key means a local endpoint (Ollama), which rejects a bare "Bearer " header.
        self._use_openai(base_url="http://localhost:11434/v1", api_key=False, model="llama3")
        settings = self.service._get_ai_settings()
        with self._mocked_requests() as requests_mock:
            requests_mock.post.return_value.json.return_value = {"choices": [{"message": {"content": "Rewritten locally."}}]}
            self.service._call_openai_compatible("Rewrite this text please", settings)
            _args, kwargs = self._http_call(requests_mock)
        self.assertNotIn("Authorization", kwargs.get("headers", {}))

    def test_openai_without_base_url_raises_and_issues_no_call(self):
        # Contract: a half configured endpoint must be reported as a settings problem, not as a network error.
        self._use_openai(base_url=False)
        with self._mocked_requests() as requests_mock, self.assertRaises(UserError):
            self.service.rewrite("Sentence to rewrite.")
        requests_mock.post.assert_not_called()
        requests_mock.get.assert_not_called()

    def test_openai_without_model_raises_and_issues_no_call(self):
        # Same for the model name: the endpoint would answer 400 and the user would see a raw provider error.
        self._use_openai(model=False)
        with self._mocked_requests() as requests_mock, self.assertRaises(UserError):
            self.service.rewrite("Sentence to rewrite.")
        requests_mock.post.assert_not_called()
        requests_mock.get.assert_not_called()

    @mute_logger(_MODULE)
    def test_provider_failure_is_reported_as_a_user_error(self):
        # Contract "Regole comuni": a provider outage must reach the dialog as a readable message, never as a traceback.
        self._use_pollinations()
        with self._mocked_requests() as requests_mock:
            requests_mock.get.side_effect = requests.exceptions.Timeout("connection timed out")
            requests_mock.post.side_effect = requests.exceptions.Timeout("connection timed out")
            requests_mock.request.side_effect = requests.exceptions.Timeout("connection timed out")
            with self.assertRaises(UserError) as error:
                self.service.rewrite("Sentence to rewrite.")
        message = str(error.exception)
        self.assertTrue(message.strip())
        self.assertNotIn("Traceback", message)

    # ------------------------------------------------------------------
    # 7. Free provider input limit and quota handling
    # ------------------------------------------------------------------

    def test_pollinations_input_limit_is_the_measured_one(self):
        # Measured on the live service: above a few hundred characters the GET is answered 402.
        self.assertEqual(POLLINATIONS_MAX_INPUT_LENGTH, 500)
        self.assertLess(POLLINATIONS_MAX_INPUT_LENGTH, MAX_INPUT_LENGTH)

    def test_pollinations_refuses_a_prompt_over_its_own_limit(self):
        # Refusing locally turns a raw 402 into an actionable message and saves a pointless round trip.
        self._use_pollinations()
        settings = self.service._get_ai_settings()
        with self._mocked_requests() as requests_mock:
            with self.assertRaises(UserError):
                self.service._call_pollinations("a" * (POLLINATIONS_MAX_INPUT_LENGTH + 1), settings)
            requests_mock.get.assert_not_called()

    def test_pollinations_accepts_a_prompt_at_its_own_limit(self):
        # Boundary: the limit is inclusive, a prompt of exactly that size must still be sent.
        self._use_pollinations()
        settings = self.service._get_ai_settings()
        with self._mocked_requests() as requests_mock:
            requests_mock.get.return_value.text = "Rewritten by the free provider."
            raw = self.service._call_pollinations("a" * POLLINATIONS_MAX_INPUT_LENGTH, settings)
        self.assertEqual(raw, "Rewritten by the free provider.")

    def test_free_provider_limit_counts_the_whole_prompt(self):
        # What is capped is what is actually sent: a short text plus a long shared system prompt overflows too.
        self._use_pollinations(system_prompt="s" * 400)
        text = "t" * 200
        self.assertLess(len(text), POLLINATIONS_MAX_INPUT_LENGTH)
        with self._mocked_requests() as requests_mock, self.assertRaises(UserError):
            self.service.rewrite(text)
        requests_mock.get.assert_not_called()

    def test_long_text_still_works_on_the_paid_provider(self):
        # The free service limit must not leak into the configured endpoint, which has no such cap.
        self._use_openai()
        with self._mocked_requests() as requests_mock:
            requests_mock.post.return_value.json.return_value = {"choices": [{"message": {"content": "Rewritten sentence."}}]}
            result = self.service.rewrite("t" * (POLLINATIONS_MAX_INPUT_LENGTH * 4))
        self.assertEqual(result, "Rewritten sentence.")

    @mute_logger(_MODULE)
    def test_pollinations_quota_errors_get_a_dedicated_message(self):
        # 402/403/429 mean "the shared free service refused you": the user must be told to configure a key,
        # not that the service is temporarily down and worth retrying as is.
        self._use_pollinations()
        settings = self.service._get_ai_settings()
        generic_message = self._provider_error_message("_call_pollinations", settings, 500)
        self.assertTrue(generic_message.strip())
        for status_code in (402, 403, 429):
            with self.subTest(status_code=status_code):
                quota_message = self._provider_error_message("_call_pollinations", settings, status_code)
                self.assertTrue(quota_message.strip())
                self.assertNotIn("Traceback", quota_message)
                self.assertNotEqual(quota_message, generic_message, "HTTP %s is a quota refusal, not a generic outage" % status_code)

    @mute_logger(_MODULE)
    def test_openai_rejected_api_key_gets_a_dedicated_message(self):
        # A 401 is a wrong key in Settings, telling the user the endpoint is unreachable sends them hunting the network.
        self._use_openai(api_key="wrong-api-key")
        settings = self.service._get_ai_settings()
        generic_message = self._provider_error_message("_call_openai_compatible", settings, 500)
        unauthorized_message = self._provider_error_message("_call_openai_compatible", settings, 401)
        self.assertTrue(unauthorized_message.strip())
        self.assertNotIn("Traceback", unauthorized_message)
        self.assertNotEqual(unauthorized_message, generic_message)

    # ------------------------------------------------------------------
    # 8. Remote call surface
    # ------------------------------------------------------------------

    def test_rewrite_is_not_callable_over_rpc(self):
        # The route is not the only door: without @api.private any logged in user could reach the model
        # through call_kw and spend the configured API key, bypassing the controller's own group check.
        with self.assertRaises(AccessError):
            get_public_method(self.service, "rewrite")

    def test_the_rpc_guard_still_lets_genuinely_public_methods_through(self):
        # Control for the test above: get_public_method() must not be refusing everything, otherwise the
        # assertion would pass even with the decorator removed.
        self.assertTrue(get_public_method(self.env["res.partner"], "read"))

    # ------------------------------------------------------------------
    # 9. The system prompt is sent once
    # ------------------------------------------------------------------

    def test_openai_payload_carries_the_system_prompt_only_once(self):
        # The endpoint has its own "system" message, while the composed prompt already starts with the
        # same text for the free provider: sending both pays twice for the same tokens on every call.
        # Only requests is mocked here, so the real prompt composition is what ends up in the payload.
        self._use_openai(system_prompt=SYSTEM_PROMPT)
        with self._mocked_requests() as requests_mock:
            requests_mock.post.return_value.json.return_value = {"choices": [{"message": {"content": "Rewritten sentence."}}]}
            self.service.rewrite("Invoice 12 is late.", "Make it polite.")
            _args, kwargs = self._http_call(requests_mock)
        payload = kwargs.get("json", {})
        self.assertEqual(json.dumps(payload).count(SYSTEM_PROMPT), 1, "The system prompt must travel once, in the system message")
        messages = {message["role"]: message["content"] for message in payload["messages"]}
        self.assertEqual(messages["system"], SYSTEM_PROMPT)
        self.assertNotIn(SYSTEM_PROMPT, messages["user"])
        self.assertIn("Make it polite.", messages["user"])
        self.assertIn("Invoice 12 is late.", messages["user"])

    def test_openai_payload_keeps_the_whole_prompt_when_no_system_prompt_is_set(self):
        # With an empty system prompt there is no prefix to remove: nothing must be cut off the user
        # message by an empty-string match.
        self._use_openai(system_prompt=False)
        with self._mocked_requests() as requests_mock:
            requests_mock.post.return_value.json.return_value = {"choices": [{"message": {"content": "Rewritten sentence."}}]}
            self.service.rewrite("Invoice 12 is late.", "Make it polite.")
            _args, kwargs = self._http_call(requests_mock)
        messages = {message["role"]: message["content"] for message in kwargs["json"]["messages"]}
        self.assertEqual(messages["user"], self.service._build_ai_prompt("Invoice 12 is late.", "Make it polite.", False))

    def test_free_provider_still_carries_the_system_prompt_in_the_url(self):
        # The free endpoint has no system channel: dropping the prefix there too would silently lose the
        # shared instruction that the whole feature is configured around.
        self._use_pollinations(system_prompt=SYSTEM_PROMPT)
        with self._mocked_requests() as requests_mock:
            requests_mock.get.return_value.text = "Rewritten sentence."
            self.service.rewrite("Invoice 12 is late.", "Make it polite.")
            args, kwargs = self._http_call(requests_mock)
        sent_prompt = unquote(self._called_url(args, kwargs))
        self.assertEqual(sent_prompt.count(SYSTEM_PROMPT), 1)
        self.assertIn("Invoice 12 is late.", sent_prompt)

    # ------------------------------------------------------------------
    # 7. What the provider says when it refuses
    # ------------------------------------------------------------------

    def _openai_failure(self, status_code, body, json_body=True):
        """Make the openai endpoint answer with the given status and body, and return the user message."""
        response_mock = MagicMock(name="response")
        response_mock.status_code = status_code
        if json_body:
            response_mock.json.return_value = body
            response_mock.text = json.dumps(body)
        else:
            response_mock.json.side_effect = ValueError("not json")
            response_mock.text = body
        error = requests.exceptions.HTTPError("%s Error" % status_code, response=response_mock)
        with self._mocked_requests() as requests_mock:
            requests_mock.post.return_value.raise_for_status.side_effect = error
            with self.assertRaises(UserError) as raised:
                self.service.rewrite("Rewrite this text please")
        return str(raised.exception)

    @mute_logger(_MODULE)
    def test_a_missing_model_says_so_instead_of_blaming_the_connection(self):
        # A 404 from an OpenAI-compatible endpoint means the model is unknown, not that the service is
        # unreachable: the old wording sent the reader looking for a network problem that does not exist.
        self._use_openai()
        message = self._openai_failure(404, {
            "error": {"message": "The model `some-model` does not exist or you do not have access to it."}
        })
        self.assertIn("does not know the configured model", message)
        self.assertIn("some-model", message)

    @mute_logger(_MODULE)
    def test_a_non_json_body_is_still_reported(self):
        # Not every gateway answers JSON; the raw body is more useful than nothing at all.
        self._use_openai()
        message = self._openai_failure(404, "<html>404 Not Found</html>", json_body=False)
        self.assertIn("404 Not Found", message)

    def test_a_response_detail_without_a_response_is_empty(self):
        self.assertEqual(self.service._response_detail(None), "")

    def test_an_empty_answer_is_refused_instead_of_blanking_the_field(self):
        # Reasoning models can spend their whole budget thinking and answer with an empty content:
        # writing that into the field would destroy the text the user asked to improve.
        self._use_openai()
        with self._mocked_requests() as requests_mock:
            requests_mock.post.return_value.json.return_value = {
                "choices": [{"message": {"content": "", "reasoning": "thinking out loud"}}]
            }
            with self.assertRaises(UserError) as raised:
                self.service.rewrite("Rewrite this text please")
        self.assertIn("empty answer", str(raised.exception))

    # ------------------------------------------------------------------
    # 6. Record context hook
    # ------------------------------------------------------------------

    def test_rewrite_puts_the_record_context_in_the_prompt(self):
        self._use_openai()
        service_cls = type(self.service)
        with patch.object(service_cls, "_get_record_context", autospec=True, return_value="Task T1 fixed the invoice report.") as context_mock, \
                self._mocked_providers() as (_pollinations_mock, openai_mock):
            self.service.rewrite("Fixed report.", False, False, "res.partner", "comment", False, {"ref": "T1"})
        prompt = openai_mock.call_args.args[1]
        self.assertIn("Task T1 fixed the invoice report.", prompt)
        self.assertLess(prompt.index("Task T1 fixed the invoice report."), prompt.index("Fixed report."))
        self.assertIn("Never add an activity", prompt)
        self.assertEqual(context_mock.call_args.args[1:], ("res.partner", "comment", False, {"ref": "T1"}))

    def test_rewrite_skips_the_record_context_on_the_free_provider(self):
        self._use_pollinations()
        service_cls = type(self.service)
        with patch.object(service_cls, "_get_record_context", autospec=True, return_value="Context.") as context_mock, \
                self._mocked_providers() as (pollinations_mock, _openai_mock):
            self.service.rewrite("Fixed report.", False, False, "res.partner", "comment")
        context_mock.assert_not_called()
        self.assertNotIn("Context.", pollinations_mock.call_args.args[1])

    def test_record_context_is_empty_by_default(self):
        self.assertEqual(self.service._get_record_context("res.partner", "comment", False, {}), "")
