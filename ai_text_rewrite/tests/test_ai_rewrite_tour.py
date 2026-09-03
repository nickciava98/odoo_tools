# Copyright 2026 Niccolò Ciavarella
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from unittest.mock import patch

from odoo.tests import HttpCase, tagged

REWRITTEN_TEXT = "This is the rewritten text produced by the mocked AI service."


@tagged("post_install", "-at_install")
class TestAiRewriteReplaceTour(HttpCase):
    """Covers the one behaviour no unit/controller test can: clicking Replace in the
    dialog must actually write the field, and the new value must survive a save."""

    def test_replace_writes_and_persists_the_field(self):
        # Scratch form, built at runtime on web_editor's own test model (already
        # installed with an open ACL as a dependency of this module): no demo view
        # ships in data/, nothing is left behind once the test transaction rolls back.
        record_id = self.env["web_editor.converter.test"].create({
            "text": "Original draft text, before any AI rewrite."
        }).id
        view_id = self.env["ir.ui.view"].create({
            "name": "ai_text_rewrite.tour_test_form",
            "model": "web_editor.converter.test",
            "type": "form",
            "arch": """
                <form>
                    <sheet>
                        <field name="text" widget="ai_text"/>
                    </sheet>
                </form>
            """
        }).id
        action_id = self.env["ir.actions.act_window"].create({
            "name": "AI Rewrite Tour Test",
            "res_model": "web_editor.converter.test",
            "res_id": record_id,
            "view_mode": "form",
            "view_id": view_id,
            "target": "current"
        }).id

        # The tour exercises the widget, not the provider selection: pin the free provider so the helper
        # mocked below is the one the service really calls. The parameter is noupdate="1" and the
        # 16.0.1.0.1 migration moves it to "openai", so its value is not the same on every database:
        # without this line the service would call the configured endpoint for real.
        self.env["ir.config_parameter"].sudo().set_param("ai_text_rewrite.provider", "pollinations")
        provider_mock = patch.object(
            type(self.env["ai.rewrite.service"]), "_call_pollinations", autospec=True, return_value=REWRITTEN_TEXT
        )
        # The webclient router only pre-selects a record on a direct URL boot when "id" (and
        # "view_type") are in the hash: the action's own res_id is not read at this stage, so
        # relying on action_id alone lands on the user's home action instead (looks like a
        # broken widget: the AI button trigger never appears, on the wrong screen entirely).
        url = f"/web#action={action_id}&view_type=form&id={record_id}"
        with provider_mock as mocked_provider:
            self.start_tour(url, "ai_text_rewrite_replace", login="admin")
            mocked_provider.assert_called_once()

        record = self.env["web_editor.converter.test"].browse(record_id)
        record.invalidate_recordset(["text"])
        self.assertEqual(record.text, REWRITTEN_TEXT, "Replace must write the rewritten text on the record")


@tagged("post_install", "-at_install")
class TestAiRewriteSettingsProviderSwitch(HttpCase):
    """Switching provider in Settings re-renders the form: a regression here breaks the page,
    which no ORM test can see because the visibility rules live in the client."""

    # Settings has no readonly state to fall back to (the form is always editable), so without this
    # flag browser_js reports "open form in edition mode" at the end of a tour that actually passed.
    allow_end_on_form = True

    def test_provider_switch_does_not_crash(self):
        # The reported "SyntaxError: Unexpected end of JSON input" on the provider switch turned out to
        # be an artefact of the CDP simulation, not a defect: this tour keeps the real path under watch.
        url = "/web#action=ai_text_rewrite.action_ai_rewrite_settings"
        self.start_tour(url, "ai_text_rewrite_settings_provider_switch", login="admin")


@tagged("post_install", "-at_install")
class TestAiRewriteReplaceHtmlTour(HttpCase):
    """Same Replace flow on the "ai_html" widget: here the value has to travel through the wysiwyg
    editor and its commit-on-save, a path the plain text widget cannot exercise."""

    def test_replace_writes_and_persists_the_html_field(self):
        # Scratch form on web_editor's own test model, same approach as the text tour: nothing is
        # shipped in data/ and everything rolls back with the test transaction.
        record_id = self.env["web_editor.converter.test"].create({
            "html": "<p>Original draft note, before any AI rewrite.</p>"
        }).id
        view_id = self.env["ir.ui.view"].create({
            "name": "ai_text_rewrite.tour_test_html_form",
            "model": "web_editor.converter.test",
            "type": "form",
            "arch": """
                <form>
                    <sheet>
                        <field name="html" widget="ai_html"/>
                    </sheet>
                </form>
            """
        }).id
        action_id = self.env["ir.actions.act_window"].create({
            "name": "AI Rewrite HTML Tour Test",
            "res_model": "web_editor.converter.test",
            "res_id": record_id,
            "view_mode": "form",
            "view_id": view_id,
            "target": "current"
        }).id

        # The default provider is "openai" now: without pinning the free one, the helper mocked below
        # would not be the one the service calls and the tour would hit the configured endpoint for real.
        self.env["ir.config_parameter"].sudo().set_param("ai_text_rewrite.provider", "pollinations")
        provider_mock = patch.object(
            type(self.env["ai.rewrite.service"]), "_call_pollinations", autospec=True, return_value=REWRITTEN_TEXT
        )
        # "id" and "view_type" in the hash, same as the text tour: the action's own res_id is not read
        # when the webclient boots on a URL, so without them the tour starts on the home action.
        url = f"/web#action={action_id}&view_type=form&id={record_id}"
        with provider_mock as mocked_provider:
            self.start_tour(url, "ai_text_rewrite_replace_html", login="admin")
            mocked_provider.assert_called_once()

        record = self.env["web_editor.converter.test"].browse(record_id)
        record.invalidate_recordset(["html"])
        self.assertIn(REWRITTEN_TEXT, record.html, "Replace must write the rewritten text on the html field")
