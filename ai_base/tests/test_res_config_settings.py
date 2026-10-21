# Copyright 2026 Niccolò Ciavarella
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

PROVIDER_FIELDS = {
    "ai_provider_base_url": ("ai_base.base_url", "char"),
    "ai_provider_api_key": ("ai_base.api_key", "char"),
    "ai_provider_model": ("ai_base.model", "char"),
    "ai_provider_timeout": ("ai_base.timeout", "integer")
}


@tagged("post_install", "-at_install")
class TestAiBaseConfigSettings(TransactionCase):
    """The provider block of General Settings is the only place where the shared AI endpoint is configured."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.settings_model = cls.env["res.config.settings"]
        cls.provider = cls.env["ai.provider"]
        cls.config_param = cls.env["ir.config_parameter"].sudo()

    def test_provider_fields_are_bound_to_the_ai_base_parameters(self):
        # Each field must write its own ai_base.* key, the one ai.provider reads.
        for field_name, (parameter, field_type) in PROVIDER_FIELDS.items():
            with self.subTest(field=field_name):
                field = self.settings_model._fields.get(field_name)
                self.assertTrue(field, "Missing settings field %s" % field_name)
                self.assertEqual(field.type, field_type)
                self.assertEqual(field.config_parameter, parameter)

    def test_general_settings_can_be_created_and_saved(self):
        # default_get() and execute() re-classify every field: both must survive the new block.
        settings_id = self.settings_model.create({})
        self.assertTrue(settings_id)
        settings_id.execute()

    def test_provider_settings_round_trip(self):
        # What is saved on the page is what the provider uses, and what the page shows again at reload.
        self.settings_model.create({
            "ai_provider_base_url": "https://llm.example.invalid/v1",
            "ai_provider_api_key": "sk-round-trip",
            "ai_provider_model": "round-trip-model",
            "ai_provider_timeout": 25
        }).execute()
        self.assertEqual(self.provider._get_provider_settings(), {
            "base_url": "https://llm.example.invalid/v1",
            "api_key": "sk-round-trip",
            "model": "round-trip-model",
            "timeout": 25
        })
        settings_id = self.settings_model.create({})
        self.assertRecordValues(settings_id, [{
            "ai_provider_base_url": "https://llm.example.invalid/v1",
            "ai_provider_api_key": "sk-round-trip",
            "ai_provider_model": "round-trip-model",
            "ai_provider_timeout": 25
        }])

    def test_clearing_the_api_key_removes_it(self):
        # A local endpoint has no key: emptying the field must really drop it, not keep the old secret around.
        self.config_param.set_param("ai_base.api_key", "sk-old")
        self.settings_model.create({"ai_provider_api_key": False}).execute()
        self.assertFalse(self.provider._get_provider_settings()["api_key"])

    def test_api_key_is_rendered_as_a_password_in_the_settings_view(self):
        # The key is a secret: shown in clear it ends up in every screenshot of the Settings page.
        arch = self.settings_model.get_view(view_type="form")["arch"]
        self.assertIn('name="ai_provider_api_key"', arch)
        self.assertRegex(arch, r'<field[^>]*name="ai_provider_api_key"[^>]*password="True"|<field[^>]*password="True"[^>]*name="ai_provider_api_key"')
