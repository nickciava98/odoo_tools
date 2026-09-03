/** @odoo-module **/

import { registry } from "@web/core/registry";
import { HtmlField } from "@web_editor/js/backend/html_field";
import { AiRewriteButton } from "./ai_rewrite_button";

export class AiRewriteHtmlField extends HtmlField {}
AiRewriteHtmlField.template = "ai_text_rewrite.AiRewriteHtmlField";
AiRewriteHtmlField.components = {
    ...HtmlField.components,
    AiRewriteButton,
};

registry.category("fields").add("ai_html", AiRewriteHtmlField);
