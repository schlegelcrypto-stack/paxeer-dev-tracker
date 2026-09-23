"""Unit tests for the watchlist loader — the contract that keeps every install
on the same sources.json.

No HTTP leaves this file: the fetcher is injected. State is sandboxed to a temp
dir so the cache tests cannot pollute real snapshots.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracker import config
from tracker import brief as brief_mod


def fetcher_of(payload):
    """A fetcher seam returning this JSON payload as bytes."""
    raw = json.dumps(payload).encode()
    return lambda url: raw


class BundledTest(unittest.TestCase):
    def test_bundled_is_valid_and_tracks_eight_accounts(self):
        cfg = config.load_bundled()
        self.assertEqual(len(config.account_pairs(cfg)), 8)
        self.assertEqual(dict(config.account_pairs(cfg))["Sidiora-Labs"], "org")
        self.assertIn("Paxeer-X-Network", cfg["main_repo"]["aliases"])

    def test_account_pairs_pair_up(self):
        pairs = config.account_pairs(config.load_bundled())
        self.assertTrue(all(isinstance(k, str) and v in ("org", "user") for k, v in pairs))


class ResolutionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="paxeer-config-test-")
        self._old = os.environ.get("PAXEER_STATE_DIR")
        os.environ["PAXEER_STATE_DIR"] = self.tmp

    def tearDown(self):
        if self._old is None:
            os.environ.pop("PAXEER_STATE_DIR", None)
        else:
            os.environ["PAXEER_STATE_DIR"] = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _payload(self, **over):
        cfg = json.loads(json.dumps(config.load_bundled()))
        cfg.update(over)
        return cfg

    def test_remote_wins_and_is_stamped_verified(self):
        cfg = config.load(fetcher=fetcher_of(self._payload(version=7)))
        self.assertEqual(cfg["_provenance"]["source"], "remote")
        self.assertEqual(cfg["_provenance"]["version"], 7)
        self.assertIsNone(cfg["_provenance"]["error"])

    def test_remote_fetch_failure_falls_back_to_bundled(self):
        def dead(url):
            raise OSError("network down")
        cfg = config.load(fetcher=dead)
        self.assertEqual(cfg["_provenance"]["source"], "bundled")
        self.assertIn("remote:", cfg["_provenance"]["error"])
        self.assertEqual(len(config.account_pairs(cfg)), 8)

    def test_cache_survives_a_later_outage(self):
        config.load(fetcher=fetcher_of(self._payload(version=3)))
        def dead(url):
            raise OSError("network down")
        cfg = config.load(fetcher=dead)
        self.assertEqual(cfg["_provenance"]["source"], "cache")
        self.assertEqual(cfg["_provenance"]["version"], 3)

    def test_local_mode_never_fetches(self):
        def must_not_fetch(url):
            raise AssertionError("local mode must not fetch")
        cfg = config.load(mode="local", fetcher=must_not_fetch)
        self.assertEqual(cfg["_provenance"]["source"], "bundled")

    def test_an_added_account_reaches_the_sweep_shape(self):
        """The user story: one JSON entry adds a developer, everywhere."""
        payload = self._payload(version=2)
        payload["accounts"].append({"login": "new-developer", "kind": "user"})
        cfg = config.load(fetcher=fetcher_of(payload))
        self.assertIn(("new-developer", "user"), config.account_pairs(cfg))

    def test_brief_stamps_which_sources_produced_it(self):
        cfg = config.load(fetcher=fetcher_of(self._payload(version=9)))
        snap = {"generated_by": "paxeer-dev-tracker", "main": {},
                "sources": cfg["_provenance"], "watch": [], "endpoints": []}
        out = brief_mod.render_brief(snap)
        self.assertIn("Sources: watchlist v9", out)
        self.assertIn("[verified]", out)
        cfg2 = config.load(mode="local", fetcher=fetcher_of(self._payload()))
        snap["sources"] = cfg2["_provenance"]
        out2 = brief_mod.render_brief(snap)
        self.assertIn("bundled fallback", out2)
        self.assertIn("[reported]", out2)


class ValidationTest(unittest.TestCase):
    """Remote config is data: it may widen the watchlist, never smuggle anything."""

    def _rejects(self, cfg):
        with self.assertRaises(config.ConfigError):
            config.validate(cfg)

    def _accepts(self, cfg):
        self.assertIs(config.validate(cfg), cfg)

    def base(self):
        return json.loads(json.dumps(config.load_bundled()))

    # Fixture values are deliberately benign: this bundle ships to other users, and a
    # supply-chain scanner cannot tell a test fixture from an attack payload. The
    # property under test is that an unknown KEY is rejected whatever its value.

    def test_unknown_top_level_key_rejected(self):
        cfg = self.base()
        cfg["evil_payload"] = "harmless"
        self._rejects(cfg)

    def test_account_row_extra_key_rejected(self):
        cfg = self.base()
        cfg["accounts"][0]["command"] = "harmless"
        self._rejects(cfg)

    def test_bad_kind_rejected(self):
        cfg = self.base()
        cfg["accounts"][0]["kind"] = "organization"
        self._rejects(cfg)

    def test_bad_endpoint_scheme_rejected(self):
        cfg = self.base()
        cfg["endpoints"] = ["file:///etc/passwd"]
        self._rejects(cfg)

    def test_missing_required_key_rejected(self):
        cfg = self.base()
        del cfg["main_repo"]
        self._rejects(cfg)

    def test_bad_version_rejected(self):
        cfg = self.base()
        cfg["version"] = "many"
        self._rejects(cfg)

    def test_good_change_accepted(self):
        cfg = self.base()
        cfg["version"] = 2
        cfg["accounts"].append({"login": "someone-new", "kind": "org"})
        cfg["endpoints"].append("https://new-site.example")
        self._accepts(cfg)


if __name__ == "__main__":
    unittest.main()
