# Copyright 2026 Niccolò Ciavarella
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.tests import tagged
from odoo.tests.common import HttpCase, TransactionCase

SYSTEM_PROMPT = "SENTINEL SYSTEM PROMPT: keep every amount unchanged."
SYSTEM_PROMPT_PARAMETER = "ai_text_rewrite.system_prompt"


@tagged("post_install", "-at_install")
class TestAiRewriteConfigSettings(TransactionCase):
    """The module adds fields to the General Settings page: opening and saving it must keep working."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.settings_model = cls.env["res.config.settings"]
        cls.service = cls.env["ai.rewrite.service"]
        cls.config_param = cls.env["ir.config_parameter"].sudo()

    # ------------------------------------------------------------------
    # 1. The General Settings page must not crash
    # ------------------------------------------------------------------

    def test_system_prompt_field_is_not_declared_as_a_config_parameter(self):
        # v16 res_config._get_classified_fields() only accepts boolean/integer/float/char/selection/many2one/datetime
        # for config_parameter: a Text field with that attribute makes the whole Settings page raise.
        field = self.settings_model._fields["ai_rewrite_system_prompt"]
        self.assertEqual(field.type, "text")
        self.assertFalse(
            getattr(field, "config_parameter", False),
            "A Text field cannot carry config_parameter in v16: read and write the parameter in get_values/set_values"
        )

    def test_general_settings_defaults_can_be_computed(self):
        # default_get() over every field is what the Settings page calls first: this is the exact call
        # that used to raise, taking down General Settings for the whole database, not only for this module.
        defaults = self.settings_model.default_get(list(self.settings_model._fields))
        self.assertIn("ai_rewrite_system_prompt", defaults)

    def test_general_settings_can_be_created_and_saved(self):
        # create({}) goes through default_get() and execute() re-classifies every field before set_values():
        # both paths must survive, otherwise saving any unrelated setting fails.
        settings_id = self.settings_model.create({})
        self.assertTrue(settings_id, "The Settings page could not even build its transient record")
        settings_id.execute()

    # ------------------------------------------------------------------
    # 2. The system prompt travels between the page and the service
    # ------------------------------------------------------------------

    def test_system_prompt_round_trips_through_the_settings_page(self):
        # The prompt is stored by hand now: what is saved must come back on the same key, or the page
        # would silently forget the user's prompt at every reload.
        settings_id = self.settings_model.create({"ai_rewrite_system_prompt": SYSTEM_PROMPT})
        settings_id.execute()
        self.assertEqual(self.config_param.get_param(SYSTEM_PROMPT_PARAMETER), SYSTEM_PROMPT)
        self.assertEqual(self.settings_model.create({}).ai_rewrite_system_prompt, SYSTEM_PROMPT)

    def test_service_uses_the_prompt_saved_from_the_settings_page(self):
        # End of the chain: the value written by the real producer (the Settings page) is the one the
        # service reads and puts in the prompt. Writing the parameter by hand here would prove nothing.
        settings_id = self.settings_model.create({"ai_rewrite_system_prompt": SYSTEM_PROMPT})
        settings_id.execute()
        self.assertEqual(self.service._get_ai_settings()["system_prompt"], SYSTEM_PROMPT)
        self.assertIn(SYSTEM_PROMPT, self.service._build_ai_prompt("Invoice 12 is late.", False, False))

    def test_clearing_the_system_prompt_keeps_the_service_working(self):
        # Emptying the field is a legitimate move (the user wants no shared instruction): it must neither
        # crash on save nor leave the prompt builder without a text to rewrite.
        settings_id = self.settings_model.create({"ai_rewrite_system_prompt": False})
        settings_id.execute()
        self.assertFalse(self.service._get_ai_settings()["system_prompt"])
        self.assertIn("Invoice 12 is late.", self.service._build_ai_prompt("Invoice 12 is late.", False, False))


ICON_ASSERT_JS = """
(async () => {
    await new Promise((r) => setTimeout(r, 1500));
    const tab = document.querySelector('.settings_tab .tab[data-key="ai_text_rewrite"] .icon');
    if (!tab) {
        console.error("no settings tab rendered for ai_text_rewrite");
        return;
    }
    const url = getComputedStyle(tab).backgroundImage.match(/url\("?([^")]+)"?\)/);
    if (!url) {
        console.error("the settings tab carries no background image");
        return;
    }
    const response = await fetch(url[1]);
    if (!response.ok) {
        console.error("the icon is not served: " + response.status + " on " + url[1]);
        return;
    }
    if (!(response.headers.get("content-type") || "").includes("image")) {
        console.error("the icon url does not serve an image: " + url[1]);
        return;
    }
    console.log("test successful");
})();
"""


@tagged("post_install", "-at_install")
class TestAiRewriteSettingsIcon(HttpCase):
    def test_the_settings_entry_shows_its_icon(self):
        # why: the settings sidebar builds the url from data-key, so a missing
        # static/description/icon.png leaves the entry with a blank spot and no error
        action_id = self.env.ref("base_setup.action_general_configuration")
        self.browser_js(
            "/web#action=%s" % action_id.id,
            ICON_ASSERT_JS,
            "!!document.querySelector('.settings')",
            login="admin"
        )
