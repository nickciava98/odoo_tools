/** @odoo-module **/

import { registry } from "@web/core/registry";
import { ListTextField, TextField } from "@web/views/fields/text/text_field";
import { AiRewriteButton } from "./ai_rewrite_button";

export class AiRewriteTextField extends TextField {}
AiRewriteTextField.template = "ai_text_rewrite.AiRewriteTextField";
AiRewriteTextField.components = {
    ...TextField.components,
    AiRewriteButton
};
// why: TextField renders a textarea, which wraps long values a plain input would truncate,
// so the widget is worth offering on char fields too
AiRewriteTextField.supportedTypes = ["char", "html", "text"];
// why: list cells are nowrap unless the field is of type text; this class carries the
// pre-wrap rule so a long char value wraps instead of being truncated, as core does
// for section_and_note_text
AiRewriteTextField.additionalClasses = ["o_field_text"];

export class AiRewriteListTextField extends ListTextField {}
AiRewriteListTextField.template = "ai_text_rewrite.AiRewriteListTextField";
AiRewriteListTextField.components = AiRewriteTextField.components;
AiRewriteListTextField.supportedTypes = AiRewriteTextField.supportedTypes;
AiRewriteListTextField.additionalClasses = AiRewriteTextField.additionalClasses;

registry.category("fields").add("ai_text", AiRewriteTextField);
registry.category("fields").add("list.ai_text", AiRewriteListTextField);
