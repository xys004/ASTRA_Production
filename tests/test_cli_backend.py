import unittest

from core.cli_backend import _claude_argv


class CliBackendTests(unittest.TestCase):
    def test_claude_text_phases_disable_all_builtin_tools(self):
        command = _claude_argv("prompt.txt", "claude-opus-4-8", "", "")
        argv = command["argv"]
        tools_index = argv.index("--tools")
        self.assertEqual(argv[tools_index + 1], "")
        self.assertNotIn("--disallowed-tools", argv)
        self.assertIn("--strict-mcp-config", argv)


if __name__ == "__main__":
    unittest.main()
