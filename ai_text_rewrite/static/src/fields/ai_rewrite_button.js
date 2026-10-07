/** @odoo-module **/

import { useService } from "@web/core/utils/hooks";
import { AiRewriteDialog } from "../dialog/ai_rewrite_dialog";

import { Component } from "@odoo/owl";

const RECORD_VALUE_TYPES = ["boolean", "char", "date", "datetime", "float", "integer", "monetary", "selection", "text"];

export class AiRewriteButton extends Component {
    setup() {
        this.dialog = useService("dialog");
    }

    openDialog() {
        this.dialog.add(AiRewriteDialog, {
            text: this.props.value,
            isHtml: this.props.isHtml,
            onApply: this.props.onApply,
            resModel: this.props.resModel,
            fieldName: this.props.fieldName,
            resId: this.props.resId,
            recordValues: this.getRecordValues(),
        });
    }

    // why: the server can only read what is saved, a timesheet line being typed has no id yet
    getRecordValues() {
        const record = this.props.record;
        const values = {};
        if (!record) {
            return values;
        }
        for (const [name, field] of Object.entries(record.fields)) {
            if (!(name in record.data)) {
                continue;
            }
            const value = record.data[name];
            if (field.type === "many2one") {
                values[name] = value ? value[0] : false;
            } else if (RECORD_VALUE_TYPES.includes(field.type)) {
                values[name] = value && value.toISO ? value.toISO() : value ?? false;
            }
        }
        return values;
    }
}
AiRewriteButton.template = "ai_text_rewrite.AiRewriteButton";
AiRewriteButton.props = {
    value: { type: String, optional: true },
    isHtml: { type: Boolean, optional: true },
    onApply: Function,
    resModel: { type: String, optional: true },
    fieldName: { type: String, optional: true },
    resId: { type: [Number, { value: false }], optional: true },
    record: { type: Object, optional: true },
};
AiRewriteButton.defaultProps = {
    value: "",
    isHtml: false,
};
