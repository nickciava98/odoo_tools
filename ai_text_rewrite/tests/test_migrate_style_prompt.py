# Copyright 2026 Niccolò Ciavarella
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import importlib.util
import os

from odoo.modules.module import get_manifest, get_module_path
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger, parse_version

MODULE = "ai_text_rewrite"
MIGRATION_VERSION = "16.0.1.5.0"
PREVIOUS_MIGRATION_VERSION = "16.0.1.4.0"
MIGRATION_SCRIPT = "post-migrate.py"
PROMPT_PARAMETER = "ai_text_rewrite.system_prompt"
PREVIOUS_VERSION = "16.0.1.4.1"
OWN_PROMPT = "Scrivi tutto in maiuscolo e in rima."
_MIGRATION_MODULE_NAME = "ai_text_rewrite_style_prompt_post_migrate"


@tagged("post_install", "-at_install")
class TestMigrateStylePrompt(TransactionCase):
    """The previous shipped prompt forbade developing the text: databases still on it move to the new one."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config_param = cls.env["ir.config_parameter"].sudo()
        cls.migration = cls._load_migration_script(MIGRATION_VERSION, _MIGRATION_MODULE_NAME)
        cls.previous_migration = cls._load_migration_script(PREVIOUS_MIGRATION_VERSION, "%s_previous" % _MIGRATION_MODULE_NAME)

    @classmethod
    def _load_migration_script(cls, version, module_name):
        script_path = os.path.join(get_module_path(MODULE), "migrations", version, MIGRATION_SCRIPT)
        spec = importlib.util.spec_from_file_location(module_name, script_path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        return migration

    def _run_migration(self, version=PREVIOUS_VERSION):
        self.migration.migrate(self.env.cr, version)
        return True

    def test_migration_directory_is_not_above_the_manifest_version(self):
        self.assertLessEqual(parse_version(MIGRATION_VERSION), parse_version(get_manifest(MODULE)["version"]))

    @mute_logger(_MIGRATION_MODULE_NAME)
    def test_the_previous_default_is_moved_to_the_shipped_prompt(self):
        self.config_param.set_param(PROMPT_PARAMETER, self.previous_migration.NEW_DEFAULT_PROMPT)
        self._run_migration()
        self.env.invalidate_all()
        prompt = self.config_param.get_param(PROMPT_PARAMETER)
        self.assertIn("Explain more, invent nothing", prompt)
        self.assertNotIn("a thin input stays thin", prompt)

    @mute_logger(_MIGRATION_MODULE_NAME)
    def test_a_prompt_written_by_the_user_is_left_alone(self):
        self.config_param.set_param(PROMPT_PARAMETER, OWN_PROMPT)
        self._run_migration()
        self.env.invalidate_all()
        self.assertEqual(self.config_param.get_param(PROMPT_PARAMETER), OWN_PROMPT)

    @mute_logger(_MIGRATION_MODULE_NAME)
    def test_a_fresh_install_is_not_migrated(self):
        self.config_param.set_param(PROMPT_PARAMETER, self.previous_migration.NEW_DEFAULT_PROMPT)
        self._run_migration(version=None)
        self.env.invalidate_all()
        self.assertEqual(self.config_param.get_param(PROMPT_PARAMETER), self.previous_migration.NEW_DEFAULT_PROMPT)
