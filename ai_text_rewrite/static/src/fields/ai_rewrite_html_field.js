/** @odoo-module **/

import { registry } from "@web/core/registry";
// why: v18 moved the html widget from web_editor to html_editor and registers the
// latter with force:true, so extending web_editor here would give the AI button a
// different editor from the one every other html field shows.
import { HtmlField, htmlField } from "@html_editor/fields/html_field";
import { AiRewriteButton } from "./ai_rewrite_button";

export class AiRewriteHtmlField extends HtmlField {
    static template = "ai_text_rewrite.AiRewriteHtmlField";
    static components = {
        ...HtmlField.components,
        AiRewriteButton,
    };
}

export const aiRewriteHtmlField = {
    ...htmlField,
    component: AiRewriteHtmlField,
};

registry.category("fields").add("ai_html", aiRewriteHtmlField);
