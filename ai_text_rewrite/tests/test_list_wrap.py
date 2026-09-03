from odoo.tests import HttpCase, tagged

WRAP_ASSERT_JS = """
(async () => {
    await new Promise((r) => setTimeout(r, 1500));
    const cells = [...document.querySelectorAll(".o_list_table tbody tr.o_data_row td.o_data_cell")];
    if (cells.length !== 2) {
        console.error("expected the two probe columns, got " + cells.length);
        return;
    }
    for (const td of cells) {
        // the value span is what actually wraps: the field div can carry pre-wrap while the span
        // still inherits the nowrap of a text-truncate cell, which is how this broke once
        const span = td.querySelector("span");
        if (!span) {
            console.error("no value span rendered in the ai_text cell");
            return;
        }
        if (getComputedStyle(span).whiteSpace !== "pre-wrap") {
            console.error("the value span does not wrap: " + getComputedStyle(span).whiteSpace);
            return;
        }
        // and the proof it wraps for real: the value is taller than the single line it would be
        if (span.getBoundingClientRect().height < 30) {
            console.error("the long value still fits one line: " + span.getBoundingClientRect().height);
            return;
        }
        if (span.getBoundingClientRect().width > td.getBoundingClientRect().width) {
            console.error("the value overflows its cell instead of wrapping");
            return;
        }
    }
    console.log("test successful");
})();
"""


@tagged("post_install", "-at_install")
class TestAiRewriteListWrap(HttpCase):
    def test_long_values_wrap_in_list_cells(self):
        long_text = "a very long snippet of text that should wrap somewhere " * 4
        self.env["ir.attachment"].create({"name": long_text, "description": long_text})
        view_id = self.env["ir.ui.view"].create({
            "name": "ai_text_rewrite list wrap",
            "model": "ir.attachment",
            "type": "tree",
            "arch": """
                <tree editable="bottom" create="0" delete="0">
                    <field name="name" widget="ai_text"/>
                    <field name="description" widget="ai_text"/>
                </tree>"""
        })
        action_id = self.env["ir.actions.act_window"].create({
            "name": "ai_text_rewrite list wrap",
            "res_model": "ir.attachment",
            "view_mode": "tree",
            "views": [(view_id.id, "tree")],
            "domain": "[('name', 'like', 'a very long snippet')]"
        })
        self.env.flush_all()
        self.browser_js(
            "/web#action=%s" % action_id.id,
            WRAP_ASSERT_JS,
            "!!document.querySelector('.o_list_table tbody tr.o_data_row')",
            login="admin"
        )
