# Copyright 2026 Niccolò Ciavarella
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from contextlib import contextmanager
from unittest.mock import patch

from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.ai_text_rewrite.models.ai_rewrite_service import STYLE_EXAMPLE_LIMIT

OWN_NOTE = "Configurazione del flusso di approvazione degli acquisti sopra la soglia di spesa."
OTHER_NOTE = "Verifica della sincronizzazione dei listini con il magazzino centrale."
CURRENT_NOTE = "sistemato flusso approvazioni"


@tagged("post_install", "-at_install")
class TestAiRewriteStyle(TransactionCase):
    """The rewrite imitates what is already written in the same field of the same model."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        config_param = cls.env["ir.config_parameter"].sudo()
        config_param.set_param("ai_text_rewrite.provider", "openai")
        config_param.set_param("ai_text_rewrite.base_url", "https://api.groq.com/openai/v1")
        config_param.set_param("ai_text_rewrite.model", "llama-3.3-70b-versatile")
        cls.user_id = cls.env["res.users"].create({
            "name": "AI Style Tester",
            "login": "ai_style_tester",
            "groups_id": [Command.set([cls.env.ref("base.group_user").id, cls.env.ref("base.group_partner_manager").id])]
        })
        cls.other_partner_id = cls.env["res.partner"].create({"name": "Other Writer", "comment": "<p>%s</p>" % OTHER_NOTE})
        cls.own_partner_id = cls.env["res.partner"].with_user(cls.user_id).create({"name": "Own Writer", "comment": "<p>%s</p>" % OWN_NOTE})
        cls.current_partner_id = cls.env["res.partner"].create({"name": "Current", "comment": "<p>%s</p>" % CURRENT_NOTE})
        cls.service = cls.env["ai.rewrite.service"].with_user(cls.user_id)

    @contextmanager
    def _mocked_openai(self):
        service_cls = type(self.service)
        with patch.object(service_cls, "_call_openai_compatible", autospec=True, return_value="Rewritten.") as openai_mock, patch.object(
            service_cls, "_call_pollinations", autospec=True, return_value="Rewritten."
        ) as pollinations_mock:
            yield openai_mock, pollinations_mock

    def _sent_prompt(self, **context):
        with self._mocked_openai() as (openai_mock, _pollinations_mock):
            self.service.rewrite(CURRENT_NOTE, False, False, **context)
        return openai_mock.call_args.args[1]

    def test_prompt_carries_the_other_records_of_the_same_field(self):
        prompt = self._sent_prompt(model="res.partner", field="comment", res_id=self.current_partner_id.id)
        self.assertIn(OWN_NOTE, prompt)
        self.assertIn(OTHER_NOTE, prompt)
        self.assertIn("<reference>", prompt)

    def test_own_records_come_before_the_others(self):
        prompt = self._sent_prompt(model="res.partner", field="comment", res_id=self.current_partner_id.id)
        self.assertLess(prompt.index(OWN_NOTE), prompt.index(OTHER_NOTE))

    def test_the_record_being_edited_is_never_its_own_reference(self):
        prompt = self._sent_prompt(model="res.partner", field="comment", res_id=self.current_partner_id.id)
        self.assertEqual(prompt.count(CURRENT_NOTE), 1)

    def test_the_text_to_rewrite_closes_the_prompt(self):
        prompt = self._sent_prompt(model="res.partner", field="comment", res_id=self.current_partner_id.id)
        self.assertTrue(prompt.endswith("Text to rewrite:\n\n%s" % CURRENT_NOTE))

    def test_examples_are_plain_text_for_html_fields(self):
        examples = self.service._get_style_examples("res.partner", "comment", self.current_partner_id.id, CURRENT_NOTE, 6000)
        self.assertIn(OWN_NOTE, examples)
        self.assertFalse([example for example in examples if "<p>" in example])

    def test_examples_respect_the_count_and_the_budget(self):
        self.env["res.partner"].create([
            {"name": "Bulk %s" % index, "comment": "<p>Nota tecnica numero %s sul modulo vendite.</p>" % index}
            for index in range(STYLE_EXAMPLE_LIMIT * 2)
        ])
        examples = self.service._get_style_examples("res.partner", "comment", False, CURRENT_NOTE, 6000)
        self.assertEqual(len(examples), STYLE_EXAMPLE_LIMIT)
        examples = self.service._get_style_examples("res.partner", "comment", False, CURRENT_NOTE, 100)
        self.assertLessEqual(sum(len(example) for example in examples), 100)

    def test_an_unknown_model_or_field_only_drops_the_examples(self):
        for model, field in (("no.such.model", "comment"), ("res.partner", "no_such_field"), ("res.partner", "id")):
            prompt = self._sent_prompt(model=model, field=field)
            self.assertNotIn("<reference>", prompt)

    def test_a_non_stored_field_gives_no_examples(self):
        self.assertFalse(self.service._get_style_examples("res.partner", "display_name", False, CURRENT_NOTE, 6000))

    def test_a_model_the_user_cannot_read_gives_no_examples(self):
        self.assertFalse(self.service._get_style_examples("ir.config_parameter", "value", False, CURRENT_NOTE, 6000))

    def test_the_free_provider_gets_no_examples(self):
        self.env["ir.config_parameter"].sudo().set_param("ai_text_rewrite.provider", "pollinations")
        self.env["ir.config_parameter"].sudo().set_param("ai_text_rewrite.system_prompt", "Rewrite it.")
        with self._mocked_openai() as (_openai_mock, pollinations_mock):
            self.service.rewrite(CURRENT_NOTE, False, False, "res.partner", "comment", self.current_partner_id.id)
        self.assertNotIn("<reference>", pollinations_mock.call_args.args[1])

    def test_style_learning_is_on_by_default(self):
        self.env["ir.config_parameter"].sudo().set_param("ai_text_rewrite.style_enabled", False)
        self.assertTrue(self.service._get_ai_settings()["style_enabled"])

    def test_disabled_style_learning_sends_no_examples(self):
        self.env["ir.config_parameter"].sudo().set_param("ai_text_rewrite.style_enabled", "False")
        prompt = self._sent_prompt(model="res.partner", field="comment", res_id=self.current_partner_id.id)
        self.assertNotIn("<reference>", prompt)
        self.assertNotIn(OWN_NOTE, prompt)

    def test_unchecking_the_setting_survives_a_reload(self):
        settings_model = self.env["res.config.settings"]
        settings_model.create({"is_ai_rewrite_style_enabled": False}).execute()
        self.assertEqual(self.env["ir.config_parameter"].sudo().get_param("ai_text_rewrite.style_enabled"), "False")
        self.assertFalse(settings_model.create({}).is_ai_rewrite_style_enabled)
        settings_model.create({"is_ai_rewrite_style_enabled": True}).execute()
        self.assertTrue(settings_model.create({}).is_ai_rewrite_style_enabled)

    def test_without_context_the_prompt_is_unchanged(self):
        prompt = self._sent_prompt()
        self.assertNotIn("<reference>", prompt)
        self.assertNotIn("Text to rewrite:", prompt)
        self.assertIn("a short label of a few words stays a short label", prompt)

    def test_with_references_the_label_guard_gives_way_to_them(self):
        prompt = self._sent_prompt(model="res.partner", field="comment", res_id=self.current_partner_id.id)
        self.assertNotIn("a short label of a few words stays a short label", prompt)
