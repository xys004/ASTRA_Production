import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.cli_backend import (
    CliResult,
    _agy_argv,
    _claude_argv,
    _codex_builder,
    _is_quota_error,
    _kill_tree,
    _model_ladder,
    _muse_argv,
    _writable_probe,
    call_cli,
)


class CliBackendTests(unittest.TestCase):
    def test_current_claude_quota_wordings_are_classified_as_quota(self):
        """The ladder only descends when the failure is classified as quota.

        "hit your weekly limit" is what Claude Code prints today; it used to
        fall through as a generic error, so the ladder broke at the first rung
        and never tried the next model (cycle_20260819_231945_f371).
        """
        for message in (
            "You've hit your weekly limit · resets 5am (America/Buenos_Aires)",
            "You've hit your usage limit",
            "You have reached your usage limit for this plan",
            "5-hour limit reached",
            "rate limit exceeded",
            "429 Too Many Requests",
            # Meta Muse Code wordings, observed 2026-09-03 during login; the
            # Model API side reports billing / insufficient credits.
            "Muse Code requires a payment method",
            "Payment method required to continue",
            "Billing error: account has no active plan",
            "insufficient credits for this request",
        ):
            with self.subTest(message=message):
                self.assertTrue(_is_quota_error(message))

    def test_real_failures_are_not_mistaken_for_quota(self):
        for message in (
            "exit 1: ModuleNotFoundError: No module named 'sympy'",
            "parseo fallo: JSONDecodeError: Expecting value",
            "perfil de cuenta claude invalido: home inexistente",
            # The one real Muse bridge failure on record
            # (workspace/cli_failures/20260903_010424_muse.json): a bug, not
            # quota, and it must keep reading as one.
            "exit 1: failed to read --prompt-file : No such file or directory (os error 2)",
        ):
            with self.subTest(message=message):
                self.assertFalse(_is_quota_error(message))

    def test_claude_text_phases_disable_all_builtin_tools(self):
        command = _claude_argv("prompt.txt", "claude-opus-4-8", "", "")
        argv = command["argv"]
        tools_index = argv.index("--tools")
        self.assertEqual(argv[tools_index + 1], "")
        self.assertNotIn("--disallowed-tools", argv)
        self.assertIn("--strict-mcp-config", argv)

    def test_agy_uses_maximum_supported_effort_by_default(self):
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            encoding="utf-8",
            delete=False,
        ) as handle:
            handle.write("test prompt")
            prompt_path = handle.name
        try:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("ASTRA_AGY_EFFORT", None)
                argv = _agy_argv(
                    prompt_path,
                    "gemini-3.1-pro-high",
                    "",
                    "",
                )
            effort_index = argv.index("--effort")
            self.assertEqual(argv[effort_index + 1], "high")
            self.assertIn("gemini-3.1-pro-high", argv)
        finally:
            os.remove(prompt_path)

    def test_agy_model_ladder_preserves_new_flash_fallback_order(self):
        ladder = _model_ladder(
            "agy",
            None,
            "gemini-3.1-pro-high,gemini-3.7-flash-high,gemini-3.5-flash-high",
        )
        self.assertEqual(
            ladder,
            [
                "gemini-3.1-pro-high",
                "gemini-3.7-flash-high",
                "gemini-3.5-flash-high",
            ],
        )

    def test_agy_forwards_gemini_37_alias_without_rewriting(self):
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            encoding="utf-8",
            delete=False,
        ) as handle:
            handle.write("test prompt")
            prompt_path = handle.name
        try:
            argv = _agy_argv(prompt_path, "gemini-3.7-flash-high", "", "")
            model_index = argv.index("--model")
            self.assertEqual(argv[model_index + 1], "gemini-3.7-flash-high")
        finally:
            os.remove(prompt_path)

    def test_codex_uses_native_stdin_invocation_on_macos(self):
        with patch("core.cli_backend.os.name", "posix"), patch(
            "core.cli_backend.shutil.which",
            return_value="/opt/homebrew/bin/codex",
        ), patch.dict(
            os.environ,
            {"ASTRA_CODEX_REASONING": "xhigh", "ASTRA_CODEX_BIN": ""},
            clear=False,
        ):
            command = _codex_builder(
                "/tmp/prompt.txt",
                "gpt-5.6-sol",
                "/tmp/output.txt",
                "/tmp/astra/workspace",
            )
        self.assertEqual(command["stdin_file"], "/tmp/prompt.txt")
        self.assertEqual(command["argv"][0], "/opt/homebrew/bin/codex")
        self.assertNotIn("powershell", command["argv"])
        self.assertIn('model_reasoning_effort="xhigh"', command["argv"])
        self.assertEqual(command["argv"][-1], "-")

    def test_muse_windows_bridge_uses_wsl_prompt_file_and_disables_tools(self):
        with patch("core.cli_backend.os.name", "nt"), patch.dict(
            os.environ,
            {"ASTRA_MUSE_WSL_DISTRO": "Debian", "ASTRA_MUSE_REASONING": "high"},
            clear=False,
        ):
            argv = _muse_argv(
                "C:\\Users\\Nelson\\Dev\\ASTRA\\workspace\\prompt.txt",
                "muse-spark-1.3", "", "",
            )
        self.assertEqual(argv[:3], ["wsl.exe", "-d", "Debian"])
        script = argv[6]
        self.assertIn("/mnt/c/Users/Nelson/Dev/ASTRA/workspace/prompt.txt", script)
        self.assertIn("--disable-write", script)
        self.assertIn("--disable-shell", script)
        self.assertIn("--disable-web-tools", script)
        self.assertIn("muse-spark-1.3", script)
        # Read tools stay rooted at the prompt's own directory, never at the
        # ASTRA checkout that the cycle runs from (which contains .env).
        self.assertIn("--workspace /mnt/c/Users/Nelson/Dev/ASTRA/workspace ", script)
        self.assertNotIn("--workspace /mnt/c/Users/Nelson/Dev/ASTRA ", script)
        for flag in (
            "--no-session-log",
            "--no-foreign-personal-context",
            "--approval-judge off",
        ):
            self.assertIn(flag, script)
        # The launcher's hourly self-update is disabled before it ever runs,
        # so the CLI build cannot drift under a trial pinned to one model.
        self.assertTrue(script.startswith("export MUSE_NO_AUTO_UPDATE=1; "))

    def test_muse_posix_bridge_pins_workspace_and_disables_auto_update(self):
        with patch("core.cli_backend.os.name", "posix"), patch.dict(
            os.environ, {"ASTRA_MUSE_REASONING": "high", "ASTRA_MUSE_BIN": ""},
            clear=False,
        ):
            argv = _muse_argv("/tmp/astra_cli_abc/prompt.txt", "muse-spark-1.3", "", "")
        self.assertEqual(argv[:3], ["env", "MUSE_NO_AUTO_UPDATE=1", "muse"])
        self.assertEqual(argv[argv.index("--workspace") + 1], "/tmp/astra_cli_abc")
        self.assertEqual(argv[argv.index("--approval-judge") + 1], "off")
        for flag in ("--no-session-log", "--no-foreign-personal-context",
                     "--disable-write", "--disable-shell", "--disable-web-tools"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--max-model-steps") + 1], "1")
        self.assertEqual(argv[argv.index("--model") + 1], "muse-spark-1.3")

    def test_cli_turn_uses_workspace_owned_temporaries(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = str(Path(temporary) / "work")
            with patch(
                "core.cli_backend._invoke_once",
                return_value=CliResult(True, text="READY"),
            ) as invoke:
                result = call_cli("claude", "test prompt", workspace=workspace)
        self.assertTrue(result.ok)
        promptfile = Path(invoke.call_args.args[1])
        self.assertEqual(promptfile.parent.parent, Path(workspace) / "cli_tmp")
        self.assertEqual(promptfile.name, "prompt.txt")

    def test_writable_probe_reports_a_denied_temp_root(self):
        """os.mkdir denied -> explicit, sandbox-aware error (not a hang).

        On Windows os.access(W_OK) reads only the DACL and never the restricted
        token, so under the Codex sandbox mkdtemp would retry os.TMP_MAX times.
        The probe does one real mkdir and fails fast instead.
        """
        with patch(
            "core.cli_backend.os.mkdir",
            side_effect=PermissionError(13, "Access is denied"),
        ):
            message = _writable_probe(r"C:\some\cli_tmp")
        self.assertIsInstance(message, str)
        self.assertIn("MCP", message)
        self.assertIn("ASTRA_CLI_TEMP_ROOT", message)

    def test_writable_probe_cleans_up_when_the_root_is_writable(self):
        created = {}
        removed = {}

        def fake_mkdir(path, *args, **kwargs):
            created["path"] = path

        def fake_rmdir(path, *args, **kwargs):
            removed["path"] = path

        with patch("core.cli_backend.os.mkdir", fake_mkdir), patch(
            "core.cli_backend.os.rmdir", fake_rmdir
        ):
            result = _writable_probe(r"C:\writable\cli_tmp")
        self.assertIsNone(result)
        self.assertEqual(removed.get("path"), created.get("path"))

    def test_call_cli_short_circuits_a_denied_probe_before_the_model(self):
        """A denied temp root must never reach _invoke_once (no quota spent)."""
        with patch(
            "core.cli_backend._writable_probe", return_value="DENIED"
        ), patch(
            "core.cli_backend._invoke_once",
            side_effect=AssertionError("the model must not be called"),
        ):
            result = call_cli("claude", "prompt")
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "DENIED")

    def test_cli_turn_cleans_its_temporary_on_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = str(Path(temporary) / "work")
            seen = {}

            def fake_invoke(kind, promptfile, outfile, mdl, ws, env, timeout):
                # The prompt file must exist DURING the call (Muse reads it).
                seen["tmp"] = os.path.dirname(promptfile)
                seen["existed_during"] = os.path.exists(promptfile)
                return CliResult(True, text="READY")

            with patch("core.cli_backend._invoke_once", fake_invoke):
                result = call_cli("claude", "prompt", workspace=workspace)
            self.assertTrue(result.ok)
            self.assertTrue(seen["existed_during"])
            # ... and it is gone afterwards: no astra_cli_* accretion.
            self.assertFalse(os.path.exists(seen["tmp"]))
            leftovers = list((Path(workspace) / "cli_tmp").glob("astra_cli_*"))
            self.assertEqual(leftovers, [])

    def test_cli_keep_temp_flag_preserves_the_temporary(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = str(Path(temporary) / "work")
            with patch.dict(os.environ, {"ASTRA_CLI_KEEP_TEMP": "1"}), patch(
                "core.cli_backend._invoke_once",
                return_value=CliResult(True, text="READY"),
            ):
                call_cli("claude", "prompt", workspace=workspace)
            leftovers = list((Path(workspace) / "cli_tmp").glob("astra_cli_*"))
            self.assertEqual(len(leftovers), 1)

    def test_timeout_branch_preserves_partial_output_and_writes_an_autopsy(self):
        """A phase that outlives its timeout keeps its partial stdout.

        The old branch discarded the second communicate(), so the reviewer
        timeout of 2026-09-10 left no trace. Now the partial output rides the
        error and an autopsy lands in workspace/cli_failures/.
        """
        import glob
        import sys as _sys

        def slow_builder(promptfile, model, outfile, ws):
            return [
                _sys.executable,
                "-c",
                'import time; print("PARTIAL-OUT", flush=True); time.sleep(30)',
            ]

        failures_dir = os.path.join(
            __import__("core.cli_backend", fromlist=["_PROJECT_ROOT"])._PROJECT_ROOT,
            "workspace",
            "cli_failures",
        )
        before = set(glob.glob(os.path.join(failures_dir, "*_slowtimeout.json")))
        with patch.dict(
            "core.cli_backend._BUILDERS", {"slowtimeout": slow_builder}
        ), patch.dict(
            "core.cli_backend._PARSERS",
            {"slowtimeout": lambda out, outfile: (out, 0.0)},
        ):
            result = call_cli("slowtimeout", "prompt", timeout=1)
        self.assertFalse(result.ok)
        self.assertIn("timeout tras 1s", result.error)
        self.assertIn("PARTIAL-OUT", result.error)
        after = set(glob.glob(os.path.join(failures_dir, "*_slowtimeout.json")))
        new_dumps = sorted(after - before)
        self.assertEqual(len(new_dumps), 1)
        try:
            import json as _json

            dump = _json.load(open(new_dumps[0], encoding="utf-8"))
            self.assertEqual(dump["reason"], "timeout tras 1s")
            self.assertIn("PARTIAL-OUT", dump["stdout"])
        finally:
            for path in new_dumps:
                os.remove(path)

    def test_posix_timeout_kills_the_process_group(self):
        with patch("core.cli_backend.os.name", "posix"), patch(
            "core.cli_backend.os.getpgid",
            return_value=4321,
            create=True,
        ), patch("core.cli_backend.os.killpg", create=True) as killpg:
            with patch("core.cli_backend.signal.SIGKILL", 9, create=True):
                _kill_tree(1234)
        killpg.assert_called_once()
        self.assertEqual(killpg.call_args.args[0], 4321)


if __name__ == "__main__":
    unittest.main()
