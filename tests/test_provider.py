"""Unit tests for the tool-provider adapter — the SDK contract and its tool surface.

These drive the provider with the sweep and state seams stubbed, so no HTTP leaves
the test process. Engine parsers are covered in test_parsers.py; the fixtures here
mirror the real snapshot shapes those parsers produce.
"""

import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gideon.sdk.tool import ToolResult

import provider as provider_mod
from provider import PaxeerTrackerProvider, create_paxeer_provider
from tracker import config as watchlist

# The watchlist the stub seam resolves — remote provenance, like a healthy run.
SOURCES = watchlist.load_bundled()
SOURCES["_provenance"] = {"source": "remote", "version": SOURCES["version"],
                          "url": watchlist.CANONICAL_URL, "error": None}


def snap(sha):
    """A snapshot in the exact shape tracker.sweep.collect produces."""
    return {
        "generated_by": "paxeer-dev-tracker",
        "main": {
            "full_name": "LayerX-Network/Paxeer-X-Network",
            "renamed_from": [],
            "commits_scanned": 80,
            "head": {"sha": sha, "date": "2026-09-22T06:24:00Z", "message": "PR #387 boundary"},
            "lanes": {"tn-boundary-simulate-arena": 2},
            "lane_phases": {"unify": 10, "fix": 10},
            "unknown_phases": [],
            "force_push_suspect": False,
            "board": {
                "raw": {"x": 31, "-": 0, " ": 24},
                "tasks": {"x": 23, "-": 0, " ": 16},
                "rollup_headers": 8,
            },
            "ledger": {
                "gates": {"pass": 22, "fail": 24, "blocked": 2},
                "gate_total": 48,
                "outcome_sum": 48,
                "arithmetic_ok": True,
                "void_gates": 0,
                "all_gates_void": False,
                "observations": 1743,
                "observation_ceiling": None,
            },
            "open_prs": {"count": 38, "source": "search-api"},
        },
        "accounts": [],
        "repos": [],
        "suspect": [],
        "endpoints": [
            {"url": "https://paxeerdyor.live", "status": 200},
            {"url": "https://agentneo.app", "status": 200},
        ],
        "packages": {"LayerX-Network": {"names": ["paxctl"]}},
    }


CURRENT = snap("35ba622c")
PREVIOUS = snap("ef5d6617")


class ProviderContractTest(unittest.TestCase):
    def test_factory_returns_provider(self):
        p = create_paxeer_provider({"timeout_secs": 5})
        self.assertIsInstance(p, PaxeerTrackerProvider)
        self.assertEqual(p.name, "paxeer-dev-tracker")

    def test_list_tools_shape(self):
        tools = asyncio.run(PaxeerTrackerProvider().list_tools())
        self.assertEqual([t.name for t in tools],
                         ["paxeer_sweep", "paxeer_brief", "paxeer_sources"])
        for t in tools:
            self.assertEqual(t.provider, "paxeer-dev-tracker")
            self.assertFalse(t.requires_approval)
            self.assertEqual(t.parameters.get("type"), "object")

    def test_sweep_modes_declared(self):
        tools = asyncio.run(PaxeerTrackerProvider().list_tools())
        self.assertEqual(tools[0].parameters["properties"]["mode"]["enum"], ["quick", "full"])

    def test_info_reports_tracked_accounts(self):
        info = create_paxeer_provider().info()
        self.assertIn("paxeer_sweep", info["tools"])
        self.assertTrue(info["accounts"])


class ProviderBehaviourTest(unittest.TestCase):
    def _invoke(self, name, args, *, collected=CURRENT, latest=PREVIOUS, previous=PREVIOUS):
        """Run one tool call with the egress and state seams stubbed.

        ``latest`` is what the state seam reports as the newest saved snapshot
        when the call starts — for a sweep that is the diff base (the previous
        sweep), for a brief it is the snapshot being rendered.
        """
        fake_state = mock.Mock()
        fake_state.load_latest.return_value = latest
        fake_state.load_previous.return_value = previous
        with mock.patch.object(provider_mod, "GithubClient"), \
                mock.patch.object(provider_mod, "collect", return_value=collected) as collect, \
                mock.patch.object(provider_mod.watchlist, "load", return_value=SOURCES), \
                mock.patch.object(provider_mod, "state", fake_state):
            result = asyncio.run(PaxeerTrackerProvider().invoke(name, args))
        return result, collect, fake_state

    def test_unknown_tool_is_legible_failure(self):
        result = asyncio.run(PaxeerTrackerProvider().invoke("nope", {}))
        self.assertFalse(result.success)
        self.assertIn("Unknown tool", result.error)
        self.assertTrue(result.recovery_hints)

    def test_invalid_mode_is_legible_failure(self):
        result = asyncio.run(PaxeerTrackerProvider().invoke("paxeer_sweep", {"mode": "turbo"}))
        self.assertFalse(result.success)
        self.assertIn("quick", result.recovery_hints[0])

    def test_sweep_renders_brief_and_saves_snapshot(self):
        result, collect, fake_state = self._invoke("paxeer_sweep", {})
        self.assertTrue(result.success)
        self.assertIn("Paxeer / Sidiora dev tracker", result.output)
        self.assertIn("The main repo moved", result.output)
        self.assertIn("38", result.output)
        collect.assert_called_once()
        self.assertFalse(collect.call_args.kwargs.get("full"))
        fake_state.save.assert_called_once()

    def test_sweep_full_mode_sweeps_everything(self):
        result, collect, _ = self._invoke("paxeer_sweep", {"mode": "full"})
        self.assertTrue(result.success)
        self.assertTrue(collect.call_args.kwargs.get("full"))

    def test_sweep_passes_resolved_watchlist_to_collect(self):
        result, collect, _ = self._invoke("paxeer_sweep", {})
        self.assertTrue(result.success)
        self.assertIs(collect.call_args.kwargs.get("sources"), SOURCES)

    def test_sources_tool_reports_accounts_and_extension_path(self):
        result, _, _ = self._invoke("paxeer_sources", {})
        self.assertTrue(result.success)
        self.assertIn("Sidiora-Labs (org)", result.output)
        self.assertIn("MachineCity (user)", result.output)
        self.assertIn("sources.json", result.output)
        self.assertIn("How to extend", result.output)
        self.assertIn("[verified]", result.output)

    def test_first_sweep_reports_baseline(self):
        result, _, _ = self._invoke("paxeer_sweep", {}, latest=None, previous={})
        self.assertTrue(result.success)
        self.assertIn("Baseline established at 35ba622c", result.output)

    def test_brief_without_snapshot_is_legible_failure(self):
        result, _, _ = self._invoke("paxeer_brief", {}, latest=None, previous={})
        self.assertIsInstance(result, ToolResult)
        self.assertFalse(result.success)
        self.assertIn("paxeer_sweep", result.recovery_hints[0])

    def test_brief_reads_saved_state_without_network(self):
        result, collect, _ = self._invoke("paxeer_brief", {}, latest=CURRENT)
        self.assertTrue(result.success)
        self.assertIn("The main repo moved", result.output)
        collect.assert_not_called()

    def test_timeout_is_clamped(self):
        self.assertEqual(PaxeerTrackerProvider({"timeout_secs": 999}).info()["timeout_secs"], 120.0)
        self.assertEqual(PaxeerTrackerProvider({"timeout_secs": 0}).info()["timeout_secs"], 2.0)


if __name__ == "__main__":
    unittest.main()
