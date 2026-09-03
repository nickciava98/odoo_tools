# Copyright 2026 Niccolò Ciavarella
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import importlib.util
import os

from odoo.modules.module import get_manifest, get_module_path
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger, parse_version

MODULE = "ai_text_rewrite"
MIGRATION_VERSION = "16.0.1.4.0"
MIGRATION_SCRIPT = "post-migrate.py"
PROMPT_PARAMETER = "ai_text_rewrite.system_prompt"
PREVIOUS_VERSION = "16.0.1.3.1"
OWN_PROMPT = "Scrivi tutto in maiuscolo e in rima."
_MIGRATION_MODULE_NAME = "ai_text_rewrite_prompt_post_migrate"


@tagged("post_install", "-at_install")
class TestMigratePromptDefault(TransactionCase):
    """The shipped prompt carries the author's own writing style, so databases installed before it
    must receive it — but a prompt the user wrote themselves must survive untouched."""

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
    def test_the_old_default_is_moved_to_the_work_log_prompt(self):
        for shipped in self.migration.OLD_DEFAULT_PROMPTS:
            self.config_param.set_param(PROMPT_PARAMETER, shipped)
            self._run_migration()
            self.env.invalidate_all()
            self.assertEqual(self.config_param.get_param(PROMPT_PARAMETER), self.migration.NEW_DEFAULT_PROMPT)

    @mute_logger(_MIGRATION_MODULE_NAME)
    def test_a_prompt_written_by_the_user_is_left_alone(self):
        self.config_param.set_param(PROMPT_PARAMETER, OWN_PROMPT)
        self._run_migration()
        self.env.invalidate_all()
        self.assertEqual(self.config_param.get_param(PROMPT_PARAMETER), OWN_PROMPT)

    @mute_logger(_MIGRATION_MODULE_NAME)
    def test_a_fresh_install_is_not_migrated(self):
        original = self.migration.OLD_DEFAULT_PROMPTS[0]
        self.config_param.set_param(PROMPT_PARAMETER, original)
        self._run_migration(version=None)
        self.env.invalidate_all()
        self.assertEqual(self.config_param.get_param(PROMPT_PARAMETER), original)

    def test_the_shipped_prompt_states_the_rules_that_shape_the_style(self):
        # why: the prompt is the feature here. Each of these rules was added because a measured
        # rewrite went wrong without it: padded tails, a mail stripped of its greeting, a label
        # turned into a sentence, an acronym left lowercase
        shipped = self.migration.NEW_DEFAULT_PROMPT
        for rule in ("same language", "Keep the shape of the input", "Never add",
                     "never drop one that is", "apostrophes and capitalisation",
                     "addresses a reader", "keep existing HTML markup"):
            self.assertIn(rule, shipped)
