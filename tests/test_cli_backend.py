import os
import tempfile
import unittest
from unittest.mock import patch

from core.cli_backend import _agy_argv, _claude_argv


class CliBackendTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
