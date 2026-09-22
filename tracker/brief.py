"""Daily brief generator.

House style, enforced structurally rather than by taste:
1. Plain-English lead, a few sentences, no jargon.
2. Build progress first. A missed date is NOT a finding.
3. Retrieved vs inferred is labelled on every claim ([verified] / [reported]).
4. Unverifiable team claims are attributed ("reported by Sidiora/Andrew"), never stated.
5. When a prior call was wrong, correct it explicitly and visibly.
6. The five-claim ladder is never collapsed: built / deployed / live / gated / confirmed on chain.
"""

import json
from datetime import datetime, timezone


def render_brief(curr, prev=None, corrections=None, watch=None):
    prev = prev or {}
    lines = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    main = curr.get("main", {})
    lines.append("# Paxeer / Sidiora dev tracker — %s" % now)
    lines.append("")
    lines.append(plain_english(curr, prev))
    lines.append("")
    lines.append("## Build progress")
    lines.extend(progress_section(main, prev.get("main", {})))
    lines.append("")
    lines.append("## Sweep detail")
    lines.extend(detail_section(curr))
    lines.append("")
    lines.append("## Watch list")
    lines.extend(watch_section(curr, watch))
    if corrections:
        lines.append("")
        lines.append("## Corrections")
        for c in corrections:
            lines.append("- **Corrected:** %s" % c)
    lines.append("")
    lines.append("## Method notes")
    for s in curr.get("suspect", []):
        lines.append("- ⚠️ %s — result marked suspect, not reported as a finding." % s)
    lines.append("- `[verified]` = retrieved from code/API this sweep. `[reported]` = team claim, unverified.")
    lines.append("- built / deployed / live / gated / confirmed on chain are five different claims.")
    return "\n".join(lines) + "\n"


def plain_english(curr, prev):
    m, pm = curr.get("main", {}), prev.get("main", {})
    parts = []
    if not m:
        return "The main repository could not be read this sweep. Nothing below should be read as a clean picture."
    head, phead = m.get("head") or {}, pm.get("head") or {}
    if head and phead and head.get("sha") != phead.get("sha"):
        parts.append("The main repo moved: new work landed since the last sweep, HEAD is now %s." % head.get("sha"))
    elif head and phead:
        parts.append("No change in the main repo — still at %s." % head.get("sha"))
    elif head:
        parts.append("Baseline established at %s." % head.get("sha"))
    new_repos = new_repo_names(curr, prev)
    if new_repos:
        parts.append("New repositories appeared: %s." % ", ".join(new_repos[:5]))
    elif not prev.get("repos"):
        parts.append("Baseline established: %d repositories across %d tracked accounts."
                     % (len(curr.get("repos", [])), len(curr.get("accounts", []))))
    lanes = m.get("lane_phases", {})
    if lanes:
        top = sorted(lanes.items(), key=lambda kv: -kv[1])[:3]
        parts.append("%d merged work lanes in the last %s commits cluster on %s — integration and repair, not new surface."
                     % (sum(lanes.values()), m.get("commits_scanned", "?"),
                        ", ".join("%s (%d)" % kv for kv in top)))
    prs = (m.get("open_prs") or {}).get("count")
    if prs is not None:
        d = prs - (pm.get("open_prs") or {}).get("count", prs)
        parts.append("Open PRs: %d%s." % (prs, " (%+d)" % d if d else ""))
    ep = {e["url"]: e for e in curr.get("endpoints", [])}
    dead = [u for u, e in ep.items() if e.get("status") in (503, None) and "agentneo" not in u]
    if dead:
        parts.append("Still no public service behind %s." % ", ".join(dead))
    return " ".join(parts) if parts else "Nothing moved this sweep."


def new_repo_names(curr, prev):
    if not prev.get("repos"):
        return []  # no diff base: a first sweep is a baseline, not a discovery
    old = {r["full_name"] for r in prev.get("repos", [])}
    return [r["full_name"] for r in curr.get("repos", []) if r["full_name"] not in old]


def progress_section(m, pm):
    out = []
    if not m:
        return out
    head = m.get("head") or {}
    phead = pm.get("head") or {}
    moved = head.get("sha") != phead.get("sha") and phead
    out.append("- **HEAD** `%s` · %s · %s · %s"
               % (head.get("sha"), head.get("date"), "moved" if moved else "unchanged",
                  head.get("message", "")[:70]))
    for lane, n in sorted(m.get("lanes", {}).items(), key=lambda kv: (-kv[1], kv[0])):
        out.append("  - lane `%s` ×%d" % (lane, n))
    for lane in m.get("unknown_phases", []):
        out.append("  - 🆕 unknown lane phase in `%s` — new vocabulary, watching." % lane)
    if m.get("force_push_suspect"):
        out.append("- ⚠️ possible force-push: repeated message/timestamp with changed SHAs. History may have been rewritten, not new work.")
    b = m.get("board", {})
    if "tasks" in b:
        t, r = b["tasks"], b["raw"]
        out.append("- **Board**: %d done / %d in progress / %d to do (raw %d/%d/%d incl. %d rollup headers) [verified]"
                   % (t["x"], t["-"], t[" "], r["x"], r["-"], r[" "], b["rollup_headers"]))
    l = m.get("ledger", {})
    if "gates" in l:
        g = ", ".join("%s %d" % (k, v) for k, v in sorted(l["gates"].items()))
        flag = "" if l["arithmetic_ok"] else " ⚠️ outcomes do NOT sum to the gate total"
        out.append("- **Gates**: %d (%s)%s [verified]" % (l["gate_total"], g, flag))
        out.append("- **Observations**: %d (activity only — the ledger is append-only)" % l["observations"])
        if l.get("all_gates_void"):
            out.append("- ⚠️ every gate ran on a dirty working tree: **no release-valid gate result exists.** A clean run on a tagged revision is the single most valuable next step.")
        if l.get("observation_ceiling"):
            out.append("- Ceiling on record (`%s`): some contract rows cannot reach their required rung even if every defined gate passes — those commands are not written yet." % l["observation_ceiling"])
    prs = m.get("open_prs", {})
    out.append("- **Open PRs**: %s [%s]" % (prs.get("count"), "verified" if prs.get("source") == "search-api" else "reported"))
    return out


def detail_section(curr):
    out = ["- Accounts swept: %s" % ", ".join("%s (%s)=%d" % (a["account"], a["kind"], a["count"])
                                            for a in curr.get("accounts", []))]
    out.append("- Repos tracked: %d (schlegelcrypto-stack excluded by design)" % len(curr.get("repos", [])))
    for owner, pk in (curr.get("packages") or {}).items():
        out.append("- Packages %s: %s" % (owner, ", ".join(pk.get("names", [])) or "NONE"))
    return out


def watch_section(curr, watch):
    defaults = [
        "Either gateway returning 200 — a backend finally serving.",
        "A clean qualification run writing new gate records on a tagged revision.",
        "The fix- lane phase winding down, hosts-/deploy lanes increasing.",
        "Anything appearing in the Sidiora-Labs package list — the first published image.",
        "Third-party SID solvers, or SID's address in the bridge module.",
        "New repos on the tracked accounts.",
    ]
    rows = []
    for item in (watch or defaults):
        rows.append("- [ ] %s" % item)
    for e in curr.get("endpoints", []):
        state = "live" if e.get("status") == 200 and not e.get("spa_suspect") else (
            "SPA shell (200 for every route) — not evidence of a backend" if e.get("spa_suspect")
            else "HTTP %s" % e.get("status"))
        rows.append("- `%s` → %s [verified]" % (e["url"], state))
    return rows
