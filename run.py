#!/usr/bin/env python3
"""Paxeer dev tracker CLI.

  python run.py pull      quick sweep: main repo signals + endpoints
  python run.py full      every tracked account and repo
  python run.py brief     render the daily brief from saved snapshots
  python run.py all       full sweep + brief (what the daily run executes)

Reads GITHUB_TOKEN from the environment if present. Never writes a secret to disk.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tracker import state
from tracker.brief import render_brief
from tracker.github_client import GithubClient
from tracker.sweep import collect


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["pull", "full", "brief", "all"])
    ap.add_argument("--out", help="write the brief to this path")
    args = ap.parse_args()

    if args.command == "brief":
        brief = render_brief(state.load_latest(), state.load_previous())
        _emit(brief, args.out)
        return

    gh = GithubClient()
    print("token: %s" % ("present (authenticated rate limit)" if gh.token
                         else "absent (anonymous, 60 req/hr)"))
    snap = collect(gh, full=(args.command in ("full", "all")))
    prev = state.load_latest()
    path = state.save(snap, label=args.command)
    print("snapshot: %s" % path)
    src = snap.get("sources", {})
    print("sources: watchlist v%s (%s)%s"
          % (src.get("version"), src.get("source"),
             (" — " + src["error"]) if src.get("error") else ""))

    if args.command == "all":
        brief = render_brief(snap, prev or state.load_previous())
        _emit(brief, args.out)
    else:
        m = snap.get("main", {})
        print("main repo: %s  head=%s  prs=%s"
              % (m.get("full_name"), (m.get("head") or {}).get("sha"),
                 (m.get("open_prs") or {}).get("count")))
        for s in snap.get("suspect", []):
            print("SUSPECT: %s" % s)


def _emit(brief, out):
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
        with open(out, "w") as f:
            f.write(brief)
        print("brief: %s" % out)
    print(brief)


if __name__ == "__main__":
    main()
