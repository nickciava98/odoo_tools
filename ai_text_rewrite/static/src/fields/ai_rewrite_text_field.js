/** @odoo-module **/

import { registry } from "@web/core/registry";
import {
    ListTextField,
    TextField,
    listTextField,
    textField,
} from "@web/views/fields/text/text_field";
import { AiRewriteButton } from "./ai_rewrite_button";

export class AiRewriteTextField extends TextField {
    static template = "ai_text_rewrite.AiRewriteTextField";
    static components = {
        ...TextField.components,
        AiRewriteButton,
    };
}

export class AiRewriteListTextField extends ListTextField {
    static template = "ai_text_rewrite.AiRewriteListTextField";
    static components = AiRewriteTextField.components;
}

// why: TextField renders a textarea, which wraps long values a plain input would truncate,
// so the widget is worth offering on char fields too
// why: list cells are nowrap unless the field is of type text; o_field_text carries the
// pre-wrap rule so a long char value wraps instead of being truncated, as core does
// for section_and_note_text
export const aiRewriteTextField = {
    ...textField,
    component: AiRewriteTextField,
    supportedTypes: ["char", "html", "text"],
    additionalClasses: ["o_field_text"],
};

export const aiRewriteListTextField = {
    ...listTextField,
    component: AiRewriteListTextField,
    supportedTypes: aiRewriteTextField.supportedTypes,
    additionalClasses: aiRewriteTextField.additionalClasses,
};

registry.category("fields").add("ai_text", aiRewriteTextField);
registry.category("fields").add("list.ai_text", aiRewriteListTextField);
