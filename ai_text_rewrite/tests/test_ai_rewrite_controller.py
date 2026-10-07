# Copyright 2026 Niccolò Ciavarella
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import json
from contextlib import contextmanager
from unittest.mock import patch

from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import HttpCase

ROUTE = "/ai_text_rewrite/rewrite"


@tagged("post_install", "-at_install")
class TestAiRewriteController(HttpCase):
    """Contract of the json route the dialog calls. No test may reach the network."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user_id = cls.env["res.users"].create({
            "name": "AI Rewrite Tester",
            "login": "ai_rewrite_tester",
            "password": "ai_rewrite_tester_pwd",
            "groups_id": [Command.link(cls.env.ref("base.group_user").id)]
        })
        cls.portal_user_id = cls.env["res.users"].create({
            "name": "AI Rewrite Portal Tester",
            "login": "ai_rewrite_portal_tester",
            "password": "ai_rewrite_portal_tester_pwd",
            "groups_id": [Command.set([cls.env.ref("base.group_portal").id])]
        })
        # Pin the provider instead of inheriting whatever the database happens to hold: the parameter
        # is noupdate="1" and was moved by the 16.0.1.0.1 migration, so its value differs per database.
        cls.env["ir.config_parameter"].sudo().set_param("ai_text_rewrite.provider", "openai")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _call_route(self, **params):
        """Call the json route the way the OWL dialog does and return (http response, jsonrpc payload)."""
        response = self.url_open(
            ROUTE,
            data=json.dumps({"jsonrpc": "2.0", "method": "call", "params": params}),
            headers={"Content-Type": "application/json"}
        )
        return response, response.json()

    @contextmanager
    def _mocked_providers(self, answer):
        """Patch both provider helpers: whichever one the configuration selects, the route can never
        issue a real HTTP call."""
        service_cls = type(self.env["ai.rewrite.service"])
        with patch.object(service_cls, "_call_pollinations", autospec=True, return_value=answer) as pollinations_mock, patch.object(
            service_cls, "_call_openai_compatible", autospec=True, return_value=answer
        ) as openai_mock:
            yield pollinations_mock, openai_mock

    def _assert_no_provider_call(self, pollinations_mock, openai_mock):
        self.assertEqual(pollinations_mock.call_count + openai_mock.call_count, 0, "No provider must have been called")
        return True

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_route_rejects_anonymous_callers(self):
        # Contract: auth="user" — the endpoint spends provider quota, it is not public.
        with self._mocked_providers("Rewritten sentence.") as (pollinations_mock, openai_mock):
            _response, payload = self._call_route(text="Sentence to rewrite.")
        self.assertNotIn("result", payload)
        self.assertIn("error", payload)
        self._assert_no_provider_call(pollinations_mock, openai_mock)

    def test_route_returns_the_rewritten_text(self):
        # Golden path: the dialog reads response.text to fill its preview area.
        self.authenticate("ai_rewrite_tester", "ai_rewrite_tester_pwd")
        with self._mocked_providers("```\nRewritten sentence.\n```") as (_pollinations_mock, openai_mock):
            response, payload = self._call_route(text="Sentence to rewrite.", instruction="Make it polite.")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload.get("result"), {"text": "Rewritten sentence."})
        openai_mock.assert_called_once()

    def test_route_reports_user_errors_without_a_server_error(self):
        # Contract: a UserError becomes {"error": ...}, so the dialog can show it instead of crashing on a 500.
        self.authenticate("ai_rewrite_tester", "ai_rewrite_tester_pwd")
        with self._mocked_providers("Rewritten sentence.") as (pollinations_mock, openai_mock):
            response, payload = self._call_route(text="   ")
        self.assertEqual(response.status_code, 200)
        result = payload.get("result")
        self.assertIsInstance(result, dict, "A UserError must be answered as a normal json result, got %s" % payload)
        self.assertNotIn("text", result)
        self.assertTrue(result.get("error"))
        self.assertIsInstance(result["error"], str)
        self._assert_no_provider_call(pollinations_mock, openai_mock)

    def test_route_forwards_the_is_html_flag_to_the_service(self):
        # Wiring: only a request flagged as html gets sanitised, so an unforwarded flag would inject the script.
        self.authenticate("ai_rewrite_tester", "ai_rewrite_tester_pwd")
        with self._mocked_providers("<p>Legit paragraph.</p><script>alert('xss')</script>"):
            _response, payload = self._call_route(text="<p>Something.</p>", is_html=True)
        rewritten = payload.get("result", {}).get("text", "")
        self.assertIn("Legit paragraph.", rewritten)
        self.assertNotIn("<script", rewritten)
        self.assertNotIn("alert(", rewritten)

    def test_route_rejects_portal_users(self):
        # auth="user" also authenticates portal/share users (ir_http only refuses uid None and the public
        # user): this LLM proxy spends the company API key on free-form input, internal users only.
        self.assertTrue(self.user_id.has_group("base.group_user"), "The fixture user must be an internal user")
        self.assertFalse(self.portal_user_id.has_group("base.group_user"))
        self.authenticate("ai_rewrite_portal_tester", "ai_rewrite_portal_tester_pwd")
        with self._mocked_providers("Rewritten sentence.") as (pollinations_mock, openai_mock):
            response, payload = self._call_route(text="Sentence to rewrite.")
        self.assertEqual(response.status_code, 200)
        result = payload.get("result")
        self.assertIsInstance(result, dict, "The refusal must be a normal json result, got %s" % payload)
        self.assertNotIn("text", result)
        self.assertTrue(result.get("error"))
        self._assert_no_provider_call(pollinations_mock, openai_mock)

    def test_route_forwards_the_style_context_to_the_service(self):
        # Wiring: the dialog sends model, field and record so the service can pick the style references.
        self.authenticate("ai_rewrite_tester", "ai_rewrite_tester_pwd")
        service_cls = type(self.env["ai.rewrite.service"])
        with patch.object(service_cls, "rewrite", autospec=True, return_value="Rewritten.") as rewrite_mock:
            self._call_route(text="Sentence.", model="res.partner", field="comment", res_id=7)
        self.assertEqual(rewrite_mock.call_args.args[1:], ("Sentence.", None, False, "res.partner", "comment", 7))

    def test_route_drops_a_malformed_style_context(self):
        self.authenticate("ai_rewrite_tester", "ai_rewrite_tester_pwd")
        service_cls = type(self.env["ai.rewrite.service"])
        with patch.object(service_cls, "rewrite", autospec=True, return_value="Rewritten.") as rewrite_mock:
            _response, payload = self._call_route(text="Sentence.", model=["res.partner"], field="comment", res_id="7")
        self.assertEqual(payload.get("result"), {"text": "Rewritten."})
        self.assertEqual(rewrite_mock.call_args.args[1:], ("Sentence.", None, False, None, None, None))
