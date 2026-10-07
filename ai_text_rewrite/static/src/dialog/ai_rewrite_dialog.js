/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { Dialog } from "@web/core/dialog/dialog";
// why: v18 dropped the "rpc" service in favour of a direct import
import { rpc } from "@web/core/network/rpc";

import { Component, markup, useState } from "@odoo/owl";

export class AiRewriteDialog extends Component {
    setup() {
        this.state = useState({
            instruction: _t("Rewrite this text so that it is clearer, more professional and technically more thorough."),
            preview: "",
            error: "",
            isLoading: false,
        });
    }

    get hasResult() {
        return Boolean(this.state.preview) && !this.state.error;
    }

    get originalValue() {
        return markup(this.props.text);
    }

    get previewValue() {
        return this.props.isHtml ? markup(this.state.preview) : this.state.preview;
    }

    async generate() {
        this.state.isLoading = true;
        this.state.error = "";
        this.state.preview = "";
        try {
            const result = await rpc("/ai_text_rewrite/rewrite", {
                text: this.props.text,
                instruction: this.state.instruction,
                is_html: this.props.isHtml,
                model: this.props.resModel,
                field: this.props.fieldName,
                res_id: this.props.resId || null,
                record_values: this.props.recordValues,
            });
            if (result.error) {
                this.state.error = result.error;
            } else {
                this.state.preview = result.text;
            }
        } catch {
            this.state.error = _t("The AI rewrite request failed. Please try again.");
        } finally {
            this.state.isLoading = false;
        }
    }

    replace() {
        this.props.onApply(this.state.preview);
        this.props.close();
    }
}
AiRewriteDialog.template = "ai_text_rewrite.AiRewriteDialog";
AiRewriteDialog.components = { Dialog };
AiRewriteDialog.props = {
    text: { type: String, optional: true },
    isHtml: { type: Boolean, optional: true },
    onApply: Function,
    close: Function,
    resModel: { type: String, optional: true },
    fieldName: { type: String, optional: true },
    resId: { type: [Number, { value: false }], optional: true },
    recordValues: { type: Object, optional: true },
};
AiRewriteDialog.defaultProps = {
    text: "",
    isHtml: false,
    recordValues: {},
};
