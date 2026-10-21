{
    "name": "AI Base",
    "summary": "Shared configuration and client for an OpenAI-compatible AI provider",
    "version": "18.0.1.0.0",
    "author": "Niccolò Ciavarella",
    "website": "https://nciavarella.odoo-cloud.ovh",
    "license": "LGPL-3",
    "category": "Productivity",
    "depends": [
        "base_setup"
    ],
    "external_dependencies": {
        "python": [
            "requests"
        ]
    },
    "data": [
        "data/ai_base_data.xml",
        "views/res_config_settings_views.xml"
    ],
    "installable": True
}
