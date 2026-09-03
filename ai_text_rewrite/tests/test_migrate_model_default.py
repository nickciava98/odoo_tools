# Copyright 2026 Niccolò Ciavarella
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import importlib.util
import os

from odoo.modules.module import get_manifest, get_module_path
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger, parse_version

MODULE = "ai_text_rewrite"
MIGRATION_VERSION = "16.0.1.2.0"
MIGRATION_SCRIPT = "post-migrate.py"
MODEL_PARAMETER = "ai_text_rewrite.model"
PREVIOUS_MODEL = "llama-3.3-70b-versatile"
CURRENT_MODEL = "openai/gpt-oss-120b"
PREVIOUS_VERSION = "16.0.1.1.0"
_MIGRATION_MODULE_NAME = "ai_text_rewrite_model_post_migrate"


@tagged("post_install", "-at_install")
class TestMigrateModelDefault(TransactionCase):
    """The shipped llama model is not served to every API key, so databases installed before the
    switch keep failing with a 404 until this migration moves them off it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config_param = cls.env["ir.config_parameter"].sudo()
        cls.migration = cls._load_migration_script()

    @classmethod
    def _load_migration_script(cls):
        script_path = os.path.join(get_module_path(MODULE), "migrations", MIGRATION_VERSION, MIGRATION_SCRIPT)
        spec = importlib.util.spec_from_file_location(_MIGRATION_MODULE_NAME, script_path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        return migration

    def _run_migration(self, version=PREVIOUS_VERSION):
        self.migration.migrate(self.env.cr, version)
        return True

    def test_migration_directory_is_not_above_the_manifest_version(self):
        self.assertLessEqual(parse_version(MIGRATION_VERSION), parse_version(get_manifest(MODULE)["version"]))
        self.assertTrue(os.path.isfile(os.path.join(get_module_path(MODULE), "migrations", MIGRATION_VERSION, MIGRATION_SCRIPT)))

    @mute_logger(_MIGRATION_MODULE_NAME)
    def test_the_old_default_is_moved_to_the_current_model(self):
        self.config_param.set_param(MODEL_PARAMETER, PREVIOUS_MODEL)
        self._run_migration()
        self.env.invalidate_all()
        self.assertEqual(self.config_param.get_param(MODEL_PARAMETER), CURRENT_MODEL)

    def test_a_model_chosen_on_purpose_is_left_alone(self):
        self.config_param.set_param(MODEL_PARAMETER, "qwen/qwen3.8-27b")
        self._run_migration()
        self.env.invalidate_all()
        self.assertEqual(self.config_param.get_param(MODEL_PARAMETER), "qwen/qwen3.8-27b")

    def test_a_missing_parameter_is_left_alone(self):
        self.config_param.search([("key", "=", MODEL_PARAMETER)]).unlink()
        self._run_migration()
        self.env.invalidate_all()
        self.assertFalse(self.config_param.get_param(MODEL_PARAMETER))

    def test_a_fresh_install_is_not_migrated(self):
        # why: Odoo passes an empty version on a fresh install, where data/ already ships the new model
        self.config_param.set_param(MODEL_PARAMETER, PREVIOUS_MODEL)
        self._run_migration(version=None)
        self.env.invalidate_all()
        self.assertEqual(self.config_param.get_param(MODEL_PARAMETER), PREVIOUS_MODEL)
