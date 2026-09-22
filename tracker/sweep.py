"""One sweep across the eight accounts plus the main repository."""

import base64
import re

from . import accounts, endpoints
from .github_client import GithubClient
from .ledger import parse_board, parse_ledger


def collect(gh, full=False, timeout=None):
    """One sweep: the main repo and endpoints always; every tracked account and
    repo when ``full``. This is the single composition seam — the CLI and the
    tool provider both build their snapshots here."""
    snap = {"generated_by": "paxeer-dev-tracker"}
    snap["main"] = sweep_main(gh)
    if full:
        snap.update(sweep_repos(gh))
    else:
        snap.setdefault("accounts", [])
        snap.setdefault("repos", [])
        snap.setdefault("suspect", [])
    kw = {"timeout": timeout} if timeout else {}
    snap["endpoints"] = [endpoints.probe(u, **kw) for u in accounts.ENDPOINTS]
    snap["packages"] = {accounts.MAIN_REPO_OWNER: endpoints.packages(gh, accounts.MAIN_REPO_OWNER)}
    return snap


def sweep_repos(gh):
    """Every repo on every tracked account. Org vs user endpoints are not interchangeable."""
    out = {"accounts": [], "repos": [], "suspect": []}
    for login, kind in accounts.ACCOUNTS:
        res = gh.list_org_repos(login) if kind == "org" else gh.list_user_repos(login)
        items = res.get("items", [])
        row = {"account": login, "kind": kind, "count": len(items),
               "error": res.get("message") if "__error__" in res else None}
        out["accounts"].append(row)
        if not items and not row["error"]:
            # Never trust a zero. An empty org/user listing is the rename trap symptom.
            out["suspect"].append("%s returned zero repos (endpoint: /%ss/%s)"
                                  % (login, kind, kind))
        for r in items:
            if not GithubClient.require_repo_object(r):
                out["suspect"].append("redirect object instead of repo data on %s" % login)
                continue
            if r.get("owner", {}).get("login") in accounts.EXCLUDED_OWNERS:
                continue
            out["repos"].append({
                "full_name": r["full_name"],
                "owner": login,
                "name": r["name"],
                "private": bool(r.get("private")),
                "language": r.get("language"),
                "license": ((r.get("license") or {}).get("spdx_id") or "none"),
                "pushed_at": r.get("pushed_at"),
                "default_branch": r.get("default_branch"),
                "stars": r.get("stargazers_count", 0),
                "forks": r.get("forks_count", 0),
                "archived": bool(r.get("archived")),
            })
    return out


def resolve_main_repo(gh):
    """Resolve the main repo's CURRENT name from the org listing. Never trust a zero."""
    res = gh.list_org_repos(accounts.MAIN_REPO_OWNER)
    by_name = {r["name"].lower(): r for r in res.get("items", [])
               if GithubClient.require_repo_object(r)}
    for alias in accounts.MAIN_REPO_ALIASES:
        hit = by_name.get(alias.lower())
        if hit:
            return hit, [a for a in accounts.MAIN_REPO_ALIASES if a != hit["name"]]
    # Fuzzy fallback: renamed again since this code last shipped.
    for name, r in by_name.items():
        if "network" in name or "layerx" in name or "paxeer" in name:
            return r, list(accounts.MAIN_REPO_ALIASES)
    return None, list(accounts.MAIN_REPO_ALIASES)


LANE_RE = re.compile(r"from\s+%s/((?:lane/)?[A-Za-z0-9._/-]+)" % re.escape(accounts.MAIN_REPO_OWNER), re.I)


def sweep_main(gh, n_commits=80):
    repo, stale_names = resolve_main_repo(gh)
    if not repo:
        return {"error": "main repo not found in org listing", "stale_names": stale_names}
    full = repo["full_name"]
    out = {"full_name": full, "renamed_from": stale_names, "head": None, "lanes": {},
           "lane_phases": {}, "unknown_phases": [], "force_push_suspect": False}

    commits, _status = gh.get("/repos/%s/commits" % full, {"per_page": n_commits})
    if isinstance(commits, dict):
        out["error"] = commits.get("message")
        return out
    lanes = {}
    seen = set()
    for c in commits:
        sha = c.get("sha", "")[:8]
        msg = (c.get("commit", {}).get("message") or "")
        when = c.get("commit", {}).get("committer", {}).get("date")
        for m in LANE_RE.finditer(msg):
            lane = m.group(1).split("/")[-1] if m.group(1).startswith("lane/") else m.group(1)
            lanes[lane] = lanes.get(lane, 0) + 1
        key = (msg.splitlines()[0] if msg else "", when)
        if key in seen:
            out["force_push_suspect"] = True
        seen.add(key)
    if commits:
        out["commits_scanned"] = len(commits)
        out["head"] = {
            "sha": commits[0]["sha"][:8],
            "date": commits[0].get("commit", {}).get("committer", {}).get("date"),
            "message": (commits[0].get("commit", {}).get("message") or "").splitlines()[0],
        }
    phases = {}
    unknown = []
    for lane in lanes:
        phase = lane.split("-")[0]
        phases[phase] = phases.get(phase, 0) + 1
        if phase not in accounts.KNOWN_LANE_PHASES:
            unknown.append(lane)
    out["lanes"], out["lane_phases"], out["unknown_phases"] = lanes, phases, unknown

    board, _ = gh.get("/repos/%s/contents/%s" % (full, accounts.BOARD_PATH))
    btext = _fetch_text(gh, board)
    out["board"] = parse_board(btext) if btext else {"error": board.get("message")}
    ledger, _ = gh.get("/repos/%s/contents/%s" % (full, accounts.LEDGER_PATH))
    ltext = _fetch_text(gh, ledger)
    out["ledger"] = parse_ledger(ltext) if ltext else {"error": ledger.get("message")}
    out["open_prs"] = count_open_prs(gh, full)
    return out


def count_open_prs(gh, full):
    """The rendered /pulls page caps at 25. Counts come from the search API."""
    data, status = gh.get("/search/issues", {"q": "repo:%s is:pr is:open" % full, "per_page": 1})
    if isinstance(data, dict) and "total_count" in data:
        return {"count": data["total_count"], "source": "search-api"}
    return {"count": None, "source": "unavailable",
            "note": (data.get("message") if isinstance(data, dict) else "unknown"),
            "hint": "search API is rate-limited without a token; the /pulls page caps at 25"}


def _fetch_text(gh, payload):
    """Contents API first; stream download_url when the file exceeds the 1 MB cap."""
    if not isinstance(payload, dict):
        return None
    if payload.get("content"):
        raw = re.sub(r"\s+", "", str(payload.get("content", "")))
        try:
            return base64.b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "replace")
        except Exception:
            return None
    url = payload.get("download_url")
    return gh.get_raw(url) if url else None
