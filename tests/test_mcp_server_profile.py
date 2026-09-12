"""ASTRA_PROFILE abstraction (docs/architecture/ASTRA_UNIFIED_MCP_RFC.md §6).

Phase 2 of the unified-service RFC: replace the two independently-defaulted
flags (server name, campaign-tools gate) with one named profile, WITHOUT
changing any default behaviour. These tests pin the equivalence directly:
every case that mattered before this refactor must resolve to the exact same
values after it, including the safety-relevant coupling where renaming the
server to "astra" (the documented promotion override) silently disables
campaign tools even without ASTRA_PROFILE or ASTRA_CAMPAIGN_TOOLS set.
"""
import importlib
import sys
import types
import unittest
from unittest.mock import patch


class _FakeFastMCP:
    def __init__(self, *_args, **_kwargs):
        pass

    def tool(self):
        return lambda function: function

    def run(self):
        pass


fastmcp = types.ModuleType("mcp.server.fastmcp")
fastmcp.FastMCP = _FakeFastMCP
server = types.ModuleType("mcp.server")
mcp = types.ModuleType("mcp")
with patch.dict(
    sys.modules,
    {
        "mcp": mcp,
        "mcp.server": server,
        "mcp.server.fastmcp": fastmcp,
    },
):
    server_module = importlib.import_module("mcp_server.server")


class ProfileResolutionTests(unittest.TestCase):
    def test_defaults_to_campaign_for_a_2_0_checkout(self):
        profile = server_module._resolve_profile(root=r"C:\Users\Nelson\Dev\ASTRA-2.0", env={})
        self.assertEqual(profile, "campaign")

    def test_defaults_to_production_for_a_non_2_0_checkout(self):
        profile = server_module._resolve_profile(root=r"C:\Users\Nelson\Dev\ASTRA", env={})
        self.assertEqual(profile, "production")

    def test_explicit_astra_profile_env_wins_over_the_checkout_heuristic(self):
        profile = server_module._resolve_profile(
            root=r"C:\Users\Nelson\Dev\ASTRA-2.0", env={"ASTRA_PROFILE": "production"}
        )
        self.assertEqual(profile, "production")

    def test_an_unrecognised_astra_profile_value_falls_back_to_the_heuristic(self):
        profile = server_module._resolve_profile(
            root=r"C:\Users\Nelson\Dev\ASTRA-2.0", env={"ASTRA_PROFILE": "nonsense"}
        )
        self.assertEqual(profile, "campaign")


class ServerNameResolutionTests(unittest.TestCase):
    def test_production_profile_names_the_server_astra(self):
        self.assertEqual(server_module._resolve_server_name("production", env={}), "astra")

    def test_campaign_and_dev_profiles_name_the_server_astra_dev(self):
        self.assertEqual(server_module._resolve_server_name("campaign", env={}), "astra_dev")
        self.assertEqual(server_module._resolve_server_name("dev", env={}), "astra_dev")

    def test_explicit_mcp_server_name_env_overrides_the_profile(self):
        name = server_module._resolve_server_name(
            "campaign", env={"ASTRA_MCP_SERVER_NAME": "astra"}
        )
        self.assertEqual(name, "astra")


class CampaignToolsGateTests(unittest.TestCase):
    def test_disabled_when_the_resolved_name_is_astra(self):
        self.assertFalse(server_module._campaign_tools_enabled_for("astra", env={}))

    def test_enabled_for_any_other_resolved_name(self):
        self.assertTrue(server_module._campaign_tools_enabled_for("astra_dev", env={}))

    def test_explicit_env_flag_overrides_the_resolved_name_either_way(self):
        self.assertTrue(
            server_module._campaign_tools_enabled_for(
                "astra", env={"ASTRA_CAMPAIGN_TOOLS": "1"}
            )
        )
        self.assertFalse(
            server_module._campaign_tools_enabled_for(
                "astra_dev", env={"ASTRA_CAMPAIGN_TOOLS": "0"}
            )
        )

    def test_promotion_override_disables_campaigns_even_without_astra_profile(self):
        # The exact safety coupling this refactor must not lose: setting only
        # ASTRA_MCP_SERVER_NAME=astra on a 2.0 checkout (the documented
        # promotion path) disables campaign tools by itself, with neither
        # ASTRA_PROFILE nor ASTRA_CAMPAIGN_TOOLS set.
        env = {"ASTRA_MCP_SERVER_NAME": "astra"}
        profile = server_module._resolve_profile(root=r"C:\Users\Nelson\Dev\ASTRA-2.0", env=env)
        name = server_module._resolve_server_name(profile, env=env)
        self.assertEqual(name, "astra")
        self.assertFalse(server_module._campaign_tools_enabled_for(name, env=env))


class EndToEndEquivalenceTests(unittest.TestCase):
    """The full default resolution, from a bare checkout root, matches the
    pre-profile behaviour for the two cases that exist on disk today."""

    def test_a_2_0_checkout_defaults_to_astra_dev_with_campaigns_on(self):
        profile = server_module._resolve_profile(root=r"C:\Users\Nelson\Dev\ASTRA-2.0", env={})
        name = server_module._resolve_server_name(profile, env={})
        self.assertEqual(name, "astra_dev")
        self.assertTrue(server_module._campaign_tools_enabled_for(name, env={}))

    def test_a_production_checkout_defaults_to_astra_with_campaigns_off(self):
        profile = server_module._resolve_profile(root=r"C:\Users\Nelson\Dev\ASTRA", env={})
        name = server_module._resolve_server_name(profile, env={})
        self.assertEqual(name, "astra")
        self.assertFalse(server_module._campaign_tools_enabled_for(name, env={}))


if __name__ == "__main__":
    unittest.main()
