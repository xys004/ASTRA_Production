import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.account_profiles import (
    AccountProfileError,
    add_isolated_profile,
    bootstrap_current_profile,
    confirm_provider_identity,
    load_registry,
    profile_environment,
    set_active_profile,
    set_provider_home,
)


class AccountProfileTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "registry"
        self.home = Path(self.tempdir.name) / "user"
        self.home.mkdir()
        self.patches = [
            patch.dict(
                os.environ,
                {
                    "ASTRA_ACCOUNT_PROFILE_ROOT": str(self.root),
                    "CODEX_HOME": str(self.home / ".codex"),
                    "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
                },
                clear=False,
            ),
            patch("core.account_profiles.Path.home", return_value=self.home),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tempdir.cleanup()

    def test_bootstrap_references_existing_homes_without_copying_tokens(self):
        data = bootstrap_current_profile(
            "primary", {"codex": "owner@example.com"}
        )
        record = data["profiles"]["primary"]["providers"]["codex"]
        self.assertEqual(Path(record["home"]), self.home / ".codex")
        self.assertEqual(record["expected_email"], "owner@example.com")
        self.assertFalse((self.root / "profiles" / "primary").exists())
        self.assertEqual(data["active"]["codex"], "primary")

    def test_isolated_profile_needs_login_before_activation(self):
        bootstrap_current_profile("primary")
        add_isolated_profile("backup")
        with self.assertRaisesRegex(AccountProfileError, "aun no esta autenticado"):
            set_active_profile("backup", ["codex"])
        config = self.root / "profiles" / "backup" / "codex" / "config.toml"
        self.assertIn('cli_auth_credentials_store = "file"', config.read_text())

    def test_active_profiles_are_independent_per_provider(self):
        bootstrap_current_profile("primary")
        data = add_isolated_profile("backup")
        backup = data["profiles"]["backup"]["providers"]
        Path(backup["codex"]["home"], "auth.json").write_text("{}", encoding="utf-8")
        set_active_profile("backup", ["codex"])
        data = load_registry()
        self.assertEqual(data["active"]["codex"], "backup")
        self.assertEqual(data["active"]["claude"], "primary")
        label, env = profile_environment("codex")
        self.assertEqual(label, "backup")
        self.assertEqual(Path(env["CODEX_HOME"]), Path(backup["codex"]["home"]))

    def test_registry_contains_no_credential_payloads(self):
        bootstrap_current_profile("primary", {"agy": "owner@example.com"})
        raw = (self.root / "profiles.json").read_text(encoding="utf-8")
        parsed = json.loads(raw)
        self.assertNotIn("access_token", raw)
        self.assertNotIn("refresh_token", raw)
        self.assertEqual(
            parsed["profiles"]["primary"]["providers"]["agy"]["expected_email"],
            "owner@example.com",
        )

    def test_existing_authenticated_home_can_replace_one_provider_only(self):
        data = bootstrap_current_profile("primary")
        alternate = Path(self.tempdir.name) / "existing-codex"
        alternate.mkdir()
        (alternate / "auth.json").write_text("{}", encoding="utf-8")
        data = set_provider_home(
            "primary", "codex", alternate, "owner@example.com"
        )
        providers = data["profiles"]["primary"]["providers"]
        self.assertEqual(Path(providers["codex"]["home"]), alternate)
        self.assertEqual(Path(providers["claude"]["home"]), self.home / ".claude")

    def test_manual_identity_confirmation_is_recorded_without_tokens(self):
        (self.home / ".claude").mkdir()
        (self.home / ".claude" / ".credentials.json").write_text(
            "{}", encoding="utf-8"
        )
        bootstrap_current_profile("primary")
        data = confirm_provider_identity(
            "primary", "claude", "owner@example.com", source="manual-user"
        )
        record = data["profiles"]["primary"]["providers"]["claude"]
        self.assertEqual(record["identity_confirmation"]["source"], "manual-user")
        self.assertEqual(record["identity_confirmation"]["email"], "owner@example.com")

    def test_call_cli_injects_only_the_selected_provider_home(self):
        bootstrap_current_profile("primary")
        data = add_isolated_profile("backup")
        backup = data["profiles"]["backup"]["providers"]
        Path(backup["claude"]["home"], ".credentials.json").write_text(
            "{}", encoding="utf-8"
        )
        set_active_profile("backup", ["claude"])
        from core.cli_backend import CliResult, call_cli

        with patch(
            "core.cli_backend._invoke_once",
            return_value=CliResult(True, text="READY"),
        ) as invoke:
            result = call_cli("claude", "test", workspace=str(self.root / "work"))
        child_env = invoke.call_args.args[5]
        self.assertTrue(result.ok)
        self.assertEqual(result.account_profile, "backup")
        self.assertEqual(
            Path(child_env["CLAUDE_CONFIG_DIR"]),
            Path(backup["claude"]["home"]),
        )
        self.assertEqual(child_env.get("CODEX_HOME"), os.environ.get("CODEX_HOME"))


if __name__ == "__main__":
    unittest.main()
