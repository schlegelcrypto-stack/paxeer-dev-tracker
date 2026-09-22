"""One sweep across the watched accounts plus the main repository.

The watchlist comes from ``sources.json`` (:mod:`tracker.config`) — fetched from
the canonical URL at run time unless the caller passes a resolved copy — so every
install sweeps the same accounts, endpoints and repos without re-installing.
"""

import base64
import re

from . import config, endpoints
from .github_client import GithubClient
from .ledger import parse_board, parse_ledger


def collect(gh, full=False, timeout=None, sources=None):
    """One sweep: the main repo and endpoints always; every tracked account and
    repo when ``full``. This is the single composition seam — the CLI and the
    tool provider both build their snapshots here."""
    if sources is None:
        sources = config.load()
    snap = {"generated_by": "paxeer-dev-tracker"}
    snap["sources"] = sources.get("_provenance",
                                 {"source": "caller", "version": sources.get("version")})
    snap["watch"] = list(sources.get("watch", []))
    snap["main"] = sweep_main(gh, sources)
    if full:
        snap.update(sweep_repos(gh, sources))
    else:
        snap.setdefault("accounts", [])
        snap.setdefault("repos", [])
        snap.setdefault("suspect", [])
    kw = {"timeout": timeout} if timeout else {}
    snap["endpoints"] = [endpoints.probe(u, **kw) for u in sources.get("endpoints", [])]
    snap["packages"] = {owner: endpoints.packages(gh, owner)
                        for owner in sources.get("packages_watch", [])}
    return snap


def sweep_repos(gh, cfg):
    """Every repo on every watched account. Org vs user endpoints are not interchangeable."""
    out = {"accounts": [], "repos": [], "suspect": []}
    excluded = set(cfg.get("excluded_owners", []))
    for login, kind in config.account_pairs(cfg):
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
            if r.get("owner", {}).get("login") in excluded:
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


def resolve_main_repo(gh, cfg=None):
    """Resolve the main repo's CURRENT name from the org listing. Never trust a zero."""
    main = (cfg or config.load_bundled())["main_repo"]
    aliases = list(main["aliases"])
    res = gh.list_org_repos(main["owner"])
    by_name = {r["name"].lower(): r for r in res.get("items", [])
               if GithubClient.require_repo_object(r)}
    for alias in aliases:
        hit = by_name.get(alias.lower())
        if hit:
            return hit, [a for a in aliases if a != hit["name"]]
    # Fuzzy fallback: renamed again since this config last shipped.
    for name, r in by_name.items():
        if "network" in name or "layerx" in name or "paxeer" in name:
            return r, aliases
    return None, aliases


def lane_re(owner):
    return re.compile(r"from\s+%s/((?:lane/)?[A-Za-z0-9._/-]+)" % re.escape(owner), re.I)


# Kept for older imports/tests: the bundled owner's pattern.
LANE_RE = lane_re(config.load_bundled()["main_repo"]["owner"])


def sweep_main(gh, cfg=None, n_commits=80):
    cfg = cfg or config.load_bundled()
    main = cfg["main_repo"]
    repo, stale_names = resolve_main_repo(gh, cfg)
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
    pat = lane_re(main["owner"])
    for c in commits:
        sha = c.get("sha", "")[:8]
        msg = (c.get("commit", {}).get("message") or "")
        when = c.get("commit", {}).get("committer", {}).get("date")
        for m in pat.finditer(msg):
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
    known = set(cfg.get("lane_phases", []))
    for lane in lanes:
        phase = lane.split("-")[0]
        phases[phase] = phases.get(phase, 0) + 1
        if phase not in known:
            unknown.append(lane)
    out["lanes"], out["lane_phases"], out["unknown_phases"] = lanes, phases, unknown

    board, _ = gh.get("/repos/%s/contents/%s" % (full, main["board_path"]))
    btext = _fetch_text(gh, board)
    out["board"] = parse_board(btext) if btext else {"error": board.get("message")}
    ledger, _ = gh.get("/repos/%s/contents/%s" % (full, main["ledger_path"]))
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
