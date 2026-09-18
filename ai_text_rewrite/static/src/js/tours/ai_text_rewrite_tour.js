/** @odoo-module **/

import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("ai_text_rewrite_replace", {
    // No "url" here on purpose: the wrapper's start_tour() navigates to a specific scratch
    // record beforehand. Setting "url" would make the tour force a redirect to it as soon as
    // it starts running, wiping out the action/record we just opened.
    test: true,
    steps: () => [
    {
        // Open the dialog from the AI button of the "ai_text" widget.
        trigger: '.o_field_widget[name="text"] .o_ai_rewrite_button',
        run: "click",
    },
    {
        // No leading ".modal" here: once a modal is visible, the tour runner scopes every
        // trigger lookup to `$('.modal:visible').last().find(trigger)` on its own, so a
        // trigger that repeats ".modal" ends up looking for a nested modal that never matches.
        trigger: ".o_ai_rewrite_dialog textarea#ai_rewrite_instruction",
        run: "edit Rewrite this note for the QA smoke test.",
    },
    {
        // Only the "Generate" button lives inside .o_ai_rewrite_dialog (Replace/Regenerate/Cancel are in the footer).
        trigger: ".o_ai_rewrite_dialog .btn-primary",
        run: "click",
    },
    {
        // Replace is disabled until a preview exists: waiting for ":not([disabled])" waits for the mocked
        // provider call to resolve instead of clicking a dead button.
        trigger: ".modal-footer .btn-primary:not([disabled])",
        run: "click",
    },
    {
        trigger: ".o_form_button_save",
        run: "click",
    },
    {
        // Last step, no run: the tour runner does not auto-click the last trigger, this is a pure check
        // that the form went back to its saved (non-dirty) state.
        trigger: ".o_form_saved",
    },
]);

registry.category("web_tour.tours").add("ai_text_rewrite_settings_provider_switch", {
    // No "url": the wrapper navigates straight to the res.config.settings action beforehand,
    // same reasoning as the tour above.
    test: true,
    steps: () => [
    {
        // Switch away from the default "openai" provider, onto "pollinations". The tour engine's
        // own "text <value>" handling for a <select> (running_tour_action_helper.js, RunningTourActionHelper._text)
        // matches an <option> by its real DOM value first: our options carry the JSON-encoded
        // field value (e.g. `"pollinations"`, quotes included, from SelectionField's `stringify()`),
        // so the trigger text must be that exact JSON literal, not the human-readable label - the
        // label-matching fallback the helper falls back to is unreliable on this widget and silently
        // resets the selection instead of raising, which is a different, non-crashing quirk than the
        // one under test here.
        trigger: '.app_settings_block[data-key="ai_text_rewrite"] .o_field_widget[name="ai_rewrite_provider"] select',
        run: 'text "pollinations"',
    },
    {
        // Proves the form re-rendered instead of crashing: the pollinations-only warning is now
        // visible, and no client error dialog interrupted the tour (it would have timed out here).
        // Anchored on the stable data-test attribute, not the (translatable) warning text: this
        // string lives in i18n/it.po and renders in whatever language the DB/user is in.
        trigger: '.app_settings_block[data-key="ai_text_rewrite"] p[data-test="pollinations-warning"]',
    },
    {
        // Switch back to "openai": the direction originally reported as crashing.
        trigger: '.app_settings_block[data-key="ai_text_rewrite"] .o_field_widget[name="ai_rewrite_provider"] select',
        run: 'text "openai"',
    },
    {
        // Same proof in the other direction: the base_url/api_key/model group is visible again.
        // Last step, no run: Settings has no readonly mode to return to (it is always "editable"),
        // so the wrapper must set allow_end_on_form = True instead of expecting a save/discard here.
        trigger: '.app_settings_block[data-key="ai_text_rewrite"] .o_field_widget[name="ai_rewrite_base_url"] input',
    },
]);

registry.category("web_tour.tours").add("ai_text_rewrite_replace_html", {
    // No "url" here on purpose, same reasoning as "ai_text_rewrite_replace": the wrapper's
    // start_tour() navigates to a specific scratch record beforehand.
    test: true,
    steps: () => [
    {
        // Open the dialog from the AI button of the "ai_html" widget. Same dialog component as
        // "ai_text_rewrite_replace": what's under test here is that Replace actually reaches the
        // wysiwyg editor, not the shared dialog flow already covered by that other tour.
        trigger: '.o_field_widget[name="html"] .o_ai_rewrite_button',
        run: "click",
    },
    {
        trigger: ".o_ai_rewrite_dialog textarea#ai_rewrite_instruction",
        run: "edit Rewrite this note for the QA smoke test.",
    },
    {
        trigger: ".o_ai_rewrite_dialog .btn-primary",
        run: "click",
    },
    {
        trigger: ".modal-footer .btn-primary:not([disabled])",
        run: "click",
    },
    {
        trigger: ".o_form_button_save",
        run: "click",
    },
    {
        // Last step, no run: proves the wysiwyg commit-on-save round trip went through instead
        // of leaving the record dirty (the actual field content is asserted from Python, on the
        // saved record, once the tour is done).
        trigger: ".o_form_saved",
    },
    ],
});
