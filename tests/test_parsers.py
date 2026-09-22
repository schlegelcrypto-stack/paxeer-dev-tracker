import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracker.ledger import parse_board, parse_ledger
from tracker.github_client import GithubClient
from tracker.sweep import LANE_RE

BOARD = """# Waves
- [ ] 1. Fix the evidence model
  - [x] 1.1 Define the executed-evidence ledger
  - [x] 1.2 Repair the clean-profile bootstrap
- [ ] 2. Close the authorization seams
  - [x] 2.1 Authenticate LNI activities
  - [-] 2.2 **Bind agent tokens**
  - [ ] 2.3 Run the evidence verifier
- [x] 3. Ship the release manifest
  - [ ] 3.1 Nested task under a done wave
```ignore fence content
- [ ] 9.9 Not a task, inside a fence
```
"""

LEDGER = """[gate.a]
command: make test
outcome: pass

[gate.b]
command: make qual
outcome: fail
note: tracked working-tree changes present at runner start; this is development evidence, not immutable release qualification.

[gate.c]
command: make lint
outcome: blocked
note: tracked working-tree changes present at runner start; this is development evidence, not immutable release qualification.

[observation.5.4.5402]
body: Seventeen surface rows of the canonical contract cannot reach their required beta rung even if every gate command the repository defines passes.
"""


class TestBoard(unittest.TestCase):
    def test_rollup_headers_excluded(self):
        b = parse_board(BOARD)
        # tasks are the N.M items; the three N. waves are rollup headers
        self.assertEqual(b["tasks"], {"x": 3, "-": 1, " ": 2})
        self.assertEqual(b["rollup_headers"], 3)
        self.assertEqual(b["raw"], {"x": 4, "-": 1, " ": 4})

    def test_numbering_decides_not_wording(self):
        b = parse_board("- [ ] 2.2 **Bind agent tokens**\n- [ ] 3. **Wave with bold title**\n")
        self.assertEqual(b["rollup_headers"], 1)   # '3.' is a wave even in bold
        self.assertEqual(b["tasks"][" "], 1)       # '2.2' is a task even in bold

    def test_fenced_content_ignored(self):
        b = parse_board(BOARD)
        self.assertEqual(b["raw"][" "], 4)  # the fenced 9.9 line is not counted at all

    def test_raw_equals_tasks_plus_headers(self):
        b = parse_board(BOARD)
        self.assertEqual(b["raw"][" "], b["tasks"][" "] + 2)  # two unchecked waves


class TestLedger(unittest.TestCase):
    def test_outcomes_sum_to_total(self):
        l = parse_ledger(LEDGER)
        self.assertEqual(l["gate_total"], 3)
        self.assertEqual(l["gates"], {"pass": 1, "fail": 1, "blocked": 1})
        self.assertTrue(l["arithmetic_ok"])

    def test_void_marker_detected(self):
        l = parse_ledger(LEDGER)
        self.assertFalse(l["all_gates_void"])  # one clean record in the fixture

    def test_observation_counted_and_ceiling(self):
        l = parse_ledger(LEDGER)
        self.assertEqual(l["observations"], 1)
        self.assertIn("5.4.5402", l["observation_ceiling"])

    def test_gate_mismatch_flagged(self):
        l = parse_ledger("[gate.x]\noutcome: pass\n\n[gate.y]\noutcome: weird\n")
        self.assertFalse(l["arithmetic_ok"])


class TestLanes(unittest.TestCase):
    def test_lane_extracted_from_merge_message(self):
        msg = "Merge pull request #450\n\nMerge branch 'lane/fix-guarantor-auth' from Sidiora-Labs/lane/fix-guarantor-auth"
        m = LANE_RE.search(msg)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "lane/fix-guarantor-auth")

    def test_phase_vocabulary(self):
        self.assertIn("fix", ("tn", "unify", "fix", "docs", "hosts", "naming"))


class TestRenameGuard(unittest.TestCase):
    def test_redirect_object_is_not_a_repo(self):
        # A renamed repo can surface as a redirect object with no full_name.
        self.assertFalse(GithubClient.require_repo_object({"url": "https://api.github.com/..."}))

    def test_real_repo_passes(self):
        self.assertTrue(GithubClient.require_repo_object({"name": "Paxeer-X-Network",
                                                          "full_name": "Sidiora-Labs/Paxeer-X-Network"}))


if __name__ == "__main__":
    unittest.main()
