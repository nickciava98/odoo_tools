{
    "name": "AI Text Rewrite",
    "summary": "Rewrite the content of char, text and html fields with an AI model, using a shared prompt set in Settings",
    "version": "18.0.1.0.0",
    "author": "Niccolò Ciavarella",
    "website": "https://nciavarella.odoo-cloud.ovh",
    "license": "LGPL-3",
    "category": "Productivity",
    "depends": [
        "html_editor"
    ],
    "external_dependencies": {
        "python": [
            "requests"
        ]
    },
    "assets": {
        "web.assets_backend": [
            "ai_text_rewrite/static/src/ai_rewrite.scss",
            "ai_text_rewrite/static/src/dialog/ai_rewrite_dialog.js",
            "ai_text_rewrite/static/src/dialog/ai_rewrite_dialog.xml",
            "ai_text_rewrite/static/src/fields/ai_rewrite_button.js",
            "ai_text_rewrite/static/src/fields/ai_rewrite_button.xml",
            "ai_text_rewrite/static/src/fields/ai_rewrite_html_field.js",
            "ai_text_rewrite/static/src/fields/ai_rewrite_html_field.xml",
            "ai_text_rewrite/static/src/fields/ai_rewrite_text_field.js",
            "ai_text_rewrite/static/src/fields/ai_rewrite_text_field.xml"
        ],
        "web.assets_tests": [
            "ai_text_rewrite/static/src/js/tours/ai_text_rewrite_tour.js"
        ]
    },
    "data": [
        "data/ai_rewrite_data.xml",
        "views/res_config_settings_views.xml"
    ],
    "installable": True
}
