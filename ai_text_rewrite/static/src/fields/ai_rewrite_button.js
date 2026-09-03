/** @odoo-module **/

import { useService } from "@web/core/utils/hooks";
import { AiRewriteDialog } from "../dialog/ai_rewrite_dialog";

import { Component } from "@odoo/owl";

export class AiRewriteButton extends Component {
    setup() {
        this.dialog = useService("dialog");
    }

    openDialog() {
        this.dialog.add(AiRewriteDialog, {
            text: this.props.value,
            isHtml: this.props.isHtml,
            onApply: this.props.onApply,
        });
    }
}
AiRewriteButton.template = "ai_text_rewrite.AiRewriteButton";
AiRewriteButton.props = {
    value: { type: String, optional: true },
    isHtml: { type: Boolean, optional: true },
    onApply: Function,
};
AiRewriteButton.defaultProps = {
    value: "",
    isHtml: false,
};
