# Copyright 2026 Niccolò Ciavarella
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import importlib.util
import os

from odoo.modules.module import get_manifest, get_module_path
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger, parse_version

MODULE = "ai_text_rewrite"
MIGRATION_VERSION = "16.0.1.0.1"
MIGRATION_SCRIPT = "post-migrate.py"
PARAMETER_KEY = "ai_text_rewrite.provider"
PREVIOUS_VERSION = "16.0.1.0.0"
# The script is loaded from its path, so its logger is named after the name given to the loader below.
_MIGRATION_MODULE_NAME = "ai_text_rewrite_post_migrate"


@tagged("post_install", "-at_install")
class TestMigrateProviderDefault(TransactionCase):
    """data/ is noupdate="1", so the switch to the paid endpoint on already installed databases
    can only come from this migration: it must move the old default and nothing else."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config_param = cls.env["ir.config_parameter"].sudo()
        cls.migration = cls._load_migration_script()

    @classmethod
    def _load_migration_script(cls):
        """Load the real migration file: "migrations/<version>/post-migrate.py" is not an importable
        module (versioned directory, dash in the file name), so it is loaded from its path."""
        script_path = os.path.join(get_module_path(MODULE), "migrations", MIGRATION_VERSION, MIGRATION_SCRIPT)
        spec = importlib.util.spec_from_file_location(_MIGRATION_MODULE_NAME, script_path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        return migration

    def _run_migration(self, version=PREVIOUS_VERSION):
        self.migration.migrate(self.env.cr, version)
        return True

    def test_migration_directory_is_not_above_the_manifest_version(self):
        # A migration living in a directory above the manifest version is never executed: the bump and
        # the folder must stay in sync, or the parameter silently stays on the free provider forever.
        self.assertLessEqual(parse_version(MIGRATION_VERSION), parse_version(get_manifest(MODULE)["version"]))
        self.assertTrue(os.path.isfile(os.path.join(get_module_path(MODULE), "migrations", MIGRATION_VERSION, MIGRATION_SCRIPT)))

    @mute_logger(_MIGRATION_MODULE_NAME)
    def test_old_default_is_moved_to_the_new_provider(self):
        # The whole point: databases installed before the switch are still pointing at the free service.
        self.config_param.set_param(PARAMETER_KEY, "pollinations")
        self._run_migration()
        self.assertEqual(self.config_param.get_param(PARAMETER_KEY), "openai")

    @mute_logger(_MIGRATION_MODULE_NAME)
    def test_provider_already_on_the_new_default_is_left_alone(self):
        # Also the idempotency check: a second run of the same migration must be a no-op.
        self.config_param.set_param(PARAMETER_KEY, "openai")
        self._run_migration()
        self.assertEqual(self.config_param.get_param(PARAMETER_KEY), "openai")

    @mute_logger(_MIGRATION_MODULE_NAME)
    def test_deliberate_custom_provider_is_not_overwritten(self):
        # A value the user chose on purpose is not ours to reset, whatever it is.
        self.config_param.set_param(PARAMETER_KEY, "custom-endpoint")
        self._run_migration()
        self.assertEqual(self.config_param.get_param(PARAMETER_KEY), "custom-endpoint")

    @mute_logger(_MIGRATION_MODULE_NAME)
    def test_missing_parameter_is_left_missing(self):
        # No parameter means the code fallback ("openai") already applies: creating one here would only
        # freeze today's default into the database.
        self.config_param.set_param(PARAMETER_KEY, False)
        self._run_migration()
        self.assertFalse(self.config_param.get_param(PARAMETER_KEY))
        self.assertFalse(self.config_param.search([("key", "=", PARAMETER_KEY)]))

    @mute_logger(_MIGRATION_MODULE_NAME)
    def test_fresh_install_is_skipped(self):
        # On a fresh install Odoo calls migrate() with version=None and data/ already ships the new
        # default: the script must not run at all there.
        self.config_param.set_param(PARAMETER_KEY, "pollinations")
        self._run_migration(None)
        self.assertEqual(self.config_param.get_param(PARAMETER_KEY), "pollinations")
