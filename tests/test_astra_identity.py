"""ASTRA announces itself recognisably, and in ASCII so Windows consoles keep it.

The banner exists so a person can tell at a glance that running activity is ASTRA
(and which line), rather than an anonymous process. A garbled banner would defeat
that, so it must be ASCII only - Windows cp1252 consoles mangle non-ASCII glyphs.
"""
import io
import os
import unittest
from unittest.mock import patch

import core.astra_identity as ident


class AstraIdentityTests(unittest.TestCase):
    def setUp(self):
        ident._BANNER_PRINTED = False

    def test_version_env_override_wins(self):
        with patch.dict(os.environ, {"ASTRA_VERSION": "9.9"}):
            self.assertEqual(ident.astra_version(), "9.9")

    def test_version_inferred_from_this_checkout(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ASTRA_VERSION", None)
            self.assertEqual(ident.astra_version(), "1.0")

    def test_banner_prints_once_per_process(self):
        buf = io.StringIO()
        with patch("core.astra_identity.sys.stderr", buf), \
                patch("core.astra_identity.set_console_title"):
            ident.banner("cycle")
            ident.banner("cycle")
        # one banner block per process; the engine line appears exactly once.
        self.assertEqual(buf.getvalue().count("scientific validation engine"), 1)

    def test_banner_names_version_action_and_pid(self):
        buf = io.StringIO()
        with patch.dict(os.environ, {"ASTRA_VERSION": "1.0"}), \
                patch("core.astra_identity.sys.stderr", buf), \
                patch("core.astra_identity.set_console_title"):
            ident.banner("quality benchmark")
        out = buf.getvalue()
        self.assertIn("ASTRA 1.0", out)
        self.assertIn("quality benchmark", out)
        self.assertIn(str(os.getpid()), out)
        self.assertIn("ABORTS", out)  # the close-the-window guidance

    def test_banner_is_ascii_only(self):
        buf = io.StringIO()
        with patch("core.astra_identity.sys.stderr", buf), \
                patch("core.astra_identity.set_console_title"):
            ident.banner("cycle")
        buf.getvalue().encode("ascii")  # raises if any non-ASCII slipped in

    def test_set_console_title_never_raises(self):
        # Best-effort; must be silent even where no console/API exists.
        ident.set_console_title("cycle")


if __name__ == "__main__":
    unittest.main()
