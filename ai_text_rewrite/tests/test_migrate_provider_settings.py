# Copyright 2026 Niccolò Ciavarella
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import importlib.util
import os

from odoo.modules.module import get_manifest, get_module_path
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger, parse_version

MODULE = "ai_text_rewrite"
MIGRATION_VERSION = "16.0.2.0.0"
MIGRATION_SCRIPT = "post-migrate.py"
PREVIOUS_VERSION = "16.0.1.5.0"
MOVED_KEYS = ("base_url", "api_key", "model", "timeout")
OLD_VALUES = {
    "base_url": "https://old.example.invalid/v1",
    "api_key": "sk-old-key",
    "model": "old-model",
    "timeout": "42"
}
SHIPPED_AI_BASE_VALUES = {
    "base_url": "https://api.groq.com/openai/v1",
    "model": "openai/gpt-oss-120b",
    "timeout": "60"
}
# xmlids the 16.0.1.x data file created on the moved keys (noupdate, so _process_end never removes them)
OLD_XMLIDS = {
    "base_url": "ai_rewrite_base_url_parameter",
    "model": "ai_rewrite_model_parameter",
    "timeout": "ai_rewrite_timeout_parameter"
}
_MIGRATION_MODULE_NAME = "ai_text_rewrite_provider_settings_post_migrate"


@tagged("post_install", "-at_install")
class TestMigrateProviderSettings(TransactionCase):
    """16.0.2.0.0 moves the endpoint configuration to ai_base: an upgraded database must keep working
    with the endpoint, key and model its administrator had chosen, and must not keep a dead copy behind."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config_param = cls.env["ir.config_parameter"].sudo()
        cls.model_data = cls.env["ir.model.data"].sudo()
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
        self.env.invalidate_all()
        return True

    def _set_ai_base(self, **values):
        for key, value in values.items():
            self.config_param.set_param("ai_base.%s" % key, value)
        return True

    def _set_old_parameters(self, values):
        """Rebuild the 16.0.1.5.0 state: old keys valued, and the xmlids its data file had put on them."""
        for key, value in values.items():
            self.config_param.set_param("ai_text_rewrite.%s" % key, value)
            if key not in OLD_XMLIDS:
                continue
            self.model_data.search([("module", "=", MODULE), ("name", "=", OLD_XMLIDS[key])]).unlink()
            self.model_data.create({
                "module": MODULE,
                "name": OLD_XMLIDS[key],
                "model": "ir.config_parameter",
                "res_id": self.config_param.search([("key", "=", "ai_text_rewrite.%s" % key)]).id,
                "noupdate": True
            })
        return True

    def _old_xmlid_ids(self):
        return self.model_data.search([("module", "=", MODULE), ("name", "in", list(OLD_XMLIDS.values()))])

    def test_migration_directory_is_not_above_the_manifest_version(self):
        self.assertLessEqual(parse_version(MIGRATION_VERSION), parse_version(get_manifest(MODULE)["version"]))
        self.assertTrue(os.path.isfile(os.path.join(get_module_path(MODULE), "migrations", MIGRATION_VERSION, MIGRATION_SCRIPT)))

    @mute_logger(_MIGRATION_MODULE_NAME)
    def test_old_values_are_copied_to_ai_base(self):
        # The administrator's endpoint wins over the ai_base defaults shipped by the fresh dependency.
        self._set_ai_base(**SHIPPED_AI_BASE_VALUES)
        self._set_old_parameters(OLD_VALUES)
        self._run_migration()
        for key in MOVED_KEYS:
            with self.subTest(key=key):
                self.assertEqual(self.config_param.get_param("ai_base.%s" % key), OLD_VALUES[key])

    @mute_logger(_MIGRATION_MODULE_NAME)
    def test_the_migrated_values_are_the_ones_the_provider_uses(self):
        # End of the chain: the copied values must be readable through the real consumer, ai.provider.
        self._set_ai_base(**SHIPPED_AI_BASE_VALUES)
        self._set_old_parameters(OLD_VALUES)
        self._run_migration()
        self.assertEqual(self.env["ai.provider"]._get_provider_settings(), {
            "base_url": OLD_VALUES["base_url"],
            "api_key": OLD_VALUES["api_key"],
            "model": OLD_VALUES["model"],
            "timeout": int(OLD_VALUES["timeout"])
        })

    @mute_logger(_MIGRATION_MODULE_NAME)
    def test_old_keys_are_deleted(self):
        # A dead copy of the key is a secret left in the database that nobody rotates.
        self._set_old_parameters(OLD_VALUES)
        self._run_migration()
        for key in MOVED_KEYS:
            with self.subTest(key=key):
                self.assertFalse(self.config_param.search([("key", "=", "ai_text_rewrite.%s" % key)]))

    @mute_logger(_MIGRATION_MODULE_NAME)
    def test_old_xmlids_are_deleted(self):
        # noupdate records dropped from data/ are never cleaned by Odoo: orphan xmlids would stay forever.
        self._set_old_parameters(OLD_VALUES)
        self.assertEqual(len(self._old_xmlid_ids()), len(OLD_XMLIDS))
        self._run_migration()
        self.assertFalse(self._old_xmlid_ids())

    @mute_logger(_MIGRATION_MODULE_NAME)
    def test_the_parameters_that_stay_are_left_alone(self):
        # Provider and system prompt keep living on ai_text_rewrite.*: the cleanup must not reach them.
        self.config_param.set_param("ai_text_rewrite.provider", "pollinations")
        self.config_param.set_param("ai_text_rewrite.system_prompt", "Keep me.")
        self._set_old_parameters(OLD_VALUES)
        self._run_migration()
        self.assertEqual(self.config_param.get_param("ai_text_rewrite.provider"), "pollinations")
        self.assertEqual(self.config_param.get_param("ai_text_rewrite.system_prompt"), "Keep me.")
        provider_parameter_id = self.env.ref("ai_text_rewrite.ai_rewrite_provider_parameter", False)
        self.assertTrue(provider_parameter_id, "The xmlid of a parameter that stays must survive the cleanup")

    @mute_logger(_MIGRATION_MODULE_NAME)
    def test_a_missing_old_key_does_not_overwrite_ai_base(self):
        # A database that never had an API key must not wipe the one already set on ai_base.
        self._set_ai_base(api_key="sk-new-key", **SHIPPED_AI_BASE_VALUES)
        old_values = dict(OLD_VALUES)
        old_values.pop("api_key")
        self.config_param.set_param("ai_text_rewrite.api_key", False)
        self._set_old_parameters(old_values)
        self._run_migration()
        self.assertEqual(self.config_param.get_param("ai_base.api_key"), "sk-new-key")
        self.assertEqual(self.config_param.get_param("ai_base.model"), OLD_VALUES["model"])

    @mute_logger(_MIGRATION_MODULE_NAME)
    def test_the_migration_is_idempotent(self):
        # A rerun (failed upgrade restarted, manual replay) must neither crash nor reset ai_base to anything.
        self._set_ai_base(**SHIPPED_AI_BASE_VALUES)
        self._set_old_parameters(OLD_VALUES)
        self._run_migration()
        self._run_migration()
        for key in MOVED_KEYS:
            with self.subTest(key=key):
                self.assertEqual(self.config_param.get_param("ai_base.%s" % key), OLD_VALUES[key])
                self.assertFalse(self.config_param.search([("key", "=", "ai_text_rewrite.%s" % key)]))

    @mute_logger(_MIGRATION_MODULE_NAME)
    def test_a_fresh_install_is_not_migrated(self):
        # why: Odoo passes an empty version on a fresh install, where there is nothing to move
        self._set_ai_base(**SHIPPED_AI_BASE_VALUES)
        self._set_old_parameters(OLD_VALUES)
        self._run_migration(version=None)
        self.assertEqual(self.config_param.get_param("ai_base.base_url"), SHIPPED_AI_BASE_VALUES["base_url"])
        self.assertEqual(self.config_param.get_param("ai_text_rewrite.base_url"), OLD_VALUES["base_url"])
        self.assertEqual(len(self._old_xmlid_ids()), len(OLD_XMLIDS))
